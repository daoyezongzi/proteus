"""Candidate discovery from Amazon SP-API B2B Product Opportunities CSV reports.

The module only turns report identifiers into a small, traceable candidate pool.
It does not treat an Amazon recommendation as a verified Proteus opportunity.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from io import StringIO
from pathlib import Path
from typing import Literal, Mapping, NotRequired, TypedDict

from proteus.normalization import normalize_part_number


IdentifierType = Literal["partNumber", "modelNumber", "EAN", "UPC", "ISBN"]


class DiscoveredCandidate(TypedDict):
    raw_part_number: str
    canonical_part_number: str
    identifier_type: IdentifierType
    source_field: str
    source_row: int
    brand: str | None
    category: str | None
    item_name: str | None


class DiscoveryDiagnostic(TypedDict):
    code: str
    source_row: int
    message: str
    canonical_part_number: NotRequired[str]
    duplicate_of_source_row: NotRequired[int]


class DiscoveryResult(TypedDict):
    candidates: list[DiscoveredCandidate]
    diagnostics: list[DiscoveryDiagnostic]


class CandidatePool(TypedDict):
    schema_version: str
    candidates: list[dict[str, str]]


class DiscoveryError(ValueError):
    """Raised when a report cannot be read or decoded as a CSV input."""


_IdentifierSpec = tuple[IdentifierType, frozenset[str]]
_IDENTIFIER_PRIORITY: tuple[_IdentifierSpec, ...] = (
    (
        "partNumber",
        frozenset(
            {
                "partnumber",
                "manufacturerpartnumber",
                "manufacturerpartno",
                "mpn",
            }
        ),
    ),
    ("modelNumber", frozenset({"modelnumber", "modelno"})),
    ("EAN", frozenset({"ean", "eancode", "eannumber"})),
    ("UPC", frozenset({"upc", "upccode", "upcnumber"})),
    ("ISBN", frozenset({"isbn", "isbn10", "isbn13", "isbnnumber"})),
)
_METADATA_ALIASES: dict[str, frozenset[str]] = {
    "brand": frozenset({"brand", "brandname"}),
    "category": frozenset({"category", "categoryname", "productcategory"}),
    "item_name": frozenset({"itemname", "productname", "title"}),
}
_HEADER_SEPARATOR = re.compile(r"[^a-z0-9]+")
_EXTRA_FIELDS = "__proteus_extra_csv_fields__"
_MISSING_FIELD = "\x00PROTEUS_MISSING_CSV_FIELD\x00"
_IDENTIFIER_PLACEHOLDERS = frozenset(
    {"-", "--", "n/a", "none", "null", "not available", "unknown"}
)


def _display_header(header: str) -> str:
    return header.removeprefix("\ufeff").strip()


def _normalized_header(header: str) -> str:
    return _HEADER_SEPARATOR.sub("", _display_header(header).casefold())


def _resolve_identifier_columns(
    fieldnames: list[str],
) -> dict[IdentifierType, list[tuple[str, str]]]:
    resolved: dict[IdentifierType, list[tuple[str, str]]] = {
        identifier_type: [] for identifier_type, _aliases in _IDENTIFIER_PRIORITY
    }
    for raw_header in fieldnames:
        if not isinstance(raw_header, str):
            continue
        normalized = _normalized_header(raw_header)
        for identifier_type, aliases in _IDENTIFIER_PRIORITY:
            if normalized in aliases:
                resolved[identifier_type].append(
                    (raw_header, _display_header(raw_header))
                )
                break
    return resolved


def _resolve_metadata_columns(fieldnames: list[str]) -> dict[str, list[str]]:
    resolved = {field_name: [] for field_name in _METADATA_ALIASES}
    for raw_header in fieldnames:
        if not isinstance(raw_header, str):
            continue
        normalized = _normalized_header(raw_header)
        for field_name, aliases in _METADATA_ALIASES.items():
            if normalized in aliases:
                resolved[field_name].append(raw_header)
                break
    return resolved


def _metadata_value(row: Mapping[str | None, object], columns: list[str]) -> str | None:
    for raw_header in columns:
        value = row.get(raw_header)
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        if text.casefold() not in _IDENTIFIER_PLACEHOLDERS:
            return text
    return None


def _normalize_category_allowlist(
    category_allowlist: Iterable[str] | None,
) -> frozenset[str] | None:
    if category_allowlist is None:
        return None
    if isinstance(category_allowlist, (str, bytes)):
        raise TypeError("category_allowlist must be an iterable of category strings")

    normalized: set[str] = set()
    for category in category_allowlist:
        if not isinstance(category, str):
            raise TypeError("category_allowlist entries must be strings")
        if not category.strip():
            raise ValueError("category_allowlist entries must not be empty")
        normalized.add(category.strip().casefold())
    return frozenset(normalized)


def _select_identifier(
    row: Mapping[str | None, object],
    columns: Mapping[IdentifierType, list[tuple[str, str]]],
) -> tuple[str, str, IdentifierType, str] | None:
    for identifier_type, _aliases in _IDENTIFIER_PRIORITY:
        for raw_header, source_field in columns[identifier_type]:
            value = row.get(raw_header)
            if not isinstance(value, str) or not value.strip():
                continue
            raw_identifier = value.strip()
            if raw_identifier.casefold() in _IDENTIFIER_PLACEHOLDERS:
                continue
            try:
                canonical = normalize_part_number(raw_identifier)
            except (TypeError, ValueError):
                continue
            return raw_identifier, canonical, identifier_type, source_field
    return None


def _diagnostic(code: str, source_row: int, message: str) -> DiscoveryDiagnostic:
    return {"code": code, "source_row": source_row, "message": message}


def _parse_csv_text(
    text: str,
    *,
    allowed_categories: frozenset[str] | None,
) -> DiscoveryResult:
    stream = StringIO(text.removeprefix("\ufeff"), newline="")
    reader = csv.DictReader(
        stream,
        restkey=_EXTRA_FIELDS,
        restval=_MISSING_FIELD,
        strict=True,
    )
    try:
        fieldnames = reader.fieldnames
    except csv.Error as exc:
        return {
            "candidates": [],
            "diagnostics": [
                _diagnostic(
                    "MALFORMED_CSV",
                    max(reader.line_num, 1),
                    f"The CSV header could not be parsed: {exc}.",
                )
            ],
        }

    if fieldnames is None:
        return {
            "candidates": [],
            "diagnostics": [
                _diagnostic("EMPTY_REPORT", 1, "The CSV report has no header row.")
            ],
        }

    columns = _resolve_identifier_columns(fieldnames)
    metadata_columns = _resolve_metadata_columns(fieldnames)
    candidates: list[DiscoveredCandidate] = []
    diagnostics: list[DiscoveryDiagnostic] = []
    if not any(columns.values()):
        diagnostics.append(
            _diagnostic(
                "MISSING_IDENTIFIER_COLUMNS",
                1,
                "The CSV header has no supported identifier columns.",
            )
        )

    first_seen_rows: dict[str, int] = {}
    while True:
        try:
            row = next(reader)
        except StopIteration:
            break
        except csv.Error as exc:
            diagnostics.append(
                _diagnostic(
                    "ROW_SKIPPED_MALFORMED_CSV",
                    max(reader.line_num, 2),
                    f"CSV parsing failed for this row: {exc}.",
                )
            )
            break

        source_row = reader.line_num
        extra_fields = row.get(_EXTRA_FIELDS)
        missing_fields = any(value == _MISSING_FIELD for value in row.values())
        if extra_fields or missing_fields:
            diagnostics.append(
                _diagnostic(
                    "ROW_SKIPPED_MALFORMED_CSV",
                    source_row,
                    "The CSV row has a different number of fields than the header.",
                )
            )
            continue

        brand = _metadata_value(row, metadata_columns["brand"])
        category = _metadata_value(row, metadata_columns["category"])
        item_name = _metadata_value(row, metadata_columns["item_name"])
        if allowed_categories is not None:
            if category is None:
                diagnostics.append(
                    _diagnostic(
                        "ROW_SKIPPED_CATEGORY_NOT_ALLOWED",
                        source_row,
                        "The row category is missing while category filtering is enabled.",
                    )
                )
                continue
            if category.casefold() not in allowed_categories:
                diagnostics.append(
                    _diagnostic(
                        "ROW_SKIPPED_CATEGORY_NOT_ALLOWED",
                        source_row,
                        f"Category {category!r} is not in the configured allowlist.",
                    )
                )
                continue

        selected = _select_identifier(row, columns)
        if selected is None:
            diagnostics.append(
                _diagnostic(
                    "ROW_SKIPPED_NO_USABLE_IDENTIFIER",
                    source_row,
                    "The row has no usable partNumber, modelNumber, EAN, UPC, or ISBN.",
                )
            )
            continue

        raw_identifier, canonical, identifier_type, source_field = selected
        if canonical in first_seen_rows:
            first_row = first_seen_rows[canonical]
            duplicate = _diagnostic(
                "ROW_SKIPPED_DUPLICATE_IDENTIFIER",
                source_row,
                f"Identifier normalizes to a candidate already discovered on row {first_row}.",
            )
            duplicate["canonical_part_number"] = canonical
            duplicate["duplicate_of_source_row"] = first_row
            diagnostics.append(duplicate)
            continue

        first_seen_rows[canonical] = source_row
        candidates.append(
            {
                "raw_part_number": raw_identifier,
                "canonical_part_number": canonical,
                "identifier_type": identifier_type,
                "source_field": source_field,
                "source_row": source_row,
                "brand": brand,
                "category": category,
                "item_name": item_name,
            }
        )

    return {"candidates": candidates, "diagnostics": diagnostics}


def parse_b2b_product_opportunities_csv(
    csv_data: str | bytes,
    *,
    category_allowlist: Iterable[str] | None = None,
) -> DiscoveryResult:
    """Parse UTF-8 or UTF-8-sig B2B Product Opportunities CSV content.

    Rows are evaluated in report order. Within each row, the stable identifier
    priority is partNumber, modelNumber, EAN, UPC, then ISBN.
    """

    if isinstance(csv_data, bytes):
        try:
            text = csv_data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DiscoveryError("CSV data must be UTF-8 or UTF-8-sig") from exc
    elif isinstance(csv_data, str):
        text = csv_data
    else:
        raise TypeError("csv_data must be str or bytes")
    return _parse_csv_text(
        text,
        allowed_categories=_normalize_category_allowlist(category_allowlist),
    )


def discover_candidates_from_csv(
    path: str | Path,
    *,
    category_allowlist: Iterable[str] | None = None,
) -> DiscoveryResult:
    """Read and parse one downloaded SP-API B2B opportunities CSV file."""

    source = Path(path)
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise DiscoveryError(f"cannot read CSV report {source}: {exc}") from exc
    try:
        return parse_b2b_product_opportunities_csv(
            data,
            category_allowlist=category_allowlist,
        )
    except DiscoveryError as exc:
        raise DiscoveryError(f"CSV report {source} must be UTF-8 or UTF-8-sig") from exc


def to_candidate_pool(result: Mapping[str, object]) -> CandidatePool:
    """Convert discovery output to the candidate-pool shape accepted by V0.2."""

    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("discovery result must contain a candidates array")

    entries: list[dict[str, str]] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise ValueError(f"discovery candidate {index} must be an object")
        raw_part_number = candidate.get("raw_part_number")
        if not isinstance(raw_part_number, str) or not raw_part_number.strip():
            raise ValueError(
                f"discovery candidate {index} needs a non-empty raw_part_number"
            )
        entries.append({"raw_part_number": raw_part_number.strip()})

    return {"schema_version": "0.2", "candidates": entries}


__all__ = [
    "CandidatePool",
    "DiscoveredCandidate",
    "DiscoveryDiagnostic",
    "DiscoveryError",
    "DiscoveryResult",
    "discover_candidates_from_csv",
    "parse_b2b_product_opportunities_csv",
    "to_candidate_pool",
]
