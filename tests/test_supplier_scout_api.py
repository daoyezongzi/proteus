from __future__ import annotations

from pathlib import Path

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
