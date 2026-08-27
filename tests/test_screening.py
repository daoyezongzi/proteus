from __future__ import annotations

from proteus.screening import evaluate_strict_market_screening, screening_policy


PART_NUMBER = "53630-53010"
RETRIEVED_AT = "2026-08-27T08:00:00Z"


def _source(provider_id: str) -> dict:
    return {
        "provider_id": provider_id,
        "source_reference": f"https://example.invalid/{provider_id}",
        "retrieved_at": RETRIEVED_AT,
    }


def _evidence(*, ebay: int = 21, amazon: int = 5, parc: int = 50000) -> dict:
    return {
        "ebay_annual_sales": {
            **_source("ebay-product-research-import"),
            "marketplace_id": "EBAY_US",
            "window_days": 365,
            "units_sold": ebay,
        },
        "amazon_competition": {
            **_source("serpapi-amazon"),
            "marketplace_id": "AMAZON_US",
            "exact_competitor_count": amazon,
        },
        "vehicle_parc": {
            **_source("tecalliance-vio"),
            "country_code": "US",
            "fitment_resolved": True,
            "compatible_vehicle_count": parc,
        },
    }


def test_strict_screening_passes_only_when_all_three_user_gates_pass() -> None:
    result = evaluate_strict_market_screening(
        PART_NUMBER,
        _evidence(),
        min_us_vehicle_parc=50000,
    )

    assert result["decision"] == "MARKET_OPPORTUNITY_CANDIDATE"
    assert result["schema_version"] == "0.2.2"
    assert {stage["status"] for stage in result["stages"].values()} == {"PASSED"}
    assert result["supply_verification"] == "NOT_EVALUATED"


def test_ebay_gate_is_strictly_greater_than_twenty() -> None:
    result = evaluate_strict_market_screening(
        PART_NUMBER,
        _evidence(ebay=20),
        min_us_vehicle_parc=50000,
    )

    assert result["decision"] == "REJECTED"
    assert result["stages"]["ebay_annual_sales"]["status"] == "REJECTED"


def test_amazon_and_vehicle_parc_reject_immediately_outside_boundaries() -> None:
    too_many_competitors = evaluate_strict_market_screening(
        PART_NUMBER,
        _evidence(amazon=6),
        min_us_vehicle_parc=50000,
    )
    insufficient_parc = evaluate_strict_market_screening(
        PART_NUMBER,
        _evidence(parc=49999),
        min_us_vehicle_parc=50000,
    )

    assert too_many_competitors["decision"] == "REJECTED"
    assert insufficient_parc["decision"] == "REJECTED"


def test_missing_or_semantically_unbound_evidence_requires_review() -> None:
    evidence = _evidence()
    evidence["ebay_annual_sales"] = None
    evidence["vehicle_parc"]["fitment_resolved"] = False

    result = evaluate_strict_market_screening(
        PART_NUMBER,
        evidence,
        min_us_vehicle_parc=50000,
    )

    assert result["decision"] == "REVIEW_REQUIRED"
    assert result["stages"]["ebay_annual_sales"]["status"] == "REVIEW_REQUIRED"
    assert result["stages"]["vehicle_parc"]["status"] == "REVIEW_REQUIRED"


def test_policy_names_selected_services_and_leaves_parc_threshold_explicit() -> None:
    policy = screening_policy()

    assert policy["profile"] == "strict-market-screening"
    assert policy["criteria"]["ebay_annual_units_sold"]["threshold"] == 20
    assert policy["criteria"]["amazon_us_exact_competitors"]["threshold"] == 5
    assert policy["criteria"]["us_compatible_vehicle_parc"]["threshold"] is None
    assert policy["providers"]["vehicle_parc"]["primary"] == "tecalliance-vio"
