"""SerpApi Amazon exact-search adapter for the competition gate."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
import re
import socket
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, quote_plus, urlencode, urlparse

from proteus.ebay import classify_listing
from proteus.models import AMAZON_US_CONTEXT
from proteus.normalization import normalize_part_number
from proteus.providers.serpapi_ebay import (
    SEARCH_ENDPOINT,
    SerpApiRequest,
    SerpApiResponse,
    Transport,
    _urllib_transport,
)


SERPAPI_AMAZON_PROVIDER = "SERPAPI_AMAZON_MANAGED"
SOURCE_METHOD = "MANAGED_API"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _retrieved_at(value: str | None) -> str:
    if value is None:
        return _utc_now()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("retrieved_at must be a non-empty ISO 8601 date-time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("retrieved_at must include a timezone")
    return value


def _nonempty_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _clip(value: Any, limit: int = 400) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    return (text or "unavailable")[:limit]


def _host_is(url: str, domain: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").rstrip(".").casefold()
    return bool(
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (host == domain or host.endswith(f".{domain}"))
    )


def _search_url(raw_part_number: str) -> str:
    return f"https://www.amazon.com/s?k={quote_plus(raw_part_number.strip())}"


def _product_url(result: Mapping[str, Any]) -> str | None:
    raw_url = _nonempty_string(result.get("link"))
    if raw_url is not None and _host_is(raw_url, "amazon.com"):
        return raw_url
    asin = _nonempty_string(result.get("asin"))
    if asin is not None and re.fullmatch(r"[A-Z0-9]{10}", asin, re.IGNORECASE):
        return f"https://www.amazon.com/dp/{quote(asin.upper(), safe='')}"
    return None


def _request_url(raw_part_number: str, api_key: str) -> str:
    return f"{SEARCH_ENDPOINT}?{urlencode({
        'engine': 'amazon',
        'k': raw_part_number.strip(),
        'amazon_domain': 'amazon.com',
        'language': 'en_US',
        'delivery_zip': '10001',
        'device': 'desktop',
        'no_cache': 'true',
        'output': 'json',
        'api_key': api_key.strip(),
    })}"


def _base(raw_part_number: str, retrieved_at: str) -> dict[str, Any]:
    context = dict(AMAZON_US_CONTEXT)
    context["ship_to_postal_code"] = "10001"
    return {
        "provider": SERPAPI_AMAZON_PROVIDER,
        "endpoint_url": SEARCH_ENDPOINT,
        "acquisition_status": "PARSER_FAILED",
        "source_method": SOURCE_METHOD,
        "query": raw_part_number.strip(),
        "market_context": context,
        "relevance_method": None,
        "relevant_result_count": None,
        "evidence": [],
        "retrieved_at": retrieved_at,
    }


def _evidence(
    metric: str,
    value: Any,
    *,
    url: str,
    retrieved_at: str,
    raw_evidence: str,
    confidence: float = 1.0,
) -> dict[str, Any]:
    return {
        "metric": metric,
        "value": value,
        "source": "SerpApi managed Amazon exact search",
        "url": url,
        "retrieved_at": retrieved_at,
        "extraction_method": SOURCE_METHOD,
        "raw_evidence": _clip(raw_evidence),
        "confidence": confidence,
    }


def _failure(
    outcome: dict[str, Any], status: str, marker: str, *, retrieved_at: str
) -> dict[str, Any]:
    outcome["acquisition_status"] = status
    outcome["evidence"] = [
        _evidence(
            "provider_status",
            status,
            url=SEARCH_ENDPOINT,
            retrieved_at=retrieved_at,
            raw_evidence=marker,
        )
    ]
    return outcome


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


def _parameters_match(payload: Mapping[str, Any], raw_part_number: str) -> bool:
    params = payload.get("search_parameters")
    if not isinstance(params, Mapping):
        return False
    try:
        query_matches = normalize_part_number(params.get("k")) == normalize_part_number(
            raw_part_number
        )
    except (TypeError, ValueError):
        return False
    expected = {
        "engine": "amazon",
        "amazon_domain": "amazon.com",
        "language": "en_US",
        "delivery_zip": "10001",
    }
    return query_matches and all(str(params.get(key)) == value for key, value in expected.items())


def _has_next_page(payload: Mapping[str, Any]) -> bool:
    for key in ("pagination", "serpapi_pagination"):
        pagination = payload.get(key)
        if isinstance(pagination, Mapping) and _nonempty_string(pagination.get("next")):
            return True
    return False


def collect_amazon_competition(
    raw_part_number: str,
    *,
    api_key: str,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Collect one fresh, complete Amazon US search page and count exact matches."""

    normalize_part_number(raw_part_number)
    timestamp = _retrieved_at(retrieved_at)
    outcome = _base(raw_part_number, timestamp)
    if not isinstance(api_key, str) or not api_key.strip():
        return _failure(
            outcome,
            "BLOCKED_BY_CREDENTIALS",
            "No SerpApi key was supplied by the caller",
            retrieved_at=timestamp,
        )
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a positive number")
    if timeout_seconds <= 0 or not math.isfinite(float(timeout_seconds)):
        raise ValueError("timeout_seconds must be a positive number")

    request = SerpApiRequest(_request_url(raw_part_number, api_key), float(timeout_seconds))
    try:
        response = (transport or _urllib_transport)(request)
    except (TimeoutError, socket.timeout):
        return _failure(outcome, "TIMEOUT", "transport timed out", retrieved_at=timestamp)
    except URLError as exc:
        status = "TIMEOUT" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "HTTP_ERROR"
        return _failure(outcome, status, "transport URL error", retrieved_at=timestamp)
    except Exception:
        return _failure(outcome, "HTTP_ERROR", "transport raised an unexpected exception", retrieved_at=timestamp)

    if not isinstance(response, SerpApiResponse):
        return _failure(outcome, "PARSER_FAILED", "unsupported transport response", retrieved_at=timestamp)
    status_error = _http_status(response.status_code)
    if status_error is not None:
        return _failure(outcome, *status_error, retrieved_at=timestamp)
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _failure(outcome, "PARSER_FAILED", "response is not valid UTF-8 JSON", retrieved_at=timestamp)
    if not isinstance(payload, Mapping):
        return _failure(outcome, "PARSER_FAILED", "response JSON root is not an object", retrieved_at=timestamp)
    if "error" in payload:
        return _failure(outcome, "HTTP_ERROR", "SerpApi returned an API error", retrieved_at=timestamp)
    metadata = payload.get("search_metadata")
    if not isinstance(metadata, Mapping) or metadata.get("status") != "Success":
        return _failure(outcome, "PARSER_FAILED", "search_metadata does not confirm Success", retrieved_at=timestamp)
    if not _parameters_match(payload, raw_part_number):
        return _failure(outcome, "MARKET_CONTEXT_MISMATCH", "search parameters do not match AMAZON_US", retrieved_at=timestamp)

    results = payload.get("organic_results")
    if not isinstance(results, list):
        return _failure(outcome, "PARSER_FAILED", "organic_results is not an array", retrieved_at=timestamp)
    search_information = payload.get("search_information")
    total = _nonnegative_integer(
        search_information.get("total_results")
        if isinstance(search_information, Mapping)
        else None
    )
    if not results:
        if total != 0:
            return _failure(outcome, "PARSER_FAILED", "empty results lack explicit total_results=0", retrieved_at=timestamp)
        outcome["acquisition_status"] = "ZERO_RESULTS"
        outcome["relevance_method"] = "DETERMINISTIC_EXACT"
        outcome["relevant_result_count"] = 0
        outcome["evidence"] = [
            _evidence(
                "relevant_result_count",
                0,
                url=_search_url(raw_part_number),
                retrieved_at=timestamp,
                raw_evidence="organic_results=[]; total_results=0; exact_matches=0",
            )
        ]
        return outcome

    relevant: list[tuple[Mapping[str, Any], str, str]] = []
    skipped = 0
    for result in results:
        if not isinstance(result, Mapping):
            skipped += 1
            continue
        title = _nonempty_string(result.get("title"))
        product_url = _product_url(result)
        if title is None or product_url is None:
            skipped += 1
            continue
        match_type, _decision = classify_listing(
            raw_part_number,
            title,
            condition="NEW",
            sold_count=1,
        )
        if match_type in {"EXACT", "NORMALIZED_EXACT"}:
            relevant.append((result, match_type, product_url))

    incomplete = bool(skipped or _has_next_page(payload))
    observed_count = len(relevant)
    outcome["acquisition_status"] = "PARTIAL_SUCCESS" if incomplete else "SUCCESS"
    outcome["relevance_method"] = None if incomplete else "DETERMINISTIC_EXACT"
    outcome["relevant_result_count"] = None if incomplete else observed_count
    outcome["evidence"] = [
        _evidence(
            "observed_relevant_result_count" if incomplete else "relevant_result_count",
            observed_count,
            url=_search_url(raw_part_number),
            retrieved_at=timestamp,
            raw_evidence=(
                f"organic_results={len(results)}; exact_matches={observed_count}; "
                f"skipped={skipped}; has_next_page={_has_next_page(payload)}; "
                f"reported_total={total}"
            ),
            confidence=0.7 if incomplete else 1.0,
        )
    ]
    for result, match_type, product_url in relevant:
        outcome["evidence"].append(
            _evidence(
                "amazon_relevant_product",
                {"asin": _nonempty_string(result.get("asin")), "match_type": match_type},
                url=product_url,
                retrieved_at=timestamp,
                raw_evidence=f"title={_clip(result.get('title'), 240)}",
            )
        )
    return outcome


__all__ = [
    "SERPAPI_AMAZON_PROVIDER",
    "SerpApiRequest",
    "SerpApiResponse",
    "collect_amazon_competition",
]
