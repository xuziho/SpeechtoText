from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.config import Settings
from app.db.repository import JobRecord, JobRepository
from app.models.schemas import ArtifactFormat, JobDetail, JobResponse, JobStatus, SourceType, TranscriptResult
from app.services.media import detect_source_type
from app.services.storage import StorageService


class JobService:
    def __init__(self, *, settings: Settings, repository: JobRepository, storage: StorageService):
        self.settings = settings
        self.repository = repository
        self.storage = storage

    async def create_job_from_upload(
        self,
        *,
        upload: UploadFile,
        source_type: SourceType,
        output_formats: list[ArtifactFormat],
        language: str | None,
    ) -> JobResponse:
        self._validate_upload(upload)
        job_id = self.storage.create_job_id()
        stored_path = await self.storage.save_upload(job_id, upload)
        if stored_path.stat().st_size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Input file is empty.")
        resolved_source_type = self._resolve_source_type(stored_path, source_type)
        record = self.repository.create_job(
            job_id=job_id,
            source_file=upload.filename or stored_path.name,
            stored_input_path=str(stored_path),
            source_type=resolved_source_type,
            language=language,
            output_formats=output_formats,
        )
        return JobResponse(job_id=record.job_id, status=JobStatus(record.status), created_at=record.created_at)

    def create_job_from_path(
        self,
        *,
        source_path: Path,
        source_type: SourceType,
        output_formats: list[ArtifactFormat],
        language: str | None,
    ) -> JobResponse:
        if not source_path.exists() or not source_path.is_file():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Input file does not exist.")
        if source_path.stat().st_size == 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Input file is empty.")
        job_id = self.storage.create_job_id()
        stored_path = self.storage.save_local_file(job_id, source_path)
        resolved_source_type = self._resolve_source_type(stored_path, source_type)
        record = self.repository.create_job(
            job_id=job_id,
            source_file=source_path.name,
            stored_input_path=str(stored_path),
            source_type=resolved_source_type,
            language=language,
            output_formats=output_formats,
        )
        return JobResponse(job_id=record.job_id, status=JobStatus(record.status), created_at=record.created_at)

    def get_job_detail(self, job_id: str) -> JobDetail:
        record = self.repository.get_job(job_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
        return self._to_job_detail(record)

    def get_result(self, job_id: str) -> TranscriptResult:
        record = self.repository.get_job(job_id)
        if not record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
        if not record.result_json:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job result is not available yet.")
        return TranscriptResult.model_validate_json(record.result_json)

    def artifact_path(self, job_id: str, fmt: ArtifactFormat) -> Path:
        result = self.get_result(job_id)
        path_value = getattr(result.artifacts, f"{fmt.value}_path")
        if not path_value:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{fmt.value} artifact is not available.")
        path = Path(path_value)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{fmt.value} artifact file is missing.")
        return path

    def _validate_upload(self, upload: UploadFile) -> None:
        if not upload.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A filename is required.")

    def _resolve_source_type(self, stored_path: Path, source_type: SourceType) -> str:
        try:
            detected = detect_source_type(stored_path)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if source_type == SourceType.auto:
            return detected
        if source_type.value != detected:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"source_type={source_type.value} does not match file type {detected}.",
            )
        return detected

    def _to_job_detail(self, record: JobRecord) -> JobDetail:
        result = TranscriptResult.model_validate_json(record.result_json) if record.result_json else None
        return JobDetail(
            job_id=record.job_id,
            status=JobStatus(record.status),
            created_at=record.created_at,
            updated_at=record.updated_at,
            source_file=record.source_file,
            source_type=record.source_type,
            language=record.language,
            output_formats=[ArtifactFormat(item) for item in record.output_formats],
            result=result,
            error=record.error,
        )
