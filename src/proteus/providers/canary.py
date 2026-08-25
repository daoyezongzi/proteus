"""One-item provider canaries with explicit access and contract outcomes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from proteus.evaluation import (
    evaluate_amazon_competition_gate,
    evaluate_ebay_demand_gate,
    evaluate_supply_gate,
)
from proteus.io import read_json, validate_acquisition, write_json_atomic
from proteus.normalization import normalize_part_number
from proteus.providers.adapters import (
    HIOBUY_1688_ID,
    NEXSCOPE_AMAZON_ID,
    SERPAPI_EBAY_ID,
    build_provider_registry,
)
from proteus.providers.base import Capability, PartLookupRequest, SupplyLookupRequest


DEFAULT_PART_NUMBER = "53630-53010"
AMAZON_SP_API_ID = "amazon-sp-api-b2b-report"
TARGETS = (
    AMAZON_SP_API_ID,
    NEXSCOPE_AMAZON_ID,
    SERPAPI_EBAY_ID,
    HIOBUY_1688_ID,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _environment_secret(name: str) -> str | None:
    value = os.environ.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _load_receiver(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    value = read_json(path)
    required = ("name", "mobile", "province", "city", "district", "address")
    if not isinstance(value, Mapping) or any(
        not isinstance(value.get(field), str) or not value[field].strip()
        for field in required
    ):
        raise ValueError(
            f"HioBuy receiver {path} must contain non-empty {', '.join(required)}"
        )
    return {field: value[field].strip() for field in required}


def _amazon_sp_api_probe() -> dict[str, Any]:
    credential_names = ("SP_API_REFRESH_TOKEN", "LWA_APP_ID", "LWA_CLIENT_SECRET")
    configured = [name for name in credential_names if _environment_secret(name)]
    wheel_available = importlib.util.find_spec("sp_api") is not None
    checks = [
        {
            "name": "WHEEL_AVAILABLE",
            "status": "PASS" if wheel_available else "FAIL",
            "message": (
                "python-amazon-sp-api is importable."
                if wheel_available
                else "python-amazon-sp-api is not installed in this environment."
            ),
        },
        {
            "name": "CREDENTIALS_AVAILABLE",
            "status": "PASS" if len(configured) == len(credential_names) else "FAIL",
            "message": (
                "All required LWA credential aliases are configured."
                if len(configured) == len(credential_names)
                else "Missing credential aliases: "
                + ", ".join(name for name in credential_names if name not in configured)
            ),
        },
        {
            "name": "ADAPTER_IMPLEMENTED",
            "status": "FAIL",
            "message": "The official report create/poll/download adapter is not implemented yet.",
        },
        {
            "name": "SELLER_REPORT_ACCESS_VALID",
            "status": "UNKNOWN",
            "message": "Seller-only B2B report access requires a live authorized call.",
        },
    ]
    return {
        "provider_id": AMAZON_SP_API_ID,
        "capability": Capability.AMAZON_CANDIDATE_SOURCE.value,
        "canary_status": "BLOCKED",
        "live_attempted": False,
        "acquisition_status": None,
        "contract_valid": False,
        "readiness": {
            "status": "BLOCKED",
            "checks": checks,
        },
        "reason": "Official Amazon candidate-source canary cannot run yet.",
    }


def _has_blocking_local_check(readiness: Mapping[str, Any]) -> bool:
    blocking_names = {
        "CREDENTIALS_AVAILABLE",
        "RECEIVER_AVAILABLE",
        "ORDER_PREVIEW_AVAILABLE",
    }
    return any(
        check.get("name") in blocking_names and check.get("status") == "FAIL"
        for check in readiness.get("checks", [])
        if isinstance(check, Mapping)
    )


def _run_adapter_canary(
    provider: Any,
    *,
    raw_part_number: str,
    max_moq: int,
    offline: bool,
) -> dict[str, Any]:
    readiness = provider.preflight().to_dict()
    base = {
        "provider_id": provider.provider_id,
        "capability": provider.capability.value,
        "canary_status": "BLOCKED",
        "live_attempted": False,
        "acquisition_status": None,
        "contract_valid": False,
        "readiness": readiness,
        "reason": "Provider canary is blocked by local configuration.",
    }
    if offline:
        base["canary_status"] = "NOT_RUN"
        base["reason"] = "Live acquisition was disabled by --offline."
        return base
    if _has_blocking_local_check(readiness):
        return base

    base["live_attempted"] = True
    request: PartLookupRequest | SupplyLookupRequest
    if provider.capability == Capability.ALIBABA_1688_SUPPLY:
        request = SupplyLookupRequest(raw_part_number, max_moq)
    else:
        request = PartLookupRequest(raw_part_number)
    try:
        outcome = provider.acquire(request)
        acquisition_status = outcome.get("status", outcome.get("acquisition_status"))
        base["acquisition_status"] = acquisition_status
        canonical = normalize_part_number(raw_part_number)
        if provider.capability == Capability.EBAY_DEMAND:
            validate_acquisition(outcome, label=f"{provider.provider_id} canary")
            stage = evaluate_ebay_demand_gate(
                outcome,
                expected_canonical_part_number=canonical,
            )
        elif provider.capability == Capability.AMAZON_COMPETITION:
            stage = evaluate_amazon_competition_gate(
                outcome,
                expected_canonical_part_number=canonical,
            )
        else:
            stage = evaluate_supply_gate(
                outcome,
                max_acceptable_moq=max_moq,
                expected_canonical_part_number=canonical,
            )
        base["contract_valid"] = True
        base["stage_status"] = stage["status"]
        if acquisition_status in {"SUCCESS", "PARTIAL_SUCCESS", "ZERO_RESULTS"}:
            base["canary_status"] = "PASSED"
            base["reason"] = "Live call returned a contract-valid terminal outcome."
        elif acquisition_status in {"AUTH_REQUIRED", "BLOCKED_BY_CREDENTIALS"}:
            base["canary_status"] = "BLOCKED"
            base["reason"] = "Live call reached the provider but authorization failed."
        else:
            base["canary_status"] = "FAILED"
            base["reason"] = "Live call returned a provider or parser failure."
    except Exception as exc:
        base["canary_status"] = "FAILED"
        base["reason"] = f"Canary runner rejected the provider outcome: {type(exc).__name__}"
    return base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proteus providers check",
        description="Run one-item, read-only provider canaries and write a redacted report.",
    )
    parser.add_argument("--provider", action="append", choices=TARGETS)
    parser.add_argument("--part-number", default=DEFAULT_PART_NUMBER)
    parser.add_argument("--max-moq", type=_positive_integer, default=10)
    parser.add_argument("--receiver", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        normalize_part_number(args.part_number)
        receiver = _load_receiver(args.receiver)
        registry = build_provider_registry(
            nexscope_key=_environment_secret("NEXSCOPE_API_KEY"),
            serpapi_key=_environment_secret("SERPAPI_API_KEY"),
            hiobuy_key=_environment_secret("HIOBUY_API_KEY"),
            receiver=receiver,
        )
        selected = tuple(args.provider or TARGETS)
        results: list[dict[str, Any]] = []
        for provider_id in selected:
            if provider_id == AMAZON_SP_API_ID:
                results.append(_amazon_sp_api_probe())
                continue
            capability = (
                Capability.AMAZON_COMPETITION
                if provider_id == NEXSCOPE_AMAZON_ID
                else Capability.EBAY_DEMAND
                if provider_id == SERPAPI_EBAY_ID
                else Capability.ALIBABA_1688_SUPPLY
            )
            provider = registry.select(
                capability,
                (provider_id,),
                require_ready=False,
            )
            results.append(
                _run_adapter_canary(
                    provider,
                    raw_part_number=args.part_number,
                    max_moq=args.max_moq,
                    offline=args.offline,
                )
            )
        report = {
            "schema_version": "0.1",
            "checked_at": _utc_now(),
            "part_number": args.part_number,
            "results": results,
            "summary": {
                "passed": sum(item["canary_status"] == "PASSED" for item in results),
                "blocked": sum(item["canary_status"] == "BLOCKED" for item in results),
                "failed": sum(item["canary_status"] == "FAILED" for item in results),
                "not_run": sum(item["canary_status"] == "NOT_RUN" for item in results),
            },
        }
        write_json_atomic(args.output, report)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"proteus providers check: error: {exc}", file=os.sys.stderr)
        return 2

    summary = report["summary"]
    print(
        f"Wrote provider canary report to {args.output} "
        f"(passed={summary['passed']}, blocked={summary['blocked']}, "
        f"failed={summary['failed']}, not_run={summary['not_run']})."
    )
    return 0 if summary["blocked"] == 0 and summary["failed"] == 0 else 3
