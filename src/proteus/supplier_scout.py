"""Supplier-first, bounded 1688 store screening.

This workflow treats one immutable supplier inventory snapshot as its candidate
source.  It reuses the active Northway leaf definitions and family-level market
logic, while preserving source completeness and provider failures separately
from Amazon A/A- competition grades.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from typing import Any
from uuid import uuid4

from proteus.category_catalog import builtin_runtime_categories
from proteus.normalization import normalize_part_number
from proteus.northway_mvp import (
    aggregate_amazon_family_results,
    build_amazon_query_pack,
    resolve_product_family,
)
from proteus.providers.local_1688_store import normalize_1688_supplier_store_target
from proteus.providers.serpapi_ebay_discovery import extract_part_number_candidates


SUPPLIER_SCOUT_DB_ENV = "PROTEUS_SUPPLIER_SCOUT_DB"
SCHEMA_VERSION = "0.2.6"
PROFILE = "supplier-first-store-scout"

Collector = Callable[..., Mapping[str, Any]]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def default_supplier_scout_db_path() -> Path:
    configured = _text(os.environ.get(SUPPLIER_SCOUT_DB_ENV))
    if configured:
        return Path(configured).expanduser().resolve()
    local_appdata = _text(os.environ.get("LOCALAPPDATA"))
    base = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
    return (base / "Proteus" / "supplier_scout.sqlite3").resolve()


class SupplierScoutStore:
    """Local single-user supplier sources and immutable inventory snapshots."""

    def __init__(self, database_path: str | os.PathLike[str] | None = None) -> None:
        self.database_path = (
            Path(database_path).resolve()
            if database_path is not None
            else default_supplier_scout_db_path()
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS supplier_sources(
                    supplier_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    submitted_target TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    shop_host TEXT NOT NULL,
                    member_id TEXT,
                    status TEXT NOT NULL CHECK(status IN ('ACTIVE', 'ARCHIVED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS supplier_sources_active_url
                ON supplier_sources(canonical_url) WHERE status = 'ACTIVE';
                CREATE TABLE IF NOT EXISTS supplier_inspections(
                    inspection_id TEXT PRIMARY KEY,
                    supplier_id TEXT REFERENCES supplier_sources(supplier_id),
                    submitted_target TEXT NOT NULL,
                    canonical_url TEXT NOT NULL,
                    acquisition_status TEXT NOT NULL,
                    inspection_sha256 TEXT NOT NULL,
                    inspection_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS supplier_inspections_supplier
                ON supplier_inspections(supplier_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS inventory_snapshots(
                    snapshot_id TEXT PRIMARY KEY,
                    supplier_id TEXT NOT NULL REFERENCES supplier_sources(supplier_id),
                    retrieved_at TEXT NOT NULL,
                    acquisition_status TEXT NOT NULL,
                    inventory_complete INTEGER NOT NULL CHECK(inventory_complete IN (0, 1)),
                    observed_offer_count INTEGER NOT NULL,
                    snapshot_sha256 TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS inventory_snapshots_supplier
                ON inventory_snapshots(supplier_id, created_at DESC);
                """
            )

    @staticmethod
    def _source_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "supplier_id": row["supplier_id"],
            "label": row["label"],
            "submitted_target": row["submitted_target"],
            "canonical_url": row["canonical_url"],
            "shop_host": row["shop_host"],
            "member_id": row["member_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def add_supplier(
        self,
        label: str,
        target: str,
        *,
        member_id: str | None = None,
    ) -> dict[str, Any]:
        clean_label = _text(label)
        if not clean_label:
            raise ValueError("supplier label must not be blank")
        normalized = normalize_1688_supplier_store_target(target)
        now = _utc_now()
        supplier_id = f"sup_{uuid4().hex}"
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO supplier_sources(
                        supplier_id, label, submitted_target, canonical_url,
                        shop_host, member_id, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
                    """,
                    (
                        supplier_id,
                        clean_label[:200],
                        normalized["submitted_target"],
                        normalized["canonical_url"],
                        normalized["shop_host"],
                        _text(member_id) or None,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("an active supplier with this canonical URL already exists") from exc
        return self.get_supplier(supplier_id)

    def get_supplier(self, supplier_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM supplier_sources WHERE supplier_id = ?", (supplier_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"supplier not found: {supplier_id}")
        return self._source_payload(row)

    def list_suppliers(self, *, include_archived: bool = False) -> dict[str, Any]:
        where = "" if include_archived else "WHERE status = 'ACTIVE'"
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM supplier_sources {where} ORDER BY updated_at DESC"
            ).fetchall()
        return {
            "database": str(self.database_path),
            "suppliers": [self._source_payload(row) for row in rows],
        }

    def archive_supplier(self, supplier_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE supplier_sources SET status = 'ARCHIVED', updated_at = ? WHERE supplier_id = ?",
                (now, supplier_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"supplier not found: {supplier_id}")
        return self.get_supplier(supplier_id)

    def update_supplier_identity(
        self, supplier_id: str, identity: Mapping[str, Any]
    ) -> dict[str, Any]:
        member_id = _text(identity.get("member_id"))
        if not member_id:
            return self.get_supplier(supplier_id)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE supplier_sources SET member_id = ?, updated_at = ? WHERE supplier_id = ?",
                (member_id, _utc_now(), supplier_id),
            )
        if cursor.rowcount != 1:
            raise KeyError(f"supplier not found: {supplier_id}")
        return self.get_supplier(supplier_id)

    def save_inspection(
        self,
        submitted_target: str,
        outcome: Mapping[str, Any],
        *,
        supplier_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist one read-only canary outcome without mutating a snapshot."""

        if supplier_id is not None:
            self.get_supplier(supplier_id)
        if not isinstance(outcome, Mapping):
            raise TypeError("inspection outcome must be a mapping")
        normalized = normalize_1688_supplier_store_target(submitted_target)
        document = deepcopy(dict(outcome))
        document.setdefault("submitted_target", normalized["submitted_target"])
        document.setdefault("canonical_url", normalized["canonical_url"])
        serialized = _canonical_json(document)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        inspection_id = f"insp_{uuid4().hex}"
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO supplier_inspections(
                    inspection_id, supplier_id, submitted_target, canonical_url,
                    acquisition_status, inspection_sha256,
                    inspection_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inspection_id,
                    supplier_id,
                    normalized["submitted_target"],
                    normalized["canonical_url"],
                    _text(document.get("acquisition_status")) or "PARSER_FAILED",
                    digest,
                    serialized,
                    now,
                ),
            )
        return {
            "inspection_id": inspection_id,
            "supplier_id": supplier_id,
            "inspection_sha256": digest,
            "created_at": now,
        }

    def get_inspection(self, inspection_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM supplier_inspections WHERE inspection_id = ?",
                (inspection_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"inspection not found: {inspection_id}")
        document = json.loads(row["inspection_json"])
        document["inspection_id"] = row["inspection_id"]
        document["supplier_id"] = row["supplier_id"]
        document["inspection_sha256"] = row["inspection_sha256"]
        document["inspection_created_at"] = row["created_at"]
        return document

    def save_snapshot(
        self,
        supplier_id: str,
        snapshot: Mapping[str, Any],
        *,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]:
        self.get_supplier(supplier_id)
        if not isinstance(snapshot, Mapping):
            raise TypeError("snapshot must be a mapping")
        offers = snapshot.get("offers")
        if not isinstance(offers, list):
            raise ValueError("snapshot offers must be an array")
        document = deepcopy(dict(snapshot))
        document["supplier_id"] = supplier_id
        serialized = _canonical_json(document)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        identifier = snapshot_id or f"snap_{uuid4().hex}"
        now = _utc_now()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO inventory_snapshots(
                        snapshot_id, supplier_id, retrieved_at,
                        acquisition_status, inventory_complete,
                        observed_offer_count, snapshot_sha256,
                        snapshot_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        identifier,
                        supplier_id,
                        _text(document.get("retrieved_at")) or now,
                        _text(document.get("acquisition_status")) or "PARSER_FAILED",
                        1 if document.get("inventory_complete") is True else 0,
                        len(offers),
                        digest,
                        serialized,
                        now,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("inventory snapshots are immutable") from exc
        return {
            "snapshot_id": identifier,
            "supplier_id": supplier_id,
            "snapshot_sha256": digest,
            "created_at": now,
        }

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM inventory_snapshots WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"snapshot not found: {snapshot_id}")
        document = json.loads(row["snapshot_json"])
        document["snapshot_id"] = row["snapshot_id"]
        document["snapshot_sha256"] = row["snapshot_sha256"]
        document["snapshot_created_at"] = row["created_at"]
        return document

    def latest_snapshot(self, supplier_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshot_id FROM inventory_snapshots
                WHERE supplier_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (supplier_id,),
            ).fetchone()
        return self.get_snapshot(row["snapshot_id"]) if row is not None else None


def _category_terms(definition: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("supply_aliases", "supply_keywords", "aliases"):
        raw = definition.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            values.extend(_text(item).casefold() for item in raw if _text(item))
    part_type = _text(definition.get("part_type")).casefold()
    if part_type:
        values.append(part_type)
    return list(dict.fromkeys(values))


def classify_supplier_offer(
    offer: Mapping[str, Any],
    category_definitions: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    title = _text(offer.get("title"))
    folded = title.casefold()
    matches: list[dict[str, Any]] = []
    for category_id, definition in category_definitions.items():
        matched_terms = [term for term in _category_terms(definition) if term in folded]
        if matched_terms:
            matches.append(
                {
                    "category_id": category_id,
                    "category_version_id": definition.get("category_version_id"),
                    "matched_terms": matched_terms,
                }
            )
    if not matches:
        return {"status": "CATEGORY_UNMATCHED", "category_id": None, "matches": []}
    if len(matches) > 1:
        return {
            "status": "CATEGORY_AMBIGUOUS",
            "category_id": None,
            "matches": matches,
        }
    return {
        "status": "MATCHED",
        "category_id": matches[0]["category_id"],
        "category_version_id": matches[0]["category_version_id"],
        "matched_terms": matches[0]["matched_terms"],
        "matches": matches,
    }


def _supplier_matches(snapshot: Mapping[str, Any], offer: Mapping[str, Any]) -> bool:
    source = snapshot.get("supplier")
    observed = offer.get("supplier")
    if not isinstance(source, Mapping) or not isinstance(observed, Mapping):
        return False
    source_member = _text(source.get("member_id"))
    offer_member = _text(observed.get("member_id"))
    if source_member and offer_member:
        return source_member == offer_member
    source_host = _text(source.get("shop_host")).casefold()
    offer_host = _text(observed.get("shop_host")).casefold()
    return bool(source_host and offer_host and source_host == offer_host)


def supplier_scout_policy(
    category_definitions: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    category_catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    definitions = category_definitions or builtin_runtime_categories()
    return {
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "source_bounds": {
            "max_pages": {"minimum": 1, "maximum": 20, "default": 3},
            "max_offers": {"minimum": 1, "maximum": 1000, "default": 100},
            "manual_challenge_wait": {"default": False, "maximum_seconds": 600},
        },
        "market_bounds": {
            "request_budget": {"minimum": 0, "maximum": 1000, "default": 20},
            "max_amazon_queries_per_family": {"minimum": 1, "maximum": 5, "default": 3},
        },
        "default_thresholds": {
            "grade_a_max_competitors": 5,
            "grade_a_minus_max_competitors": 8,
            "min_family_price_usd": 20.0,
            "min_observed_ebay_demand": 1,
        },
        "categories": {
            key: {
                "category_id": key,
                "category_version_id": value.get("category_version_id"),
                "label_zh": value.get("label_zh"),
                "label_en": value.get("label_en"),
                "group_id": value.get("group_id"),
                "part_type": value.get("part_type"),
            }
            for key, value in definitions.items()
        },
        "category_catalog": deepcopy(dict(category_catalog)) if category_catalog else None,
        "competition_rule": {
            "A": "complete competitive_product_cluster_count <= 5 by default",
            "A-": "complete count 6-8 by default",
            "REJECTED": "complete or observed lower bound >= 9 by default",
            "PENDING": "low observed count with incomplete Amazon evidence",
        },
        "boundary": "A/A- grades Amazon product-family competition only; it is not a supplier score or purchase decision.",
    }


def _source_inventory(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: deepcopy(snapshot.get(key))
        for key in (
            "supplier_id",
            "snapshot_id",
            "snapshot_sha256",
            "provider",
            "source_method",
            "canonical_url",
            "supplier",
            "retrieved_at",
            "acquisition_status",
            "inventory_complete",
            "pages_attempted",
            "pages_completed",
            "observed_offer_count",
            "available_offer_count",
            "has_next_page",
            "warnings",
            "diagnostics",
        )
    }


def _progress(
    callback: Callable[[Mapping[str, Any]], None] | None,
    *,
    phase: str,
    current: int,
    total: int,
    offer: Mapping[str, Any] | None,
    provider: str | None,
    budget_used: int,
) -> None:
    if callback is None:
        return
    callback(
        {
            "phase": phase,
            "current": current,
            "total": total,
            "last_query": _text(offer.get("title")) if isinstance(offer, Mapping) else None,
            "provider": provider,
            "budget_used": budget_used,
            "updated_at": _utc_now(),
        }
    )


def _identity_candidate(offer: Mapping[str, Any], definition: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    title = _text(offer.get("title"))
    identifiers = list(extract_part_number_candidates(title))
    # The eBay discovery extractor deliberately rejects unseparated numeric
    # tokens because broad marketplace titles contain too much numeric noise.
    # A supplier card already passed an explicit narrow part-type alias, so an
    # isolated 7-14 digit OEM token is useful here. Four-digit years and ranges
    # remain excluded, and the family still requires vehicle fitment.
    seen = {normalize_part_number(item) for item in identifiers}
    for match in re.finditer(r"(?<![A-Z0-9])(\d{7,14})(?![A-Z0-9])", title.upper()):
        token = match.group(1)
        if token not in seen:
            identifiers.append(token)
            seen.add(token)
    if not identifiers:
        return {
            "scope_status": "IN_SCOPE",
            "identity_status": "REVIEW_REQUIRED",
            "category_profile": definition.get("profile"),
            "family": None,
            "reasons": ["No conservative OEM/MPN token was extracted from the supplier title."],
        }, []
    source_title = f"{_text(definition.get('part_type'))} {title}".strip()
    candidates = [
        {
            "raw_part_number": raw,
            "canonical_part_number": normalize_part_number(raw),
            "source_listing_id": _text(offer.get("offer_id")),
            "source_listing_url": _text(offer.get("offer_url")),
            "source_listing_title": source_title,
            "source_listing_position": 1,
            "source_sold_count": None,
        }
        for raw in identifiers
    ]
    resolution = resolve_product_family(
        candidates,
        _text(definition.get("category_id")),
        category_definitions={_text(definition.get("category_id")): definition},
    )
    return resolution, identifiers


def _not_run_report(
    offer: Mapping[str, Any],
    category_match: Mapping[str, Any],
    *,
    status: str,
    reason: str,
    resolution: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "offer": deepcopy(dict(offer)),
        "category_match": deepcopy(dict(category_match)),
        "resolution": deepcopy(dict(resolution)) if isinstance(resolution, Mapping) else None,
        "identifiers": [],
        "demand": None,
        "amazon_query_pack": [],
        "competition": None,
        "competition_grade": None,
        "market_status": status,
        "decision": "REVIEW_REQUIRED",
        "evidence_gaps": [reason],
        "provider_attempts": [],
    }


def run_supplier_scout(
    inventory_snapshot: Mapping[str, Any],
    *,
    category_definitions: Mapping[str, Mapping[str, Any]] | None = None,
    selected_category_ids: Sequence[str] | None = None,
    serpapi_key: str | None,
    market_request_budget: int = 20,
    max_amazon_queries_per_family: int = 3,
    grade_a_max_competitors: int = 5,
    grade_a_minus_max_competitors: int = 8,
    min_family_price_usd: float = 20.0,
    min_observed_ebay_demand: int = 1,
    collectors: Mapping[str, Collector] | None = None,
    progress_callback: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Screen every observed offer; bounds produce explicit not-run reports."""

    if not isinstance(inventory_snapshot, Mapping):
        raise TypeError("inventory_snapshot must be a mapping")
    if isinstance(market_request_budget, bool) or not isinstance(market_request_budget, int) or not 0 <= market_request_budget <= 1000:
        raise ValueError("market_request_budget must be between 0 and 1000")
    if isinstance(max_amazon_queries_per_family, bool) or not isinstance(max_amazon_queries_per_family, int) or not 1 <= max_amazon_queries_per_family <= 5:
        raise ValueError("max_amazon_queries_per_family must be between 1 and 5")
    if grade_a_minus_max_competitors <= grade_a_max_competitors:
        raise ValueError("grade_a_minus_max_competitors must exceed grade_a_max_competitors")
    all_definitions = dict(category_definitions or builtin_runtime_categories())
    selected = list(selected_category_ids or all_definitions.keys())
    unknown = sorted(set(selected) - set(all_definitions))
    if unknown:
        raise ValueError(f"selected categories are not active: {', '.join(unknown)}")
    definitions = {key: all_definitions[key] for key in selected}
    offers = inventory_snapshot.get("offers")
    if not isinstance(offers, list):
        raise ValueError("inventory_snapshot.offers must be an array")
    acquisition_status = _text(inventory_snapshot.get("acquisition_status")).upper()
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "profile": PROFILE,
        "status": "COMPLETED",
        "created_at": _utc_now(),
        "inventory": _source_inventory(inventory_snapshot),
        "policy": {
            "selected_category_ids": selected,
            "category_versions": {
                key: value.get("category_version_id") for key, value in definitions.items()
            },
            "market_request_budget": market_request_budget,
            "max_amazon_queries_per_family": max_amazon_queries_per_family,
            "grade_a_max_competitors": grade_a_max_competitors,
            "grade_a_minus_max_competitors": grade_a_minus_max_competitors,
            "min_family_price_usd": min_family_price_usd,
            "min_observed_ebay_demand": min_observed_ebay_demand,
        },
        "market_budget": {"limit": market_request_budget, "used": 0, "remaining": market_request_budget},
        "reports": [],
        "summary": {},
    }
    if acquisition_status not in {"SUCCESS", "PARTIAL", "EMPTY"}:
        result["status"] = "SOURCE_BLOCKED"
        result["summary"] = {
            "observed_offers": len(offers),
            "reports": 0,
            "source_status": acquisition_status or "PARSER_FAILED",
        }
        return result
    if acquisition_status == "EMPTY" and not (
        inventory_snapshot.get("inventory_complete") is True and len(offers) == 0
    ):
        result["status"] = "SOURCE_BLOCKED"
        result["inventory"]["acquisition_status"] = "PARSER_FAILED"
        result["summary"] = {"observed_offers": len(offers), "reports": 0, "source_status": "PARSER_FAILED"}
        return result

    from proteus.providers.serpapi_amazon import collect_amazon_search
    from proteus.providers.serpapi_ebay import collect_ebay_sold

    collector_map = dict(collectors or {})
    ebay_collector = collector_map.get("ebay_demand", collect_ebay_sold)
    amazon_collector = collector_map.get("amazon_search", collect_amazon_search)
    used = 0
    reports: list[dict[str, Any]] = []
    total = len(offers)
    for index, raw_offer in enumerate(offers, start=1):
        if not isinstance(raw_offer, Mapping):
            reports.append(
                _not_run_report({}, {"status": "CATEGORY_UNMATCHED", "matches": []}, status="INVALID_OFFER", reason="INVALID_OFFER")
            )
            continue
        offer = dict(raw_offer)
        _progress(progress_callback, phase="classifying", current=index - 1, total=total, offer=offer, provider=None, budget_used=used)
        if not _supplier_matches(inventory_snapshot, offer):
            reports.append(
                _not_run_report(offer, {"status": "SUPPLIER_MISMATCH", "matches": []}, status="SUPPLIER_MISMATCH", reason="SUPPLIER_MISMATCH")
            )
            continue
        category_match = classify_supplier_offer(offer, definitions)
        if category_match["status"] != "MATCHED":
            reports.append(
                _not_run_report(offer, category_match, status=category_match["status"], reason=category_match["status"])
            )
            continue
        category_id = category_match["category_id"]
        definition = definitions[category_id]
        resolution, identifiers = _identity_candidate(offer, definition)
        if resolution.get("identity_status") != "RESOLVED" or not isinstance(resolution.get("family"), Mapping):
            report = _not_run_report(
                offer,
                category_match,
                status="IDENTITY_INCOMPLETE",
                reason="IDENTITY_INCOMPLETE",
                resolution=resolution,
            )
            report["identifiers"] = identifiers
            reports.append(report)
            continue
        if used >= market_request_budget:
            report = _not_run_report(offer, category_match, status="NOT_RUN_BUDGET", reason="MARKET_REQUEST_BUDGET_EXHAUSTED", resolution=resolution)
            report["identifiers"] = identifiers
            reports.append(report)
            continue

        family = resolution["family"]
        raw_part_number = identifiers[0]
        _progress(progress_callback, phase="ebay_demand", current=index - 1, total=total, offer=offer, provider="SERPAPI_EBAY_MANAGED", budget_used=used)
        demand = dict(ebay_collector(raw_part_number, api_key=serpapi_key or ""))
        used += 1
        demand_status = _text(demand.get("status") or demand.get("acquisition_status")).upper()
        observed = demand.get("observed_demand")
        observed_sold = (
            observed.get("aggregate_observed_sold")
            if isinstance(observed, Mapping) and isinstance(observed.get("aggregate_observed_sold"), int)
            else None
        )
        demand_rejected = bool(
            demand_status == "ZERO_RESULTS"
            or (
                demand_status == "SUCCESS"
                and isinstance(observed_sold, int)
                and observed_sold < min_observed_ebay_demand
            )
        )
        demand_passed = bool(
            demand_status in {"SUCCESS", "PARTIAL_SUCCESS"}
            and isinstance(observed_sold, int)
            and observed_sold >= min_observed_ebay_demand
        )
        query_pack = build_amazon_query_pack(
            family, max_queries=max_amazon_queries_per_family
        )
        provider_attempts = [
            {"provider": demand.get("provider"), "query": raw_part_number, "status": demand_status}
        ]
        if demand_rejected:
            reports.append(
                {
                    "offer": offer,
                    "category_match": category_match,
                    "resolution": resolution,
                    "identifiers": identifiers,
                    "demand": demand,
                    "amazon_query_pack": query_pack,
                    "competition": None,
                    "competition_grade": None,
                    "market_status": "DEMAND_REJECTED",
                    "decision": "REJECTED",
                    "evidence_gaps": [],
                    "provider_attempts": provider_attempts,
                }
            )
            continue
        amazon_results: list[dict[str, Any]] = []
        for query in query_pack:
            if used >= market_request_budget:
                amazon_results.append(
                    {
                        "provider": "NOT_RUN",
                        "query": query["query"],
                        "acquisition_status": "REQUEST_BUDGET_EXHAUSTED",
                        "result_page_complete": False,
                        "has_next_page": None,
                        "products": [],
                        "diagnostics": [{"code": "REQUEST_BUDGET_EXHAUSTED", "message": "The market request budget was exhausted."}],
                    }
                )
                provider_attempts.append(
                    {"provider": "NOT_RUN", "query": query["query"], "status": "REQUEST_BUDGET_EXHAUSTED"}
                )
                continue
            _progress(progress_callback, phase="amazon_competition", current=index - 1, total=total, offer=offer, provider="SERPAPI_AMAZON_MANAGED", budget_used=used)
            amazon = dict(amazon_collector(query["query"], api_key=serpapi_key or ""))
            used += 1
            amazon_results.append(amazon)
            provider_attempts.append(
                {"provider": amazon.get("provider"), "query": query["query"], "status": amazon.get("acquisition_status")}
            )
        competition = aggregate_amazon_family_results(
            family,
            amazon_results,
            min_family_price_usd=min_family_price_usd,
            grade_a_max_competitors=grade_a_max_competitors,
            grade_a_minus_max_competitors=grade_a_minus_max_competitors,
            category_definition=definition,
        )
        grade = competition.get("competition_grade")
        price_stage = competition.get("price_stage")
        price_status = (
            _text(price_stage.get("status")).upper()
            if isinstance(price_stage, Mapping)
            else "REVIEW_REQUIRED"
        )
        if grade == "REJECTED" or price_status == "REJECTED":
            decision = "REJECTED"
        elif demand_passed and grade in {"A", "A-"} and price_status == "PASSED":
            decision = "MARKET_SHORTLIST_CANDIDATE"
        else:
            decision = "REVIEW_REQUIRED"
        evidence_gaps: list[str] = []
        if not demand_passed and not demand_rejected:
            evidence_gaps.append("EBAY_DEMAND_INCOMPLETE")
        if grade == "PENDING":
            evidence_gaps.append("AMAZON_COMPETITION_INCOMPLETE")
        if price_status == "REVIEW_REQUIRED":
            evidence_gaps.append("AMAZON_PRICE_INCOMPLETE")
        if any(item.get("status") == "REQUEST_BUDGET_EXHAUSTED" for item in provider_attempts):
            evidence_gaps.append("MARKET_REQUEST_BUDGET_EXHAUSTED")
        reports.append(
            {
                "offer": offer,
                "category_match": category_match,
                "resolution": resolution,
                "identifiers": identifiers,
                "demand": demand,
                "amazon_query_pack": query_pack,
                "competition": competition,
                "competition_grade": grade,
                "market_status": "COMPLETED" if "MARKET_REQUEST_BUDGET_EXHAUSTED" not in evidence_gaps else "PARTIAL_BUDGET",
                "decision": decision,
                "evidence_gaps": evidence_gaps,
                "provider_attempts": provider_attempts,
            }
        )
    result["reports"] = reports
    result["market_budget"] = {
        "limit": market_request_budget,
        "used": used,
        "remaining": market_request_budget - used,
    }
    grades = Counter(report.get("competition_grade") or "NOT_GRADED" for report in reports)
    statuses = Counter(report.get("market_status") or "UNKNOWN" for report in reports)
    decisions = Counter(report.get("decision") or "UNKNOWN" for report in reports)
    result["summary"] = {
        "observed_offers": len(offers),
        "reports": len(reports),
        "inventory_complete": inventory_snapshot.get("inventory_complete") is True,
        "competition_grades": dict(grades),
        "market_statuses": dict(statuses),
        "decisions": dict(decisions),
    }
    if acquisition_status == "PARTIAL" or inventory_snapshot.get("inventory_complete") is not True:
        result["status"] = "PARTIAL_SOURCE"
    _progress(progress_callback, phase="completed", current=total, total=total, offer=None, provider=None, budget_used=used)
    return result


def compact_supplier_scout_result(result: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise TypeError("supplier scout result must be a mapping")
    reports: list[dict[str, Any]] = []
    for raw in result.get("reports", []):
        if not isinstance(raw, Mapping):
            continue
        offer = raw.get("offer") if isinstance(raw.get("offer"), Mapping) else {}
        resolution = raw.get("resolution") if isinstance(raw.get("resolution"), Mapping) else {}
        family = resolution.get("family") if isinstance(resolution.get("family"), Mapping) else None
        competition = raw.get("competition") if isinstance(raw.get("competition"), Mapping) else None
        reports.append(
            {
                "offer": {
                    key: deepcopy(offer.get(key))
                    for key in ("offer_id", "title", "offer_url", "image_url", "price_cny", "moq", "supplier")
                    if offer.get(key) is not None
                },
                "category_match": deepcopy(raw.get("category_match")),
                "identity_status": resolution.get("identity_status"),
                "family": deepcopy(family),
                "identifiers": list(raw.get("identifiers", [])) if isinstance(raw.get("identifiers"), list) else [],
                "demand": {
                    "status": (raw.get("demand") or {}).get("status"),
                    "observed_demand": deepcopy((raw.get("demand") or {}).get("observed_demand")),
                } if isinstance(raw.get("demand"), Mapping) else None,
                "competition": {
                    key: deepcopy(competition.get(key))
                    for key in (
                        "competition_grade",
                        "competitive_product_cluster_count",
                        "competitive_asin_count",
                        "family_price_floor_usd",
                        "competition_complete",
                        "competition_stage",
                        "price_stage",
                    )
                    if competition.get(key) is not None
                } if competition else None,
                "competition_grade": raw.get("competition_grade"),
                "market_status": raw.get("market_status"),
                "decision": raw.get("decision"),
                "evidence_gaps": list(raw.get("evidence_gaps", [])) if isinstance(raw.get("evidence_gaps"), list) else [],
                "provider_attempts": deepcopy(raw.get("provider_attempts", [])),
            }
        )
    return {
        "schema_version": result.get("schema_version"),
        "profile": result.get("profile"),
        "status": result.get("status"),
        "created_at": result.get("created_at"),
        "inventory": deepcopy(result.get("inventory")),
        "policy": deepcopy(result.get("policy")),
        "market_budget": deepcopy(result.get("market_budget")),
        "summary": deepcopy(result.get("summary")),
        "reports": reports,
    }


__all__ = [
    "PROFILE",
    "SCHEMA_VERSION",
    "SUPPLIER_SCOUT_DB_ENV",
    "SupplierScoutStore",
    "classify_supplier_offer",
    "compact_supplier_scout_result",
    "default_supplier_scout_db_path",
    "run_supplier_scout",
    "supplier_scout_policy",
]
