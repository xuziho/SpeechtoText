from functools import lru_cache

from app.config import get_settings
from app.db.repository import JobRepository
from app.services.asr_client import ASRClient
from app.services.jobs import JobService
from app.services.storage import StorageService
from app.workers.runner import JobWorker


@lru_cache
def get_repository() -> JobRepository:
    settings = get_settings()
    return JobRepository(settings.database_path)


@lru_cache
def get_storage_service() -> StorageService:
    settings = get_settings()
    return StorageService(settings.jobs_dir)


@lru_cache
def get_asr_client() -> ASRClient:
    settings = get_settings()
    return ASRClient(base_url=settings.asr_base_url, api_key=settings.asr_api_key, model=settings.asr_model)


@lru_cache
def get_job_service() -> JobService:
    settings = get_settings()
    return JobService(settings=settings, repository=get_repository(), storage=get_storage_service())


@lru_cache
def get_worker() -> JobWorker:
    settings = get_settings()
    return JobWorker(
        repository=get_repository(),
        storage=get_storage_service(),
        asr_client=get_asr_client(),
        ffmpeg_path=settings.ffmpeg_path,
        poll_interval_seconds=settings.worker_poll_interval_seconds,
    )
