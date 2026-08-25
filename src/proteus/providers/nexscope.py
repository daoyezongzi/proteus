"""Deterministic Nexscope REST collectors for Proteus V0.2.

The collectors call concrete managed REST endpoints.  They do not use Agents,
MCP, environment credentials, or hidden credential stores.  Each API key is
accepted only as a call argument, and the transport is injectable for offline
tests and controlled deployments.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from proteus.ebay import classify_listing, parse_condition
from proteus.models import AMAZON_US_CONTEXT, EBAY_US_CONTEXT, SCHEMA_VERSION
from proteus.normalization import build_part_query, normalize_part_number


NEXSCOPE_PROVIDER = "NEXSCOPE_MANAGED_REST"
SOURCE_METHOD = "MANAGED_API"
EXTRACTION_METHOD = "MANAGED_API"

API_BASE_URL = "https://api.nexscope.ai/api/skill-api/v1/skills"
AMAZON_SEARCH_ENDPOINT = f"{API_BASE_URL}/amazon-search/run"
EBAY_SEARCH_ENDPOINT = f"{API_BASE_URL}/ebay-search/run"
SUPPLY_1688_SEARCH_ENDPOINT = f"{API_BASE_URL}/1688-product-search/run"

_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_SUCCESS_STATUSES = {"SUCCESS", "PARTIAL_SUCCESS"}


@dataclass(frozen=True, slots=True)
class RestRequest:
    """One fully materialized Nexscope REST request for an injected transport."""

    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class RestResponse:
    """Minimal transport response consumed by the collectors."""

    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[RestRequest], RestResponse]


@dataclass(frozen=True, slots=True)
class _ApiResult:
    status: str
    payload: Mapping[str, Any] | None
    marker: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _retrieved_at(value: str | None) -> str:
    if value is None:
        return _utc_now()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("retrieved_at must be a non-empty ISO 8601 date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("retrieved_at must be a valid ISO 8601 date-time") from exc
    if parsed.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone")
    return value


def _clip(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return (text or "unavailable")[:limit]


def _nonempty_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _positive_integer(value: Any) -> int | None:
    result = _nonnegative_integer(value)
    return result if result is not None and result >= 1 else None


def _nonnegative_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or not math.isfinite(value):
        return None
    return value


def _host_is(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").casefold()
    expected = domain.casefold()
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (host == expected or host.endswith(f".{expected}"))
    )


def _read_limited(stream: Any) -> bytes:
    body = stream.read(_MAX_RESPONSE_BYTES + 1)
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("Nexscope response exceeds the configured size limit")
    return body


class _NoRedirectHandler(HTTPRedirectHandler):
    """Keep bearer credentials on the single configured endpoint only."""

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


def _urllib_transport(request: RestRequest) -> RestResponse:
    http_request = Request(
        request.url,
        data=request.body,
        headers=dict(request.headers),
        method="POST",
    )
    try:
        opener = build_opener(_NoRedirectHandler())
        with opener.open(http_request, timeout=request.timeout_seconds) as response:
            return RestResponse(
                status_code=int(response.status),
                body=_read_limited(response),
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        return RestResponse(
            status_code=int(exc.code),
            body=_read_limited(exc),
            headers=dict(exc.headers.items()) if exc.headers is not None else {},
        )


def _http_status(status_code: int) -> tuple[str, str] | None:
    if 200 <= status_code < 300:
        return None
    if status_code == 401:
        return "AUTH_REQUIRED", "HTTP 401: Nexscope API key was rejected"
    if status_code == 403:
        return "BLOCKED_BY_CREDENTIALS", "HTTP 403: Nexscope API access is not authorized"
    if status_code == 429:
        return "HTTP_ERROR", "HTTP 429: Nexscope request was rate limited"
    return "HTTP_ERROR", f"HTTP {status_code}: Nexscope REST request failed"


def _provider_error(payload: Mapping[str, Any]) -> tuple[str, str] | None:
    raw_code = payload.get("errcode")
    if raw_code in (None, 0, "0"):
        raw_code = payload.get("code")
    if raw_code in (None, 0, "0", 200, "200", "SUCCESS", "success", "OK", "ok"):
        return None
    code = str(raw_code).strip()
    if code == "401":
        status = "AUTH_REQUIRED"
    elif code == "403":
        status = "BLOCKED_BY_CREDENTIALS"
    else:
        status = "HTTP_ERROR"
    # Provider error text/code can echo request data. Preserve only the local
    # status classification so credentials cannot reach evidence markers.
    return status, "Nexscope upstream reported an API error"


def _execute_json(
    endpoint: str,
    request_payload: Mapping[str, Any],
    *,
    api_key: str,
    transport: Transport | None,
    timeout_seconds: float,
) -> _ApiResult:
    if not isinstance(api_key, str) or not api_key.strip():
        return _ApiResult(
            "BLOCKED_BY_CREDENTIALS",
            None,
            "No Nexscope API key was supplied by the caller",
        )
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a positive number")
    if timeout_seconds <= 0 or not math.isfinite(float(timeout_seconds)):
        raise ValueError("timeout_seconds must be a positive number")

    body = json.dumps(
        request_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    request = RestRequest(
        url=endpoint,
        headers={
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Proteus-Nexscope/0.2",
        },
        body=body,
        timeout_seconds=float(timeout_seconds),
    )
    active_transport = transport or _urllib_transport
    try:
        response = active_transport(request)
    except (TimeoutError, socket.timeout):
        return _ApiResult("TIMEOUT", None, f"{endpoint}: transport timed out")
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return _ApiResult("TIMEOUT", None, f"{endpoint}: transport timed out")
        return _ApiResult("HTTP_ERROR", None, f"{endpoint}: transport URL error")
    except Exception:
        return _ApiResult(
            "HTTP_ERROR",
            None,
            f"{endpoint}: transport raised an unexpected exception",
        )

    if not isinstance(response, RestResponse):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            f"{endpoint}: transport returned an unsupported response object",
        )
    if (
        isinstance(response.status_code, bool)
        or not isinstance(response.status_code, int)
    ):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            f"{endpoint}: transport response has an invalid status_code",
        )
    if not isinstance(response.body, bytes):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            f"{endpoint}: transport response body is not bytes",
        )
    status_error = _http_status(response.status_code)
    if status_error is not None:
        status, marker = status_error
        return _ApiResult(status, None, f"{endpoint}: {marker}")
    try:
        decoded = response.body.decode("utf-8")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            f"{endpoint}: response body is not valid UTF-8 JSON",
        )
    if not isinstance(payload, Mapping):
        return _ApiResult(
            "PARSER_FAILED",
            None,
            f"{endpoint}: response JSON root is not an object",
        )
    provider_error = _provider_error(payload)
    if provider_error is not None:
        status, marker = provider_error
        return _ApiResult(status, None, f"{endpoint}: {marker}")
    return _ApiResult("SUCCESS", payload, endpoint)


def _evidence(
    metric: str,
    value: Any,
    *,
    source: str,
    url: str,
    retrieved_at: str,
    raw_evidence: str,
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "source": source,
        "url": url,
        "retrieved_at": retrieved_at,
        "extraction_method": EXTRACTION_METHOD,
        "raw_evidence": _clip(raw_evidence, 500),
        "confidence": confidence,
    }


def _status_evidence(
    status: str,
    marker: str,
    *,
    endpoint: str,
    retrieved_at: str,
) -> dict[str, Any]:
    return _evidence(
        "provider_status",
        status,
        source=NEXSCOPE_PROVIDER,
        url=endpoint,
        retrieved_at=retrieved_at,
        raw_evidence=marker,
    )


def _products(
    payload: Mapping[str, Any],
) -> tuple[list[Any] | None, int | None, str | None]:
    if "products" not in payload:
        return None, None, "response is missing products"
    products = payload.get("products")
    if not isinstance(products, list):
        return None, None, "response products is not an array"
    if "total" not in payload:
        return None, None, "response is missing total"
    total = _nonnegative_integer(payload.get("total"))
    if total is None:
        return None, None, "response total is not a non-negative integer"
    if not products and total != 0:
        return None, None, "empty products is not bound to an explicit total of zero"
    if products and total == 0:
        return None, None, "response total conflicts with non-empty products"
    if total < len(products):
        return None, None, "response total is smaller than the products array"
    return products, total, None


def _amazon_search_url(raw_part_number: str) -> str:
    return f"https://www.amazon.com/s?k={quote_plus(raw_part_number.strip())}"


def _amazon_product_url(product: Mapping[str, Any]) -> str | None:
    asin = _nonempty_string(product.get("asin"))
    raw_url = _nonempty_string(product.get("asinUrl"))
    if raw_url and _host_is(raw_url, "amazon.com"):
        return raw_url
    if asin and re.fullmatch(r"[A-Z0-9]{10}", asin, re.IGNORECASE):
        return f"https://www.amazon.com/dp/{quote(asin.upper(), safe='')}"
    if raw_url and re.fullmatch(r"[A-Z0-9]{10}", raw_url, re.IGNORECASE):
        return f"https://www.amazon.com/dp/{quote(raw_url.upper(), safe='')}"
    return None


def _deterministic_match_type(raw_part_number: str, title: str) -> str:
    match_type, _ = classify_listing(
        raw_part_number,
        title,
        condition="NEW",
        sold_count=1,
    )
    return match_type


def _amazon_base(raw_part_number: str, retrieved_at: str) -> dict[str, Any]:
    context = dict(AMAZON_US_CONTEXT)
    context["ship_to_postal_code"] = "10001"
    return {
        "provider": NEXSCOPE_PROVIDER,
        "endpoint_url": AMAZON_SEARCH_ENDPOINT,
        "acquisition_status": "PARSER_FAILED",
        "source_method": SOURCE_METHOD,
        "query": raw_part_number,
        "market_context": context,
        "relevance_method": None,
        "relevant_result_count": None,
        "evidence": [],
        "retrieved_at": retrieved_at,
    }


def collect_amazon_search(
    raw_part_number: str,
    *,
    api_key: str,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Collect deterministic AMAZON_US competition evidence through Nexscope."""

    normalize_part_number(raw_part_number)
    timestamp = _retrieved_at(retrieved_at)
    outcome = _amazon_base(raw_part_number, timestamp)
    api_result = _execute_json(
        AMAZON_SEARCH_ENDPOINT,
        {
            "amazonDomain": "amazon.com",
            "deliveryZip": "10001",
            "device": "desktop",
            "keyword": raw_part_number.strip(),
            "language": "en_US",
            "page": 1,
        },
        api_key=api_key,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    if api_result.status != "SUCCESS":
        outcome["acquisition_status"] = api_result.status
        outcome["evidence"] = [
            _status_evidence(
                api_result.status,
                api_result.marker,
                endpoint=AMAZON_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome

    payload = api_result.payload or {}
    response_keyword = payload.get("keyword")
    if response_keyword is not None:
        try:
            query_matches = (
                isinstance(response_keyword, str)
                and normalize_part_number(response_keyword)
                == normalize_part_number(raw_part_number)
            )
        except (TypeError, ValueError):
            query_matches = False
        if not query_matches:
            outcome["acquisition_status"] = "MARKET_CONTEXT_MISMATCH"
            outcome["evidence"] = [
                _status_evidence(
                    "MARKET_CONTEXT_MISMATCH",
                    "Nexscope response keyword does not match the requested candidate",
                    endpoint=AMAZON_SEARCH_ENDPOINT,
                    retrieved_at=timestamp,
                )
            ]
            return outcome
    source_type = _nonempty_string(payload.get("sourceType"))
    if source_type is not None and source_type.casefold() != "amazon":
        outcome["acquisition_status"] = "MARKET_CONTEXT_MISMATCH"
        outcome["evidence"] = [
            _status_evidence(
                "MARKET_CONTEXT_MISMATCH",
                f"unexpected sourceType={source_type}",
                endpoint=AMAZON_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome

    products, total, products_issue = _products(payload)
    if products_issue is not None:
        outcome["acquisition_status"] = "PARSER_FAILED"
        outcome["evidence"] = [
            _status_evidence(
                "PARSER_FAILED",
                products_issue,
                endpoint=AMAZON_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome
    if products == []:
        outcome["acquisition_status"] = "ZERO_RESULTS"
        outcome["relevance_method"] = "DETERMINISTIC_EXACT"
        outcome["relevant_result_count"] = 0
        outcome["evidence"] = [
            _evidence(
                "relevant_result_count",
                0,
                source="Nexscope managed Amazon Search",
                url=_amazon_search_url(raw_part_number),
                retrieved_at=timestamp,
                raw_evidence="products=[]; total=0; exact_or_normalized_matches=0",
            )
        ]
        return outcome
    incomplete_page = total is not None and total > len(products or [])

    relevant: list[tuple[Mapping[str, Any], str, str]] = []
    skipped = 0
    for product in products or []:
        if not isinstance(product, Mapping):
            skipped += 1
            continue
        title = _nonempty_string(product.get("title"))
        if title is None:
            skipped += 1
            continue
        product_source_type = _nonempty_string(product.get("sourceType"))
        if (
            product_source_type is not None
            and product_source_type.casefold() != "amazon"
        ):
            outcome["acquisition_status"] = "MARKET_CONTEXT_MISMATCH"
            outcome["evidence"] = [
                _status_evidence(
                    "MARKET_CONTEXT_MISMATCH",
                    f"Amazon product sourceType is {product_source_type}",
                    endpoint=AMAZON_SEARCH_ENDPOINT,
                    retrieved_at=timestamp,
                )
            ]
            return outcome
        currency = _nonempty_string(product.get("currency"))
        if currency is None:
            skipped += 1
            continue
        if currency.upper() != "USD":
            outcome["acquisition_status"] = "MARKET_CONTEXT_MISMATCH"
            outcome["evidence"] = [
                _status_evidence(
                    "MARKET_CONTEXT_MISMATCH",
                    f"Amazon product currency is {currency}, not USD",
                    endpoint=AMAZON_SEARCH_ENDPOINT,
                    retrieved_at=timestamp,
                )
            ]
            return outcome
        match_type = _deterministic_match_type(raw_part_number, title)
        if match_type in {"EXACT", "NORMALIZED_EXACT"}:
            product_url = _amazon_product_url(product) or _amazon_search_url(raw_part_number)
            relevant.append((product, match_type, product_url))

    evidence = [
        _evidence(
            "provider_endpoint",
            AMAZON_SEARCH_ENDPOINT,
            source=NEXSCOPE_PROVIDER,
            url=AMAZON_SEARCH_ENDPOINT,
            retrieved_at=timestamp,
            raw_evidence=f"POST {AMAZON_SEARCH_ENDPOINT}",
        ),
        _evidence(
            (
                "observed_relevant_result_count"
                if incomplete_page
                else "relevant_result_count"
            ),
            len(relevant),
            source="Nexscope managed Amazon Search",
            url=_amazon_search_url(raw_part_number),
            retrieved_at=timestamp,
            raw_evidence=(
                f"products_reviewed={len(products or []) - skipped}; "
                f"exact_or_normalized_matches={len(relevant)}; skipped={skipped}; "
                f"reported_total={total}; returned_products={len(products or [])}"
            ),
            confidence=1.0 if skipped == 0 and not incomplete_page else 0.7,
        ),
    ]
    if incomplete_page:
        evidence.append(
            _evidence(
                "provider_page_complete",
                False,
                source=NEXSCOPE_PROVIDER,
                url=AMAZON_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
                raw_evidence=(
                    f"reported_total={total}; returned_products={len(products or [])}"
                ),
            )
        )
    for product, match_type, product_url in relevant:
        evidence.append(
            _evidence(
                "amazon_relevant_product",
                {
                    "asin": _nonempty_string(product.get("asin")),
                    "match_type": match_type,
                },
                source="Nexscope managed Amazon Search",
                url=product_url,
                retrieved_at=timestamp,
                raw_evidence=f"title={_clip(product.get('title'), 240)}",
                confidence=1.0,
            )
        )
    outcome["acquisition_status"] = (
        "PARTIAL_SUCCESS" if skipped or incomplete_page else "SUCCESS"
    )
    outcome["relevance_method"] = (
        "DETERMINISTIC_EXACT" if skipped == 0 and not incomplete_page else None
    )
    outcome["relevant_result_count"] = None if incomplete_page else len(relevant)
    outcome["evidence"] = evidence
    return outcome


def _ebay_failure(
    raw_part_number: str,
    status: str,
    *,
    retrieved_at: str,
    marker: str,
) -> dict[str, Any]:
    diagnostics = []
    if status != "ZERO_RESULTS":
        code = status if status in {
            "HTTP_ERROR",
            "TIMEOUT",
            "AUTH_REQUIRED",
            "BLOCKED_BY_CREDENTIALS",
            "MARKET_CONTEXT_MISMATCH",
            "PARSER_FAILED",
        } else "PARSER_FAILED"
        diagnostics.append(
            {
                "code": code,
                "message": f"Nexscope eBay acquisition ended with {status}",
                "raw_marker": _clip(f"{EBAY_SEARCH_ENDPOINT}: {marker}", 300),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "platform": "EBAY",
        "provider": NEXSCOPE_PROVIDER,
        "source_method": SOURCE_METHOD,
        "query": build_part_query(raw_part_number),
        "market_context": dict(EBAY_US_CONTEXT),
        "status": status,
        "retrieved_at": retrieved_at,
        "listings": [],
        "observed_demand": {
            "eligible_listing_count": 0,
            "max_single_listing_sold": None,
            "aggregate_observed_sold": 0,
        },
        "diagnostics": diagnostics,
    }


def _ebay_listing_url(product: Mapping[str, Any], listing_id: str) -> str | None:
    raw_url = _nonempty_string(product.get("link"))
    if raw_url is not None:
        return raw_url if _host_is(raw_url, "ebay.com") else None
    return f"https://www.ebay.com/itm/{quote(listing_id, safe='')}"


def _ebay_observed_demand(listings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sold_counts = [
        int(listing["sold_count"])
        for listing in listings
        if listing.get("decision") == "ACCEPT_DEMAND_EVIDENCE"
        and listing.get("match_type") in {"EXACT", "NORMALIZED_EXACT"}
        and listing.get("condition") == "NEW"
        and isinstance(listing.get("sold_count"), int)
        and int(listing["sold_count"]) > 0
    ]
    return {
        "eligible_listing_count": len(sold_counts),
        "max_single_listing_sold": max(sold_counts) if sold_counts else None,
        "aggregate_observed_sold": sum(sold_counts),
    }


def collect_ebay_search(
    raw_part_number: str,
    *,
    api_key: str,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Collect an evaluator-ready eBay AcquisitionOutcome through Nexscope."""

    normalize_part_number(raw_part_number)
    timestamp = _retrieved_at(retrieved_at)
    api_result = _execute_json(
        EBAY_SEARCH_ENDPOINT,
        {
            "ebayDomain": "ebay.com",
            "keyword": raw_part_number.strip(),
            "location": 1,
            "orderBy": "12",
            "page": 1,
            "pageSize": 50,
            "prefLoc": "1",
            "zipCode": "10001",
        },
        api_key=api_key,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    if api_result.status != "SUCCESS":
        return _ebay_failure(
            raw_part_number,
            api_result.status,
            retrieved_at=timestamp,
            marker=api_result.marker,
        )

    payload = api_result.payload or {}
    source_type = _nonempty_string(payload.get("sourceType"))
    if source_type is not None and source_type.casefold() != "ebay":
        return _ebay_failure(
            raw_part_number,
            "MARKET_CONTEXT_MISMATCH",
            retrieved_at=timestamp,
            marker=f"unexpected sourceType={source_type}",
        )
    products, total, products_issue = _products(payload)
    if products_issue is not None:
        return _ebay_failure(
            raw_part_number,
            "PARSER_FAILED",
            retrieved_at=timestamp,
            marker=products_issue,
        )
    if products == []:
        return _ebay_failure(
            raw_part_number,
            "ZERO_RESULTS",
            retrieved_at=timestamp,
            marker="Nexscope returned products=[] and total=0",
        )

    listings: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    if total is not None and total > len(products or []):
        diagnostics.append(
            {
                "code": "CARD_SKIPPED",
                "message": "Nexscope eBay result page is incomplete",
                "raw_marker": (
                    f"reported_total={total}; returned_products={len(products or [])}"
                ),
            }
        )
    seen: set[str] = set()
    for index, product in enumerate(products or []):
        if not isinstance(product, Mapping):
            diagnostics.append(
                {
                    "code": "CARD_SKIPPED",
                    "message": f"Nexscope product {index} is not an object",
                    "raw_marker": None,
                }
            )
            continue
        product_source_type = _nonempty_string(product.get("sourceType"))
        if (
            product_source_type is not None
            and product_source_type.casefold() != "ebay"
        ):
            return _ebay_failure(
                raw_part_number,
                "MARKET_CONTEXT_MISMATCH",
                retrieved_at=timestamp,
                marker=f"product {index} sourceType is {product_source_type}",
            )
        listing_id = _nonempty_string(product.get("productId"))
        title = _nonempty_string(product.get("title"))
        if listing_id is None or title is None:
            diagnostics.append(
                {
                    "code": "CARD_SKIPPED",
                    "message": f"Nexscope product {index} lacks productId or title",
                    "raw_marker": _clip(product.get("productId"), 100),
                }
            )
            continue
        if listing_id in seen:
            diagnostics.append(
                {
                    "code": "DUPLICATE_LISTING",
                    "message": "Duplicate Nexscope eBay productId was ignored",
                    "raw_marker": listing_id,
                }
            )
            continue
        seen.add(listing_id)
        currency = _nonempty_string(product.get("currency"))
        if currency is None or currency.upper() != "USD":
            return _ebay_failure(
                raw_part_number,
                "MARKET_CONTEXT_MISMATCH",
                retrieved_at=timestamp,
                marker=f"product {listing_id} does not explicitly use USD",
            )
        listing_url = _ebay_listing_url(product, listing_id)
        if listing_url is None:
            return _ebay_failure(
                raw_part_number,
                "MARKET_CONTEXT_MISMATCH",
                retrieved_at=timestamp,
                marker=f"product {listing_id} link is not on ebay.com",
            )
        condition_raw = _nonempty_string(product.get("condition"))
        condition = parse_condition(condition_raw)
        if condition_raw is None or condition == "UNKNOWN":
            diagnostics.append(
                {
                    "code": "CARD_SKIPPED",
                    "message": f"Product {listing_id} has no recognized condition",
                    "raw_marker": condition_raw,
                }
            )
        sold_count = _nonnegative_integer(product.get("salesQuantity"))
        if "salesQuantity" not in product or sold_count is None:
            diagnostics.append(
                {
                    "code": "CARD_SKIPPED",
                    "message": f"Product {listing_id} has no valid salesQuantity",
                    "raw_marker": _clip(product.get("salesQuantity"), 100),
                }
            )
        match_type, decision = classify_listing(
            raw_part_number,
            title,
            condition=condition,
            sold_count=sold_count,
        )
        price_value = _nonnegative_number(product.get("price"))
        raw = (
            f"productId={listing_id} | title={_clip(title, 240)} | "
            f"condition={condition} | salesQuantity={sold_count}"
        )
        listings.append(
            {
                "listing_id": listing_id,
                "url": listing_url,
                "title": title,
                "condition": condition,
                "price": (
                    {"amount": price_value, "currency": "USD"}
                    if price_value is not None
                    else None
                ),
                "sold_count": sold_count,
                "sold_label_raw": None,
                "available_count": None,
                "seller": _nonempty_string(product.get("sellerName")),
                "location": _nonempty_string(product.get("location")),
                "part_numbers": (
                    [raw_part_number]
                    if match_type in {"EXACT", "NORMALIZED_EXACT"}
                    else []
                ),
                "match_type": match_type,
                "decision": decision,
                "evidence": [
                    _evidence(
                        "sold_count",
                        sold_count,
                        source="Nexscope managed eBay Search",
                        url=EBAY_SEARCH_ENDPOINT,
                        retrieved_at=timestamp,
                        raw_evidence=raw,
                        confidence=1.0 if sold_count is not None else 0.5,
                    )
                ],
            }
        )

    if not listings:
        failure = _ebay_failure(
            raw_part_number,
            "PARSER_FAILED",
            retrieved_at=timestamp,
            marker="no valid listing could be normalized from non-zero products",
        )
        failure["diagnostics"] = diagnostics + failure["diagnostics"]
        return failure
    return {
        "schema_version": SCHEMA_VERSION,
        "platform": "EBAY",
        "provider": NEXSCOPE_PROVIDER,
        "source_method": SOURCE_METHOD,
        "query": build_part_query(raw_part_number),
        "market_context": dict(EBAY_US_CONTEXT),
        "status": "PARTIAL_SUCCESS" if diagnostics else "SUCCESS",
        "retrieved_at": timestamp,
        "listings": listings,
        "observed_demand": _ebay_observed_demand(listings),
        "diagnostics": diagnostics,
    }


def _supply_base(raw_part_number: str, retrieved_at: str) -> dict[str, Any]:
    return {
        "provider": NEXSCOPE_PROVIDER,
        "endpoint_url": SUPPLY_1688_SEARCH_ENDPOINT,
        "acquisition_status": "PARSER_FAILED",
        "source_method": SOURCE_METHOD,
        "query": raw_part_number,
        "matched_part_numbers": [],
        "match_type": None,
        "supplier": None,
        "offer_url": None,
        "purchasable": None,
        "purchasability_reason": (
            "Nexscope product-search data is listing-level and does not prove an order preview."
        ),
        "price_cny": None,
        "moq": None,
        "order_preview": None,
        "evidence": [],
        "retrieved_at": retrieved_at,
    }


def _offer_url(product: Mapping[str, Any]) -> str | None:
    raw_url = _nonempty_string(product.get("asinUrl"))
    if raw_url and _host_is(raw_url, "1688.com"):
        return raw_url
    offer_id = _nonempty_string(product.get("offerId"))
    if offer_id:
        return f"https://detail.1688.com/offer/{quote(offer_id, safe='')}.html"
    return None


def _supply_match_type(raw_part_number: str, product: Mapping[str, Any]) -> str:
    asin = _nonempty_string(product.get("asin"))
    if asin is not None:
        try:
            if normalize_part_number(asin) == normalize_part_number(raw_part_number):
                return "EXACT" if asin.casefold() == raw_part_number.casefold() else "NORMALIZED_EXACT"
        except (TypeError, ValueError):
            pass
    title = _nonempty_string(product.get("title"))
    return _deterministic_match_type(raw_part_number, title or "unavailable")


def collect_1688_search(
    raw_part_number: str,
    *,
    api_key: str,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Collect listing-level 1688 supply evidence without claiming purchasability."""

    normalize_part_number(raw_part_number)
    timestamp = _retrieved_at(retrieved_at)
    outcome = _supply_base(raw_part_number, timestamp)
    api_result = _execute_json(
        SUPPLY_1688_SEARCH_ENDPOINT,
        {
            "keyWord": raw_part_number.strip(),
            "pageIndex": 1,
            "pageSize": 10,
            "searchType": 3,
        },
        api_key=api_key,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    if api_result.status != "SUCCESS":
        outcome["acquisition_status"] = api_result.status
        outcome["evidence"] = [
            _status_evidence(
                api_result.status,
                api_result.marker,
                endpoint=SUPPLY_1688_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome

    payload = api_result.payload or {}
    source_type = _nonempty_string(payload.get("sourceType"))
    if source_type is not None and source_type.casefold() != "1688":
        outcome["acquisition_status"] = "MARKET_CONTEXT_MISMATCH"
        outcome["evidence"] = [
            _status_evidence(
                "MARKET_CONTEXT_MISMATCH",
                f"unexpected sourceType={source_type}",
                endpoint=SUPPLY_1688_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome
    products, total, products_issue = _products(payload)
    if products_issue is not None:
        outcome["acquisition_status"] = "PARSER_FAILED"
        outcome["evidence"] = [
            _status_evidence(
                "PARSER_FAILED",
                products_issue,
                endpoint=SUPPLY_1688_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome
    if products == []:
        outcome["acquisition_status"] = "ZERO_RESULTS"
        outcome["evidence"] = [
            _status_evidence(
                "ZERO_RESULTS",
                "Nexscope returned products=[] and total=0",
                endpoint=SUPPLY_1688_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome
    incomplete_page = total is not None and total > len(products or [])

    candidates: list[tuple[int, int, Mapping[str, Any], str]] = []
    invalid_products = 0
    fallback_match_type = "IRRELEVANT"
    for index, product in enumerate(products or []):
        if not isinstance(product, Mapping):
            invalid_products += 1
            continue
        product_source_type = _nonempty_string(product.get("sourceType"))
        if (
            product_source_type is not None
            and product_source_type.casefold() != "1688"
        ):
            outcome["acquisition_status"] = "MARKET_CONTEXT_MISMATCH"
            outcome["evidence"] = [
                _status_evidence(
                    "MARKET_CONTEXT_MISMATCH",
                    f"1688 product sourceType is {product_source_type}",
                    endpoint=SUPPLY_1688_SEARCH_ENDPOINT,
                    retrieved_at=timestamp,
                )
            ]
            return outcome
        if (
            _nonempty_string(product.get("asin")) is None
            and _nonempty_string(product.get("title")) is None
        ):
            invalid_products += 1
            continue
        match_type = _supply_match_type(raw_part_number, product)
        if match_type != "IRRELEVANT":
            fallback_match_type = match_type
        if match_type not in {"EXACT", "NORMALIZED_EXACT"}:
            continue
        completeness = sum(
            value is not None
            for value in (
                _nonempty_string(product.get("company")),
                _offer_url(product),
                _nonnegative_number(product.get("price")),
                _positive_integer(product.get("quantityBegin")),
            )
        )
        candidates.append((completeness, -index, product, match_type))

    endpoint_record = _evidence(
        "provider_endpoint",
        SUPPLY_1688_SEARCH_ENDPOINT,
        source=NEXSCOPE_PROVIDER,
        url=SUPPLY_1688_SEARCH_ENDPOINT,
        retrieved_at=timestamp,
        raw_evidence=f"POST {SUPPLY_1688_SEARCH_ENDPOINT}",
    )
    page_records = [endpoint_record]
    if incomplete_page:
        page_records.append(
            _evidence(
                "provider_page_complete",
                False,
                source=NEXSCOPE_PROVIDER,
                url=SUPPLY_1688_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
                raw_evidence=(
                    f"reported_total={total}; returned_products={len(products or [])}"
                ),
            )
        )
    if not candidates:
        outcome["acquisition_status"] = (
            "PARTIAL_SUCCESS"
            if invalid_products or incomplete_page
            else "SUCCESS"
        )
        outcome["match_type"] = fallback_match_type
        outcome["evidence"] = page_records
        return outcome

    _, _, selected, match_type = max(candidates, key=lambda item: (item[0], item[1]))
    supplier = _nonempty_string(selected.get("company"))
    offer_url = _offer_url(selected)
    price = _nonnegative_number(selected.get("price"))
    moq = _positive_integer(selected.get("quantityBegin"))
    currency = _nonempty_string(selected.get("currency"))
    if currency is not None and currency.upper() not in {"CNY", "RMB", "¥"}:
        outcome["acquisition_status"] = "MARKET_CONTEXT_MISMATCH"
        outcome["evidence"] = [
            _status_evidence(
                "MARKET_CONTEXT_MISMATCH",
                f"1688 product currency is {currency}, not CNY",
                endpoint=SUPPLY_1688_SEARCH_ENDPOINT,
                retrieved_at=timestamp,
            )
        ]
        return outcome
    selected_part_number = _nonempty_string(selected.get("asin"))
    try:
        selected_part_matches = (
            selected_part_number is not None
            and normalize_part_number(selected_part_number)
            == normalize_part_number(raw_part_number)
        )
    except (TypeError, ValueError):
        selected_part_matches = False
    matched_part_number = (
        selected_part_number if selected_part_matches else raw_part_number
    )
    outcome.update(
        {
            "acquisition_status": (
                "SUCCESS"
                if all(value is not None for value in (supplier, offer_url, price, moq))
                and not invalid_products
                and not incomplete_page
                else "PARTIAL_SUCCESS"
            ),
            "matched_part_numbers": [matched_part_number],
            "match_type": match_type,
            "supplier": supplier,
            "offer_url": offer_url,
            "purchasable": None,
            "price_cny": price,
            "moq": moq,
        }
    )
    evidence = page_records
    raw_offer = (
        f"offerId={_clip(selected.get('offerId'), 80)} | "
        f"asin={_clip(selected.get('asin'), 100)} | "
        f"company={_clip(supplier, 160)} | price={price} | quantityBegin={moq}"
    )
    field_evidence_url = offer_url or SUPPLY_1688_SEARCH_ENDPOINT
    for metric, value in (
        ("matched_part_number", matched_part_number),
        ("supplier", supplier),
        ("offer_url", offer_url),
        ("price_cny", price),
        ("moq", moq),
        ("listing_signal_only", True),
    ):
        if value is not None:
            evidence.append(
                _evidence(
                    metric,
                    value,
                    source="Nexscope managed 1688 Product Search",
                    url=field_evidence_url,
                    retrieved_at=timestamp,
                    raw_evidence=raw_offer,
                )
            )
    outcome["evidence"] = evidence
    return outcome


__all__ = [
    "AMAZON_SEARCH_ENDPOINT",
    "EBAY_SEARCH_ENDPOINT",
    "NEXSCOPE_PROVIDER",
    "SOURCE_METHOD",
    "SUPPLY_1688_SEARCH_ENDPOINT",
    "RestRequest",
    "RestResponse",
    "Transport",
    "collect_1688_search",
    "collect_amazon_search",
    "collect_ebay_search",
]
