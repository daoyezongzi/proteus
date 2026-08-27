"""Bounded asynchronous SerpApi submit-and-poll transport."""

from __future__ import annotations

from collections.abc import Callable
import json
import math
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from proteus.providers.serpapi_ebay import (
    SerpApiRequest,
    SerpApiResponse,
    Transport,
    _urllib_transport,
)


def _trusted_serpapi_url(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(
        parsed.scheme.casefold() == "https"
        and parsed.hostname is not None
        and parsed.hostname.rstrip(".").casefold() == "serpapi.com"
        and parsed.username is None
        and parsed.password is None
    )


def _async_submission_url(url: str) -> str:
    if not _trusted_serpapi_url(url):
        raise ValueError("SerpApi submission must use trusted SerpApi HTTPS")
    parsed = urlsplit(url)
    parameters = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"async", "no_cache"}
    ]
    parameters.append(("async", "true"))
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(parameters), parsed.fragment)
    )


def _metadata(response: SerpApiResponse) -> dict[str, Any] | None:
    if not 200 <= response.status_code < 300:
        return None
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("search_metadata")
    return dict(metadata) if isinstance(metadata, dict) else None


def perform_async_search(
    request: SerpApiRequest,
    *,
    transport: Transport | None = None,
    poll_interval_seconds: float = 1.0,
    max_wait_seconds: float = 120.0,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> SerpApiResponse:
    """Submit a SerpApi search asynchronously and return its terminal response."""

    for name, value, allow_zero in (
        ("poll_interval_seconds", poll_interval_seconds, True),
        ("max_wait_seconds", max_wait_seconds, True),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
            or (not allow_zero and value == 0)
        ):
            raise ValueError(f"{name} must be a finite non-negative number")

    active_transport = transport or _urllib_transport
    deadline = monotonic() + float(max_wait_seconds)
    submitted = SerpApiRequest(
        _async_submission_url(request.url), request.timeout_seconds
    )
    response = active_transport(submitted)

    while True:
        metadata = _metadata(response)
        if metadata is None or metadata.get("status") != "Processing":
            return response
        poll_url = metadata.get("json_endpoint")
        if not isinstance(poll_url, str) or not _trusted_serpapi_url(poll_url):
            raise ValueError("SerpApi poll URL must use trusted SerpApi HTTPS")
        if monotonic() >= deadline:
            raise TimeoutError("SerpApi asynchronous search did not finish in time")
        if poll_interval_seconds:
            sleeper(min(float(poll_interval_seconds), max(0.0, deadline - monotonic())))
        if monotonic() >= deadline:
            raise TimeoutError("SerpApi asynchronous search did not finish in time")
        try:
            response = active_transport(
                SerpApiRequest(poll_url, request.timeout_seconds)
            )
        except OSError:
            if monotonic() >= deadline:
                raise TimeoutError(
                    "SerpApi asynchronous search did not finish in time"
                ) from None


__all__ = ["perform_async_search"]
