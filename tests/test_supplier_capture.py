from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from proteus.supplier_capture import (
    CaptureAuthorizationError,
    CaptureConflictError,
    SupplierCaptureManager,
)
from proteus.supplier_scout import SupplierScoutStore


STORE_URL = "https://shop3w093345o1043.1688.com/page/offerlist.htm"
SHOP_HOST = "shop3w093345o1043.1688.com"


def offer(offer_id: str, title: str | None = None) -> dict:
    return {
        "offer_id": offer_id,
        "title": title or f"测试商品 {offer_id}",
        "offer_url": f"https://detail.1688.com/offer/{offer_id}.html",
        "image_url": f"https://cbu01.alicdn.com/{offer_id}.jpg",
    }


def manager(tmp_path: Path, **kwargs) -> tuple[SupplierCaptureManager, dict]:
    store = SupplierScoutStore(tmp_path / "supplier-scout.sqlite3")
    supplier = store.add_supplier("测试供应商", STORE_URL)
    return SupplierCaptureManager(store, **kwargs), supplier


def test_capture_requires_token_and_exact_saved_store_host(tmp_path: Path) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=3, max_offers=100
    )

    assert created["status"] == "PENDING"
    assert created["capture_token"]
    assert "capture_token" not in captures.get_capture(created["capture_id"])
    assert captures.pending_capture(shop_host=SHOP_HOST)["capture_id"] == created["capture_id"]
    assert captures.pending_capture(shop_host="") is None

    with pytest.raises(CaptureAuthorizationError):
        captures.claim_capture(
            created["capture_id"], "wrong-token", page_url=STORE_URL
        )
    with pytest.raises(CaptureConflictError, match="saved supplier"):
        captures.claim_capture(
            created["capture_id"],
            created["capture_token"],
            page_url="https://different.1688.com/page/offerlist.htm",
        )

    claimed = captures.claim_capture(
        created["capture_id"],
        created["capture_token"],
        page_url=STORE_URL,
        extension_version="0.2.6",
    )

    assert claimed["status"] == "CAPTURING"
    assert claimed["collector_version"] == "0.2.6"


def test_capturing_session_can_be_reattached_after_extension_state_loss(
    tmp_path: Path,
) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=3, max_offers=100
    )
    token = created["capture_token"]
    captures.claim_capture(
        created["capture_id"],
        token,
        page_url=STORE_URL,
        extension_version="0.2.6",
    )

    recoverable = captures.pending_capture(shop_host=SHOP_HOST)
    assert recoverable is not None
    assert recoverable["capture_id"] == created["capture_id"]
    assert recoverable["capture_token"] == token
    assert recoverable["status"] == "CAPTURING"

    reclaimed = captures.claim_capture(
        created["capture_id"],
        token,
        page_url=STORE_URL,
        extension_version="0.2.7",
    )
    assert reclaimed["status"] == "CAPTURING"
    assert reclaimed["collector_version"] == "0.2.7"


def test_capture_ingests_sequential_pages_idempotently_and_seals_snapshot(
    tmp_path: Path,
) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=3, max_offers=100
    )
    token = created["capture_token"]
    captures.claim_capture(created["capture_id"], token, page_url=STORE_URL)
    page_one = {
        "page_number": 1,
        "page_url": STORE_URL,
        "has_next_page": True,
        "available_offer_count": 3,
        "empty_state": False,
        "offers": [offer("10001"), offer("10002")],
        "evidence": {"dom_sha256": "a" * 64},
    }

    first = captures.ingest_page(created["capture_id"], token, page_one)
    repeated = captures.ingest_page(created["capture_id"], token, page_one)
    dynamic_retry = {
        **page_one,
        "offers": [offer("10001", "动态标题"), offer("10002")],
        "evidence": {"dom_sha256": "8" * 64, "document_title": "动态页面标题"},
    }
    repeated_after_dom_change = captures.ingest_page(
        created["capture_id"], token, dynamic_retry
    )

    assert first["status"] == "CAPTURING"
    assert first["pages_completed"] == 1
    assert repeated["pages_completed"] == 1
    assert repeated["observed_offer_count"] == 2
    assert repeated_after_dom_change["pages_completed"] == 1
    assert repeated_after_dom_change["observed_offer_count"] == 2

    changed = dict(page_one)
    changed["offers"] = [offer("10001"), offer("10004")]
    with pytest.raises(CaptureConflictError, match="already ingested"):
        captures.ingest_page(created["capture_id"], token, changed)
    with pytest.raises(CaptureConflictError, match="next sequential"):
        captures.ingest_page(
            created["capture_id"],
            token,
            {
                **page_one,
                "page_number": 3,
                "evidence": {"dom_sha256": "c" * 64},
            },
        )

    completed = captures.ingest_page(
        created["capture_id"],
        token,
        {
            "page_number": 2,
            "page_url": f"{STORE_URL}?pageNum=2",
            "has_next_page": False,
            "available_offer_count": 3,
            "empty_state": False,
            "offers": [offer("10002", "duplicate"), offer("10003")],
            "evidence": {"dom_sha256": "b" * 64},
        },
    )

    assert completed["status"] == "COMPLETED"
    assert completed["observed_offer_count"] == 3
    assert completed["snapshot_id"].startswith("snap_")
    snapshot = captures.store.get_snapshot(completed["snapshot_id"])
    assert snapshot["acquisition_status"] == "SUCCESS"
    assert snapshot["inventory_complete"] is True
    assert snapshot["pages_completed"] == 2
    assert [item["offer_id"] for item in snapshot["offers"]] == [
        "10001",
        "10002",
        "10003",
    ]
    assert "DUPLICATE_OFFER_SKIPPED" in snapshot["warnings"]


@pytest.mark.parametrize(
    ("max_pages", "max_offers", "offers", "expected_warning"),
    [
        (1, 100, [offer("10001")], "PAGE_BOUND_REACHED"),
        (3, 2, [offer("10001"), offer("10002"), offer("10003")], "OFFER_BOUND_REACHED"),
    ],
)
def test_capture_bounds_seal_an_explicit_partial_snapshot(
    tmp_path: Path,
    max_pages: int,
    max_offers: int,
    offers: list[dict],
    expected_warning: str,
) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=max_pages, max_offers=max_offers
    )
    token = created["capture_token"]
    captures.claim_capture(created["capture_id"], token, page_url=STORE_URL)

    completed = captures.ingest_page(
        created["capture_id"],
        token,
        {
            "page_number": 1,
            "page_url": STORE_URL,
            "has_next_page": True,
            "available_offer_count": 8,
            "empty_state": False,
            "offers": offers,
            "evidence": {"dom_sha256": "d" * 64},
        },
    )

    snapshot = captures.store.get_snapshot(completed["snapshot_id"])
    assert completed["status"] == "COMPLETED"
    assert snapshot["acquisition_status"] == "PARTIAL"
    assert snapshot["inventory_complete"] is False
    assert len(snapshot["offers"]) <= max_offers
    assert expected_warning in snapshot["warnings"]


def test_capture_requires_explicit_empty_marker_to_claim_an_empty_store(
    tmp_path: Path,
) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=2, max_offers=20
    )
    token = created["capture_token"]
    captures.claim_capture(created["capture_id"], token, page_url=STORE_URL)

    completed = captures.ingest_page(
        created["capture_id"],
        token,
        {
            "page_number": 1,
            "page_url": STORE_URL,
            "has_next_page": False,
            "available_offer_count": 0,
            "empty_state": True,
            "offers": [],
            "evidence": {"dom_sha256": "e" * 64},
        },
    )

    snapshot = captures.store.get_snapshot(completed["snapshot_id"])
    assert snapshot["acquisition_status"] == "EMPTY"
    assert snapshot["inventory_complete"] is True
    assert snapshot["observed_offer_count"] == 0


@pytest.mark.parametrize("reported_total", [0, 2])
def test_final_page_total_mismatch_stays_partial(
    tmp_path: Path, reported_total: int
) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=2, max_offers=20
    )
    token = created["capture_token"]
    captures.claim_capture(created["capture_id"], token, page_url=STORE_URL)

    completed = captures.ingest_page(
        created["capture_id"],
        token,
        {
            "page_number": 1,
            "page_url": STORE_URL,
            "has_next_page": False,
            "available_offer_count": reported_total,
            "empty_state": False,
            "offers": [offer("10001")],
            "evidence": {"dom_sha256": "9" * 64},
        },
    )

    snapshot = captures.store.get_snapshot(completed["snapshot_id"])
    assert completed["status"] == "COMPLETED"
    assert snapshot["acquisition_status"] == "PARTIAL"
    assert snapshot["inventory_complete"] is False
    assert "AVAILABLE_COUNT_MISMATCH" in snapshot["warnings"]


def test_unproven_empty_page_pauses_without_consuming_the_page_number(
    tmp_path: Path,
) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=2, max_offers=20
    )
    token = created["capture_token"]
    captures.claim_capture(created["capture_id"], token, page_url=STORE_URL)

    page = {
        "page_number": 1,
        "page_url": STORE_URL,
        "has_next_page": None,
        "available_offer_count": None,
        "empty_state": False,
        "offers": [],
        "evidence": {
            "dom_sha256": "0" * 64,
            "document_title": "供应商全部商品",
            "profile_id": "1688-store-offer-list-v1",
            "parser_probe": {
                "anchor_count": 20,
                "iframe_count": 1,
                "shadow_host_count": 0,
                "configured_offer_match_count": 0,
                "configured_next_match_count": 0,
                "offer_candidates": [
                    {
                        "tag": "div",
                        "url": "https://shop3w093345o1043.1688.com/offer/90001.html",
                        "text": "测试商品 90001",
                        "class_name": "modern-item",
                        "data_offer_id": "90001",
                    }
                ],
                "pagination_candidates": [],
                "frame_candidates": [
                    {
                        "tag": "iframe",
                        "url": "https://show.1688.com/page/offers.html",
                    }
                ],
                "embedded_data_markers": [],
            },
        },
    }
    paused = captures.ingest_page(
        created["capture_id"],
        token,
        page,
    )

    assert paused["status"] == "PAUSED"
    assert paused["pages_attempted"] == 1
    assert paused["pages_completed"] == 0
    assert paused["next_page_number"] == 1
    assert paused["last_diagnostic"]["code"] == "PAGE_OFFERS_NOT_CONFIRMED"
    assert paused["last_page_evidence"]["parser_probe"]["anchor_count"] == 20
    blocked = captures.store.get_snapshot(paused["snapshot_id"])
    assert blocked["acquisition_status"] == "PARSER_FAILED"
    assert blocked["pages_attempted"] == 1
    assert blocked["page_evidence"][0]["parser_probe"]["offer_candidates"][0][
        "data_offer_id"
    ] == "90001"

    captures.claim_capture(created["capture_id"], token, page_url=STORE_URL)
    repeated = captures.ingest_page(created["capture_id"], token, page)
    repeated_snapshot = captures.store.get_snapshot(repeated["snapshot_id"])
    assert len(repeated_snapshot["page_evidence"]) == 1
    assert [item["code"] for item in repeated_snapshot["diagnostics"]].count(
        "PAGE_OFFERS_NOT_CONFIRMED"
    ) == 1
    assert blocked["inventory_complete"] is False


def test_blocked_capture_preserves_partial_snapshot_and_can_resume(
    tmp_path: Path,
) -> None:
    captures, supplier = manager(tmp_path)
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=3, max_offers=20
    )
    token = created["capture_token"]
    captures.claim_capture(created["capture_id"], token, page_url=STORE_URL)
    captures.ingest_page(
        created["capture_id"],
        token,
        {
            "page_number": 1,
            "page_url": STORE_URL,
            "has_next_page": True,
            "available_offer_count": None,
            "empty_state": False,
            "offers": [offer("10001")],
            "evidence": {"dom_sha256": "f" * 64},
        },
    )

    paused = captures.pause_capture(
        created["capture_id"],
        token,
        reason="RISK_CONTROL",
        page_url=f"{STORE_URL}?pageNum=2",
    )

    assert paused["status"] == "PAUSED"
    partial = captures.store.get_snapshot(paused["snapshot_id"])
    assert partial["acquisition_status"] == "PARTIAL"
    assert "RISK_CONTROL" in partial["warnings"]

    resumed = captures.claim_capture(
        created["capture_id"], token, page_url=f"{STORE_URL}?pageNum=2"
    )
    assert resumed["status"] == "CAPTURING"


def test_expired_capture_cannot_be_claimed(tmp_path: Path) -> None:
    current = [datetime(2026, 8, 30, tzinfo=timezone.utc)]
    captures, supplier = manager(
        tmp_path, ttl_seconds=60, clock=lambda: current[0]
    )
    created = captures.create_capture(
        supplier["supplier_id"], max_pages=3, max_offers=20
    )
    current[0] += timedelta(seconds=61)

    with pytest.raises(CaptureConflictError, match="expired"):
        captures.claim_capture(
            created["capture_id"], created["capture_token"], page_url=STORE_URL
        )
    assert captures.get_capture(created["capture_id"])["status"] == "EXPIRED"
