from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from proteus.supplier_inventory_import import (
    SupplierInventoryImportError,
    normalize_supplier_inventory_import,
)


ROOT = Path(__file__).resolve().parents[1]
STORE_URL = "https://shop3w093345o1043.1688.com/page/offerlist.htm"
SOURCE = {
    "supplier_id": "sup_test",
    "label": "测试供应商",
    "canonical_url": STORE_URL,
    "shop_host": "shop3w093345o1043.1688.com",
    "member_id": None,
}


def _document(*, complete: bool = True) -> dict:
    return {
        "format": "proteus.supplier_inventory",
        "version": 1,
        "supplier": {"url": STORE_URL},
        "capture": {
            "collector": "test-agent",
            "captured_at": "2026-08-30T00:00:00Z",
            "acquisition_status": "SUCCESS" if complete else "PARTIAL",
            "inventory_complete": complete,
            "pages_attempted": 2,
            "pages_completed": 2,
            "has_next_page": False if complete else True,
            "reported_total": 1 if complete else None,
            "warnings": [],
        },
        "offers": [
            {
                "offer_id": "10001",
                "title": "丰田雾灯框 81482-0R010",
                "offer_url": "https://detail.1688.com/offer/10001.html",
            }
        ],
    }


def test_import_contract_and_example_are_valid() -> None:
    schema = json.loads(
        (ROOT / "contracts" / "v0_2_9_supplier_inventory_import.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    document = json.loads(
        (ROOT / "examples" / "supplier_inventory_import.example.json").read_text(
            encoding="utf-8"
        )
    )
    errors = list(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(document)
    )
    assert errors == []


def test_import_normalizes_and_binds_offers_to_selected_supplier() -> None:
    snapshot, report = normalize_supplier_inventory_import(
        _document(), SOURCE, filename="C:\\tmp\\offers.json"
    )

    assert report["can_run"] is True
    assert report["valid_offer_count"] == 1
    assert report["filename"] == "offers.json"
    assert snapshot["provider"] == "FILE_JSON_IMPORT"
    assert snapshot["source_method"] == "AGENT_JSON_IMPORT"
    assert snapshot["offers"][0]["supplier"] == {
        "shop_host": SOURCE["shop_host"],
        "name": SOURCE["label"],
    }


def test_import_duplicate_and_semantically_invalid_rows_are_visible_and_partial() -> None:
    document = _document()
    document["capture"]["reported_total"] = 3
    document["offers"].extend(
        [
            deepcopy(document["offers"][0]),
            {
                "offer_id": "10002",
                "title": "另一个商品",
                "offer_url": "https://detail.1688.com/offer/10002.html",
                "image_url": "http://insecure.example/image.jpg",
            },
        ]
    )

    snapshot, report = normalize_supplier_inventory_import(document, SOURCE)

    assert report["valid_offer_count"] == 1
    assert report["duplicate_offer_count"] == 1
    assert report["invalid_offer_count"] == 1
    assert report["can_run"] is True
    assert snapshot["acquisition_status"] == "PARTIAL"
    assert snapshot["inventory_complete"] is False
    assert snapshot["diagnostics"][0]["code"] == "IMPORT_INVALID_ROWS"
    assert snapshot["diagnostics"][1]["code"] == "IMPORT_DUPLICATE_ROWS"


def test_import_preserves_total_invalid_count_when_diagnostic_rows_are_truncated() -> None:
    document = _document(complete=False)
    document["offers"].extend(
        {
            "offer_id": str(20_000 + index),
            "title": f"无效图片商品 {index}",
            "offer_url": f"https://detail.1688.com/offer/{20_000 + index}.html",
            "image_url": "http://insecure.example/image.jpg",
        }
        for index in range(105)
    )

    snapshot, report = normalize_supplier_inventory_import(document, SOURCE)

    assert report["invalid_offer_count"] == 105
    diagnostic = snapshot["diagnostics"][0]
    assert diagnostic["count"] == 105
    assert len(diagnostic["rows"]) == 100
    assert diagnostic["rows_truncated"] is True


def test_import_rejects_supplier_or_offer_identity_mismatch() -> None:
    document = _document()
    document["supplier"]["url"] = "https://other-shop.1688.com/page/offerlist.htm"
    with pytest.raises(SupplierInventoryImportError, match="does not match"):
        normalize_supplier_inventory_import(document, SOURCE)

    document = _document()
    document["offers"][0]["offer_id"] = "10002"
    with pytest.raises(SupplierInventoryImportError, match="does not match"):
        normalize_supplier_inventory_import(document, SOURCE)


def test_import_requires_explicit_complete_empty_semantics() -> None:
    document = _document()
    document["capture"].update(
        {
            "acquisition_status": "EMPTY",
            "inventory_complete": True,
            "has_next_page": False,
            "reported_total": 0,
        }
    )
    document["offers"] = []

    snapshot, report = normalize_supplier_inventory_import(document, SOURCE)

    assert snapshot["acquisition_status"] == "EMPTY"
    assert snapshot["inventory_complete"] is True
    # EMPTY is a valid, complete source snapshot. A run is allowed so the
    # result can explicitly record that this supplier had no imported offers.
    assert report["can_run"] is True


def test_import_downgrades_complete_success_when_reported_total_disagrees() -> None:
    document = _document()
    document["capture"]["reported_total"] = 2

    snapshot, report = normalize_supplier_inventory_import(document, SOURCE)

    assert snapshot["acquisition_status"] == "PARTIAL"
    assert snapshot["inventory_complete"] is False
    assert "IMPORT_REPORTED_TOTAL_MISMATCH" in snapshot["warnings"]
    assert report["can_run"] is True


def test_import_rejects_blocked_status_claiming_complete() -> None:
    document = _document()
    document["capture"]["acquisition_status"] = "RISK_CONTROL"
    document["capture"]["inventory_complete"] = True
    with pytest.raises(SupplierInventoryImportError, match="RISK_CONTROL"):
        normalize_supplier_inventory_import(document, SOURCE)
