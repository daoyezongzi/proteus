from __future__ import annotations

import json
from pathlib import Path

from proteus.supplier_scout import SupplierScoutStore
from proteus.supplier_scout_cli import main


STORE_URL = "https://shop3w093345o1043.1688.com/page/offerlist.htm"


def test_supplier_scout_cli_imports_json_and_prints_snapshot(
    tmp_path: Path, capsys
) -> None:
    database_path = tmp_path / "supplier-scout.sqlite3"
    store = SupplierScoutStore(database_path)
    supplier = store.add_supplier("测试供应商", STORE_URL)
    source_document = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "examples"
            / "supplier_inventory_import.example.json"
        ).read_text(encoding="utf-8")
    )
    input_path = tmp_path / "offers.json"
    input_path.write_text(json.dumps(source_document), encoding="utf-8")

    exit_code = main(
        [
            "import-json",
            "--database",
            str(database_path),
            "--supplier-id",
            supplier["supplier_id"],
            "--file",
            str(input_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["snapshot"]["provider"] == "FILE_JSON_IMPORT"
    assert output["can_run"] is True
    assert store.get_snapshot(output["snapshot"]["snapshot_id"])["offers"]


def test_supplier_scout_cli_rejects_unknown_supplier(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "offers.json"
    input_path.write_text(
        json.dumps(
            {
                "format": "proteus.supplier_inventory",
                "version": 1,
                "supplier": {"url": STORE_URL},
                "capture": {
                    "captured_at": "2026-08-30T00:00:00Z",
                    "acquisition_status": "SUCCESS",
                    "inventory_complete": True,
                    "pages_attempted": 1,
                    "pages_completed": 1,
                    "has_next_page": False,
                },
                "offers": [],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "import-json",
            "--database",
            str(tmp_path / "supplier-scout.sqlite3"),
            "--supplier-id",
            "sup_missing",
            "--file",
            str(input_path),
        ]
    )

    assert exit_code == 2
    assert "supplier not found" in capsys.readouterr().err
