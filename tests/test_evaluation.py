from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proteus.evaluation import (  # noqa: E402
    decide_opportunity,
    evaluate_amazon_competition_gate,
    evaluate_candidate,
    evaluate_ebay_demand_gate,
    evaluate_supply_gate,
)
from proteus.normalization import normalize_part_number  # noqa: E402


OPPORTUNITY_CASES = json.loads(
    (ROOT / "fixtures" / "opportunity_v0_1_cases.json").read_text(encoding="utf-8")
)
EBAY_CASES = json.loads(
    (ROOT / "fixtures" / "ebay_v0_1_cases.json").read_text(encoding="utf-8")
)
RETRIEVED_AT = "2026-08-25T00:00:00Z"


def _evidence(metric: str, value: object, *, source: str) -> dict:
    source_urls = {
        "AMAZON": "https://www.amazon.com/s?k=53630-53010",
        "1688": "https://detail.1688.com/offer/fixture.html",
        "EBAY": "https://www.ebay.com/sch/i.html?_nkw=53630-53010",
    }
    return {
        "metric": metric,
        "value": value,
        "source": source,
        "url": source_urls[source],
        "retrieved_at": RETRIEVED_AT,
        "extraction_method": "MANUAL_REVIEW",
        "raw_evidence": f"fixture evidence for {metric}",
        "confidence": 1.0,
    }


def _market_context(platform: str, *, exact: bool = True) -> dict:
    if platform == "EBAY":
        context = deepcopy(EBAY_CASES["market_context"])
        if not exact:
            context["locale"] = "ja-JP"
        return context

    context = {
        "marketplace_id": "AMAZON_US",
        "site": "www.amazon.com",
        "locale": "en-US",
        "ship_to_country": "US",
        "ship_to_postal_code": "10001",
        "currency": "USD",
    }
    if not exact:
        context["marketplace_id"] = "AMAZON_CA"
        context["site"] = "www.amazon.ca"
        context["currency"] = "CAD"
    return context


def _listing(
    listing_id: str,
    *,
    sold_count: int | None,
    match_type: str = "EXACT",
    decision: str = "ACCEPT_DEMAND_EVIDENCE",
) -> dict:
    return {
        "listing_id": listing_id,
        "url": f"https://www.ebay.com/itm/{listing_id}",
        "title": "New OEM 53630-53010 Automotive Part",
        "condition": "NEW",
        "price": {"amount": 50.0, "currency": "USD"},
        "sold_count": sold_count,
        "sold_label_raw": None if sold_count is None else f"{sold_count} sold",
        "available_count": None,
        "seller": "fixture-seller",
        "location": "United States",
        "part_numbers": ["53630-53010"],
        "match_type": match_type,
        "decision": decision,
        "evidence": [_evidence("sold_count", sold_count, source="EBAY")],
    }


def _ebay_acquisition(case: dict) -> dict:
    status = case["acquisition_status"]
    eligible_count = case["eligible_listing_count"]
    aggregate = case["aggregate_observed_sold"]
    listings: list[dict] = []

    if status in {"SUCCESS", "PARTIAL_SUCCESS"}:
        if eligible_count:
            sold_counts = [1] * eligible_count
            sold_counts[0] += aggregate - eligible_count
            listings = [
                _listing(f"eligible-{index}", sold_count=sold_count)
                for index, sold_count in enumerate(sold_counts, start=1)
            ]
        elif case.get("ambiguous"):
            listings = [
                _listing(
                    "ambiguous-1",
                    sold_count=5,
                    match_type="AMBIGUOUS",
                    decision="HUMAN_REVIEW",
                )
            ]
        else:
            listings = [
                _listing(
                    "no-sold-1",
                    sold_count=None,
                    decision="REJECT",
                )
            ]

    return {
        "schema_version": "0.1",
        "platform": "EBAY",
        "provider": "fixture",
        "source_method": "MANUAL",
        "query": {
            "raw_part_number": "53630-53010",
            "canonical_part_number": "5363053010",
            "query_type": "EXACT_PART_NUMBER",
        },
        "market_context": _market_context(
            "EBAY", exact=case.get("market_context_exact", True)
        ),
        "status": status,
        "retrieved_at": RETRIEVED_AT,
        "listings": listings,
        "observed_demand": {
            "eligible_listing_count": eligible_count,
            "max_single_listing_sold": max(
                (listing["sold_count"] for listing in listings if listing["sold_count"]),
                default=None,
            ),
            "aggregate_observed_sold": aggregate,
        },
        "diagnostics": [],
    }


def _amazon_evidence(case: dict) -> dict:
    return {
        "acquisition_status": case["acquisition_status"],
        "source_method": "MANUAL",
        "query": "53630-53010",
        "market_context": _market_context(
            "AMAZON", exact=case["market_context_exact"]
        ),
        "relevance_reviewed": case["relevance_reviewed"],
        "relevant_result_count": case["relevant_result_count"],
        "evidence": (
            [
                _evidence(
                    "relevant_result_count",
                    case["relevant_result_count"],
                    source="AMAZON",
                )
            ]
            if case["evidence_present"]
            else []
        ),
    }


def _supply_evidence(case: dict) -> dict:
    evidence = []
    if case["evidence_present"]:
        if case["purchasable"] is not None:
            evidence.append(_evidence("purchasable", case["purchasable"], source="1688"))
        if case["price_cny"] is not None:
            evidence.append(_evidence("price_cny", case["price_cny"], source="1688"))
        if case["moq"] is not None:
            evidence.append(_evidence("moq", case["moq"], source="1688"))
    return {
        "acquisition_status": case["acquisition_status"],
        "source_method": "MANUAL",
        "matched_part_numbers": (
            ["53630-53010"] if case["matched_part_number_present"] else []
        ),
        "match_type": case["match_type"],
        "supplier": "Fixture Supplier" if case["supplier_present"] else None,
        "offer_url": (
            "https://detail.1688.com/offer/fixture.html"
            if case["offer_url_present"]
            else None
        ),
        "purchasable": case["purchasable"],
        "price_cny": case["price_cny"],
        "moq": case["moq"],
        "evidence": evidence,
    }


@pytest.mark.parametrize(
    "case", OPPORTUNITY_CASES["amazon_gate_cases"], ids=lambda case: case["id"]
)
def test_all_amazon_gate_rule_fixtures(case: dict) -> None:
    stage = evaluate_amazon_competition_gate(_amazon_evidence(case))

    assert stage["status"] == case["expected_stage_status"]


def test_amazon_query_must_match_candidate() -> None:
    evidence = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    evidence["query"] = "TOTALLY-DIFFERENT"

    stage = evaluate_amazon_competition_gate(
        evidence,
        expected_canonical_part_number="5363053010",
    )

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "does not match" in stage["reason"]


def test_amazon_count_must_be_bound_to_matching_metric_evidence() -> None:
    evidence = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    evidence["evidence"][0]["metric"] = "unrelated_price"
    evidence["evidence"][0]["value"] = 999999

    stage = evaluate_amazon_competition_gate(evidence)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "bind relevant_result_count" in stage["reason"]


@pytest.mark.parametrize(
    "source_url",
    [
        "https://example.com/s?k=53630-53010",
        "https://amazon.com.example.com/s?k=53630-53010",
        "https://www.amazon.com/s?k=TOTALLY-DIFFERENT",
    ],
)
def test_amazon_count_evidence_requires_matching_real_search_url(
    source_url: str,
) -> None:
    evidence = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    evidence["evidence"][0]["url"] = source_url

    stage = evaluate_amazon_competition_gate(evidence)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "URL" in stage["reason"]


def test_amazon_conflicting_duplicate_count_evidence_requires_review() -> None:
    evidence = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    conflicting = deepcopy(evidence["evidence"][0])
    conflicting["value"] = 999
    evidence["evidence"].append(conflicting)

    stage = evaluate_amazon_competition_gate(evidence)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "conflicts" in stage["reason"]


@pytest.mark.parametrize(
    "case", OPPORTUNITY_CASES["ebay_gate_cases"], ids=lambda case: case["id"]
)
def test_all_ebay_gate_rule_fixtures(case: dict) -> None:
    stage = evaluate_ebay_demand_gate(_ebay_acquisition(case))

    assert stage["status"] == case["expected_stage_status"]


@pytest.mark.parametrize(
    "case", OPPORTUNITY_CASES["supply_gate_cases"], ids=lambda case: case["id"]
)
def test_all_supply_gate_rule_fixtures(case: dict) -> None:
    stage = evaluate_supply_gate(
        _supply_evidence(case),
        max_acceptable_moq=OPPORTUNITY_CASES["policy"]["max_acceptable_moq"],
    )

    assert stage["status"] == case["expected_stage_status"]


@pytest.mark.parametrize(
    ("metric", "conflicting_value"),
    [
        ("purchasable", False),
        ("price_cny", 41),
        ("moq", 9),
    ],
)
def test_supply_pass_rejects_conflicting_summary_evidence(
    metric: str, conflicting_value: object
) -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    record = next(record for record in supply["evidence"] if record["metric"] == metric)
    record["value"] = conflicting_value

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert metric in stage["reason"]


def test_supply_pass_requires_all_three_metric_bindings() -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    supply["evidence"] = [
        record for record in supply["evidence"] if record["metric"] != "price_cny"
    ]

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "price_cny" in stage["reason"]


@pytest.mark.parametrize(
    "evidence_url",
    [
        "https://example.com/offer/fixture.html",
        "https://1688.com.example.com/offer/fixture.html",
        "https://detail.1688.com/offer/different.html",
    ],
)
def test_supply_key_evidence_requires_matching_real_1688_url(evidence_url: str) -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    supply["evidence"][0]["url"] = evidence_url

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "purchasable" in stage["reason"]


def test_supply_offer_url_requires_real_1688_host() -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    supply["offer_url"] = "https://detail.1688.com.example.com/offer/fixture.html"

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "1688 offer URL" in stage["reason"]


def test_not_purchasable_reject_needs_only_matching_purchasable_evidence() -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][2])
    supply["price_cny"] = None
    supply["moq"] = None
    supply["evidence"] = [
        record for record in supply["evidence"] if record["metric"] == "purchasable"
    ]

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REJECTED"


def test_not_purchasable_without_matching_evidence_requires_review() -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][2])
    supply["evidence"] = [
        record for record in supply["evidence"] if record["metric"] != "purchasable"
    ]

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REVIEW_REQUIRED"


def test_high_moq_reject_needs_purchasable_and_moq_evidence_but_not_price() -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][1])
    supply["price_cny"] = None
    supply["evidence"] = [
        record for record in supply["evidence"] if record["metric"] != "price_cny"
    ]

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REJECTED"


def test_conflicting_supply_evidence_cannot_create_opportunity_candidate() -> None:
    ebay = _ebay_acquisition(OPPORTUNITY_CASES["ebay_gate_cases"][0])
    amazon = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    next(
        record for record in supply["evidence"] if record["metric"] == "price_cny"
    )["value"] = 999

    report = evaluate_candidate(
        "53630-53010",
        ebay,
        amazon,
        supply,
        max_acceptable_moq=10,
        generated_at=RETRIEVED_AT,
    )

    assert report["decision"] == "REVIEW_REQUIRED"
    assert report["stages"]["alibaba_1688_supply"]["status"] == "REVIEW_REQUIRED"
    _validate_opportunity_report(report)


@pytest.mark.parametrize(
    "case", OPPORTUNITY_CASES["decision_cases"], ids=lambda case: case["id"]
)
def test_all_final_decision_rule_fixtures(case: dict) -> None:
    decision = decide_opportunity(
        case["amazon_competition"],
        case["ebay_demand"],
        case["alibaba_1688_supply"],
    )

    assert decision == case["expected_decision"]


@pytest.mark.parametrize(
    "case", EBAY_CASES["normalization_cases"], ids=lambda case: case["id"]
)
def test_part_number_normalization_fixtures(case: dict) -> None:
    assert normalize_part_number(case["raw"]) == case["expected_canonical"]


def _validate_opportunity_report(report: dict) -> None:
    schema_path = ROOT / "contracts" / "v0_1_opportunity_report.schema.json"
    acquisition_schema_path = ROOT / "contracts" / "v0_1_acquisition.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    acquisition_schema = json.loads(acquisition_schema_path.read_text(encoding="utf-8"))
    schema["$id"] = schema_path.as_uri()
    acquisition_schema["$id"] = acquisition_schema_path.as_uri()
    registry = Registry().with_resource(
        acquisition_schema_path.as_uri(), Resource.from_contents(acquisition_schema)
    )
    Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    ).validate(report)


def test_candidate_report_passes_all_gates_and_schema() -> None:
    ebay = _ebay_acquisition(OPPORTUNITY_CASES["ebay_gate_cases"][0])
    amazon = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])

    report = evaluate_candidate(
        "53630-53010",
        ebay,
        amazon,
        supply,
        max_acceptable_moq=10,
        generated_at=RETRIEVED_AT,
    )

    assert report["candidate"]["canonical_part_number"] == "5363053010"
    assert report["decision"] == "OPPORTUNITY_CANDIDATE"
    assert [stage["status"] for stage in report["stages"].values()] == [
        "PASSED",
        "PASSED",
        "PASSED",
    ]
    _validate_opportunity_report(report)


def test_ebay_rejection_short_circuits_both_downstream_gates() -> None:
    ebay = _ebay_acquisition(OPPORTUNITY_CASES["ebay_gate_cases"][1])

    report = evaluate_candidate(
        "53630-53010",
        ebay,
        _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0]),
        _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0]),
        max_acceptable_moq=10,
        generated_at=RETRIEVED_AT,
    )

    assert report["decision"] == "REJECTED"
    assert report["stages"]["amazon_competition"] == {
        "status": "NOT_CHECKED",
        "acquisition_status": None,
        "source_method": None,
        "query": None,
        "market_context": None,
        "relevance_reviewed": None,
        "relevant_result_count": None,
        "evidence": [],
        "reason": "Not checked because the eBay demand gate did not pass.",
    }
    assert report["stages"]["alibaba_1688_supply"]["status"] == "NOT_CHECKED"
    _validate_opportunity_report(report)


def test_missing_amazon_evidence_short_circuits_supply_as_review() -> None:
    ebay = _ebay_acquisition(OPPORTUNITY_CASES["ebay_gate_cases"][0])

    report = evaluate_candidate(
        "53630-53010",
        ebay,
        None,
        _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0]),
        max_acceptable_moq=10,
        generated_at=RETRIEVED_AT,
    )

    assert report["decision"] == "REVIEW_REQUIRED"
    assert report["stages"]["amazon_competition"]["status"] == "REVIEW_REQUIRED"
    assert report["stages"]["alibaba_1688_supply"]["status"] == "NOT_CHECKED"
    _validate_opportunity_report(report)


def test_invalid_moq_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_acceptable_moq"):
        evaluate_supply_gate(None, max_acceptable_moq=0)
