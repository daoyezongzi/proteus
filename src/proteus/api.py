"""Loopback-only HTTP surface reserved for a future Proteus frontend."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from threading import Lock
from typing import Any, Literal, Protocol
from urllib.parse import parse_qsl, urlparse
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from proteus import __version__
from proteus.category_catalog import (
    CategoryCatalog,
    CategoryNotFoundError,
    runtime_category_definition,
)
from proteus.credentials import (
    HIOBUY_API_KEY,
    MARKETCHECK_API_KEY,
    SERPAPI_API_KEY,
    configuration_status,
    resolve_receiver,
    resolve_secret,
)
from proteus.normalization import normalize_part_number
from proteus.northway_mvp import compact_northway_result, northway_mvp_policy
from proteus.providers.local_1688_store import (
    collect_1688_store_offers,
    normalize_1688_supplier_store_target,
)
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
from proteus.supplier_scout import (
    SupplierScoutStore,
    compact_supplier_scout_result,
    run_supplier_scout,
    supplier_scout_policy,
)
from proteus.supplier_capture import (
    CAPTURE_PROTOCOL_VERSION,
    CaptureAuthorizationError,
    CaptureConflictError,
    CaptureNotFoundError,
    SupplierCaptureManager,
    supplier_collector_profile as load_supplier_collector_profile,
)
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

    def northway_policy(self) -> dict: ...

    def supplier_scout_policy(self) -> dict: ...

    def list_supplier_scout_suppliers(self) -> dict: ...

    def inspect_supplier_scout_supplier(self, request: dict) -> dict: ...

    def add_supplier_scout_supplier(self, request: dict) -> dict: ...

    def latest_supplier_snapshot(self, supplier_id: str) -> dict | None: ...

    def create_supplier_capture(self, request: dict) -> dict: ...

    def supplier_collector_profile(self) -> dict: ...

    def pending_supplier_capture(self, shop_host: str) -> dict | None: ...

    def get_supplier_capture(self, capture_id: str) -> dict | None: ...

    def claim_supplier_capture(
        self, capture_id: str, token: str, request: dict
    ) -> dict: ...

    def ingest_supplier_capture_page(
        self, capture_id: str, token: str, request: dict
    ) -> dict: ...

    def pause_supplier_capture(
        self, capture_id: str, token: str, request: dict
    ) -> dict: ...

    def submit_supplier_scout_run(self, request: dict) -> dict: ...

    def get_supplier_scout_run(self, run_id: str) -> dict | None: ...


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

    archetype: str = Field(
        min_length=3,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]{2,79}$",
    )
    discovery_pages: int = Field(default=1, ge=1, le=10)
    request_budget: int = Field(default=20, ge=1, le=500)
    max_1688_checks: int = Field(default=20, ge=0, le=500)
    enable_1688_prefilter: bool = True
    max_amazon_queries_per_family: int = Field(default=3, ge=1, le=5)
    grade_a_max_competitors: int = Field(default=5, ge=0, le=100000)
    grade_a_minus_max_competitors: int = Field(default=8, ge=1, le=100000)
    min_family_price_usd: float = Field(default=20.0, ge=0, le=1000000)
    min_observed_ebay_demand: int = Field(default=1, ge=0, le=1000000)

    @field_validator("archetype")
    @classmethod
    def validate_archetype(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_discovery_budget(self) -> "NorthwayMvpRunRequest":
        required = self.discovery_pages
        if self.request_budget < required:
            raise ValueError(
                "request_budget must cover the selected archetype discovery pages "
                f"({required} requests required)"
            )
        if self.grade_a_minus_max_competitors <= self.grade_a_max_competitors:
            raise ValueError(
                "grade_a_minus_max_competitors must be greater than "
                "grade_a_max_competitors"
            )
        return self


class SupplierScoutInspectRequest(BaseModel):
    """One small read-only canary for a supplier store target."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(min_length=10, max_length=6000)
    max_pages: int = Field(default=1, ge=1, le=3)
    max_offers: int = Field(default=20, ge=1, le=100)
    headed: bool = False
    challenge_timeout_seconds: int = Field(default=180, ge=10, le=600)

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        normalize_1688_supplier_store_target(value)
        return value.strip()


class SupplierScoutSupplierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=10, max_length=6000)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value.strip()

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        normalize_1688_supplier_store_target(value)
        return value.strip()


class SupplierCaptureCreateRequest(BaseModel):
    """Create one bounded user-triggered Edge collection session."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: str = Field(min_length=5, max_length=100, pattern=r"^sup_[a-zA-Z0-9_-]+$")
    max_pages: int = Field(default=3, ge=1, le=20)
    max_offers: int = Field(default=100, ge=1, le=1000)


class SupplierCaptureClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_url: str = Field(min_length=10, max_length=6000)
    extension_version: str | None = Field(default=None, min_length=1, max_length=50)
    parser_version: str | None = Field(default=None, min_length=1, max_length=50)


class SupplierCaptureOfferRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(min_length=1, max_length=30, pattern=r"^[0-9]+$")
    title: str = Field(min_length=1, max_length=500)
    offer_url: str = Field(
        min_length=30,
        max_length=2000,
        pattern=r"^https://detail\.1688\.com/offer/[0-9]+\.html(?:[?#].*)?$",
    )
    image_url: str | None = Field(default=None, min_length=10, max_length=2000)
    price_cny: float | None = Field(default=None, ge=0)
    moq: int | None = Field(default=None, ge=0)

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("https://"):
            raise ValueError("image_url must use HTTPS")
        return value


class SupplierCaptureElementHintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str = Field(min_length=1, max_length=20, pattern=r"^[a-z][a-z0-9-]*$")
    url: str | None = Field(
        default=None,
        max_length=700,
        pattern=r"^https://(?:[a-zA-Z0-9-]+\.)*1688\.com(?:/[^\s#]*)?$",
    )
    text: str | None = Field(default=None, max_length=160)
    class_name: str | None = Field(default=None, max_length=240)
    aria_label: str | None = Field(default=None, max_length=120)
    data_offer_id: str | None = Field(default=None, max_length=30, pattern=r"^[0-9]+$")

    @field_validator("url")
    @classmethod
    def validate_diagnostic_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not re.fullmatch(r"(?:[a-zA-Z0-9-]+\.)*1688\.com", parsed.hostname or "")
        ):
            raise ValueError("diagnostic URLs must be sanitized HTTPS 1688 URLs")
        allowed_keys = {"pageNum", "pageNo", "page", "beginPage", "offerId", "offer_id", "offerid"}
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key not in allowed_keys or not re.fullmatch(r"\d{1,30}", value) for key, value in query):
            raise ValueError("diagnostic URL query parameters must be bounded numeric fields")
        return value


class SupplierCaptureShadowRootHintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str = Field(min_length=1, max_length=20, pattern=r"^[a-z][a-z0-9-]*$")
    class_name: str | None = Field(default=None, max_length=240)
    child_count: int = Field(ge=0, le=1_000_000)
    anchor_count: int = Field(ge=0, le=1_000_000)
    configured_offer_match_count: int = Field(ge=0, le=100_000)
    offer_candidate_count: int = Field(ge=0, le=100_000)
    nested_shadow_host_count: int = Field(ge=0, le=100_000)
    text_length: int = Field(ge=0, le=1_000_000)


class SupplierCaptureDomStructureHintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tag: str = Field(min_length=1, max_length=20, pattern=r"^[a-z][a-z0-9-]*$")
    id_name: str | None = Field(default=None, max_length=120)
    class_name: str | None = Field(default=None, max_length=240)
    role: str | None = Field(default=None, max_length=80)
    child_count: int = Field(ge=0, le=1_000_000)
    anchor_count: int = Field(ge=0, le=1_000_000)
    image_count: int = Field(ge=0, le=1_000_000)
    visible: bool
    identity_attribute_names: list[str] = Field(default_factory=list, max_length=16)
    text_length: int = Field(ge=0, le=1_000_000)

    @field_validator("identity_attribute_names")
    @classmethod
    def validate_identity_attribute_names(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,40}", item) for item in value):
            raise ValueError("DOM identity attribute names must contain attribute names")
        return value


class SupplierCaptureFrameHintRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_class: Literal["1688", "foreign", "blank"]
    url: str | None = Field(
        default=None,
        max_length=700,
        pattern=r"^https://(?:[a-zA-Z0-9-]+\.)*1688\.com(?:/[^\s#]*)?$",
    )
    id_name: str | None = Field(default=None, max_length=120)
    class_name: str | None = Field(default=None, max_length=240)
    title: str | None = Field(default=None, max_length=120)
    visible: bool
    width: int = Field(ge=0, le=10_000)
    height: int = Field(ge=0, le=10_000)
    same_origin_accessible: bool
    anchor_count: int = Field(ge=0, le=1_000_000)
    offer_candidate_count: int = Field(ge=0, le=100_000)
    text_length: int = Field(ge=0, le=1_000_000)


class SupplierCaptureParserProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_count: int = Field(ge=0, le=1_000_000)
    iframe_count: int = Field(ge=0, le=10_000)
    shadow_host_count: int = Field(ge=0, le=10_000)
    configured_offer_match_count: int = Field(ge=0, le=100_000)
    configured_next_match_count: int = Field(ge=0, le=10_000)
    offer_candidates: list[SupplierCaptureElementHintRequest] = Field(
        default_factory=list, max_length=24
    )
    pagination_candidates: list[SupplierCaptureElementHintRequest] = Field(
        default_factory=list, max_length=12
    )
    frame_candidates: list[SupplierCaptureElementHintRequest] = Field(
        default_factory=list, max_length=12
    )
    shadow_root_hints: list[SupplierCaptureShadowRootHintRequest] = Field(
        default_factory=list, max_length=8
    )
    link_candidates: list[SupplierCaptureElementHintRequest] = Field(
        default_factory=list, max_length=24
    )
    light_dom_identity_markers: list[str] = Field(default_factory=list, max_length=24)
    light_dom_structure_hints: list[SupplierCaptureDomStructureHintRequest] = Field(
        default_factory=list, max_length=24
    )
    iframe_hints: list[SupplierCaptureFrameHintRequest] = Field(
        default_factory=list, max_length=8
    )
    embedded_data_markers: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("embedded_data_markers")
    @classmethod
    def validate_embedded_markers(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,50}", item) for item in value):
            raise ValueError("embedded data markers must contain 1-50 characters")
        return value

    @field_validator("light_dom_identity_markers")
    @classmethod
    def validate_identity_markers(cls, value: list[str]) -> list[str]:
        if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,40}", item) for item in value):
            raise ValueError("light DOM identity markers must contain attribute names")
        return value


class SupplierCaptureEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dom_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_title: str | None = Field(default=None, max_length=300)
    profile_id: str | None = Field(default=None, min_length=1, max_length=100)
    parser_probe: SupplierCaptureParserProbeRequest | None = None


class SupplierCapturePageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_number: int = Field(ge=1, le=20)
    page_url: str = Field(min_length=10, max_length=6000)
    has_next_page: bool | None = None
    available_offer_count: int | None = Field(default=None, ge=0)
    empty_state: bool = False
    offers: list[SupplierCaptureOfferRequest] = Field(default_factory=list, max_length=500)
    evidence: SupplierCaptureEvidenceRequest


class SupplierCapturePauseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Literal["AUTH_REQUIRED", "RISK_CONTROL", "PARSER_FAILED", "TIMEOUT"]
    page_url: str = Field(min_length=10, max_length=6000)


class SupplierScoutRunRequest(BaseModel):
    """One supplier source, one immutable inventory snapshot, bounded market checks."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: str = Field(min_length=5, max_length=100, pattern=r"^sup_[a-zA-Z0-9_-]+$")
    inventory_snapshot_id: str | None = Field(
        default=None,
        min_length=6,
        max_length=100,
        pattern=r"^snap_[a-zA-Z0-9_-]+$",
    )
    selected_category_ids: list[str] = Field(default_factory=list, max_length=100)
    max_pages: int = Field(default=3, ge=1, le=20)
    max_offers: int = Field(default=100, ge=1, le=1000)
    headed: bool = False
    challenge_timeout_seconds: int = Field(default=180, ge=10, le=600)
    market_request_budget: int = Field(default=20, ge=0, le=1000)
    max_amazon_queries_per_family: int = Field(default=3, ge=1, le=5)
    grade_a_max_competitors: int = Field(default=5, ge=0, le=100000)
    grade_a_minus_max_competitors: int = Field(default=8, ge=1, le=100000)
    min_family_price_usd: float = Field(default=20.0, ge=0, le=1000000)
    min_observed_ebay_demand: int = Field(default=1, ge=0, le=1000000)

    @field_validator("selected_category_ids")
    @classmethod
    def validate_categories(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", value.strip()):
                raise ValueError("selected_category_ids must contain category identifiers")
            if value.strip() not in cleaned:
                cleaned.append(value.strip())
        return cleaned

    @model_validator(mode="after")
    def validate_grade_order(self) -> "SupplierScoutRunRequest":
        if self.grade_a_minus_max_competitors <= self.grade_a_max_competitors:
            raise ValueError(
                "grade_a_minus_max_competitors must be greater than grade_a_max_competitors"
            )
        return self


def _validate_supplier_snapshot_for_run(snapshot: Mapping[str, Any]) -> None:
    status_value = str(snapshot.get("acquisition_status") or "").upper()
    observed = int(snapshot.get("observed_offer_count") or 0)
    complete = snapshot.get("inventory_complete") is True
    usable = (
        (status_value == "SUCCESS" and complete and observed > 0)
        or (status_value == "EMPTY" and complete and observed == 0)
        or (status_value == "PARTIAL" and observed > 0)
    )
    if not usable:
        raise ValueError(
            "inventory snapshot is not usable for screening; capture visible offers first"
        )


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
                "budget_used": (
                    result.get("request_budget", {}).get("used", 0)
                    if isinstance(result.get("request_budget"), Mapping)
                    else result.get("market_budget", {}).get("used", 0)
                    if isinstance(result.get("market_budget"), Mapping)
                    else 0
                ),
                "updated_at": _utc_now(),
            }

    def get(self, run_id: str) -> dict | None:
        with self._lock:
            value = self._runs.get(run_id)
            return deepcopy(value) if value is not None else None


class DefaultFrontendService:
    def __init__(
        self,
        *,
        category_catalog: CategoryCatalog | None = None,
        supplier_store: SupplierScoutStore | None = None,
        supplier_store_collector: Callable[..., Mapping[str, Any]] | None = None,
    ) -> None:
        self._category_catalog = category_catalog or CategoryCatalog()
        self._supplier_store = supplier_store or SupplierScoutStore()
        self._supplier_store_collector = (
            supplier_store_collector or collect_1688_store_offers
        )
        self._supplier_capture_manager = SupplierCaptureManager(self._supplier_store)
        self._manager = InMemoryRunManager(self._run)
        self._mvp_manager = InMemoryRunManager(self._run_mvp)
        self._northway_manager = InMemoryRunManager(
            self._run_northway,
            supports_progress=True,
        )
        self._supplier_scout_manager = InMemoryRunManager(
            self._run_supplier_scout,
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

    def northway_policy(self) -> dict:
        definitions = self._category_catalog.active_runtime_definitions()
        return northway_mvp_policy(
            definitions,
            category_catalog=self._category_catalog.public_active_catalog(),
        )

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
        category_id = str(request.get("archetype") or "")
        active = self._category_catalog.get_active_definition(category_id)
        snapshot = dict(request)
        snapshot["category_definition"] = runtime_category_definition(
            active["definition"],
            version_id=active["version_id"],
            version_number=active["version_number"],
            status=active["status"],
        )
        return self._northway_manager.submit(snapshot)

    def get_northway_run(self, run_id: str) -> dict | None:
        return self._northway_manager.get(run_id)

    def supplier_scout_policy(self) -> dict:
        definitions = self._category_catalog.active_runtime_definitions()
        policy = supplier_scout_policy(
            definitions,
            category_catalog=self._category_catalog.public_active_catalog(),
        )
        extension_relative_path = Path("browser-extension") / "supplier-collector"
        extension_absolute_path = (
            Path(__file__).resolve().parents[2] / extension_relative_path
        ).resolve()
        policy["edge_collector"] = {
            "protocol_version": CAPTURE_PROTOCOL_VERSION,
            "extension_path": extension_relative_path.as_posix(),
            "extension_path_absolute": str(extension_absolute_path)
            if extension_absolute_path.is_dir()
            else None,
            "api_base": "http://127.0.0.1:8765/api/v1",
            "primary": True,
            "handles_captcha": False,
        }
        return policy

    def list_supplier_scout_suppliers(self) -> dict:
        return self._supplier_store.list_suppliers()

    def inspect_supplier_scout_supplier(self, request: dict) -> dict:
        outcome = dict(
            self._supplier_store_collector(
                request["target"],
                max_pages=request["max_pages"],
                max_offers=request["max_offers"],
                headed=request["headed"],
                challenge_timeout_seconds=request["challenge_timeout_seconds"],
            )
        )
        normalized = normalize_1688_supplier_store_target(request["target"])
        supplier_id = next(
            (
                source["supplier_id"]
                for source in self._supplier_store.list_suppliers()["suppliers"]
                if source["canonical_url"] == normalized["canonical_url"]
            ),
            None,
        )
        outcome["inspection"] = self._supplier_store.save_inspection(
            request["target"], outcome, supplier_id=supplier_id
        )
        return outcome

    def add_supplier_scout_supplier(self, request: dict) -> dict:
        return self._supplier_store.add_supplier(request["label"], request["target"])

    def latest_supplier_snapshot(self, supplier_id: str) -> dict | None:
        self._supplier_store.get_supplier(supplier_id)
        snapshot = self._supplier_store.latest_snapshot(supplier_id)
        if snapshot is None:
            return None
        return {
            key: deepcopy(snapshot.get(key))
            for key in (
                "snapshot_id",
                "supplier_id",
                "snapshot_sha256",
                "retrieved_at",
                "acquisition_status",
                "inventory_complete",
                "pages_attempted",
                "pages_completed",
                "observed_offer_count",
                "available_offer_count",
                "has_next_page",
                "source_method",
                "warnings",
                "diagnostics",
                "page_evidence",
            )
        }

    def create_supplier_capture(self, request: dict) -> dict:
        return self._supplier_capture_manager.create_capture(
            request["supplier_id"],
            max_pages=request["max_pages"],
            max_offers=request["max_offers"],
        )

    def supplier_collector_profile(self) -> dict:
        return load_supplier_collector_profile()

    def pending_supplier_capture(self, shop_host: str) -> dict | None:
        return self._supplier_capture_manager.pending_capture(shop_host=shop_host)

    def get_supplier_capture(self, capture_id: str) -> dict | None:
        try:
            return self._supplier_capture_manager.get_capture(capture_id)
        except CaptureNotFoundError:
            return None

    def claim_supplier_capture(
        self, capture_id: str, token: str, request: dict
    ) -> dict:
        return self._supplier_capture_manager.claim_capture(
            capture_id,
            token,
            page_url=request["page_url"],
            extension_version=request.get("extension_version"),
            parser_version=request.get("parser_version"),
        )

    def ingest_supplier_capture_page(
        self, capture_id: str, token: str, request: dict
    ) -> dict:
        return self._supplier_capture_manager.ingest_page(capture_id, token, request)

    def pause_supplier_capture(
        self, capture_id: str, token: str, request: dict
    ) -> dict:
        return self._supplier_capture_manager.pause_capture(
            capture_id,
            token,
            reason=request["reason"],
            page_url=request["page_url"],
        )

    def _run_supplier_scout(
        self,
        request: dict,
        *,
        progress: Callable[[Mapping[str, Any]], None] | None = None,
    ) -> Mapping[str, Any]:
        source = request["_supplier_source"]
        definitions = request["_category_definitions"]
        captured_snapshot_id = request.get("_inventory_snapshot_id")
        snapshot: dict[str, Any] | None = None
        if captured_snapshot_id:
            snapshot = self._supplier_store.get_snapshot(str(captured_snapshot_id))
            if snapshot.get("supplier_id") != source["supplier_id"]:
                raise ValueError("inventory snapshot belongs to a different supplier")
            _validate_supplier_snapshot_for_run(snapshot)
        if progress is not None:
            progress(
                {
                    "phase": "supplier_inventory",
                    "current": int(snapshot.get("observed_offer_count") or 0)
                    if snapshot
                    else 0,
                    "total": int(snapshot.get("observed_offer_count") or 0)
                    if snapshot
                    else 0,
                    "last_query": source["canonical_url"],
                    "provider": "PROTEUS_EDGE_EXTENSION"
                    if snapshot
                    else "LOCAL_1688_STORE_BRIDGE",
                    "budget_used": 0,
                }
            )
        if snapshot is None:
            snapshot = dict(
                self._supplier_store_collector(
                    source["canonical_url"],
                    max_pages=request["max_pages"],
                    max_offers=request["max_offers"],
                    headed=request["headed"],
                    challenge_timeout_seconds=request["challenge_timeout_seconds"],
                )
            )
            snapshot["supplier_id"] = source["supplier_id"]
            saved = self._supplier_store.save_snapshot(source["supplier_id"], snapshot)
            snapshot.update(saved)
        identity = snapshot.get("supplier")
        if isinstance(identity, Mapping):
            self._supplier_store.update_supplier_identity(source["supplier_id"], identity)
        return run_supplier_scout(
            snapshot,
            category_definitions=definitions,
            selected_category_ids=request["selected_category_ids"],
            serpapi_key=resolve_secret(SERPAPI_API_KEY),
            market_request_budget=request["market_request_budget"],
            max_amazon_queries_per_family=request["max_amazon_queries_per_family"],
            grade_a_max_competitors=request["grade_a_max_competitors"],
            grade_a_minus_max_competitors=request["grade_a_minus_max_competitors"],
            min_family_price_usd=request["min_family_price_usd"],
            min_observed_ebay_demand=request["min_observed_ebay_demand"],
            progress_callback=progress,
        )

    def submit_supplier_scout_run(self, request: dict) -> dict:
        source = self._supplier_store.get_supplier(str(request.get("supplier_id") or ""))
        if source["status"] != "ACTIVE":
            raise ValueError("supplier source is archived")
        definitions = self._category_catalog.active_runtime_definitions()
        selected = list(request.get("selected_category_ids") or definitions.keys())
        unknown = sorted(set(selected) - set(definitions))
        if unknown:
            raise CategoryNotFoundError(
                "selected category is no longer active: " + ", ".join(unknown)
            )
        snapshot = dict(request)
        captured_snapshot_id = request.get("inventory_snapshot_id")
        if captured_snapshot_id:
            captured = self._supplier_store.get_snapshot(str(captured_snapshot_id))
            if captured.get("supplier_id") != source["supplier_id"]:
                raise ValueError("inventory snapshot belongs to a different supplier")
            _validate_supplier_snapshot_for_run(captured)
            snapshot["_inventory_snapshot_id"] = str(captured_snapshot_id)
        snapshot["selected_category_ids"] = selected
        snapshot["_supplier_source"] = source
        snapshot["_category_definitions"] = {
            key: definitions[key] for key in selected
        }
        return self._supplier_scout_manager.submit(snapshot)

    def get_supplier_scout_run(self, run_id: str) -> dict | None:
        return self._supplier_scout_manager.get(run_id)


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
                "supplier-first-store-scout",
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

    def resolved_northway_policy() -> dict:
        policy_getter = getattr(active_service, "northway_policy", None)
        if callable(policy_getter):
            return dict(policy_getter())
        return northway_mvp_policy()

    @app.get("/api/v1/northway/policy")
    def northway_policy() -> dict:
        return resolved_northway_policy()

    @app.post("/api/v1/northway/runs", status_code=status.HTTP_202_ACCEPTED)
    def submit_northway_run(request: NorthwayMvpRunRequest) -> dict:
        category_id = request.archetype
        active_categories = resolved_northway_policy().get("archetypes", {})
        if category_id not in active_categories:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="archetype must be an active Northway leaf category",
            )
        try:
            return active_service.submit_northway_run(request.model_dump())
        except CategoryNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="the selected category is no longer active; refresh and choose again",
            ) from exc

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

    def resolved_supplier_scout_policy() -> dict:
        policy_getter = getattr(active_service, "supplier_scout_policy", None)
        if callable(policy_getter):
            return dict(policy_getter())
        return supplier_scout_policy()

    @app.get("/api/v1/supplier-scout/policy")
    def get_supplier_scout_policy() -> dict:
        return resolved_supplier_scout_policy()

    @app.get("/api/v1/supplier-scout/suppliers")
    def list_supplier_scout_suppliers() -> dict:
        getter = getattr(active_service, "list_supplier_scout_suppliers", None)
        if not callable(getter):
            return {"suppliers": []}
        return dict(getter())

    @app.post("/api/v1/supplier-scout/suppliers/inspect")
    def inspect_supplier_scout_supplier(
        request: SupplierScoutInspectRequest,
    ) -> dict:
        inspector = getattr(active_service, "inspect_supplier_scout_supplier", None)
        if not callable(inspector):
            raise HTTPException(status_code=501, detail="supplier inspection is unavailable")
        try:
            return dict(inspector(request.model_dump()))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/v1/supplier-scout/suppliers",
        status_code=status.HTTP_201_CREATED,
    )
    def add_supplier_scout_supplier(
        request: SupplierScoutSupplierRequest,
    ) -> dict:
        creator = getattr(active_service, "add_supplier_scout_supplier", None)
        if not callable(creator):
            raise HTTPException(status_code=501, detail="supplier storage is unavailable")
        try:
            return dict(creator(request.model_dump()))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/supplier-scout/suppliers/{supplier_id}/snapshots/latest")
    def latest_supplier_snapshot(supplier_id: str) -> dict:
        getter = getattr(active_service, "latest_supplier_snapshot", None)
        if not callable(getter):
            return {"snapshot": None}
        try:
            snapshot = getter(supplier_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="supplier not found") from exc
        return {
            "snapshot": dict(snapshot) if isinstance(snapshot, Mapping) else None
        }

    @app.post(
        "/api/v1/supplier-scout/captures",
        status_code=status.HTTP_201_CREATED,
    )
    def create_supplier_capture(request: SupplierCaptureCreateRequest) -> dict:
        creator = getattr(active_service, "create_supplier_capture", None)
        if not callable(creator):
            raise HTTPException(status_code=501, detail="Edge capture is unavailable")
        try:
            return dict(creator(request.model_dump()))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="supplier not found") from exc
        except (CaptureConflictError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/supplier-scout/collector/profile")
    def get_supplier_collector_profile() -> dict:
        getter = getattr(active_service, "supplier_collector_profile", None)
        return dict(getter()) if callable(getter) else load_supplier_collector_profile()

    @app.get("/api/v1/supplier-scout/captures/pending")
    def pending_supplier_capture(shop_host: str) -> dict:
        getter = getattr(active_service, "pending_supplier_capture", None)
        capture = getter(shop_host) if callable(getter) else None
        return {"capture": dict(capture) if isinstance(capture, Mapping) else None}

    @app.get("/api/v1/supplier-scout/captures/{capture_id}")
    def get_supplier_capture(capture_id: str) -> dict:
        getter = getattr(active_service, "get_supplier_capture", None)
        capture = getter(capture_id) if callable(getter) else None
        if not isinstance(capture, Mapping):
            raise HTTPException(status_code=404, detail="capture not found")
        return dict(capture)

    def capture_mutation_error(exc: Exception) -> HTTPException:
        if isinstance(exc, CaptureNotFoundError):
            return HTTPException(status_code=404, detail="capture not found")
        if isinstance(exc, CaptureAuthorizationError):
            return HTTPException(status_code=403, detail=str(exc))
        if isinstance(exc, CaptureConflictError):
            return HTTPException(status_code=409, detail=str(exc))
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )

    @app.post("/api/v1/supplier-scout/captures/{capture_id}/claim")
    def claim_supplier_capture(
        capture_id: str,
        request: SupplierCaptureClaimRequest,
        capture_token: str = Header(alias="X-Proteus-Capture-Token"),
    ) -> dict:
        claimer = getattr(active_service, "claim_supplier_capture", None)
        if not callable(claimer):
            raise HTTPException(status_code=501, detail="Edge capture is unavailable")
        try:
            return dict(claimer(capture_id, capture_token, request.model_dump()))
        except (CaptureNotFoundError, CaptureAuthorizationError, CaptureConflictError, ValueError) as exc:
            raise capture_mutation_error(exc) from exc

    @app.post("/api/v1/supplier-scout/captures/{capture_id}/pages")
    def ingest_supplier_capture_page(
        capture_id: str,
        request: SupplierCapturePageRequest,
        capture_token: str = Header(alias="X-Proteus-Capture-Token"),
    ) -> dict:
        ingester = getattr(active_service, "ingest_supplier_capture_page", None)
        if not callable(ingester):
            raise HTTPException(status_code=501, detail="Edge capture is unavailable")
        try:
            return dict(ingester(capture_id, capture_token, request.model_dump()))
        except (CaptureNotFoundError, CaptureAuthorizationError, CaptureConflictError, ValueError) as exc:
            raise capture_mutation_error(exc) from exc

    @app.post("/api/v1/supplier-scout/captures/{capture_id}/pause")
    def pause_supplier_capture(
        capture_id: str,
        request: SupplierCapturePauseRequest,
        capture_token: str = Header(alias="X-Proteus-Capture-Token"),
    ) -> dict:
        pauser = getattr(active_service, "pause_supplier_capture", None)
        if not callable(pauser):
            raise HTTPException(status_code=501, detail="Edge capture is unavailable")
        try:
            return dict(pauser(capture_id, capture_token, request.model_dump()))
        except (CaptureNotFoundError, CaptureAuthorizationError, CaptureConflictError, ValueError) as exc:
            raise capture_mutation_error(exc) from exc

    @app.post(
        "/api/v1/supplier-scout/runs",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_supplier_scout_run(request: SupplierScoutRunRequest) -> dict:
        policy_categories = resolved_supplier_scout_policy().get("categories", {})
        selected = request.selected_category_ids or list(policy_categories)
        unknown = sorted(set(selected) - set(policy_categories))
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="selected_category_ids must contain active leaf categories",
            )
        submitter = getattr(active_service, "submit_supplier_scout_run", None)
        if not callable(submitter):
            raise HTTPException(status_code=501, detail="supplier scout runs are unavailable")
        payload = request.model_dump()
        payload["selected_category_ids"] = selected
        try:
            return dict(submitter(payload))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="supplier not found") from exc
        except (CategoryNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    @app.get("/api/v1/supplier-scout/runs/{run_id}")
    def get_supplier_scout_run(run_id: str) -> dict:
        getter = getattr(active_service, "get_supplier_scout_run", None)
        value = getter(run_id) if callable(getter) else None
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        return dict(value)

    def completed_supplier_scout_result(run_id: str) -> Mapping[str, Any]:
        getter = getattr(active_service, "get_supplier_scout_run", None)
        value = getter(run_id) if callable(getter) else None
        if value is None:
            raise HTTPException(status_code=404, detail="run not found")
        if value.get("status") != "COMPLETED" or not isinstance(value.get("result"), Mapping):
            raise HTTPException(status_code=409, detail="run is not complete")
        return value["result"]

    @app.get("/api/v1/supplier-scout/runs/{run_id}/export")
    def export_supplier_scout_run(run_id: str) -> JSONResponse:
        return JSONResponse(
            completed_supplier_scout_result(run_id),
            headers={
                "Content-Disposition": f'attachment; filename="proteus-{run_id}.json"'
            },
        )

    @app.get("/api/v1/supplier-scout/runs/{run_id}/export/compact")
    def export_compact_supplier_scout_run(run_id: str) -> JSONResponse:
        return JSONResponse(
            compact_supplier_scout_result(completed_supplier_scout_result(run_id)),
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
