from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import get_asr_client, get_job_service, get_repository
from app.models.schemas import ArtifactFormat, HealthStatus, JobDetail, JobResponse, SourceType, TranscriptResult
from app.services.jobs import JobService

router = APIRouter()


def _parse_output_formats(value: str | None) -> list[ArtifactFormat]:
    if not value:
        return [ArtifactFormat.json, ArtifactFormat.srt, ArtifactFormat.txt]
    items = [item.strip().lower() for item in value.split(",") if item.strip()]
    return [ArtifactFormat(item) for item in items] if items else [ArtifactFormat.json, ArtifactFormat.srt, ArtifactFormat.txt]


@router.post("/jobs/transcriptions", response_model=JobResponse, status_code=202)
async def create_transcription_job(
    file: Annotated[UploadFile, File(...)],
    output_formats: Annotated[str | None, Form()] = None,
    source_type: Annotated[SourceType, Form()] = SourceType.auto,
    language: Annotated[str | None, Form()] = None,
    service: JobService = Depends(get_job_service),
) -> JobResponse:
    return await service.create_job_from_upload(
        upload=file,
        source_type=source_type,
        output_formats=_parse_output_formats(output_formats),
        language=language,
    )


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str, service: JobService = Depends(get_job_service)) -> JobDetail:
    return service.get_job_detail(job_id)


@router.get("/jobs/{job_id}/result", response_model=TranscriptResult)
def get_job_result(job_id: str, service: JobService = Depends(get_job_service)) -> TranscriptResult:
    return service.get_result(job_id)


@router.get("/jobs/{job_id}/artifacts/{fmt}")
def download_artifact(job_id: str, fmt: ArtifactFormat, service: JobService = Depends(get_job_service)) -> FileResponse:
    path = service.artifact_path(job_id, fmt)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/health", response_model=HealthStatus)
async def healthcheck() -> HealthStatus:
    upstream = "ok" if await get_asr_client().healthcheck() else "unreachable"
    get_repository()
    return HealthStatus(database="ok", upstream_asr=upstream)
