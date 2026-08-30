"""User-triggered Edge capture sessions for bounded 1688 store snapshots.

The browser extension never transfers browser credentials. It submits only
normally rendered offer-card evidence to this loopback-only manager, which owns
supplier binding, bounds, deduplication, completeness and immutable snapshots.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from importlib import resources
import json
import re
import secrets
from threading import Lock
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from proteus.supplier_scout import SCHEMA_VERSION, SupplierScoutStore


CAPTURE_PROTOCOL_VERSION = "1"
DEFAULT_CAPTURE_TTL_SECONDS = 30 * 60
PAUSE_REASONS = {"AUTH_REQUIRED", "RISK_CONTROL", "PARSER_FAILED", "TIMEOUT"}


class CaptureAuthorizationError(PermissionError):
    """The opaque capture token did not authorize this mutation."""


class CaptureConflictError(ValueError):
    """The requested transition conflicts with capture state or source binding."""


class CaptureNotFoundError(KeyError):
    """The requested in-memory capture session does not exist."""


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _identity(source: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"shop_host": _text(source.get("shop_host")).casefold()}
    member_id = _text(source.get("member_id"))
    if member_id:
        result["member_id"] = member_id
    label = _text(source.get("label"))
    if label:
        result["name"] = label
    return result


def _page_url_for_source(value: Any, source: Mapping[str, Any]) -> str:
    page_url = _text(value)
    parsed = urlparse(page_url)
    expected = _text(source.get("shop_host")).casefold()
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != expected
        or parsed.username
        or parsed.password
    ):
        raise CaptureConflictError("capture page must belong to the saved supplier")
    return urlunparse(("https", expected, parsed.path or "/", "", parsed.query, ""))


def _normalize_offer(
    raw: Any, supplier: Mapping[str, Any]
) -> dict[str, Any] | None:
    if not isinstance(raw, Mapping):
        return None
    supplied_id = _text(raw.get("offer_id") or raw.get("offerId"))
    title = _text(raw.get("title") or raw.get("subject"))
    supplied_url = _text(raw.get("offer_url") or raw.get("url"))
    parsed = urlparse(supplied_url)
    match = re.fullmatch(r"/offer/(\d+)\.html", parsed.path)
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != "detail.1688.com"
        or match is None
        or not title
    ):
        return None
    offer_id = match.group(1)
    if supplied_id and supplied_id != offer_id:
        return None
    result: dict[str, Any] = {
        "offer_id": offer_id,
        "title": title,
        "offer_url": f"https://detail.1688.com/offer/{offer_id}.html",
        "supplier": dict(supplier),
    }
    image_url = _text(raw.get("image_url") or raw.get("image"))
    if image_url.startswith("//"):
        image_url = "https:" + image_url
    if image_url.startswith("https://"):
        result["image_url"] = image_url
    for key in ("price", "price_cny", "moq", "attributes", "skus"):
        if raw.get(key) is not None:
            result[key] = deepcopy(raw[key])
    return result


def supplier_collector_profile() -> dict[str, Any]:
    """Return the packaged non-executable selector profile for the Edge extension."""

    resource = resources.files("proteus.data").joinpath(
        "1688_supplier_collector_profile.json"
    )
    profile = json.loads(resource.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "profile_id",
        "parser_version",
        "offer_link_selectors",
        "next_page_selectors",
        "risk_text",
        "auth_text",
        "empty_text",
        "scroll",
    }
    if not isinstance(profile, dict) or not required.issubset(profile):
        raise RuntimeError("packaged supplier collector profile is invalid")
    return profile


class SupplierCaptureManager:
    """Thread-safe, process-local capture state with persistent final snapshots."""

    def __init__(
        self,
        store: SupplierScoutStore,
        *,
        ttl_seconds: int = DEFAULT_CAPTURE_TTL_SECONDS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not 60 <= ttl_seconds <= 24 * 60 * 60:
            raise ValueError("ttl_seconds must be between 60 and 86400")
        self.store = store
        self._ttl_seconds = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._captures: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _get_locked(self, capture_id: str) -> dict[str, Any]:
        capture = self._captures.get(_text(capture_id))
        if capture is None:
            raise CaptureNotFoundError(f"capture not found: {capture_id}")
        return capture

    def _authorize_locked(self, capture: Mapping[str, Any], token: str) -> None:
        supplied = _text(token)
        expected = str(capture["_capture_token"])
        if not supplied or not secrets.compare_digest(supplied, expected):
            raise CaptureAuthorizationError("capture token is invalid")

    def _public_locked(
        self, capture: Mapping[str, Any], *, include_token: bool = False
    ) -> dict[str, Any]:
        keys = (
            "capture_id",
            "protocol_version",
            "supplier_id",
            "supplier_label",
            "canonical_url",
            "shop_host",
            "status",
            "max_pages",
            "max_offers",
            "pages_attempted",
            "pages_completed",
            "observed_offer_count",
            "available_offer_count",
            "has_next_page",
            "collector_version",
            "parser_version",
            "snapshot_id",
            "snapshot_sha256",
            "last_pause_reason",
            "warnings",
            "created_at",
            "updated_at",
            "expires_at",
        )
        result = {
            key: deepcopy(capture.get(key))
            for key in keys
            if capture.get(key) is not None
        }
        result["next_page_number"] = int(capture["pages_completed"]) + 1
        if include_token:
            result["capture_token"] = str(capture["_capture_token"])
        return result

    def _touch_locked(self, capture: dict[str, Any]) -> None:
        now = self._now()
        capture["updated_at"] = _iso(now)
        capture["expires_at"] = _iso(now + timedelta(seconds=self._ttl_seconds))

    def _snapshot_document_locked(
        self,
        capture: Mapping[str, Any],
        *,
        acquisition_status: str,
        inventory_complete: bool,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        combined_warnings = list(capture["warnings"])
        combined_warnings.extend(warnings or [])
        combined_warnings = list(dict.fromkeys(item for item in combined_warnings if item))
        return {
            "schema_version": SCHEMA_VERSION,
            "provider": "PROTEUS_EDGE_EXTENSION",
            "source_method": "USER_INITIATED_BROWSER_EXTENSION",
            "submitted_target": capture["submitted_target"],
            "canonical_url": capture["canonical_url"],
            "supplier": deepcopy(capture["supplier"]),
            "retrieved_at": _iso(self._now()),
            "acquisition_status": acquisition_status,
            "pages_attempted": capture["pages_attempted"],
            "pages_completed": capture["pages_completed"],
            "observed_offer_count": len(capture["offers"]),
            "available_offer_count": capture["available_offer_count"],
            "has_next_page": capture["has_next_page"],
            "inventory_complete": inventory_complete,
            "offers": deepcopy(capture["offers"]),
            "warnings": combined_warnings,
            "diagnostics": deepcopy(capture["diagnostics"]),
            "page_evidence": deepcopy(capture["page_evidence"]),
            "capture": {
                "capture_id": capture["capture_id"],
                "protocol_version": CAPTURE_PROTOCOL_VERSION,
                "collector_version": capture.get("collector_version"),
                "parser_version": capture.get("parser_version"),
                "max_pages": capture["max_pages"],
                "max_offers": capture["max_offers"],
            },
        }

    def _persist_snapshot_locked(
        self,
        capture: dict[str, Any],
        *,
        acquisition_status: str,
        inventory_complete: bool,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        document = self._snapshot_document_locked(
            capture,
            acquisition_status=acquisition_status,
            inventory_complete=inventory_complete,
            warnings=warnings,
        )
        saved = self.store.save_snapshot(capture["supplier_id"], document)
        capture["snapshot_id"] = saved["snapshot_id"]
        capture["snapshot_sha256"] = saved["snapshot_sha256"]
        return saved

    def _expire_locked(self, capture: dict[str, Any]) -> bool:
        if capture["status"] in {"COMPLETED", "EXPIRED", "CANCELLED"}:
            return capture["status"] == "EXPIRED"
        expires = datetime.fromisoformat(str(capture["expires_at"]).replace("Z", "+00:00"))
        if self._now() <= expires:
            return False
        if capture["offers"]:
            self._persist_snapshot_locked(
                capture,
                acquisition_status="PARTIAL",
                inventory_complete=False,
                warnings=["CAPTURE_EXPIRED"],
            )
        capture["status"] = "EXPIRED"
        capture["updated_at"] = _iso(self._now())
        return True

    def create_capture(
        self, supplier_id: str, *, max_pages: int, max_offers: int
    ) -> dict[str, Any]:
        if isinstance(max_pages, bool) or not 1 <= max_pages <= 20:
            raise ValueError("max_pages must be between 1 and 20")
        if isinstance(max_offers, bool) or not 1 <= max_offers <= 1000:
            raise ValueError("max_offers must be between 1 and 1000")
        source = self.store.get_supplier(supplier_id)
        if source["status"] != "ACTIVE":
            raise CaptureConflictError("supplier source is archived")
        now = self._now()
        capture_id = f"cap_{uuid4().hex}"
        capture: dict[str, Any] = {
            "capture_id": capture_id,
            "protocol_version": CAPTURE_PROTOCOL_VERSION,
            "_capture_token": secrets.token_urlsafe(32),
            "supplier_id": source["supplier_id"],
            "supplier_label": source["label"],
            "submitted_target": source["submitted_target"],
            "canonical_url": source["canonical_url"],
            "shop_host": source["shop_host"],
            "supplier": _identity(source),
            "status": "PENDING",
            "max_pages": max_pages,
            "max_offers": max_offers,
            "pages_attempted": 0,
            "pages_completed": 0,
            "observed_offer_count": 0,
            "available_offer_count": None,
            "has_next_page": None,
            "collector_version": None,
            "parser_version": None,
            "snapshot_id": None,
            "snapshot_sha256": None,
            "last_pause_reason": None,
            "warnings": [],
            "diagnostics": [],
            "offers": [],
            "_offer_ids": set(),
            "page_evidence": [],
            "_page_hashes": {},
            "_invalid_offer_count": 0,
            "created_at": _iso(now),
            "updated_at": _iso(now),
            "expires_at": _iso(now + timedelta(seconds=self._ttl_seconds)),
        }
        with self._lock:
            self._captures[capture_id] = capture
            return self._public_locked(capture, include_token=True)

    def get_capture(self, capture_id: str) -> dict[str, Any]:
        with self._lock:
            capture = self._get_locked(capture_id)
            self._expire_locked(capture)
            return self._public_locked(capture)

    def pending_capture(self, *, shop_host: str) -> dict[str, Any] | None:
        requested_host = _text(shop_host).casefold()
        if not requested_host.endswith(".1688.com"):
            return None
        with self._lock:
            candidates: list[dict[str, Any]] = []
            for capture in self._captures.values():
                self._expire_locked(capture)
                if capture["status"] not in {"PENDING", "PAUSED"}:
                    continue
                if capture["shop_host"] != requested_host:
                    continue
                candidates.append(capture)
            if not candidates:
                return None
            newest = max(candidates, key=lambda item: item["updated_at"])
            return self._public_locked(newest, include_token=True)

    def claim_capture(
        self,
        capture_id: str,
        token: str,
        *,
        page_url: str,
        extension_version: str | None = None,
        parser_version: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            capture = self._get_locked(capture_id)
            self._authorize_locked(capture, token)
            if self._expire_locked(capture):
                raise CaptureConflictError("capture session expired")
            _page_url_for_source(page_url, capture)
            if capture["status"] not in {"PENDING", "PAUSED"}:
                raise CaptureConflictError(
                    f"capture cannot be claimed from {capture['status']}"
                )
            capture["status"] = "CAPTURING"
            capture["last_pause_reason"] = None
            if _text(extension_version):
                capture["collector_version"] = _text(extension_version)[:50]
            if _text(parser_version):
                capture["parser_version"] = _text(parser_version)[:50]
            self._touch_locked(capture)
            return self._public_locked(capture)

    def _pause_locked(
        self,
        capture: dict[str, Any],
        *,
        reason: str,
        page_url: str,
    ) -> dict[str, Any]:
        capture["last_pause_reason"] = reason
        capture["status"] = "PAUSED"
        capture["warnings"] = list(dict.fromkeys([*capture["warnings"], reason]))
        capture["diagnostics"].append(
            {
                "code": reason,
                "message": "The ordinary Edge page requires user attention before capture can continue.",
                "page_url": page_url,
            }
        )
        self._persist_snapshot_locked(
            capture,
            acquisition_status="PARTIAL" if capture["offers"] else reason,
            inventory_complete=False,
            warnings=[reason],
        )
        self._touch_locked(capture)
        return self._public_locked(capture)

    def pause_capture(
        self,
        capture_id: str,
        token: str,
        *,
        reason: str,
        page_url: str,
    ) -> dict[str, Any]:
        normalized_reason = _text(reason).upper()
        if normalized_reason not in PAUSE_REASONS:
            raise ValueError("unsupported capture pause reason")
        with self._lock:
            capture = self._get_locked(capture_id)
            self._authorize_locked(capture, token)
            if self._expire_locked(capture):
                raise CaptureConflictError("capture session expired")
            clean_page_url = _page_url_for_source(page_url, capture)
            if capture["status"] != "CAPTURING":
                raise CaptureConflictError(
                    f"capture cannot pause from {capture['status']}"
                )
            return self._pause_locked(
                capture, reason=normalized_reason, page_url=clean_page_url
            )

    def ingest_page(
        self, capture_id: str, token: str, page: Mapping[str, Any]
    ) -> dict[str, Any]:
        if not isinstance(page, Mapping):
            raise TypeError("page payload must be an object")
        with self._lock:
            capture = self._get_locked(capture_id)
            self._authorize_locked(capture, token)
            if self._expire_locked(capture):
                raise CaptureConflictError("capture session expired")

            try:
                page_number = int(page.get("page_number"))
            except (TypeError, ValueError) as exc:
                raise ValueError("page_number must be an integer") from exc
            if isinstance(page.get("page_number"), bool) or not 1 <= page_number <= 20:
                raise ValueError("page_number must be between 1 and 20")
            page_url = _page_url_for_source(page.get("page_url"), capture)
            raw_offers = page.get("offers")
            if not isinstance(raw_offers, list):
                raise ValueError("offers must be an array")
            has_next = page.get("has_next_page")
            if not isinstance(has_next, bool) and has_next is not None:
                raise ValueError("has_next_page must be true, false or null")
            available = page.get("available_offer_count")
            if isinstance(available, bool) or (
                available is not None and (not isinstance(available, int) or available < 0)
            ):
                raise ValueError("available_offer_count must be a non-negative integer or null")
            empty_state = page.get("empty_state", False)
            if not isinstance(empty_state, bool):
                raise ValueError("empty_state must be true or false")

            identity_offer_ids: list[str] = []
            identity_invalid_count = 0
            for raw in raw_offers:
                normalized = _normalize_offer(raw, capture["supplier"])
                if normalized is None:
                    identity_invalid_count += 1
                else:
                    identity_offer_ids.append(normalized["offer_id"])
            page_identity = {
                "page_number": page_number,
                "page_url": page_url,
                "has_next_page": has_next,
                "available_offer_count": available,
                "empty_state": empty_state,
                "offer_ids": sorted(identity_offer_ids),
                "invalid_offer_count": identity_invalid_count,
            }
            page_hash = hashlib.sha256(
                _canonical_json(page_identity).encode("utf-8")
            ).hexdigest()
            existing_hash = capture["_page_hashes"].get(page_number)
            if existing_hash is not None:
                if existing_hash == page_hash:
                    return self._public_locked(capture)
                raise CaptureConflictError("page was already ingested with different evidence")
            if capture["status"] != "CAPTURING":
                raise CaptureConflictError(
                    f"capture cannot ingest pages from {capture['status']}"
                )
            expected_page = int(capture["pages_completed"]) + 1
            if page_number != expected_page:
                raise CaptureConflictError(
                    f"page_number must be the next sequential page ({expected_page})"
                )
            if page_number > capture["max_pages"]:
                raise CaptureConflictError("page exceeds the capture page bound")

            supplier = capture["supplier"]
            invalid = 0
            duplicates = 0
            accepted = 0
            truncated = 0
            remaining = capture["max_offers"] - len(capture["offers"])
            for raw in raw_offers:
                normalized = _normalize_offer(raw, supplier)
                if normalized is None:
                    invalid += 1
                    continue
                offer_id = normalized["offer_id"]
                if offer_id in capture["_offer_ids"]:
                    duplicates += 1
                    continue
                if remaining <= 0:
                    truncated += 1
                    continue
                capture["_offer_ids"].add(offer_id)
                capture["offers"].append(normalized)
                accepted += 1
                remaining -= 1

            if invalid:
                capture["_invalid_offer_count"] += invalid
                capture["warnings"].append("INVALID_OFFER_SKIPPED")
                capture["diagnostics"].append(
                    {
                        "code": "INVALID_OFFER_SKIPPED",
                        "message": f"{invalid} rendered offer records lacked a valid 1688 identity.",
                        "page_url": page_url,
                    }
                )
            if duplicates:
                capture["warnings"].append("DUPLICATE_OFFER_SKIPPED")
            if truncated:
                capture["warnings"].append("OFFER_BOUND_REACHED")

            if accepted == 0 and truncated == 0 and not empty_state:
                capture["diagnostics"].append(
                    {
                        "code": "PAGE_OFFERS_NOT_CONFIRMED",
                        "message": "The rendered page did not prove a new offer list or an explicit empty state.",
                        "page_url": page_url,
                    }
                )
                return self._pause_locked(
                    capture, reason="PARSER_FAILED", page_url=page_url
                )

            evidence = page.get("evidence")
            evidence_copy = deepcopy(dict(evidence)) if isinstance(evidence, Mapping) else {}
            evidence_copy.update(
                {
                    "page_number": page_number,
                    "page_url": page_url,
                    "captured_at": _iso(self._now()),
                    "raw_offer_count": len(raw_offers),
                    "accepted_offer_count": accepted,
                    "invalid_offer_count": invalid,
                    "duplicate_offer_count": duplicates,
                    "truncated_offer_count": truncated,
                    "has_next_page": has_next,
                    "available_offer_count": available,
                    "empty_state": empty_state,
                }
            )
            capture["page_evidence"].append(evidence_copy)
            capture["_page_hashes"][page_number] = page_hash
            capture["pages_attempted"] = page_number
            capture["pages_completed"] = page_number
            capture["observed_offer_count"] = len(capture["offers"])
            capture["available_offer_count"] = available
            capture["has_next_page"] = has_next
            capture["warnings"] = list(dict.fromkeys(capture["warnings"]))
            self._touch_locked(capture)

            offer_bound = truncated > 0 or (
                len(capture["offers"]) >= capture["max_offers"]
                and has_next is not False
            )
            page_bound = page_number >= capture["max_pages"] and has_next is not False
            if offer_bound or page_bound:
                if offer_bound:
                    capture["warnings"] = list(
                        dict.fromkeys([*capture["warnings"], "OFFER_BOUND_REACHED"])
                    )
                if page_bound:
                    capture["warnings"] = list(
                        dict.fromkeys([*capture["warnings"], "PAGE_BOUND_REACHED"])
                    )
                self._persist_snapshot_locked(
                    capture,
                    acquisition_status="PARTIAL",
                    inventory_complete=False,
                )
                capture["status"] = "COMPLETED"
                self._touch_locked(capture)
                return self._public_locked(capture)

            if has_next is False:
                if not capture["offers"]:
                    genuine_empty = (
                        empty_state and available == 0 and invalid == 0
                    )
                    if not genuine_empty:
                        return self._pause_locked(
                            capture, reason="PARSER_FAILED", page_url=page_url
                        )
                    acquisition_status = "EMPTY"
                    inventory_complete = True
                else:
                    count_consistent = available is None or available == len(
                        capture["offers"]
                    )
                    if not count_consistent:
                        capture["warnings"] = list(
                            dict.fromkeys(
                                [
                                    *capture["warnings"],
                                    "AVAILABLE_COUNT_MISMATCH",
                                ]
                            )
                        )
                        capture["diagnostics"].append(
                            {
                                "code": "AVAILABLE_COUNT_MISMATCH",
                                "message": (
                                    "The reported store total did not equal the unique "
                                    "offers observed at the claimed final page."
                                ),
                                "page_url": page_url,
                            }
                        )
                    inventory_complete = (
                        capture["_invalid_offer_count"] == 0 and count_consistent
                    )
                    acquisition_status = "SUCCESS" if inventory_complete else "PARTIAL"
                self._persist_snapshot_locked(
                    capture,
                    acquisition_status=acquisition_status,
                    inventory_complete=inventory_complete,
                )
                capture["status"] = "COMPLETED"
                self._touch_locked(capture)
                return self._public_locked(capture)

            if has_next is None:
                return self._pause_locked(
                    capture, reason="PARSER_FAILED", page_url=page_url
                )
            return self._public_locked(capture)


__all__ = [
    "CAPTURE_PROTOCOL_VERSION",
    "CaptureAuthorizationError",
    "CaptureConflictError",
    "CaptureNotFoundError",
    "SupplierCaptureManager",
    "supplier_collector_profile",
]
