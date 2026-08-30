"""Validation and normalization for user/Agent-produced supplier inventory JSON."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

from proteus.io import ContractValidationError, validate_json_contract
from proteus.providers.local_1688_store import normalize_1688_supplier_store_target
from proteus.supplier_scout import SCHEMA_VERSION


IMPORT_FORMAT = "proteus.supplier_inventory"
IMPORT_VERSION = 1
IMPORT_SCHEMA_NAME = "v0_2_9_supplier_inventory_import.schema.json"
IMPORT_PROVIDER = "FILE_JSON_IMPORT"
IMPORT_SOURCE_METHOD = "AGENT_JSON_IMPORT"
MAX_IMPORT_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_IMPORT_OFFERS = 1000


class SupplierInventoryImportError(ValueError):
    """Raised when an imported supplier inventory cannot be trusted or used."""


def _text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _clean_filename(value: Any) -> str:
    name = Path(_text(value) or "supplier-inventory.json").name
    if not name or name in {".", ".."}:
        return "supplier-inventory.json"
    return name[:255]


def _canonical_document_hash(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(document).encode("utf-8")).hexdigest()


def _normalize_offer(raw: Any, supplier_identity: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise SupplierInventoryImportError("offer must be an object")
    offer_id = _text(raw.get("offer_id") or raw.get("offerId"))
    title = _text(raw.get("title") or raw.get("subject"))
    offer_url = _text(raw.get("offer_url") or raw.get("url"))
    parsed = urlparse(offer_url)
    match = re.fullmatch(r"/offer/(\d+)\.html", parsed.path)
    if not re.fullmatch(r"\d{1,30}", offer_id):
        raise SupplierInventoryImportError("offer_id must contain digits only")
    if not title or len(title) > 500:
        raise SupplierInventoryImportError("title must contain 1-500 characters")
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != "detail.1688.com"
        or parsed.username
        or parsed.password
        or match is None
    ):
        raise SupplierInventoryImportError(
            "offer_url must be an HTTPS detail.1688.com offer URL"
        )
    if match.group(1) != offer_id:
        raise SupplierInventoryImportError("offer_id does not match offer_url")

    result: dict[str, Any] = {
        "offer_id": offer_id,
        "title": title,
        "offer_url": f"https://detail.1688.com/offer/{offer_id}.html",
        "supplier": deepcopy(dict(supplier_identity)),
    }
    image_url = _text(raw.get("image_url") or raw.get("image"))
    if image_url.startswith("//"):
        image_url = "https:" + image_url
    if image_url:
        image_parsed = urlparse(image_url)
        if (
            image_parsed.scheme.casefold() != "https"
            or not image_parsed.hostname
            or image_parsed.username
            or image_parsed.password
        ):
            raise SupplierInventoryImportError("image_url must use HTTPS")
        result["image_url"] = image_url[:2000]
    for key in (
        "price",
        "price_cny",
        "moq",
        "attributes",
        "skus",
        "sales",
        "monthly_sales",
        "source_page",
    ):
        if raw.get(key) is not None:
            result[key] = deepcopy(raw[key])
    return result


def _validate_completeness(
    *,
    status: str,
    complete: bool,
    has_next_page: bool | None,
    offers: list[Any],
    available_offer_count: int | None,
) -> None:
    if status not in {
        "SUCCESS",
        "EMPTY",
        "PARTIAL",
        "AUTH_REQUIRED",
        "RISK_CONTROL",
        "TIMEOUT",
        "PARSER_FAILED",
        "CLI_ERROR",
        "NOT_CONFIGURED",
    }:
        raise SupplierInventoryImportError(f"unsupported acquisition_status: {status}")
    if complete and (status not in {"SUCCESS", "EMPTY"} or has_next_page is not False):
        raise SupplierInventoryImportError(
            "inventory_complete=true requires SUCCESS/EMPTY and has_next_page=false"
        )
    if status == "EMPTY":
        if not complete or has_next_page is not False or offers:
            raise SupplierInventoryImportError(
                "EMPTY requires a complete zero-offer snapshot with no next page"
            )
        if available_offer_count != 0:
            raise SupplierInventoryImportError("EMPTY requires reported_total=0")
    if status in {
        "AUTH_REQUIRED",
        "RISK_CONTROL",
        "TIMEOUT",
        "PARSER_FAILED",
        "CLI_ERROR",
        "NOT_CONFIGURED",
    }:
        if complete:
            raise SupplierInventoryImportError(
                f"{status} cannot claim inventory_complete=true"
            )


def normalize_supplier_inventory_import(
    document: Mapping[str, Any],
    supplier: Mapping[str, Any],
    *,
    filename: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a public import document and convert it to an internal snapshot.

    The selected saved supplier is authoritative. The input may provide a
    stronger ``member_id`` when the saved source does not have one; the caller
    can persist that identity after the snapshot is sealed.
    """

    if not isinstance(document, Mapping):
        raise SupplierInventoryImportError("import document must be an object")
    serialized_size = len(_canonical_json(document).encode("utf-8"))
    if serialized_size > MAX_IMPORT_DOCUMENT_BYTES:
        raise SupplierInventoryImportError(
            f"import document exceeds {MAX_IMPORT_DOCUMENT_BYTES} bytes"
        )
    try:
        validate_json_contract(document, IMPORT_SCHEMA_NAME, "supplier inventory import")
    except ContractValidationError as exc:
        raise SupplierInventoryImportError(str(exc)) from exc
    if not isinstance(supplier, Mapping):
        raise SupplierInventoryImportError("saved supplier must be an object")

    input_supplier = document["supplier"]
    normalized_input_target = normalize_1688_supplier_store_target(input_supplier["url"])
    expected_url = _text(supplier.get("canonical_url"))
    if normalized_input_target["canonical_url"] != expected_url:
        raise SupplierInventoryImportError(
            "import supplier URL does not match the selected saved supplier"
        )
    saved_member_id = _text(supplier.get("member_id"))
    input_member_id = _text(input_supplier.get("member_id"))
    if saved_member_id and input_member_id and saved_member_id != input_member_id:
        raise SupplierInventoryImportError(
            "import member_id does not match the selected saved supplier"
        )
    member_id = saved_member_id or input_member_id
    supplier_identity: dict[str, Any] = {
        "shop_host": _text(supplier.get("shop_host")).casefold(),
    }
    if member_id:
        supplier_identity["member_id"] = member_id
    if _text(supplier.get("label")):
        supplier_identity["name"] = _text(supplier["label"])

    capture = document["capture"]
    status = _text(capture["acquisition_status"]).upper()
    complete = capture["inventory_complete"] is True
    has_next_page = capture["has_next_page"]
    pages_attempted = int(capture["pages_attempted"])
    pages_completed = int(capture["pages_completed"])
    if pages_completed > pages_attempted:
        raise SupplierInventoryImportError(
            "pages_completed cannot exceed pages_attempted"
        )
    reported_total = capture.get("reported_total")
    _validate_completeness(
        status=status,
        complete=complete,
        has_next_page=has_next_page,
        offers=document["offers"],
        available_offer_count=reported_total,
    )
    if len(document["offers"]) > MAX_IMPORT_OFFERS:
        raise SupplierInventoryImportError(
            f"import contains more than {MAX_IMPORT_OFFERS} offers"
        )

    normalized_offers: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    invalid_offer_count = 0
    duplicate_rows: list[int] = []
    seen_ids: set[str] = set()
    for index, raw_offer in enumerate(document["offers"]):
        try:
            normalized = _normalize_offer(raw_offer, supplier_identity)
        except SupplierInventoryImportError as exc:
            invalid_offer_count += 1
            if len(invalid_rows) < 100:
                invalid_rows.append({"index": index, "reason": str(exc)})
            continue
        if normalized["offer_id"] in seen_ids:
            duplicate_rows.append(index)
            continue
        seen_ids.add(normalized["offer_id"])
        normalized_offers.append(normalized)

    if document["offers"] and not normalized_offers:
        detail = invalid_rows[0]["reason"] if invalid_rows else "all offer rows are invalid"
        raise SupplierInventoryImportError(
            f"import contains no valid offers after validation: {detail}"
        )
    if invalid_offer_count:
        complete = False
        if status in {"SUCCESS", "EMPTY"}:
            status = "PARTIAL"

    count_mismatch = (
        complete
        and reported_total is not None
        and reported_total != len(normalized_offers)
    )
    if count_mismatch:
        complete = False
        if status == "SUCCESS":
            status = "PARTIAL"

    warnings = [_text(item) for item in capture.get("warnings", []) if _text(item)]
    if invalid_offer_count:
        warnings.append(f"IMPORT_INVALID_ROWS:{invalid_offer_count}")
    if duplicate_rows:
        warnings.append(f"IMPORT_DUPLICATE_ROWS:{len(duplicate_rows)}")
    if count_mismatch:
        warnings.append("IMPORT_REPORTED_TOTAL_MISMATCH")
    warnings = list(dict.fromkeys(warnings))
    diagnostics: list[dict[str, Any]] = []
    if invalid_offer_count:
        diagnostics.append(
            {
                "code": "IMPORT_INVALID_ROWS",
                "count": invalid_offer_count,
                "rows": invalid_rows,
                "rows_truncated": invalid_offer_count > len(invalid_rows),
            }
        )
    if duplicate_rows:
        diagnostics.append(
            {
                "code": "IMPORT_DUPLICATE_ROWS",
                "count": len(duplicate_rows),
                "indexes": duplicate_rows[:100],
            }
        )
    if count_mismatch:
        diagnostics.append(
            {
                "code": "IMPORT_REPORTED_TOTAL_MISMATCH",
                "reported_total": reported_total,
                "valid_offer_count": len(normalized_offers),
            }
        )

    if reported_total is None and status == "SUCCESS":
        available_offer_count: int | None = len(normalized_offers)
    else:
        available_offer_count = reported_total
    document_hash = _canonical_document_hash(document)
    clean_filename = _clean_filename(filename)
    snapshot: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "provider": IMPORT_PROVIDER,
        "source_method": IMPORT_SOURCE_METHOD,
        "submitted_target": normalized_input_target["submitted_target"],
        "canonical_url": expected_url,
        "supplier": supplier_identity,
        "retrieved_at": capture["captured_at"],
        "acquisition_status": status,
        "pages_attempted": pages_attempted,
        "pages_completed": pages_completed,
        "observed_offer_count": len(normalized_offers),
        "available_offer_count": available_offer_count,
        "has_next_page": has_next_page,
        "inventory_complete": complete,
        "offers": normalized_offers,
        "warnings": warnings,
        "diagnostics": diagnostics,
        "import": {
            "format": IMPORT_FORMAT,
            "version": IMPORT_VERSION,
            "filename": clean_filename,
            "document_sha256": document_hash,
            "collector": _text(capture.get("collector")) or "user-agent",
        },
    }
    report = {
        "format": IMPORT_FORMAT,
        "version": IMPORT_VERSION,
        "filename": clean_filename,
        "document_sha256": document_hash,
        "input_offer_count": len(document["offers"]),
        "valid_offer_count": len(normalized_offers),
        "invalid_offer_count": invalid_offer_count,
        "duplicate_offer_count": len(duplicate_rows),
        "acquisition_status": status,
        "inventory_complete": complete,
        "warnings": warnings,
        "can_run": (
            (status == "SUCCESS" and complete and bool(normalized_offers))
            or (status == "EMPTY" and complete and not normalized_offers)
            or (status == "PARTIAL" and bool(normalized_offers))
        ),
        "identity_member_id": member_id or None,
    }
    return snapshot, report


__all__ = [
    "IMPORT_FORMAT",
    "IMPORT_PROVIDER",
    "IMPORT_SCHEMA_NAME",
    "IMPORT_SOURCE_METHOD",
    "IMPORT_VERSION",
    "MAX_IMPORT_DOCUMENT_BYTES",
    "MAX_IMPORT_OFFERS",
    "SupplierInventoryImportError",
    "normalize_supplier_inventory_import",
]
