"""Agent-facing CLI for importing a supplier inventory JSON snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from proteus.io import InputDataError, read_json
from proteus.supplier_inventory_import import (
    MAX_IMPORT_DOCUMENT_BYTES,
    SupplierInventoryImportError,
    normalize_supplier_inventory_import,
)
from proteus.supplier_scout import SupplierScoutStore, default_supplier_scout_db_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proteus supplier-scout",
        description=(
            "Import a user/Agent-produced 1688 supplier inventory JSON file "
            "into an immutable local snapshot."
        ),
    )
    parser.add_argument(
        "--database",
        type=Path,
        help=(
            "supplier-scout SQLite path; defaults to PROTEUS_SUPPLIER_SCOUT_DB "
            "or the local Proteus data directory"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    import_json = commands.add_parser(
        "import-json", help="validate and seal one supplier inventory JSON snapshot"
    )
    import_json.add_argument(
        "--database",
        dest="command_database",
        type=Path,
        help="same as the global --database option; may be placed after import-json",
    )
    import_json.add_argument("--supplier-id", required=True)
    import_json.add_argument("--file", type=Path, required=True)
    return parser


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.command != "import-json":
        raise AssertionError(f"unhandled supplier-scout command: {args.command}")
    try:
        if args.file.stat().st_size > MAX_IMPORT_DOCUMENT_BYTES:
            raise SupplierInventoryImportError(
                f"import file exceeds {MAX_IMPORT_DOCUMENT_BYTES} bytes"
            )
        document = read_json(args.file)
        database = SupplierScoutStore(
            args.command_database or args.database or default_supplier_scout_db_path()
        )
        source = database.get_supplier(args.supplier_id)
        if source["status"] != "ACTIVE":
            raise ValueError("supplier source is archived")
        snapshot, report = normalize_supplier_inventory_import(
            document,
            source,
            filename=args.file.name,
        )
        saved = database.save_snapshot(source["supplier_id"], snapshot)
        snapshot.update(saved)
        member_id = report.get("identity_member_id")
        if member_id and not source.get("member_id"):
            database.update_supplier_identity(
                source["supplier_id"], {"member_id": member_id}
            )
        _print_json(
            {
                "snapshot": {
                    key: snapshot.get(key)
                    for key in (
                        "snapshot_id",
                        "supplier_id",
                        "snapshot_sha256",
                        "retrieved_at",
                        "acquisition_status",
                        "inventory_complete",
                        "pages_attempted",
                        "pages_completed",
                        "observed_offer_count",
                        "available_offer_count",
                        "has_next_page",
                        "source_method",
                        "provider",
                        "warnings",
                    )
                },
                "import": report,
                "can_run": report["can_run"],
            }
        )
        return 0
    except (InputDataError, SupplierInventoryImportError, KeyError, OSError, ValueError) as exc:
        print(f"proteus supplier-scout: error: {exc}", file=sys.stderr)
        return 2


__all__ = ["main"]
