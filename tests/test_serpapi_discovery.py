from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from proteus.io import validate_candidate_discovery
from proteus.providers.serpapi_ebay import SerpApiRequest, SerpApiResponse
from proteus.providers.serpapi_ebay_discovery import (
    SERPAPI_EBAY_DISCOVERY_PROVIDER,
    collect_ebay_sold_candidates,
    extract_part_number_candidates,
)


API_KEY = "serp-secret-never-output"
RETRIEVED_AT = "2026-08-25T10:00:00Z"


@dataclass
class RecordingTransport:
    response: SerpApiResponse

    def __post_init__(self) -> None:
        self.requests: list[SerpApiRequest] = []

    def __call__(self, request: SerpApiRequest) -> SerpApiResponse:
        self.requests.append(request)
        return self.response


def response(payload: Any, status_code: int = 200) -> SerpApiResponse:
    return SerpApiResponse(status_code, json.dumps(payload).encode("utf-8"))


def sold_category_payload() -> dict[str, Any]:
    return {
        "search_metadata": {"id": "discovery_123", "status": "Success"},
        "search_parameters": {
            "engine": "ebay",
            "ebay_domain": "ebay.com",
            "_sacat": "6028",
            "show_only": "Sold",
            "LH_ItemCondition": "1000",
            "_salic": "1",
            "_stpos": "10001",
            "_pgn": "1",
        },
        "search_information": {"total_results": 2},
        "organic_results": [
            {
                "title": "New OEM Toyota Lexus Hood Latch 53630-53010",
                "link": "https://www.ebay.com/itm/123456789012",
                "product_id": "123456789012",
                "condition": "Brand New",
                "quantity_sold": "32 sold",
                "extracted_quantity_sold": 32,
            },
            {
                "title": "Universal auto trim 12V 2024 model",
                "link": "https://www.ebay.com/itm/999999999999",
                "product_id": "999999999999",
                "condition": "Brand New",
                "quantity_sold": "5 sold",
                "extracted_quantity_sold": 5,
            },
        ],
    }


def test_part_extraction_prefers_part_shaped_tokens_and_rejects_noise() -> None:
    assert extract_part_number_candidates(
        "New OEM 53630-53010 / LR024154 replacement 12V 2024"
    ) == ("53630-53010", "LR024154")


def test_category_sold_search_discovers_traceable_part_candidates() -> None:
    transport = RecordingTransport(response(sold_category_payload()))

    outcome = collect_ebay_sold_candidates(
        api_key=API_KEY,
        category_id="6028",
        max_candidates=20,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    validate_candidate_discovery(outcome, label="SerpApi discovery fixture")
    assert outcome["provider"] == SERPAPI_EBAY_DISCOVERY_PROVIDER
    assert outcome["status"] == "PARTIAL_SUCCESS"
    assert outcome["category"] == {
        "id": "6028",
        "name": "Auto Parts & Accessories",
    }
    assert len(outcome["candidates"]) == 1
    candidate = outcome["candidates"][0]
    assert candidate["raw_part_number"] == "53630-53010"
    assert candidate["canonical_part_number"] == "5363053010"
    assert candidate["source_listing_id"] == "123456789012"
    assert candidate["source_sold_count"] == 32
    assert API_KEY not in json.dumps(outcome)

    query = parse_qs(urlparse(transport.requests[0].url).query)
    assert query["_sacat"] == ["6028"]
    assert query["show_only"] == ["Sold"]
    assert "_nkw" not in query


def test_discovery_missing_explicit_sold_count_fails_closed() -> None:
    payload = sold_category_payload()
    payload["organic_results"][0].pop("quantity_sold")
    payload["organic_results"][0].pop("extracted_quantity_sold")
    payload["organic_results"] = payload["organic_results"][:1]
    payload["search_information"]["total_results"] = 1

    outcome = collect_ebay_sold_candidates(
        api_key=API_KEY,
        category_id="6028",
        max_candidates=20,
        transport=RecordingTransport(response(payload)),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["status"] == "PARTIAL_SUCCESS"
    assert outcome["candidates"] == []
    assert any(item["code"] == "LISTING_SKIPPED" for item in outcome["diagnostics"])
