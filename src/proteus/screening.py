"""Deterministic policy for the strict market-opportunity screening profile."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from proteus.normalization import normalize_part_number


STRICT_SCREENING_PROFILE = "strict-market-screening"
EBAY_ANNUAL_WINDOW_DAYS = 365
MIN_EBAY_ANNUAL_UNITS_EXCLUSIVE = 20
MAX_AMAZON_US_EXACT_COMPETITORS = 5


def screening_policy() -> dict[str, Any]:
    """Return a frontend-safe statement of thresholds, services and readiness."""

    return {
        "profile": STRICT_SCREENING_PROFILE,
        "decision": "MARKET_OPPORTUNITY_CANDIDATE",
        "criteria": {
            "ebay_annual_units_sold": {
                "operator": "GT",
                "threshold": MIN_EBAY_ANNUAL_UNITS_EXCLUSIVE,
                "window_days": EBAY_ANNUAL_WINDOW_DAYS,
                "marketplace_id": "EBAY_US",
            },
            "amazon_us_exact_competitors": {
                "operator": "LTE",
                "threshold": MAX_AMAZON_US_EXACT_COMPETITORS,
                "marketplace_id": "AMAZON_US",
            },
            "us_compatible_vehicle_parc": {
                "operator": "GTE",
                "threshold": None,
                "threshold_required_per_run": True,
                "country_code": "US",
            },
        },
        "providers": {
            "marketplace_discovery_and_amazon": {
                "primary": "serpapi",
                "configuration": "SERPAPI_API_KEY",
                "implementation_status": "AMAZON_ADAPTER_AVAILABLE",
            },
            "ebay_annual_sales": {
                "primary": "ebay-product-research-import",
                "configuration": "authorized Seller Hub export or normalized evidence",
                "implementation_status": "NORMALIZED_EVIDENCE_API_AVAILABLE",
            },
            "vehicle_parc": {
                "primary": "tecalliance-vio",
                "configuration": "commercial onboarding required",
                "implementation_status": "PROVIDER_CONTRACT_RESERVED",
                "fallback": "experian-vio",
            },
            "supply_verification": {
                "primary": None,
                "optional_compatibility": "hiobuy-1688",
                "implementation_status": "OUTSIDE_MARKET_SCREENING",
            },
        },
        "qualification_boundary": (
            "Market qualification does not prove source availability, landed cost, "
            "margin or orderability."
        ),
    }


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _source_is_bound(evidence: Mapping[str, Any]) -> bool:
    for field in ("provider_id", "source_reference", "retrieved_at"):
        value = evidence.get(field)
        if not isinstance(value, str) or not value.strip():
            return False
    try:
        parsed = datetime.fromisoformat(str(evidence["retrieved_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _review(reason: str) -> dict[str, Any]:
    return {"status": "REVIEW_REQUIRED", "value": None, "reason": reason}


def _ebay_stage(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return _review("Trailing-365-day eBay sales evidence is missing.")
    units = _nonnegative_integer(value.get("units_sold"))
    if (
        not _source_is_bound(value)
        or value.get("marketplace_id") != "EBAY_US"
        or value.get("window_days") != EBAY_ANNUAL_WINDOW_DAYS
        or units is None
    ):
        return _review("eBay evidence is not bound to EBAY_US and an exact 365-day window.")
    passed = units > MIN_EBAY_ANNUAL_UNITS_EXCLUSIVE
    return {
        "status": "PASSED" if passed else "REJECTED",
        "value": units,
        "operator": "GT",
        "threshold": MIN_EBAY_ANNUAL_UNITS_EXCLUSIVE,
        "window_days": EBAY_ANNUAL_WINDOW_DAYS,
        "provider_id": value["provider_id"],
        "source_reference": value["source_reference"],
        "retrieved_at": value["retrieved_at"],
        "reason": (
            "Observed eBay sales exceed twenty units in the trailing year."
            if passed
            else "Observed eBay sales do not exceed twenty units in the trailing year."
        ),
    }


def _amazon_stage(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return _review("Amazon US exact-competition evidence is missing.")
    count = _nonnegative_integer(value.get("exact_competitor_count"))
    if (
        not _source_is_bound(value)
        or value.get("marketplace_id") != "AMAZON_US"
        or count is None
    ):
        return _review("Amazon evidence is not bound to an exact AMAZON_US result count.")
    passed = count <= MAX_AMAZON_US_EXACT_COMPETITORS
    return {
        "status": "PASSED" if passed else "REJECTED",
        "value": count,
        "operator": "LTE",
        "threshold": MAX_AMAZON_US_EXACT_COMPETITORS,
        "provider_id": value["provider_id"],
        "source_reference": value["source_reference"],
        "retrieved_at": value["retrieved_at"],
        "reason": (
            "Amazon US has at most five exact competitors."
            if passed
            else "Amazon US has more than five exact competitors."
        ),
    }


def _vehicle_stage(value: object, min_us_vehicle_parc: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return _review("Compatible US vehicle-parc evidence is missing.")
    count = _nonnegative_integer(value.get("compatible_vehicle_count"))
    if (
        not _source_is_bound(value)
        or value.get("country_code") != "US"
        or value.get("fitment_resolved") is not True
        or count is None
    ):
        return _review("Vehicle-parc evidence is not bound to resolved US fitment.")
    passed = count >= min_us_vehicle_parc
    return {
        "status": "PASSED" if passed else "REJECTED",
        "value": count,
        "operator": "GTE",
        "threshold": min_us_vehicle_parc,
        "provider_id": value["provider_id"],
        "source_reference": value["source_reference"],
        "retrieved_at": value["retrieved_at"],
        "reason": (
            "Compatible US vehicle parc meets the configured threshold."
            if passed
            else "Compatible US vehicle parc is below the configured threshold."
        ),
    }


def evaluate_strict_market_screening(
    raw_part_number: str,
    evidence: Mapping[str, Any],
    *,
    min_us_vehicle_parc: int,
) -> dict[str, Any]:
    """Apply the three user-approved market gates to normalized evidence."""

    canonical = normalize_part_number(raw_part_number)
    if (
        isinstance(min_us_vehicle_parc, bool)
        or not isinstance(min_us_vehicle_parc, int)
        or min_us_vehicle_parc < 1
    ):
        raise ValueError("min_us_vehicle_parc must be a positive integer")
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence must be an object")

    stages = {
        "ebay_annual_sales": _ebay_stage(evidence.get("ebay_annual_sales")),
        "amazon_competition": _amazon_stage(evidence.get("amazon_competition")),
        "vehicle_parc": _vehicle_stage(
            evidence.get("vehicle_parc"),
            min_us_vehicle_parc,
        ),
    }
    statuses = {stage["status"] for stage in stages.values()}
    decision = (
        "REJECTED"
        if "REJECTED" in statuses
        else "MARKET_OPPORTUNITY_CANDIDATE"
        if statuses == {"PASSED"}
        else "REVIEW_REQUIRED"
    )
    return {
        "schema_version": "0.2.2",
        "profile": STRICT_SCREENING_PROFILE,
        "part_number": {
            "raw": raw_part_number,
            "canonical": canonical,
        },
        "decision": decision,
        "stages": stages,
        "supply_verification": "NOT_EVALUATED",
    }


__all__ = [
    "EBAY_ANNUAL_WINDOW_DAYS",
    "MAX_AMAZON_US_EXACT_COMPETITORS",
    "MIN_EBAY_ANNUAL_UNITS_EXCLUSIVE",
    "STRICT_SCREENING_PROFILE",
    "evaluate_strict_market_screening",
    "screening_policy",
]
