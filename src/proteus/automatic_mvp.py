"""Threshold-driven automatic MVP that produces human-review candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from proteus.io import InputDataError
from proteus.normalization import normalize_part_number
from proteus.providers.ny_registration import collect_ny_registered_vehicle_proxy
from proteus.providers.serpapi_amazon import collect_amazon_competition
from proteus.providers.serpapi_ebay import collect_ebay_sold
from proteus.providers.serpapi_ebay_discovery import (
    DEFAULT_CATEGORY_ID,
    collect_ebay_sold_candidates,
)
from proteus.providers.serpapi_ebay_product import collect_ebay_compatibility


DISCOVERY_COLLECTOR = "ebay_candidate_discovery"
EBAY_DEMAND_COLLECTOR = "ebay_recent_sold"
AMAZON_COLLECTOR = "amazon_us_competition"
EBAY_COMPATIBILITY_COLLECTOR = "ebay_compatibility"
VEHICLE_PROXY_COLLECTOR = "vehicle_population_proxy"
# Compatibility key for callers that injected the old MarketCheck collector.
MARKETCHECK_COLLECTOR = "marketcheck_us_vehicle_proxy"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _required_secret(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputDataError(f"{name} is not configured; run 'proteus setup' first")
    return value.strip()


def _limit(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def automatic_mvp_policy() -> dict[str, Any]:
    return {
        "profile": "automatic-mvp",
        "decision": "MVP_OPPORTUNITY_CANDIDATE",
        "criteria": {
            "ebay_recent_sold_lower_bound": {
                "operator": "GT",
                "default_threshold": 20,
                "source": "SerpApi eBay sold-result distinct exact listing count",
                "strict_365_day_metric": False,
            },
            "amazon_us_exact_competitors": {
                "operator": "LTE",
                "default_threshold": 5,
                "marketplace_id": "AMAZON_US",
            },
            "us_active_vehicle_proxy": {
                "operator": "GTE",
                "default_threshold": None,
                "threshold_required_per_run": True,
                "country_code": "US",
                "official_vio": False,
                "state_code": "NY",
                "source": (
                    "Anonymous NY DMV active-registration count with a bounded "
                    "NHTSA VIN-decoded model estimate"
                ),
            },
        },
        "providers": {
            "candidate_discovery": "serpapi-ebay",
            "ebay_recent_sold": "serpapi-ebay",
            "amazon_us_competition": "serpapi-amazon",
            "compatibility": "serpapi-ebay-product",
            "us_active_vehicle_proxy": "ny-dmv-nhtsa-registration-estimate",
        },
        "human_review_required": True,
        "qualification_boundary": (
            "This heuristic MVP finds review candidates. It does not prove strict 365-day "
            "eBay units or official nationwide vehicles-in-operation. The vehicle "
            "gate is a New York model estimate and requires human review."
        ),
    }


def _stage(
    status: str,
    *,
    value: int | None,
    operator: str | None,
    threshold: int | None,
    reason: str,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": status,
        "value": value,
        "operator": operator,
        "threshold": threshold,
        "reason": reason,
    }
    if evidence is not None:
        result["provider_status"] = evidence.get("status", evidence.get("acquisition_status"))
        result["retrieved_at"] = evidence.get("retrieved_at")
    return result


def _not_run(reason: str) -> dict[str, Any]:
    return _stage(
        "NOT_RUN", value=None, operator=None, threshold=None, reason=reason
    )


def _candidate_identity(candidate: Mapping[str, Any]) -> tuple[str, str]:
    raw = candidate.get("raw_part_number")
    if not isinstance(raw, str):
        raise ValueError("Discovery candidate lacks raw_part_number")
    canonical = normalize_part_number(raw)
    supplied = candidate.get("canonical_part_number")
    if supplied is not None and supplied != canonical:
        raise ValueError("Discovery candidate canonical identity mismatch")
    return raw, canonical


def _eligible_listing_ids(ebay: Mapping[str, Any], maximum: int) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    listings = ebay.get("listings")
    if not isinstance(listings, list):
        return values
    for listing in listings:
        if not isinstance(listing, Mapping):
            continue
        listing_id = listing.get("listing_id")
        if (
            isinstance(listing_id, str)
            and listing_id.strip()
            and listing.get("condition") == "NEW"
            and listing.get("match_type") in {"EXACT", "NORMALIZED_EXACT"}
            and listing.get("decision") == "ACCEPT_DEMAND_EVIDENCE"
            and listing_id not in seen
        ):
            seen.add(listing_id)
            values.append(listing_id)
            if len(values) >= maximum:
                break
    return values


def _blank_report(candidate: Mapping[str, Any]) -> dict[str, Any]:
    raw, canonical = _candidate_identity(candidate)
    return {
        "schema_version": "0.2.3",
        "profile": "automatic-mvp",
        "part_number": {"raw": raw, "canonical": canonical},
        "source": {
            key: candidate.get(key)
            for key in (
                "source_listing_id",
                "source_listing_url",
                "source_listing_title",
                "source_sold_count",
            )
        },
        "decision": "REVIEW_REQUIRED",
        "human_review_required": True,
        "evidence": {},
        "stages": {
            "ebay_recent_sold_lower_bound": _not_run("Not evaluated"),
            "amazon_us_competition": _not_run("Not evaluated"),
            "ebay_compatibility": _not_run("Not evaluated"),
            "us_active_vehicle_proxy": _not_run("Not evaluated"),
        },
    }


def _evaluate_candidate(
    candidate: Mapping[str, Any],
    *,
    serpapi_key: str,
    ebay_threshold: int,
    amazon_threshold: int,
    vehicle_threshold: int,
    max_fitment_listings: int,
    collectors: Mapping[str, Callable[..., Mapping[str, Any]]],
) -> dict[str, Any]:
    report = _blank_report(candidate)
    raw = report["part_number"]["raw"]
    stages = report["stages"]

    ebay = collectors[EBAY_DEMAND_COLLECTOR](raw, api_key=serpapi_key)
    ebay_listings = ebay.get("listings") if isinstance(ebay, Mapping) else None
    report["evidence"]["ebay_recent_sold"] = {
        "provider": ebay.get("provider") if isinstance(ebay, Mapping) else None,
        "retrieved_at": ebay.get("retrieved_at") if isinstance(ebay, Mapping) else None,
        "listing_references": [
            {
                key: listing.get(key)
                for key in ("listing_id", "url", "title", "sold_count")
            }
            for listing in (ebay_listings if isinstance(ebay_listings, list) else [])
            if isinstance(listing, Mapping)
        ][:10],
    }
    observed = ebay.get("observed_demand") if isinstance(ebay, Mapping) else None
    eligible = observed.get("eligible_listing_count") if isinstance(observed, Mapping) else None
    if isinstance(eligible, bool) or not isinstance(eligible, int) or eligible < 0:
        stages["ebay_recent_sold_lower_bound"] = _stage(
            "REVIEW_REQUIRED",
            value=None,
            operator="GT",
            threshold=ebay_threshold,
            reason="Provider did not return a valid distinct exact sold-listing count.",
            evidence=ebay,
        )
        return report
    if eligible <= ebay_threshold:
        stages["ebay_recent_sold_lower_bound"] = _stage(
            "REVIEW_REQUIRED",
            value=eligible,
            operator="GT",
            threshold=ebay_threshold,
            reason=(
                "The provider-visible recent subset does not prove the trailing-year threshold; "
                "it is not treated as a rejection."
            ),
            evidence=ebay,
        )
        return report
    stages["ebay_recent_sold_lower_bound"] = _stage(
        "PASSED",
        value=eligible,
        operator="GT",
        threshold=ebay_threshold,
        reason="Observed distinct exact sold listings exceed the configured MVP threshold.",
        evidence=ebay,
    )

    amazon = collectors[AMAZON_COLLECTOR](raw, api_key=serpapi_key)
    report["evidence"]["amazon_us_competition"] = {
        "provider": amazon.get("provider") if isinstance(amazon, Mapping) else None,
        "retrieved_at": amazon.get("retrieved_at") if isinstance(amazon, Mapping) else None,
        "relevant_result_count": amazon.get("relevant_result_count")
        if isinstance(amazon, Mapping)
        else None,
    }
    count = amazon.get("relevant_result_count") if isinstance(amazon, Mapping) else None
    acquisition_status = amazon.get("acquisition_status") if isinstance(amazon, Mapping) else None
    if (
        acquisition_status not in {"SUCCESS", "ZERO_RESULTS"}
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
    ):
        stages["amazon_us_competition"] = _stage(
            "REVIEW_REQUIRED",
            value=None,
            operator="LTE",
            threshold=amazon_threshold,
            reason="Amazon exact-result count is incomplete or unavailable.",
            evidence=amazon,
        )
        return report
    if count > amazon_threshold:
        stages["amazon_us_competition"] = _stage(
            "REJECTED",
            value=count,
            operator="LTE",
            threshold=amazon_threshold,
            reason="Complete Amazon US exact competitor count exceeds the threshold.",
            evidence=amazon,
        )
        report["decision"] = "REJECTED"
        return report
    stages["amazon_us_competition"] = _stage(
        "PASSED",
        value=count,
        operator="LTE",
        threshold=amazon_threshold,
        reason="Complete Amazon US exact competitor count is within the threshold.",
        evidence=amazon,
    )

    listing_ids = _eligible_listing_ids(ebay, max_fitment_listings)
    compatibility: Mapping[str, Any] | None = None
    for listing_id in listing_ids:
        attempt = collectors[EBAY_COMPATIBILITY_COLLECTOR](
            listing_id, api_key=serpapi_key
        )
        fitments = attempt.get("fitments") if isinstance(attempt, Mapping) else None
        if attempt.get("status") in {"SUCCESS", "PARTIAL_SUCCESS"} and isinstance(fitments, list) and fitments:
            compatibility = attempt
            break
    if compatibility is None:
        stages["ebay_compatibility"] = _stage(
            "REVIEW_REQUIRED",
            value=0,
            operator="GT",
            threshold=0,
            reason="No exact sold listing exposed usable automotive compatibility.",
        )
        return report
    fitments = compatibility["fitments"]
    report["evidence"]["ebay_compatibility"] = {
        "provider": compatibility.get("provider"),
        "listing_id": compatibility.get("listing_id"),
        "retrieved_at": compatibility.get("retrieved_at"),
        "fitment_count": len(fitments),
        "fitments": fitments[:100],
        "fitments_truncated": len(fitments) > 100,
    }
    stages["ebay_compatibility"] = _stage(
        "PASSED",
        value=len(fitments),
        operator="GT",
        threshold=0,
        reason="At least one exact sold listing exposed normalized YMMT fitment.",
        evidence=compatibility,
    )

    vehicle_collector = collectors.get(VEHICLE_PROXY_COLLECTOR)
    if not callable(vehicle_collector):
        vehicle_collector = collectors.get(MARKETCHECK_COLLECTOR)
    if not callable(vehicle_collector):
        raise ValueError("Vehicle proxy collector is not configured")
    vehicle = vehicle_collector(fitments)
    report["evidence"]["us_active_vehicle_proxy"] = {
        key: vehicle.get(key)
        for key in (
            "provider",
            "metric",
            "retrieved_at",
            "fitment_resolution",
            "official_vio",
            "qualification_boundary",
            "country_code",
            "state_code",
            "sampling_randomized",
            "sampling_method",
            "groups",
        )
    }
    proxy = vehicle.get("vehicle_count_proxy") if isinstance(vehicle, Mapping) else None
    if (
        vehicle.get("status") != "SUCCESS"
        or isinstance(proxy, bool)
        or not isinstance(proxy, int)
        or proxy < 0
    ):
        stages["us_active_vehicle_proxy"] = _stage(
            "REVIEW_REQUIRED",
            value=None,
            operator="GTE",
            threshold=vehicle_threshold,
            reason="Complete New York registration model estimate is unavailable.",
            evidence=vehicle,
        )
        return report
    if proxy < vehicle_threshold:
        stages["us_active_vehicle_proxy"] = _stage(
            "REVIEW_REQUIRED",
            value=proxy,
            operator="GTE",
            threshold=vehicle_threshold,
            reason=(
                "New York registration estimate is below threshold, but one-state sampled "
                "coverage cannot decisively reject nationwide vehicle population."
            ),
            evidence=vehicle,
        )
        return report
    stages["us_active_vehicle_proxy"] = _stage(
        "PASSED",
        value=proxy,
        operator="GTE",
        threshold=vehicle_threshold,
        reason="Complete New York registration model estimate meets the MVP threshold.",
        evidence=vehicle,
    )
    report["decision"] = "MVP_OPPORTUNITY_CANDIDATE"
    return report


def run_automatic_mvp(
    *,
    serpapi_key: str | None,
    min_us_active_vins: int,
    marketcheck_key: str | None = None,
    max_candidates: int = 20,
    ebay_category_id: str = DEFAULT_CATEGORY_ID,
    discovery_pages: int = 1,
    min_ebay_trailing_year_units_exclusive: int = 20,
    max_amazon_us_exact_competitors: int = 5,
    max_fitment_listings: int = 3,
    collectors: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Automatically discover and screen rough candidates for later human review."""

    serpapi_secret = _required_secret(serpapi_key, "SERPAPI_API_KEY")
    _limit("max_candidates", max_candidates, 1, 100)
    _limit("discovery_pages", discovery_pages, 1, 10)
    _limit("min_ebay_trailing_year_units_exclusive", min_ebay_trailing_year_units_exclusive, 0, 1000000)
    _limit("max_amazon_us_exact_competitors", max_amazon_us_exact_competitors, 0, 100000)
    _limit("min_us_active_vins", min_us_active_vins, 1, 100000000)
    _limit("max_fitment_listings", max_fitment_listings, 1, 10)
    if not isinstance(ebay_category_id, str) or not ebay_category_id.isdigit():
        raise ValueError("ebay_category_id must contain digits only")

    active_collectors: dict[str, Callable[..., Mapping[str, Any]]] = {
        DISCOVERY_COLLECTOR: collect_ebay_sold_candidates,
        EBAY_DEMAND_COLLECTOR: collect_ebay_sold,
        AMAZON_COLLECTOR: collect_amazon_competition,
        EBAY_COMPATIBILITY_COLLECTOR: collect_ebay_compatibility,
        VEHICLE_PROXY_COLLECTOR: collect_ny_registered_vehicle_proxy,
    }
    if collectors is not None:
        active_collectors.update(collectors)
        if (
            MARKETCHECK_COLLECTOR in collectors
            and VEHICLE_PROXY_COLLECTOR not in collectors
        ):
            legacy_collector = collectors[MARKETCHECK_COLLECTOR]

            def collect_legacy_vehicle_proxy(
                fitments: Sequence[Mapping[str, Any]],
            ) -> Mapping[str, Any]:
                return legacy_collector(fitments, api_key=marketcheck_key)

            active_collectors[VEHICLE_PROXY_COLLECTOR] = collect_legacy_vehicle_proxy
    missing = [name for name in active_collectors if not callable(active_collectors[name])]
    if missing:
        raise ValueError(f"Collectors are not callable: {', '.join(missing)}")

    discovered: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    discovery_diagnostics: list[dict[str, Any]] = []
    pages_completed = 0
    for page in range(1, discovery_pages + 1):
        if len(discovered) >= max_candidates:
            break
        outcome = active_collectors[DISCOVERY_COLLECTOR](
            api_key=serpapi_secret,
            category_id=ebay_category_id,
            max_candidates=max_candidates - len(discovered),
            page=page,
        )
        pages_completed += 1
        for item in outcome.get("diagnostics", []):
            if isinstance(item, Mapping):
                discovery_diagnostics.append({"page": page, **dict(item)})
        if outcome.get("status") not in {"SUCCESS", "PARTIAL_SUCCESS"}:
            discovery_diagnostics.append(
                {
                    "page": page,
                    "code": "DISCOVERY_STOPPED",
                    "message": f"Discovery ended with {outcome.get('status')}",
                }
            )
            break
        candidates = outcome.get("candidates")
        if not isinstance(candidates, list):
            break
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            try:
                _raw, canonical = _candidate_identity(candidate)
            except (TypeError, ValueError):
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            discovered.append(candidate)
            if len(discovered) >= max_candidates:
                break

    reports = [
        _evaluate_candidate(
            candidate,
            serpapi_key=serpapi_secret,
            ebay_threshold=min_ebay_trailing_year_units_exclusive,
            amazon_threshold=max_amazon_us_exact_competitors,
            vehicle_threshold=min_us_active_vins,
            max_fitment_listings=max_fitment_listings,
            collectors=active_collectors,
        )
        for candidate in discovered
    ]
    counts = Counter(report["decision"] for report in reports)
    return {
        "schema_version": "0.2.3",
        "profile": "automatic-mvp",
        "policy": {
            "min_ebay_trailing_year_units_exclusive": min_ebay_trailing_year_units_exclusive,
            "max_amazon_us_exact_competitors": max_amazon_us_exact_competitors,
            "min_us_active_vins": min_us_active_vins,
            "max_fitment_listings": max_fitment_listings,
        },
        "execution": {
            "mode": "AUTOMATIC_HEURISTIC_MVP",
            "human_review_required": True,
            "account_count": 1,
            "provider_count": 2,
        },
        "discovery": {
            "category_id": ebay_category_id,
            "pages_requested": discovery_pages,
            "pages_completed": pages_completed,
            "candidate_count": len(discovered),
            "diagnostics": discovery_diagnostics,
        },
        "reports": reports,
        "summary": {
            "mvp_opportunity_candidates": counts["MVP_OPPORTUNITY_CANDIDATE"],
            "rejected": counts["REJECTED"],
            "review_required": counts["REVIEW_REQUIRED"],
        },
        "completed_at": _utc_now(),
    }


__all__ = [
    "AMAZON_COLLECTOR",
    "DISCOVERY_COLLECTOR",
    "EBAY_COMPATIBILITY_COLLECTOR",
    "EBAY_DEMAND_COLLECTOR",
    "MARKETCHECK_COLLECTOR",
    "VEHICLE_PROXY_COLLECTOR",
    "automatic_mvp_policy",
    "run_automatic_mvp",
]
