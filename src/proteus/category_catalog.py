"""Versioned, single-user category catalog for the Northway screening flow."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from importlib import resources
import json
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock
from typing import Any
from uuid import uuid4

from proteus.io import ContractValidationError, validate_json_contract


CATEGORY_SCHEMA_VERSION = "0.2.5"
CATEGORY_DEFINITION_SCHEMA = "v0_2_5_category_definition.schema.json"
CATEGORY_VALIDATOR_VERSION = "category-validator-v1"
CATEGORY_DB_ENV = "PROTEUS_CATEGORY_DB"

SUPPORTED_IDENTITY_PROFILES = frozenset(
    {
        "vehicle_specific_small_trim",
        "vehicle_specific_cable",
    }
)
SUPPORTED_CAPABILITIES = frozenset(
    {
        "PART_TYPE_ALIAS_MATCH",
        "PART_IDENTIFIER",
        "VEHICLE_FITMENT",
        "SIDE",
        "POSITION",
        "PACKAGE_QUANTITY",
        "ENGINE_TRANSMISSION",
    }
)

_BLOCKED_RISK_TERMS = (
    "airbag",
    "brake",
    "steering",
    "seat belt",
    "suspension control",
    "fuel line",
)
_OUT_OF_SCOPE_TITLE_TERMS = (
    "universal",
    "cleaner",
    "cleaning kit",
    "chemical",
    "polish",
    "brake",
    "steering",
    "airbag",
    "headlight assembly",
    "tail light assembly",
    "led assembly",
    "complete assembly",
)


class CategoryCatalogError(RuntimeError):
    """Base error for category catalog operations."""


class CategoryDefinitionError(CategoryCatalogError):
    """Raised when a definition cannot be stored as a draft."""


class CategoryNotFoundError(CategoryCatalogError):
    """Raised when a category or version does not exist."""


class CategoryActivationError(CategoryCatalogError):
    """Raised when an explicit activation fails conservative validation."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _definition_hash(definition: Mapping[str, Any]) -> str:
    return sha256(_canonical_json(definition).encode("utf-8")).hexdigest()


def default_category_db_path() -> Path:
    """Return the local per-user database path, with one explicit test override."""

    override = os.environ.get(CATEGORY_DB_ENV)
    if isinstance(override, str) and override.strip():
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if isinstance(base, str) and base.strip() else Path.home()
        return root / "Proteus" / "categories.sqlite3"
    xdg = os.environ.get("XDG_DATA_HOME")
    root = (
        Path(xdg)
        if isinstance(xdg, str) and xdg.strip()
        else Path.home() / ".local" / "share"
    )
    return root / "proteus" / "categories.sqlite3"


@lru_cache(maxsize=1)
def _seed_document_cached() -> dict[str, Any]:
    text = (
        resources.files("proteus")
        .joinpath("data/northway_categories.seed.json")
        .read_text(encoding="utf-8")
    )
    value = json.loads(text)
    if not isinstance(value, dict):
        raise CategoryDefinitionError("category seed document must be an object")
    return value


def load_seed_document() -> dict[str, Any]:
    """Return an isolated copy of the packaged category seed document."""

    return deepcopy(_seed_document_cached())


def seed_version_id(category_id: str) -> str:
    return f"seed.{category_id}.v1"


def runtime_category_definition(
    definition: Mapping[str, Any],
    *,
    version_id: str,
    version_number: int,
    status: str = "ACTIVE",
) -> dict[str, Any]:
    """Translate an Agent-facing definition into the runner's compact profile."""

    discovery = definition.get("discovery")
    supply = definition.get("supply")
    group = definition.get("group")
    queries = (
        list(discovery.get("queries", []))
        if isinstance(discovery, Mapping)
        else []
    )
    return {
        "category_id": definition.get("category_id"),
        "profile": definition.get("identity_profile"),
        "part_type": definition.get("part_type"),
        "aliases": tuple(definition.get("aliases", [])),
        "discovery_keyword": queries[0] if queries else "",
        "discovery_queries": tuple(queries),
        "ebay_category_id": discovery.get("ebay_category_id")
        if isinstance(discovery, Mapping)
        else None,
        "group_id": group.get("group_id") if isinstance(group, Mapping) else None,
        "group_label_zh": group.get("label_zh")
        if isinstance(group, Mapping)
        else None,
        "group_label_en": group.get("label_en")
        if isinstance(group, Mapping)
        else None,
        "label_zh": definition.get("label_zh"),
        "label_en": definition.get("label_en"),
        "display_order": definition.get("display_order", 0),
        "material_family": definition.get("material_family"),
        "supply_keywords": tuple(
            supply.get("keywords", []) if isinstance(supply, Mapping) else []
        ),
        "supply_aliases": tuple(
            supply.get("aliases", []) if isinstance(supply, Mapping) else []
        ),
        "required_capabilities": tuple(
            definition.get("required_capabilities", [])
        ),
        "risk": deepcopy(definition.get("risk")),
        "category_version_id": version_id,
        "category_version_number": version_number,
        "category_version_status": status,
    }


def builtin_runtime_categories() -> dict[str, dict[str, Any]]:
    """Return seed profiles for direct runner use outside the API catalog."""

    categories: dict[str, dict[str, Any]] = {}
    for definition in load_seed_document().get("categories", []):
        if not isinstance(definition, Mapping):
            continue
        category_id = str(definition.get("category_id") or "")
        categories[category_id] = runtime_category_definition(
            definition,
            version_id=seed_version_id(category_id),
            version_number=1,
        )
    return categories


def _public_catalog_payload(
    definitions: Mapping[str, Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    *,
    maintenance_mode: str,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for category_id, value in definitions.items():
        grouped.setdefault(str(value["group_id"]), []).append(
            {
                "category_id": category_id,
                "category_version_id": value["category_version_id"],
                "category_version_number": value["category_version_number"],
                "label_zh": value["label_zh"],
                "label_en": value["label_en"],
                "part_type": value["part_type"],
                "identity_profile": value["profile"],
                "material_family": value["material_family"],
                "discovery_keyword": value["discovery_keyword"],
                "display_order": value["display_order"],
            }
        )
    public_groups: list[dict[str, Any]] = []
    for row in sorted(
        groups,
        key=lambda item: (int(item["display_order"]), str(item["group_id"])),
    ):
        categories = sorted(
            grouped.get(str(row["group_id"]), []),
            key=lambda item: (item["display_order"], item["category_id"]),
        )
        public_groups.append(
            {
                "group_id": row["group_id"],
                "label_zh": row["label_zh"],
                "label_en": row["label_en"],
                "display_order": int(row["display_order"]),
                "categories": categories,
            }
        )
    revision_input = "|".join(
        str(definitions[key]["category_version_id"])
        for key in sorted(definitions)
    )
    return {
        "schema_version": CATEGORY_SCHEMA_VERSION,
        "maintenance_mode": maintenance_mode,
        "activation_policy": "explicit",
        "catalog_revision": sha256(revision_input.encode("utf-8")).hexdigest()[:16],
        "groups": public_groups,
    }


def builtin_public_catalog() -> dict[str, Any]:
    """Return the packaged active catalog without creating a local database."""

    document = load_seed_document()
    groups = [
        item for item in document.get("groups", []) if isinstance(item, Mapping)
    ]
    return _public_catalog_payload(
        builtin_runtime_categories(),
        groups,
        maintenance_mode="packaged_seed",
    )


def _casefold_duplicates(values: Sequence[Any]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        folded = re.sub(r"\s+", " ", raw).strip().casefold()
        if folded in seen:
            duplicates.add(raw)
        seen.add(folded)
    return sorted(duplicates)


def _title_matches_definition(title: str, definition: Mapping[str, Any]) -> bool:
    folded = re.sub(r"\s+", " ", title).strip().casefold()
    aliases = [
        str(value).strip().casefold()
        for value in definition.get("aliases", [])
        if isinstance(value, str) and value.strip()
    ]
    return bool(
        folded
        and not any(term in folded for term in _OUT_OF_SCOPE_TITLE_TERMS)
        and any(alias in folded for alias in aliases)
    )


def validate_category_definition(definition: Any) -> dict[str, Any]:
    """Run schema, capability, risk and example checks without provider calls."""

    validated_at = _utc_now()
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    capability_gaps: list[str] = []
    example_results: list[dict[str, Any]] = []
    schema_valid = True
    try:
        validate_json_contract(
            definition,
            CATEGORY_DEFINITION_SCHEMA,
            "category definition",
        )
    except ContractValidationError as exc:
        schema_valid = False
        errors.append(
            {
                "code": "CATEGORY_SCHEMA_INVALID",
                "message": str(exc),
            }
        )

    category_id = (
        str(definition.get("category_id") or "")
        if isinstance(definition, Mapping)
        else ""
    )
    if schema_valid and isinstance(definition, Mapping):
        aliases = list(definition.get("aliases", []))
        if _casefold_duplicates(aliases):
            errors.append(
                {
                    "code": "CATEGORY_ALIASES_CASE_INSENSITIVE_DUPLICATE",
                    "message": "aliases must also be unique after case folding",
                }
            )
        part_type = str(definition.get("part_type") or "").strip().casefold()
        if part_type not in {
            str(value).strip().casefold() for value in aliases if isinstance(value, str)
        }:
            errors.append(
                {
                    "code": "CATEGORY_PART_TYPE_ALIAS_MISSING",
                    "message": "aliases must contain the canonical part_type",
                }
            )

        identity_profile = str(definition.get("identity_profile") or "")
        if identity_profile not in SUPPORTED_IDENTITY_PROFILES:
            capability_gaps.append(f"IDENTITY_PROFILE:{identity_profile}")
        required = {
            str(value)
            for value in definition.get("required_capabilities", [])
            if isinstance(value, str)
        }
        capability_gaps.extend(sorted(required - SUPPORTED_CAPABILITIES))

        discovery = definition.get("discovery")
        queries = (
            list(discovery.get("queries", []))
            if isinstance(discovery, Mapping)
            else []
        )
        if len(queries) != 1:
            capability_gaps.append("MULTI_DISCOVERY_QUERY_EXECUTION")

        risk = definition.get("risk")
        risk_level = risk.get("level") if isinstance(risk, Mapping) else None
        if risk_level != "LOW":
            errors.append(
                {
                    "code": "CATEGORY_RISK_NOT_LOW",
                    "message": "only LOW-risk definitions are activation eligible",
                }
            )
        core_text = " ".join(
            [
                str(definition.get("part_type") or ""),
                *(str(value) for value in aliases),
                *(str(value) for value in queries),
            ]
        ).casefold()
        blocked = sorted({term for term in _BLOCKED_RISK_TERMS if term in core_text})
        if blocked:
            errors.append(
                {
                    "code": "CATEGORY_BLOCKED_RISK_TERM",
                    "message": f"blocked risk terms present: {', '.join(blocked)}",
                }
            )

        examples = definition.get("examples")
        positive = (
            list(examples.get("positive_titles", []))
            if isinstance(examples, Mapping)
            else []
        )
        negative = (
            list(examples.get("negative_titles", []))
            if isinstance(examples, Mapping)
            else []
        )
        for title in positive:
            matched = _title_matches_definition(str(title), definition)
            example_results.append(
                {"kind": "POSITIVE", "title": title, "matched": matched}
            )
            if not matched:
                errors.append(
                    {
                        "code": "CATEGORY_POSITIVE_EXAMPLE_FAILED",
                        "message": f"positive example did not match: {title}",
                    }
                )
        for title in negative:
            matched = _title_matches_definition(str(title), definition)
            example_results.append(
                {"kind": "NEGATIVE", "title": title, "matched": matched}
            )
            if matched:
                errors.append(
                    {
                        "code": "CATEGORY_NEGATIVE_EXAMPLE_FAILED",
                        "message": f"negative example matched unexpectedly: {title}",
                    }
                )

        supply = definition.get("supply")
        supply_aliases = {
            str(value).strip().casefold()
            for value in (
                supply.get("aliases", []) if isinstance(supply, Mapping) else []
            )
            if isinstance(value, str)
        }
        if not supply_aliases.intersection(
            str(value).strip().casefold()
            for value in aliases
            if isinstance(value, str)
        ):
            warnings.append(
                {
                    "code": "CATEGORY_SUPPLY_ALIAS_DISJOINT",
                    "message": "supply aliases do not overlap marketplace aliases",
                }
            )

    capability_gaps = sorted(set(capability_gaps))
    activation_eligible = bool(
        schema_valid and not errors and not capability_gaps
    )
    definition_sha256 = (
        _definition_hash(definition)
        if schema_valid and isinstance(definition, Mapping)
        else None
    )
    return {
        "schema_version": CATEGORY_SCHEMA_VERSION,
        "validator_version": CATEGORY_VALIDATOR_VERSION,
        "validated_at": validated_at,
        "category_id": category_id,
        "definition_sha256": definition_sha256,
        "schema_valid": schema_valid,
        "activation_eligible": activation_eligible,
        "external_requests": 0,
        "errors": errors,
        "warnings": warnings,
        "capability_gaps": capability_gaps,
        "example_results": example_results,
    }


class CategoryCatalog:
    """SQLite-backed immutable category versions with explicit activation."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        self.database_path = Path(database_path or default_category_db_path()).resolve()
        self._initialization_lock = Lock()
        self._initialized = False
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        with self._initialization_lock:
            if self._initialized:
                return
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS category_groups (
                        group_id TEXT PRIMARY KEY,
                        label_zh TEXT NOT NULL,
                        label_en TEXT NOT NULL,
                        display_order INTEGER NOT NULL,
                        visible INTEGER NOT NULL DEFAULT 0 CHECK (visible IN (0, 1)),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS categories (
                        category_id TEXT PRIMARY KEY,
                        group_id TEXT NOT NULL REFERENCES category_groups(group_id),
                        active_version_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        archived_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS category_versions (
                        version_id TEXT PRIMARY KEY,
                        category_id TEXT NOT NULL REFERENCES categories(category_id),
                        version_number INTEGER NOT NULL,
                        status TEXT NOT NULL CHECK (
                            status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'ARCHIVED')
                        ),
                        definition_json TEXT NOT NULL,
                        definition_sha256 TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        UNIQUE (category_id, version_number)
                    );

                    CREATE UNIQUE INDEX IF NOT EXISTS one_active_category_version
                    ON category_versions(category_id)
                    WHERE status = 'ACTIVE';

                    CREATE TABLE IF NOT EXISTS category_validations (
                        validation_id TEXT PRIMARY KEY,
                        version_id TEXT REFERENCES category_versions(version_id),
                        category_id TEXT NOT NULL,
                        validator_version TEXT NOT NULL,
                        validated_at TEXT NOT NULL,
                        activation_eligible INTEGER NOT NULL CHECK (
                            activation_eligible IN (0, 1)
                        ),
                        report_json TEXT NOT NULL
                    );

                    CREATE TRIGGER IF NOT EXISTS category_versions_definition_immutable
                    BEFORE UPDATE OF category_id, version_number, definition_json,
                        definition_sha256 ON category_versions
                    BEGIN
                        SELECT RAISE(ABORT, 'category version definitions are immutable');
                    END;
                    """
                )
                self._seed(connection)
            self._initialized = True

    def _seed(self, connection: sqlite3.Connection) -> None:
        document = load_seed_document()
        if document.get("schema_version") != CATEGORY_SCHEMA_VERSION:
            raise CategoryDefinitionError("unsupported category seed schema version")
        now = _utc_now()
        for group in document.get("groups", []):
            if not isinstance(group, Mapping):
                continue
            connection.execute(
                """
                INSERT INTO category_groups(
                    group_id, label_zh, label_en, display_order, visible,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    label_zh = excluded.label_zh,
                    label_en = excluded.label_en,
                    display_order = excluded.display_order,
                    visible = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    group["group_id"],
                    group["label_zh"],
                    group["label_en"],
                    group["display_order"],
                    now,
                    now,
                ),
            )
        for definition in document.get("categories", []):
            if not isinstance(definition, Mapping):
                continue
            report = validate_category_definition(definition)
            if not report["activation_eligible"]:
                raise CategoryDefinitionError(
                    f"packaged category {definition.get('category_id')} is not activation eligible"
                )
            category_id = str(definition["category_id"])
            existing = connection.execute(
                "SELECT category_id FROM categories WHERE category_id = ?",
                (category_id,),
            ).fetchone()
            if existing is not None:
                continue
            group_id = str(definition["group"]["group_id"])
            version_id = seed_version_id(category_id)
            connection.execute(
                """
                INSERT INTO categories(
                    category_id, group_id, active_version_id, created_at,
                    updated_at, archived_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (category_id, group_id, version_id, now, now),
            )
            connection.execute(
                """
                INSERT INTO category_versions(
                    version_id, category_id, version_number, status,
                    definition_json, definition_sha256, created_at
                ) VALUES (?, ?, 1, 'ACTIVE', ?, ?, ?)
                """,
                (
                    version_id,
                    category_id,
                    _canonical_json(definition),
                    report["definition_sha256"],
                    now,
                ),
            )
            self._insert_validation(connection, version_id, report)
        connection.execute(
            """
            INSERT INTO catalog_meta(key, value) VALUES ('seed_revision', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(document.get("seed_revision", 1)),),
        )

    @staticmethod
    def _insert_validation(
        connection: sqlite3.Connection,
        version_id: str | None,
        report: Mapping[str, Any],
    ) -> str:
        validation_id = f"catval_{uuid4().hex}"
        connection.execute(
            """
            INSERT INTO category_validations(
                validation_id, version_id, category_id, validator_version,
                validated_at, activation_eligible, report_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                validation_id,
                version_id,
                report.get("category_id", ""),
                report.get("validator_version", CATEGORY_VALIDATOR_VERSION),
                report.get("validated_at", _utc_now()),
                1 if report.get("activation_eligible") else 0,
                _canonical_json(report),
            ),
        )
        return validation_id

    def create_draft(self, definition: Any) -> dict[str, Any]:
        report = validate_category_definition(definition)
        if not report["schema_valid"] or not isinstance(definition, Mapping):
            raise CategoryDefinitionError(report["errors"][0]["message"])
        category_id = str(definition["category_id"])
        group = definition["group"]
        group_id = str(group["group_id"])
        now = _utc_now()
        version_id = f"catv_{uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO category_groups(
                    group_id, label_zh, label_en, display_order, visible,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?, ?)
                """,
                (
                    group_id,
                    group["label_zh"],
                    group["label_en"],
                    group["display_order"],
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO categories(
                    category_id, group_id, active_version_id, created_at,
                    updated_at, archived_at
                ) VALUES (?, ?, NULL, ?, ?, NULL)
                """,
                (category_id, group_id, now, now),
            )
            row = connection.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM category_versions WHERE category_id = ?
                """,
                (category_id,),
            ).fetchone()
            version_number = int(row["next_version"])
            connection.execute(
                """
                INSERT INTO category_versions(
                    version_id, category_id, version_number, status,
                    definition_json, definition_sha256, created_at
                ) VALUES (?, ?, ?, 'DRAFT', ?, ?, ?)
                """,
                (
                    version_id,
                    category_id,
                    version_number,
                    _canonical_json(definition),
                    report["definition_sha256"],
                    now,
                ),
            )
            validation_id = self._insert_validation(connection, version_id, report)
        return {
            "category_id": category_id,
            "version_id": version_id,
            "version_number": version_number,
            "status": "DRAFT",
            "validation_id": validation_id,
            "validation": report,
        }

    def _version_row(self, version_id: str) -> sqlite3.Row:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM category_versions WHERE version_id = ?",
                (version_id,),
            ).fetchone()
        if row is None:
            raise CategoryNotFoundError(f"category version not found: {version_id}")
        return row

    def activate(self, category_id: str, version_id: str) -> dict[str, Any]:
        row = self._version_row(version_id)
        if row["category_id"] != category_id:
            raise CategoryActivationError(
                f"version {version_id} does not belong to category {category_id}"
            )
        definition = json.loads(row["definition_json"])
        report = validate_category_definition(definition)
        with self._connect() as connection:
            validation_id = self._insert_validation(connection, version_id, report)
        if not report["activation_eligible"]:
            gaps = [
                *(item["code"] for item in report["errors"]),
                *report["capability_gaps"],
            ]
            raise CategoryActivationError(
                "category version is not activation eligible: "
                + ", ".join(gaps or ["validation failed"])
            )
        group = definition["group"]
        now = _utc_now()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT active_version_id FROM categories WHERE category_id = ?",
                (category_id,),
            ).fetchone()
            if current is None:
                raise CategoryNotFoundError(f"category not found: {category_id}")
            previous = current["active_version_id"]
            if previous and previous != version_id:
                connection.execute(
                    """
                    UPDATE category_versions SET status = 'SUPERSEDED'
                    WHERE version_id = ? AND status = 'ACTIVE'
                    """,
                    (previous,),
                )
            connection.execute(
                "UPDATE category_versions SET status = 'ACTIVE' WHERE version_id = ?",
                (version_id,),
            )
            connection.execute(
                """
                INSERT INTO category_groups(
                    group_id, label_zh, label_en, display_order, visible,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    label_zh = excluded.label_zh,
                    label_en = excluded.label_en,
                    display_order = excluded.display_order,
                    visible = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    group["group_id"],
                    group["label_zh"],
                    group["label_en"],
                    group["display_order"],
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE categories
                SET group_id = ?, active_version_id = ?, updated_at = ?, archived_at = NULL
                WHERE category_id = ?
                """,
                (group["group_id"], version_id, now, category_id),
            )
        return {
            "category_id": category_id,
            "version_id": version_id,
            "version_number": int(row["version_number"]),
            "status": "ACTIVE",
            "previous_active_version_id": previous,
            "validation_id": validation_id,
            "validation": report,
        }

    def archive(self, category_id: str) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT active_version_id FROM categories WHERE category_id = ?",
                (category_id,),
            ).fetchone()
            if row is None:
                raise CategoryNotFoundError(f"category not found: {category_id}")
            active_version_id = row["active_version_id"]
            if active_version_id:
                connection.execute(
                    "UPDATE category_versions SET status = 'ARCHIVED' WHERE version_id = ?",
                    (active_version_id,),
                )
            connection.execute(
                """
                UPDATE categories
                SET active_version_id = NULL, archived_at = ?, updated_at = ?
                WHERE category_id = ?
                """,
                (now, now, category_id),
            )
        return {
            "category_id": category_id,
            "archived_version_id": active_version_id,
            "status": "ARCHIVED",
        }

    @staticmethod
    def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "category_id": row["category_id"],
            "version_id": row["version_id"],
            "version_number": int(row["version_number"]),
            "status": row["status"],
            "definition_sha256": row["definition_sha256"],
            "created_at": row["created_at"],
            "definition": json.loads(row["definition_json"]),
        }

    def get_version(self, version_id: str) -> dict[str, Any]:
        return self._row_payload(self._version_row(version_id))

    def get_active_definition(self, category_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT v.* FROM categories c
                JOIN category_versions v ON v.version_id = c.active_version_id
                WHERE c.category_id = ? AND c.archived_at IS NULL
                """,
                (category_id,),
            ).fetchone()
        if row is None:
            raise CategoryNotFoundError(
                f"active category not found: {category_id}"
            )
        return self._row_payload(row)

    def list_versions(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT v.* FROM category_versions v
                ORDER BY v.category_id, v.version_number DESC
                """
            ).fetchall()
        return {
            "database": str(self.database_path),
            "versions": [self._row_payload(row) for row in rows],
        }

    def active_runtime_definitions(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT v.* FROM categories c
                JOIN category_versions v ON v.version_id = c.active_version_id
                WHERE c.archived_at IS NULL AND v.status = 'ACTIVE'
                ORDER BY c.category_id
                """
            ).fetchall()
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            definition = json.loads(row["definition_json"])
            result[row["category_id"]] = runtime_category_definition(
                definition,
                version_id=row["version_id"],
                version_number=int(row["version_number"]),
                status=row["status"],
            )
        return result

    def public_active_catalog(self) -> dict[str, Any]:
        definitions = self.active_runtime_definitions()
        with self._connect() as connection:
            groups = connection.execute(
                """
                SELECT group_id, label_zh, label_en, display_order
                FROM category_groups WHERE visible = 1
                ORDER BY display_order, group_id
                """
            ).fetchall()
        return _public_catalog_payload(
            definitions,
            [dict(row) for row in groups],
            maintenance_mode="agent_cli",
        )


__all__ = [
    "CATEGORY_DB_ENV",
    "CATEGORY_DEFINITION_SCHEMA",
    "CATEGORY_SCHEMA_VERSION",
    "CategoryActivationError",
    "CategoryCatalog",
    "CategoryCatalogError",
    "CategoryDefinitionError",
    "CategoryNotFoundError",
    "SUPPORTED_CAPABILITIES",
    "SUPPORTED_IDENTITY_PROFILES",
    "builtin_public_catalog",
    "builtin_runtime_categories",
    "default_category_db_path",
    "load_seed_document",
    "runtime_category_definition",
    "seed_version_id",
    "validate_category_definition",
]
