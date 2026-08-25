"""Deterministic OEM/MPN normalization used by the V0.1 pipeline."""

from __future__ import annotations

import re


_NON_ASCII_ALPHANUMERIC = re.compile(r"[^A-Z0-9]+")


def normalize_part_number(raw_part_number: str) -> str:
    """Return the uppercase alphanumeric canonical form of a part number.

    V0.1 deliberately performs no cross-reference or replacement inference.
    Separators and surrounding whitespace are removed; every other semantic
    relationship remains evidence that requires a separate gate decision.
    """

    if not isinstance(raw_part_number, str):
        raise TypeError("raw_part_number must be a string")

    canonical = _NON_ASCII_ALPHANUMERIC.sub("", raw_part_number.upper())
    if not canonical:
        raise ValueError("raw_part_number must contain at least one ASCII letter or digit")
    return canonical


def build_part_query(raw_part_number: str) -> dict:
    """Build the part-query object shared by both V0.1 JSON schemas."""

    if not isinstance(raw_part_number, str):
        raise TypeError("raw_part_number must be a string")
    raw = raw_part_number.strip()
    if not raw:
        raise ValueError("raw_part_number must not be empty")
    return {
        "raw_part_number": raw,
        "canonical_part_number": normalize_part_number(raw),
        "query_type": "EXACT_PART_NUMBER",
    }
