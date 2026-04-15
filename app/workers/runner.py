from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.db.repository import JobRepository
from app.models.schemas import ArtifactFormat, ArtifactPaths, JobStatus, ProcessingMetrics, Segment, TranscriptResult
from app.services.asr_client import ASRClient
from app.services.formatting import write_result_artifacts
from app.services.media import AudioChunk, extract_audio, split_audio_with_overlap
from app.services.storage import StorageService


class JobWorker:
    def __init__(
        self,
        *,
        repository: JobRepository,
        storage: StorageService,
        asr_client: ASRClient,
        ffmpeg_path: str,
        poll_interval_seconds: float,
    ):
        self.repository = repository
        self.storage = storage
        self.asr_client = asr_client
        self.ffmpeg_path = ffmpeg_path
        self.poll_interval_seconds = poll_interval_seconds
        settings = get_settings()
        self.asr_max_file_size_bytes = settings.asr_max_file_size_mb * 1024 * 1024
        self.chunk_duration_seconds = settings.chunk_duration_seconds
        self.chunk_overlap_seconds = settings.chunk_overlap_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        self._stop = asyncio.Event()

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            job = self.repository.get_next_queued_job()
            if not job:
                await asyncio.sleep(self.poll_interval_seconds)
                continue
            await self._process_job(job.job_id)

    async def _process_job(self, job_id: str) -> None:
        record = self.repository.get_job(job_id)
        if not record:
            return
        processing_started_at = datetime.now(UTC)
        self.repository.update_status(job_id, JobStatus.processing)
        try:
            input_path = Path(record.stored_input_path)
            transcription_input = input_path
            if record.source_type == "video":
                transcription_input = self.storage.create_job_dir(job_id) / "extracted.wav"
                extract_audio(
                    ffmpeg_path=self.ffmpeg_path,
                    input_path=input_path,
                    output_path=transcription_input,
                )
            result = await self._transcribe_with_chunking(
                job_id=job_id,
                source_file=record.source_file,
                source_type=record.source_type,
                language=record.language,
                transcription_input=transcription_input,
            )
            completed_at = datetime.now(UTC)
            result.metrics = ProcessingMetrics(
                queued_seconds=round((processing_started_at - record.created_at).total_seconds(), 3),
                processing_seconds=round((completed_at - processing_started_at).total_seconds(), 3),
                total_seconds=round((completed_at - record.created_at).total_seconds(), 3),
                chunk_count=result.metrics.chunk_count,
            )
            formats = {ArtifactFormat(item) for item in record.output_formats}
            json_path = self.storage.artifact_path(job_id, ArtifactFormat.json)
            srt_path = self.storage.artifact_path(job_id, ArtifactFormat.srt) if ArtifactFormat.srt in formats else None
            txt_path = self.storage.artifact_path(job_id, ArtifactFormat.txt) if ArtifactFormat.txt in formats else None
            result.artifacts = ArtifactPaths(
                json_path=str(json_path),
                srt_path=str(srt_path) if srt_path else None,
                txt_path=str(txt_path) if txt_path else None,
            )
            write_result_artifacts(result, json_path=json_path, srt_path=srt_path, txt_path=txt_path)
            self.repository.save_result(job_id, result)
        except Exception as exc:
            self.repository.update_status(job_id, JobStatus.failed, error=str(exc))

    async def _transcribe_with_chunking(
        self,
        *,
        job_id: str,
        source_file: str,
        source_type: str,
        language: str | None,
        transcription_input: Path,
    ) -> TranscriptResult:
        if transcription_input.stat().st_size <= self.asr_max_file_size_bytes:
            raw = await self.asr_client.transcribe(file_path=transcription_input, language=language)
            result = self.asr_client.normalize_result(
                raw_response=raw,
                job_id=job_id,
                source_file=source_file,
                source_type=source_type,
                requested_language=language,
            )
            result.metrics.chunk_count = 1
            return result

        chunk_dir = self.storage.create_job_dir(job_id) / "chunks"
        chunks = split_audio_with_overlap(
            ffmpeg_path=self.ffmpeg_path,
            input_path=transcription_input,
            output_dir=chunk_dir,
            chunk_duration_seconds=self.chunk_duration_seconds,
            overlap_seconds=self.chunk_overlap_seconds,
        )
        chunk_results: list[tuple[AudioChunk, TranscriptResult]] = []
        for chunk in chunks:
            raw = await self.asr_client.transcribe(file_path=chunk.path, language=language)
            chunk_result = self.asr_client.normalize_result(
                raw_response=raw,
                job_id=job_id,
                source_file=source_file,
                source_type=source_type,
                requested_language=language,
            )
            chunk_results.append((chunk, chunk_result))
        return self._merge_chunk_results(
            job_id=job_id,
            source_file=source_file,
            source_type=source_type,
            language=language,
            chunk_results=chunk_results,
            chunk_count=len(chunks),
        )

    def _merge_chunk_results(
        self,
        *,
        job_id: str,
        source_file: str,
        source_type: str,
        language: str | None,
        chunk_results: list[tuple[AudioChunk, TranscriptResult]],
        chunk_count: int,
    ) -> TranscriptResult:
        merged_segments: list[Segment] = []
        merged_text = ""
        segment_index = 1
        max_end_ms = 0
        detected_language = language

        for chunk, result in chunk_results:
            detected_language = detected_language or result.language
            trimmed_text = self._trim_overlap_text(
                text=result.full_text,
                previous_text=merged_text,
                trim_lead=chunk.trim_lead_seconds > 0,
            )
            if trimmed_text:
                merged_text = f"{merged_text} {trimmed_text}".strip()

            if result.segments:
                for segment in result.segments:
                    start_ms = int(chunk.start_seconds * 1000) + segment.start_ms
                    end_ms = int(chunk.start_seconds * 1000) + segment.end_ms
                    lead_cutoff_ms = int((chunk.start_seconds + chunk.trim_lead_seconds) * 1000)
                    tail_cutoff_ms = int((chunk.end_seconds - chunk.trim_tail_seconds) * 1000)
                    if chunk.trim_lead_seconds and end_ms <= lead_cutoff_ms:
                        continue
                    if chunk.trim_tail_seconds and start_ms >= tail_cutoff_ms:
                        continue
                    merged_segments.append(
                        Segment(
                            index=segment_index,
                            start_ms=max(start_ms, lead_cutoff_ms) if chunk.trim_lead_seconds else start_ms,
                            end_ms=min(end_ms, tail_cutoff_ms) if chunk.trim_tail_seconds else end_ms,
                            text=segment.text,
                        )
                    )
                    max_end_ms = max(max_end_ms, merged_segments[-1].end_ms)
                    segment_index += 1
            elif trimmed_text:
                start_ms = int((chunk.start_seconds + chunk.trim_lead_seconds) * 1000)
                end_ms = int((chunk.end_seconds - chunk.trim_tail_seconds) * 1000)
                merged_segments.append(
                    Segment(index=segment_index, start_ms=start_ms, end_ms=end_ms, text=trimmed_text)
                )
                max_end_ms = max(max_end_ms, end_ms)
                segment_index += 1

        return TranscriptResult(
            job_id=job_id,
            status=JobStatus.succeeded,
            source_file=source_file,
            source_type=source_type,
            language=detected_language,
            duration_seconds=(max_end_ms / 1000.0) if max_end_ms else None,
            full_text=merged_text,
            segments=merged_segments,
            metrics=ProcessingMetrics(chunk_count=chunk_count),
        )

    def _trim_overlap_text(self, *, text: str, previous_text: str, trim_lead: bool) -> str:
        normalized = " ".join(text.split())
        if not normalized:
            return ""
        if not trim_lead or not previous_text:
            return normalized
        prev_words = previous_text.split()
        curr_words = normalized.split()
        max_overlap = min(len(prev_words), len(curr_words), 25)
        for overlap in range(max_overlap, 0, -1):
            if prev_words[-overlap:] == curr_words[:overlap]:
                return " ".join(curr_words[overlap:]).strip()
        return normalized
