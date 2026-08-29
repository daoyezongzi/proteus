"""Agent-facing local CLI for conservative category catalog maintenance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from proteus.category_catalog import (
    CategoryCatalog,
    CategoryCatalogError,
    default_category_db_path,
    validate_category_definition,
)
from proteus.io import InputDataError, read_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proteus categories",
        description=(
            "Maintain the local versioned Northway category catalog. Draft and "
            "validation operations never call marketplace providers."
        ),
    )
    parser.add_argument(
        "--database",
        type=Path,
        help=(
            "catalog SQLite path; defaults to the local per-user Proteus data "
            "directory or PROTEUS_CATEGORY_DB"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate", help="validate one CategoryDefinition JSON offline"
    )
    validate.add_argument("--file", type=Path, required=True)

    draft = commands.add_parser(
        "draft", help="store one immutable DRAFT version after schema validation"
    )
    draft.add_argument("--file", type=Path, required=True)

    listing = commands.add_parser("list", help="list active choices or every version")
    listing.add_argument("--all", action="store_true", dest="include_all")

    show = commands.add_parser("show", help="show an active category or exact version")
    show.add_argument("category_id")
    show.add_argument("--version", dest="version_id")

    activate = commands.add_parser(
        "activate", help="explicitly activate one validation-eligible version"
    )
    activate.add_argument("category_id")
    activate.add_argument("--version", dest="version_id", required=True)

    archive = commands.add_parser(
        "archive", help="explicitly remove a category from active choices"
    )
    archive.add_argument("category_id")

    commands.add_parser("path", help="show the resolved local catalog path")
    return parser


def _print_json(value: Any, *, stream: Any | None = None) -> None:
    print(
        json.dumps(value, ensure_ascii=False, indent=2),
        file=stream if stream is not None else sys.stdout,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    database_path = args.database or default_category_db_path()
    try:
        if args.command == "path":
            _print_json({"database": str(Path(database_path).resolve())})
            return 0
        if args.command == "validate":
            report = validate_category_definition(read_json(args.file))
            _print_json(report)
            return 0 if report["activation_eligible"] else 1

        catalog = CategoryCatalog(database_path)
        if args.command == "draft":
            _print_json(catalog.create_draft(read_json(args.file)))
            return 0
        if args.command == "list":
            _print_json(
                catalog.list_versions()
                if args.include_all
                else catalog.public_active_catalog()
            )
            return 0
        if args.command == "show":
            value = (
                catalog.get_version(args.version_id)
                if args.version_id
                else catalog.get_active_definition(args.category_id)
            )
            if value["category_id"] != args.category_id:
                raise CategoryCatalogError(
                    f"version does not belong to category {args.category_id}"
                )
            _print_json(value)
            return 0
        if args.command == "activate":
            _print_json(catalog.activate(args.category_id, args.version_id))
            return 0
        if args.command == "archive":
            _print_json(catalog.archive(args.category_id))
            return 0
    except (CategoryCatalogError, InputDataError, OSError) as exc:
        print(f"proteus categories: error: {exc}", file=sys.stderr)
        return 2
    raise AssertionError(f"unhandled category command: {args.command}")


__all__ = ["main"]
