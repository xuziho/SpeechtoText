from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus", ".webm"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".m4v", ".ts"}


def detect_source_type(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    raise ValueError(f"Unsupported file type: {suffix or '<none>'}")


def extract_audio(*, ffmpeg_path: str, input_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg failed to extract audio")
    return output_path


@dataclass
class AudioChunk:
    index: int
    start_seconds: float
    end_seconds: float
    path: Path
    trim_lead_seconds: float
    trim_tail_seconds: float


def get_media_duration(*, ffmpeg_path: str, input_path: Path) -> float:
    ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe") if "ffmpeg" in ffmpeg_path else "ffprobe"
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(input_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffprobe failed to inspect media duration")
    payload = json.loads(completed.stdout or "{}")
    duration = ((payload.get("format") or {}).get("duration"))
    if duration is None:
        raise RuntimeError("Media duration was not returned by ffprobe")
    return float(duration)


def split_audio_with_overlap(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_dir: Path,
    chunk_duration_seconds: int,
    overlap_seconds: int,
) -> list[AudioChunk]:
    duration = get_media_duration(ffmpeg_path=ffmpeg_path, input_path=input_path)
    if duration <= chunk_duration_seconds:
        return [
            AudioChunk(
                index=1,
                start_seconds=0.0,
                end_seconds=duration,
                path=input_path,
                trim_lead_seconds=0.0,
                trim_tail_seconds=0.0,
            )
        ]

    output_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[AudioChunk] = []
    step = max(chunk_duration_seconds - overlap_seconds, 1)
    start = 0.0
    index = 1
    while start < duration:
        end = min(start + chunk_duration_seconds, duration)
        chunk_path = output_dir / f"chunk-{index:04d}.wav"
        _extract_audio_window(
            ffmpeg_path=ffmpeg_path,
            input_path=input_path,
            output_path=chunk_path,
            start_seconds=start,
            duration_seconds=end - start,
        )
        trim_lead = 0.0 if index == 1 else float(overlap_seconds)
        trim_tail = 0.0 if end >= duration else float(overlap_seconds)
        chunks.append(
            AudioChunk(
                index=index,
                start_seconds=start,
                end_seconds=end,
                path=chunk_path,
                trim_lead_seconds=trim_lead,
                trim_tail_seconds=trim_tail,
            )
        )
        if end >= duration:
            break
        start += step
        index += 1
    return chunks


def _extract_audio_window(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
) -> Path:
    command = [
        ffmpeg_path,
        "-y",
        "-ss",
        str(start_seconds),
        "-t",
        str(duration_seconds),
        "-i",
        str(input_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "ffmpeg failed to split audio chunk")
    return output_path
