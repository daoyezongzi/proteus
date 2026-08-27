from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from proteus.evaluation import evaluate_amazon_competition_gate
from proteus.normalization import normalize_part_number
from proteus.providers.serpapi_amazon import (
    SERPAPI_AMAZON_PROVIDER,
    SerpApiRequest,
    SerpApiResponse,
    collect_amazon_competition,
    collect_amazon_search,
)


PART_NUMBER = "53630-53010"
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


def success_payload() -> dict[str, Any]:
    return {
        "search_metadata": {"id": "amazon_search_123", "status": "Success"},
        "search_parameters": {
            "engine": "amazon",
            "k": PART_NUMBER,
            "amazon_domain": "amazon.com",
            "language": "en_US",
            "delivery_zip": "10001",
        },
        "search_information": {"total_results": 2},
        "organic_results": [
            {
                "asin": "B000000001",
                "title": "Genuine Toyota Lexus Hood Latch 53630-53010",
                "link": "https://www.amazon.com/dp/B000000001",
                "price": "$31.50",
                "extracted_price": 31.5,
                "more_buying_choices": "$29.99 (4 new offers)",
            },
            {
                "asin": "B000000002",
                "title": "Universal automotive hood latch kit",
                "link": "https://www.amazon.com/dp/B000000002",
                "price": "$12.00",
            },
        ],
    }


def test_amazon_exact_search_maps_to_existing_competition_gate() -> None:
    transport = RecordingTransport(response(success_payload()))

    outcome = collect_amazon_competition(
        PART_NUMBER,
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["provider"] == SERPAPI_AMAZON_PROVIDER
    assert outcome["source_method"] == "MANAGED_API"
    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["relevance_method"] == "DETERMINISTIC_EXACT"
    assert outcome["relevant_result_count"] == 1
    assert outcome["minimum_exact_result_price_usd"] == 31.5
    assert outcome["price_observation_complete"] is True
    assert outcome["active_offer_count_lower_bound"] == 4
    assert outcome["active_offer_count_complete"] is True
    assert API_KEY not in json.dumps(outcome)
    assert evaluate_amazon_competition_gate(
        outcome,
        expected_canonical_part_number=normalize_part_number(PART_NUMBER),
    )["status"] == "PASSED"

    query = parse_qs(urlparse(transport.requests[0].url).query)
    assert query == {
        "amazon_domain": ["amazon.com"],
        "api_key": [API_KEY],
        "delivery_zip": ["10001"],
        "device": ["desktop"],
        "engine": ["amazon"],
        "k": [PART_NUMBER],
        "language": ["en_US"],
        "no_cache": ["true"],
        "output": ["json"],
    }


def test_amazon_pagination_cannot_prove_low_competition() -> None:
    payload = success_payload()
    payload["pagination"] = {"next": "https://www.amazon.com/s?k=53630-53010&page=2"}

    outcome = collect_amazon_competition(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(payload)),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "PARTIAL_SUCCESS"
    assert outcome["relevance_method"] is None
    assert outcome["relevant_result_count"] is None
    assert evaluate_amazon_competition_gate(outcome)["status"] == "REVIEW_REQUIRED"


def test_amazon_plus_offer_count_preserves_a_decisive_lower_bound() -> None:
    payload = success_payload()
    payload["organic_results"][0]["more_buying_choices"] = (
        "$18.75 (343+ used & new offers)"
    )

    outcome = collect_amazon_competition(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(payload)),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["active_offer_count_lower_bound"] == 343
    assert outcome["active_offer_count_complete"] is False


def test_amazon_missing_exact_price_cannot_pass_a_strict_price_gate() -> None:
    payload = success_payload()
    payload["organic_results"][0].pop("extracted_price")

    outcome = collect_amazon_competition(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(payload)),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["minimum_exact_result_price_usd"] is None
    assert outcome["price_observation_complete"] is False


def test_amazon_explicit_zero_and_auth_failure_are_not_confused() -> None:
    empty = success_payload()
    empty["organic_results"] = []
    empty["search_information"]["total_results"] = 0

    zero = collect_amazon_competition(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(empty)),
        retrieved_at=RETRIEVED_AT,
    )
    auth = collect_amazon_competition(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(SerpApiResponse(401, b"rejected")),
        retrieved_at=RETRIEVED_AT,
    )

    assert zero["acquisition_status"] == "ZERO_RESULTS"
    assert zero["relevant_result_count"] == 0
    assert auth["acquisition_status"] == "AUTH_REQUIRED"
    assert auth["relevant_result_count"] is None


def test_amazon_descriptive_search_preserves_products_for_family_classification() -> None:
    query = "fog light bezel Chevrolet Silverado 2007-2013 right"
    payload = success_payload()
    payload["search_parameters"]["k"] = query
    payload["organic_results"][0]["title"] = (
        "Right Fog Light Bezel for 2007-2013 Chevrolet Silverado 25778388"
    )
    payload["organic_results"][1]["title"] = "Universal LED fog lamp assembly"

    outcome = collect_amazon_search(
        query,
        api_key=API_KEY,
        transport=RecordingTransport(response(payload)),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["schema_version"] == "0.2.4"
    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["result_page_complete"] is True
    assert outcome["results_seen"] == 2
    assert [product["asin"] for product in outcome["products"]] == [
        "B000000001",
        "B000000002",
    ]
    assert outcome["products"][0]["title"].startswith("Right Fog Light Bezel")
    assert outcome["products"][0]["active_offer_count_lower_bound"] == 4
    assert API_KEY not in json.dumps(outcome)


def test_amazon_descriptive_search_marks_pagination_incomplete() -> None:
    query = "hood release cable Toyota Yaris"
    payload = success_payload()
    payload["search_parameters"]["k"] = query
    payload["pagination"] = {"next": "https://www.amazon.com/s?page=2"}

    outcome = collect_amazon_search(
        query,
        api_key=API_KEY,
        transport=RecordingTransport(response(payload)),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "PARTIAL_SUCCESS"
    assert outcome["result_page_complete"] is False
    assert outcome["has_next_page"] is True
