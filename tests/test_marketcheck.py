from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

from proteus.providers import marketcheck as marketcheck_module
from proteus.providers.marketcheck import (
    HttpRequest,
    HttpResponse,
    collect_us_used_active_vin_proxy,
)


@dataclass
class RecordingTransport:
    response: HttpResponse

    def __post_init__(self) -> None:
        self.requests: list[HttpRequest] = []

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        return self.response


def test_marketcheck_collects_deduplicated_us_used_active_vin_proxy() -> None:
    transport = RecordingTransport(
        HttpResponse(200, json.dumps({"num_found": 54321}).encode("utf-8"))
    )
    fitments = [
        {"year": 2015, "make": "Toyota", "model": "Camry", "trim": "LE"},
        {"year": 2016, "make": "Toyota", "model": "Camry", "trim": "LE"},
    ]

    outcome = collect_us_used_active_vin_proxy(
        fitments,
        api_key="market-secret",
        transport=transport,
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert outcome["status"] == "SUCCESS"
    assert outcome["metric"] == "US_USED_ACTIVE_INVENTORY_DISTINCT_VIN_PROXY"
    assert outcome["vehicle_count_proxy"] == 54321
    assert outcome["official_vio"] is False
    assert outcome["fitment_resolution"] == "YMMT_ONLY"
    assert "market-secret" not in json.dumps(outcome)

    query = parse_qs(urlparse(transport.requests[0].url).query)
    assert query["country"] == ["us"]
    assert query["rows"] == ["0"]
    assert query["dedup"] == ["true"]
    assert query["car_type"] == ["used"]
    assert query["ymmt"] == ["2015|Toyota|Camry|LE,2016|Toyota|Camry|LE"]


def test_marketcheck_does_not_turn_missing_fitment_into_zero() -> None:
    outcome = collect_us_used_active_vin_proxy(
        [],
        api_key="market-secret",
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert outcome["status"] == "NO_FITMENT"
    assert outcome["vehicle_count_proxy"] is None


def test_marketcheck_transport_does_not_follow_credential_bearing_redirects(
    monkeypatch,
) -> None:
    class RedirectingOpener:
        def open(self, request, timeout: float):
            raise HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "https://attacker.invalid/capture"},
                None,
            )

    monkeypatch.setattr(
        marketcheck_module, "build_opener", lambda handler: RedirectingOpener()
    )

    result = marketcheck_module._transport(
        HttpRequest("https://api.marketcheck.com/test?api_key=secret", 1.0)
    )

    assert result.status_code == 302
