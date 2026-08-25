"""Read-only HioBuy 1688 supply verification for Proteus V0.2.

This module intentionally exposes only the search -> detail -> order-preview
path.  It never creates or pays an order.  The caller supplies both the API
key and a domestic receiver at runtime; neither is copied into the returned
evidence or diagnostics.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from proteus.normalization import normalize_part_number


HIOBUY_PROVIDER = "HIOBUY_PUBLIC_REST"
SOURCE_METHOD = "MANAGED_API"

API_BASE_URL = "https://api.hiobuy.com/v1"
PRODUCT_SEARCH_ENDPOINT = f"{API_BASE_URL}/products/search"
PRODUCT_DETAIL_ENDPOINT = f"{API_BASE_URL}/products/detail"
ORDER_PREVIEW_ENDPOINT = f"{API_BASE_URL}/orders/preview"

_ALLOWED_ENDPOINTS = frozenset(
    {PRODUCT_SEARCH_ENDPOINT, PRODUCT_DETAIL_ENDPOINT, ORDER_PREVIEW_ENDPOINT}
)
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_RECEIVER_REQUIRED_FIELDS = ("name", "mobile", "province", "city", "address")
_RECEIVER_OPTIONAL_FIELDS = (
    "district",
    "town",
    "zip",
    "country",
    "address_id",
    "district_code",
)


@dataclass(frozen=True, slots=True)
class HioBuyRequest:
    """A materialized HioBuy request passed to an injected transport."""

    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class HioBuyResponse:
    """The small transport response surface consumed by this adapter."""

    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[HioBuyRequest], HioBuyResponse]


@dataclass(frozen=True, slots=True)
class _ApiResult:
    status: str
    payload: Mapping[str, Any] | None
    diagnostic_code: str
    diagnostic_message: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _nonempty_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nonnegative_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or not math.isfinite(float(value)):
        return None
    return value


def _nonnegative_integer(value: Any) -> int | None:
    number = _nonnegative_number(value)
    if number is None or int(number) != number:
        return None
    return int(number)


def _positive_integer(value: Any) -> int | None:
    number = _nonnegative_integer(value)
    return number if number is not None and number >= 1 else None


def _is_real_1688_url(value: Any) -> bool:
    raw_url = _nonempty_string(value)
    if raw_url is None:
        return False
    parsed = urlparse(raw_url)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (hostname == "1688.com" or hostname.endswith(".1688.com"))
    )


def _read_limited(stream: Any) -> bytes:
    body = stream.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("HioBuy response exceeds the configured size limit")
    return body


class _NoRedirectHandler(HTTPRedirectHandler):
    """Do not forward bearer credentials or receiver requests through redirects."""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _urllib_transport(request: HioBuyRequest) -> HioBuyResponse:
    http_request = Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method="POST",
    )
    try:
        opener = build_opener(_NoRedirectHandler())
        with opener.open(http_request, timeout=request.timeout_seconds) as response:
            return HioBuyResponse(
                status_code=int(response.status),
                body=_read_limited(response),
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        return HioBuyResponse(
            status_code=int(exc.code),
            body=_read_limited(exc),
            headers=dict(exc.headers.items()) if exc.headers is not None else {},
        )


def _http_failure(status_code: int) -> tuple[str, str, str] | None:
    if 200 <= status_code < 300:
        return None
    if status_code == 401:
        return (
            "AUTH_REQUIRED",
            "HIOBUY_AUTH_REQUIRED",
            "HioBuy rejected or could not authorize the API credential.",
        )
    if status_code == 403:
        return (
            "BLOCKED_BY_CREDENTIALS",
            "HIOBUY_SCOPE_BLOCKED",
            "HioBuy denied the required channel or endpoint scope.",
        )
    if status_code in {408, 504}:
        return (
            "TIMEOUT",
            "HIOBUY_HTTP_TIMEOUT",
            "The HioBuy request timed out at the HTTP boundary.",
        )
    return (
        "HTTP_ERROR",
        "HIOBUY_HTTP_ERROR",
        f"HioBuy returned HTTP {status_code}.",
    )


def _payload_failure(payload: Mapping[str, Any]) -> tuple[str, str, str] | None:
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return None
    raw_code = _nonempty_string(error.get("code"))
    code = (raw_code or "UNKNOWN_ERROR").upper()
    if code in {"INVALID_API_KEY", "CHANNEL_NOT_AUTHORIZED", "UNAUTHORIZED"}:
        status = "AUTH_REQUIRED"
    elif code in {"INSUFFICIENT_SCOPE", "FORBIDDEN"}:
        status = "BLOCKED_BY_CREDENTIALS"
    else:
        status = "HTTP_ERROR"
    # Do not copy provider messages: an upstream validation error may echo the
    # receiver or other request fields.
    safe_codes = {
        "INVALID_API_KEY",
        "CHANNEL_NOT_AUTHORIZED",
        "UNAUTHORIZED",
        "INSUFFICIENT_SCOPE",
        "FORBIDDEN",
        "RATE_LIMITED",
        "VALIDATION_ERROR",
        "NOT_FOUND",
    }
    safe_code = code if code in safe_codes else "UNRECOGNIZED_ERROR"
    return status, "HIOBUY_API_ERROR", f"HioBuy returned API error code {safe_code}."


def _execute_json(
    endpoint: str,
    request_payload: Mapping[str, Any],
    *,
    api_key: str,
    transport: Transport | None,
    timeout: float,
) -> _ApiResult:
    if endpoint not in _ALLOWED_ENDPOINTS:
        raise ValueError("HioBuy endpoint is outside the read-only allowlist")
    if not isinstance(api_key, str) or not api_key.strip():
        return _ApiResult(
            "BLOCKED_BY_CREDENTIALS",
            None,
            "HIOBUY_API_KEY_MISSING",
            "No HioBuy API credential was supplied by the caller.",
        )
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise ValueError("timeout must be a positive number")
    if timeout <= 0 or not math.isfinite(float(timeout)):
        raise ValueError("timeout must be a positive number")

    body = json.dumps(
        request_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    request = HioBuyRequest(
        url=endpoint,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Proteus-HioBuy/0.2",
        },
        body=body,
        timeout_seconds=float(timeout),
    )

    try:
        response = (transport or _urllib_transport)(request)
    except (TimeoutError, socket.timeout):
        return _ApiResult(
            "TIMEOUT",
            None,
            "HIOBUY_TRANSPORT_TIMEOUT",
            "The HioBuy transport timed out.",
        )
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return _ApiResult(
                "TIMEOUT",
                None,
                "HIOBUY_TRANSPORT_TIMEOUT",
                "The HioBuy transport timed out.",
            )
        return _ApiResult(
            "HTTP_ERROR",
            None,
            "HIOBUY_TRANSPORT_ERROR",
            "The HioBuy transport failed before a valid response was received.",
        )
    except Exception:
        # Exception text is deliberately not retained: injected transports can
        # include a full request repr containing Authorization and receiver.
        return _ApiResult(
            "HTTP_ERROR",
            None,
            "HIOBUY_TRANSPORT_ERROR",
            "The HioBuy transport failed before a valid response was received.",
        )

    if not isinstance(response, HioBuyResponse):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            "HIOBUY_TRANSPORT_RESPONSE_INVALID",
            "The HioBuy transport returned an unsupported response object.",
        )
    failure = _http_failure(response.status_code)
    if failure is not None:
        return _ApiResult(failure[0], None, failure[1], failure[2])
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            "HIOBUY_RESPONSE_INVALID_JSON",
            "HioBuy returned an invalid JSON response.",
        )
    if not isinstance(payload, Mapping):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            "HIOBUY_RESPONSE_ROOT_INVALID",
            "HioBuy returned a non-object JSON response.",
        )
    failure = _payload_failure(payload)
    if failure is not None:
        return _ApiResult(failure[0], None, failure[1], failure[2])
    return _ApiResult("SUCCESS", payload, "HIOBUY_OK", "HioBuy request succeeded.")


def _sanitize_receiver(receiver: Mapping[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(receiver, Mapping):
        return None
    sanitized: dict[str, str] = {}
    for field_name in _RECEIVER_REQUIRED_FIELDS:
        value = _nonempty_string(receiver.get(field_name))
        if value is None:
            return None
        sanitized[field_name] = value
    for field_name in _RECEIVER_OPTIONAL_FIELDS:
        if field_name not in receiver:
            continue
        value = _nonempty_string(receiver.get(field_name))
        if value is None:
            return None
        sanitized[field_name] = value
    if "address_id" not in sanitized and "district" not in sanitized:
        return None
    country = sanitized.get("country")
    if country is None:
        sanitized["country"] = "中国"
    elif country.casefold() not in {"中国", "china", "cn", "chn"}:
        return None
    return sanitized


def _safe_request_id(
    value: Any,
    *,
    api_key: str,
    receiver: Mapping[str, str],
) -> str | None:
    request_id = _nonempty_string(value)
    if request_id is None:
        return None
    sensitive_values = [api_key.strip(), *receiver.values()]
    if any(secret and secret in request_id for secret in sensitive_values):
        return None
    return request_id


def _localized_texts(value: Any) -> list[str]:
    if isinstance(value, str):
        text = _nonempty_string(value)
        return [text] if text is not None else []
    if not isinstance(value, Mapping):
        return []
    texts: list[str] = []
    for field_name in ("original", "translated"):
        text = _nonempty_string(value.get(field_name))
        if text is not None and text not in texts:
            texts.append(text)
    return texts


def _candidate_match_type(raw_part_number: str, value: Any) -> str | None:
    canonical = normalize_part_number(raw_part_number)
    # Allow the separators that marketplaces commonly insert into an OEM/MPN,
    # but require ASCII-alphanumeric token boundaries so 1234 cannot match
    # 12345.  This is deterministic identifier matching, not fuzzy semantics.
    normalized_pattern = r"(?<![A-Z0-9])" + r"[\s._/\\:\-]*".join(
        re.escape(character) for character in canonical
    ) + r"(?![A-Z0-9])"
    exact_pattern = (
        r"(?<![A-Z0-9])" + re.escape(raw_part_number.strip()) + r"(?![A-Z0-9])"
    )
    for text in _localized_texts(value):
        if re.search(exact_pattern, text, flags=re.IGNORECASE):
            return "EXACT"
        if re.search(normalized_pattern, text, flags=re.IGNORECASE):
            return "NORMALIZED_EXACT"
    return None


def _base_outcome(raw_part_number: str, retrieved_at: str) -> dict[str, Any]:
    return {
        "provider": HIOBUY_PROVIDER,
        "endpoint_url": PRODUCT_SEARCH_ENDPOINT,
        "acquisition_status": "PARSER_FAILED",
        "source_method": SOURCE_METHOD,
        "query": raw_part_number.strip(),
        "matched_part_numbers": [],
        "match_type": None,
        "supplier": None,
        "offer_url": None,
        "purchasable": None,
        "price_cny": None,
        "moq": None,
        "order_preview": None,
        "evidence": [],
        "diagnostics": [],
        "retrieved_at": retrieved_at,
    }


def _fail(
    outcome: dict[str, Any],
    status: str,
    code: str,
    message: str,
    *,
    endpoint: str,
) -> dict[str, Any]:
    outcome["endpoint_url"] = endpoint
    outcome["acquisition_status"] = status
    outcome["diagnostics"] = [{"code": code, "message": message}]
    return outcome


def _evidence(
    metric: str,
    value: Any,
    *,
    source: str,
    offer_url: str,
    retrieved_at: str,
    extraction_method: str,
    raw_evidence: str,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "source": source,
        "url": offer_url,
        "retrieved_at": retrieved_at,
        "extraction_method": extraction_method,
        "raw_evidence": raw_evidence,
        "confidence": 1.0,
    }


def _search_items(
    payload: Mapping[str, Any],
    raw_part_number: str,
) -> tuple[list[tuple[Mapping[str, Any], str]] | None, str | None, bool]:
    if payload.get("channel") != "1688":
        return None, "HioBuy search did not preserve channel=1688.", False
    keyword = _nonempty_string(payload.get("keyword"))
    try:
        keyword_matches = (
            keyword is not None
            and normalize_part_number(keyword) == normalize_part_number(raw_part_number)
        )
    except (TypeError, ValueError):
        keyword_matches = False
    if not keyword_matches:
        return None, "HioBuy search did not preserve the requested identifier.", False

    total = _nonnegative_integer(payload.get("total"))
    items = payload.get("items")
    if total is None or not isinstance(items, list):
        return None, "HioBuy search response is missing a valid total/items pair.", False
    if not items:
        if total == 0:
            return [], None, True
        return None, "HioBuy search returned no items but did not report total=0.", False
    if total == 0:
        return None, "HioBuy search total conflicts with its non-empty items.", False

    exact_items: list[tuple[Mapping[str, Any], str]] = []
    malformed = False
    for item in items:
        if not isinstance(item, Mapping):
            malformed = True
            continue
        item_id = _nonempty_string(item.get("id"))
        item_channel = item.get("channel")
        title = item.get("title")
        if item_id is None or item_channel != "1688" or not _localized_texts(title):
            malformed = True
            continue
        match_type = _candidate_match_type(raw_part_number, title)
        if match_type is not None:
            exact_items.append((item, match_type))
    if not exact_items and malformed:
        return None, "HioBuy search items were incomplete before an exact match was found.", False
    return exact_items, None, False


def _price_amount(value: Any) -> int | float | None:
    if not isinstance(value, Mapping):
        return None
    currencies = [
        _nonempty_string(value.get(field_name))
        for field_name in ("display_currency", "original_currency")
    ]
    if any(currency is not None and currency.upper() != "CNY" for currency in currencies):
        return None
    for field_name in ("promotion_amount", "display_amount", "original_amount"):
        amount = _nonnegative_number(value.get(field_name))
        if amount is not None:
            return amount
    return None


def _variant_part_relation(raw_part_number: str, variant: Mapping[str, Any]) -> str:
    attributes = variant.get("attributes")
    if not isinstance(attributes, list):
        return "NEUTRAL"
    saw_identifier_like_value = False
    for attribute in attributes:
        if not isinstance(attribute, Mapping):
            continue
        values = [
            text
            for field_name in ("value", "original_value")
            for text in _localized_texts(attribute.get(field_name))
        ]
        if any(_candidate_match_type(raw_part_number, value) for value in values):
            return "MATCH"
        names = " ".join(
            text.casefold()
            for field_name in ("name", "original_name")
            for text in _localized_texts(attribute.get(field_name))
        )
        identifier_named = any(
            marker in names
            for marker in (
                "part",
                "model",
                "mpn",
                "oem",
                "sku",
                "货号",
                "型号",
                "零件号",
                "编号",
            )
        )
        identifier_shaped = any(
            re.search(r"(?=[A-Z0-9-]{5,})(?=.*\d)[A-Z0-9]+-[A-Z0-9-]+", value, re.I)
            for value in values
        )
        saw_identifier_like_value = (
            saw_identifier_like_value or identifier_named or identifier_shaped
        )
    return "CONFLICT" if saw_identifier_like_value else "NEUTRAL"


def _select_variant(
    product: Mapping[str, Any],
    raw_part_number: str,
    max_acceptable_moq: int | None,
) -> tuple[Mapping[str, Any], int | float, int] | None:
    variants = product.get("variants")
    if not isinstance(variants, list):
        return None
    product_moq = _positive_integer(product.get("min_order_quantity"))
    product_price = _price_amount(product.get("price"))
    eligible: list[tuple[int | float, str, Mapping[str, Any], int, str]] = []
    for variant in variants:
        if not isinstance(variant, Mapping):
            continue
        sku_id = _nonempty_string(variant.get("sku_id"))
        stock = _nonnegative_number(variant.get("stock"))
        moq = _positive_integer(variant.get("min_order_quantity")) or product_moq
        price = _price_amount(variant.get("price"))
        if price is None:
            price = product_price
        if (
            sku_id is None
            or stock is None
            or moq is None
            or price is None
            or stock < moq
        ):
            continue
        relation = _variant_part_relation(raw_part_number, variant)
        eligible.append((price, sku_id, variant, moq, relation))
    if not eligible:
        return None
    matching = [item for item in eligible if item[4] == "MATCH"]
    if matching:
        eligible = matching
    elif any(item[4] == "CONFLICT" for item in eligible):
        # Once a product exposes a part/model dimension, an unlabelled sibling
        # SKU is not evidence that it fits the requested identifier.  Stop
        # instead of silently selecting a cheaper neutral or conflicting SKU.
        return None
    else:
        eligible = [item for item in eligible if item[4] == "NEUTRAL"]
    acceptable = (
        [item for item in eligible if item[3] <= max_acceptable_moq]
        if max_acceptable_moq is not None
        else eligible
    )
    pool = acceptable or eligible
    if acceptable:
        price, _sku_id, variant, moq, _relation = min(
            pool, key=lambda item: (item[0], item[3], item[1])
        )
    else:
        price, _sku_id, variant, moq, _relation = min(
            pool, key=lambda item: (item[3], item[0], item[1])
        )
    return variant, price, moq


def _preview_binds_requested_line(
    preview_payload: Mapping[str, Any],
    *,
    product_id: str,
    sku_id: str,
    quantity: int,
) -> bool:
    sellers = preview_payload.get("sellers")
    if not isinstance(sellers, list):
        return False
    for seller in sellers:
        if not isinstance(seller, Mapping):
            continue
        lines = seller.get("lines")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, Mapping):
                continue
            identities = [
                identity
                for field_name in ("id", "offer_id")
                if (identity := _nonempty_string(line.get(field_name))) is not None
            ]
            if not identities or any(identity != product_id for identity in identities):
                continue
            if _nonempty_string(line.get("spec_id")) != sku_id:
                continue
            if _positive_integer(line.get("quantity")) != quantity:
                continue
            return True
    return False


def _preview_money_cny(value: Any) -> int | float | None:
    if not isinstance(value, Mapping):
        return None
    if _nonempty_string(value.get("currency")) != "CNY":
        return None
    amount_fen = _nonnegative_integer(value.get("amount"))
    if amount_fen is None:
        return None
    return amount_fen / 100


def collect_1688_supply(
    raw_part_number: str,
    *,
    api_key: str,
    receiver: Mapping[str, Any] | None,
    transport: Transport | None = None,
    timeout: float = 30.0,
    max_acceptable_moq: int | None = None,
) -> dict[str, Any]:
    """Verify an exact 1688 offer through search, detail, and order preview.

    ``receiver`` is sent only to the preview endpoint.  It is never included in
    the returned evidence.  A true ``purchasable`` value is emitted only when
    HioBuy reports ``success=true`` and an empty ``unavailable_lines`` array.
    """

    normalize_part_number(raw_part_number)
    if max_acceptable_moq is not None and _positive_integer(max_acceptable_moq) is None:
        raise ValueError("max_acceptable_moq must be a positive integer or None")
    timestamp = _utc_now()
    outcome = _base_outcome(raw_part_number, timestamp)
    sanitized_receiver = _sanitize_receiver(receiver)
    if sanitized_receiver is None:
        return _fail(
            outcome,
            "PARSER_FAILED",
            "HIOBUY_RECEIVER_INVALID",
            "The runtime domestic receiver configuration is incomplete or invalid.",
            endpoint=ORDER_PREVIEW_ENDPOINT,
        )

    search = _execute_json(
        PRODUCT_SEARCH_ENDPOINT,
        {
            "channel": "1688",
            "keyword": raw_part_number.strip(),
            "language": "en",
            "page": 1,
            "page_size": 20,
            "response_format": "standard",
        },
        api_key=api_key,
        transport=transport,
        timeout=timeout,
    )
    if search.status != "SUCCESS":
        return _fail(
            outcome,
            search.status,
            search.diagnostic_code,
            search.diagnostic_message,
            endpoint=PRODUCT_SEARCH_ENDPOINT,
        )
    exact_items, issue, explicit_zero = _search_items(
        search.payload or {}, raw_part_number
    )
    if explicit_zero:
        return _fail(
            outcome,
            "ZERO_RESULTS",
            "HIOBUY_ZERO_RESULTS",
            "HioBuy explicitly returned items=[] and total=0 for the 1688 search.",
            endpoint=PRODUCT_SEARCH_ENDPOINT,
        )
    if exact_items is None:
        return _fail(
            outcome,
            "PARSER_FAILED",
            "HIOBUY_SEARCH_RESPONSE_INVALID",
            issue or "The HioBuy search response could not be validated.",
            endpoint=PRODUCT_SEARCH_ENDPOINT,
        )
    if not exact_items:
        outcome["acquisition_status"] = "SUCCESS"
        outcome["match_type"] = "AMBIGUOUS"
        outcome["diagnostics"] = [
            {
                "code": "HIOBUY_EXACT_MATCH_NOT_FOUND",
                "message": (
                    "Search results existed, but none contained the candidate "
                    "identifier under the deterministic exact rule."
                ),
            }
        ]
        return outcome

    search_item, search_match_type = exact_items[0]
    product_id = _nonempty_string(search_item.get("id"))
    assert product_id is not None  # Guaranteed by _search_items.
    detail = _execute_json(
        PRODUCT_DETAIL_ENDPOINT,
        {
            "channel": "1688",
            "id": product_id,
            "language": "en",
            "response_format": "standard",
        },
        api_key=api_key,
        transport=transport,
        timeout=timeout,
    )
    if detail.status != "SUCCESS":
        outcome["matched_part_numbers"] = [raw_part_number.strip()]
        outcome["match_type"] = search_match_type
        return _fail(
            outcome,
            detail.status,
            detail.diagnostic_code,
            detail.diagnostic_message,
            endpoint=PRODUCT_DETAIL_ENDPOINT,
        )

    product = (detail.payload or {}).get("product")
    if not isinstance(product, Mapping):
        return _fail(
            outcome,
            "PARSER_FAILED",
            "HIOBUY_DETAIL_RESPONSE_INVALID",
            "HioBuy detail response is missing the standard product object.",
            endpoint=PRODUCT_DETAIL_ENDPOINT,
        )
    detail_id = _nonempty_string(product.get("id"))
    source_product_id = _nonempty_string(product.get("source_product_id"))
    if (
        product.get("channel") != "1688"
        or detail_id != product_id
        or source_product_id != product_id
    ):
        return _fail(
            outcome,
            "MARKET_CONTEXT_MISMATCH",
            "HIOBUY_DETAIL_IDENTITY_MISMATCH",
            "HioBuy detail did not preserve the selected 1688 product identity.",
            endpoint=PRODUCT_DETAIL_ENDPOINT,
        )
    detail_match_type = _candidate_match_type(raw_part_number, product.get("title"))
    if detail_match_type is None:
        outcome["acquisition_status"] = "SUCCESS"
        outcome["match_type"] = "AMBIGUOUS"
        outcome["diagnostics"] = [
            {
                "code": "HIOBUY_DETAIL_EXACT_MATCH_NOT_CONFIRMED",
                "message": (
                    "The detail title did not confirm the candidate identifier "
                    "under the deterministic exact rule."
                ),
            }
        ]
        return outcome

    offer_url = _nonempty_string(product.get("source_url"))
    if offer_url is None or not _is_real_1688_url(offer_url):
        return _fail(
            outcome,
            "PARSER_FAILED",
            "HIOBUY_1688_URL_INVALID",
            "HioBuy detail did not provide a real 1688 offer URL.",
            endpoint=PRODUCT_DETAIL_ENDPOINT,
        )
    seller = product.get("seller")
    supplier = (
        _nonempty_string(seller.get("name")) if isinstance(seller, Mapping) else None
    )
    selected = _select_variant(product, raw_part_number, max_acceptable_moq)
    outcome.update(
        {
            "matched_part_numbers": [raw_part_number.strip()],
            "match_type": (
                "EXACT"
                if search_match_type == detail_match_type == "EXACT"
                else "NORMALIZED_EXACT"
            ),
            "supplier": supplier,
            "offer_url": offer_url,
        }
    )
    if supplier is None or selected is None:
        return _fail(
            outcome,
            "PARTIAL_SUCCESS",
            "HIOBUY_DETAIL_NOT_PREVIEWABLE",
            (
                "The exact 1688 detail lacks a supplier or an in-stock SKU with "
                "valid CNY price and MOQ."
            ),
            endpoint=PRODUCT_DETAIL_ENDPOINT,
        )

    variant, price_cny, moq = selected
    sku_id = _nonempty_string(variant.get("sku_id"))
    assert sku_id is not None  # Guaranteed by _select_variant.
    outcome["price_cny"] = price_cny
    outcome["moq"] = moq
    outcome["evidence"] = [
        _evidence(
            "price_cny",
            price_cny,
            source="HioBuy standard 1688 product detail",
            offer_url=offer_url,
            retrieved_at=timestamp,
            extraction_method="MANAGED_API",
            raw_evidence="Selected in-stock SKU unit price from the standard detail response.",
        ),
        _evidence(
            "moq",
            moq,
            source="HioBuy standard 1688 product detail",
            offer_url=offer_url,
            retrieved_at=timestamp,
            extraction_method="MANAGED_API",
            raw_evidence="Selected in-stock SKU MOQ from the standard detail response.",
        ),
    ]

    preview = _execute_json(
        ORDER_PREVIEW_ENDPOINT,
        {
            "channel": "1688",
            "receiver": sanitized_receiver,
            "lines": [{"id": product_id, "spec_id": sku_id, "quantity": moq}],
            "response_format": "standard",
        },
        api_key=api_key,
        transport=transport,
        timeout=timeout,
    )
    if preview.status != "SUCCESS":
        return _fail(
            outcome,
            preview.status,
            preview.diagnostic_code,
            preview.diagnostic_message,
            endpoint=ORDER_PREVIEW_ENDPOINT,
        )
    preview_payload = preview.payload or {}
    success = preview_payload.get("success")
    unavailable_lines = preview_payload.get("unavailable_lines")
    request_id = _safe_request_id(
        preview_payload.get("request_id"),
        api_key=api_key,
        receiver=sanitized_receiver,
    )
    if (
        preview_payload.get("channel") != "1688"
        or not isinstance(success, bool)
        or not isinstance(unavailable_lines, list)
        or request_id is None
    ):
        return _fail(
            outcome,
            "PARSER_FAILED",
            "HIOBUY_PREVIEW_RESPONSE_INVALID",
            (
                "HioBuy preview response is missing its 1688 success, availability, "
                "or request identity fields."
            ),
            endpoint=ORDER_PREVIEW_ENDPOINT,
        )

    purchasable = success is True and not unavailable_lines
    if not _preview_binds_requested_line(
        preview_payload,
        product_id=product_id,
        sku_id=sku_id,
        quantity=moq,
    ):
        return _fail(
            outcome,
            "PARSER_FAILED",
            "HIOBUY_PREVIEW_LINE_MISMATCH",
            (
                "The HioBuy preview did not bind the selected 1688 "
                "offer, SKU, and quantity to one returned seller line."
            ),
            endpoint=ORDER_PREVIEW_ENDPOINT,
        )
    preview_total = preview_payload.get("total")
    preview_payment_cny = None
    preview_shipping_cny = None
    if isinstance(preview_total, Mapping):
        preview_payment_cny = _preview_money_cny(preview_total.get("payment"))
        preview_shipping_cny = _preview_money_cny(preview_total.get("shipping"))
    if purchasable and (
        preview_payload.get("monetary_unit") != "CNY_minor"
        or preview_payment_cny is None
        or preview_shipping_cny is None
    ):
        return _fail(
            outcome,
            "PARSER_FAILED",
            "HIOBUY_PREVIEW_MONEY_INVALID",
            (
                "HioBuy purchasable preview is missing valid CNY payment or "
                "shipping totals."
            ),
            endpoint=ORDER_PREVIEW_ENDPOINT,
        )
    preview_retrieved_at = _utc_now()
    outcome["endpoint_url"] = ORDER_PREVIEW_ENDPOINT
    outcome["acquisition_status"] = "SUCCESS"
    outcome["purchasable"] = purchasable
    preview_binding = {
        "provider": HIOBUY_PROVIDER,
        "request_id": request_id,
        "offer_id": product_id,
        "sku_id": sku_id,
        "quantity": moq,
    }
    outcome["order_preview"] = {
        **preview_binding,
        "currency": "CNY",
        "payment_cny": preview_payment_cny,
        "shipping_cny": preview_shipping_cny,
        "retrieved_at": preview_retrieved_at,
    }
    outcome["evidence"].append(
        _evidence(
            "purchasable",
            purchasable,
            source="HioBuy standard 1688 order preview",
            offer_url=offer_url,
            retrieved_at=preview_retrieved_at,
            extraction_method="ORDER_PREVIEW",
            raw_evidence=(
                (
                    f"request_id={request_id}; id={product_id}; spec_id={sku_id}; "
                    f"quantity={moq}; success=true; unavailable_lines=[]; "
                    "the returned seller line matched; no order was created."
                )
                if purchasable
                else (
                    f"request_id={request_id}; id={product_id}; spec_id={sku_id}; "
                    f"quantity={moq}; the bound order preview did not return both "
                    "success=true and unavailable_lines=[]."
                )
            ),
        )
    )
    if purchasable:
        for metric, value in (
            ("preview_payment_cny", preview_payment_cny),
            ("preview_shipping_cny", preview_shipping_cny),
        ):
            outcome["evidence"].append(
                _evidence(
                    metric,
                    value,
                    source="HioBuy standard 1688 order preview",
                    offer_url=offer_url,
                    retrieved_at=preview_retrieved_at,
                    extraction_method="ORDER_PREVIEW",
                    raw_evidence=(
                        f"request_id={request_id}; offer_id={product_id}; "
                        f"spec_id={sku_id}; quantity={moq}; {metric}={value}"
                    ),
                )
            )
    for record in outcome["evidence"]:
        record["preview_binding"] = dict(preview_binding)
    if not purchasable:
        outcome["diagnostics"] = [
            {
                "code": "HIOBUY_PREVIEW_NOT_PURCHASABLE",
                "message": "The read-only order preview did not confirm availability.",
            }
        ]
    return outcome
