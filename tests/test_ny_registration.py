from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.parse import parse_qs, urlencode, urlparse

from proteus.providers.ny_registration import (
    NhtsaRequest,
    NhtsaResponse,
    NyRequest,
    NyResponse,
    collect_ny_registered_vehicle_proxy,
)


@dataclass
class NyFixtureTransport:
    total: int = 1000

    def __post_init__(self) -> None:
        self.requests: list[NyRequest] = []

    def __call__(self, request: NyRequest) -> NyResponse:
        self.requests.append(request)
        query = parse_qs(urlparse(request.url).query)
        if query.get("$select") == ["count(distinct vin) as registrations"]:
            return NyResponse(200, json.dumps([{"registrations": str(self.total)}]).encode())
        offset = int(query.get("$offset", ["0"])[0])
        limit = int(query.get("$limit", ["3"])[0])
        rows = [
            {"vin": f"VIN{offset + index:04d}"}
            for index in range(min(limit, max(0, self.total - offset)))
        ]
        return NyResponse(200, json.dumps(rows).encode())


class NhtsaFixtureTransport:
    def __init__(self, *, model: str = "Camry", malformed: bool = False) -> None:
        self.requests: list[NhtsaRequest] = []
        self.model = model
        self.malformed = malformed

    def __call__(self, request: NhtsaRequest) -> NhtsaResponse:
        self.requests.append(request)
        if self.malformed:
            return NhtsaResponse(200, b"{}")
        params = parse_qs(request.body.decode())
        data = params["data"][0]
        rows = []
        for item in data.split(";"):
            vin, year = item.split(",")
            rows.append({"VIN": vin, "ModelYear": year, "Make": "Toyota", "Model": self.model})
        return NhtsaResponse(200, json.dumps({"Results": rows}).encode())


def test_anonymous_ny_and_nhtsa_requests_estimate_model_share() -> None:
    ny = NyFixtureTransport()
    nhtsa = NhtsaFixtureTransport()
    result = collect_ny_registered_vehicle_proxy(
        [{"year": 2015, "make": "Toyota", "model": "Camry", "trim": "LE"}],
        transport=ny,
        nhtsa_transport=nhtsa,
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert result["status"] == "SUCCESS"
    assert result["provider"] == "NY_DMV_NHTSA_REGISTERED_VEHICLE_PROXY"
    assert result["metric"] == "NY_REGISTERED_VEHICLE_MODEL_ESTIMATE_PROXY"
    assert result["vehicle_count_proxy"] == 1000
    assert result["official_vio"] is False
    assert result["sampling_randomized"] is False
    assert len(ny.requests) == 4
    count_query = parse_qs(urlparse(ny.requests[0].url).query)
    assert count_query["$select"] == ["count(distinct vin) as registrations"]
    assert "api_key" not in ny.requests[0].url
    assert all("$order" not in parse_qs(urlparse(item.url).query) for item in ny.requests)
    body = parse_qs(nhtsa.requests[0].body.decode())
    assert body["format"] == ["json"]
    assert body["data"][0].split(";")[0].endswith(",2015")


def test_fitment_aliases_are_deduplicated_and_unknown_models_do_not_match() -> None:
    ny = NyFixtureTransport(total=100)
    nhtsa = NhtsaFixtureTransport(model="Corolla")
    result = collect_ny_registered_vehicle_proxy(
        [
            {"year": 2015, "make": "Toyota", "model": "Camry"},
            {"year": 2015, "make": "TOYOTA", "model": "Camry", "trim": "XLE"},
        ],
        transport=ny,
        nhtsa_transport=nhtsa,
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert len(result["groups"]) == 1
    assert result["vehicle_count_proxy"] == 0


def test_incomplete_decode_is_partial_and_never_passes_as_zero() -> None:
    ny = NyFixtureTransport(total=1000)
    nhtsa = NhtsaFixtureTransport(malformed=True)
    result = collect_ny_registered_vehicle_proxy(
        [{"year": 2015, "make": "Toyota", "model": "Camry"}],
        transport=ny,
        nhtsa_transport=nhtsa,
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["vehicle_count_proxy"] is None
    assert result["diagnostics"]
    assert result["groups"][0]["status"] == "INCOMPLETE"


def test_empty_registration_group_is_complete_zero() -> None:
    result = collect_ny_registered_vehicle_proxy(
        [{"year": 2015, "make": "Toyota", "model": "Camry"}],
        transport=NyFixtureTransport(total=0),
        nhtsa_transport=NhtsaFixtureTransport(),
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert result["status"] == "SUCCESS"
    assert result["vehicle_count_proxy"] == 0
    assert result["groups"][0]["sample_returned"] == 0


def test_fitment_group_limit_is_partial_and_bounded() -> None:
    ny = NyFixtureTransport(total=100)
    result = collect_ny_registered_vehicle_proxy(
        [{"year": 2000 + index, "make": "Toyota", "model": "Camry"} for index in range(13)],
        transport=ny,
        nhtsa_transport=NhtsaFixtureTransport(),
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert result["status"] == "PARTIAL_SUCCESS"
    assert result["vehicle_count_proxy"] is None
    assert len(result["groups"]) == 12
    assert len(ny.requests) == 48
    assert result["diagnostics"][0]["code"] == "FITMENT_GROUP_LIMIT"


def test_models_for_one_year_make_share_one_sample() -> None:
    ny = NyFixtureTransport(total=100)
    nhtsa = NhtsaFixtureTransport(model="Camry")
    result = collect_ny_registered_vehicle_proxy(
        [
            {"year": 2015, "make": "Toyota", "model": "Camry"},
            {"year": 2015, "make": "Toyota", "model": "Corolla"},
        ],
        transport=ny,
        nhtsa_transport=nhtsa,
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert result["status"] == "SUCCESS"
    assert len(result["groups"]) == 2
    assert len(ny.requests) == 4
    assert result["groups"][0]["estimated_model_registrations"] == 100
    assert result["groups"][1]["estimated_model_registrations"] == 0
