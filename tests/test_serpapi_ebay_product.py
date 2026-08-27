from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from proteus.providers.serpapi_ebay import SerpApiRequest, SerpApiResponse
from proteus.providers.serpapi_ebay_product import collect_ebay_compatibility


@dataclass
class RecordingTransport:
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        self.requests: list[SerpApiRequest] = []

    def __call__(self, request: SerpApiRequest) -> SerpApiResponse:
        self.requests.append(request)
        return SerpApiResponse(200, json.dumps(self.payload).encode("utf-8"))


def test_ebay_product_normalizes_and_deduplicates_compatibility() -> None:
    transport = RecordingTransport(
        {
            "search_metadata": {"id": "product-1", "status": "Success"},
            "search_parameters": {
                "engine": "ebay_product",
                "product_id": "123456789012",
                "ebay_domain": "ebay.com",
            },
            "product_results": {
                "product_id": "123456789012",
                "compatibility": {
                    "items": [
                        {
                            "year": "2015",
                            "make": "Toyota",
                            "model": "Camry",
                            "trim": "LE Sedan 4-Door",
                            "engine": "2.5L 2494CC 4Cu. In. l4 GAS DOHC",
                            "notes": "Base fitment",
                        },
                        {
                            "year": "2015",
                            "make": " Toyota ",
                            "model": "Camry",
                            "trim": "LE Sedan 4-Door",
                            "engine": "2.5L 2494CC 4Cu. In. l4 GAS DOHC",
                        },
                    ]
                },
            },
        }
    )

    outcome = collect_ebay_compatibility(
        "123456789012",
        api_key="secret",
        transport=transport,
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert outcome["status"] == "SUCCESS"
    assert outcome["listing_id"] == "123456789012"
    assert outcome["fitment_count"] == 1
    assert outcome["fitments"][0]["year"] == 2015
    assert outcome["fitments"][0]["make"] == "Toyota"
    assert "secret" not in json.dumps(outcome)
    query = parse_qs(urlparse(transport.requests[0].url).query)
    assert query["engine"] == ["ebay_product"]
    assert query["product_id"] == ["123456789012"]


def test_ebay_product_fails_closed_when_compatibility_is_missing() -> None:
    outcome = collect_ebay_compatibility(
        "123",
        api_key="secret",
        transport=RecordingTransport(
            {
                "search_metadata": {"status": "Success"},
                "search_parameters": {
                    "engine": "ebay_product",
                    "product_id": "123",
                    "ebay_domain": "ebay.com",
                },
                "product_results": {"product_id": "123"},
            }
        ),
        retrieved_at="2026-08-27T10:00:00Z",
    )

    assert outcome["status"] == "NO_COMPATIBILITY"
    assert outcome["fitments"] == []
