from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.models.schemas import ArtifactFormat


class StorageService:
    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def create_job_id(self) -> str:
        return uuid4().hex

    def create_job_dir(self, job_id: str) -> Path:
        path = self.jobs_dir / job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def save_upload(self, job_id: str, upload: UploadFile) -> Path:
        job_dir = self.create_job_dir(job_id)
        suffix = Path(upload.filename or "").suffix
        target = job_dir / f"input{suffix}"
        with target.open("wb") as handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        await upload.close()
        return target

    def save_local_file(self, job_id: str, source_path: Path) -> Path:
        job_dir = self.create_job_dir(job_id)
        target = job_dir / f"input{source_path.suffix}"
        shutil.copy2(source_path, target)
        return target

    def artifact_path(self, job_id: str, fmt: ArtifactFormat) -> Path:
        return self.create_job_dir(job_id) / f"result.{fmt.value}"
