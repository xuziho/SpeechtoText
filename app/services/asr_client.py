from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import httpx

from app.models.schemas import Segment, TranscriptResult

_ASR_TEXT_TAG = "<asr_text>"
_LANG_PREFIX = "language "
_INLINE_TAG_PATTERN = re.compile(r"language\s+[A-Za-z]+\s*<asr_text>", re.IGNORECASE)


class ASRClient:
    def __init__(self, *, base_url: str, api_key: str | None, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._resolved_model_id: str | None = None

    async def healthcheck(self) -> bool:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{self.base_url}/models", headers=self._headers())
                return response.status_code < 500
            except httpx.HTTPError:
                return False

    async def transcribe(self, *, file_path: Path, language: str | None) -> dict[str, Any]:
        model_candidates = [await self._get_model_id()]
        response_formats = ["verbose_json", "json"]
        for model_id in model_candidates:
            for response_format in response_formats:
                try:
                    return await self._post_transcription(
                        file_path=file_path,
                        language=language,
                        model_id=model_id,
                        response_format=response_format,
                    )
                except httpx.HTTPStatusError as exc:
                    error_text = exc.response.text
                    if exc.response.status_code == 404 and "does not exist" in error_text and model_id == model_candidates[0]:
                        discovered = await self._discover_model_id()
                        self._resolved_model_id = discovered
                        if discovered not in model_candidates:
                            model_candidates.append(discovered)
                        break
                    if exc.response.status_code == 400 and "do not support verbose_json" in error_text and response_format == "verbose_json":
                        continue
                    raise
        raise RuntimeError("Unable to transcribe audio with the configured upstream model.")

    def normalize_result(
        self,
        *,
        raw_response: dict[str, Any],
        job_id: str,
        source_file: str,
        source_type: str,
        requested_language: str | None,
    ) -> TranscriptResult:
        segments_raw = raw_response.get("segments") or raw_response.get("chunks") or []
        segments: list[Segment] = []
        for idx, item in enumerate(segments_raw, start=1):
            start = item.get("start") or item.get("start_time") or item.get("from") or 0
            end = item.get("end") or item.get("end_time") or item.get("to") or start
            _, cleaned_segment_text = _parse_asr_output(item.get("text") or "", user_language=requested_language)
            segments.append(
                Segment(
                    index=idx,
                    start_ms=_seconds_to_ms(start),
                    end_ms=_seconds_to_ms(end),
                    text=cleaned_segment_text,
                )
            )
        language_from_text, full_text = _parse_asr_output(raw_response.get("text") or "", user_language=requested_language)
        if not full_text and segments:
            full_text = " ".join(segment.text for segment in segments).strip()
        full_text = _strip_inline_asr_tags(full_text)
        cleaned_segments = []
        for segment in segments:
            cleaned_segments.append(
                Segment(
                    index=segment.index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=_strip_inline_asr_tags(segment.text),
                )
            )
        duration_seconds = raw_response.get("duration") or raw_response.get("audio_duration")
        language = raw_response.get("language") or language_from_text or requested_language
        return TranscriptResult(
            job_id=job_id,
            status="succeeded",
            source_file=source_file,
            source_type=source_type,
            language=language,
            duration_seconds=float(duration_seconds) if duration_seconds is not None else None,
            full_text=full_text,
            segments=cleaned_segments,
        )

    def _headers(self) -> dict[str, str]:
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def _post_transcription(
        self,
        *,
        file_path: Path,
        language: str | None,
        model_id: str,
        response_format: str,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "model": model_id,
            "response_format": response_format,
        }
        if response_format == "verbose_json":
            data["timestamp_granularities[]"] = "segment"
        if language:
            data["language"] = language
        async with httpx.AsyncClient(timeout=None) as client:
            with file_path.open("rb") as handle:
                files = {"file": (file_path.name, handle, "application/octet-stream")}
                response = await client.post(
                    f"{self.base_url}/audio/transcriptions",
                    headers=self._headers(),
                    data=data,
                    files=files,
                )
            response.raise_for_status()
            return response.json()

    async def _get_model_id(self) -> str:
        if self._resolved_model_id:
            return self._resolved_model_id
        self._resolved_model_id = self.model
        return self._resolved_model_id

    async def _discover_model_id(self) -> str:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self.base_url}/models", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") or []
        if not data:
            raise RuntimeError("No upstream ASR model was returned by /models.")
        return data[0]["id"]


def _seconds_to_ms(value: Any) -> int:
    try:
        return int(float(value) * 1000)
    except (TypeError, ValueError):
        return 0


def _parse_asr_output(raw: str, user_language: str | None = None) -> tuple[str, str]:
    if raw is None:
        return "", ""
    text = str(raw).strip()
    if not text:
        return "", ""
    if user_language:
        return user_language, text
    if not text.lower().startswith(_LANG_PREFIX):
        return "", _strip_inline_asr_tags(text)
    if _ASR_TEXT_TAG not in text:
        return "", text

    meta_part, text_part = text.split(_ASR_TEXT_TAG, 1)
    meta_lower = meta_part.lower()
    if "language none" in meta_lower:
        cleaned_text = text_part.strip()
        return "", cleaned_text

    language = ""
    for line in meta_part.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if lowered.startswith(_LANG_PREFIX):
            value = candidate[len(_LANG_PREFIX):].strip()
            if value:
                language = _normalize_language_name(value)
            break
    return language, text_part.strip()


def _normalize_language_name(language: str) -> str:
    value = str(language).strip()
    if not value:
        return ""
    return value[:1].upper() + value[1:].lower()


def _strip_inline_asr_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = _INLINE_TAG_PATTERN.sub("", text)
    return " ".join(cleaned.split())
