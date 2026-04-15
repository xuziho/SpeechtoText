from __future__ import annotations

from pathlib import Path

from app.models.schemas import Segment, TranscriptResult


def format_timestamp(milliseconds: int) -> str:
    total_ms = max(milliseconds, 0)
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def segments_to_srt(segments: list[Segment]) -> str:
    blocks: list[str] = []
    for segment in segments:
        blocks.append(
            "\n".join(
                [
                    str(segment.index),
                    f"{format_timestamp(segment.start_ms)} --> {format_timestamp(segment.end_ms)}",
                    segment.text.strip(),
                ]
            )
        )
    return "\n\n".join(blocks).strip() + ("\n" if blocks else "")


def result_to_txt(result: TranscriptResult) -> str:
    return result.full_text.strip() + ("\n" if result.full_text else "")


def write_result_artifacts(
    result: TranscriptResult,
    *,
    json_path: Path,
    srt_path: Path | None,
    txt_path: Path | None,
) -> None:
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    if srt_path:
        srt_path.write_text(segments_to_srt(result.segments), encoding="utf-8")
    if txt_path:
        txt_path.write_text(result_to_txt(result), encoding="utf-8")
