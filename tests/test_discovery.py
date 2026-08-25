from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from proteus.discovery import (  # noqa: E402
    DiscoveryError,
    discover_candidates_from_csv,
    parse_b2b_product_opportunities_csv,
    to_candidate_pool,
)


def test_identifier_priority_and_fallback_order() -> None:
    report = """partNumber,modelNumber,ean,upc,isbn,itemName
PN-100,MODEL-100,4006381333931,012345678905,9780306406157,All identifiers
,MODEL-200,4006381333932,012345678906,9780306406158,Model fallback
,,4006381333933,012345678907,9780306406159,EAN fallback
,,,012345678908,9780306406160,UPC fallback
,,,,9780306406161,ISBN fallback
"""

    result = parse_b2b_product_opportunities_csv(report)

    assert [candidate["raw_part_number"] for candidate in result["candidates"]] == [
        "PN-100",
        "MODEL-200",
        "4006381333933",
        "012345678908",
        "9780306406161",
    ]
    assert [candidate["identifier_type"] for candidate in result["candidates"]] == [
        "partNumber",
        "modelNumber",
        "EAN",
        "UPC",
        "ISBN",
    ]
    assert [candidate["source_row"] for candidate in result["candidates"]] == [
        2,
        3,
        4,
        5,
        6,
    ]
    assert [candidate["item_name"] for candidate in result["candidates"]] == [
        "All identifiers",
        "Model fallback",
        "EAN fallback",
        "UPC fallback",
        "ISBN fallback",
    ]
    assert result["diagnostics"] == []


def test_utf8_sig_and_header_aliases_are_supported(tmp_path: Path) -> None:
    csv_path = tmp_path / "b2b-opportunities.csv"
    csv_path.write_bytes(
        (
            "Manufacturer Part Number,Model_Number,EAN Code,UPC Code,ISBN-13\n"
            "A18-67004-004,ignored,4006381333931,012345678905,9780306406157\n"
        ).encode("utf-8-sig")
    )

    result = discover_candidates_from_csv(csv_path)

    assert result["candidates"] == [
        {
            "raw_part_number": "A18-67004-004",
            "canonical_part_number": "A1867004004",
            "identifier_type": "partNumber",
            "source_field": "Manufacturer Part Number",
            "source_row": 2,
            "brand": None,
            "category": None,
            "item_name": None,
        }
    ]


def test_mpn_alias_and_plain_utf8_file_are_supported(tmp_path: Path) -> None:
    csv_path = tmp_path / "plain.csv"
    csv_path.write_text("MPN,itemName\n53630-53010,Steering part\n", encoding="utf-8")

    result = discover_candidates_from_csv(csv_path)

    assert result["candidates"][0]["identifier_type"] == "partNumber"
    assert result["candidates"][0]["source_field"] == "MPN"
    assert result["candidates"][0]["canonical_part_number"] == "5363053010"


@pytest.mark.parametrize(
    ("header", "value", "identifier_type"),
    [
        ("Model No", "MODEL-7", "modelNumber"),
        ("EAN_Number", "4006381333931", "EAN"),
        ("UPC-number", "012345678905", "UPC"),
        ("ISBN 10", "0306406152", "ISBN"),
    ],
)
def test_each_identifier_type_accepts_common_header_aliases(
    header: str, value: str, identifier_type: str
) -> None:
    result = parse_b2b_product_opportunities_csv(f"{header}\n{value}\n")

    assert result["candidates"][0]["identifier_type"] == identifier_type
    assert result["candidates"][0]["source_field"] == header


def test_placeholder_identifier_falls_through_to_next_priority() -> None:
    result = parse_b2b_product_opportunities_csv(
        "partNumber,modelNumber\nN/A,MODEL-300\n"
    )

    assert result["candidates"][0]["raw_part_number"] == "MODEL-300"
    assert result["candidates"][0]["identifier_type"] == "modelNumber"


def test_official_brand_category_and_item_name_are_preserved() -> None:
    result = parse_b2b_product_opportunities_csv(
        "partNumber,brand,category,itemName\n"
        "PT-100,Acme,Automotive,Acme replacement sensor\n"
    )

    candidate = result["candidates"][0]
    assert candidate["brand"] == "Acme"
    assert candidate["category"] == "Automotive"
    assert candidate["item_name"] == "Acme replacement sensor"


def test_optional_metadata_uses_consistent_none_values() -> None:
    result = parse_b2b_product_opportunities_csv("partNumber\nPT-101\n")

    candidate = result["candidates"][0]
    assert candidate["brand"] is None
    assert candidate["category"] is None
    assert candidate["item_name"] is None


def test_category_allowlist_is_case_insensitive_exact_and_diagnostic() -> None:
    report = """partNumber,category,itemName
PT-1,Automotive,Allowed title case
PT-2,AUTOMOTIVE,Allowed uppercase
PT-3,Automotive Parts,Not an exact category
PT-4,,Missing category
"""

    result = parse_b2b_product_opportunities_csv(
        report, category_allowlist={"automotive"}
    )

    assert [candidate["raw_part_number"] for candidate in result["candidates"]] == [
        "PT-1",
        "PT-2",
    ]
    assert [diagnostic["code"] for diagnostic in result["diagnostics"]] == [
        "ROW_SKIPPED_CATEGORY_NOT_ALLOWED",
        "ROW_SKIPPED_CATEGORY_NOT_ALLOWED",
    ]
    assert [diagnostic["source_row"] for diagnostic in result["diagnostics"]] == [
        4,
        5,
    ]
    assert "Automotive Parts" in result["diagnostics"][0]["message"]
    assert "missing" in result["diagnostics"][1]["message"].casefold()


def test_file_parser_forwards_category_allowlist(tmp_path: Path) -> None:
    csv_path = tmp_path / "filtered.csv"
    csv_path.write_text(
        "partNumber,category\nPT-1,Industrial\nPT-2,Automotive\n",
        encoding="utf-8",
    )

    result = discover_candidates_from_csv(
        csv_path, category_allowlist=["AUTOMOTIVE"]
    )

    assert [candidate["raw_part_number"] for candidate in result["candidates"]] == [
        "PT-2"
    ]
    assert result["diagnostics"][0]["code"] == "ROW_SKIPPED_CATEGORY_NOT_ALLOWED"


def test_default_category_filter_keeps_rows_without_category() -> None:
    result = parse_b2b_product_opportunities_csv("partNumber,itemName\nPT-1,No category\n")

    assert result["candidates"][0]["raw_part_number"] == "PT-1"
    assert result["diagnostics"] == []


def test_category_allowlist_rejects_a_bare_string() -> None:
    with pytest.raises(TypeError, match="category_allowlist"):
        parse_b2b_product_opportunities_csv(
            "partNumber,category\nPT-1,Automotive\n",
            category_allowlist="Automotive",
        )


def test_candidates_are_normalized_and_deduplicated_in_first_seen_order() -> None:
    report = """partNumber,modelNumber,itemName
A18-67004-004,,First
,a18 67004 004,Duplicate through another identifier type
53630_53010,,Second unique
"""

    result = parse_b2b_product_opportunities_csv(report)

    assert [candidate["canonical_part_number"] for candidate in result["candidates"]] == [
        "A1867004004",
        "5363053010",
    ]
    assert result["candidates"][0]["raw_part_number"] == "A18-67004-004"
    assert result["candidates"][0]["source_row"] == 2
    assert result["diagnostics"] == [
        {
            "code": "ROW_SKIPPED_DUPLICATE_IDENTIFIER",
            "source_row": 3,
            "message": "Identifier normalizes to a candidate already discovered on row 2.",
            "canonical_part_number": "A1867004004",
            "duplicate_of_source_row": 2,
        }
    ]


def test_unusable_and_structurally_bad_rows_are_skipped_with_diagnostics() -> None:
    report = """partNumber,modelNumber,itemName
,,No identifier
---,***,Invalid identifiers
GOOD-1,,Too many columns,unexpected
GOOD-2,,Valid
GOOD-3
"""

    result = parse_b2b_product_opportunities_csv(report)

    assert result["candidates"] == [
        {
            "raw_part_number": "GOOD-2",
            "canonical_part_number": "GOOD2",
            "identifier_type": "partNumber",
            "source_field": "partNumber",
            "source_row": 5,
            "brand": None,
            "category": None,
            "item_name": "Valid",
        }
    ]
    assert [diagnostic["code"] for diagnostic in result["diagnostics"]] == [
        "ROW_SKIPPED_NO_USABLE_IDENTIFIER",
        "ROW_SKIPPED_NO_USABLE_IDENTIFIER",
        "ROW_SKIPPED_MALFORMED_CSV",
        "ROW_SKIPPED_MALFORMED_CSV",
    ]
    assert [diagnostic["source_row"] for diagnostic in result["diagnostics"]] == [
        2,
        3,
        4,
        6,
    ]


def test_unknown_columns_do_not_shift_identifier_binding() -> None:
    report = """futureField,Part Number,anotherFutureField
future-value,PT-900,another-value
"""

    result = parse_b2b_product_opportunities_csv(report)

    assert result["candidates"][0]["raw_part_number"] == "PT-900"
    assert result["candidates"][0]["source_field"] == "Part Number"


def test_report_without_identifier_columns_returns_explicit_diagnostics() -> None:
    report = """asin,itemName
B000000001,No supported source identifier
"""

    result = parse_b2b_product_opportunities_csv(report)

    assert result["candidates"] == []
    assert [diagnostic["code"] for diagnostic in result["diagnostics"]] == [
        "MISSING_IDENTIFIER_COLUMNS",
        "ROW_SKIPPED_NO_USABLE_IDENTIFIER",
    ]


def test_discovery_result_converts_to_existing_candidate_pool_shape() -> None:
    result = parse_b2b_product_opportunities_csv(
        "partNumber,modelNumber\n53630-53010,ignored\n,A18-67004-004\n"
    )

    assert to_candidate_pool(result) == {
        "schema_version": "0.2",
        "candidates": [
            {"raw_part_number": "53630-53010"},
            {"raw_part_number": "A18-67004-004"},
        ],
    }


def test_empty_report_returns_diagnostic_instead_of_raising() -> None:
    result = parse_b2b_product_opportunities_csv("")

    assert result == {
        "candidates": [],
        "diagnostics": [
            {
                "code": "EMPTY_REPORT",
                "source_row": 1,
                "message": "The CSV report has no header row.",
            }
        ],
    }


def test_non_utf8_report_has_path_aware_error(tmp_path: Path) -> None:
    csv_path = tmp_path / "invalid.csv"
    csv_path.write_bytes(b"partNumber\n\xff\n")

    with pytest.raises(DiscoveryError, match="invalid.csv.*UTF-8"):
        discover_candidates_from_csv(csv_path)
