from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from proteus.providers.local_1688_store import (
    collect_1688_store_offers,
    normalize_1688_supplier_target,
)


EXAMPLE = "https://shop3w093345o1043.1688.com/page/offerlist.htm"
ROOT = Path(__file__).resolve().parents[1]


def test_normalizer_repairs_the_duplicated_tracked_user_url() -> None:
    tracked = f"{EXAMPLE}?scrollTo=pcTopNav&spm=a2615.2177701/2506.wp_pc_common_topnav.0"
    submitted = f"[{tracked}{tracked}]({tracked}{tracked})"

    normalized = normalize_1688_supplier_target(submitted)

    assert normalized["canonical_url"] == EXAMPLE
    assert normalized["shop_host"] == "shop3w093345o1043.1688.com"
    assert normalized["target_type"] == "STORE_OFFER_LIST"


@pytest.mark.parametrize(
    "target",
    [
        "http://shop3w093345o1043.1688.com/page/offerlist.htm",
        "https://user:secret@shop3w093345o1043.1688.com/page/offerlist.htm",
        "https://example.com/page/offerlist.htm",
        f"{EXAMPLE} https://different.1688.com/page/offerlist.htm",
    ],
)
def test_normalizer_fails_closed_outside_one_https_1688_source(target: str) -> None:
    with pytest.raises(ValueError):
        normalize_1688_supplier_target(target)


def test_store_collector_preserves_partial_and_supplier_binding() -> None:
    calls: list[list[str]] = []

    def run(argv, _timeout):
        calls.append(list(argv))
        return 0, json.dumps(
            {
                "provider": "LOCAL_1688_STORE_BRIDGE",
                "acquisition_status": "PARTIAL",
                "canonical_url": EXAMPLE,
                "supplier": {
                    "shop_host": "shop3w093345o1043.1688.com",
                    "member_id": "b2b-123",
                    "name": "测试供应商",
                },
                "pages_attempted": 2,
                "pages_completed": 2,
                "observed_offer_count": 2,
                "available_offer_count": 80,
                "has_next_page": True,
                "inventory_complete": False,
                "offers": [
                    {
                        "offer_id": "628196518518",
                        "title": "丰田 RAV4 雾灯框 81482-0R010",
                        "offer_url": "https://detail.1688.com/offer/628196518518.html",
                    },
                    {
                        "offer_id": "628196518519",
                        "title": "丰田 RAV4 拖车钩盖 52128-0R020",
                        "offer_url": "https://detail.1688.com/offer/628196518519.html",
                    },
                ],
                "warnings": ["PAGE_BOUND_REACHED"],
                "retrieved_at": "2026-08-30T00:00:00Z",
            }
        ), ""

    outcome = collect_1688_store_offers(
        EXAMPLE,
        max_pages=2,
        max_offers=20,
        cli_root="C:/tools/1688-cli",
        bridge_path="C:/proteus/bridge.mjs",
        command_runner=run,
    )

    assert outcome["acquisition_status"] == "PARTIAL"
    assert outcome["inventory_complete"] is False
    assert outcome["observed_offer_count"] == 2
    assert all(
        item["supplier"]["member_id"] == "b2b-123" for item in outcome["offers"]
    )
    assert calls[0][0] == "node"
    assert "--max-pages" in calls[0]
    assert "--max-offers" in calls[0]


@pytest.mark.parametrize(
    "target",
    [
        "https://www.1688.com/page/offerlist.htm",
        "https://detail.1688.com/offer/628196518518.html",
        "https://shop3w093345o1043.1688.com/",
    ],
)
def test_store_collector_requires_an_explicit_supplier_offer_list(target: str) -> None:
    with pytest.raises(ValueError, match="supplier subdomain"):
        collect_1688_store_offers(
            target,
            cli_root="C:/tools/1688-cli",
            bridge_path="C:/proteus/bridge.mjs",
            command_runner=lambda _argv, _timeout: (0, "{}", ""),
        )


@pytest.mark.parametrize("status", ["AUTH_REQUIRED", "RISK_CONTROL", "TIMEOUT"])
def test_store_collector_never_converts_provider_failure_to_empty(status: str) -> None:
    def run(_argv, _timeout):
        return 0, json.dumps(
            {
                "provider": "LOCAL_1688_STORE_BRIDGE",
                "acquisition_status": status,
                "canonical_url": EXAMPLE,
                "supplier": {"shop_host": "shop3w093345o1043.1688.com"},
                "pages_attempted": 1,
                "pages_completed": 0,
                "observed_offer_count": 0,
                "available_offer_count": None,
                "has_next_page": None,
                "inventory_complete": False,
                "offers": [],
                "warnings": [status],
                "retrieved_at": "2026-08-30T00:00:00Z",
            }
        ), ""

    outcome = collect_1688_store_offers(
        EXAMPLE,
        cli_root="C:/tools/1688-cli",
        bridge_path="C:/proteus/bridge.mjs",
        command_runner=run,
    )

    assert outcome["acquisition_status"] == status
    assert outcome["inventory_complete"] is False
    assert outcome["observed_offer_count"] == 0


def test_store_collector_deduplicates_offers_and_rejects_foreign_urls() -> None:
    def run(_argv, _timeout):
        return 0, json.dumps(
            {
                "provider": "LOCAL_1688_STORE_BRIDGE",
                "acquisition_status": "SUCCESS",
                "canonical_url": EXAMPLE,
                "supplier": {"shop_host": "shop3w093345o1043.1688.com"},
                "pages_attempted": 1,
                "pages_completed": 1,
                "observed_offer_count": 3,
                "available_offer_count": 2,
                "has_next_page": False,
                "inventory_complete": True,
                "offers": [
                    {"offer_id": "10001", "title": "A", "offer_url": "https://detail.1688.com/offer/10001.html"},
                    {"offer_id": "10001", "title": "A duplicate", "offer_url": "https://detail.1688.com/offer/10001.html"},
                    {"offer_id": "99999", "title": "mismatch", "offer_url": "https://detail.1688.com/offer/10003.html"},
                    {"offer_id": "10002", "title": "foreign", "offer_url": "https://example.com/offer/10002.html"},
                ],
                "warnings": [],
                "retrieved_at": "2026-08-30T00:00:00Z",
            }
        ), ""

    outcome = collect_1688_store_offers(
        EXAMPLE,
        cli_root="C:/tools/1688-cli",
        bridge_path="C:/proteus/bridge.mjs",
        command_runner=run,
    )

    assert [item["offer_id"] for item in outcome["offers"]] == ["10001"]
    assert outcome["inventory_complete"] is False
    assert "INVALID_OFFER_SKIPPED" in outcome["warnings"]


def test_normalized_inventory_validates_against_the_v026_contract() -> None:
    def run(_argv, _timeout):
        return 0, json.dumps(
            {
                "acquisition_status": "EMPTY",
                "supplier": {"shop_host": "shop3w093345o1043.1688.com"},
                "pages_attempted": 1,
                "pages_completed": 1,
                "observed_offer_count": 0,
                "available_offer_count": 0,
                "has_next_page": False,
                "inventory_complete": True,
                "offers": [],
                "warnings": [],
                "retrieved_at": "2026-08-30T00:00:00Z",
            }
        ), ""

    outcome = collect_1688_store_offers(
        EXAMPLE,
        cli_root="C:/tools/1688-cli",
        bridge_path="C:/proteus/bridge.mjs",
        command_runner=run,
    )
    schema = json.loads(
        (ROOT / "contracts" / "v0_2_6_supplier_inventory_snapshot.schema.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(schema, format_checker=FormatChecker()).validate(outcome)
