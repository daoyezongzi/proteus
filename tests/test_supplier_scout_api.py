from __future__ import annotations

from pathlib import Path
from time import monotonic, sleep

import pytest
from fastapi.testclient import TestClient

from proteus.api import DefaultFrontendService, create_app
from proteus.category_catalog import CategoryCatalog
from proteus.supplier_scout import SupplierScoutStore


STORE_URL = "https://shop3w093345o1043.1688.com/page/offerlist.htm"


class SupplierScoutApiService:
    def configuration_status(self) -> dict:
        return {"credentials": {}}

    def provider_status(self) -> dict:
        return {"providers": []}

    def submit_run(self, request: dict) -> dict:
        raise AssertionError(request)

    def get_run(self, run_id: str) -> dict | None:
        return None

    def submit_mvp_run(self, request: dict) -> dict:
        raise AssertionError(request)

    def get_mvp_run(self, run_id: str) -> dict | None:
        return None

    def submit_northway_run(self, request: dict) -> dict:
        raise AssertionError(request)

    def get_northway_run(self, run_id: str) -> dict | None:
        return None

    def supplier_scout_policy(self) -> dict:
        return {
            "schema_version": "0.2.6",
            "profile": "supplier-first-store-scout",
            "categories": {"fog_light_bezel": {"category_id": "fog_light_bezel"}},
        }

    def list_supplier_scout_suppliers(self) -> dict:
        return {
            "suppliers": [
                {
                    "supplier_id": "sup_123",
                    "label": "测试供应商",
                    "canonical_url": STORE_URL,
                    "status": "ACTIVE",
                }
            ]
        }

    def inspect_supplier_scout_supplier(self, request: dict) -> dict:
        assert request == {
            "target": STORE_URL,
            "max_pages": 1,
            "max_offers": 20,
            "headed": False,
            "challenge_timeout_seconds": 180,
        }
        return {
            "acquisition_status": "RISK_CONTROL",
            "canonical_url": STORE_URL,
            "inventory_complete": False,
            "offers": [],
        }

    def add_supplier_scout_supplier(self, request: dict) -> dict:
        assert request == {"label": "测试供应商", "target": STORE_URL}
        return {
            "supplier_id": "sup_123",
            "label": request["label"],
            "canonical_url": STORE_URL,
            "status": "ACTIVE",
        }

    def latest_supplier_snapshot(self, supplier_id: str) -> dict | None:
        assert supplier_id == "sup_123"
        return {
            "snapshot_id": "snap_123",
            "supplier_id": supplier_id,
            "acquisition_status": "PARTIAL",
            "observed_offer_count": 1,
            "inventory_complete": False,
        }

    def create_supplier_capture(self, request: dict) -> dict:
        assert request == {"supplier_id": "sup_123", "max_pages": 3, "max_offers": 100}
        return {
            "capture_id": "cap_123",
            "capture_token": "capture-secret",
            "supplier_id": "sup_123",
            "shop_host": "shop3w093345o1043.1688.com",
            "canonical_url": STORE_URL,
            "status": "PENDING",
            "max_pages": 3,
            "max_offers": 100,
        }

    def pending_supplier_capture(self, shop_host: str) -> dict | None:
        assert shop_host == "shop3w093345o1043.1688.com"
        return {
            "capture_id": "cap_123",
            "capture_token": "capture-secret",
            "shop_host": shop_host,
            "status": "PENDING",
        }

    def get_supplier_capture(self, capture_id: str) -> dict | None:
        if capture_id != "cap_123":
            return None
        return {
            "capture_id": capture_id,
            "supplier_id": "sup_123",
            "status": "CAPTURING",
            "pages_completed": 0,
            "observed_offer_count": 0,
        }

    def claim_supplier_capture(self, capture_id: str, token: str, request: dict) -> dict:
        assert capture_id == "cap_123"
        assert token == "capture-secret"
        assert request["page_url"] == STORE_URL
        return {"capture_id": capture_id, "status": "CAPTURING"}

    def ingest_supplier_capture_page(
        self, capture_id: str, token: str, request: dict
    ) -> dict:
        assert capture_id == "cap_123"
        assert token == "capture-secret"
        assert request["offers"][0]["offer_id"] == "10001"
        return {
            "capture_id": capture_id,
            "status": "COMPLETED",
            "snapshot_id": "snap_123",
            "pages_completed": 1,
            "observed_offer_count": 1,
        }

    def pause_supplier_capture(self, capture_id: str, token: str, request: dict) -> dict:
        assert capture_id == "cap_123"
        assert token == "capture-secret"
        assert request["reason"] == "RISK_CONTROL"
        return {"capture_id": capture_id, "status": "PAUSED", "snapshot_id": "snap_124"}

    def submit_supplier_scout_run(self, request: dict) -> dict:
        assert request["supplier_id"] == "sup_123"
        assert request["selected_category_ids"] == ["fog_light_bezel"]
        assert request["market_request_budget"] == 2
        return {"run_id": "supplier-run-123", "status": "QUEUED"}

    def get_supplier_scout_run(self, run_id: str) -> dict | None:
        if run_id == "supplier-run-123":
            return {
                "run_id": run_id,
                "status": "COMPLETED",
                "result": {
                    "schema_version": "0.2.6",
                    "profile": "supplier-first-store-scout",
                    "status": "PARTIAL_SOURCE",
                    "inventory": {"inventory_complete": False},
                    "market_budget": {"limit": 2, "used": 2, "remaining": 0},
                    "summary": {"reports": 1},
                    "reports": [],
                },
            }
        if run_id == "supplier-run-running":
            return {"run_id": run_id, "status": "RUNNING", "result": None}
        return None


def test_supplier_scout_api_exposes_sources_inspection_runs_and_exports() -> None:
    client = TestClient(create_app(service=SupplierScoutApiService()))

    policy = client.get("/api/v1/supplier-scout/policy")
    suppliers = client.get("/api/v1/supplier-scout/suppliers")
    inspected = client.post(
        "/api/v1/supplier-scout/suppliers/inspect", json={"target": STORE_URL}
    )
    created = client.post(
        "/api/v1/supplier-scout/suppliers",
        json={"label": "测试供应商", "target": STORE_URL},
    )
    submitted = client.post(
        "/api/v1/supplier-scout/runs",
        json={
            "supplier_id": "sup_123",
            "selected_category_ids": ["fog_light_bezel"],
            "market_request_budget": 2,
        },
    )
    run = client.get("/api/v1/supplier-scout/runs/supplier-run-123")
    full = client.get("/api/v1/supplier-scout/runs/supplier-run-123/export")
    compact = client.get("/api/v1/supplier-scout/runs/supplier-run-123/export/compact")
    running = client.get("/api/v1/supplier-scout/runs/supplier-run-running/export")

    assert policy.json()["profile"] == "supplier-first-store-scout"
    assert suppliers.json()["suppliers"][0]["supplier_id"] == "sup_123"
    assert inspected.json()["acquisition_status"] == "RISK_CONTROL"
    assert inspected.json()["inventory_complete"] is False
    assert created.status_code == 201
    assert submitted.status_code == 202
    assert run.json()["result"]["status"] == "PARTIAL_SOURCE"
    assert full.status_code == 200
    assert full.headers["content-disposition"].endswith('supplier-run-123.json"')
    assert compact.status_code == 200
    assert compact.json()["profile"] == "supplier-first-store-scout"
    assert running.status_code == 409


def test_supplier_scout_api_exposes_user_triggered_edge_capture_lifecycle() -> None:
    client = TestClient(create_app(service=SupplierScoutApiService()))

    created = client.post(
        "/api/v1/supplier-scout/captures",
        json={"supplier_id": "sup_123", "max_pages": 3, "max_offers": 100},
    )
    pending = client.get(
        "/api/v1/supplier-scout/captures/pending",
        params={"shop_host": "shop3w093345o1043.1688.com"},
    )
    missing_host = client.get("/api/v1/supplier-scout/captures/pending")
    claimed = client.post(
        "/api/v1/supplier-scout/captures/cap_123/claim",
        headers={"X-Proteus-Capture-Token": "capture-secret"},
        json={"page_url": STORE_URL, "extension_version": "0.2.6"},
    )
    captured = client.post(
        "/api/v1/supplier-scout/captures/cap_123/pages",
        headers={"X-Proteus-Capture-Token": "capture-secret"},
        json={
            "page_number": 1,
            "page_url": STORE_URL,
            "has_next_page": False,
            "available_offer_count": 1,
            "empty_state": False,
            "offers": [
                {
                    "offer_id": "10001",
                    "title": "测试商品",
                    "offer_url": "https://detail.1688.com/offer/10001.html",
                }
            ],
            "evidence": {
                "dom_sha256": "a" * 64,
                "parser_probe": {
                    "anchor_count": 10,
                    "iframe_count": 0,
                    "shadow_host_count": 0,
                    "configured_offer_match_count": 1,
                    "configured_next_match_count": 0,
                    "offer_candidates": [],
                    "pagination_candidates": [],
                    "frame_candidates": [],
                    "shadow_root_hints": [
                        {
                            "tag": "x-products",
                            "child_count": 3,
                            "anchor_count": 2,
                            "configured_offer_match_count": 2,
                            "offer_candidate_count": 2,
                            "nested_shadow_host_count": 0,
                            "text_length": 80,
                        }
                    ],
                    "link_candidates": [
                        {
                            "tag": "a",
                            "url": "https://detail.1688.com/offer/10001.html",
                            "text": "测试商品",
                        }
                    ],
                    "light_dom_identity_markers": ["data-offer-id"],
                    "light_dom_structure_hints": [
                        {
                            "tag": "div",
                            "class_name": "product-card",
                            "child_count": 3,
                            "anchor_count": 1,
                            "image_count": 1,
                            "visible": True,
                            "identity_attribute_names": ["data-offer-id"],
                            "text_length": 40,
                        }
                    ],
                    "iframe_hints": [
                        {
                            "host_class": "1688",
                            "url": "https://show.1688.com/page/offers.html",
                            "visible": True,
                            "width": 300,
                            "height": 150,
                            "same_origin_accessible": False,
                            "anchor_count": 0,
                            "offer_candidate_count": 0,
                            "text_length": 0,
                        }
                    ],
                    "embedded_data_markers": [],
                },
            },
        },
    )
    status_response = client.get("/api/v1/supplier-scout/captures/cap_123")
    latest = client.get("/api/v1/supplier-scout/suppliers/sup_123/snapshots/latest")
    paused = client.post(
        "/api/v1/supplier-scout/captures/cap_123/pause",
        headers={"X-Proteus-Capture-Token": "capture-secret"},
        json={"reason": "RISK_CONTROL", "page_url": STORE_URL},
    )

    assert created.status_code == 201
    assert created.json()["capture_token"] == "capture-secret"
    assert pending.json()["capture"]["capture_id"] == "cap_123"
    assert missing_host.status_code == 422
    assert claimed.json()["status"] == "CAPTURING"
    assert captured.json()["snapshot_id"] == "snap_123"
    assert status_response.json()["status"] == "CAPTURING"
    assert latest.json()["snapshot"]["snapshot_id"] == "snap_123"
    assert paused.json()["status"] == "PAUSED"


def test_supplier_capture_mutations_require_the_opaque_token() -> None:
    client = TestClient(create_app(service=SupplierScoutApiService()))

    response = client.post(
        "/api/v1/supplier-scout/captures/cap_123/claim",
        json={"page_url": STORE_URL},
    )

    assert response.status_code == 422


def test_supplier_capture_parser_probe_rejects_unsanitized_diagnostic_values() -> None:
    client = TestClient(create_app(service=SupplierScoutApiService()))

    response = client.post(
        "/api/v1/supplier-scout/captures/cap_123/pages",
        headers={"X-Proteus-Capture-Token": "capture-secret"},
        json={
            "page_number": 1,
            "page_url": STORE_URL,
            "has_next_page": None,
            "available_offer_count": None,
            "empty_state": False,
            "offers": [],
            "evidence": {
                "dom_sha256": "b" * 64,
                "parser_probe": {
                    "anchor_count": 1,
                    "iframe_count": 0,
                    "shadow_host_count": 0,
                    "configured_offer_match_count": 0,
                    "configured_next_match_count": 0,
                    "offer_candidates": [
                        {
                            "tag": "a",
                            "url": f"{STORE_URL}?token=secret",
                        }
                    ],
                    "pagination_candidates": [],
                    "frame_candidates": [],
                    "embedded_data_markers": [],
                },
            },
        },
    )

    assert response.status_code == 422


def test_supplier_scout_api_validates_bounds_categories_and_grade_order() -> None:
    client = TestClient(create_app(service=SupplierScoutApiService()))

    too_many_pages = client.post(
        "/api/v1/supplier-scout/runs",
        json={"supplier_id": "sup_123", "max_pages": 21},
    )
    unknown_category = client.post(
        "/api/v1/supplier-scout/runs",
        json={"supplier_id": "sup_123", "selected_category_ids": ["unknown"]},
    )
    unordered_grades = client.post(
        "/api/v1/supplier-scout/runs",
        json={
            "supplier_id": "sup_123",
            "grade_a_max_competitors": 8,
            "grade_a_minus_max_competitors": 8,
        },
    )

    assert too_many_pages.status_code == 422
    assert unknown_category.status_code == 422
    assert unordered_grades.status_code == 422


def test_default_service_persists_and_binds_supplier_inspection_audit(
    tmp_path: Path,
) -> None:
    store = SupplierScoutStore(tmp_path / "supplier-scout.sqlite3")

    def collector(target: str, **_kwargs):
        return {
            "acquisition_status": "RISK_CONTROL",
            "canonical_url": target,
            "inventory_complete": False,
            "offers": [],
            "diagnostics": [{"code": "MANUAL_CHALLENGE_REQUIRED"}],
        }

    service = DefaultFrontendService(
        category_catalog=CategoryCatalog(tmp_path / "categories.sqlite3"),
        supplier_store=store,
        supplier_store_collector=collector,
    )
    supplier = service.add_supplier_scout_supplier(
        {"label": "测试供应商", "target": STORE_URL}
    )
    inspected = service.inspect_supplier_scout_supplier(
        {
            "target": STORE_URL,
            "max_pages": 1,
            "max_offers": 20,
            "headed": False,
            "challenge_timeout_seconds": 180,
        }
    )

    audit = store.get_inspection(inspected["inspection"]["inspection_id"])
    assert audit["supplier_id"] == supplier["supplier_id"]
    assert audit["diagnostics"] == [{"code": "MANUAL_CHALLENGE_REQUIRED"}]


def test_default_service_reuses_a_same_supplier_edge_snapshot_without_reacquiring(
    tmp_path: Path,
) -> None:
    store = SupplierScoutStore(tmp_path / "supplier-scout.sqlite3")
    source = store.add_supplier("测试供应商", STORE_URL)
    saved = store.save_snapshot(
        source["supplier_id"],
        {
            "schema_version": "0.2.6",
            "provider": "PROTEUS_EDGE_EXTENSION",
            "source_method": "USER_INITIATED_BROWSER_EXTENSION",
            "canonical_url": STORE_URL,
            "supplier": {"shop_host": "shop3w093345o1043.1688.com"},
            "retrieved_at": "2026-08-30T00:00:00Z",
            "acquisition_status": "EMPTY",
            "pages_attempted": 1,
            "pages_completed": 1,
            "observed_offer_count": 0,
            "available_offer_count": 0,
            "has_next_page": False,
            "inventory_complete": True,
            "offers": [],
            "warnings": [],
        },
    )

    def collector(*_args, **_kwargs):
        raise AssertionError("captured snapshot must skip the Playwright bridge")

    service = DefaultFrontendService(
        category_catalog=CategoryCatalog(tmp_path / "categories.sqlite3"),
        supplier_store=store,
        supplier_store_collector=collector,
    )
    submitted = service.submit_supplier_scout_run(
        {
            "supplier_id": source["supplier_id"],
            "inventory_snapshot_id": saved["snapshot_id"],
            "selected_category_ids": [],
            "max_pages": 3,
            "max_offers": 100,
            "headed": False,
            "challenge_timeout_seconds": 180,
            "market_request_budget": 0,
            "max_amazon_queries_per_family": 3,
            "grade_a_max_competitors": 5,
            "grade_a_minus_max_competitors": 8,
            "min_family_price_usd": 20,
            "min_observed_ebay_demand": 1,
        }
    )
    deadline = monotonic() + 2
    record = service.get_supplier_scout_run(submitted["run_id"])
    while record and record["status"] not in {"COMPLETED", "FAILED"} and monotonic() < deadline:
        sleep(0.01)
        record = service.get_supplier_scout_run(submitted["run_id"])

    assert record is not None
    assert record["status"] == "COMPLETED"
    assert record["result"]["inventory"]["snapshot_id"] == saved["snapshot_id"]
    assert record["result"]["inventory"]["acquisition_status"] == "EMPTY"


def test_default_service_rejects_a_blocked_zero_offer_snapshot(
    tmp_path: Path,
) -> None:
    store = SupplierScoutStore(tmp_path / "supplier-scout.sqlite3")
    source = store.add_supplier("测试供应商", STORE_URL)
    saved = store.save_snapshot(
        source["supplier_id"],
        {
            "schema_version": "0.2.6",
            "provider": "PROTEUS_EDGE_EXTENSION",
            "source_method": "USER_INITIATED_BROWSER_EXTENSION",
            "canonical_url": STORE_URL,
            "supplier": {"shop_host": "shop3w093345o1043.1688.com"},
            "retrieved_at": "2026-08-30T00:00:00Z",
            "acquisition_status": "RISK_CONTROL",
            "pages_attempted": 0,
            "pages_completed": 0,
            "observed_offer_count": 0,
            "available_offer_count": None,
            "has_next_page": None,
            "inventory_complete": False,
            "offers": [],
            "warnings": ["RISK_CONTROL"],
        },
    )
    service = DefaultFrontendService(
        category_catalog=CategoryCatalog(tmp_path / "categories.sqlite3"),
        supplier_store=store,
    )

    with pytest.raises(ValueError, match="not usable"):
        service.submit_supplier_scout_run(
            {
                "supplier_id": source["supplier_id"],
                "inventory_snapshot_id": saved["snapshot_id"],
                "selected_category_ids": [],
                "max_pages": 3,
                "max_offers": 100,
                "headed": False,
                "challenge_timeout_seconds": 180,
                "market_request_budget": 0,
                "max_amazon_queries_per_family": 3,
                "grade_a_max_competitors": 5,
                "grade_a_minus_max_competitors": 8,
                "min_family_price_usd": 20,
                "min_observed_ebay_demand": 1,
            }
        )


def test_supplier_scout_inspection_rejects_non_1688_and_http_targets() -> None:
    client = TestClient(create_app(service=SupplierScoutApiService()))

    foreign = client.post(
        "/api/v1/supplier-scout/suppliers/inspect",
        json={"target": "https://example.com/page/offerlist.htm"},
    )
    insecure = client.post(
        "/api/v1/supplier-scout/suppliers/inspect",
        json={"target": "http://shop3w093345o1043.1688.com/page/offerlist.htm"},
    )
    generic_1688 = client.post(
        "/api/v1/supplier-scout/suppliers/inspect",
        json={"target": "https://www.1688.com/page/offerlist.htm"},
    )

    assert foreign.status_code == 422
    assert insecure.status_code == 422
    assert generic_1688.status_code == 422
