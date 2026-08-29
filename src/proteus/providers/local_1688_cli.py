"""Read-only adapter for the locally installed ``1688`` CLI.

The adapter deliberately stays on the sourcing side of the buyer journey:
one shallow keyword search, followed by at most one offer-detail read when a
search card does not expose the supplier.  It never invokes ``--deeppro``,
seller messaging, cart, checkout, or order commands.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import json
import os
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import urlparse


LOCAL_1688_CLI_PROVIDER = "LOCAL_1688_CLI"
SOURCE_METHOD = "LOCAL_CLI"
DEFAULT_EXECUTABLE = "1688"

CommandRunner = Callable[[Sequence[str], float], tuple[int, str, str]]

_PART_KEYWORDS = {
    "fog light bezel": "雾灯框",
    "tow hook cover": "拖车钩盖",
    "bumper reflector": "保险杠反光片",
    "headlight washer cover": "大灯清洗盖",
    "lower air deflector": "下导流板",
    "hood latch release cable": "发动机盖锁拉线",
    "accelerator cable": "油门拉线",
    "door handle bowden cable": "车门拉线",
    "transmission shift control cable": "换挡拉线",
}

_PART_ALIASES = {
    "fog light bezel": ("fog light bezel", "fog lamp bezel", "fog light cover", "雾灯框", "雾灯罩"),
    "tow hook cover": ("tow hook cover", "tow eye cover", "拖车钩盖", "牵引钩盖"),
    "bumper reflector": ("bumper reflector", "rear reflector", "保险杠反光片"),
    "headlight washer cover": ("headlight washer cover", "headlamp washer cover", "大灯清洗盖"),
    "lower air deflector": ("lower air deflector", "lower splash shield", "下导流板"),
    "hood latch release cable": ("hood latch release cable", "hood release cable", "发动机盖锁拉线"),
    "accelerator cable": ("accelerator cable", "throttle cable", "油门拉线"),
    "door handle bowden cable": ("door handle bowden cable", "door handle cable", "车门拉线"),
    "transmission shift control cable": ("transmission shift control cable", "shift control cable", "换挡拉线"),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def is_real_1688_url(value: Any) -> bool:
    raw_url = _text(value)
    if not raw_url:
        return False
    parsed = urlparse(raw_url)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (hostname == "1688.com" or hostname.endswith(".1688.com"))
    )


def is_1688_cli_available(executable: str = DEFAULT_EXECUTABLE) -> bool:
    """Return only executable presence; do not launch Chrome during readiness."""

    return bool(_text(executable) and shutil.which(executable))


def is_valid_1688_offer_id(value: Any) -> bool:
    """Accept the opaque offer identifiers emitted by 1688 CLI/API adapters."""

    return bool(re.fullmatch(r"[A-Za-z0-9_-]{4,80}", _text(value)))


def _default_command_runner(
    argv: Sequence[str], timeout_seconds: float
) -> tuple[int, str, str]:
    command = list(argv)
    if os.name == "nt":
        resolved = shutil.which(command[0])
        if resolved and resolved.casefold().endswith((".cmd", ".bat")):
            command = [
                os.environ.get("ComSpec", "cmd.exe"),
                "/d",
                "/c",
                resolved,
                *command[1:],
            ]
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=timeout_seconds,
    )
    return int(completed.returncode), completed.stdout or "", completed.stderr or ""


def _parse_json(stdout: str) -> Any | None:
    raw = stdout.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
            except json.JSONDecodeError:
                continue
            return value
    return None


def is_1688_cli_authenticated(
    executable: str = DEFAULT_EXECUTABLE,
    *,
    profile: str = "default",
    timeout_seconds: float = 8.0,
    command_runner: CommandRunner | None = None,
) -> bool:
    """Check the local profile with ``whoami`` without opening a browser."""

    if not _text(executable) or not _text(profile):
        return False
    if command_runner is None and not is_1688_cli_available(executable):
        return False
    runner = command_runner or _default_command_runner
    try:
        return_code, stdout, _stderr = runner(
            [executable, "whoami", "--profile", profile, "--json"],
            float(timeout_seconds),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError, OSError):
        return False
    if return_code != 0:
        return False
    payload = _parse_json(stdout)
    return isinstance(payload, Mapping) and payload.get("loggedIn") is True


def _walk_offer_records(value: Any, *, depth: int = 0) -> list[Mapping[str, Any]]:
    if depth > 5:
        return []
    if isinstance(value, list):
        records: list[Mapping[str, Any]] = []
        for item in value:
            records.extend(_walk_offer_records(item, depth=depth + 1))
        return records
    if not isinstance(value, Mapping):
        return []

    identity_keys = {
        "id",
        "offerId",
        "offer_id",
        "productId",
        "product_id",
        "title",
        "subject",
        "detailUrl",
        "detail_url",
        "offerUrl",
        "offer_url",
    }
    if any(key in value for key in identity_keys):
        return [value]

    records: list[Mapping[str, Any]] = []
    for key in ("offers", "items", "products", "results", "data", "offer", "product"):
        child = value.get(key)
        if child is not None:
            records.extend(_walk_offer_records(child, depth=depth + 1))
    return records


def _first_value(record: Mapping[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _supplier(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        nested = value.get("supplier") or value.get("seller") or value.get("company")
        if isinstance(nested, Mapping):
            value = nested
        name = _text(
            _first_value(
                value,
                ("name", "companyName", "company_name", "shopName", "shop_name", "sellerName"),
            )
        )
        supplier_id = _text(_first_value(value, ("id", "memberId", "member_id", "sellerId", "seller_id")))
        shop_name = _text(_first_value(value, ("shopName", "shop_name", "storeName", "store_name")))
        url = _text(_first_value(value, ("url", "shopUrl", "shop_url", "homepage", "link")))
        if not any((name, supplier_id, shop_name, url)):
            return None
        result: dict[str, Any] = {}
        if supplier_id:
            result["id"] = supplier_id
        if name:
            result["name"] = name
        if shop_name:
            result["shop_name"] = shop_name
        if url and is_real_1688_url(url):
            result["url"] = url
        return result or None
    name = _text(value)
    return {"name": name} if name else None


def _offer_id(record: Mapping[str, Any], url: str) -> str:
    value = _text(
        _first_value(
            record,
            ("offerId", "offer_id", "id", "productId", "product_id", "source_product_id"),
        )
    )
    if value:
        return value
    match = re.search(r"/offer/(\d+)(?:\.html)?", url, re.IGNORECASE)
    return match.group(1) if match else ""


def _normalized_offer(record: Mapping[str, Any]) -> dict[str, Any]:
    url = _text(
        _first_value(
            record,
            ("offerUrl", "offer_url", "detailUrl", "detail_url", "source_url", "url", "link"),
        )
    )
    if url.startswith("//"):
        url = f"https:{url}"
    supplier_value = _first_value(
        record,
        ("supplier", "seller", "company", "shop", "merchant", "supplierInfo", "supplier_info"),
    )
    title = _text(_first_value(record, ("title", "subject", "name", "productName", "product_name")))
    result: dict[str, Any] = {
        "offer_id": _offer_id(record, url),
        "title": title,
        "offer_url": url,
        "supplier": _supplier(supplier_value),
    }
    for key in ("price_cny", "price", "moq", "minOrderQuantity", "min_order_quantity"):
        if key in record:
            result[key] = record[key]
    return result


def build_1688_query_pack(
    family: Mapping[str, Any] | None,
    raw_part_number: str,
) -> list[str]:
    """Build a short exact-first query pack for one product family."""

    queries: list[str] = []

    def add(value: str) -> None:
        clean = _text(value)
        if clean and clean.casefold() not in {query.casefold() for query in queries}:
            queries.append(clean)

    add(raw_part_number)
    part_type = _text(family.get("part_type")) if isinstance(family, Mapping) else ""
    configured_keywords = (
        [
            _text(value)
            for value in family.get("supply_keywords", [])
            if _text(value)
        ]
        if isinstance(family, Mapping)
        and isinstance(family.get("supply_keywords"), Sequence)
        and not isinstance(family.get("supply_keywords"), (str, bytes))
        else []
    )
    part_keywords = configured_keywords or [
        _PART_KEYWORDS.get(part_type.casefold(), part_type)
    ]
    part_keyword = part_keywords[0]
    fitment = None
    if isinstance(family, Mapping) and isinstance(family.get("fitments"), list):
        for item in family["fitments"][:1]:
            if isinstance(item, Mapping):
                make = _text(item.get("make"))
                model = _text(item.get("model"))
                if make or model:
                    fitment = " ".join(part for part in (make, model) if part)
                    break
    if fitment:
        add(f"{fitment} {part_keyword}")
    for keyword in part_keywords:
        add(keyword)
    return queries[:3]


def _title_matches(
    title: str,
    *,
    raw_part_number: str,
    family: Mapping[str, Any] | None,
) -> bool:
    folded = title.casefold()
    canonical_identifier = re.sub(r"[^a-z0-9]", "", raw_part_number.casefold())
    canonical_title = re.sub(r"[^a-z0-9]", "", folded)
    if canonical_identifier and canonical_identifier in canonical_title:
        return True
    part_type = _text(family.get("part_type")) if isinstance(family, Mapping) else ""
    configured_aliases: list[str] = []
    if isinstance(family, Mapping):
        for key in ("supply_aliases", "category_aliases"):
            values = family.get(key)
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                configured_aliases.extend(_text(value) for value in values if _text(value))
    aliases = configured_aliases or list(
        _PART_ALIASES.get(part_type.casefold(), (part_type,))
    )
    return any(alias.casefold() in folded for alias in aliases if alias)


def _result_base(raw_part_number: str) -> dict[str, Any]:
    return {
        "provider": LOCAL_1688_CLI_PROVIDER,
        "source_method": SOURCE_METHOD,
        "acquisition_status": "NOT_CONFIGURED",
        "query": None,
        "searched_queries": [],
        "offer_id": None,
        "offer_url": None,
        "title": None,
        "supplier": None,
        "supplier_found": False,
        "matched_part_numbers": [],
        "match_type": None,
        "retrieved_at": _utc_now(),
        "diagnostics": [],
        "raw_part_number": raw_part_number,
    }


def _diagnostic(code: str, message: str) -> list[dict[str, str]]:
    return [{"code": code, "message": message}]


def _failure_status(stderr: str) -> tuple[str, str, str]:
    folded = stderr.casefold()
    if any(term in folded for term in ("risk_control", "captcha", "challenge", "verification")):
        return "RISK_CONTROL", "1688_CLI_RISK_CONTROL", "1688 returned a verification or risk-control challenge."
    if any(term in folded for term in ("login", "not logged", "unauthorized", "未登录")):
        return "AUTH_REQUIRED", "1688_CLI_AUTH_REQUIRED", "The local 1688 profile is not authenticated."
    return "CLI_ERROR", "1688_CLI_COMMAND_FAILED", "The local 1688 read-only command failed."


def collect_1688_supplier(
    raw_part_number: str,
    *,
    family: Mapping[str, Any] | None = None,
    executable: str = DEFAULT_EXECUTABLE,
    max_offers: int = 5,
    timeout_seconds: float = 45.0,
    command_runner: CommandRunner | None = None,
) -> Mapping[str, Any]:
    """Find one family-matching 1688 offer with a supplier identity.

    The per-family budget is enforced by the Northway runner. This function
    itself stays shallow so a single family never turns into a bulk crawl.
    """

    outcome = _result_base(raw_part_number)
    if not isinstance(raw_part_number, str) or not raw_part_number.strip():
        outcome["acquisition_status"] = "PARSER_FAILED"
        outcome["diagnostics"] = _diagnostic("1688_PART_NUMBER_MISSING", "A non-empty part number is required.")
        return outcome
    if isinstance(max_offers, bool) or not isinstance(max_offers, int) or not 1 <= max_offers <= 10:
        raise ValueError("max_offers must be between 1 and 10")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if not _text(executable):
        outcome["diagnostics"] = _diagnostic("1688_CLI_EXECUTABLE_MISSING", "The local 1688 executable is not configured.")
        return outcome
    if command_runner is None and not is_1688_cli_available(executable):
        outcome["diagnostics"] = _diagnostic("1688_CLI_NOT_FOUND", "Install 1688 CLI and log in before running supplier filtering.")
        return outcome

    runner = command_runner or _default_command_runner
    queries = build_1688_query_pack(family, raw_part_number.strip())
    outcome["searched_queries"] = queries
    last_search_record: dict[str, Any] | None = None
    for query in queries:
        outcome["query"] = query
        try:
            return_code, stdout, stderr = runner(
                [executable, "search", query, "--max", str(max_offers), "--json", "--pretty"],
                float(timeout_seconds),
            )
        except subprocess.TimeoutExpired:
            outcome["acquisition_status"] = "TIMEOUT"
            outcome["diagnostics"] = _diagnostic("1688_CLI_TIMEOUT", "The local 1688 search exceeded its read-only timeout.")
            return outcome
        except (FileNotFoundError, PermissionError):
            outcome["diagnostics"] = _diagnostic("1688_CLI_NOT_FOUND", "The local 1688 executable could not be started.")
            return outcome
        except OSError:
            outcome["acquisition_status"] = "CLI_ERROR"
            outcome["diagnostics"] = _diagnostic("1688_CLI_START_FAILED", "The local 1688 command could not be started.")
            return outcome
        if return_code != 0:
            status, code, message = _failure_status(stderr)
            outcome["acquisition_status"] = status
            outcome["diagnostics"] = _diagnostic(code, message)
            return outcome
        payload = _parse_json(stdout)
        if payload is None:
            outcome["acquisition_status"] = "PARSER_FAILED"
            outcome["diagnostics"] = _diagnostic("1688_CLI_JSON_INVALID", "The local 1688 search did not return valid JSON.")
            return outcome
        records = _walk_offer_records(payload)
        if not records:
            continue
        for record in records:
            normalized = _normalized_offer(record)
            if not _title_matches(
                normalized["title"],
                raw_part_number=raw_part_number,
                family=family,
            ):
                continue
            if not last_search_record:
                last_search_record = normalized
            if is_valid_1688_offer_id(normalized.get("offer_id")) and is_real_1688_url(normalized.get("offer_url")) and normalized.get("supplier"):
                normalized["supplier_found"] = True
                normalized["acquisition_status"] = "SUCCESS"
                normalized["provider"] = LOCAL_1688_CLI_PROVIDER
                normalized["source_method"] = SOURCE_METHOD
                normalized["query"] = query
                normalized["searched_queries"] = queries
                normalized["matched_part_numbers"] = [raw_part_number.strip()]
                normalized["match_type"] = "IDENTIFIER_OR_FAMILY_MATCH"
                normalized["retrieved_at"] = outcome["retrieved_at"]
                normalized["diagnostics"] = []
                return normalized

        if last_search_record and is_valid_1688_offer_id(last_search_record.get("offer_id")):
            break

    if last_search_record and is_valid_1688_offer_id(last_search_record.get("offer_id")):
        outcome.update(last_search_record)
        offer_id = _text(last_search_record.get("offer_id"))
        try:
            return_code, stdout, stderr = runner(
                [executable, "offer", offer_id, "--json", "--pretty"],
                float(timeout_seconds),
            )
        except subprocess.TimeoutExpired:
            outcome["acquisition_status"] = "TIMEOUT"
            outcome["diagnostics"] = _diagnostic("1688_CLI_TIMEOUT", "The local 1688 offer read exceeded its read-only timeout.")
            return outcome
        except (FileNotFoundError, PermissionError, OSError):
            outcome["acquisition_status"] = "CLI_ERROR"
            outcome["diagnostics"] = _diagnostic("1688_CLI_OFFER_FAILED", "The local 1688 offer detail could not be read.")
            return outcome
        if return_code != 0:
            status, code, message = _failure_status(stderr)
            outcome["acquisition_status"] = status
            outcome["diagnostics"] = _diagnostic(code, message)
            return outcome
        detail_payload = _parse_json(stdout)
        detail_records = _walk_offer_records(detail_payload)
        if detail_records:
            detail = _normalized_offer(detail_records[0])
            merged = {**outcome, **{key: value for key, value in detail.items() if value not in (None, "", {})}}
            if not merged.get("title"):
                merged["title"] = outcome.get("title")
            if not merged.get("offer_url"):
                merged["offer_url"] = outcome.get("offer_url")
            if not merged.get("offer_id"):
                merged["offer_id"] = offer_id
            if not merged.get("supplier"):
                merged["supplier"] = outcome.get("supplier")
            if _title_matches(
                _text(merged.get("title")),
                raw_part_number=raw_part_number,
                family=family,
            ) and is_valid_1688_offer_id(merged.get("offer_id")) and is_real_1688_url(merged.get("offer_url")) and merged.get("supplier"):
                merged["supplier_found"] = True
                merged["acquisition_status"] = "SUCCESS"
                merged["provider"] = LOCAL_1688_CLI_PROVIDER
                merged["source_method"] = SOURCE_METHOD
                merged["matched_part_numbers"] = [raw_part_number.strip()]
                merged["match_type"] = "IDENTIFIER_OR_FAMILY_MATCH"
                merged["diagnostics"] = []
                return merged

    outcome["acquisition_status"] = "ZERO_RESULTS" if not last_search_record else "SUCCESS"
    outcome["supplier_found"] = False
    outcome["diagnostics"] = _diagnostic(
        "1688_NO_SUPPLIER_FOUND" if last_search_record else "1688_ZERO_RESULTS",
        "No family-matching 1688 offer with a supplier identity was found.",
    )
    return outcome


__all__ = [
    "DEFAULT_EXECUTABLE",
    "LOCAL_1688_CLI_PROVIDER",
    "SOURCE_METHOD",
    "build_1688_query_pack",
    "collect_1688_supplier",
    "is_1688_cli_available",
    "is_1688_cli_authenticated",
    "is_valid_1688_offer_id",
    "is_real_1688_url",
]
