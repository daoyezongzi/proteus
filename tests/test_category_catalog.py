from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest
from jsonschema import Draft202012Validator

from proteus.category_catalog import (
    CategoryActivationError,
    CategoryCatalog,
    CategoryNotFoundError,
    load_seed_document,
    validate_category_definition,
)
from proteus.category_cli import main as category_cli_main
from proteus.api import DefaultFrontendService


def _new_plastic_category() -> dict:
    return {
        "schema_version": "0.2.5",
        "category_id": "mirror_mount_cover",
        "group": {
            "group_id": "plastic_parts",
            "label_zh": "塑料件",
            "label_en": "Plastic parts",
            "display_order": 20,
        },
        "label_zh": "后视镜安装盖",
        "label_en": "Mirror mount cover",
        "display_order": 60,
        "material_family": "PLASTIC",
        "identity_profile": "vehicle_specific_small_trim",
        "part_type": "mirror mount cover",
        "aliases": ["mirror mount cover", "mirror base cover"],
        "discovery": {
            "ebay_category_id": "6028",
            "queries": ["mirror mount cover OEM"],
        },
        "supply": {
            "keywords": ["后视镜底座盖"],
            "aliases": ["mirror mount cover", "mirror base cover", "后视镜底座盖"],
        },
        "required_capabilities": [
            "PART_TYPE_ALIAS_MATCH",
            "PART_IDENTIFIER",
            "VEHICLE_FITMENT",
            "SIDE",
            "POSITION",
            "PACKAGE_QUANTITY",
        ],
        "risk": {
            "level": "LOW",
            "rationale": "Small cosmetic vehicle-specific plastic trim.",
        },
        "examples": {
            "positive_titles": [
                "Left Mirror Mount Cover 87945-0R010 for Toyota RAV4 2013-2018"
            ],
            "negative_titles": ["Universal blind spot mirror pair"],
        },
    }


def test_category_definition_schema_and_packaged_seed_are_valid() -> None:
    seed = load_seed_document()
    schema = json.loads(
        (Path(__file__).parents[1] / "contracts" / "v0_2_5_category_definition.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)

    reports = [validate_category_definition(item) for item in seed["categories"]]

    assert len(reports) == 9
    assert all(report["activation_eligible"] for report in reports)
    assert all(report["external_requests"] == 0 for report in reports)

    example = json.loads(
        (
            Path(__file__).parents[1]
            / "examples"
            / "northway_category_definition.example.json"
        ).read_text(encoding="utf-8")
    )
    assert validate_category_definition(example)["activation_eligible"] is True


def test_catalog_seeds_active_categories_and_empty_metal_group(tmp_path) -> None:
    catalog = CategoryCatalog(tmp_path / "categories.sqlite3")

    public = catalog.public_active_catalog()

    assert public["activation_policy"] == "explicit"
    assert [group["group_id"] for group in public["groups"]] == [
        "cables",
        "plastic_parts",
        "low_liability_metal_parts",
    ]
    assert sum(len(group["categories"]) for group in public["groups"]) == 9
    assert public["groups"][2]["categories"] == []
    assert len(catalog.active_runtime_definitions()) == 9


def test_draft_is_invisible_until_explicit_activation_and_versions_are_immutable(
    tmp_path,
) -> None:
    database = tmp_path / "categories.sqlite3"
    catalog = CategoryCatalog(database)

    draft = catalog.create_draft(_new_plastic_category())

    assert draft["status"] == "DRAFT"
    assert draft["validation"]["activation_eligible"] is True
    assert draft["validation"]["external_requests"] == 0
    assert "mirror_mount_cover" not in catalog.active_runtime_definitions()
    with pytest.raises(CategoryNotFoundError):
        catalog.get_active_definition("mirror_mount_cover")

    activated = catalog.activate("mirror_mount_cover", draft["version_id"])

    assert activated["status"] == "ACTIVE"
    active = catalog.get_active_definition("mirror_mount_cover")
    assert active["version_id"] == draft["version_id"]
    assert active["definition"]["label_zh"] == "后视镜安装盖"

    with sqlite3.connect(database) as connection, pytest.raises(
        sqlite3.IntegrityError, match="immutable"
    ):
        connection.execute(
            "UPDATE category_versions SET definition_json = '{}' WHERE version_id = ?",
            (draft["version_id"],),
        )


def test_new_version_does_not_replace_active_version_until_activation(tmp_path) -> None:
    catalog = CategoryCatalog(tmp_path / "categories.sqlite3")
    original = catalog.get_active_definition("fog_light_bezel")
    updated_definition = deepcopy(original["definition"])
    updated_definition["label_zh"] = "雾灯装饰框"

    draft = catalog.create_draft(updated_definition)

    assert draft["version_number"] == 2
    assert catalog.get_active_definition("fog_light_bezel")["version_id"] == original[
        "version_id"
    ]

    catalog.activate("fog_light_bezel", draft["version_id"])

    assert catalog.get_active_definition("fog_light_bezel")["version_id"] == draft[
        "version_id"
    ]
    versions = {
        item["version_id"]: item["status"]
        for item in catalog.list_versions()["versions"]
        if item["category_id"] == "fog_light_bezel"
    }
    assert versions[original["version_id"]] == "SUPERSEDED"
    assert versions[draft["version_id"]] == "ACTIVE"


def test_capability_gap_can_be_saved_as_draft_but_cannot_be_activated(tmp_path) -> None:
    catalog = CategoryCatalog(tmp_path / "categories.sqlite3")
    definition = _new_plastic_category()
    definition["category_id"] = "dimensioned_mounting_bracket"
    definition["required_capabilities"].append("CRITICAL_HOLE_SPACING")

    draft = catalog.create_draft(definition)

    assert draft["validation"]["schema_valid"] is True
    assert draft["validation"]["activation_eligible"] is False
    assert draft["validation"]["capability_gaps"] == ["CRITICAL_HOLE_SPACING"]
    with pytest.raises(CategoryActivationError, match="CRITICAL_HOLE_SPACING"):
        catalog.activate(definition["category_id"], draft["version_id"])
    assert definition["category_id"] not in catalog.active_runtime_definitions()


def test_archive_is_explicit_and_removes_only_the_active_choice(tmp_path) -> None:
    catalog = CategoryCatalog(tmp_path / "categories.sqlite3")

    archived = catalog.archive("tow_hook_cover")

    assert archived["status"] == "ARCHIVED"
    assert "tow_hook_cover" not in catalog.active_runtime_definitions()
    with pytest.raises(CategoryNotFoundError):
        catalog.get_active_definition("tow_hook_cover")
    assert any(
        item["category_id"] == "tow_hook_cover" and item["status"] == "ARCHIVED"
        for item in catalog.list_versions()["versions"]
    )


def test_agent_cli_validates_then_creates_only_a_draft(tmp_path, capsys) -> None:
    source = tmp_path / "category.json"
    database = tmp_path / "categories.sqlite3"
    source.write_text(json.dumps(_new_plastic_category()), encoding="utf-8")

    validation_exit = category_cli_main(
        ["--database", str(database), "validate", "--file", str(source)]
    )
    validation = json.loads(capsys.readouterr().out)

    assert validation_exit == 0
    assert validation["activation_eligible"] is True
    assert validation["external_requests"] == 0
    assert database.exists() is False

    draft_exit = category_cli_main(
        ["--database", str(database), "draft", "--file", str(source)]
    )
    draft = json.loads(capsys.readouterr().out)

    assert draft_exit == 0
    assert draft["status"] == "DRAFT"
    assert "mirror_mount_cover" not in CategoryCatalog(
        database
    ).active_runtime_definitions()


def test_default_service_snapshots_the_active_category_version_at_submission(
    tmp_path,
) -> None:
    catalog = CategoryCatalog(tmp_path / "categories.sqlite3")
    original = catalog.get_active_definition("fog_light_bezel")

    class CaptureManager:
        request: dict | None = None

        def submit(self, request: dict) -> dict:
            self.request = deepcopy(request)
            return {"run_id": "captured", "status": "QUEUED"}

    service = DefaultFrontendService(category_catalog=catalog)
    capture = CaptureManager()
    service._northway_manager = capture

    submitted = service.submit_northway_run({"archetype": "fog_light_bezel"})
    updated_definition = deepcopy(original["definition"])
    updated_definition["label_zh"] = "雾灯装饰框"
    draft = catalog.create_draft(updated_definition)
    catalog.activate("fog_light_bezel", draft["version_id"])

    assert submitted == {"run_id": "captured", "status": "QUEUED"}
    assert capture.request is not None
    assert capture.request["category_definition"]["category_version_id"] == original[
        "version_id"
    ]
    assert service.northway_policy()["archetypes"]["fog_light_bezel"][
        "category_version_id"
    ] == draft["version_id"]
