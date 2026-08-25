"""JSON input/output helpers for the Proteus V0.2 CLI."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from proteus.models import SCHEMA_VERSION, SUPPORTED_INPUT_SCHEMA_VERSIONS


JsonObject = dict[str, Any]


class InputDataError(ValueError):
    """Raised when a CLI input file does not follow its declared contract."""


class ContractValidationError(ValueError):
    """Raised when an acquisition or report violates a JSON Schema."""


def canonical_part_key(part_number: str) -> str:
    """Return the lookup key used to join candidate and evidence bundles."""

    if not isinstance(part_number, str) or not part_number.strip():
        raise InputDataError("part number must be a non-empty string")
    key = re.sub(r"[^A-Za-z0-9]", "", part_number).upper()
    if not key:
        raise InputDataError(f"part number has no letters or digits: {part_number!r}")
    return key


def read_json(path: str | Path) -> Any:
    """Read one UTF-8 JSON document with a path-aware error."""

    source = Path(path)
    try:
        return json.loads(source.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise InputDataError(f"JSON file does not exist: {source}") from exc
    except OSError as exc:
        raise InputDataError(f"cannot read JSON file {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InputDataError(
            f"invalid JSON in {source} at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc


def write_json_atomic(path: str | Path, value: Any) -> None:
    """Write a UTF-8 JSON document atomically in the destination directory."""

    destination = Path(path)
    if not destination.parent.exists():
        raise InputDataError(
            f"output directory does not exist: {destination.parent}"
        )

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            json.dump(value, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    except OSError as exc:
        raise InputDataError(f"cannot write output JSON {destination}: {exc}") from exc
    finally:
        if temporary_name:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass


def load_candidate_pool(path: str | Path) -> list[str]:
    """Load candidate part numbers in their declared order.

    The preferred document is ``{"schema_version": "0.1", "candidates": [...]}``.
    Each entry may be a part-number string or an object containing
    ``raw_part_number``. A top-level array is also accepted for small ad-hoc runs.
    """

    document = read_json(path)
    if isinstance(document, dict):
        _check_schema_version(document, path)
        entries = document.get("candidates")
    elif isinstance(document, list):
        entries = document
    else:
        entries = None

    if not isinstance(entries, list) or not entries:
        raise InputDataError(
            f"candidate pool {path} must contain a non-empty 'candidates' array"
        )

    candidates: list[str] = []
    for index, entry in enumerate(entries):
        if isinstance(entry, str):
            raw_part_number = entry
        elif isinstance(entry, dict):
            raw_part_number = entry.get("raw_part_number")
        else:
            raw_part_number = None
        if not isinstance(raw_part_number, str) or not raw_part_number.strip():
            raise InputDataError(
                f"candidate pool {path} entry {index} needs a non-empty "
                "raw_part_number"
            )
        canonical_part_key(raw_part_number)
        candidates.append(raw_part_number.strip())
    return candidates


def load_manual_evidence_bundle(path: str | Path) -> dict[str, JsonObject]:
    """Load Amazon and 1688 manual evidence indexed by canonical part number.

    Preferred shape::

        {"schema_version": "0.1", "evidence": [
          {"raw_part_number": "...", "amazon": {...},
           "alibaba_1688": {...}}
        ]}

    ``source_method`` and every supplied evidence ``extraction_method`` are
    checked, but the evidence dictionaries are otherwise passed through without
    mutation so missing fields remain missing and can require review.
    """

    document = read_json(path)
    if isinstance(document, dict):
        _check_schema_version(document, path)
        entries = document.get("evidence")
    elif isinstance(document, list):
        entries = document
    else:
        entries = None

    if not isinstance(entries, list):
        raise InputDataError(
            f"manual evidence bundle {path} must contain an 'evidence' array"
        )

    indexed: dict[str, JsonObject] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise InputDataError(
                f"manual evidence bundle {path} entry {index} must be an object"
            )
        selector = _part_selector(entry)
        key = canonical_part_key(selector)
        if key in indexed:
            raise InputDataError(
                f"manual evidence bundle {path} has duplicate part number {selector!r}"
            )

        amazon = _one_alias(entry, ("amazon", "amazon_competition"), path, index)
        supply = _one_alias(
            entry,
            ("alibaba_1688", "alibaba_1688_supply", "supply"),
            path,
            index,
        )
        _validate_manual_provenance(amazon, "Amazon", path, index)
        _validate_manual_provenance(supply, "1688", path, index)
        indexed[key] = {
            "amazon": deepcopy(amazon),
            "alibaba_1688": deepcopy(supply),
        }
    return indexed


def load_ebay_evidence_bundle(path: str | Path) -> dict[str, JsonObject]:
    """Load and validate offline eBay acquisitions by canonical query key."""

    document = read_json(path)
    if isinstance(document, dict):
        _check_schema_version(document, path)
        acquisitions = document.get("acquisitions")
    elif isinstance(document, list):
        acquisitions = document
    else:
        acquisitions = None

    if not isinstance(acquisitions, list):
        raise InputDataError(
            f"eBay evidence bundle {path} must contain an 'acquisitions' array"
        )

    indexed: dict[str, JsonObject] = {}
    for index, acquisition in enumerate(acquisitions):
        if not isinstance(acquisition, dict):
            raise InputDataError(
                f"eBay evidence bundle {path} entry {index} must be an object"
            )
        validate_acquisition(acquisition, label=f"{path} acquisition {index}")
        query = acquisition["query"]
        key = canonical_part_key(query["canonical_part_number"])
        if key in indexed:
            raise InputDataError(
                f"eBay evidence bundle {path} has duplicate acquisition for "
                f"{query['canonical_part_number']!r}"
            )
        indexed[key] = deepcopy(acquisition)
    return indexed


def evidence_for_candidate(
    indexed: dict[str, JsonObject], raw_part_number: str
) -> JsonObject | None:
    """Return a defensive copy of evidence for a candidate, if present."""

    value = indexed.get(canonical_part_key(raw_part_number))
    return deepcopy(value) if value is not None else None


def validate_acquisition(value: Any, *, label: str = "eBay acquisition") -> None:
    """Validate one eBay AcquisitionOutcome document."""

    version = _contract_version(value, label)
    _validate_contract(value, f"v{version.replace('.', '_')}_acquisition.schema.json", label)


def validate_opportunity_report(
    value: Any, *, label: str = "opportunity report"
) -> None:
    """Validate one final OpportunityCandidateReport document."""

    version = _contract_version(value, label)
    _validate_contract(
        value,
        f"v{version.replace('.', '_')}_opportunity_report.schema.json",
        label,
    )
    if version == SCHEMA_VERSION and value.get("automation_qualified") is True:
        # Local import keeps the schema/IO layer usable by the evaluator without
        # introducing a module import cycle.
        from proteus.evaluation import is_report_automation_qualified

        if not is_report_automation_qualified(value):
            raise ContractValidationError(
                f"{label} claims automation_qualified=true but does not satisfy "
                "the V0.2 automation semantics"
            )
    if version == SCHEMA_VERSION and value.get("decision") == "OPPORTUNITY_CANDIDATE":
        from proteus.evaluation import (
            is_report_opportunity_candidate_semantically_valid,
        )

        if not is_report_opportunity_candidate_semantically_valid(value):
            raise ContractValidationError(
                f"{label} claims OPPORTUNITY_CANDIDATE but does not satisfy "
                "the V0.2 opportunity semantics"
            )


def _contract_version(value: Any, label: str) -> str:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{label} must be an object")
    version = value.get("schema_version")
    if version not in SUPPORTED_INPUT_SCHEMA_VERSIONS:
        raise ContractValidationError(
            f"{label} has unsupported schema_version {version!r}; "
            f"expected one of {sorted(SUPPORTED_INPUT_SCHEMA_VERSIONS)!r}"
        )
    return version


def _check_schema_version(document: JsonObject, path: str | Path) -> None:
    version = document.get("schema_version")
    if version is not None and version not in SUPPORTED_INPUT_SCHEMA_VERSIONS:
        raise InputDataError(
            f"unsupported schema_version in {path}: expected one of "
            f"{sorted(SUPPORTED_INPUT_SCHEMA_VERSIONS)!r}, got {version!r}"
        )


def _part_selector(entry: JsonObject) -> str:
    for field in ("raw_part_number", "canonical_part_number", "part_number"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value
    raise InputDataError(
        "manual evidence entry needs raw_part_number, canonical_part_number, "
        "or part_number"
    )


def _one_alias(
    entry: JsonObject,
    aliases: tuple[str, ...],
    path: str | Path,
    index: int,
) -> JsonObject | None:
    present = [alias for alias in aliases if alias in entry]
    if len(present) > 1:
        raise InputDataError(
            f"manual evidence bundle {path} entry {index} supplies aliases "
            f"{present}; use only one"
        )
    if not present or entry[present[0]] is None:
        return None
    value = entry[present[0]]
    if not isinstance(value, dict):
        raise InputDataError(
            f"manual evidence bundle {path} entry {index} field "
            f"{present[0]!r} must be an object or null"
        )
    return value


def _validate_manual_provenance(
    evidence_bundle: JsonObject | None,
    platform: str,
    path: str | Path,
    index: int,
) -> None:
    if evidence_bundle is None:
        return
    source_method = evidence_bundle.get("source_method")
    if source_method is not None and source_method != "MANUAL":
        raise InputDataError(
            f"manual evidence bundle {path} entry {index} {platform} "
            "source_method must be 'MANUAL'"
        )

    evidence_items = evidence_bundle.get("evidence")
    if evidence_items is None:
        return
    if not isinstance(evidence_items, list):
        raise InputDataError(
            f"manual evidence bundle {path} entry {index} {platform} evidence "
            "must be an array"
        )
    for evidence_index, evidence in enumerate(evidence_items):
        if not isinstance(evidence, dict):
            raise InputDataError(
                f"manual evidence bundle {path} entry {index} {platform} "
                f"evidence {evidence_index} must be an object"
            )
        extraction_method = evidence.get("extraction_method")
        if extraction_method is not None and extraction_method != "MANUAL_REVIEW":
            raise InputDataError(
                f"manual evidence bundle {path} entry {index} {platform} "
                f"evidence {evidence_index} extraction_method must be "
                "'MANUAL_REVIEW'"
            )


def _contracts_directory() -> Path:
    candidates = (
        Path(__file__).resolve().parents[2] / "contracts",
        Path(sys.prefix) / "share" / "proteus" / "contracts",
        Path.cwd() / "contracts",
    )
    for candidate in candidates:
        if (candidate / f"v{SCHEMA_VERSION.replace('.', '_')}_acquisition.schema.json").is_file():
            return candidate
    raise ContractValidationError(
        "cannot locate Proteus contracts directory; run from the project checkout"
    )


def _validator(schema_name: str) -> Draft202012Validator:
    contracts = _contracts_directory()
    schemas: dict[str, JsonObject] = {}
    resources: list[tuple[str, Resource[Any]]] = []
    for path in contracts.glob("*.schema.json"):
        schema = read_json(path)
        if not isinstance(schema, dict):
            raise ContractValidationError(f"schema is not an object: {path}")
        schemas[path.name] = schema
        resource = Resource.from_contents(schema)
        resources.extend(((path.name, resource), (path.resolve().as_uri(), resource)))

    try:
        schema = schemas[schema_name]
    except KeyError as exc:
        raise ContractValidationError(f"missing JSON Schema: {schema_name}") from exc
    registry = Registry().with_resources(resources)
    return Draft202012Validator(
        schema,
        registry=registry,
        format_checker=FormatChecker(),
    )


def _validate_contract(value: Any, schema_name: str, label: str) -> None:
    validator = _validator(schema_name)
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    json_path = "$"
    for item in error.absolute_path:
        if isinstance(item, int):
            json_path += f"[{item}]"
        else:
            json_path += f".{item}"
    raise ContractValidationError(f"{label} violates {schema_name} at {json_path}: {error.message}")
