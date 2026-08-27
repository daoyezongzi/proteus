from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "contracts" / "v0_2_4_product_family_resolution.schema.json"
FIXTURE_PATH = ROOT / "fixtures" / "northway_v0_2_4_product_family_cases.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
CASES = FIXTURE["cases"]
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def _resolution(case_id: str) -> dict:
    return next(
        case["expected_resolution"] for case in CASES if case["case_id"] == case_id
    )


def test_product_family_schema_is_valid_draft_2020_12() -> None:
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_all_northway_reference_resolutions_match_contract(case: dict) -> None:
    VALIDATOR.validate(case["expected_resolution"])


def test_fixture_contract_and_case_ids_are_consistent() -> None:
    assert FIXTURE["schema_version"] == "0.2.4"
    assert FIXTURE["contract"] == (
        "../contracts/v0_2_4_product_family_resolution.schema.json"
    )
    assert len({case["case_id"] for case in CASES}) == len(CASES)
    assert all(
        case["case_id"] == case["expected_resolution"]["resolution_id"]
        for case in CASES
    )


def test_northway_gold_is_store_derived_and_covers_both_profiles() -> None:
    gold = [
        case["expected_resolution"]
        for case in CASES
        if case["expected_resolution"]["label_role"] == "NORTHWAY_GOLD"
    ]

    assert len(gold) >= 7
    assert {resolution["source"]["source_seller"] for resolution in gold} == {
        "northwayautoparts"
    }
    assert {resolution["category_profile"] for resolution in gold} == {
        "vehicle_specific_small_trim",
        "vehicle_specific_cable",
    }


def test_left_and_right_bezels_are_distinct_counterpart_families() -> None:
    right = _resolution("northway_fog_bezel_right_25778389")["family"]
    left = _resolution("northway_fog_bezel_left_25778388")["family"]

    assert right["family_key"] != left["family_key"]
    assert right["sides"] == ["RIGHT"]
    assert left["sides"] == ["LEFT"]
    assert right["relations"][0]["relation_type"] == "left_right_counterpart"
    assert left["relations"][0]["relation_type"] == "left_right_counterpart"


def test_left_right_pair_is_not_a_single_side_family() -> None:
    pair = _resolution(
        "northway_headlight_washer_cover_pair_25928247_25928248"
    )["family"]

    assert pair["package_type"] == "PAIR"
    assert pair["package_quantity"] == 2
    assert set(pair["sides"]) == {"LEFT", "RIGHT"}
    assert {identifier["role"] for identifier in pair["identifiers"]} == {
        "COMPONENT"
    }


def test_467903x100_is_extension_case_not_primary_gold() -> None:
    extension = _resolution("northway_like_shift_control_cable_467903x100")

    assert extension["label_role"] == "NORTHWAY_LIKE"
    assert extension["category_profile"] == "vehicle_specific_cable"
    assert extension["family"]["fitments"][0]["transmissions"] == ["automatic"]


@pytest.mark.parametrize(
    "case_id", ["negative_ac_refresher_00289_acrkt", "negative_universal_mud_flaps"]
)
def test_out_of_scope_controls_never_create_a_family(case_id: str) -> None:
    negative = _resolution(case_id)

    assert negative["label_role"] == "OUT_OF_SCOPE_NEGATIVE"
    assert negative["scope_status"] == "OUT_OF_SCOPE"
    assert negative["category_profile"] is None
    assert negative["family"] is None
