from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.models.schemas import ArtifactFormat, JobStatus, TranscriptResult


def utcnow() -> datetime:
    return datetime.now(UTC)


def _to_iso(value: datetime) -> str:
    return value.isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


@dataclass
class JobRecord:
    job_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    source_file: str
    stored_input_path: str
    source_type: str
    language: str | None
    output_formats: list[str]
    error: str | None
    result_json: str | None


class JobRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    source_file TEXT NOT NULL,
                    stored_input_path TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    language TEXT,
                    output_formats TEXT NOT NULL,
                    error TEXT,
                    result_json TEXT
                )
                """
            )

    def create_job(
        self,
        *,
        job_id: str,
        source_file: str,
        stored_input_path: str,
        source_type: str,
        language: str | None,
        output_formats: list[ArtifactFormat],
    ) -> JobRecord:
        now = utcnow()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    job_id, status, created_at, updated_at, source_file, stored_input_path,
                    source_type, language, output_formats, error, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    JobStatus.queued.value,
                    _to_iso(now),
                    _to_iso(now),
                    source_file,
                    stored_input_path,
                    source_type,
                    language,
                    json.dumps([item.value for item in output_formats]),
                    None,
                    None,
                ),
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def get_next_queued_job(self) -> JobRecord | None:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (JobStatus.queued.value,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def update_status(self, job_id: str, status: JobStatus, *, error: str | None = None) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error = ?
                WHERE job_id = ?
                """,
                (status.value, _to_iso(utcnow()), error, job_id),
            )

    def save_result(self, job_id: str, result: TranscriptResult) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = ?, error = ?, result_json = ?
                WHERE job_id = ?
                """,
                (JobStatus.succeeded.value, _to_iso(utcnow()), None, result.model_dump_json(), job_id),
            )

    def _row_to_record(self, row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            status=row["status"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
            source_file=row["source_file"],
            stored_input_path=row["stored_input_path"],
            source_type=row["source_type"],
            language=row["language"],
            output_formats=json.loads(row["output_formats"]),
            error=row["error"],
            result_json=row["result_json"],
        )
