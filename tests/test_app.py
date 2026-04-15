from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    jobs_dir = tmp_path / "jobs"
    db_path = tmp_path / "app.db"
    monkeypatch.setenv("ASR_BASE_URL", "http://asr.local/v1")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("JOBS_DIR", jobs_dir.as_posix())
    monkeypatch.setenv("WORKER_POLL_INTERVAL_SECONDS", "0.05")
    monkeypatch.setenv("SERVICE_BASE_URL", "http://testserver")

    from app.api import dependencies
    from app.config import get_settings

    get_settings.cache_clear()
    dependencies.get_repository.cache_clear()
    dependencies.get_storage_service.cache_clear()
    dependencies.get_asr_client.cache_clear()
    dependencies.get_job_service.cache_clear()
    dependencies.get_worker.cache_clear()
    yield tmp_path
    get_settings.cache_clear()
    dependencies.get_repository.cache_clear()
    dependencies.get_storage_service.cache_clear()
    dependencies.get_asr_client.cache_clear()
    dependencies.get_job_service.cache_clear()
    dependencies.get_worker.cache_clear()


@pytest.fixture
def client(app_env, monkeypatch):
    from app.api.dependencies import get_asr_client
    from app.main import app

    async def fake_transcribe(*, file_path: Path, language: str | None):
        return {
            "text": "hello world",
            "language": language or "zh",
            "duration": 1.25,
            "segments": [
                {"start": 0.0, "end": 0.5, "text": "hello"},
                {"start": 0.5, "end": 1.25, "text": "world"},
            ],
        }

    async def fake_healthcheck():
        return True

    monkeypatch.setattr(get_asr_client(), "transcribe", fake_transcribe)
    monkeypatch.setattr(get_asr_client(), "healthcheck", fake_healthcheck)

    with TestClient(app) as test_client:
        yield test_client


def wait_for_completion(client: TestClient, job_id: str):
    for _ in range(50):
        payload = client.get(f"/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed"}:
            return payload
        time.sleep(0.05)
    raise AssertionError("job did not complete in time")


def test_audio_job_success(client: TestClient):
    response = client.post(
        "/jobs/transcriptions",
        files={"file": ("sample.wav", b"fake-audio", "audio/wav")},
        data={"output_formats": "json,srt,txt"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    completed = wait_for_completion(client, job_id)
    assert completed["status"] == "succeeded"
    assert completed["result"]["full_text"] == "hello world"
    assert completed["result"]["metrics"]["total_seconds"] is not None
    assert completed["result"]["metrics"]["processing_seconds"] is not None
    assert completed["result"]["metrics"]["chunk_count"] == 1

    result_response = client.get(f"/jobs/{job_id}/result")
    assert result_response.status_code == 200
    assert result_response.json()["segments"][0]["text"] == "hello"

    srt_response = client.get(f"/jobs/{job_id}/artifacts/srt")
    assert srt_response.status_code == 200
    assert "00:00:00,000 --> 00:00:00,500" in srt_response.text


def test_invalid_file_type_rejected(client: TestClient):
    response = client.post(
        "/jobs/transcriptions",
        files={"file": ("sample.bin", b"nope", "application/octet-stream")},
    )
    assert response.status_code == 400


def test_healthcheck(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_video_job_uses_extraction(client: TestClient, monkeypatch):
    def fake_extract_audio(*, ffmpeg_path: str, input_path: Path, output_path: Path):
        output_path.write_bytes(b"fake-wav")
        return output_path

    monkeypatch.setattr("app.workers.runner.extract_audio", fake_extract_audio)

    response = client.post(
        "/jobs/transcriptions",
        files={"file": ("sample.mp4", b"fake-video", "video/mp4")},
        data={"source_type": "video", "output_formats": "json"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    completed = wait_for_completion(client, job_id)
    assert completed["status"] == "succeeded"
    assert completed["source_type"] == "video"


def test_large_audio_uses_chunking(client: TestClient, monkeypatch, tmp_path):
    from app.api.dependencies import get_worker
    from app.services.media import AudioChunk

    worker = get_worker()
    worker.asr_max_file_size_bytes = 1
    worker.chunk_duration_seconds = 50
    worker.chunk_overlap_seconds = 5

    chunk1 = tmp_path / "chunk-0001.wav"
    chunk2 = tmp_path / "chunk-0002.wav"
    chunk1.write_bytes(b"a")
    chunk2.write_bytes(b"b")

    def fake_split_audio_with_overlap(**kwargs):
        return [
            AudioChunk(
                index=1,
                start_seconds=0.0,
                end_seconds=50.0,
                path=chunk1,
                trim_lead_seconds=0.0,
                trim_tail_seconds=5.0,
            ),
            AudioChunk(
                index=2,
                start_seconds=45.0,
                end_seconds=90.0,
                path=chunk2,
                trim_lead_seconds=5.0,
                trim_tail_seconds=0.0,
            ),
        ]

    async def fake_chunk_transcribe(*, file_path: Path, language: str | None):
        if file_path == chunk1:
            return {"text": "hello brave new", "language": "en"}
        if file_path == chunk2:
            return {"text": "brave new world", "language": "en"}
        return {"text": "fallback", "language": "en"}

    from app.api.dependencies import get_asr_client

    monkeypatch.setattr("app.workers.runner.split_audio_with_overlap", fake_split_audio_with_overlap)
    monkeypatch.setattr(get_asr_client(), "transcribe", fake_chunk_transcribe)

    response = client.post(
        "/jobs/transcriptions",
        files={"file": ("large.wav", b"large-audio", "audio/wav")},
        data={"output_formats": "json,txt"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    completed = wait_for_completion(client, job_id)
    assert completed["status"] == "succeeded"
    assert completed["result"]["full_text"] == "hello brave new world"
    assert completed["result"]["segments"][0]["text"] == "hello brave new"
    assert completed["result"]["segments"][1]["text"] == "world"


def test_qwen_output_prefix_is_cleaned(client: TestClient, monkeypatch):
    from app.api.dependencies import get_asr_client

    async def fake_prefixed_transcribe(*, file_path: Path, language: str | None):
        return {
            "text": "language English<asr_text>Hello from Qwen",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "language English<asr_text>Hello from Qwen"}
            ],
        }

    monkeypatch.setattr(get_asr_client(), "transcribe", fake_prefixed_transcribe)

    response = client.post(
        "/jobs/transcriptions",
        files={"file": ("prefixed.wav", b"fake-audio", "audio/wav")},
        data={"output_formats": "json,srt,txt"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    completed = wait_for_completion(client, job_id)
    assert completed["status"] == "succeeded"
    assert completed["result"]["full_text"] == "Hello from Qwen"
    assert completed["result"]["language"] == "English"
    assert completed["result"]["segments"][0]["text"] == "Hello from Qwen"


def test_inline_qwen_prefix_is_removed_from_merged_text(client: TestClient, monkeypatch):
    from app.api.dependencies import get_asr_client

    async def fake_inline_transcribe(*, file_path: Path, language: str | None):
        return {
            "text": "Hello language English<asr_text>world",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello language English<asr_text>world"}
            ],
        }

    monkeypatch.setattr(get_asr_client(), "transcribe", fake_inline_transcribe)

    response = client.post(
        "/jobs/transcriptions",
        files={"file": ("inline.wav", b"fake-audio", "audio/wav")},
        data={"output_formats": "json"},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    completed = wait_for_completion(client, job_id)
    assert completed["status"] == "succeeded"
    assert completed["result"]["full_text"] == "Hello world"
    assert completed["result"]["segments"][0]["text"] == "Hello world"
