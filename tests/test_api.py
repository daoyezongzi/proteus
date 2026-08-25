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

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert config.json()["account_count"] == 2
    assert providers.status_code == 200
    assert submitted.status_code == 202
    assert submitted.json() == {"run_id": "run-123", "status": "QUEUED"}
    assert run.json()["status"] == "COMPLETED"
    assert missing.status_code == 404


def test_frontend_api_rejects_invalid_run_limits() -> None:
    client = TestClient(create_app(service=FakeFrontendService()))

    response = client.post(
        "/api/v1/runs",
        json={"max_candidates": 0, "max_moq": 5},
    )

    assert response.status_code == 422
