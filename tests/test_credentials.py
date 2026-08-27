from __future__ import annotations

import json

from proteus.credentials import (
    HIOBUY_API_KEY,
    HIOBUY_RECEIVER,
    SERPAPI_API_KEY,
    configuration_status,
    resolve_receiver,
    resolve_secret,
)


class MemoryBackend:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


def test_environment_overrides_os_secret_store() -> None:
    backend = MemoryBackend({SERPAPI_API_KEY: "stored-secret"})

    resolved = resolve_secret(
        SERPAPI_API_KEY,
        environment={SERPAPI_API_KEY: "environment-secret"},
        backend=backend,
    )

    assert resolved == "environment-secret"


def test_receiver_is_loaded_from_secret_store_and_validated() -> None:
    receiver = {
        "name": "Test Buyer",
        "mobile": "13800000000",
        "province": "广东省",
        "city": "深圳市",
        "district": "南山区",
        "address": "测试地址 1 号",
    }
    backend = MemoryBackend({HIOBUY_RECEIVER: json.dumps(receiver)})

    assert resolve_receiver(backend=backend) == receiver


def test_configuration_status_never_returns_secret_values() -> None:
    backend = MemoryBackend(
        {
            SERPAPI_API_KEY: "serp-secret",
            HIOBUY_API_KEY: "hio-secret",
            HIOBUY_RECEIVER: json.dumps(
                {
                    "name": "Buyer",
                    "mobile": "13800000000",
                    "province": "广东省",
                    "city": "深圳市",
                    "district": "南山区",
                    "address": "测试地址",
                }
            ),
        }
    )

    status = configuration_status(environment={}, backend=backend)
    serialized = json.dumps(status, ensure_ascii=False)

    assert status["ready"] is True
    assert status["account_count"] == 1
    assert status["profile"] == "market-screening-base"
    assert status["profiles"]["supply_verified"]["ready"] is True
    assert status["credentials"][SERPAPI_API_KEY]["configured"] is True
    assert status["credentials"][HIOBUY_API_KEY]["configured"] is True
    assert "serp-secret" not in serialized
    assert "hio-secret" not in serialized
    assert "13800000000" not in serialized


def test_serpapi_alone_is_enough_for_base_configuration() -> None:
    status = configuration_status(
        environment={},
        backend=MemoryBackend({SERPAPI_API_KEY: "serp-secret"}),
    )

    assert status["ready"] is True
    assert status["profiles"]["market_screening_base"]["ready"] is True
    assert status["profiles"]["strict_market_screening"]["ready"] is False
    assert status["profiles"]["supply_verified"]["ready"] is False
