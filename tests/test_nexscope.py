from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

import jsonschema
import pytest

from proteus.providers import nexscope as nexscope_module
from proteus.evaluation import (
    evaluate_amazon_competition_gate,
    evaluate_ebay_demand_gate,
    evaluate_supply_gate,
)
from proteus.normalization import normalize_part_number
from proteus.providers.nexscope import (
    AMAZON_SEARCH_ENDPOINT,
    EBAY_SEARCH_ENDPOINT,
    NEXSCOPE_PROVIDER,
    SOURCE_METHOD,
    SUPPLY_1688_SEARCH_ENDPOINT,
    RestRequest,
    RestResponse,
    collect_1688_search,
    collect_amazon_search,
    collect_ebay_search,
)


ROOT = Path(__file__).resolve().parents[1]
ACQUISITION_SCHEMA = json.loads(
    (ROOT / "contracts" / "v0_2_acquisition.schema.json").read_text(encoding="utf-8")
)
RETRIEVED_AT = "2026-08-25T08:00:00Z"
API_KEY = "nk_test_only_not_a_real_key"


class RecordingTransport:
    def __init__(
        self,
        response: RestResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response or json_response({"total": 0, "products": []})
        self.error = error
        self.requests: list[RestRequest] = []

    def __call__(self, request: RestRequest) -> RestResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def json_response(payload: Any, status_code: int = 200) -> RestResponse:
    return RestResponse(
        status_code=status_code,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def _status(outcome: dict[str, Any]) -> str:
    return str(outcome.get("status", outcome.get("acquisition_status")))


def _collectors() -> tuple[Any, ...]:
    return (collect_amazon_search, collect_ebay_search, collect_1688_search)


def test_amazon_collector_fixes_us_request_and_passes_existing_evaluator() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "total": 2,
                "keyword": "53630-53010",
                "sourceType": "amazon",
                "products": [
                    {
                        "asin": "B012345678",
                        "asinUrl": "B012345678",
                        "title": "New OEM 53630-53010 Automotive Part",
                        "currency": "USD",
                    },
                    {
                        "asin": "B087654321",
                        "title": "Universal Vehicle Cup Holder",
                        "currency": "USD",
                    },
                ],
            }
        )
    )

    outcome = collect_amazon_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["provider"] == NEXSCOPE_PROVIDER
    assert outcome["endpoint_url"] == AMAZON_SEARCH_ENDPOINT
    assert outcome["source_method"] == SOURCE_METHOD == "MANAGED_API"
    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["market_context"] == {
        "marketplace_id": "AMAZON_US",
        "site": "www.amazon.com",
        "locale": "en-US",
        "ship_to_country": "US",
        "currency": "USD",
        "ship_to_postal_code": "10001",
    }
    assert outcome["relevance_method"] == "DETERMINISTIC_EXACT"
    assert outcome["relevant_result_count"] == 1
    assert any(record["url"] == AMAZON_SEARCH_ENDPOINT for record in outcome["evidence"])

    request = transport.requests[0]
    assert request.url == AMAZON_SEARCH_ENDPOINT
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert json.loads(request.body) == {
        "amazonDomain": "amazon.com",
        "deliveryZip": "10001",
        "device": "desktop",
        "keyword": "53630-53010",
        "language": "en_US",
        "page": 1,
    }
    assert API_KEY not in json.dumps(outcome)

    stage = evaluate_amazon_competition_gate(
        outcome,
        expected_canonical_part_number=normalize_part_number("53630-53010"),
    )
    assert stage["status"] == "PASSED"


def test_amazon_incomplete_product_is_partial_and_not_claimed_reviewed() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "total": 2,
                "keyword": "53630-53010",
                "products": [
                    {
                        "asin": "B012345678",
                        "title": "53630-53010 New OEM Part",
                        "currency": "USD",
                    },
                    {"asin": "B087654321", "currency": "USD"},
                ],
            }
        )
    )

    outcome = collect_amazon_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "PARTIAL_SUCCESS"
    assert outcome["relevance_method"] is None
    assert outcome["relevant_result_count"] == 1
    stage = evaluate_amazon_competition_gate(outcome)
    assert stage["status"] == "REVIEW_REQUIRED"


def test_amazon_missing_currency_is_partial_and_cannot_claim_exact_review() -> None:
    outcome = collect_amazon_search(
        "53630-53010",
        api_key=API_KEY,
        transport=RecordingTransport(
            json_response(
                {
                    "total": 1,
                    "products": [
                        {
                            "asin": "B012345678",
                            "title": "53630-53010 New OEM Part",
                        }
                    ],
                }
            )
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "PARTIAL_SUCCESS"
    assert outcome["relevance_method"] is None
    assert evaluate_amazon_competition_gate(outcome)["status"] == "REVIEW_REQUIRED"


def test_amazon_explicit_zero_is_deterministic_low_competition_evidence() -> None:
    outcome = collect_amazon_search(
        "53630-53010",
        api_key=API_KEY,
        transport=RecordingTransport(
            json_response({"total": 0, "keyword": "53630-53010", "products": []})
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "ZERO_RESULTS"
    assert outcome["relevance_method"] == "DETERMINISTIC_EXACT"
    assert outcome["relevant_result_count"] == 0
    count_records = [
        record
        for record in outcome["evidence"]
        if record["metric"] == "relevant_result_count"
    ]
    assert len(count_records) == 1
    assert count_records[0]["value"] == 0
    assert count_records[0]["url"] == (
        "https://www.amazon.com/s?k=53630-53010"
    )
    assert count_records[0]["extraction_method"] == "MANAGED_API"

    stage = evaluate_amazon_competition_gate(
        outcome,
        expected_canonical_part_number=normalize_part_number("53630-53010"),
    )
    assert stage["status"] == "PASSED"


def test_amazon_incomplete_page_cannot_pass_as_low_competition() -> None:
    outcome = collect_amazon_search(
        "53630-53010",
        api_key=API_KEY,
        transport=RecordingTransport(
            json_response(
                {
                    "total": 2,
                    "products": [
                        {
                            "asin": "B012345678",
                            "title": "53630-53010 New OEM Part",
                            "currency": "USD",
                        }
                    ],
                }
            )
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "PARTIAL_SUCCESS"
    assert outcome["relevance_method"] is None
    assert outcome["relevant_result_count"] is None
    assert evaluate_amazon_competition_gate(outcome)["status"] == "REVIEW_REQUIRED"


def test_ebay_collector_normalizes_sales_quantity_and_passes_schema_and_gate() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "total": 2,
                "sourceType": "ebay",
                "products": [
                    {
                        "productId": "123456789012",
                        "title": "New OEM 53630-53010 Automotive Part",
                        "price": 88.5,
                        "currency": "USD",
                        "condition": "New",
                        "link": "https://www.ebay.com/itm/123456789012",
                        "sellerName": "parts-seller",
                        "location": "United States",
                        "salesQuantity": 32,
                    },
                    {
                        "productId": "210987654321",
                        "title": "Used OEM 53630-53010 Automotive Part",
                        "price": 20,
                        "currency": "USD",
                        "condition": "Used",
                        "link": "https://www.ebay.com/itm/210987654321",
                        "salesQuantity": 10,
                    },
                ],
            }
        )
    )

    outcome = collect_ebay_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    jsonschema.validate(outcome, ACQUISITION_SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["provider"] == NEXSCOPE_PROVIDER
    assert outcome["source_method"] == "MANAGED_API"
    assert outcome["status"] == "SUCCESS"
    assert outcome["listings"][0]["match_type"] == "EXACT"
    assert outcome["listings"][0]["condition"] == "NEW"
    assert outcome["listings"][0]["sold_count"] == 32
    assert outcome["listings"][0]["evidence"][0]["metric"] == "sold_count"
    assert outcome["listings"][0]["evidence"][0]["url"] == EBAY_SEARCH_ENDPOINT
    assert outcome["observed_demand"] == {
        "eligible_listing_count": 1,
        "max_single_listing_sold": 32,
        "aggregate_observed_sold": 32,
    }
    request_payload = json.loads(transport.requests[0].body)
    assert request_payload["ebayDomain"] == "ebay.com"
    assert request_payload["location"] == 1
    assert request_payload["zipCode"] == "10001"
    assert request_payload["page"] == 1

    stage = evaluate_ebay_demand_gate(
        outcome,
        expected_canonical_part_number=normalize_part_number("53630-53010"),
    )
    assert stage["status"] == "PASSED"


def test_ebay_missing_sales_quantity_is_explicit_partial_success() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "total": 1,
                "products": [
                    {
                        "productId": "123456789012",
                        "title": "New OEM 53630-53010 Automotive Part",
                        "currency": "USD",
                        "condition": "New",
                        "link": "https://www.ebay.com/itm/123456789012",
                    }
                ],
            }
        )
    )

    outcome = collect_ebay_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    jsonschema.validate(outcome, ACQUISITION_SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == "PARTIAL_SUCCESS"
    assert outcome["listings"][0]["sold_count"] is None
    assert outcome["diagnostics"][0]["code"] == "CARD_SKIPPED"


def test_ebay_incomplete_page_is_explicit_partial_success() -> None:
    outcome = collect_ebay_search(
        "53630-53010",
        api_key=API_KEY,
        transport=RecordingTransport(
            json_response(
                {
                    "total": 2,
                    "products": [
                        {
                            "productId": "123456789012",
                            "title": "New OEM 53630-53010 Automotive Part",
                            "currency": "USD",
                            "condition": "New",
                            "link": "https://www.ebay.com/itm/123456789012",
                            "salesQuantity": 32,
                        }
                    ],
                }
            )
        ),
        retrieved_at=RETRIEVED_AT,
    )

    jsonschema.validate(outcome, ACQUISITION_SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == "PARTIAL_SUCCESS"
    assert any("incomplete" in diagnostic["message"] for diagnostic in outcome["diagnostics"])


def test_ebay_non_usd_response_is_market_context_mismatch() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "total": 1,
                "products": [
                    {
                        "productId": "123456789012",
                        "title": "New OEM 53630-53010 Automotive Part",
                        "currency": "JPY",
                        "condition": "New",
                        "link": "https://www.ebay.com/itm/123456789012",
                        "salesQuantity": 32,
                    }
                ],
            }
        )
    )

    outcome = collect_ebay_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    jsonschema.validate(outcome, ACQUISITION_SCHEMA, format_checker=jsonschema.FormatChecker())
    assert outcome["status"] == "MARKET_CONTEXT_MISMATCH"
    assert outcome["listings"] == []


def test_1688_collector_maps_listing_fields_but_never_claims_order_preview() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "total": 1,
                "sourceType": "1688",
                "products": [
                    {
                        "offerId": "9876543210",
                        "asin": "53630-53010",
                        "title": "53630-53010 汽车配件",
                        "asinUrl": "https://detail.1688.com/offer/9876543210.html",
                        "company": "测试汽配有限公司",
                        "price": 12.5,
                        "currency": "CNY",
                        "quantityBegin": 5,
                        "purchasable": True,
                    }
                ],
            }
        )
    )

    outcome = collect_1688_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["provider"] == NEXSCOPE_PROVIDER
    assert outcome["endpoint_url"] == SUPPLY_1688_SEARCH_ENDPOINT
    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["match_type"] == "EXACT"
    assert outcome["matched_part_numbers"] == ["53630-53010"]
    assert outcome["supplier"] == "测试汽配有限公司"
    assert outcome["offer_url"] == "https://detail.1688.com/offer/9876543210.html"
    assert outcome["price_cny"] == 12.5
    assert outcome["moq"] == 5
    assert outcome["purchasable"] is None
    assert "order preview" in outcome["purchasability_reason"]
    assert not any(record["metric"] == "purchasable" for record in outcome["evidence"])
    assert {
        "matched_part_number",
        "supplier",
        "offer_url",
        "price_cny",
        "moq",
        "listing_signal_only",
    }.issubset({record["metric"] for record in outcome["evidence"]})
    assert any(record["url"] == SUPPLY_1688_SEARCH_ENDPOINT for record in outcome["evidence"])
    request_payload = json.loads(transport.requests[0].body)
    assert request_payload == {
        "keyWord": "53630-53010",
        "pageIndex": 1,
        "pageSize": 10,
        "searchType": 3,
    }

    stage = evaluate_supply_gate(
        outcome,
        max_acceptable_moq=10,
        expected_canonical_part_number=normalize_part_number("53630-53010"),
    )
    assert stage["status"] == "REVIEW_REQUIRED"
    assert "purchasability" in stage["reason"]


def test_1688_missing_company_is_partial_and_remains_review() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "total": 1,
                "products": [
                    {
                        "offerId": "9876543210",
                        "asin": "5363053010",
                        "title": "5363053010 汽车配件",
                        "price": 10,
                        "currency": "¥",
                        "quantityBegin": 2,
                    }
                ],
            }
        )
    )

    outcome = collect_1688_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "PARTIAL_SUCCESS"
    assert outcome["match_type"] == "NORMALIZED_EXACT"
    assert outcome["matched_part_numbers"] == ["5363053010"]
    assert outcome["supplier"] is None
    assert outcome["purchasable"] is None


def test_1688_incomplete_page_is_explicit_partial_success() -> None:
    outcome = collect_1688_search(
        "53630-53010",
        api_key=API_KEY,
        transport=RecordingTransport(
            json_response(
                {
                    "total": 2,
                    "products": [
                        {
                            "offerId": "9876543210",
                            "asin": "53630-53010",
                            "title": "53630-53010 汽车配件",
                            "asinUrl": "https://detail.1688.com/offer/9876543210.html",
                            "company": "测试汽配有限公司",
                            "price": 12.5,
                            "currency": "CNY",
                            "quantityBegin": 5,
                        }
                    ],
                }
            )
        ),
        retrieved_at=RETRIEVED_AT,
    )

    assert outcome["acquisition_status"] == "PARTIAL_SUCCESS"
    assert outcome["purchasable"] is None
    assert any(
        record["metric"] == "provider_page_complete" and record["value"] is False
        for record in outcome["evidence"]
    )


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, "HTTP_ERROR"),
        (401, "AUTH_REQUIRED"),
        (403, "BLOCKED_BY_CREDENTIALS"),
        (429, "HTTP_ERROR"),
        (503, "HTTP_ERROR"),
    ],
)
def test_http_failures_are_explicit_for_all_collectors(
    status_code: int,
    expected: str,
) -> None:
    for collector in _collectors():
        transport = RecordingTransport(RestResponse(status_code=status_code, body=b"error"))
        outcome = collector(
            "53630-53010",
            api_key=API_KEY,
            transport=transport,
            retrieved_at=RETRIEVED_AT,
        )
        assert _status(outcome) == expected
        assert _status(outcome) != "ZERO_RESULTS"
        assert API_KEY not in json.dumps(outcome)
        if collector is collect_ebay_search:
            jsonschema.validate(
                outcome,
                ACQUISITION_SCHEMA,
                format_checker=jsonschema.FormatChecker(),
            )


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (RestResponse(200, b"not-json"), "PARSER_FAILED"),
        (json_response({"total": 1}), "PARSER_FAILED"),
        (json_response({"products": [{"title": "53630-53010"}]}), "PARSER_FAILED"),
        (json_response({"total": 1, "products": []}), "PARSER_FAILED"),
        (json_response({"errcode": 429, "errmsg": "rate limited"}), "HTTP_ERROR"),
    ],
)
def test_bad_payloads_never_become_zero_results(
    response: RestResponse,
    expected: str,
) -> None:
    for collector in _collectors():
        outcome = collector(
            "53630-53010",
            api_key=API_KEY,
            transport=RecordingTransport(response),
            retrieved_at=RETRIEVED_AT,
        )
        assert _status(outcome) == expected
        assert _status(outcome) != "ZERO_RESULTS"


@pytest.mark.parametrize(
    "response",
    [
        RestResponse(status_code="200", body=b"{}"),  # type: ignore[arg-type]
        RestResponse(status_code=200, body="{}"),  # type: ignore[arg-type]
    ],
)
def test_malformed_transport_response_is_parser_failed(response: RestResponse) -> None:
    for collector in _collectors():
        outcome = collector(
            "53630-53010",
            api_key=API_KEY,
            transport=RecordingTransport(response),
            retrieved_at=RETRIEVED_AT,
        )
        assert _status(outcome) == "PARSER_FAILED"
        assert _status(outcome) != "ZERO_RESULTS"


def test_only_explicit_empty_products_and_zero_total_is_zero_results() -> None:
    for collector in _collectors():
        outcome = collector(
            "53630-53010",
            api_key=API_KEY,
            transport=RecordingTransport(json_response({"total": 0, "products": []})),
            retrieved_at=RETRIEVED_AT,
        )
        assert _status(outcome) == "ZERO_RESULTS"


def test_missing_api_key_is_explicit_and_transport_is_not_called() -> None:
    for collector in _collectors():
        transport = RecordingTransport()
        outcome = collector(
            "53630-53010",
            api_key="   ",
            transport=transport,
            retrieved_at=RETRIEVED_AT,
        )
        assert _status(outcome) == "BLOCKED_BY_CREDENTIALS"
    assert transport.requests == []


def test_provider_error_payload_cannot_echo_api_key() -> None:
    transport = RecordingTransport(
        json_response(
            {
                "errcode": API_KEY,
                "errmsg": f"Authorization: Bearer {API_KEY}",
            }
        )
    )

    outcome = collect_amazon_search(
        "53630-53010",
        api_key=API_KEY,
        transport=transport,
        retrieved_at=RETRIEVED_AT,
    )

    serialized = json.dumps(outcome)
    assert outcome["acquisition_status"] == "HTTP_ERROR"
    assert API_KEY not in serialized
    assert "Authorization" not in serialized


def test_transport_timeout_is_explicit_for_all_collectors() -> None:
    for collector in _collectors():
        outcome = collector(
            "53630-53010",
            api_key=API_KEY,
            transport=RecordingTransport(error=TimeoutError("deadline exceeded")),
            retrieved_at=RETRIEVED_AT,
        )
        assert _status(outcome) == "TIMEOUT"
        assert _status(outcome) != "ZERO_RESULTS"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (TimeoutError(f"Authorization: Bearer {API_KEY}"), "TIMEOUT"),
        (URLError(f"request headers included {API_KEY}"), "HTTP_ERROR"),
        (RuntimeError(f"transport failed with {API_KEY}"), "HTTP_ERROR"),
    ],
)
def test_transport_exception_text_cannot_leak_api_key(
    error: Exception,
    expected_status: str,
) -> None:
    for collector in _collectors():
        outcome = collector(
            "53630-53010",
            api_key=API_KEY,
            transport=RecordingTransport(error=error),
            retrieved_at=RETRIEVED_AT,
        )
        serialized = json.dumps(outcome, ensure_ascii=False)
        assert _status(outcome) == expected_status
        assert API_KEY not in serialized
        assert "Authorization" not in serialized


def test_default_transport_refuses_redirects_with_bearer_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedirectingOpener:
        def open(self, request: Request, timeout: float) -> None:
            raise HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "https://attacker.invalid/capture"},
                BytesIO(b"redirect refused"),
            )

    def fake_build_opener(handler: object) -> RedirectingOpener:
        assert isinstance(handler, nexscope_module._NoRedirectHandler)
        assert (
            handler.redirect_request(
                Request(AMAZON_SEARCH_ENDPOINT),
                None,
                302,
                "Found",
                {},
                "https://attacker.invalid/capture",
            )
            is None
        )
        return RedirectingOpener()

    monkeypatch.setattr(nexscope_module, "build_opener", fake_build_opener)
    response = nexscope_module._urllib_transport(
        RestRequest(
            AMAZON_SEARCH_ENDPOINT,
            {"Authorization": f"Bearer {API_KEY}"},
            b"{}",
            1.0,
        )
    )

    assert response.status_code == 302
    assert response.body == b"redirect refused"
