from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    succeeded = "succeeded"
    failed = "failed"


class SourceType(str, Enum):
    audio = "audio"
    video = "video"
    auto = "auto"


class ArtifactFormat(str, Enum):
    json = "json"
    srt = "srt"
    txt = "txt"


class Segment(BaseModel):
    index: int
    start_ms: int
    end_ms: int
    text: str


class ArtifactPaths(BaseModel):
    json_path: str | None = None
    srt_path: str | None = None
    txt_path: str | None = None


class ProcessingMetrics(BaseModel):
    queued_seconds: float | None = None
    processing_seconds: float | None = None
    total_seconds: float | None = None
    chunk_count: int | None = None


class TranscriptResult(BaseModel):
    job_id: str
    status: JobStatus
    source_file: str
    source_type: str
    language: str | None = None
    duration_seconds: float | None = None
    full_text: str = ""
    segments: list[Segment] = Field(default_factory=list)
    artifacts: ArtifactPaths = Field(default_factory=ArtifactPaths)
    metrics: ProcessingMetrics = Field(default_factory=ProcessingMetrics)
    error: str | None = None


class JobResponse(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime


class JobDetail(BaseModel):
    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    source_file: str
    source_type: str
    language: str | None = None
    output_formats: list[ArtifactFormat]
    result: TranscriptResult | None = None
    error: str | None = None


class HealthStatus(BaseModel):
    service: str = "ok"
    database: str
    upstream_asr: str
