"""Bounded, read-only collection of one 1688 supplier's store offers.

The installed ``1688-cli`` does not currently expose a store-catalog command.
This adapter therefore launches a small, version-gated Node bridge that reuses
the CLI's persistent browser profile without reading or exporting cookies.  A
challenge, login redirect, parser failure, or page/offer bound is evidence in
its own right and is never converted into a genuine empty-store result.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import urlparse, urlunparse


LOCAL_1688_STORE_PROVIDER = "LOCAL_1688_STORE_BRIDGE"
SOURCE_METHOD = "AUTHENTICATED_BROWSER_DOM"
SUPPORTED_CLI_VERSION = "0.1.47"
DEFAULT_EXECUTABLE = "node"

CommandRunner = Callable[[Sequence[str], float], tuple[int, str, str]]

_STATUSES = {
    "SUCCESS",
    "EMPTY",
    "PARTIAL",
    "AUTH_REQUIRED",
    "RISK_CONTROL",
    "TIMEOUT",
    "PARSER_FAILED",
    "CLI_ERROR",
    "NOT_CONFIGURED",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _url_segments(value: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"https?://", value, re.I)]
    if not starts:
        return []
    segments: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(value)
        segment = value[start:end].strip().rstrip(".,;'”’>)]}")
        # Markdown link text commonly ends immediately before ](.
        segment = re.split(r"\]\(", segment, maxsplit=1)[0]
        if segment:
            segments.append(segment)
    return segments


def _canonical_1688_url(raw_url: str) -> dict[str, str]:
    parsed = urlparse(raw_url)
    host = (parsed.hostname or "").rstrip(".").casefold()
    if parsed.scheme.casefold() != "https":
        raise ValueError("supplier target must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("supplier target must not contain embedded credentials")
    if not (host == "1688.com" or host.endswith(".1688.com")):
        raise ValueError("supplier target must be on 1688.com")
    if parsed.port not in (None, 443):
        raise ValueError("supplier target must use the standard HTTPS port")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    offer_match = re.fullmatch(r"/offer/(\d+)(?:\.html)?/?", path, re.I)
    if offer_match:
        canonical_path = f"/offer/{offer_match.group(1)}.html"
        target_type = "OFFER"
    elif path.casefold().rstrip("/") == "/page/offerlist.htm":
        canonical_path = "/page/offerlist.htm"
        target_type = "STORE_OFFER_LIST"
    else:
        canonical_path = path.rstrip("/") or "/"
        target_type = "STORE"
    canonical = urlunparse(("https", host, canonical_path, "", "", ""))
    return {
        "canonical_url": canonical,
        "shop_host": host,
        "target_type": target_type,
    }


def normalize_1688_supplier_target(value: str) -> dict[str, str]:
    """Normalize exactly one 1688 source, accepting an identical pasted repeat."""

    submitted = _text(value)
    if not submitted:
        raise ValueError("supplier target must be a non-empty 1688 URL")
    urls = _url_segments(submitted)
    if not urls:
        raise ValueError("supplier target must contain an HTTPS 1688 URL")
    normalized = [_canonical_1688_url(item) for item in urls]
    unique = {item["canonical_url"] for item in normalized}
    if len(unique) != 1:
        raise ValueError("supplier target must resolve to exactly one 1688 source")
    result = dict(normalized[0])
    result["submitted_target"] = submitted
    return result


def normalize_1688_supplier_store_target(value: str) -> dict[str, str]:
    """Require the one source shape the bounded store collector can prove."""

    normalized = normalize_1688_supplier_target(value)
    if (
        normalized["target_type"] != "STORE_OFFER_LIST"
        or normalized["shop_host"] in {"1688.com", "www.1688.com", "detail.1688.com"}
    ):
        raise ValueError(
            "store collection requires one supplier subdomain /page/offerlist.htm URL"
        )
    return normalized


def _default_command_runner(
    argv: Sequence[str], timeout_seconds: float
) -> tuple[int, str, str]:
    completed = subprocess.run(
        list(argv),
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        shell=False,
        timeout=timeout_seconds,
    )
    return int(completed.returncode), completed.stdout or "", completed.stderr or ""


def _parse_json(stdout: str) -> Mapping[str, Any] | None:
    raw = stdout.strip()
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, Mapping) else None
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, Mapping):
                return value
    return None


def _default_cli_root() -> Path | None:
    configured = _text(os.environ.get("PROTEUS_1688_CLI_ROOT"))
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    appdata = _text(os.environ.get("APPDATA"))
    if appdata:
        candidates.append(Path(appdata) / "npm" / "node_modules" / "1688-cli")
    for candidate in candidates:
        if (candidate / "package.json").is_file():
            return candidate.resolve()
    return None


def _default_bridge_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "collect_1688_supplier_store.mjs"


def _diagnostic(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _base(normalized: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schema_version": "0.2.6",
        "provider": LOCAL_1688_STORE_PROVIDER,
        "source_method": SOURCE_METHOD,
        "acquisition_status": "NOT_CONFIGURED",
        "submitted_target": normalized["submitted_target"],
        "canonical_url": normalized["canonical_url"],
        "supplier": {"shop_host": normalized["shop_host"]},
        "pages_attempted": 0,
        "pages_completed": 0,
        "observed_offer_count": 0,
        "available_offer_count": None,
        "has_next_page": None,
        "inventory_complete": False,
        "offers": [],
        "warnings": [],
        "diagnostics": [],
        "retrieved_at": _utc_now(),
    }


def _real_offer_url(value: Any) -> str | None:
    raw = _text(value)
    if raw.startswith("//"):
        raw = f"https:{raw}"
    if not raw:
        return None
    parsed = urlparse(raw)
    host = (parsed.hostname or "").rstrip(".").casefold()
    match = re.search(r"/offer/(\d+)(?:\.html)?", parsed.path, re.I)
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or not (host == "1688.com" or host.endswith(".1688.com"))
        or match is None
    ):
        return None
    return f"https://detail.1688.com/offer/{match.group(1)}.html"


def _normalize_supplier(
    value: Any, *, fallback_host: str
) -> dict[str, str]:
    supplier: dict[str, str] = {"shop_host": fallback_host}
    if not isinstance(value, Mapping):
        return supplier
    for output, keys in {
        "member_id": ("member_id", "memberId", "id"),
        "name": ("name", "company_name", "companyName", "shop_name", "shopName"),
        "shop_host": ("shop_host", "shopHost"),
    }.items():
        for key in keys:
            clean = _text(value.get(key))
            if clean:
                supplier[output] = clean[:300]
                break
    return supplier


def _normalize_payload(
    payload: Mapping[str, Any], normalized: Mapping[str, str]
) -> dict[str, Any]:
    outcome = _base(normalized)
    status = _text(payload.get("acquisition_status")).upper()
    outcome["acquisition_status"] = status if status in _STATUSES else "PARSER_FAILED"
    outcome["source_method"] = _text(payload.get("source_method")) or SOURCE_METHOD
    outcome["supplier"] = _normalize_supplier(
        payload.get("supplier"), fallback_host=normalized["shop_host"]
    )
    for key in ("pages_attempted", "pages_completed", "available_offer_count"):
        value = payload.get(key)
        outcome[key] = (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else (None if key == "available_offer_count" else 0)
        )
    has_next = payload.get("has_next_page")
    outcome["has_next_page"] = has_next if isinstance(has_next, bool) else None
    warnings = payload.get("warnings")
    if isinstance(warnings, list):
        outcome["warnings"] = [
            _text(item)[:200] for item in warnings if _text(item)
        ]
    retrieved_at = _text(payload.get("retrieved_at"))
    if retrieved_at:
        outcome["retrieved_at"] = retrieved_at

    raw_offers = payload.get("offers")
    invalid = 0
    duplicate = 0
    seen: set[str] = set()
    offers: list[dict[str, Any]] = []
    if isinstance(raw_offers, list):
        for raw in raw_offers:
            if not isinstance(raw, Mapping):
                invalid += 1
                continue
            offer_url = _real_offer_url(raw.get("offer_url") or raw.get("url"))
            supplied_offer_id = _text(raw.get("offer_id") or raw.get("offerId"))
            match = re.search(r"/offer/(\d+)\.html", offer_url or "")
            offer_id = match.group(1) if match else ""
            title = _text(raw.get("title") or raw.get("subject"))
            if (
                not offer_url
                or not offer_id
                or (supplied_offer_id and supplied_offer_id != offer_id)
                or not title
            ):
                invalid += 1
                continue
            if offer_id in seen:
                duplicate += 1
                continue
            seen.add(offer_id)
            record: dict[str, Any] = {
                "offer_id": offer_id,
                "title": title,
                "offer_url": offer_url,
                "supplier": dict(outcome["supplier"]),
            }
            for key in ("image_url", "price", "price_cny", "moq", "attributes", "skus"):
                if raw.get(key) is not None:
                    record[key] = raw[key]
            offers.append(record)
    else:
        outcome["acquisition_status"] = "PARSER_FAILED"
        invalid += 1
    outcome["offers"] = offers
    outcome["observed_offer_count"] = len(offers)
    if invalid:
        outcome["warnings"].append("INVALID_OFFER_SKIPPED")
        outcome["diagnostics"].append(
            _diagnostic(
                "INVALID_OFFER_SKIPPED",
                f"{invalid} store records lacked a valid 1688 offer identity.",
            )
        )
    if duplicate:
        outcome["warnings"].append("DUPLICATE_OFFER_SKIPPED")

    claimed_complete = payload.get("inventory_complete") is True
    outcome["inventory_complete"] = bool(
        claimed_complete
        and outcome["acquisition_status"] in {"SUCCESS", "EMPTY"}
        and outcome["has_next_page"] is False
        and not invalid
    )
    if not offers and outcome["acquisition_status"] in {"SUCCESS", "EMPTY"}:
        genuine_empty = bool(
            outcome["inventory_complete"]
            and outcome["available_offer_count"] == 0
            and outcome["has_next_page"] is False
        )
        if genuine_empty:
            outcome["acquisition_status"] = "EMPTY"
        else:
            outcome["acquisition_status"] = "PARSER_FAILED"
            outcome["inventory_complete"] = False
            outcome["warnings"].append("EMPTY_NOT_PROVEN")
    elif outcome["acquisition_status"] == "SUCCESS" and not outcome["inventory_complete"]:
        outcome["acquisition_status"] = "PARTIAL"
    return outcome


def collect_1688_store_offers(
    target: str,
    *,
    max_pages: int = 3,
    max_offers: int = 100,
    profile: str = "default",
    headed: bool = False,
    challenge_timeout_seconds: int = 180,
    timeout_seconds: float = 240.0,
    node_executable: str = DEFAULT_EXECUTABLE,
    cli_root: str | os.PathLike[str] | None = None,
    bridge_path: str | os.PathLike[str] | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Collect one bounded store snapshot without any buying-side action."""

    normalized = normalize_1688_supplier_store_target(target)
    outcome = _base(normalized)
    if isinstance(max_pages, bool) or not isinstance(max_pages, int) or not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be between 1 and 20")
    if isinstance(max_offers, bool) or not isinstance(max_offers, int) or not 1 <= max_offers <= 1000:
        raise ValueError("max_offers must be between 1 and 1000")
    if not _text(profile):
        raise ValueError("profile must be non-empty")
    if not 10 <= challenge_timeout_seconds <= 600:
        raise ValueError("challenge_timeout_seconds must be between 10 and 600")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    root = Path(cli_root) if cli_root is not None else _default_cli_root()
    bridge = Path(bridge_path) if bridge_path is not None else _default_bridge_path()
    if root is None or (command_runner is None and not (root / "package.json").is_file()):
        outcome["diagnostics"] = [
            _diagnostic("1688_CLI_NOT_FOUND", "The supported local 1688 CLI installation was not found.")
        ]
        return outcome
    if command_runner is None and not bridge.is_file():
        outcome["diagnostics"] = [
            _diagnostic("STORE_BRIDGE_NOT_FOUND", "The read-only store collector bridge is missing.")
        ]
        return outcome
    if command_runner is None and not shutil.which(node_executable):
        outcome["diagnostics"] = [
            _diagnostic("NODE_NOT_FOUND", "Node.js is required for the local authenticated store bridge.")
        ]
        return outcome

    argv = [
        node_executable,
        str(bridge),
        "--cli-root",
        str(root),
        "--url",
        normalized["canonical_url"],
        "--profile",
        profile,
        "--max-pages",
        str(max_pages),
        "--max-offers",
        str(max_offers),
        "--challenge-timeout-seconds",
        str(challenge_timeout_seconds),
    ]
    if headed:
        argv.append("--headed")
    runner = command_runner or _default_command_runner
    try:
        return_code, stdout, stderr = runner(argv, float(timeout_seconds))
    except subprocess.TimeoutExpired:
        outcome["acquisition_status"] = "TIMEOUT"
        outcome["warnings"] = ["STORE_COLLECTION_TIMEOUT"]
        return outcome
    except (FileNotFoundError, PermissionError, OSError):
        outcome["acquisition_status"] = "CLI_ERROR"
        outcome["warnings"] = ["STORE_BRIDGE_START_FAILED"]
        return outcome
    payload = _parse_json(stdout)
    if payload is None:
        outcome["acquisition_status"] = "CLI_ERROR" if return_code else "PARSER_FAILED"
        message = re.sub(r"\s+", " ", stderr).strip()[:300]
        outcome["diagnostics"] = [
            _diagnostic(
                "STORE_BRIDGE_INVALID_OUTPUT",
                message or "The store bridge did not emit a JSON result.",
            )
        ]
        return outcome
    result = _normalize_payload(payload, normalized)
    if return_code != 0 and result["acquisition_status"] in {"SUCCESS", "EMPTY", "PARTIAL"}:
        result["acquisition_status"] = "CLI_ERROR"
        result["inventory_complete"] = False
    return result


__all__ = [
    "LOCAL_1688_STORE_PROVIDER",
    "SOURCE_METHOD",
    "SUPPORTED_CLI_VERSION",
    "collect_1688_store_offers",
    "normalize_1688_supplier_store_target",
    "normalize_1688_supplier_target",
]
