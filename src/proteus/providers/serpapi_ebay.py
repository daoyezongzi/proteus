"""SerpApi eBay sold-search adapter mapped to Proteus AcquisitionOutcome."""

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
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from proteus.ebay import classify_listing, parse_condition, parse_sold_label
from proteus.models import EBAY_US_CONTEXT, SCHEMA_VERSION
from proteus.normalization import build_part_query, normalize_part_number


SERPAPI_EBAY_PROVIDER = "SERPAPI_EBAY_MANAGED"
SEARCH_ENDPOINT = "https://serpapi.com/search"
SOURCE_METHOD = "MANAGED_API"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SerpApiRequest:
    url: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SerpApiResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[SerpApiRequest], SerpApiResponse]


class _NoRedirectHandler(HTTPRedirectHandler):
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


def _read_limited(stream: Any) -> bytes:
    body = stream.read(_MAX_RESPONSE_BYTES + 1) if stream is not None else b""
    if len(body) > _MAX_RESPONSE_BYTES:
        raise ValueError("SerpApi response exceeds the configured size limit")
    return body


def _urllib_transport(request: SerpApiRequest) -> SerpApiResponse:
    http_request = Request(
        request.url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Proteus-SerpApi/0.2",
        },
        method="GET",
    )
    try:
        opener = build_opener(_NoRedirectHandler())
        with opener.open(http_request, timeout=request.timeout_seconds) as response:
            return SerpApiResponse(
                int(response.status),
                _read_limited(response),
                dict(response.headers.items()),
            )
    except HTTPError as exc:
        return SerpApiResponse(
            int(exc.code),
            _read_limited(exc),
            dict(exc.headers.items()) if exc.headers is not None else {},
        )


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


def _observed_demand(listings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
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


def _failure(
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
                "message": f"SerpApi eBay acquisition ended with {status}",
                "raw_marker": _clip(marker),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "platform": "EBAY",
        "provider": SERPAPI_EBAY_PROVIDER,
        "source_method": SOURCE_METHOD,
        "query": build_part_query(raw_part_number),
        "market_context": dict(EBAY_US_CONTEXT),
        "status": status,
        "retrieved_at": retrieved_at,
        "listings": [],
        "observed_demand": _observed_demand([]),
        "diagnostics": diagnostics,
    }


def _http_status(status_code: int) -> tuple[str, str] | None:
    if 200 <= status_code < 300:
        return None
    if status_code == 401:
        return "AUTH_REQUIRED", "HTTP 401: SerpApi key was rejected"
    if status_code == 403:
        return "BLOCKED_BY_CREDENTIALS", "HTTP 403: SerpApi access is not authorized"
    if status_code == 429:
        return "HTTP_ERROR", "HTTP 429: SerpApi request was rate limited"
    return "HTTP_ERROR", f"HTTP {status_code}: SerpApi request failed"


def _request_url(raw_part_number: str, api_key: str) -> str:
    return f"{SEARCH_ENDPOINT}?{urlencode({
        'engine': 'ebay',
        '_nkw': raw_part_number.strip(),
        'ebay_domain': 'ebay.com',
        '_salic': '1',
        '_stpos': '10001',
        'LH_ItemCondition': '1000',
        'show_only': 'Sold',
        '_ipg': '50',
        'no_cache': 'true',
        'output': 'json',
        'api_key': api_key.strip(),
    })}"


def _parameters_match(payload: Mapping[str, Any], raw_part_number: str) -> bool:
    params = payload.get("search_parameters")
    if not isinstance(params, Mapping):
        return False
    try:
        query_matches = normalize_part_number(params.get("_nkw")) == normalize_part_number(raw_part_number)
    except (TypeError, ValueError):
        return False
    expected = {
        "engine": "ebay",
        "ebay_domain": "ebay.com",
        "show_only": "Sold",
        "LH_ItemCondition": "1000",
        "_salic": "1",
        "_stpos": "10001",
    }
    return query_matches and all(str(params.get(key)) == value for key, value in expected.items())


def _listing_price(result: Mapping[str, Any]) -> dict[str, Any] | None:
    price = result.get("price")
    if not isinstance(price, Mapping):
        return None
    amount = _nonnegative_number(price.get("extracted"))
    return {"amount": amount, "currency": "USD"} if amount is not None else None


def _sold_count(result: Mapping[str, Any]) -> tuple[int | None, str | None]:
    raw_label = _nonempty_string(result.get("quantity_sold"))
    parsed_label, parse_status = parse_sold_label(raw_label)
    extracted = _nonnegative_integer(result.get("extracted_quantity_sold"))
    if raw_label is None or parse_status != "PARSED" or parsed_label is None:
        return None, raw_label
    if extracted is not None and extracted != parsed_label:
        return None, raw_label
    return parsed_label, raw_label


def collect_ebay_sold(
    raw_part_number: str,
    *,
    api_key: str,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Collect a fresh, US, new-condition eBay sold search through SerpApi."""

    normalize_part_number(raw_part_number)
    timestamp = _retrieved_at(retrieved_at)
    if not isinstance(api_key, str) or not api_key.strip():
        return _failure(
            raw_part_number,
            "BLOCKED_BY_CREDENTIALS",
            retrieved_at=timestamp,
            marker="No SerpApi key was supplied by the caller",
        )
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a positive number")
    if timeout_seconds <= 0 or not math.isfinite(float(timeout_seconds)):
        raise ValueError("timeout_seconds must be a positive number")

    request = SerpApiRequest(_request_url(raw_part_number, api_key), float(timeout_seconds))
    try:
        response = (transport or _urllib_transport)(request)
    except (TimeoutError, socket.timeout):
        return _failure(raw_part_number, "TIMEOUT", retrieved_at=timestamp, marker="transport timed out")
    except URLError as exc:
        status = "TIMEOUT" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "HTTP_ERROR"
        return _failure(raw_part_number, status, retrieved_at=timestamp, marker="transport URL error")
    except Exception:
        return _failure(raw_part_number, "HTTP_ERROR", retrieved_at=timestamp, marker="transport raised an unexpected exception")

    if not isinstance(response, SerpApiResponse):
        return _failure(raw_part_number, "PARSER_FAILED", retrieved_at=timestamp, marker="transport returned an unsupported response")
    status_error = _http_status(response.status_code)
    if status_error is not None:
        status, marker = status_error
        return _failure(raw_part_number, status, retrieved_at=timestamp, marker=marker)
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _failure(raw_part_number, "PARSER_FAILED", retrieved_at=timestamp, marker="response is not valid UTF-8 JSON")
    if not isinstance(payload, Mapping):
        return _failure(raw_part_number, "PARSER_FAILED", retrieved_at=timestamp, marker="response JSON root is not an object")
    if "error" in payload:
        return _failure(raw_part_number, "HTTP_ERROR", retrieved_at=timestamp, marker="SerpApi returned an API error")
    metadata = payload.get("search_metadata")
    if not isinstance(metadata, Mapping) or metadata.get("status") != "Success":
        return _failure(raw_part_number, "PARSER_FAILED", retrieved_at=timestamp, marker="search_metadata does not confirm Success")
    if not _parameters_match(payload, raw_part_number):
        return _failure(raw_part_number, "MARKET_CONTEXT_MISMATCH", retrieved_at=timestamp, marker="search parameters do not match the fixed US sold-search contract")

    organic_results = payload.get("organic_results")
    if not isinstance(organic_results, list):
        return _failure(raw_part_number, "PARSER_FAILED", retrieved_at=timestamp, marker="organic_results is not an array")
    search_information = payload.get("search_information")
    total_results = search_information.get("total_results") if isinstance(search_information, Mapping) else None
    total = _nonnegative_integer(total_results)
    if not organic_results:
        if total == 0:
            return _failure(raw_part_number, "ZERO_RESULTS", retrieved_at=timestamp, marker="explicit total_results=0")
        return _failure(raw_part_number, "PARSER_FAILED", retrieved_at=timestamp, marker="empty organic_results lacks explicit total_results=0")

    diagnostics: list[dict[str, Any]] = []
    if total is None or total > len(organic_results):
        diagnostics.append(
            {
                "code": "CARD_SKIPPED",
                "message": "SerpApi eBay sold result page is incomplete or has unknown total",
                "raw_marker": f"reported_total={total}; returned_results={len(organic_results)}",
            }
        )
    listings: list[dict[str, Any]] = []
    seen: set[str] = set()
    exact_without_sold = False
    for index, result in enumerate(organic_results):
        if not isinstance(result, Mapping):
            diagnostics.append({"code": "CARD_SKIPPED", "message": f"Result {index} is not an object", "raw_marker": None})
            continue
        listing_id = _nonempty_string(result.get("product_id"))
        title = _nonempty_string(result.get("title"))
        raw_url = _nonempty_string(result.get("link"))
        if listing_id is None or title is None or raw_url is None or not _host_is(raw_url, "ebay.com"):
            diagnostics.append({"code": "CARD_SKIPPED", "message": f"Result {index} lacks a valid eBay listing identity", "raw_marker": _clip(result.get("product_id"), 100)})
            continue
        if listing_id in seen:
            diagnostics.append({"code": "DUPLICATE_LISTING", "message": "Duplicate SerpApi product_id was ignored", "raw_marker": listing_id})
            continue
        seen.add(listing_id)
        condition = parse_condition(_nonempty_string(result.get("condition")))
        sold_count, sold_label = _sold_count(result)
        match_type, decision = classify_listing(
            raw_part_number,
            title,
            condition=condition,
            sold_count=sold_count,
        )
        if condition == "UNKNOWN":
            diagnostics.append(
                {
                    "code": "CARD_SKIPPED",
                    "message": f"Listing {listing_id} has no recognized condition",
                    "raw_marker": _clip(result.get("condition"), 100),
                }
            )
        if (
            match_type in {"EXACT", "NORMALIZED_EXACT"}
            and condition == "NEW"
            and (sold_count is None or sold_count < 1)
        ):
            exact_without_sold = True
            diagnostics.append({"code": "CARD_SKIPPED", "message": f"Listing {listing_id} has no consistent explicit sold count", "raw_marker": _clip(sold_label, 100)})
        listing_url = f"https://www.ebay.com/itm/{quote(listing_id, safe='')}"
        raw_marker = f"search_id={_clip(metadata.get('id'), 100)} | product_id={listing_id} | sold_label={_clip(sold_label, 100)}"
        listings.append(
            {
                "listing_id": listing_id,
                "url": listing_url,
                "title": title,
                "condition": condition,
                "price": _listing_price(result),
                "sold_count": sold_count,
                "sold_label_raw": sold_label,
                "available_count": None,
                "seller": _nonempty_string(result.get("seller", {}).get("username")) if isinstance(result.get("seller"), Mapping) else None,
                "location": None,
                "part_numbers": [raw_part_number] if match_type in {"EXACT", "NORMALIZED_EXACT"} else [],
                "match_type": match_type,
                "decision": decision,
                "evidence": [
                    {
                        "metric": "sold_count",
                        "value": sold_count,
                        "source": "SerpApi managed eBay sold search",
                        "url": listing_url,
                        "retrieved_at": timestamp,
                        "extraction_method": SOURCE_METHOD,
                        "raw_evidence": raw_marker,
                        "confidence": 1.0 if sold_count is not None else 0.5,
                    }
                ],
            }
        )
    if not listings:
        return _failure(raw_part_number, "PARSER_FAILED", retrieved_at=timestamp, marker="no valid listing could be normalized")
    observed = _observed_demand(listings)
    if observed["aggregate_observed_sold"] == 0 and (exact_without_sold or total is None or total > len(organic_results)):
        status = "PARTIAL_SUCCESS"
    else:
        status = "PARTIAL_SUCCESS" if diagnostics else "SUCCESS"
    return {
        "schema_version": SCHEMA_VERSION,
        "platform": "EBAY",
        "provider": SERPAPI_EBAY_PROVIDER,
        "source_method": SOURCE_METHOD,
        "query": build_part_query(raw_part_number),
        "market_context": dict(EBAY_US_CONTEXT),
        "status": status,
        "retrieved_at": timestamp,
        "listings": listings,
        "observed_demand": observed,
        "diagnostics": diagnostics,
    }
