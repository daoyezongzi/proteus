from __future__ import annotations

from pathlib import Path
import json

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from proteus.category_catalog import builtin_runtime_categories
from proteus.supplier_scout import (
    SupplierScoutStore,
    classify_supplier_offer,
    compact_supplier_scout_result,
    run_supplier_scout,
)


STORE_URL = "https://shop3w093345o1043.1688.com/page/offerlist.htm"
ROOT = Path(__file__).resolve().parents[1]


def snapshot(*offers: dict, complete: bool = True) -> dict:
    return {
        "provider": "TEST_STORE",
        "source_method": "TEST_FIXTURE",
        "acquisition_status": "SUCCESS" if complete else "PARTIAL",
        "canonical_url": STORE_URL,
        "supplier": {"member_id": "supplier-1", "shop_host": "shop3w093345o1043.1688.com"},
        "pages_attempted": 1,
        "pages_completed": 1,
        "observed_offer_count": len(offers),
        "available_offer_count": len(offers) if complete else None,
        "has_next_page": False if complete else True,
        "inventory_complete": complete,
        "offers": list(offers),
        "warnings": [],
        "retrieved_at": "2026-08-30T00:00:00Z",
    }


def offer(offer_id: str, title: str) -> dict:
    return {
        "offer_id": offer_id,
        "title": title,
        "offer_url": f"https://detail.1688.com/offer/{offer_id}.html",
        "supplier": {"member_id": "supplier-1", "shop_host": "shop3w093345o1043.1688.com"},
    }


def test_sqlite_sources_and_snapshots_are_separate_and_immutable(tmp_path: Path) -> None:
    database = tmp_path / "supplier-scout.sqlite3"
    store = SupplierScoutStore(database)
    source = store.add_supplier("测试店铺", STORE_URL)
    captured = snapshot(offer("10001", "丰田雾灯框 81482-0R010"))

    saved = store.save_snapshot(source["supplier_id"], captured)
    inspection = store.save_inspection(
        STORE_URL,
        {
            "acquisition_status": "PARTIAL",
            "inventory_complete": False,
            "diagnostics": [{"code": "PAGE_BOUND_REACHED"}],
        },
        supplier_id=source["supplier_id"],
    )

    assert database.exists()
    assert store.list_suppliers()["suppliers"][0]["canonical_url"] == STORE_URL
    assert store.get_inspection(inspection["inspection_id"])["diagnostics"] == [
        {"code": "PAGE_BOUND_REACHED"}
    ]
    assert store.get_snapshot(saved["snapshot_id"])["offers"][0]["offer_id"] == "10001"
    with pytest.raises(ValueError, match="immutable"):
        store.save_snapshot(source["supplier_id"], captured, snapshot_id=saved["snapshot_id"])


def test_sqlite_supplier_sources_and_snapshots_are_tenant_scoped(tmp_path: Path) -> None:
    store = SupplierScoutStore(tmp_path / "supplier-scout.sqlite3")
    source = store.add_supplier("租户 A", STORE_URL, tenant_id="tenant_a")
    saved = store.save_snapshot(
        source["supplier_id"],
        snapshot(offer("10001", "租户 A 商品")),
        tenant_id="tenant_a",
    )

    assert store.list_suppliers(tenant_id="tenant_a")["suppliers"]
    assert store.list_suppliers(tenant_id="tenant_b")["suppliers"] == []
    with pytest.raises(KeyError):
        store.get_supplier(source["supplier_id"], tenant_id="tenant_b")
    with pytest.raises(KeyError):
        store.get_snapshot(saved["snapshot_id"], tenant_id="tenant_b")


def test_category_match_uses_chinese_supply_aliases_and_keeps_ambiguity() -> None:
    definitions = builtin_runtime_categories()

    matched = classify_supplier_offer(
        offer("10001", "丰田 RAV4 雾灯框 81482-0R010"), definitions
    )
    unmatched = classify_supplier_offer(offer("10002", "通用车载收纳盒"), definitions)
    ambiguous = classify_supplier_offer(
        offer("10003", "雾灯框 拖车钩盖 汽车塑料件"), definitions
    )

    assert matched["status"] == "MATCHED"
    assert matched["category_id"] == "fog_light_bezel"
    assert unmatched["status"] == "CATEGORY_UNMATCHED"
    assert ambiguous["status"] == "CATEGORY_AMBIGUOUS"


def test_runner_preserves_every_offer_and_market_budget() -> None:
    source_snapshot = snapshot(
        offer("10001", "2007-2013 Chevrolet Silverado 雾灯框 25778388"),
        offer("10002", "2008-2013 Cadillac CTS 雾灯框 25778389"),
        offer("10003", "通用车载收纳盒"),
    )
    calls: list[tuple[str, str]] = []

    def ebay(raw_part_number: str, **_kwargs):
        calls.append(("ebay", raw_part_number))
        return {
            "provider": "TEST_EBAY",
            "status": "SUCCESS",
            "observed_demand": {"aggregate_observed_sold": 4},
            "listings": [],
            "diagnostics": [],
        }

    def amazon(query: str, **_kwargs):
        calls.append(("amazon", query))
        return {
            "provider": "TEST_AMAZON",
            "query": query,
            "acquisition_status": "ZERO_RESULTS",
            "result_page_complete": True,
            "has_next_page": False,
            "products": [],
            "diagnostics": [],
        }

    result = run_supplier_scout(
        source_snapshot,
        category_definitions=builtin_runtime_categories(),
        selected_category_ids=["fog_light_bezel"],
        serpapi_key="test",
        market_request_budget=2,
        max_amazon_queries_per_family=1,
        collectors={"ebay_demand": ebay, "amazon_search": amazon},
    )

    assert len(result["reports"]) == 3
    assert result["reports"][0]["competition_grade"] == "A"
    assert result["reports"][0]["decision"] == "REVIEW_REQUIRED"
    assert "AMAZON_PRICE_INCOMPLETE" in result["reports"][0]["evidence_gaps"]
    assert result["reports"][1]["market_status"] == "NOT_RUN_BUDGET"
    assert result["reports"][2]["category_match"]["status"] == "CATEGORY_UNMATCHED"
    assert result["market_budget"] == {"limit": 2, "used": 2, "remaining": 0}
    assert len(calls) == 2


def test_runner_refuses_to_screen_a_risk_control_snapshot_as_empty() -> None:
    blocked = snapshot(complete=False)
    blocked["acquisition_status"] = "RISK_CONTROL"

    result = run_supplier_scout(
        blocked,
        category_definitions=builtin_runtime_categories(),
        serpapi_key="test",
    )

    assert result["status"] == "SOURCE_BLOCKED"
    assert result["reports"] == []
    assert result["inventory"]["acquisition_status"] == "RISK_CONTROL"


def test_explicit_zero_demand_stops_amazon_without_hiding_the_offer() -> None:
    amazon_calls: list[str] = []

    def ebay(_raw_part_number: str, **_kwargs):
        return {
            "provider": "TEST_EBAY",
            "status": "ZERO_RESULTS",
            "observed_demand": {"aggregate_observed_sold": 0},
            "listings": [],
            "diagnostics": [],
        }

    def amazon(query: str, **_kwargs):
        amazon_calls.append(query)
        raise AssertionError("Amazon must not run after explicit zero demand")

    result = run_supplier_scout(
        snapshot(offer("10001", "2007-2013 Chevrolet Silverado 雾灯框 25778388")),
        category_definitions=builtin_runtime_categories(),
        selected_category_ids=["fog_light_bezel"],
        serpapi_key="test",
        market_request_budget=5,
        collectors={"ebay_demand": ebay, "amazon_search": amazon},
    )

    assert len(result["reports"]) == 1
    assert result["reports"][0]["market_status"] == "DEMAND_REJECTED"
    assert result["reports"][0]["decision"] == "REJECTED"
    assert result["market_budget"]["used"] == 1
    assert amazon_calls == []


@pytest.mark.parametrize(
    ("price_usd", "expected_decision"),
    [(12.0, "REJECTED"), (28.0, "MARKET_SHORTLIST_CANDIDATE")],
)
def test_price_qualification_is_separate_from_the_a_grade(
    price_usd: float, expected_decision: str
) -> None:
    def ebay(_raw_part_number: str, **_kwargs):
        return {
            "provider": "TEST_EBAY",
            "status": "SUCCESS",
            "observed_demand": {"aggregate_observed_sold": 4},
            "listings": [],
            "diagnostics": [],
        }

    def amazon(query: str, **_kwargs):
        return {
            "provider": "TEST_AMAZON",
            "query": query,
            "acquisition_status": "SUCCESS",
            "result_page_complete": True,
            "has_next_page": False,
            "products": [
                {
                    "asin": "B000000001",
                    "title": "Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388",
                    "price_usd": price_usd,
                }
            ],
            "diagnostics": [],
        }

    result = run_supplier_scout(
        snapshot(offer("10001", "2007-2013 Chevrolet Silverado 雾灯框 25778388")),
        category_definitions=builtin_runtime_categories(),
        selected_category_ids=["fog_light_bezel"],
        serpapi_key="test",
        market_request_budget=2,
        max_amazon_queries_per_family=1,
        min_family_price_usd=20,
        collectors={"ebay_demand": ebay, "amazon_search": amazon},
    )

    report = result["reports"][0]
    assert report["competition_grade"] == "A"
    assert report["decision"] == expected_decision
    compact_report = compact_supplier_scout_result(result)["reports"][0]
    assert compact_report["competition"]["competition_complete"] is True
    assert compact_report["competition"]["price_stage"]["status"] == (
        "REJECTED" if price_usd <= 20 else "PASSED"
    )


def test_compact_export_keeps_boundary_grade_and_evidence_status() -> None:
    result = run_supplier_scout(
        snapshot(offer("10001", "2007-2013 Chevrolet Silverado 雾灯框 25778388"), complete=False),
        category_definitions=builtin_runtime_categories(),
        selected_category_ids=["fog_light_bezel"],
        serpapi_key=None,
        market_request_budget=1,
    )

    compact = compact_supplier_scout_result(result)

    assert compact["inventory"]["inventory_complete"] is False
    assert compact["reports"][0]["offer"]["offer_url"].startswith("https://detail.1688.com/")
    assert compact["reports"][0]["competition_grade"] in {"PENDING", None}


def test_supplier_scout_result_validates_against_the_v026_contract() -> None:
    result = run_supplier_scout(
        snapshot(offer("10001", "通用车载收纳盒")),
        category_definitions=builtin_runtime_categories(),
        serpapi_key=None,
        market_request_budget=0,
    )
    schema = json.loads(
        (ROOT / "contracts" / "v0_2_6_supplier_scout_result.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(result)
