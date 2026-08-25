from __future__ import annotations

import json
from io import BytesIO
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

import pytest

from proteus.providers import hiobuy as hiobuy_module
from proteus.evaluation import evaluate_supply_gate
from proteus.normalization import normalize_part_number
from proteus.providers.hiobuy import (
    HIOBUY_PROVIDER,
    ORDER_PREVIEW_ENDPOINT,
    PRODUCT_DETAIL_ENDPOINT,
    PRODUCT_SEARCH_ENDPOINT,
    HioBuyRequest,
    HioBuyResponse,
    collect_1688_supply,
)


API_KEY = "hio_test_secret_not_for_output"
PART_NUMBER = "53630-53010"
RECEIVER = {
    "name": "ReceiverOnly-7d3a",
    "mobile": "13000009991",
    "province": "浙江省-ReceiverOnly",
    "city": "杭州市-ReceiverOnly",
    "district": "萧山区-ReceiverOnly",
    "address": "ReceiverOnly Road 8821",
    "zip": "311200",
    "country": "中国",
}


def json_response(payload: Any, status_code: int = 200) -> HioBuyResponse:
    return HioBuyResponse(
        status_code=status_code,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


class SequenceTransport:
    def __init__(
        self,
        responses: list[HioBuyResponse] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.requests: list[HioBuyRequest] = []

    def __call__(self, request: HioBuyRequest) -> HioBuyResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("unexpected HioBuy request")
        return self.responses.pop(0)


def search_payload(*, exact: bool = True) -> dict[str, Any]:
    title = (
        "New OEM 53630-53010 Steering Part"
        if exact
        else "Compatible Steering Part 53630-53011"
    )
    return {
        "channel": "1688",
        "keyword": PART_NUMBER,
        "page": 1,
        "page_size": 20,
        "total": 1,
        "items": [
            {
                "id": "9876543210",
                "channel": "1688",
                "source_product_id": "9876543210",
                "source_url": "https://detail.1688.com/offer/9876543210.html",
                "title": {
                    "original": title,
                    "translated": None,
                    "language": "en",
                },
            }
        ],
    }


def detail_payload() -> dict[str, Any]:
    return {
        "product": {
            "id": "9876543210",
            "channel": "1688",
            "source_product_id": "9876543210",
            "source_url": "https://detail.1688.com/offer/9876543210.html",
            "title": {
                "original": "5363053010 汽车转向配件",
                "translated": "OEM 5363053010 steering part",
                "language": "en",
            },
            "price": {
                "display_amount": 15.0,
                "display_currency": "CNY",
            },
            "min_order_quantity": 5,
            "seller": {"id": "seller-1", "name": "杭州测试汽配有限公司"},
            "variants": [
                {
                    "sku_id": "sku-expensive",
                    "stock": 100,
                    "min_order_quantity": 5,
                    "price": {
                        "display_amount": 15.0,
                        "display_currency": "CNY",
                    },
                    "attributes": [],
                },
                {
                    "sku_id": "sku-selected",
                    "stock": 50,
                    "min_order_quantity": 5,
                    "price": {
                        "display_amount": 12.5,
                        "display_currency": "CNY",
                    },
                    "attributes": [],
                },
                {
                    "sku_id": "sku-out-of-stock",
                    "stock": 0,
                    "min_order_quantity": 1,
                    "price": {
                        "display_amount": 1.0,
                        "display_currency": "CNY",
                    },
                    "attributes": [],
                },
            ],
        },
        "request_id": "req_detail_test",
    }


def preview_payload(*, success: bool = True) -> dict[str, Any]:
    return {
        "channel": "1688",
        "success": success,
        "monetary_unit": "CNY_minor",
        "total": {
            "payment": {"amount": 6500, "currency": "CNY"},
            "shipping": {"amount": 500, "currency": "CNY"},
        },
        "unavailable_lines": [] if success else [{"line": 0, "reason": "OUT_OF_STOCK"}],
        "sellers": [
            {
                "seller_id": "seller-1",
                "lines": [
                    {
                        "offer_id": "9876543210",
                        "spec_id": "sku-selected",
                        "quantity": 5,
                    }
                ],
            }
        ],
        "request_id": "req_preview_test",
    }


def happy_transport(*, preview_success: bool = True) -> SequenceTransport:
    return SequenceTransport(
        [
            json_response(search_payload()),
            json_response(detail_payload()),
            json_response(preview_payload(success=preview_success)),
        ]
    )


def test_happy_path_uses_only_search_detail_preview_and_passes_supply_gate() -> None:
    transport = happy_transport()

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )

    assert [request.url for request in transport.requests] == [
        PRODUCT_SEARCH_ENDPOINT,
        PRODUCT_DETAIL_ENDPOINT,
        ORDER_PREVIEW_ENDPOINT,
    ]
    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["source_method"] == "MANAGED_API"
    assert outcome["match_type"] == "NORMALIZED_EXACT"
    assert outcome["matched_part_numbers"] == [PART_NUMBER]
    assert outcome["offer_url"] == "https://detail.1688.com/offer/9876543210.html"
    assert outcome["supplier"] == "杭州测试汽配有限公司"
    assert outcome["price_cny"] == 12.5
    assert outcome["moq"] == 5
    assert outcome["purchasable"] is True
    assert outcome["order_preview"] == {
        "provider": HIOBUY_PROVIDER,
        "request_id": "req_preview_test",
        "offer_id": "9876543210",
        "sku_id": "sku-selected",
        "quantity": 5,
        "currency": "CNY",
        "payment_cny": 65,
        "shipping_cny": 5,
        "retrieved_at": outcome["order_preview"]["retrieved_at"],
    }
    assert {
        evidence["metric"]: evidence["value"] for evidence in outcome["evidence"]
    }["preview_payment_cny"] == 65
    assert {
        evidence["metric"]: evidence["value"] for evidence in outcome["evidence"]
    }["preview_shipping_cny"] == 5
    assert {
        record["metric"]: record["extraction_method"]
        for record in outcome["evidence"]
    } == {
        "price_cny": "MANAGED_API",
        "moq": "MANAGED_API",
        "purchasable": "ORDER_PREVIEW",
        "preview_payment_cny": "ORDER_PREVIEW",
        "preview_shipping_cny": "ORDER_PREVIEW",
    }
    purchasable_evidence = next(
        record for record in outcome["evidence"] if record["metric"] == "purchasable"
    )
    assert "request_id=req_preview_test" in purchasable_evidence["raw_evidence"]
    assert "id=9876543210" in purchasable_evidence["raw_evidence"]
    assert "spec_id=sku-selected" in purchasable_evidence["raw_evidence"]
    assert "quantity=5" in purchasable_evidence["raw_evidence"]

    search_request, detail_request, preview_request = transport.requests
    assert all(request.headers["Authorization"] == f"Bearer {API_KEY}" for request in transport.requests)
    assert all(API_KEY.encode() not in request.body for request in transport.requests)
    assert json.loads(search_request.body) == {
        "channel": "1688",
        "keyword": PART_NUMBER,
        "language": "en",
        "page": 1,
        "page_size": 20,
        "response_format": "standard",
    }
    assert json.loads(detail_request.body) == {
        "channel": "1688",
        "id": "9876543210",
        "language": "en",
        "response_format": "standard",
    }
    assert json.loads(preview_request.body) == {
        "channel": "1688",
        "lines": [
            {"id": "9876543210", "quantity": 5, "spec_id": "sku-selected"}
        ],
        "receiver": RECEIVER,
        "response_format": "standard",
    }

    stage = evaluate_supply_gate(
        outcome,
        max_acceptable_moq=5,
        expected_canonical_part_number=normalize_part_number(PART_NUMBER),
    )
    assert stage["status"] == "PASSED"


def test_non_exact_results_stop_before_detail_and_require_review() -> None:
    transport = SequenceTransport([json_response(search_payload(exact=False))])

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )

    assert [request.url for request in transport.requests] == [PRODUCT_SEARCH_ENDPOINT]
    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["match_type"] == "AMBIGUOUS"
    assert outcome["purchasable"] is None
    assert outcome["diagnostics"][0]["code"] == "HIOBUY_EXACT_MATCH_NOT_FOUND"
    stage = evaluate_supply_gate(outcome, max_acceptable_moq=10)
    assert stage["status"] == "REVIEW_REQUIRED"
    assert "not exact" in stage["reason"]


def test_variant_identifier_conflict_stops_before_preview() -> None:
    detail = detail_payload()
    detail["product"]["variants"][0]["attributes"] = [
        {"name": "Model", "value": "WRONG-999"}
    ]
    transport = SequenceTransport(
        [json_response(search_payload()), json_response(detail)]
    )

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
        max_acceptable_moq=10,
    )
    stage = evaluate_supply_gate(outcome, max_acceptable_moq=10)

    assert len(transport.requests) == 2
    assert outcome["purchasable"] is None
    assert stage["status"] == "REVIEW_REQUIRED"


def test_selector_prefers_acceptable_moq_over_cheaper_high_moq() -> None:
    detail = detail_payload()
    detail["product"]["variants"].insert(
        0,
        {
            "sku_id": "sku-too-high",
            "stock": 1000,
            "min_order_quantity": 100,
            "price": {"display_amount": 1, "display_currency": "CNY"},
            "attributes": [],
        },
    )
    transport = SequenceTransport(
        [
            json_response(search_payload()),
            json_response(detail),
            json_response(preview_payload()),
        ]
    )

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
        max_acceptable_moq=10,
    )

    preview_request = json.loads(transport.requests[2].body)
    assert preview_request["lines"] == [
        {"id": "9876543210", "spec_id": "sku-selected", "quantity": 5}
    ]
    assert outcome["moq"] == 5
    assert outcome["purchasable"] is True


def test_failed_preview_records_false_and_rejects_supply() -> None:
    transport = happy_transport(preview_success=False)

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )

    assert outcome["acquisition_status"] == "SUCCESS"
    assert outcome["purchasable"] is False
    assert outcome["order_preview"]["offer_id"] == "9876543210"
    assert outcome["order_preview"]["sku_id"] == "sku-selected"
    assert outcome["order_preview"]["quantity"] == 5
    purchasable = next(
        record for record in outcome["evidence"] if record["metric"] == "purchasable"
    )
    assert purchasable["value"] is False
    assert purchasable["extraction_method"] == "ORDER_PREVIEW"
    stage = evaluate_supply_gate(outcome, max_acceptable_moq=10)
    assert stage["status"] == "REJECTED"


def test_unavailable_preview_without_exact_line_binding_requires_review() -> None:
    payload = preview_payload(success=False)
    payload["sellers"][0]["lines"][0]["spec_id"] = "different-sku"
    transport = SequenceTransport(
        [
            json_response(search_payload()),
            json_response(detail_payload()),
            json_response(payload),
        ]
    )

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )
    stage = evaluate_supply_gate(outcome, max_acceptable_moq=10)

    assert outcome["acquisition_status"] == "PARSER_FAILED"
    assert outcome["purchasable"] is None
    assert outcome["diagnostics"][0]["code"] == "HIOBUY_PREVIEW_LINE_MISMATCH"
    assert stage["status"] == "REVIEW_REQUIRED"


def test_purchasable_preview_requires_valid_cny_minor_totals() -> None:
    invalid_preview = preview_payload()
    invalid_preview["total"]["payment"]["currency"] = "USD"
    transport = SequenceTransport(
        [
            json_response(search_payload()),
            json_response(detail_payload()),
            json_response(invalid_preview),
        ]
    )

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )
    stage = evaluate_supply_gate(outcome, max_acceptable_moq=10)

    assert outcome["acquisition_status"] == "PARSER_FAILED"
    assert outcome["purchasable"] is None
    assert stage["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda payload: payload["sellers"][0]["lines"][0].update(
                offer_id="wrong"
            ),
            "HIOBUY_PREVIEW_LINE_MISMATCH",
        ),
        (
            lambda payload: payload["sellers"][0]["lines"][0].update(
                spec_id="wrong"
            ),
            "HIOBUY_PREVIEW_LINE_MISMATCH",
        ),
        (
            lambda payload: payload["sellers"][0]["lines"][0].update(quantity=6),
            "HIOBUY_PREVIEW_LINE_MISMATCH",
        ),
        (
            lambda payload: payload.update(request_id=""),
            "HIOBUY_PREVIEW_RESPONSE_INVALID",
        ),
        (
            lambda payload: payload.update(request_id=API_KEY),
            "HIOBUY_PREVIEW_RESPONSE_INVALID",
        ),
    ],
)
def test_successful_preview_requires_exact_line_binding_and_request_id(
    mutation: Any,
    expected_code: str,
) -> None:
    payload = preview_payload()
    mutation(payload)
    transport = SequenceTransport(
        [
            json_response(search_payload()),
            json_response(detail_payload()),
            json_response(payload),
        ]
    )

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )

    assert outcome["acquisition_status"] == "PARSER_FAILED"
    assert outcome["purchasable"] is None
    assert outcome["diagnostics"][0]["code"] == expected_code
    stage = evaluate_supply_gate(outcome, max_acceptable_moq=10)
    assert stage["status"] == "REVIEW_REQUIRED"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, "AUTH_REQUIRED"),
        (403, "BLOCKED_BY_CREDENTIALS"),
        (429, "HTTP_ERROR"),
        (503, "HTTP_ERROR"),
        (504, "TIMEOUT"),
    ],
)
def test_http_and_auth_failures_are_explicit(status_code: int, expected: str) -> None:
    transport = SequenceTransport([HioBuyResponse(status_code, b"sensitive body")])

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )

    assert outcome["acquisition_status"] == expected
    assert outcome["acquisition_status"] != "ZERO_RESULTS"
    assert "sensitive body" not in json.dumps(outcome)
    assert len(transport.requests) == 1


def test_missing_key_is_explicit_and_transport_is_not_called() -> None:
    transport = SequenceTransport([])

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key="   ",
        receiver=RECEIVER,
        transport=transport,
    )

    assert outcome["acquisition_status"] == "BLOCKED_BY_CREDENTIALS"
    assert transport.requests == []


def test_transport_exception_cannot_leak_key_or_receiver() -> None:
    receiver_blob = json.dumps(RECEIVER, ensure_ascii=False)
    transport = SequenceTransport(
        error=RuntimeError(f"request leaked {API_KEY} receiver={receiver_blob}")
    )

    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )

    serialized = json.dumps(outcome, ensure_ascii=False)
    assert outcome["acquisition_status"] == "HTTP_ERROR"
    assert API_KEY not in serialized
    assert receiver_blob not in serialized
    assert all(value not in serialized for value in RECEIVER.values())


def test_default_transport_refuses_redirects_with_key_and_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedirectingOpener:
        def open(self, request: Request, timeout: float) -> None:
            raise HTTPError(
                request.full_url,
                303,
                "See Other",
                {"Location": "https://attacker.invalid/capture"},
                BytesIO(b"redirect refused"),
            )

    def fake_build_opener(handler: object) -> RedirectingOpener:
        assert isinstance(handler, hiobuy_module._NoRedirectHandler)
        assert (
            handler.redirect_request(
                Request(ORDER_PREVIEW_ENDPOINT),
                None,
                303,
                "See Other",
                {},
                "https://attacker.invalid/capture",
            )
            is None
        )
        return RedirectingOpener()

    monkeypatch.setattr(hiobuy_module, "build_opener", fake_build_opener)
    response = hiobuy_module._urllib_transport(
        HioBuyRequest(
            ORDER_PREVIEW_ENDPOINT,
            {"Authorization": f"Bearer {API_KEY}"},
            json.dumps({"receiver": RECEIVER}).encode("utf-8"),
            1.0,
        )
    )

    assert response.status_code == 303
    assert response.body == b"redirect refused"


def test_receiver_is_runtime_only_and_not_returned() -> None:
    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=happy_transport(),
    )

    serialized = json.dumps(outcome, ensure_ascii=False)
    assert API_KEY not in serialized
    assert "receiver" not in outcome
    assert all(value not in serialized for value in RECEIVER.values())


def test_only_explicit_empty_search_is_zero_and_malformed_is_parser_failure() -> None:
    explicit_zero = SequenceTransport(
        [
            json_response(
                {
                    "channel": "1688",
                    "keyword": PART_NUMBER,
                    "total": 0,
                    "items": [],
                }
            )
        ]
    )
    malformed = SequenceTransport(
        [
            json_response(
                {
                    "channel": "1688",
                    "keyword": PART_NUMBER,
                    "total": 1,
                    "items": [],
                }
            )
        ]
    )

    zero_outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=explicit_zero,
    )
    malformed_outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=malformed,
    )

    assert zero_outcome["acquisition_status"] == "ZERO_RESULTS"
    assert malformed_outcome["acquisition_status"] == "PARSER_FAILED"


def test_timeout_is_explicit_and_never_becomes_zero() -> None:
    outcome = collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=SequenceTransport(error=TimeoutError("deadline")),
    )

    assert outcome["acquisition_status"] == "TIMEOUT"
    assert outcome["acquisition_status"] != "ZERO_RESULTS"


def test_adapter_never_calls_create_or_pay() -> None:
    transport = happy_transport()

    collect_1688_supply(
        PART_NUMBER,
        api_key=API_KEY,
        receiver=RECEIVER,
        transport=transport,
    )

    allowed = {
        PRODUCT_SEARCH_ENDPOINT,
        PRODUCT_DETAIL_ENDPOINT,
        ORDER_PREVIEW_ENDPOINT,
    }
    assert {request.url for request in transport.requests} <= allowed
    assert all("/create" not in request.url for request in transport.requests)
    assert all("/pay" not in request.url for request in transport.requests)
