from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from app.api.dependencies import get_job_service
from app.config import get_settings
from app.models.schemas import ArtifactFormat, SourceType
from app.services.jobs import JobService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stt", description="Local speech-to-text CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit = subparsers.add_parser("submit", help="Submit a local file for transcription")
    submit.add_argument("file", type=Path)
    submit.add_argument("--source-type", choices=[item.value for item in SourceType], default=SourceType.auto.value)
    submit.add_argument("--language")
    submit.add_argument("--output-formats", default="json,srt,txt")

    status = subparsers.add_parser("status", help="Get job status")
    status.add_argument("job_id")

    result = subparsers.add_parser("result", help="Fetch job result")
    result.add_argument("job_id")
    result.add_argument("--format", choices=[item.value for item in ArtifactFormat], default=ArtifactFormat.json.value)

    subparsers.add_parser("health", help="Check service health")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = get_settings()
    base_url = settings.service_base_url.rstrip("/")

    if args.command == "submit":
        _submit_local(args)
        return
    if args.command == "status":
        response = httpx.get(f"{base_url}/jobs/{args.job_id}", timeout=30.0)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        return
    if args.command == "result":
        if args.format == ArtifactFormat.json.value:
            response = httpx.get(f"{base_url}/jobs/{args.job_id}/result", timeout=30.0)
            response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False, indent=2))
        else:
            response = httpx.get(f"{base_url}/jobs/{args.job_id}/artifacts/{args.format}", timeout=30.0)
            response.raise_for_status()
            print(response.text)
        return
    if args.command == "health":
        response = httpx.get(f"{base_url}/health", timeout=10.0)
        response.raise_for_status()
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))


def _submit_local(args: argparse.Namespace) -> None:
    service: JobService = get_job_service()
    output_formats = [ArtifactFormat(item.strip()) for item in args.output_formats.split(",") if item.strip()]
    response = service.create_job_from_path(
        source_path=args.file,
        source_type=SourceType(args.source_type),
        output_formats=output_formats,
        language=args.language,
    )
    print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))
