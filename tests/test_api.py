from __future__ import annotations

from fastapi.testclient import TestClient

from proteus.api import create_app


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
