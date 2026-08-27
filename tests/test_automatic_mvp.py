from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from proteus.automatic_mvp import (
    AMAZON_COLLECTOR,
    DISCOVERY_COLLECTOR,
    EBAY_COMPATIBILITY_COLLECTOR,
    EBAY_DEMAND_COLLECTOR,
    MARKETCHECK_COLLECTOR,
    automatic_mvp_policy,
    run_automatic_mvp,
)
from proteus.io import InputDataError


def _discovery(**_kwargs: Any) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "retrieved_at": "2026-08-27T10:00:00Z",
        "diagnostics": [],
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
        "observed_demand": {"eligible_listing_count": 21},
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


def _marketcheck(_fitments: list[dict], **_kwargs: Any) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "metric": "US_USED_ACTIVE_INVENTORY_DISTINCT_VIN_PROXY",
        "vehicle_count_proxy": 10000,
        "official_vio": False,
        "fitment_resolution": "YMMT_ONLY",
        "retrieved_at": "2026-08-27T10:04:00Z",
    }


def _collectors(**overrides: Callable[..., dict]) -> dict[str, Callable[..., dict]]:
    values = {
        DISCOVERY_COLLECTOR: _discovery,
        EBAY_DEMAND_COLLECTOR: _ebay,
        AMAZON_COLLECTOR: _amazon,
        EBAY_COMPATIBILITY_COLLECTOR: _compatibility,
        MARKETCHECK_COLLECTOR: _marketcheck,
    }
    values.update(overrides)
    return values


def test_automatic_mvp_selects_candidate_for_mandatory_human_review() -> None:
    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        marketcheck_key="market-secret",
        min_us_active_vins=5000,
        collectors=_collectors(),
    )

    report = result["reports"][0]
    assert report["decision"] == "MVP_OPPORTUNITY_CANDIDATE"
    assert report["human_review_required"] is True
    assert report["stages"]["ebay_recent_sold_lower_bound"]["status"] == "PASSED"
    assert report["stages"]["amazon_us_competition"]["status"] == "PASSED"
    assert report["stages"]["us_active_vehicle_proxy"]["status"] == "PASSED"
    assert report["evidence"]["ebay_compatibility"]["listing_id"] == "123"
    assert report["evidence"]["ebay_compatibility"]["fitments"][0]["model"] == "Camry"
    assert report["evidence"]["us_active_vehicle_proxy"]["official_vio"] is False
    assert result["summary"]["mvp_opportunity_candidates"] == 1
    assert "serp-secret" not in str(result)
    assert "market-secret" not in str(result)


def test_insufficient_recent_sold_subset_requires_review_not_rejection() -> None:
    calls = {"amazon": 0}

    def low_demand(part: str, **kwargs: Any) -> dict[str, Any]:
        outcome = _ebay(part, **kwargs)
        outcome["observed_demand"]["eligible_listing_count"] = 20
        return outcome

    def amazon(part: str, **kwargs: Any) -> dict[str, Any]:
        calls["amazon"] += 1
        return _amazon(part, **kwargs)

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        marketcheck_key="market-secret",
        min_us_active_vins=5000,
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
        marketcheck_key="market-secret",
        min_us_active_vins=5000,
        collectors=_collectors(**{AMAZON_COLLECTOR: crowded}),
    )

    assert result["reports"][0]["decision"] == "REJECTED"


def test_vehicle_proxy_below_threshold_requires_review_not_rejection() -> None:
    def sparse(fitments: list[dict], **kwargs: Any) -> dict[str, Any]:
        outcome = _marketcheck(fitments, **kwargs)
        outcome["vehicle_count_proxy"] = 4999
        return outcome

    result = run_automatic_mvp(
        serpapi_key="serp-secret",
        marketcheck_key="market-secret",
        min_us_active_vins=5000,
        collectors=_collectors(**{MARKETCHECK_COLLECTOR: sparse}),
    )

    report = result["reports"][0]
    assert report["decision"] == "REVIEW_REQUIRED"
    assert report["stages"]["us_active_vehicle_proxy"]["status"] == "REVIEW_REQUIRED"


def test_policy_names_proxy_boundary_and_configurable_thresholds() -> None:
    policy = automatic_mvp_policy()

    assert policy["profile"] == "automatic-mvp"
    assert policy["criteria"]["ebay_recent_sold_lower_bound"]["default_threshold"] == 20
    assert policy["criteria"]["amazon_us_exact_competitors"]["default_threshold"] == 5
    assert policy["criteria"]["us_active_vehicle_proxy"]["threshold_required_per_run"] is True
    assert policy["criteria"]["us_active_vehicle_proxy"]["official_vio"] is False


def test_missing_marketcheck_key_blocks_before_discovery() -> None:
    with pytest.raises(InputDataError, match="MARKETCHECK_API_KEY"):
        run_automatic_mvp(
            serpapi_key="serp-secret",
            marketcheck_key=None,
            min_us_active_vins=5000,
            collectors=_collectors(),
        )
