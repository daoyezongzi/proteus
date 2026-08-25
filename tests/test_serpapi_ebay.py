from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from proteus.evaluation import evaluate_ebay_demand_gate
from proteus.io import validate_acquisition
from proteus.normalization import normalize_part_number
from proteus.providers import serpapi_ebay as serpapi_module
from proteus.providers.serpapi_ebay import (
    SERPAPI_EBAY_PROVIDER,
    SerpApiRequest,
    SerpApiResponse,
    collect_ebay_sold,
)


PART_NUMBER = "53630-53010"
API_KEY = "serp-secret-never-output"
RETRIEVED_AT = "2026-08-25T10:00:00Z"


@dataclass
class RecordingTransport:
    response: SerpApiResponse | None = None
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.requests: list[SerpApiRequest] = []

    def __call__(self, request: SerpApiRequest) -> SerpApiResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def response(payload: Any, status_code: int = 200) -> SerpApiResponse:
    return SerpApiResponse(status_code, json.dumps(payload).encode("utf-8"))


def success_payload() -> dict[str, Any]:
    return {
        "search_metadata": {
            "id": "search_123",
            "status": "Success",
            "ebay_url": (
                "https://www.ebay.com/sch/i.html?_nkw=53630-53010"
                "&show_only=Sold&LH_ItemCondition=1000&_salic=1&_stpos=10001"
            ),
        },
        "search_parameters": {
            "engine": "ebay",
            "_nkw": PART_NUMBER,
            "ebay_domain": "ebay.com",
            "show_only": "Sold",
            "LH_ItemCondition": "1000",
            "_salic": "1",
            "_stpos": "10001",
        },
        "search_information": {"total_results": 1},
        "organic_results": [
            {
                "title": "New OEM Lexus Toyota Hood Latch 53630-53010",
                "link": "https://www.ebay.com/itm/123456789012?hash=fixture",
                "product_id": "123456789012",
                "condition": "Brand New",
                "price": {"raw": "$31.50", "extracted": 31.5},
                "quantity_sold": "32 sold",
                "extracted_quantity_sold": 32,
                "seller": {"username": "fixture-seller"},
            }
        ],
    }


def test_exact_sold_result_maps_to_provider_neutral_acquisition() -> None:
    transport = RecordingTransport(response(success_payload()))

    outcome = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    validate_acquisition(outcome, label="SerpApi fixture")
    assert outcome["provider"] == SERPAPI_EBAY_PROVIDER
    assert outcome["source_method"] == "MANAGED_API"
    assert outcome["status"] == "SUCCESS"
    assert outcome["observed_demand"] == {
        "eligible_listing_count": 1,
        "max_single_listing_sold": 32,
        "aggregate_observed_sold": 32,
    }
    listing = outcome["listings"][0]
    assert listing["listing_id"] == "123456789012"
    assert listing["url"] == "https://www.ebay.com/itm/123456789012"
    assert listing["condition"] == "NEW"
    assert listing["sold_count"] == 32
    assert listing["decision"] == "ACCEPT_DEMAND_EVIDENCE"
    assert API_KEY not in json.dumps(outcome)

    query = parse_qs(urlparse(transport.requests[0].url).query)
    assert query == {
        "LH_ItemCondition": ["1000"],
        "_ipg": ["50"],
        "_nkw": [PART_NUMBER],
        "_salic": ["1"],
        "_stpos": ["10001"],
        "api_key": [API_KEY],
        "ebay_domain": ["ebay.com"],
        "engine": ["ebay"],
        "no_cache": ["true"],
        "output": ["json"],
        "show_only": ["Sold"],
    }
    stage = evaluate_ebay_demand_gate(
        outcome,
        expected_canonical_part_number=normalize_part_number(PART_NUMBER),
    )
    assert stage["status"] == "PASSED"


def test_market_or_filter_mismatch_fails_closed() -> None:
    payload = success_payload()
    payload["search_parameters"]["ebay_domain"] = "ebay.co.jp"

    outcome = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(payload)),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["status"] == "MARKET_CONTEXT_MISMATCH"
    assert outcome["listings"] == []
    assert evaluate_ebay_demand_gate(outcome)["status"] == "REVIEW_REQUIRED"


def test_explicit_empty_results_is_zero_but_nonzero_empty_is_parser_failure() -> None:
    explicit_zero = success_payload()
    explicit_zero["organic_results"] = []
    explicit_zero["search_information"]["total_results"] = 0
    malformed = success_payload()
    malformed["organic_results"] = []

    zero = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(explicit_zero)),
        retrieved_at=RETRIEVED_AT,
    )
    failed = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(malformed)),
        retrieved_at=RETRIEVED_AT,
    )

    assert zero["status"] == "ZERO_RESULTS"
    assert failed["status"] == "PARSER_FAILED"


def test_unknown_condition_or_nonpositive_sold_count_cannot_prove_absence() -> None:
    unknown_condition = success_payload()
    unknown_condition["organic_results"][0]["condition"] = "Unspecified"
    zero_sold = success_payload()
    zero_sold["organic_results"][0]["quantity_sold"] = "0 sold"
    zero_sold["organic_results"][0]["extracted_quantity_sold"] = 0

    unknown = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(unknown_condition)),
        retrieved_at=RETRIEVED_AT,
    )
    zero = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response(zero_sold)),
        retrieved_at=RETRIEVED_AT,
    )

    assert unknown["status"] == "PARTIAL_SUCCESS"
    assert zero["status"] == "PARTIAL_SUCCESS"
    assert evaluate_ebay_demand_gate(unknown)["status"] == "REVIEW_REQUIRED"
    assert evaluate_ebay_demand_gate(zero)["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [(401, "AUTH_REQUIRED"), (403, "BLOCKED_BY_CREDENTIALS"), (429, "HTTP_ERROR"), (503, "HTTP_ERROR")],
)
def test_http_failures_are_explicit(status_code: int, expected: str) -> None:
    outcome = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(response=SerpApiResponse(status_code, b"secret body")),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["status"] == expected
    assert "secret body" not in json.dumps(outcome)


def test_missing_key_and_timeout_do_not_become_zero_results() -> None:
    missing_transport = RecordingTransport(response(success_payload()))
    missing = collect_ebay_sold(
        PART_NUMBER,
        api_key=" ",
        transport=missing_transport,
        retrieved_at=RETRIEVED_AT,
    )
    timed_out = collect_ebay_sold(
        PART_NUMBER,
        api_key=API_KEY,
        transport=RecordingTransport(error=TimeoutError("deadline")),
        retrieved_at=RETRIEVED_AT,
    )

    assert missing["status"] == "BLOCKED_BY_CREDENTIALS"
    assert missing_transport.requests == []
    assert timed_out["status"] == "TIMEOUT"


def test_default_transport_refuses_redirect_with_query_key(monkeypatch: pytest.MonkeyPatch) -> None:
    class RedirectingOpener:
        def open(self, request: Any, timeout: float) -> None:
            raise HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "https://attacker.invalid/capture"},
                None,
            )

    monkeypatch.setattr(serpapi_module, "build_opener", lambda handler: RedirectingOpener())
    result = serpapi_module._urllib_transport(
        SerpApiRequest("https://serpapi.com/search?api_key=secret", 1.0)
    )

    assert result.status_code == 302
