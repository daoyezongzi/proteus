"""MarketCheck used-inventory VIN proxy adapter for the automatic MVP."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import math
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from proteus.providers.serpapi_ebay import _read_limited, _retrieved_at


MARKETCHECK_PROVIDER = "MARKETCHECK_US_USED_INVENTORY_PROXY"
INVENTORY_ENDPOINT = "https://api.marketcheck.com/v2/search/car/active"


@dataclass(frozen=True, slots=True)
class HttpRequest:
    url: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


Transport = Callable[[HttpRequest], HttpResponse]


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


def _transport(request: HttpRequest) -> HttpResponse:
    http_request = Request(
        request.url,
        headers={"Accept": "application/json", "User-Agent": "Proteus-MarketCheck/0.2"},
        method="GET",
    )
    try:
        opener = build_opener(_NoRedirectHandler())
        with opener.open(http_request, timeout=request.timeout_seconds) as response:
            return HttpResponse(
                int(response.status), _read_limited(response), dict(response.headers.items())
            )
    except HTTPError as exc:
        return HttpResponse(
            int(exc.code),
            _read_limited(exc),
            dict(exc.headers.items()) if exc.headers is not None else {},
        )


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    result = re.sub(r"\s+", " ", value).strip()
    if not result or any(character in result for character in "|,"):
        return None
    return result


def _ymmt(fitments: Sequence[Mapping[str, Any]]) -> tuple[str, int]:
    values: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for fitment in fitments:
        try:
            year = int(fitment.get("year"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        make = _text(fitment.get("make"))
        model = _text(fitment.get("model"))
        trim = _text(fitment.get("trim"))
        if not 1886 <= year <= 2100 or make is None or model is None or trim is None:
            skipped += 1
            continue
        value = f"{year}|{make}|{model}|{trim}"
        identity = value.casefold()
        if identity not in seen:
            seen.add(identity)
            values.append(value)
    return ",".join(values), skipped


def _base(retrieved_at: str) -> dict[str, Any]:
    return {
        "provider": MARKETCHECK_PROVIDER,
        "status": "PARSER_FAILED",
        "metric": "US_USED_ACTIVE_INVENTORY_DISTINCT_VIN_PROXY",
        "country_code": "US",
        "inventory_type": "used",
        "deduplicated_by_vin": True,
        "fitment_resolution": "YMMT_ONLY",
        "vehicle_count_proxy": None,
        "official_vio": False,
        "retrieved_at": retrieved_at,
        "diagnostics": [],
        "qualification_boundary": (
            "Active used dealer inventory is an observable proxy, not official vehicles-in-operation data."
        ),
    }


def _failure(outcome: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    outcome["status"] = status
    outcome["diagnostics"] = [{"code": status, "message": message}]
    return outcome


def collect_us_used_active_vin_proxy(
    fitments: Sequence[Mapping[str, Any]],
    *,
    api_key: str,
    transport: Transport | None = None,
    timeout_seconds: float = 30.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Count distinct active used-listing VINs matching eBay YMMT fitments."""

    timestamp = _retrieved_at(retrieved_at)
    outcome = _base(timestamp)
    if not isinstance(api_key, str) or not api_key.strip():
        return _failure(outcome, "BLOCKED_BY_CREDENTIALS", "No MarketCheck key supplied")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
        or not math.isfinite(float(timeout_seconds))
    ):
        raise ValueError("timeout_seconds must be a positive number")
    if not isinstance(fitments, Sequence) or isinstance(fitments, (str, bytes)):
        raise ValueError("fitments must be a sequence")
    ymmt, skipped = _ymmt(fitments)
    if not ymmt:
        return _failure(outcome, "NO_FITMENT", "No complete YMMT fitment is available")
    url = f"{INVENTORY_ENDPOINT}?{urlencode({
        'api_key': api_key.strip(),
        'country': 'us',
        'car_type': 'used',
        'ymmt': ymmt,
        'dedup': 'true',
        'rows': '0',
    })}"
    try:
        response = (transport or _transport)(HttpRequest(url, float(timeout_seconds)))
    except (TimeoutError, socket.timeout):
        return _failure(outcome, "TIMEOUT", "MarketCheck request timed out")
    except URLError:
        return _failure(outcome, "HTTP_ERROR", "MarketCheck URL error")
    except Exception:
        return _failure(outcome, "HTTP_ERROR", "MarketCheck request failed")
    if not isinstance(response, HttpResponse):
        return _failure(outcome, "PARSER_FAILED", "Unsupported transport response")
    if not 200 <= response.status_code < 300:
        status = (
            "AUTH_REQUIRED"
            if response.status_code == 401
            else "BLOCKED_BY_CREDENTIALS"
            if response.status_code == 403
            else "HTTP_ERROR"
        )
        return _failure(outcome, status, f"MarketCheck HTTP {response.status_code}")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _failure(outcome, "PARSER_FAILED", "Response is not valid JSON")
    if not isinstance(payload, Mapping):
        return _failure(outcome, "PARSER_FAILED", "Response root is not an object")
    count = payload.get("num_found")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return _failure(outcome, "PARSER_FAILED", "num_found is missing or invalid")
    outcome["status"] = "PARTIAL_SUCCESS" if skipped else "SUCCESS"
    outcome["vehicle_count_proxy"] = count
    outcome["fitment_query_count"] = len(ymmt.split(","))
    if skipped:
        outcome["diagnostics"] = [
            {"code": "FITMENT_SKIPPED", "message": f"Skipped {skipped} incomplete fitment rows"}
        ]
    return outcome


__all__ = [
    "HttpRequest",
    "HttpResponse",
    "MARKETCHECK_PROVIDER",
    "collect_us_used_active_vin_proxy",
]
