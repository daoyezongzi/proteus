"""Anonymous New York registration and NHTSA VIN model proxy.

The NY DMV Socrata dataset has VIN, year and make, but no model field.  This
adapter therefore counts active year/make registrations, samples VINs in a
bounded deterministic way, and uses the anonymous NHTSA vPIC decoder to
estimate the requested year/make/model share.  It is a coverage proxy, not
official nationwide vehicles-in-operation data.
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
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from proteus.providers.serpapi_ebay import _read_limited, _retrieved_at


NY_REGISTRATION_PROVIDER = "NY_DMV_NHTSA_REGISTERED_VEHICLE_PROXY"
NY_DATASET_ENDPOINT = "https://data.ny.gov/resource/w4pv-hbkt.json"
NHTSA_BATCH_ENDPOINT = (
    "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
)
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_SAMPLE_PER_STRATUM = 3
_MIN_USABLE_DECODED = 3
_MAX_FITMENT_GROUPS = 12


@dataclass(frozen=True, slots=True)
class NyRequest:
    url: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class NyResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NhtsaRequest:
    url: str
    body: bytes
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class NhtsaResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


NyTransport = Callable[[NyRequest], NyResponse]
NhtsaTransport = Callable[[NhtsaRequest], NhtsaResponse]


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


def _get_transport(request: NyRequest) -> NyResponse:
    http_request = Request(
        request.url,
        headers={"Accept": "application/json", "User-Agent": "Proteus-NY-Proxy/0.2"},
        method="GET",
    )
    try:
        with build_opener(_NoRedirectHandler()).open(
            http_request, timeout=request.timeout_seconds
        ) as response:
            return NyResponse(
                int(response.status), _read_limited(response), dict(response.headers.items())
            )
    except HTTPError as exc:
        return NyResponse(
            int(exc.code), _read_limited(exc), dict(exc.headers.items()) if exc.headers else {}
        )


def _post_transport(request: NhtsaRequest) -> NhtsaResponse:
    http_request = Request(
        request.url,
        data=request.body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Proteus-NHTSA-Proxy/0.2",
        },
        method="POST",
    )
    try:
        with build_opener(_NoRedirectHandler()).open(
            http_request, timeout=request.timeout_seconds
        ) as response:
            return NhtsaResponse(
                int(response.status), _read_limited(response), dict(response.headers.items())
            )
    except HTTPError as exc:
        return NhtsaResponse(
            int(exc.code), _read_limited(exc), dict(exc.headers.items()) if exc.headers else {}
        )


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"\s+", " ", value).strip()
    return normalized or None


def _identity(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    return re.sub(r"[^a-z0-9]", "", text.casefold()) or None


def _make_code(value: str) -> str:
    """Map common eBay/NHTSA makes to NY DMV's compact make code."""

    aliases = {
        "TOYOTA": "TOYOT",
        "LEXUS": "LEXUS",
        "HONDA": "HOND",
        "FORD": "FORD",
        "CHEVROLET": "CHEVR",
        "CHEVY": "CHEVR",
        "NISSAN": "NISSA",
        "INFINITI": "INFIN",
        "SUBARU": "SUBAR",
        "BMW": "BMW",
        "VOLKSWAGEN": "VOLKS",
        "VOLVO": "VOLVO",
        "HYUNDAI": "HYUND",
        "KIA": "KIA",
        "MAZDA": "MAZDA",
        "MERCEDES-BENZ": "MERCE",
        "MERCEDES": "MERCE",
        "JEEP": "JEEP",
        "DODGE": "DODGE",
        "RAM": "RAM",
    }
    normalized = re.sub(r"[^A-Z0-9-]", "", value.upper())
    return aliases.get(normalized, normalized[:5])


def _base(timestamp: str) -> dict[str, Any]:
    return {
        "provider": NY_REGISTRATION_PROVIDER,
        "status": "PARSER_FAILED",
        "metric": "NY_REGISTERED_VEHICLE_MODEL_ESTIMATE_PROXY",
        "country_code": "US",
        "state_code": "NY",
        "inventory_type": "registered",
        "deduplicated_by_vin": True,
        "fitment_resolution": "YEAR_MAKE_MODEL_SAMPLED",
        "vehicle_count_proxy": None,
        "official_vio": False,
        "sampling_randomized": False,
        "sampling_method": "bounded_fixed_offsets_without_order",
        "retrieved_at": timestamp,
        "diagnostics": [],
        "groups": [],
        "qualification_boundary": (
            "This is a deterministic New York active-registration model estimate, "
            "not nationwide official vehicles-in-operation data; trim and engine "
            "compatibility still require human review. No formal confidence interval "
            "is claimed for the systematic sample."
        ),
    }


def _failure(outcome: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    outcome["status"] = status
    outcome["diagnostics"] = [{"code": status, "message": message}]
    return outcome


def _valid_timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or value <= 0
        or not math.isfinite(float(value))
    ):
        raise ValueError("timeout_seconds must be a positive number")
    return float(value)


def _active_date(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()


def _fitment_groups(fitments: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    groups: dict[tuple[int, str, str], dict[str, Any]] = {}
    skipped = 0
    for fitment in fitments:
        if not isinstance(fitment, Mapping):
            skipped += 1
            continue
        try:
            year = int(fitment.get("year"))
        except (TypeError, ValueError):
            skipped += 1
            continue
        make = _text(fitment.get("make"))
        model = _text(fitment.get("model"))
        make_key = _identity(make)
        model_key = _identity(model)
        if not 1886 <= year <= 2100 or make is None or model is None or not make_key or not model_key:
            skipped += 1
            continue
        key = (year, make_key, model_key)
        groups.setdefault(
            key,
            {
                "year": year,
                "make": make,
                "model": model,
                "make_key": make_key,
                "model_key": model_key,
                "ny_make": _make_code(make),
            },
        )
    return list(groups.values()), skipped


def _query_url(select: str, where: str, *, order: str | None = None, limit: int | None = None, offset: int | None = None) -> str:
    params: dict[str, str] = {"$select": select, "$where": where}
    if order is not None:
        params["$order"] = order
    if limit is not None:
        params["$limit"] = str(limit)
    if offset is not None:
        params["$offset"] = str(offset)
    return f"{NY_DATASET_ENDPOINT}?{urlencode(params)}"


def _json_response(response: NyResponse | NhtsaResponse) -> Any:
    return json.loads(response.body.decode("utf-8"))


def _count(
    group: Mapping[str, Any], active_date: str, transport: NyTransport, timeout: float
) -> tuple[int | None, str | None]:
    where = (
        "record_type='VEH' AND model_year={year} AND make='{make}' "
        "AND reg_expiration_date >= '{date}T00:00:00.000' AND vin IS NOT NULL"
    ).format(year=group["year"], make=group["ny_make"], date=active_date)
    try:
        response = transport(NyRequest(_query_url("count(distinct vin) as registrations", where), timeout))
        if not 200 <= response.status_code < 300:
            return None, f"NY DMV HTTP {response.status_code}"
        payload = _json_response(response)
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], Mapping):
            return None, "NY DMV count response is malformed"
        value = payload[0].get("registrations")
        parsed = int(value) if isinstance(value, (int, str)) and str(value).isdigit() else None
        return (parsed, None) if parsed is not None and parsed >= 0 else (None, "NY DMV count is invalid")
    except (TimeoutError, socket.timeout):
        return None, "NY DMV count timed out"
    except (URLError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None, "NY DMV count request failed"


def _sample(
    group: Mapping[str, Any], total: int, transport: NyTransport, timeout: float
) -> tuple[list[str], str | None]:
    if total <= 0:
        return [], None
    limit = _SAMPLE_PER_STRATUM
    offsets = sorted({0, max(0, total // 2 - limit // 2), max(0, total - limit)})
    vins: list[str] = []
    seen: set[str] = set()
    where = (
        "record_type='VEH' AND model_year={year} AND make='{make}' "
        "AND reg_expiration_date >= '{date}T00:00:00.000' AND vin IS NOT NULL"
    )
    # The date is embedded by the caller in group to keep every sample query identical.
    where = where.format(year=group["year"], make=group["ny_make"], date=group["active_date"])
    for offset in offsets:
        try:
            response = transport(
                NyRequest(
                    _query_url("vin", where, limit=limit, offset=offset),
                    timeout,
                )
            )
            if not 200 <= response.status_code < 300:
                return vins, f"NY DMV sample HTTP {response.status_code}"
            payload = _json_response(response)
            if not isinstance(payload, list):
                return vins, "NY DMV sample response is malformed"
            for row in payload:
                value = row.get("vin") if isinstance(row, Mapping) else None
                if isinstance(value, str) and value.strip() and value.strip() not in seen:
                    seen.add(value.strip())
                    vins.append(value.strip())
        except (TimeoutError, socket.timeout):
            return vins, "NY DMV sample timed out"
        except (URLError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return vins, "NY DMV sample request failed"
    return vins, None


def _decode(
    vins: Sequence[str],
    *,
    model_year: int,
    nhtsa_transport: NhtsaTransport,
    timeout: float,
) -> tuple[list[dict[str, Any]], str | None]:
    if not vins:
        return [], None
    chunks = [vins[index : index + 25] for index in range(0, len(vins), 25)]
    decoded: list[dict[str, Any]] = []
    for chunk in chunks:
        body = urlencode(
            {"format": "json", "data": ";".join(f"{vin},{model_year}" for vin in chunk)}
        ).encode()
        try:
            response = nhtsa_transport(NhtsaRequest(NHTSA_BATCH_ENDPOINT, body, timeout))
            if not 200 <= response.status_code < 300:
                return decoded, f"NHTSA HTTP {response.status_code}"
            payload = _json_response(response)
            rows = payload.get("Results") if isinstance(payload, Mapping) else None
            if not isinstance(rows, list):
                return decoded, "NHTSA response is malformed"
            decoded.extend(row for row in rows if isinstance(row, Mapping))
        except (TimeoutError, socket.timeout):
            return decoded, "NHTSA batch timed out"
        except (URLError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return decoded, "NHTSA batch request failed"
    return decoded, None


def _decoded_fields(row: Mapping[str, Any]) -> tuple[int | None, str | None, str | None]:
    try:
        year = int(row.get("ModelYear") or row.get("Model Year"))
    except (TypeError, ValueError):
        year = None
    make = _identity(row.get("Make"))
    model = _identity(row.get("Model"))
    return year, make, model


def collect_ny_registered_vehicle_proxy(
    fitments: Sequence[Mapping[str, Any]],
    *,
    transport: NyTransport | None = None,
    nhtsa_transport: NhtsaTransport | None = None,
    timeout_seconds: float = 20.0,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Estimate NY active registrations for eBay year/make/model fitments."""

    timestamp = _retrieved_at(retrieved_at)
    outcome = _base(timestamp)
    timeout = _valid_timeout(timeout_seconds)
    if not isinstance(fitments, Sequence) or isinstance(fitments, (str, bytes)):
        raise ValueError("fitments must be a sequence")
    groups, skipped = _fitment_groups(fitments)
    if not groups:
        return _failure(outcome, "NO_FITMENT", "No valid year/make/model fitment is available")
    groups_truncated = len(groups) > _MAX_FITMENT_GROUPS
    groups = groups[:_MAX_FITMENT_GROUPS]
    ny_transport = transport or _get_transport
    decode_transport = nhtsa_transport or _post_transport
    active_date = _active_date(timestamp)
    all_complete = skipped == 0 and not groups_truncated
    total_estimate = 0
    diagnostics: list[dict[str, str]] = []
    if groups_truncated:
        diagnostics.append(
            {
                "code": "FITMENT_GROUP_LIMIT",
                "message": f"Only the first {_MAX_FITMENT_GROUPS} normalized fitment groups were sampled",
            }
        )
    by_year_make: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for group in groups:
        by_year_make.setdefault((group["year"], group["make_key"]), []).append(group)

    for targets in by_year_make.values():
        base_group = dict(targets[0])
        base_group["active_date"] = active_date
        total, count_error = _count(base_group, active_date, ny_transport, timeout)
        if count_error is not None or total is None:
            all_complete = False
            diagnostics.append(
                {"code": "COUNT_INCOMPLETE", "message": count_error or "NY DMV count unavailable"}
            )
            for group in targets:
                outcome["groups"].append(
                    {
                        "year": group["year"],
                        "make": group["make"],
                        "model": group["model"],
                        "status": "INCOMPLETE",
                    }
                )
            continue
        if total == 0:
            for group in targets:
                outcome["groups"].append(
                    {
                        "year": group["year"],
                        "make": group["make"],
                        "model": group["model"],
                        "status": "SUCCESS",
                        "year_make_registration_total": 0,
                        "sample_requested": 0,
                        "sample_returned": 0,
                        "usable_decoded": 0,
                        "matched_model_decoded": 0,
                        "estimated_model_registrations": 0,
                    }
                )
            continue

        vins, sample_error = _sample(base_group, total, ny_transport, timeout)
        decoded, decode_error = _decode(
            vins,
            model_year=base_group["year"],
            nhtsa_transport=decode_transport,
            timeout=timeout,
        )
        usable = 0
        matches: dict[str, int] = {group["model_key"]: 0 for group in targets}
        for row in decoded:
            year, make, model = _decoded_fields(row)
            if year is None or make is None or model is None:
                continue
            usable += 1
            if year == base_group["year"] and make == base_group["make_key"]:
                if model in matches:
                    matches[model] += 1
        complete_sample = (
            sample_error is None
            and decode_error is None
            and len(vins) >= _MIN_USABLE_DECODED
            and usable >= _MIN_USABLE_DECODED
        )
        if not complete_sample:
            all_complete = False
            diagnostics.append(
                {
                    "code": "SAMPLE_INCOMPLETE",
                    "message": sample_error
                    or decode_error
                    or "Insufficient usable NHTSA decodes",
                }
            )
        sample_requested = len(
            {
                0,
                max(0, total // 2 - _SAMPLE_PER_STRATUM // 2),
                max(0, total - _SAMPLE_PER_STRATUM),
            }
        ) * _SAMPLE_PER_STRATUM
        for group in targets:
            matched = matches[group["model_key"]]
            estimate = math.floor(total * matched / usable) if usable else None
            if estimate is not None:
                total_estimate += estimate
            outcome["groups"].append(
                {
                    "year": group["year"],
                    "make": group["make"],
                    "model": group["model"],
                    "status": "SUCCESS" if complete_sample else "INCOMPLETE",
                    "year_make_registration_total": total,
                    "sample_requested": sample_requested,
                    "sample_returned": len(vins),
                    "usable_decoded": usable,
                    "matched_model_decoded": matched,
                    "estimated_model_registrations": estimate,
                }
            )
    if skipped:
        diagnostics.append({"code": "FITMENT_SKIPPED", "message": f"Skipped {skipped} invalid fitment rows"})
    outcome["diagnostics"] = diagnostics
    outcome["vehicle_count_proxy"] = total_estimate if all_complete else None
    outcome["status"] = "SUCCESS" if all_complete else "PARTIAL_SUCCESS"
    return outcome


__all__ = [
    "NHTSA_BATCH_ENDPOINT",
    "NY_DATASET_ENDPOINT",
    "NY_REGISTRATION_PROVIDER",
    "NhtsaRequest",
    "NhtsaResponse",
    "NyRequest",
    "NyResponse",
    "collect_ny_registered_vehicle_proxy",
]
