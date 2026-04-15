from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    asr_base_url: str = Field(..., alias="ASR_BASE_URL")
    asr_api_key: str | None = Field(default=None, alias="ASR_API_KEY")
    asr_model: str = Field(default="Qwen3-ASR-0.6B", alias="ASR_MODEL")
    database_url: str = Field(default="sqlite:///data/app.db", alias="DATABASE_URL")
    jobs_dir: Path = Field(default=Path("data/jobs"), alias="JOBS_DIR")
    ffmpeg_path: str = Field(default="ffmpeg", alias="FFMPEG_PATH")
    max_upload_size_mb: int = Field(default=500, alias="MAX_UPLOAD_SIZE_MB")
    asr_max_file_size_mb: int = Field(default=25, alias="ASR_MAX_FILE_SIZE_MB")
    chunk_duration_seconds: int = Field(default=50, alias="CHUNK_DURATION_SECONDS")
    chunk_overlap_seconds: int = Field(default=5, alias="CHUNK_OVERLAP_SECONDS")
    worker_poll_interval_seconds: float = Field(default=1.0, alias="WORKER_POLL_INTERVAL_SECONDS")
    service_base_url: str = Field(default="http://127.0.0.1:8000", alias="SERVICE_BASE_URL")

    @property
    def database_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("Only sqlite:/// DATABASE_URL values are supported in v1.")
        return Path(self.database_url.replace("sqlite:///", "", 1))


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
