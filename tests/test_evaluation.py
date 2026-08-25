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
from proteus.io import ContractValidationError, validate_opportunity_report  # noqa: E402
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
    schema_path = ROOT / "contracts" / "v0_2_opportunity_report.schema.json"
    acquisition_schema_path = ROOT / "contracts" / "v0_2_acquisition.schema.json"
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
    assert report["stages"]["alibaba_1688_supply"]["order_preview"] is None
    _validate_opportunity_report(report)


def test_ebay_rejection_short_circuits_only_supply_gate() -> None:
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
    assert report["stages"]["amazon_competition"]["status"] == "PASSED"
    assert report["stages"]["ebay_demand"]["status"] == "REJECTED"
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
    assert report["stages"]["ebay_demand"]["status"] == "NOT_CHECKED"
    assert report["stages"]["alibaba_1688_supply"]["status"] == "NOT_CHECKED"
    _validate_opportunity_report(report)


def test_deterministic_managed_amazon_exact_count_can_pass() -> None:
    amazon = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    amazon["source_method"] = "MANAGED_API"
    amazon.pop("relevance_reviewed")
    amazon["relevance_method"] = "DETERMINISTIC_EXACT"
    for evidence in amazon["evidence"]:
        evidence["extraction_method"] = "MANAGED_API"

    stage = evaluate_amazon_competition_gate(
        amazon,
        expected_canonical_part_number="5363053010",
    )

    assert stage["status"] == "PASSED"
    assert stage["relevance_method"] == "DETERMINISTIC_EXACT"


def test_partial_ebay_page_without_sold_evidence_requires_review() -> None:
    ebay = _ebay_acquisition(OPPORTUNITY_CASES["ebay_gate_cases"][2])
    ebay["status"] = "PARTIAL_SUCCESS"
    ebay["diagnostics"] = [
        {
            "code": "CARD_SKIPPED",
            "message": "Provider returned an incomplete page.",
            "raw_marker": "provider_page_complete=false",
        }
    ]

    stage = evaluate_ebay_demand_gate(ebay)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "Partial eBay results" in stage["reason"]


def test_ebay_sold_summary_requires_matching_field_evidence() -> None:
    ebay = _ebay_acquisition(OPPORTUNITY_CASES["ebay_gate_cases"][0])
    for listing in ebay["listings"]:
        for evidence in listing["evidence"]:
            if evidence["metric"] == "sold_count":
                evidence["value"] = 999

    stage = evaluate_ebay_demand_gate(ebay)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert stage["acquisition"]["observed_demand"]["aggregate_observed_sold"] == 0


def test_partial_managed_amazon_results_cannot_prove_low_competition() -> None:
    amazon = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    amazon["acquisition_status"] = "PARTIAL_SUCCESS"
    amazon["source_method"] = "MANAGED_API"
    amazon.pop("relevance_reviewed")
    amazon["relevance_method"] = "DETERMINISTIC_EXACT"
    for evidence in amazon["evidence"]:
        evidence["extraction_method"] = "MANAGED_API"

    stage = evaluate_amazon_competition_gate(amazon)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "Partial Amazon API results" in stage["reason"]


def test_managed_1688_listing_cannot_replace_order_preview() -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    supply["source_method"] = "MANAGED_API"
    for evidence in supply["evidence"]:
        evidence["extraction_method"] = "MANAGED_API"

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "order preview" in stage["reason"]


@pytest.mark.parametrize("source_method", ["BROWSER", "HTTP", "SEARCH"])
def test_non_manual_supply_cannot_pass_without_structured_preview(
    source_method: str,
) -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    supply["source_method"] = source_method
    for record in supply["evidence"]:
        if record["metric"] == "purchasable":
            record["extraction_method"] = "ORDER_PREVIEW"

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REVIEW_REQUIRED"
    assert "structured order preview" in stage["reason"]


def test_api_not_purchasable_preview_remains_a_rejection() -> None:
    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][2])
    supply["source_method"] = "OFFICIAL_API"
    purchasable_record = next(
        record for record in supply["evidence"] if record["metric"] == "purchasable"
    )
    purchasable_record["extraction_method"] = "ORDER_PREVIEW"
    supply["order_preview"] = {
        "provider": "HIOBUY_STANDARD",
        "request_id": "preview-unavailable",
        "offer_id": "fixture",
        "sku_id": "fixture-sku",
        "quantity": 1,
        "currency": "CNY",
        "payment_cny": None,
        "shipping_cny": None,
        "retrieved_at": RETRIEVED_AT,
    }
    binding = {
        key: supply["order_preview"][key]
        for key in ("provider", "request_id", "offer_id", "sku_id", "quantity")
    }
    purchasable_record["preview_binding"] = binding

    stage = evaluate_supply_gate(supply, max_acceptable_moq=10)

    assert stage["status"] == "REJECTED"
    assert stage["order_preview"]["request_id"] == "preview-unavailable"


def _automation_ready_inputs() -> tuple[dict, dict, dict, dict]:
    ebay = _ebay_acquisition(OPPORTUNITY_CASES["ebay_gate_cases"][0])
    ebay["schema_version"] = "0.2"
    ebay["source_method"] = "OFFICIAL_API"
    for listing in ebay["listings"]:
        for evidence in listing["evidence"]:
            evidence["extraction_method"] = "OFFICIAL_API"

    amazon = _amazon_evidence(OPPORTUNITY_CASES["amazon_gate_cases"][0])
    amazon["source_method"] = "OFFICIAL_API"
    amazon.pop("relevance_reviewed")
    amazon["relevance_method"] = "DETERMINISTIC_EXACT"
    for evidence in amazon["evidence"]:
        evidence["extraction_method"] = "OFFICIAL_API"

    supply = _supply_evidence(OPPORTUNITY_CASES["supply_gate_cases"][0])
    supply["source_method"] = "OFFICIAL_API"
    for evidence in supply["evidence"]:
        evidence["extraction_method"] = (
            "ORDER_PREVIEW"
            if evidence["metric"] == "purchasable"
            else "OFFICIAL_API"
        )
    preview_template = next(
        evidence
        for evidence in supply["evidence"]
        if evidence["metric"] == "purchasable"
    )
    for metric, value in (
        ("preview_payment_cny", 85),
        ("preview_shipping_cny", 5),
    ):
        record = deepcopy(preview_template)
        record["metric"] = metric
        record["value"] = value
        record["raw_evidence"] = f"{metric}={value}"
        supply["evidence"].append(record)
    supply["order_preview"] = {
        "provider": "HIOBUY_STANDARD",
        "request_id": "preview-request-id",
        "offer_id": "fixture",
        "sku_id": "fixture-sku",
        "quantity": 10,
        "currency": "CNY",
        "payment_cny": 85,
        "shipping_cny": 5,
        "retrieved_at": RETRIEVED_AT,
    }
    preview_binding = {
        key: supply["order_preview"][key]
        for key in ("provider", "request_id", "offer_id", "sku_id", "quantity")
    }
    for record in supply["evidence"]:
        record["preview_binding"] = deepcopy(preview_binding)

    candidate_source = {
        "method": "AMAZON_B2B_REPORT_API",
        "provider": "AMAZON_SP_API",
        "source_reference": "report-id",
        "source_row": 2,
        "source_field": "partNumber",
        "identifier_type": "partNumber",
        "category": "Automotive",
        "brand": "Fixture Brand",
        "item_name": "Fixture automotive part",
        "report_generated_at": RETRIEVED_AT,
    }
    return ebay, amazon, supply, candidate_source


def _automation_report(
    ebay: dict,
    amazon: dict,
    supply: dict,
    candidate_source: dict,
) -> dict:
    return evaluate_candidate(
        "53630-53010",
        ebay,
        amazon,
        supply,
        max_acceptable_moq=10,
        candidate_source=candidate_source,
        generated_at=RETRIEVED_AT,
    )


def test_official_api_only_report_can_be_automation_qualified() -> None:
    report = _automation_report(*_automation_ready_inputs())

    assert report["decision"] == "OPPORTUNITY_CANDIDATE"
    assert report["automation_qualified"] is True
    _validate_opportunity_report(report)
    validate_opportunity_report(report)


@pytest.mark.parametrize(
    "stale_surface",
    [
        "candidate_report",
        "amazon_evidence",
        "ebay_acquisition",
        "ebay_evidence",
        "supply_evidence",
        "order_preview",
    ],
)
def test_stale_official_data_is_not_automation_qualified(
    stale_surface: str,
) -> None:
    ebay, amazon, supply, candidate_source = _automation_ready_inputs()
    if stale_surface == "candidate_report":
        candidate_source["report_generated_at"] = "2026-08-16T23:59:59Z"
    elif stale_surface == "amazon_evidence":
        amazon["evidence"][0]["retrieved_at"] = "2026-08-23T23:59:59Z"
    elif stale_surface == "ebay_acquisition":
        ebay["retrieved_at"] = "2026-08-23T23:59:59Z"
    elif stale_surface == "ebay_evidence":
        ebay["listings"][0]["evidence"][0]["retrieved_at"] = (
            "2026-08-23T23:59:59Z"
        )
    elif stale_surface == "supply_evidence":
        next(
            record
            for record in supply["evidence"]
            if record["metric"] == "price_cny"
        )["retrieved_at"] = "2026-08-23T23:59:59Z"
    else:
        supply["order_preview"]["retrieved_at"] = "2026-08-24T23:44:59Z"
        for record in supply["evidence"]:
            if record["extraction_method"] == "ORDER_PREVIEW":
                record["retrieved_at"] = "2026-08-24T23:44:59Z"

    report = _automation_report(ebay, amazon, supply, candidate_source)

    assert report["decision"] == "OPPORTUNITY_CANDIDATE"
    assert report["automation_qualified"] is False
    _validate_opportunity_report(report)


def test_validate_report_rejects_forged_automation_claim() -> None:
    ebay, amazon, supply, candidate_source = _automation_ready_inputs()
    amazon["evidence"][0]["retrieved_at"] = "2020-01-01T00:00:00Z"
    report = _automation_report(ebay, amazon, supply, candidate_source)
    assert report["automation_qualified"] is False
    report["automation_qualified"] = True

    with pytest.raises(ContractValidationError, match="automation semantics"):
        validate_opportunity_report(report)


@pytest.mark.parametrize("field_name", ["provider", "request_id", "sku_id"])
def test_validate_report_rejects_mutated_preview_identity(field_name: str) -> None:
    report = _automation_report(*_automation_ready_inputs())
    report["stages"]["alibaba_1688_supply"]["order_preview"][field_name] = (
        f"unrelated-{field_name}"
    )

    with pytest.raises(ContractValidationError, match="automation semantics"):
        validate_opportunity_report(report)


@pytest.mark.parametrize(
    ("surface", "extraction_method"),
    [
        ("amazon", "MANAGED_API"),
        ("amazon", "MANUAL_REVIEW"),
        ("ebay", "MANAGED_API"),
        ("ebay", "MANUAL_REVIEW"),
        ("supply_price", "MANAGED_API"),
        ("supply_price", "MANUAL_REVIEW"),
        ("supply_moq", "MANAGED_API"),
        ("supply_moq", "MANUAL_REVIEW"),
    ],
)
def test_validate_report_rejects_mixed_official_provenance(
    surface: str,
    extraction_method: str,
) -> None:
    report = _automation_report(*_automation_ready_inputs())
    if surface == "amazon":
        record = report["stages"]["amazon_competition"]["evidence"][0]
    elif surface == "ebay":
        record = report["stages"]["ebay_demand"]["acquisition"]["listings"][0][
            "evidence"
        ][0]
    else:
        metric = "price_cny" if surface == "supply_price" else "moq"
        record = next(
            item
            for item in report["stages"]["alibaba_1688_supply"]["evidence"]
            if item["metric"] == metric
        )
    record["extraction_method"] = extraction_method

    with pytest.raises(ContractValidationError, match="automation semantics"):
        validate_opportunity_report(report)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("provider", "USER_INPUT"),
        ("source_reference", None),
        ("source_row", None),
        ("source_field", None),
        ("identifier_type", None),
        ("category", "Industrial"),
    ],
)
def test_validate_report_rejects_incomplete_api_candidate_provenance(
    field_name: str,
    invalid_value: object,
) -> None:
    report = _automation_report(*_automation_ready_inputs())
    report["candidate_source"][field_name] = invalid_value

    with pytest.raises(ContractValidationError):
        validate_opportunity_report(report)


def test_non_qualified_opportunity_still_requires_bound_supply_semantics() -> None:
    report = _automation_report(*_automation_ready_inputs())
    report["automation_qualified"] = False
    report["stages"]["alibaba_1688_supply"]["order_preview"]["sku_id"] = (
        "unrelated-sku"
    )

    with pytest.raises(ContractValidationError, match="opportunity semantics"):
        validate_opportunity_report(report)


def test_schema_rejects_managed_api_as_automation_qualified() -> None:
    report = _automation_report(*_automation_ready_inputs())
    report["stages"]["amazon_competition"]["source_method"] = "MANAGED_API"
    report["stages"]["ebay_demand"]["acquisition"]["source_method"] = (
        "MANAGED_API"
    )
    report["stages"]["alibaba_1688_supply"]["source_method"] = "MANAGED_API"

    with pytest.raises(ContractValidationError):
        validate_opportunity_report(report)


def test_invalid_moq_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_acceptable_moq"):
        evaluate_supply_gate(None, max_acceptable_moq=0)
