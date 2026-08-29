from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from proteus.northway_mvp import (
    ARCHETYPES,
    aggregate_amazon_family_results,
    build_amazon_query_pack,
    classify_scope,
    compact_northway_result,
    northway_mvp_policy,
    resolve_product_family,
    run_northway_mvp,
)


def candidate(
    part_number: str,
    title: str,
    *,
    listing_id: str = "123",
    sold_count: int = 4,
) -> dict:
    return {
        "raw_part_number": part_number,
        "canonical_part_number": part_number.replace("-", ""),
        "source_listing_id": listing_id,
        "source_listing_url": f"https://www.ebay.com/itm/{listing_id}",
        "source_listing_title": title,
        "source_listing_position": 1,
        "source_sold_count": sold_count,
    }


def amazon_result(query: str, products: list[dict], *, complete: bool = True) -> dict:
    return {
        "schema_version": "0.2.4",
        "provider": "SERPAPI_AMAZON_MANAGED",
        "marketplace_id": "AMAZON_US",
        "query": query,
        "search_url": f"https://www.amazon.com/s?k={query}",
        "retrieved_at": "2026-08-28T00:00:00Z",
        "acquisition_status": "SUCCESS" if complete else "PARTIAL_SUCCESS",
        "result_page_complete": complete,
        "has_next_page": not complete,
        "reported_total_results": len(products),
        "results_seen": len(products),
        "products": products,
        "diagnostics": [],
    }


def supplier_result(raw_part_number: str, *, family: dict | None = None, **_kwargs) -> dict:
    return {
        "provider": "TEST_1688",
        "source_method": "TEST_FIXTURE",
        "acquisition_status": "SUCCESS",
        "query": raw_part_number,
        "offer_id": "628196518518",
        "offer_url": "https://detail.1688.com/offer/628196518518.html",
        "title": (family or {}).get("part_type", "automotive part"),
        "supplier": {"id": "supplier-1", "name": "Test Supplier"},
        "supplier_found": True,
        "matched_part_numbers": [raw_part_number],
        "match_type": "IDENTIFIER_OR_FAMILY_MATCH",
        "retrieved_at": "2026-08-28T00:00:00Z",
        "diagnostics": [],
    }


def test_policy_is_narrow_and_has_no_candidate_cap() -> None:
    policy = northway_mvp_policy()

    assert policy["profile"] == "northway-product-family-mvp"
    assert set(policy["category_profiles"]) == {
        "vehicle_specific_small_trim",
        "vehicle_specific_cable",
    }
    assert policy["run_bounds"]["candidate_cap"] is None
    assert policy["run_bounds"]["request_budget"]["minimum"] == 1
    assert policy["run_bounds"]["max_1688_checks"]["default"] == 20
    assert policy["run_bounds"]["enable_1688_prefilter"] == {
        "default": True,
        "can_disable": True,
    }
    assert "fog_light_bezel" in policy["archetypes"]
    assert "max_competitive_products" not in policy["default_thresholds"]
    assert policy["default_thresholds"]["grade_a_max_competitors"] == 5
    assert policy["default_thresholds"]["grade_a_minus_max_competitors"] == 8
    assert policy["competition_rule"]["count_field"] == (
        "competitive_product_cluster_count"
    )


def test_runner_rejects_an_incomplete_category_version_snapshot() -> None:
    with pytest.raises(ValueError, match="category_version_id"):
        run_northway_mvp(
            serpapi_key=None,
            category_definition={"category_id": "mirror_mount_cover"},
        )


def test_scope_rejects_universal_and_wrong_product_shapes() -> None:
    assert classify_scope(
        "Universal mud flaps splash guards 4 piece", "fog_light_bezel"
    )["status"] == "OUT_OF_SCOPE"
    assert classify_scope(
        "Toyota 00289-ACRKT cleaner kit", "hood_latch_release_cable"
    )["status"] == "OUT_OF_SCOPE"
    assert classify_scope(
        "Right Fog Light Bezel for Chevrolet Silverado 25778388",
        "fog_light_bezel",
    )["status"] == "IN_SCOPE"


def test_family_resolution_keeps_left_right_and_pair_identity() -> None:
    right = resolve_product_family(
        [
            candidate(
                "25778388",
                "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
            )
        ],
        "fog_light_bezel",
    )
    left = resolve_product_family(
        [
            candidate(
                "25778389",
                "Left Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778389",
                listing_id="124",
            )
        ],
        "fog_light_bezel",
    )
    pair = resolve_product_family(
        [
            candidate(
                "25928247",
                "Left Right Pair Headlight Washer Covers for BMW 25928247 25928248",
                listing_id="125",
            ),
            candidate(
                "25928248",
                "Left Right Pair Headlight Washer Covers for BMW 25928247 25928248",
                listing_id="125",
            ),
        ],
        "headlight_washer_cover",
        fitment_rows=[{"year": 2011, "make": "BMW", "model": "X5", "engine": None}],
    )

    assert right["identity_status"] == "RESOLVED"
    assert right["family"]["sides"] == ["RIGHT"]
    assert left["family"]["sides"] == ["LEFT"]
    assert right["family"]["family_key"] != left["family"]["family_key"]
    assert pair["family"]["sides"] == ["LEFT", "RIGHT"]
    assert pair["family"]["package_quantity"] == 2
    assert pair["family"]["package_type"] == "PAIR"


def test_query_pack_combines_identifiers_and_fitment_without_duplicates() -> None:
    resolution = resolve_product_family(
        [
            candidate(
                "53630-89114",
                "Hood Latch Release Cable for 1989-1995 Toyota Pickup 53630-89114",
            )
        ],
        "hood_latch_release_cable",
    )

    pack = build_amazon_query_pack(resolution["family"], max_queries=4)

    assert pack[0] == {"query_type": "exact_identifier", "query": "53630-89114"}
    assert any("hood latch release cable" in item["query"].lower() for item in pack)
    assert any("Toyota" in item["query"] and "Pickup" in item["query"] for item in pack)
    assert len({item["query"].casefold() for item in pack}) == len(pack)


def test_family_resolution_normalizes_two_digit_fitment_year_ranges() -> None:
    resolution = resolve_product_family(
        [
            candidate(
                "57731FG290PG",
                "11-14 Subaru Impreza Right Fog Light Bezel 57731FG290PG",
            )
        ],
        "fog_light_bezel",
    )

    fitment = resolution["family"]["fitments"][0]
    assert fitment == {
        "make": "Subaru",
        "model": "Impreza",
        "year_from": 2011,
        "year_to": 2014,
        "engines": [],
        "transmissions": [],
    }


def test_amazon_family_aggregation_separates_asins_clusters_offers_and_price() -> None:
    resolution = resolve_product_family(
        [
            candidate(
                "25778388",
                "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
            )
        ],
        "fog_light_bezel",
    )
    title = "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388"
    products = [
        {
            "asin": "B000000001",
            "title": title,
            "url": "https://www.amazon.com/dp/B000000001",
            "price_usd": 28.0,
            "active_offer_count_lower_bound": 3,
            "active_offer_count_complete": True,
        },
        {
            "asin": "B000000002",
            "title": title,
            "url": "https://www.amazon.com/dp/B000000002",
            "price_usd": 26.0,
            "active_offer_count_lower_bound": 1,
            "active_offer_count_complete": True,
        },
        {
            "asin": "B000000003",
            "title": "Left Fog Light Bezel Chevrolet Silverado 25778389",
            "url": "https://www.amazon.com/dp/B000000003",
            "price_usd": 12.0,
            "active_offer_count_lower_bound": 8,
            "active_offer_count_complete": True,
        },
        {
            "asin": "B000000004",
            "title": "Universal LED fog lamp assembly",
            "url": "https://www.amazon.com/dp/B000000004",
            "price_usd": 9.0,
            "active_offer_count_lower_bound": 20,
            "active_offer_count_complete": True,
        },
    ]

    aggregate = aggregate_amazon_family_results(
        resolution["family"],
        [amazon_result("25778388", products)],
        max_competitive_products=3,
        min_family_price_usd=20,
    )

    assert aggregate["competitive_asin_count"] == 2
    assert aggregate["competitive_product_cluster_count"] == 1
    assert aggregate["offer_count_by_asin"] == {
        "B000000001": 3,
        "B000000002": 1,
    }
    assert aggregate["family_price_floor_usd"] == 26.0
    assert aggregate["competition_stage"]["status"] == "PASSED"
    assert aggregate["price_stage"]["status"] == "PASSED"
    relations = {item["asin"]: item["relation"] for item in aggregate["observations"]}
    assert relations["B000000003"] == "LEFT_RIGHT_COUNTERPART"
    assert relations["B000000004"] == "IRRELEVANT"


def test_incomplete_amazon_pages_cannot_prove_low_competition() -> None:
    resolution = resolve_product_family(
        [
            candidate(
                "25778388",
                "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
            )
        ],
        "fog_light_bezel",
    )
    aggregate = aggregate_amazon_family_results(
        resolution["family"],
        [amazon_result("25778388", [], complete=False)],
        max_competitive_products=3,
        min_family_price_usd=20,
    )

    assert aggregate["competition_complete"] is False
    assert aggregate["competition_stage"]["status"] == "REVIEW_REQUIRED"
    assert aggregate["competition_grade"] == "PENDING"


@pytest.mark.parametrize(
    ("count", "complete", "expected_grade", "expected_status"),
    [
        (5, True, "A", "PASSED"),
        (6, True, "A-", "PASSED"),
        (8, True, "A-", "PASSED"),
        (9, True, "REJECTED", "REJECTED"),
        (8, False, "PENDING", "REVIEW_REQUIRED"),
        (9, False, "REJECTED", "REJECTED"),
    ],
)
def test_amazon_competition_grades_use_product_clusters_and_safe_partial_bounds(
    count: int,
    complete: bool,
    expected_grade: str,
    expected_status: str,
) -> None:
    resolution = resolve_product_family(
        [
            candidate(
                "25778388",
                "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
            )
        ],
        "fog_light_bezel",
    )
    products = [
        {
            "asin": f"B00000000{index}",
            "title": f"Brand {index} Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
            "url": f"https://www.amazon.com/dp/B00000000{index}",
            "price_usd": 28.0 + index,
            "active_offer_count_lower_bound": 1,
            "active_offer_count_complete": True,
        }
        for index in range(1, count + 1)
    ]

    aggregate = aggregate_amazon_family_results(
        resolution["family"],
        [amazon_result("25778388", products, complete=complete)],
        min_family_price_usd=20,
        grade_a_max_competitors=5,
        grade_a_minus_max_competitors=8,
    )

    assert aggregate["competitive_product_cluster_count"] == count
    assert aggregate["competition_grade"] == expected_grade
    assert aggregate["competition_stage"]["status"] == expected_status
    assert aggregate["competition_stage"]["operator"] == "LTE"


def test_compact_northway_export_keeps_decisions_and_drops_raw_arrays() -> None:
    full = {
        "schema_version": "0.2.5",
        "profile": "northway-product-family-mvp",
        "result_id": "result_0000000000000001",
        "generated_at": "2026-08-28T00:00:00Z",
        "policy": {
            "grade_a_max_competitors": 5,
            "grade_a_minus_max_competitors": 8,
            "category_version_id": "seed.fog_light_bezel.v1",
            "min_family_price_usd": 20.0,
        },
        "scan_manifest": {
            "marketplace": "EBAY_US",
            "category_id": "6028",
            "archetypes": ["fog_light_bezel"],
            "discovery_queries": [],
            "pages_requested": 1,
            "pages_attempted": 1,
            "pages_completed": 1,
        },
        "request_budget": {"limit": 10, "used": 2, "remaining": 8},
        "discovery": {
            "status": "SUCCESS",
            "listing_groups": 1,
            "resolved_family_count": 1,
            "deduplicated_candidate_count": 1,
            "stats": {"candidates_emitted": 1},
            "diagnostics": [{"code": "HTTP_ERROR", "message": "long raw detail"}],
            "per_archetype": [],
        },
        "summary": {
            "candidate_count": 1,
            "opportunity_candidates": 0,
            "market_shortlist_candidates": 1,
            "review_required": 0,
            "rejected": 0,
        },
        "ranking": ["family-1"],
        "reports": [
            {
                "schema_version": "0.2.5",
                "profile": "northway-product-family-mvp",
                "candidate_id": "family-1",
                "discovery_order": 0,
                "decision": "MARKET_SHORTLIST_CANDIDATE",
                "rank": 1,
                "category_profile": "vehicle_specific_small_trim",
                "archetype": "fog_light_bezel",
                "category_version_id": "seed.fog_light_bezel.v1",
                "category_group_id": "plastic_parts",
                "competition_grade": "A",
                "source_listings": [{"source_listing_id": "ebay-1", "source_listing_title": "title"}],
                "resolution": {"scope_status": "IN_SCOPE", "identity_status": "RESOLVED", "evidence": [{"raw_value": "long"}]},
                "family": {"family_key": "family-1", "part_type": "fog light bezel", "evidence": [{"raw_value": "long"}]},
                "query_pack": [{"query_type": "exact_identifier", "query": "25778388"}],
                "competition": {
                    "competition_complete": True,
                    "competition_grade": "A",
                    "grade_a_max_competitors": 5,
                    "grade_a_minus_max_competitors": 8,
                    "competitive_product_cluster_count": 1,
                    "competitive_asin_count": 1,
                    "observations": [{"asin": "B000000001", "title": "Brand fog light bezel 25778388", "relation": "INTERCHANGEABLE"}],
                    "query_evidence": [
                        {
                            **amazon_result("25778388", [{"asin": "B000000001", "title": "Brand fog light bezel 25778388"}]),
                            "diagnostics": [{"code": "PARSER_FAILED", "message": "raw detail"}],
                        }
                    ],
                    "competition_stage": {"status": "PASSED", "value": 1, "reason": "complete"},
                    "price_stage": {"status": "PASSED", "value": 28, "reason": "price"},
                },
                "demand": {"observed_sold_count_lower_bound": 4, "source_listing_count": 1},
                "supply": None,
                "stages": {"amazon_family_competition": {"status": "PASSED", "value": 1}},
                "evidence_gaps": [],
                "failure_reasons": [],
                "provider_attempts": [{"provider": "SERPAPI_AMAZON_MANAGED", "query": "25778388", "status": "SUCCESS"}],
            }
        ],
    }

    compact = compact_northway_result(full)
    compact_report = compact["reports"][0]

    assert compact["export_format"] == "compact_v1"
    assert compact["discovery"]["diagnostics"] == {"count": 1, "codes": {"HTTP_ERROR": 1}}
    assert "evidence" not in compact_report["family"]
    assert "products" not in compact_report["competition"]["query_evidence"][0]
    assert compact_report["competition"]["relevant_products"][0]["asin"] == "B000000001"
    assert compact_report["competition"]["query_evidence"][0]["products_seen"] == 1
    assert compact_report["competition_grade"] == "A"
    assert compact_report["category_version_id"] == "seed.fog_light_bezel.v1"


def test_runner_processes_every_discovered_listing_and_records_budget_exhaustion() -> None:
    listings = [
        candidate(
            "25778388",
            "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
            listing_id="1",
        ),
        candidate(
            "25778389",
            "Left Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778389",
            listing_id="2",
        ),
    ]

    def discover(**_kwargs):
        return {
            "status": "SUCCESS",
            "retrieved_at": "2026-08-28T00:00:00Z",
            "stats": {
                "results_seen": 2,
                "eligible_sold_listings": 2,
                "listings_with_part_number": 2,
                "candidates_emitted": 2,
            },
            "candidates": listings,
            "diagnostics": [],
        }

    def search(query, **_kwargs):
        return amazon_result(query, [])

    result = run_northway_mvp(
        serpapi_key="configured",
        archetype="fog_light_bezel",
        discovery_pages=1,
        request_budget=2,
        max_amazon_queries_per_family=3,
        collectors={
            "discovery": discover,
            "amazon_search": search,
            "1688_supplier_prefilter": supplier_result,
        },
    )

    assert result["scan_manifest"]["candidate_cap"] is None
    assert result["discovery"]["listing_groups"] == 2
    assert len(result["reports"]) == 2
    assert result["request_budget"]["used"] == 2
    assert result["provider_budgets"]["1688"]["used"] == 2
    assert any("REQUEST_BUDGET_EXHAUSTED" in report["evidence_gaps"] for report in result["reports"])
    assert len(result["ranking"]) == 2

    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "v0_2_5_northway_mvp_result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)


def test_runner_scans_every_archetype_and_assigns_matching_family_type() -> None:
    keywords: list[str] = []

    def discover(**kwargs):
        keywords.append(kwargs["keyword"])
        if kwargs["keyword"] == "fog light bezel OEM":
            candidates = [
                candidate(
                    "25778388",
                    "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
                )
            ]
            status = "SUCCESS"
        else:
            candidates = []
            status = "ZERO_RESULTS"
        return {
            "status": status,
            "retrieved_at": "2026-08-28T00:00:00Z",
            "stats": {"candidates_emitted": len(candidates)},
            "candidates": candidates,
            "diagnostics": [],
        }

    result = run_northway_mvp(
        serpapi_key="configured",
        discovery_pages=1,
        request_budget=80,
        collectors={
            "discovery": discover,
            "amazon_search": lambda query, **_kwargs: amazon_result(query, []),
        },
    )

    assert keywords == [ARCHETYPES[key]["discovery_keyword"] for key in ARCHETYPES]
    assert result["policy"]["archetypes"] == list(ARCHETYPES)
    assert result["scan_manifest"]["archetypes"] == list(ARCHETYPES)
    assert len(result["scan_manifest"]["discovery_queries"]) == len(ARCHETYPES)
    assert len(result["discovery"]["per_archetype"]) == len(ARCHETYPES)
    assert len(result["reports"]) == 1
    assert result["reports"][0]["archetype"] == "fog_light_bezel"


def test_supplier_prefilter_rejects_without_spending_amazon_budget() -> None:
    listing = candidate(
        "25778388",
        "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
    )
    amazon_calls: list[str] = []

    def discover(**_kwargs):
        return {
            "status": "SUCCESS",
            "retrieved_at": "2026-08-28T00:00:00Z",
            "stats": {"candidates_emitted": 1},
            "candidates": [listing],
            "diagnostics": [],
        }

    def no_supplier(raw_part_number: str, *, family: dict, **_kwargs):
        return {
            "provider": "TEST_1688",
            "acquisition_status": "SUCCESS",
            "query": raw_part_number,
            "supplier_found": False,
            "diagnostics": [{"code": "1688_NO_SUPPLIER_FOUND", "message": "fixture"}],
        }

    def search(query: str, **_kwargs):
        amazon_calls.append(query)
        return amazon_result(query, [])

    result = run_northway_mvp(
        serpapi_key="configured",
        archetype="fog_light_bezel",
        request_budget=20,
        max_1688_checks=1,
        collectors={
            "discovery": discover,
            "amazon_search": search,
            "1688_supplier_prefilter": no_supplier,
        },
    )

    report = result["reports"][0]
    assert amazon_calls == []
    assert report["stages"]["china_non_oem_supply"]["status"] == "REJECTED"
    assert report["stages"]["amazon_family_competition"]["status"] == "NOT_RUN"
    assert report["decision"] == "REJECTED"
    assert result["request_budget"]["used"] == 1


def test_disabling_1688_prefilter_runs_amazon_but_keeps_supply_unverified(monkeypatch) -> None:
    listing = candidate(
        "25778388",
        "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
    )
    amazon_calls: list[str] = []

    def discover(**_kwargs):
        return {
            "status": "SUCCESS",
            "retrieved_at": "2026-08-28T00:00:00Z",
            "stats": {"candidates_emitted": 1},
            "candidates": [listing],
            "diagnostics": [],
        }

    def should_not_call_supplier(*_args, **_kwargs):
        raise AssertionError("1688 supplier prefilter must be skipped when disabled")

    def should_not_check_cli():
        raise AssertionError("1688 CLI readiness must be skipped when disabled")

    monkeypatch.setattr("proteus.northway_mvp.is_1688_cli_available", should_not_check_cli)

    def search(query: str, **_kwargs):
        amazon_calls.append(query)
        return amazon_result(query, [], complete=False)

    result = run_northway_mvp(
        serpapi_key="configured",
        archetype="fog_light_bezel",
        request_budget=20,
        max_1688_checks=1,
        enable_1688_prefilter=False,
        max_amazon_queries_per_family=1,
        collectors={
            "discovery": discover,
            "amazon_search": search,
            "1688_supplier_prefilter": should_not_call_supplier,
        },
    )

    report = result["reports"][0]
    assert amazon_calls == ["25778388"]
    assert report["stages"]["china_non_oem_supply"]["status"] == "NOT_RUN"
    assert "1688_PREFILTER_DISABLED" in report["evidence_gaps"]
    assert report["stages"]["amazon_family_competition"]["status"] == "REVIEW_REQUIRED"
    assert report["decision"] == "REVIEW_REQUIRED"
    assert result["policy"]["enable_1688_prefilter"] is False
    assert result["provider_budgets"]["1688"]["used"] == 0
    assert result["supply_filter"] == {
        "provider": "DISABLED_BY_REQUEST",
        "enabled": False,
        "checked": 0,
        "supplier_found": 0,
        "no_supplier": 0,
        "review_required": 0,
        "not_run": 1,
    }
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "v0_2_5_northway_mvp_result.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
