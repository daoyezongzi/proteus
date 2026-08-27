"""Automatic part-number candidates from fresh eBay Motors sold listings."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import re
import socket
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlencode

from proteus.ebay import parse_condition
from proteus.models import EBAY_US_CONTEXT, SCHEMA_VERSION
from proteus.normalization import normalize_part_number
from proteus.providers.base import (
    DEFAULT_DISCOVERY_KEYWORD as BASE_DEFAULT_DISCOVERY_KEYWORD,
)
from proteus.providers.serpapi_ebay import (
    SEARCH_ENDPOINT,
    SerpApiRequest,
    SerpApiResponse,
    Transport,
    _host_is,
    _http_status,
    _nonempty_string,
    _retrieved_at,
    _sold_count,
    _urllib_transport,
)


SERPAPI_EBAY_DISCOVERY_PROVIDER = "SERPAPI_EBAY_SOLD_DISCOVERY"
SOURCE_METHOD = "MANAGED_API"
DEFAULT_CATEGORY_ID = "6028"
DEFAULT_CATEGORY_NAME = "Auto Parts & Accessories"

# SerpApi's eBay engine will not browse a category alone: category_id with no
# keyword answers every request with "eBay hasn't returned any results for this
# query". A keyword is therefore required, which makes the sample keyword-shaped
# rather than a whole-category sweep. It is a request parameter so the operator
# can see and change what the sample is actually drawn from.
DEFAULT_DISCOVERY_KEYWORD = BASE_DEFAULT_DISCOVERY_KEYWORD

_SEPARATED_PART = re.compile(
    r"(?<![A-Z0-9])([A-Z0-9]{2,8}(?:[-/][A-Z0-9]{2,8}){1,3})(?![A-Z0-9])"
)
_COMPACT_PART = re.compile(
    r"(?<![A-Z0-9])((?=[A-Z0-9]{7,20}(?![A-Z0-9]))(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]+)(?![A-Z0-9])"
)
_NOISE = re.compile(
    r"^(?:19\d{2}|20\d{2}|\d{1,2}V|\dWD|\dX\d|[A-Z]?\d+(?:MM|CM|IN))$",
    re.IGNORECASE,
)

# Fitment year ranges ("2006-2009", "06-09") match the separated-part shape but
# are never part numbers. Each junk token costs a live exact-demand search, so
# reject them before they reach the gate.
_YEAR_RANGE = re.compile(
    r"^(?:19\d{2}|20\d{2})[-/](?:19\d{2}|20\d{2}|\d{2})$"
)

# A token with no digit is a model or trim word ("FLAPS/SPLASH"); real part
# numbers in this corpus always carry one.
_NO_DIGIT = re.compile(r"^[A-Z]+(?:[-/][A-Z]+)*$")

# Model names that carry a digit are shaped exactly like part numbers, so no
# pattern separates them. Only a name list can, and a wrong entry here silently
# hides a real part number, so this stays deliberately short: names seen
# producing junk exact-demand searches, nothing speculative.
_MODEL_NAMES = frozenset({"4RUNNER", "F150", "F250", "F350", "CX5", "CX9", "MX5"})


def extract_part_number_candidates(title: str) -> tuple[str, ...]:
    """Return conservative, ordered title tokens suitable for exact re-checks."""

    if not isinstance(title, str) or not title.strip():
        return ()
    upper = title.upper()
    found: list[tuple[int, str]] = []
    for pattern in (_SEPARATED_PART, _COMPACT_PART):
        for match in pattern.finditer(upper):
            token = match.group(1).strip("-/")
            if (
                _NOISE.fullmatch(token)
                or _YEAR_RANGE.fullmatch(token)
                or _NO_DIGIT.fullmatch(token)
                or token.replace("-", "").replace("/", "") in _MODEL_NAMES
            ):
                continue
            try:
                canonical = normalize_part_number(token)
            except (TypeError, ValueError):
                continue
            if not 6 <= len(canonical) <= 20:
                continue
            if token.isdigit() and "-" not in token and "/" not in token:
                continue
            found.append((match.start(1), token))

    ordered: list[str] = []
    seen: set[str] = set()
    for _position, token in sorted(found, key=lambda item: item[0]):
        canonical = normalize_part_number(token)
        if canonical in seen:
            continue
        seen.add(canonical)
        ordered.append(token)
    return tuple(ordered)


# SerpApi's eBay engine returns zero results for show_only=Sold, so asking for
# it discovered nothing at all. Sold evidence comes from each card's
# quantity_sold label instead, which a plain category search already carries;
# collect_ebay_sold_candidates drops any card lacking it, so dropping the
# parameter cannot admit an unsold listing.
def _request_url(api_key: str, category_id: str, page: int, keyword: str) -> str:
    return f"{SEARCH_ENDPOINT}?{urlencode({
        'engine': 'ebay',
        '_nkw': keyword.strip(),
        'ebay_domain': 'ebay.com',
        'category_id': category_id,
        '_salic': '1',
        '_stpos': '10001',
        'LH_ItemCondition': '1000',
        '_ipg': '50',
        '_pgn': page,
        'no_cache': 'true',
        'output': 'json',
        'api_key': api_key.strip(),
    })}"


def _base(
    category_id: str, retrieved_at: str, page: int, keyword: str
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": SERPAPI_EBAY_DISCOVERY_PROVIDER,
        "source_method": SOURCE_METHOD,
        "category": {"id": category_id, "name": DEFAULT_CATEGORY_NAME},
        # The keyword bounds what this sample could contain, so it travels with
        # the outcome: a caller must be able to see the sample was not the
        # whole category.
        "keyword": keyword,
        "market_context": dict(EBAY_US_CONTEXT),
        "status": "PARSER_FAILED",
        "retrieved_at": retrieved_at,
        "page": page,
        "stats": {
            "results_seen": 0,
            "eligible_sold_listings": 0,
            "listings_with_part_number": 0,
            "candidates_emitted": 0,
        },
        "candidates": [],
        "diagnostics": [],
    }


def _diagnostic(code: str, message: str, marker: Any = None) -> dict[str, Any]:
    raw_marker = None
    if marker is not None:
        raw_marker = re.sub(r"\s+", " ", str(marker)).strip()[:300] or None
    return {"code": code, "message": message, "raw_marker": raw_marker}


def _failure(
    outcome: dict[str, Any], status: str, message: str
) -> dict[str, Any]:
    outcome["status"] = status
    if status != "ZERO_RESULTS":
        outcome["diagnostics"] = [_diagnostic(status, message)]
    return outcome


def _parameters_match(
    payload: Mapping[str, Any], category_id: str, page: int, keyword: str
) -> bool:
    params = payload.get("search_parameters")
    if not isinstance(params, Mapping):
        return False
    expected = {
        "engine": "ebay",
        "_nkw": keyword.strip(),
        "ebay_domain": "ebay.com",
        "category_id": category_id,
        "LH_ItemCondition": "1000",
        "_salic": "1",
        "_stpos": "10001",
        "_pgn": str(page),
    }
    return all(str(params.get(key)) == value for key, value in expected.items())


def collect_ebay_sold_candidates(
    *,
    api_key: str,
    category_id: str = DEFAULT_CATEGORY_ID,
    keyword: str = DEFAULT_DISCOVERY_KEYWORD,
    max_candidates: int = 20,
    page: int = 1,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Discover candidates; every token must still pass the exact-demand gate."""

    if not isinstance(category_id, str) or not category_id.isdigit():
        raise ValueError("category_id must contain digits only")
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("keyword must be a non-empty string")
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int) or max_candidates < 1:
        raise ValueError("max_candidates must be a positive integer")
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be a positive integer")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a positive number")
    if timeout_seconds <= 0 or not math.isfinite(float(timeout_seconds)):
        raise ValueError("timeout_seconds must be a positive number")

    timestamp = _retrieved_at(retrieved_at)
    outcome = _base(category_id, timestamp, page, keyword)
    if not isinstance(api_key, str) or not api_key.strip():
        return _failure(outcome, "BLOCKED_BY_CREDENTIALS", "No SerpApi key was supplied")

    request = SerpApiRequest(
        _request_url(api_key, category_id, page, keyword), float(timeout_seconds)
    )
    try:
        if transport is not None:
            response = transport(request)
        else:
            from proteus.providers.serpapi_transport import perform_async_search

            response = perform_async_search(request)
    except (TimeoutError, socket.timeout):
        return _failure(outcome, "TIMEOUT", "transport timed out")
    except URLError as exc:
        status = "TIMEOUT" if isinstance(exc.reason, (TimeoutError, socket.timeout)) else "HTTP_ERROR"
        return _failure(outcome, status, "transport URL error")
    except Exception:
        return _failure(outcome, "HTTP_ERROR", "transport raised an unexpected exception")

    if not isinstance(response, SerpApiResponse):
        return _failure(outcome, "PARSER_FAILED", "unsupported transport response")
    status_error = _http_status(response.status_code)
    if status_error is not None:
        return _failure(outcome, status_error[0], status_error[1])
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _failure(outcome, "PARSER_FAILED", "response is not valid UTF-8 JSON")
    if not isinstance(payload, Mapping):
        return _failure(outcome, "PARSER_FAILED", "response JSON root is not an object")
    metadata = payload.get("search_metadata")
    if not isinstance(metadata, Mapping):
        return _failure(outcome, "PARSER_FAILED", "search_metadata does not confirm Success")
    if metadata.get("status") != "Success":
        message = (
            "SerpApi returned an API error"
            if "error" in payload
            else "search_metadata does not confirm Success"
        )
        status = "HTTP_ERROR" if "error" in payload else "PARSER_FAILED"
        return _failure(outcome, status, message)
    if not _parameters_match(payload, category_id, page, keyword):
        return _failure(outcome, "MARKET_CONTEXT_MISMATCH", "search parameters do not match the fixed sold category contract")

    # SerpApi documents a top-level error together with metadata.status=Success
    # as a search-engine empty result, not a provider/API failure. Keep the raw
    # provider prose out of the normalized outcome while preserving that
    # semantic distinction for the caller and UI.
    if "error" in payload:
        outcome["status"] = "ZERO_RESULTS"
        return outcome

    results = payload.get("organic_results")
    if not isinstance(results, list):
        return _failure(outcome, "PARSER_FAILED", "organic_results is not an array")
    search_information = payload.get("search_information")
    total = search_information.get("total_results") if isinstance(search_information, Mapping) else None
    if not results:
        if total == 0:
            outcome["status"] = "ZERO_RESULTS"
            return outcome
        return _failure(outcome, "PARSER_FAILED", "empty results lack explicit total_results=0")

    candidates: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen: set[str] = set()
    for position, result in enumerate(results, start=1):
        if len(candidates) >= max_candidates:
            break
        outcome["stats"]["results_seen"] += 1
        if not isinstance(result, Mapping):
            diagnostics.append(_diagnostic("LISTING_SKIPPED", "Result is not an object", position))
            continue
        listing_id = _nonempty_string(result.get("product_id"))
        title = _nonempty_string(result.get("title"))
        raw_url = _nonempty_string(result.get("link"))
        condition = parse_condition(_nonempty_string(result.get("condition")))
        sold_count, sold_label = _sold_count(result)
        if (
            listing_id is None
            or title is None
            or raw_url is None
            or not _host_is(raw_url, "ebay.com")
            or condition != "NEW"
            or sold_count is None
            or sold_count < 1
        ):
            diagnostics.append(
                _diagnostic(
                    "LISTING_SKIPPED",
                    "Listing lacks valid eBay identity, new condition, or explicit sold count",
                    f"position={position}; sold_label={sold_label}",
                )
            )
            continue
        outcome["stats"]["eligible_sold_listings"] += 1
        tokens = extract_part_number_candidates(title)
        if not tokens:
            diagnostics.append(
                _diagnostic(
                    "LISTING_SKIPPED",
                    "Listing title contains no conservative part-number token",
                    f"position={position}; listing_id={listing_id}",
                )
            )
            continue
        outcome["stats"]["listings_with_part_number"] += 1
        listing_url = f"https://www.ebay.com/itm/{quote(listing_id, safe='')}"
        for token in tokens:
            canonical = normalize_part_number(token)
            if canonical in seen:
                diagnostics.append(
                    _diagnostic(
                        "DUPLICATE_CANDIDATE",
                        "Duplicate normalized candidate was ignored",
                        canonical,
                    )
                )
                continue
            seen.add(canonical)
            candidates.append(
                {
                    "raw_part_number": token,
                    "canonical_part_number": canonical,
                    "identifier_type": "partNumber",
                    "source_field": "title",
                    "source_listing_id": listing_id,
                    "source_listing_url": listing_url,
                    "source_listing_title": title,
                    "source_listing_position": position,
                    "source_sold_count": sold_count,
                }
            )
            if len(candidates) >= max_candidates:
                break

    outcome["candidates"] = candidates
    outcome["stats"]["candidates_emitted"] = len(candidates)
    outcome["diagnostics"] = diagnostics
    outcome["status"] = "PARTIAL_SUCCESS" if diagnostics else "SUCCESS"
    return outcome


__all__ = [
    "DEFAULT_CATEGORY_ID",
    "DEFAULT_CATEGORY_NAME",
    "SERPAPI_EBAY_DISCOVERY_PROVIDER",
    "collect_ebay_sold_candidates",
    "extract_part_number_candidates",
]
