"""Loopback-only HTTP surface reserved for a future Proteus frontend."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import os
from threading import Lock
from typing import Any, Protocol
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from proteus import __version__
from proteus.credentials import (
    HIOBUY_API_KEY,
    SERPAPI_API_KEY,
    configuration_status,
    resolve_receiver,
    resolve_secret,
)
from proteus.providers.adapters import (
    HIOBUY_1688_ID,
    SERPAPI_AMAZON_ID,
    SERPAPI_EBAY_DISCOVERY_ID,
    SERPAPI_EBAY_ID,
    build_provider_registry,
)
from proteus.providers.base import Capability


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class FrontendService(Protocol):
    def configuration_status(self) -> dict: ...

    def provider_status(self) -> dict: ...

    def submit_run(self, request: dict) -> dict: ...

    def get_run(self, run_id: str) -> dict | None: ...


class ApiRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_candidates: int = Field(default=20, ge=1, le=100)
    max_moq: int = Field(ge=1, le=100000)
    ebay_category_id: str = Field(default="6028", pattern=r"^[0-9]+$")
    discovery_pages: int = Field(default=1, ge=1, le=10)


class InMemoryRunManager:
    """Single-process async run store; persistence can replace this contract later."""

    def __init__(self, runner: Callable[[dict], Mapping[str, Any]]) -> None:
        self._runner = runner
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="proteus-run")
        self._lock = Lock()
        self._runs: dict[str, dict[str, Any]] = {}

    def submit(self, request: dict) -> dict:
        run_id = str(uuid4())
        record = {
            "run_id": run_id,
            "status": "QUEUED",
            "created_at": _utc_now(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._runs[run_id] = record
        self._executor.submit(self._execute, run_id, deepcopy(request))
        return {"run_id": run_id, "status": "QUEUED"}

    def _execute(self, run_id: str, request: dict) -> None:
        with self._lock:
            self._runs[run_id]["status"] = "RUNNING"
            self._runs[run_id]["started_at"] = _utc_now()
        try:
            result = dict(self._runner(request))
        except Exception as exc:
            with self._lock:
                self._runs[run_id]["status"] = "FAILED"
                self._runs[run_id]["completed_at"] = _utc_now()
                self._runs[run_id]["error"] = {
                    "code": type(exc).__name__,
                    "message": "The managed run failed; check provider readiness and retry.",
                }
            return
        with self._lock:
            self._runs[run_id]["status"] = "COMPLETED"
            self._runs[run_id]["completed_at"] = _utc_now()
            self._runs[run_id]["result"] = result

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            value = self._runs.get(run_id)
            return deepcopy(value) if value is not None else None


class DefaultFrontendService:
    def __init__(self) -> None:
        self._manager = InMemoryRunManager(self._run)

    def configuration_status(self) -> dict:
        return configuration_status()

    def provider_status(self) -> dict:
        serpapi_key = resolve_secret(SERPAPI_API_KEY)
        hiobuy_key = resolve_secret(HIOBUY_API_KEY)
        receiver = resolve_receiver()
        registry = build_provider_registry(
            nexscope_key=None,
            serpapi_key=serpapi_key,
            hiobuy_key=hiobuy_key,
            receiver=receiver,
        )
        selections = (
            (Capability.EBAY_CANDIDATE_SOURCE, SERPAPI_EBAY_DISCOVERY_ID),
            (Capability.AMAZON_COMPETITION, SERPAPI_AMAZON_ID),
            (Capability.EBAY_DEMAND, SERPAPI_EBAY_ID),
            (Capability.ALIBABA_1688_SUPPLY, HIOBUY_1688_ID),
        )
        return {
            "profile": "two-account-managed",
            "providers": [
                registry.select(capability, (provider_id,), require_ready=False)
                .preflight()
                .to_dict()
                for capability, provider_id in selections
            ],
        }

    def _run(self, request: dict) -> Mapping[str, Any]:
        from proteus.managed import run_two_account_managed

        return run_two_account_managed(
            serpapi_key=resolve_secret(SERPAPI_API_KEY),
            hiobuy_key=resolve_secret(HIOBUY_API_KEY),
            receiver=resolve_receiver(),
            **request,
        )

    def submit_run(self, request: dict) -> dict:
        return self._manager.submit(request)

    def get_run(self, run_id: str) -> dict | None:
        return self._manager.get(run_id)


def create_app(*, service: FrontendService | None = None) -> FastAPI:
    active_service = service or DefaultFrontendService()
    app = FastAPI(
        title="Proteus Opportunity Finder API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    @app.get("/api/v1/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": __version__,
            "profile": "two-account-managed",
        }

    @app.get("/api/v1/config/status")
    def config_status() -> dict:
        return active_service.configuration_status()

    @app.get("/api/v1/providers")
    def providers() -> dict:
        return active_service.provider_status()

    @app.post("/api/v1/runs", status_code=status.HTTP_202_ACCEPTED)
    def submit_run(request: ApiRunRequest) -> dict:
        return active_service.submit_run(request.model_dump())

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        value = active_service.get_run(run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        return value

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proteus api",
        description="Run the loopback-only Proteus frontend API.",
    )
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        print("proteus api: error: port must be between 1 and 65535", file=os.sys.stderr)
        return 2
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=args.port)
    return 0


__all__ = [
    "ApiRunRequest",
    "DefaultFrontendService",
    "FrontendService",
    "InMemoryRunManager",
    "create_app",
]
