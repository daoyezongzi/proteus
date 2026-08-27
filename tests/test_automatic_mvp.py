from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from proteus.automatic_mvp import (
    AMAZON_COLLECTOR,
    DISCOVERY_COLLECTOR,
    EBAY_COMPATIBILITY_COLLECTOR,
    EBAY_DEMAND_COLLECTOR,
    automatic_mvp_policy,
    run_automatic_mvp,
)


def _discovery(**_kwargs: Any) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "retrieved_at": "2026-08-27T10:00:00Z",
        "diagnostics": [],
        "stats": {
            "results_seen": 1,
            "eligible_sold_listings": 1,
            "listings_with_part_number": 1,
            "candidates_emitted": 1,
        },
        "candidates": [
            {
                "raw_part_number": "53630-53010",
                "canonical_part_number": "5363053010",
                "source_listing_id": "123",
                "source_listing_url": "https://www.ebay.com/itm/123",
                "source_listing_title": "New OEM Toyota latch 53630-53010",
                "source_sold_count": 30,
            }
        ],
    }


def _ebay(_part: str, **_kwargs: Any) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "observed_demand": {"eligible_listing_count": 1},
        "listings": [
            {
                "listing_id": "123",
                "condition": "NEW",
                "match_type": "EXACT",
                "decision": "ACCEPT_DEMAND_EVIDENCE",
            }
        ],
        "retrieved_at": "2026-08-27T10:01:00Z",
        "diagnostics": [],
    }


def _amazon(_part: str, **_kwargs: Any) -> dict[str, Any]:
    return {
        "acquisition_status": "SUCCESS",
        "relevant_result_count": 5,
        "minimum_exact_result_price_usd": 31.5,
        "price_observation_complete": True,
        "active_offer_count_lower_bound": 5,
        "active_offer_count_complete": True,
        "retrieved_at": "2026-08-27T10:02:00Z",
        "evidence": [],
    }


def _compatibility(_listing_id: str, **_kwargs: Any) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "listing_id": "123",
        "fitments": [
            {"year": 2015, "make": "Toyota", "model": "Camry", "trim": "LE"}
        ],
        "fitment_count": 1,
        "retrieved_at": "2026-08-27T10:03:00Z",
    }


def _collectors(**overrides: Callable[..., dict]) -> dict[str, Callable[..., dict]]:
    values = {
        DISCOVERY_COLLECTOR: _discovery,
        EBAY_DEMAND_COLLECTOR: _ebay,
        AMAZON_COLLECTOR: _amazon,
        EBAY_COMPATIBILITY_COLLECTOR: _compatibility,
    }
    values.update(overrides)
    return values


def test_automatic_mvp_selects_candidate_for_mandatory_human_review() -> None:
    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        collectors=_collectors(),
    )

    report = result["reports"][0]
    assert report["decision"] == "MVP_OPPORTUNITY_CANDIDATE"
    assert report["human_review_required"] is True
    assert report["stages"]["ebay_recent_sold_lower_bound"]["status"] == "PASSED"
    assert report["stages"]["amazon_us_competition"]["status"] == "PASSED"
    assert report["stages"]["amazon_us_minimum_price"]["status"] == "PASSED"
    assert report["stages"]["amazon_us_active_offers"]["status"] == "PASSED"
    assert "us_active_vehicle_proxy" not in report["stages"]
    assert report["evidence"]["ebay_compatibility"]["listing_id"] == "123"
    assert report["evidence"]["ebay_compatibility"]["fitments"][0]["model"] == "Camry"
    assert "us_active_vehicle_proxy" not in report["evidence"]
    assert result["summary"]["mvp_opportunity_candidates"] == 1
    assert result["discovery"]["status"] == "SUCCESS"
    assert result["discovery"]["pages_attempted"] == 1
    assert result["discovery"]["pages_completed"] == 1
    assert "serp-secret" not in str(result)


def test_discovery_failure_is_not_counted_as_a_completed_page() -> None:
    def failed_discovery(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "HTTP_ERROR",
            "diagnostics": [
                {
                    "code": "HTTP_ERROR",
                    "message": "transport URL error",
                    "raw_marker": None,
                }
            ],
            "candidates": [],
        }

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        discovery_pages=3,
        collectors=_collectors(**{DISCOVERY_COLLECTOR: failed_discovery}),
    )

    assert result["discovery"]["status"] == "HTTP_ERROR"
    assert result["discovery"]["pages_requested"] == 3
    assert result["discovery"]["pages_attempted"] == 1
    assert result["discovery"]["pages_completed"] == 0
    assert result["discovery"]["diagnostics"][0]["code"] == "HTTP_ERROR"
    assert result["reports"] == []


def test_explicit_zero_results_is_a_completed_discovery_page() -> None:
    def zero_results(**_kwargs: Any) -> dict[str, Any]:
        return {"status": "ZERO_RESULTS", "diagnostics": [], "candidates": []}

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        discovery_pages=3,
        collectors=_collectors(**{DISCOVERY_COLLECTOR: zero_results}),
    )

    assert result["discovery"]["status"] == "ZERO_RESULTS"
    assert result["discovery"]["pages_requested"] == 3
    assert result["discovery"]["pages_attempted"] == 1
    assert result["discovery"]["pages_completed"] == 1
    assert result["discovery"]["diagnostics"] == []


def test_no_exact_sold_listing_requires_review_not_rejection() -> None:
    calls = {"amazon": 0}

    def low_demand(part: str, **kwargs: Any) -> dict[str, Any]:
        outcome = _ebay(part, **kwargs)
        outcome["observed_demand"]["eligible_listing_count"] = 0
        return outcome

    def amazon(part: str, **kwargs: Any) -> dict[str, Any]:
        calls["amazon"] += 1
        return _amazon(part, **kwargs)

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        collectors=_collectors(
            **{EBAY_DEMAND_COLLECTOR: low_demand, AMAZON_COLLECTOR: amazon}
        ),
    )

    assert result["reports"][0]["decision"] == "REVIEW_REQUIRED"
    assert calls["amazon"] == 0


def test_amazon_over_threshold_is_a_decisive_rejection() -> None:
    def crowded(part: str, **kwargs: Any) -> dict[str, Any]:
        outcome = _amazon(part, **kwargs)
        outcome["relevant_result_count"] = 6
        return outcome

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        collectors=_collectors(**{AMAZON_COLLECTOR: crowded}),
    )

    assert result["reports"][0]["decision"] == "REJECTED"


def test_amazon_price_at_or_below_threshold_is_rejected() -> None:
    def cheap(part: str, **kwargs: Any) -> dict[str, Any]:
        outcome = _amazon(part, **kwargs)
        outcome["minimum_exact_result_price_usd"] = 20.0
        return outcome

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        min_amazon_price_usd=20.0,
        collectors=_collectors(**{AMAZON_COLLECTOR: cheap}),
    )

    report = result["reports"][0]
    assert report["decision"] == "REJECTED"
    assert report["stages"]["amazon_us_minimum_price"]["status"] == "REJECTED"


def test_amazon_offer_lower_bound_over_frontend_limit_is_rejected() -> None:
    def saturated(part: str, **kwargs: Any) -> dict[str, Any]:
        outcome = _amazon(part, **kwargs)
        outcome["active_offer_count_lower_bound"] = 343
        outcome["active_offer_count_complete"] = False
        return outcome

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        max_amazon_active_sellers=10,
        collectors=_collectors(**{AMAZON_COLLECTOR: saturated}),
    )

    report = result["reports"][0]
    assert report["decision"] == "REJECTED"
    assert report["stages"]["amazon_us_active_offers"]["value"] == 343
    assert report["stages"]["amazon_us_active_offers"]["threshold"] == 10


def test_incomplete_amazon_offer_count_under_limit_requires_review() -> None:
    def incomplete(part: str, **kwargs: Any) -> dict[str, Any]:
        outcome = _amazon(part, **kwargs)
        outcome["active_offer_count_lower_bound"] = 4
        outcome["active_offer_count_complete"] = False
        return outcome

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        max_amazon_active_sellers=10,
        collectors=_collectors(**{AMAZON_COLLECTOR: incomplete}),
    )

    report = result["reports"][0]
    assert report["decision"] == "REVIEW_REQUIRED"
    assert report["stages"]["amazon_us_active_offers"]["status"] == "REVIEW_REQUIRED"


def test_policy_names_configurable_thresholds_without_vehicle_gate() -> None:
    policy = automatic_mvp_policy()

    assert policy["profile"] == "automatic-mvp"
    assert policy["criteria"]["ebay_recent_sold_lower_bound"]["default_threshold"] == 0
    assert policy["criteria"]["amazon_us_exact_competitors"]["default_threshold"] == 5
    assert policy["criteria"]["amazon_us_minimum_price"]["default_threshold"] == 20.0
    assert policy["criteria"]["amazon_us_active_offers"]["default_threshold"] == 10
    assert "us_active_vehicle_proxy" not in policy["criteria"]


def test_discovery_summary_explains_a_successful_page_with_no_oem_candidates() -> None:
    def filtered_discovery(**_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "PARTIAL_SUCCESS",
            "diagnostics": [],
            "stats": {
                "results_seen": 60,
                "eligible_sold_listings": 49,
                "listings_with_part_number": 0,
                "candidates_emitted": 0,
            },
            "candidates": [],
        }

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        collectors=_collectors(**{DISCOVERY_COLLECTOR: filtered_discovery}),
    )

    assert result["discovery"]["results_seen"] == 60
    assert result["discovery"]["eligible_sold_listings"] == 49
    assert result["discovery"]["listings_with_part_number"] == 0
    assert result["discovery"]["candidates_emitted"] == 0
