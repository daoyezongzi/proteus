"""Loopback-only HTTP surface reserved for a future Proteus frontend."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from proteus import __version__
from proteus.credentials import (
    HIOBUY_API_KEY,
    MARKETCHECK_API_KEY,
    SERPAPI_API_KEY,
    configuration_status,
    resolve_receiver,
    resolve_secret,
)
from proteus.normalization import normalize_part_number
from proteus.northway_mvp import ARCHETYPES, compact_northway_result, northway_mvp_policy
from proteus.providers.adapters import (
    HIOBUY_1688_ID,
    LOCAL_1688_CLI_ID,
    SERPAPI_AMAZON_ID,
    SERPAPI_EBAY_DISCOVERY_ID,
    SERPAPI_EBAY_ID,
    build_provider_registry,
)
from proteus.providers.base import Capability, DEFAULT_DISCOVERY_KEYWORD
from proteus.screening import evaluate_strict_market_screening, screening_policy
from proteus.automatic_mvp import automatic_mvp_policy


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class FrontendService(Protocol):
    def configuration_status(self) -> dict: ...

    def provider_status(self) -> dict: ...

    def submit_run(self, request: dict) -> dict: ...

    def get_run(self, run_id: str) -> dict | None: ...

    def submit_mvp_run(self, request: dict) -> dict: ...

    def get_mvp_run(self, run_id: str) -> dict | None: ...

    def submit_northway_run(self, request: dict) -> dict: ...

    def get_northway_run(self, run_id: str) -> dict | None: ...


class ApiRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_candidates: int = Field(default=20, ge=1, le=100)
    max_moq: int = Field(ge=1, le=100000)
    ebay_category_id: str = Field(default="6028", pattern=r"^[0-9]+$")
    discovery_pages: int = Field(default=1, ge=1, le=10)


class AutomaticMvpRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_candidates: int = Field(default=20, ge=1, le=100)
    ebay_category_id: str = Field(default="6028", pattern=r"^[0-9]+$")
    # The marketplace engine cannot browse a category with no query, so the
    # sample is drawn from this keyword within the category.
    discovery_keyword: str = Field(
        default=DEFAULT_DISCOVERY_KEYWORD, min_length=1, max_length=200
    )
    discovery_pages: int = Field(default=1, ge=1, le=10)

    @field_validator("discovery_keyword")
    @classmethod
    def validate_discovery_keyword(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("discovery_keyword must not be blank")
        return value.strip()
    min_ebay_trailing_year_units_exclusive: int = Field(default=0, ge=0, le=1000000)
    max_amazon_us_exact_competitors: int = Field(default=5, ge=0, le=100000)
    min_amazon_price_usd: float = Field(default=20.0, ge=0, le=1000000)
    max_amazon_active_sellers: int = Field(default=10, ge=0, le=1000000)
    max_fitment_listings: int = Field(default=3, ge=1, le=10)


class NorthwayMvpRunRequest(BaseModel):
    """One bounded run for one selected Northway product archetype."""

    model_config = ConfigDict(extra="forbid")

    archetype: str = Field(min_length=1)
    discovery_pages: int = Field(default=1, ge=1, le=10)
    request_budget: int = Field(default=20, ge=1, le=500)
    max_1688_checks: int = Field(default=20, ge=0, le=500)
    max_amazon_queries_per_family: int = Field(default=3, ge=1, le=5)
    min_family_price_usd: float = Field(default=20.0, ge=0, le=1000000)
    min_observed_ebay_demand: int = Field(default=1, ge=0, le=1000000)

    @field_validator("archetype")
    @classmethod
    def validate_archetype(cls, value: str) -> str:
        if value not in ARCHETYPES:
            raise ValueError("archetype must be one of the Northway leaf categories")
        return value

    @model_validator(mode="after")
    def validate_discovery_budget(self) -> "NorthwayMvpRunRequest":
        required = self.discovery_pages
        if self.request_budget < required:
            raise ValueError(
                "request_budget must cover the selected archetype discovery pages "
                f"({required} requests required)"
            )
        return self


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str = Field(min_length=1, max_length=100)
    source_reference: str = Field(min_length=1, max_length=2000)
    retrieved_at: datetime


class EbayAnnualSalesEvidence(EvidenceSource):
    marketplace_id: Literal["EBAY_US"] = "EBAY_US"
    window_days: Literal[365] = 365
    units_sold: int = Field(ge=0)


class AmazonCompetitionEvidence(EvidenceSource):
    marketplace_id: Literal["AMAZON_US"] = "AMAZON_US"
    exact_competitor_count: int = Field(ge=0)


class VehicleParcEvidence(EvidenceSource):
    country_code: Literal["US"] = "US"
    fitment_resolved: bool
    compatible_vehicle_count: int = Field(ge=0)


class StrictScreeningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_number: str = Field(min_length=3, max_length=100)
    min_us_vehicle_parc: int = Field(ge=1)
    ebay_annual_sales: EbayAnnualSalesEvidence | None = None
    amazon_competition: AmazonCompetitionEvidence | None = None
    vehicle_parc: VehicleParcEvidence | None = None

    @field_validator("part_number")
    @classmethod
    def validate_part_number(cls, value: str) -> str:
        normalize_part_number(value)
        return value


class ScreeningCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator: Literal["GT", "LTE", "GTE"]
    threshold: int | None
    window_days: int | None = None
    marketplace_id: str | None = None
    threshold_required_per_run: bool = False
    country_code: str | None = None


class ScreeningCriteriaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ebay_annual_units_sold: ScreeningCriterion
    amazon_us_exact_competitors: ScreeningCriterion
    us_compatible_vehicle_parc: ScreeningCriterion


class ScreeningProviderChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str | None
    configuration: str | None = None
    implementation_status: str
    fallback: str | None = None
    optional_compatibility: str | None = None


class ScreeningProvidersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    marketplace_discovery_and_amazon: ScreeningProviderChoice
    ebay_annual_sales: ScreeningProviderChoice
    vehicle_parc: ScreeningProviderChoice
    supply_verification: ScreeningProviderChoice


class ScreeningPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["strict-market-screening"]
    decision: Literal["MARKET_OPPORTUNITY_CANDIDATE"]
    criteria: ScreeningCriteriaResponse
    providers: ScreeningProvidersResponse
    qualification_boundary: str


class ScreeningStageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["PASSED", "REJECTED", "REVIEW_REQUIRED"]
    value: int | None
    reason: str
    operator: Literal["GT", "LTE", "GTE"] | None = None
    threshold: int | None = None
    window_days: int | None = None
    provider_id: str | None = None
    source_reference: str | None = None
    retrieved_at: datetime | None = None


class ScreeningStagesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ebay_annual_sales: ScreeningStageResponse
    amazon_competition: ScreeningStageResponse
    vehicle_parc: ScreeningStageResponse


class ScreenedPartNumber(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw: str
    canonical: str


class StrictScreeningResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["0.2.2"]
    profile: Literal["strict-market-screening"]
    part_number: ScreenedPartNumber
    decision: Literal[
        "MARKET_OPPORTUNITY_CANDIDATE", "REJECTED", "REVIEW_REQUIRED"
    ]
    stages: ScreeningStagesResponse
    supply_verification: Literal["NOT_EVALUATED"]


class InMemoryRunManager:
    """Single-process async run store; persistence can replace this contract later."""

    def __init__(
        self,
        runner: Callable[..., Mapping[str, Any]],
        *,
        supports_progress: bool = False,
    ) -> None:
        self._runner = runner
        self._supports_progress = supports_progress
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
            "progress": {
                "phase": "queued",
                "current": 0,
                "total": 0,
                "last_query": None,
                "provider": None,
                "budget_used": 0,
                "updated_at": _utc_now(),
            },
        }
        with self._lock:
            self._runs[run_id] = record
        self._executor.submit(self._execute, run_id, deepcopy(request))
        return {"run_id": run_id, "status": "QUEUED"}

    def _execute(self, run_id: str, request: dict) -> None:
        with self._lock:
            self._runs[run_id]["status"] = "RUNNING"
            self._runs[run_id]["started_at"] = _utc_now()

        def update_progress(value: Mapping[str, Any]) -> None:
            if not isinstance(value, Mapping):
                return
            payload = dict(value)
            payload.setdefault("updated_at", _utc_now())
            with self._lock:
                if run_id in self._runs:
                    self._runs[run_id]["progress"] = payload

        try:
            result = dict(
                self._runner(request, progress=update_progress)
                if self._supports_progress
                else self._runner(request)
            )
        except Exception as exc:
            with self._lock:
                previous_progress = self._runs[run_id].get("progress", {})
                if not isinstance(previous_progress, Mapping):
                    previous_progress = {}
                self._runs[run_id]["status"] = "FAILED"
                self._runs[run_id]["completed_at"] = _utc_now()
                self._runs[run_id]["error"] = {
                    "code": type(exc).__name__,
                    "message": "The managed run failed; check provider readiness and retry.",
                }
                self._runs[run_id]["progress"] = {
                    "phase": "failed",
                    "current": previous_progress.get("current", 0),
                    "total": previous_progress.get("total", 0),
                    "last_query": previous_progress.get("last_query"),
                    "provider": previous_progress.get("provider"),
                    "budget_used": previous_progress.get("budget_used", 0),
                    "updated_at": _utc_now(),
                }
            return
        with self._lock:
            self._runs[run_id]["status"] = "COMPLETED"
            self._runs[run_id]["completed_at"] = _utc_now()
            self._runs[run_id]["result"] = result
            self._runs[run_id]["progress"] = {
                "phase": "completed",
                "current": len(result.get("reports", []))
                if isinstance(result.get("reports"), list)
                else 0,
                "total": len(result.get("reports", []))
                if isinstance(result.get("reports"), list)
                else 0,
                "last_query": None,
                "provider": None,
                "budget_used": result.get("request_budget", {}).get("used", 0)
                if isinstance(result.get("request_budget"), Mapping)
                else 0,
                "updated_at": _utc_now(),
            }

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            value = self._runs.get(run_id)
            return deepcopy(value) if value is not None else None


class DefaultFrontendService:
    def __init__(self) -> None:
        self._manager = InMemoryRunManager(self._run)
        self._mvp_manager = InMemoryRunManager(self._run_mvp)
        self._northway_manager = InMemoryRunManager(
            self._run_northway,
            supports_progress=True,
        )

    def configuration_status(self) -> dict:
        return configuration_status()

    def provider_status(self) -> dict:
        serpapi_key = resolve_secret(SERPAPI_API_KEY)
        marketcheck_key = resolve_secret(MARKETCHECK_API_KEY)
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
            (Capability.ALIBABA_1688_SUPPLY, LOCAL_1688_CLI_ID),
            (Capability.ALIBABA_1688_SUPPLY, HIOBUY_1688_ID),
        )
        return {
            "profile": "provider-readiness",
            "screening_strategy": screening_policy()["providers"],
            "providers": [
                registry.select(capability, (provider_id,), require_ready=False)
                .preflight()
                .to_dict()
                for capability, provider_id in selections
            ]
            + [
                {
                    "provider_id": "ny-dmv-nhtsa-registration-estimate",
                    "capability": "US_ACTIVE_VEHICLE_PROXY",
                    "ready": True,
                    "checks": [
                        {
                            "name": "ANONYMOUS_PUBLIC_APIS",
                            "status": "PASS",
                            "message": "NY DMV Socrata and NHTSA vPIC require no account.",
                        },
                        {
                            "name": "OFFICIAL_VIO",
                            "status": "FAIL",
                            "message": "This is a sampled New York registration estimate, not nationwide official VIO.",
                        },
                    ],
                },
                {
                    "provider_id": "marketcheck-active-used-inventory",
                    "capability": "US_ACTIVE_VEHICLE_PROXY",
                    "ready": marketcheck_key is not None,
                    "optional": True,
                    "checks": [
                        {
                            "name": "CREDENTIALS_AVAILABLE",
                            "status": "PASS" if marketcheck_key is not None else "UNKNOWN",
                            "message": "Credential alias MARKETCHECK_API_KEY is configured."
                            if marketcheck_key is not None
                            else "Credential alias MARKETCHECK_API_KEY is not configured.",
                        },
                        {
                            "name": "OFFICIAL_VIO",
                            "status": "FAIL",
                            "message": "This provider is an active used-inventory proxy, not official VIO.",
                        },
                    ],
                }
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

    def _run_mvp(self, request: dict) -> Mapping[str, Any]:
        from proteus.automatic_mvp import run_automatic_mvp

        return run_automatic_mvp(
            serpapi_key=resolve_secret(SERPAPI_API_KEY),
            **request,
        )

    def submit_mvp_run(self, request: dict) -> dict:
        return self._mvp_manager.submit(request)

    def get_mvp_run(self, run_id: str) -> dict | None:
        return self._mvp_manager.get(run_id)

    def _run_northway(
        self,
        request: dict,
        *,
        progress: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Mapping[str, Any]:
        from proteus.northway_mvp import run_northway_mvp

        return run_northway_mvp(
            serpapi_key=resolve_secret(SERPAPI_API_KEY),
            progress_callback=progress,
            **request,
        )

    def submit_northway_run(self, request: dict) -> dict:
        return self._northway_manager.submit(request)

    def get_northway_run(self, run_id: str) -> dict | None:
        return self._northway_manager.get(run_id)


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
            "profile": "northway-product-family-mvp",
            "compatibility_profiles": [
                "automatic-mvp",
                "strict-market-screening",
                "two-account-managed",
            ],
        }

    @app.get("/api/v1/config/status")
    def config_status() -> dict:
        return active_service.configuration_status()

    @app.get("/api/v1/providers")
    def providers() -> dict:
        return active_service.provider_status()

    @app.get(
        "/api/v1/screening/policy",
        response_model=ScreeningPolicyResponse,
        response_model_exclude_none=True,
    )
    def strict_screening_policy() -> dict:
        return screening_policy()

    @app.post(
        "/api/v1/screening/evaluate",
        response_model=StrictScreeningResponse,
        response_model_exclude_none=True,
    )
    def evaluate_screening(request: StrictScreeningRequest) -> dict:
        payload = request.model_dump(mode="json")
        return evaluate_strict_market_screening(
            payload.pop("part_number"),
            payload,
            min_us_vehicle_parc=payload.pop("min_us_vehicle_parc"),
        )

    @app.get("/api/v1/mvp/policy")
    def mvp_policy() -> dict:
        return automatic_mvp_policy()

    @app.post("/api/v1/mvp/runs", status_code=status.HTTP_202_ACCEPTED)
    def submit_mvp_run(request: AutomaticMvpRunRequest) -> dict:
        return active_service.submit_mvp_run(request.model_dump())

    @app.get("/api/v1/mvp/runs/{run_id}")
    def get_mvp_run(run_id: str) -> dict:
        value = active_service.get_mvp_run(run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        return value

    @app.get("/api/v1/northway/policy")
    def northway_policy() -> dict:
        return northway_mvp_policy()

    @app.post("/api/v1/northway/runs", status_code=status.HTTP_202_ACCEPTED)
    def submit_northway_run(request: NorthwayMvpRunRequest) -> dict:
        return active_service.submit_northway_run(request.model_dump())

    @app.get("/api/v1/northway/runs/{run_id}")
    def get_northway_run(run_id: str) -> dict:
        value = active_service.get_northway_run(run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        return value

    @app.get("/api/v1/northway/runs/{run_id}/export")
    def export_northway_run(run_id: str) -> JSONResponse:
        value = active_service.get_northway_run(run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        if value.get("status") != "COMPLETED" or not isinstance(value.get("result"), Mapping):
            raise HTTPException(status_code=409, detail="run is not complete")
        return JSONResponse(
            value["result"],
            headers={
                "Content-Disposition": f'attachment; filename="proteus-{run_id}.json"'
            },
        )

    @app.get("/api/v1/northway/runs/{run_id}/export/compact")
    def export_compact_northway_run(run_id: str) -> JSONResponse:
        value = active_service.get_northway_run(run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        if value.get("status") != "COMPLETED" or not isinstance(value.get("result"), Mapping):
            raise HTTPException(status_code=409, detail="run is not complete")
        return JSONResponse(
            compact_northway_result(value["result"]),
            headers={
                "Content-Disposition": f'attachment; filename="proteus-{run_id}-compact.json"'
            },
        )

    @app.post("/api/v1/runs", status_code=status.HTTP_202_ACCEPTED)
    def submit_run(request: ApiRunRequest) -> dict:
        return active_service.submit_run(request.model_dump())

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        value = active_service.get_run(run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        return value

    # Serve the loopback operator UI last so it cannot shadow any API route.
    # The directory is absent in a wheel-only install; the API still works.
    web_root = Path(__file__).resolve().parents[2] / "web"
    if web_root.is_dir():

        class _NoStoreStatic(StaticFiles):
            """Serve the UI without caching.

            This is a single-user loopback tool that is edited in place; a
            cached index.html paired with fresh JS silently breaks the page.
            """

            def file_response(self, *args: Any, **kwargs: Any):
                response = super().file_response(*args, **kwargs)
                response.headers["cache-control"] = "no-store"
                return response

        app.mount("/", _NoStoreStatic(directory=web_root, html=True), name="web")

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
    "AutomaticMvpRunRequest",
    "DefaultFrontendService",
    "FrontendService",
    "InMemoryRunManager",
    "NorthwayMvpRunRequest",
    "ScreeningPolicyResponse",
    "StrictScreeningRequest",
    "StrictScreeningResponse",
    "create_app",
]
