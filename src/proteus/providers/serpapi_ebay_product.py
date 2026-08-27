"""SerpApi eBay Product adapter for normalized automotive compatibility."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import re
import socket
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode

from proteus.providers.serpapi_ebay import (
    SEARCH_ENDPOINT,
    SerpApiRequest,
    SerpApiResponse,
    Transport,
    _http_status,
    _retrieved_at,
)
from proteus.providers.serpapi_transport import perform_async_search


SERPAPI_EBAY_PRODUCT_PROVIDER = "SERPAPI_EBAY_PRODUCT_COMPATIBILITY"
SOURCE_METHOD = "MANAGED_API"


def _request_url(listing_id: str, api_key: str) -> str:
    return f"{SEARCH_ENDPOINT}?{urlencode({
        'engine': 'ebay_product',
        'product_id': listing_id,
        'ebay_domain': 'ebay.com',
        'output': 'json',
        'api_key': api_key.strip(),
    })}"


def _base(listing_id: str, retrieved_at: str) -> dict[str, Any]:
    return {
        "provider": SERPAPI_EBAY_PRODUCT_PROVIDER,
        "source_method": SOURCE_METHOD,
        "status": "PARSER_FAILED",
        "listing_id": listing_id,
        "marketplace_id": "EBAY_US",
        "fitments": [],
        "fitment_count": 0,
        "retrieved_at": retrieved_at,
        "diagnostics": [],
    }


def _failure(outcome: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    outcome["status"] = status
    outcome["diagnostics"] = [{"code": status, "message": message}]
    return outcome


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _parameters_match(payload: Mapping[str, Any], listing_id: str) -> bool:
    parameters = payload.get("search_parameters")
    return bool(
        isinstance(parameters, Mapping)
        and str(parameters.get("engine")) == "ebay_product"
        and str(parameters.get("product_id")) == listing_id
        and str(parameters.get("ebay_domain")) == "ebay.com"
    )


def _fitment(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    raw_year = value.get("year")
    try:
        year = int(raw_year)
    except (TypeError, ValueError):
        return None
    make = _text(value.get("make"))
    model = _text(value.get("model"))
    if not 1886 <= year <= 2100 or make is None or model is None:
        return None
    return {
        "year": year,
        "make": make,
        "model": model,
        "trim": _text(value.get("trim")),
        "engine": _text(value.get("engine")),
        "notes": _text(value.get("notes")),
    }


def collect_ebay_compatibility(
    listing_id: str,
    *,
    api_key: str,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Collect fitment rows from a specific eBay listing."""

    if not isinstance(listing_id, str) or not listing_id.strip():
        raise ValueError("listing_id must be a non-empty string")
    listing_id = listing_id.strip()
    timestamp = _retrieved_at(retrieved_at)
    outcome = _base(listing_id, timestamp)
    if not isinstance(api_key, str) or not api_key.strip():
        return _failure(outcome, "BLOCKED_BY_CREDENTIALS", "No SerpApi key supplied")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
        or not math.isfinite(float(timeout_seconds))
    ):
        raise ValueError("timeout_seconds must be a positive number")

    request = SerpApiRequest(_request_url(listing_id, api_key), float(timeout_seconds))
    try:
        response = (
            transport(request)
            if transport is not None
            else perform_async_search(request)
        )
    except (TimeoutError, socket.timeout):
        return _failure(outcome, "TIMEOUT", "SerpApi compatibility search timed out")
    except URLError:
        return _failure(outcome, "HTTP_ERROR", "SerpApi compatibility URL error")
    except Exception:
        return _failure(outcome, "HTTP_ERROR", "SerpApi compatibility request failed")
    if not isinstance(response, SerpApiResponse):
        return _failure(outcome, "PARSER_FAILED", "Unsupported transport response")
    status_error = _http_status(response.status_code)
    if status_error is not None:
        return _failure(outcome, status_error[0], status_error[1])
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _failure(outcome, "PARSER_FAILED", "Response is not valid JSON")
    if not isinstance(payload, Mapping):
        return _failure(outcome, "PARSER_FAILED", "Response root is not an object")
    if "error" in payload:
        return _failure(outcome, "HTTP_ERROR", "SerpApi returned an API error")
    metadata = payload.get("search_metadata")
    if not isinstance(metadata, Mapping) or metadata.get("status") != "Success":
        return _failure(outcome, "PARSER_FAILED", "Search did not confirm Success")
    if not _parameters_match(payload, listing_id):
        return _failure(outcome, "MARKET_CONTEXT_MISMATCH", "Product query mismatch")
    product = payload.get("product_results")
    if not isinstance(product, Mapping) or str(product.get("product_id")) != listing_id:
        return _failure(outcome, "PARSER_FAILED", "Product identity mismatch")
    compatibility = product.get("compatibility")
    items = compatibility.get("items") if isinstance(compatibility, Mapping) else None
    if items is None:
        return _failure(outcome, "NO_COMPATIBILITY", "Listing exposes no compatibility")
    if not isinstance(items, list):
        return _failure(outcome, "PARSER_FAILED", "Compatibility items are malformed")

    fitments: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    skipped = 0
    for item in items:
        normalized = _fitment(item)
        if normalized is None:
            skipped += 1
            continue
        identity = tuple(normalized[key] for key in ("year", "make", "model", "trim", "engine"))
        folded_identity = tuple(
            value.casefold() if isinstance(value, str) else value for value in identity
        )
        if folded_identity in seen:
            continue
        seen.add(folded_identity)
        fitments.append(normalized)
    if not fitments:
        status = "PARSER_FAILED" if items else "NO_COMPATIBILITY"
        return _failure(outcome, status, "No usable compatibility rows")
    outcome["status"] = "PARTIAL_SUCCESS" if skipped else "SUCCESS"
    outcome["fitments"] = fitments
    outcome["fitment_count"] = len(fitments)
    if skipped:
        outcome["diagnostics"] = [
            {"code": "FITMENT_SKIPPED", "message": f"Skipped {skipped} malformed fitment rows"}
        ]
    return outcome


__all__ = ["SERPAPI_EBAY_PRODUCT_PROVIDER", "collect_ebay_compatibility"]
