from __future__ import annotations

from time import monotonic, sleep

from fastapi.testclient import TestClient

from proteus.api import InMemoryRunManager, create_app


def test_in_memory_run_manager_marks_failed_progress() -> None:
    def failing_runner(request: dict, *, progress) -> dict:
        progress(
            {
                "phase": "1688_supplier",
                "current": 1,
                "total": 2,
                "last_query": "53630-53010",
                "provider": "LOCAL_1688_CLI",
                "budget_used": 1,
            }
        )
        raise RuntimeError("provider unavailable")

    manager = InMemoryRunManager(failing_runner, supports_progress=True)
    submission = manager.submit({})
    deadline = monotonic() + 1.0
    record = manager.get(submission["run_id"])
    while record and record["status"] not in {"FAILED", "COMPLETED"} and monotonic() < deadline:
        sleep(0.01)
        record = manager.get(submission["run_id"])

    assert record is not None
    assert record["status"] == "FAILED"
    assert record["progress"] == {
        "phase": "failed",
        "current": 1,
        "total": 2,
        "last_query": "53630-53010",
        "provider": "LOCAL_1688_CLI",
        "budget_used": 1,
        "updated_at": record["progress"]["updated_at"],
    }


class FakeFrontendService:
    def configuration_status(self) -> dict:
        return {
            "profile": "two-account-managed",
            "ready": True,
            "account_count": 2,
            "credentials": {},
            "receiver": {"configured": True, "source": "os_keyring"},
        }

    def provider_status(self) -> dict:
        return {"profile": "two-account-managed", "providers": []}

    def submit_run(self, request: dict) -> dict:
        assert request == {
            "max_candidates": 10,
            "max_moq": 5,
            "ebay_category_id": "6028",
            "discovery_pages": 1,
        }
        return {"run_id": "run-123", "status": "QUEUED"}

    def get_run(self, run_id: str) -> dict | None:
        if run_id == "run-123":
            return {"run_id": run_id, "status": "COMPLETED", "reports": []}
        return None

    def submit_mvp_run(self, request: dict) -> dict:
        assert request == {
            "max_candidates": 10,
            "ebay_category_id": "6028",
            "discovery_keyword": "OEM",
            "discovery_pages": 1,
            "min_ebay_trailing_year_units_exclusive": 0,
            "max_amazon_us_exact_competitors": 5,
            "min_amazon_price_usd": 20.0,
            "max_amazon_active_sellers": 10,
            "max_fitment_listings": 3,
        }
        return {"run_id": "mvp-123", "status": "QUEUED"}

    def get_mvp_run(self, run_id: str) -> dict | None:
        if run_id == "mvp-123":
            return {
                "run_id": run_id,
                "status": "COMPLETED",
                "result": {"reports": []},
            }
        return None

    def submit_northway_run(self, request: dict) -> dict:
        assert request == {
            "archetype": "fog_light_bezel",
            "discovery_pages": 1,
            "request_budget": 12,
            "max_1688_checks": 20,
            "enable_1688_prefilter": True,
            "max_amazon_queries_per_family": 3,
            "grade_a_max_competitors": 5,
            "grade_a_minus_max_competitors": 8,
            "min_family_price_usd": 20.0,
            "min_observed_ebay_demand": 1,
        }
        return {"run_id": "northway-123", "status": "QUEUED"}

    def get_northway_run(self, run_id: str) -> dict | None:
        if run_id == "northway-123":
            return {
                "run_id": run_id,
                "status": "COMPLETED",
                "result": {
                    "schema_version": "0.2.5",
                    "profile": "northway-product-family-mvp",
                    "reports": [],
                    "ranking": [],
                },
            }
        if run_id == "northway-running":
            return {"run_id": run_id, "status": "RUNNING", "result": None}
        return None


def test_frontend_api_exposes_health_config_providers_and_async_runs() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    health = client.get("/api/v1/health")
    config = client.get("/api/v1/config/status")
    providers = client.get("/api/v1/providers")
    submitted = client.post(
        "/api/v1/runs",
        json={"max_candidates": 10, "max_moq": 5},
    )
    run = client.get("/api/v1/runs/run-123")
    missing = client.get("/api/v1/runs/missing")
    policy = client.get("/api/v1/screening/policy")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert config.json()["account_count"] == 2
    assert providers.status_code == 200
    assert submitted.status_code == 202
    assert submitted.json() == {"run_id": "run-123", "status": "QUEUED"}
    assert run.json()["status"] == "COMPLETED"
    assert missing.status_code == 404
    assert policy.status_code == 200
    assert policy.json()["profile"] == "strict-market-screening"


def test_frontend_api_rejects_invalid_run_limits() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    response = client.post(
        "/api/v1/runs",
        json={"max_candidates": 0, "max_moq": 5},
    )

    assert response.status_code == 422


def test_frontend_api_exposes_threshold_driven_automatic_mvp_jobs() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    policy = client.get("/api/v1/mvp/policy")
    submitted = client.post(
        "/api/v1/mvp/runs",
        json={"max_candidates": 10},
    )
    run = client.get("/api/v1/mvp/runs/mvp-123")
    missing = client.get("/api/v1/mvp/runs/missing")

    assert policy.status_code == 200
    assert policy.json()["profile"] == "automatic-mvp"
    assert policy.json()["human_review_required"] is True
    assert submitted.status_code == 202
    assert submitted.json() == {"run_id": "mvp-123", "status": "QUEUED"}
    assert run.json()["status"] == "COMPLETED"
    assert missing.status_code == 404

    openapi = client.get("/api/openapi.json").json()
    request_schema = openapi["paths"]["/api/v1/mvp/runs"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]
    assert request_schema["$ref"].endswith("/AutomaticMvpRunRequest")
    model = openapi["components"]["schemas"]["AutomaticMvpRunRequest"]
    assert "min_us_active_vins" not in model["properties"]


def test_frontend_api_exposes_northway_family_screening_and_json_export() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    policy = client.get("/api/v1/northway/policy")
    submitted = client.post(
        "/api/v1/northway/runs",
        json={"archetype": "fog_light_bezel", "request_budget": 12},
    )
    run = client.get("/api/v1/northway/runs/northway-123")
    export = client.get("/api/v1/northway/runs/northway-123/export")
    compact_export = client.get("/api/v1/northway/runs/northway-123/export/compact")
    running_export = client.get("/api/v1/northway/runs/northway-running/export")

    assert policy.status_code == 200
    assert policy.json()["profile"] == "northway-product-family-mvp"
    assert policy.json()["run_bounds"]["candidate_cap"] is None
    assert [
        group["label_zh"] for group in policy.json()["category_catalog"]["groups"]
    ] == ["拉线", "塑料件", "低责任金属件"]
    assert submitted.status_code == 202
    assert submitted.json() == {"run_id": "northway-123", "status": "QUEUED"}
    assert run.json()["result"]["schema_version"] == "0.2.5"
    assert export.status_code == 200
    assert export.headers["content-disposition"].endswith('northway-123.json"')
    assert export.json()["ranking"] == []
    assert compact_export.status_code == 200
    assert compact_export.headers["content-disposition"].endswith('northway-123-compact.json"')
    assert compact_export.json()["export_format"] == "compact_v1"
    assert running_export.status_code == 409

    openapi = client.get("/api/openapi.json").json()
    model = openapi["components"]["schemas"]["NorthwayMvpRunRequest"]
    assert "max_candidates" not in model["properties"]
    assert "archetype" in model["properties"]
    assert "max_1688_checks" in model["properties"]
    assert model["properties"]["enable_1688_prefilter"]["default"] is True
    assert model["properties"]["grade_a_max_competitors"]["default"] == 5
    assert model["properties"]["grade_a_minus_max_competitors"]["default"] == 8
    assert "max_competitive_products" not in model["properties"]


def test_frontend_api_rejects_unknown_single_archetype_field() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    response = client.post(
        "/api/v1/northway/runs",
        json={"archetype": "universal_mud_flap"},
    )

    assert response.status_code == 422


def test_frontend_api_requires_budget_for_selected_archetype_pages() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    response = client.post(
        "/api/v1/northway/runs",
        json={"archetype": "fog_light_bezel", "discovery_pages": 2, "request_budget": 1},
    )

    assert response.status_code == 422


def test_frontend_api_requires_ordered_competition_grade_thresholds() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    response = client.post(
        "/api/v1/northway/runs",
        json={
            "archetype": "fog_light_bezel",
            "grade_a_max_competitors": 8,
            "grade_a_minus_max_competitors": 8,
        },
    )

    assert response.status_code == 422


def test_frontend_can_evaluate_normalized_strict_screening_evidence() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))
    source = {
        "source_reference": "https://example.invalid/evidence",
        "retrieved_at": "2026-08-27T08:00:00Z",
    }

    response = client.post(
        "/api/v1/screening/evaluate",
        json={
            "part_number": "53630-53010",
            "min_us_vehicle_parc": 50000,
            "ebay_annual_sales": {
                **source,
                "provider_id": "ebay-product-research-import",
                "marketplace_id": "EBAY_US",
                "window_days": 365,
                "units_sold": 21,
            },
            "amazon_competition": {
                **source,
                "provider_id": "serpapi-amazon",
                "marketplace_id": "AMAZON_US",
                "exact_competitor_count": 5,
            },
            "vehicle_parc": {
                **source,
                "provider_id": "tecalliance-vio",
                "country_code": "US",
                "fitment_resolved": True,
                "compatible_vehicle_count": 50000,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "MARKET_OPPORTUNITY_CANDIDATE"

    openapi = client.get("/api/openapi.json").json()
    response_schema = openapi["paths"]["/api/v1/screening/evaluate"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert response_schema["$ref"].endswith("/StrictScreeningResponse")


def test_frontend_requires_explicit_vehicle_parc_threshold() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    response = client.post(
        "/api/v1/screening/evaluate",
        json={"part_number": "53630-53010"},
    )

    assert response.status_code == 422


def test_frontend_rejects_part_number_without_ascii_identity() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    response = client.post(
        "/api/v1/screening/evaluate",
        json={"part_number": "---", "min_us_vehicle_parc": 1},
    )

    assert response.status_code == 422
