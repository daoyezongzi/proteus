"""Command-line entry point for the Proteus V0.2 opportunity finder."""

from __future__ import annotations

import argparse
from collections import Counter
import os
from pathlib import Path
import sys
from typing import Any, Sequence

from proteus.discovery import DiscoveryError, discover_candidates_from_csv
from proteus.ebay import collect_ebay
from proteus.evaluation import (
    evaluate_amazon_competition_gate,
    evaluate_candidate,
    evaluate_ebay_demand_gate,
)
from proteus.io import (
    ContractValidationError,
    InputDataError,
    evidence_for_candidate,
    load_candidate_pool,
    load_ebay_evidence_bundle,
    load_manual_evidence_bundle,
    read_json,
    validate_acquisition,
    validate_opportunity_report,
    write_json_atomic,
)
from proteus.normalization import normalize_part_number
from proteus.providers.nexscope import (
    collect_1688_search,
    collect_amazon_search,
    collect_ebay_search,
)
from proteus.providers.serpapi_ebay import collect_ebay_sold
from proteus.providers.adapters import (
    HIOBUY_1688_ID,
    NEXSCOPE_1688_LISTING_ID,
    NEXSCOPE_AMAZON_ID,
    NEXSCOPE_EBAY_ID,
    SERPAPI_EBAY_ID,
    FunnelProviders,
    build_provider_registry,
)
from proteus.providers.base import Capability, PartLookupRequest, SupplyLookupRequest


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proteus",
        description=(
            "Discover or import OEM/MPN candidates, then evaluate the Proteus "
            "V0.2 Amazon -> eBay -> 1688 opportunity funnel."
        ),
    )

    candidate_source = parser.add_mutually_exclusive_group(required=True)
    candidate_source.add_argument(
        "--candidate-pool",
        "--candidates",
        dest="candidate_pool",
        type=Path,
        help="legacy/direct candidate-pool JSON file",
    )
    candidate_source.add_argument(
        "--amazon-b2b-report",
        type=Path,
        help="downloaded Amazon SP-API B2B Product Opportunities CSV report",
    )
    parser.add_argument(
        "--amazon-category",
        action="append",
        help=(
            "allowed B2B report category; repeatable (default for report input: "
            "Automotive)"
        ),
    )

    parser.add_argument(
        "--manual-evidence",
        type=Path,
        help="legacy Amazon/1688 manual-evidence JSON bundle",
    )
    acquisition_source = parser.add_mutually_exclusive_group(required=True)
    acquisition_source.add_argument(
        "--ebay-evidence",
        "--offline-ebay",
        dest="ebay_evidence",
        type=Path,
        help="legacy/offline eBay AcquisitionOutcome bundle",
    )
    acquisition_source.add_argument(
        "--live-ebay",
        action="store_true",
        help="collect eBay evidence sequentially with the browser provider",
    )
    acquisition_source.add_argument(
        "--nexscope",
        action="store_true",
        help="use deterministic Nexscope REST for Amazon, eBay and 1688 search",
    )
    acquisition_source.add_argument(
        "--managed-providers",
        action="store_true",
        help="use the explicit per-stage provider registry",
    )

    parser.add_argument(
        "--nexscope-api-key-env",
        default="NEXSCOPE_API_KEY",
        help="environment variable containing the Nexscope key",
    )
    parser.add_argument(
        "--serpapi-api-key-env",
        default="SERPAPI_API_KEY",
        help="environment variable containing the SerpApi key",
    )
    parser.add_argument(
        "--amazon-provider",
        choices=(NEXSCOPE_AMAZON_ID,),
        default=NEXSCOPE_AMAZON_ID,
        help="Amazon competition provider for --managed-providers",
    )
    parser.add_argument(
        "--ebay-provider",
        choices=(SERPAPI_EBAY_ID, NEXSCOPE_EBAY_ID),
        default=SERPAPI_EBAY_ID,
        help="eBay demand provider for --managed-providers",
    )
    parser.add_argument(
        "--supply-provider",
        choices=(HIOBUY_1688_ID, NEXSCOPE_1688_LISTING_ID),
        help=(
            "1688 provider for --managed-providers; defaults to HioBuy when a "
            "receiver is supplied, otherwise listing-only Nexscope"
        ),
    )
    parser.add_argument(
        "--hiobuy-receiver",
        type=Path,
        help=(
            "runtime-only domestic receiver JSON; enables HioBuy 1688 detail "
            "and order-preview verification"
        ),
    )
    parser.add_argument(
        "--hiobuy-api-key-env",
        default="HIOBUY_API_KEY",
        help="environment variable containing the HioBuy key",
    )
    parser.add_argument(
        "--max-candidates",
        type=_positive_integer,
        default=20,
        help="maximum candidates processed per run (default: 20)",
    )
    parser.add_argument(
        "--max-moq",
        type=_positive_integer,
        required=True,
        help="maximum acceptable 1688 minimum order quantity",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="destination JSON file; output is an ordered array of reports",
    )
    parser.add_argument(
        "--browser-channel",
        choices=("auto", "chrome", "msedge"),
        default="auto",
        help="Playwright browser channel for --live-ebay (default: auto)",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="show the browser window during --live-ebay collection",
    )
    return parser


def _candidate_inputs(args: argparse.Namespace) -> tuple[list[dict[str, Any]], int]:
    if args.amazon_b2b_report is None:
        candidates = load_candidate_pool(args.candidate_pool)
        return (
            [
                {
                    "raw_part_number": raw_part_number,
                    "source": {
                        "method": "SUPPLIED_POOL",
                        "provider": "USER_INPUT",
                        "source_reference": args.candidate_pool.name,
                        "source_row": None,
                        "source_field": None,
                        "identifier_type": None,
                        "category": None,
                        "brand": None,
                        "item_name": None,
                    },
                }
                for raw_part_number in candidates[: args.max_candidates]
            ],
            0,
        )

    result = discover_candidates_from_csv(
        args.amazon_b2b_report,
        category_allowlist=args.amazon_category or ("Automotive",),
    )
    discovered = result["candidates"]
    if not discovered:
        diagnostic_codes = ", ".join(
            str(item["code"]) for item in result["diagnostics"]
        ) or "no diagnostics"
        raise InputDataError(
            "Amazon B2B report yielded no usable candidates "
            f"({diagnostic_codes})"
        )
    candidates = []
    for item in discovered[: args.max_candidates]:
        candidates.append(
            {
                "raw_part_number": item["raw_part_number"],
                "source": {
                    "method": "AMAZON_B2B_REPORT_REPLAY",
                    "provider": "AMAZON_SP_API",
                    "source_reference": args.amazon_b2b_report.name,
                    "source_row": item["source_row"],
                    "source_field": item["source_field"],
                    "identifier_type": item["identifier_type"],
                    "category": item.get("category"),
                    "brand": item.get("brand"),
                    "item_name": item.get("item_name"),
                },
            }
        )
    return candidates, len(result["diagnostics"])


def _secret_from_environment(variable_name: str, provider: str) -> str:
    if not isinstance(variable_name, str) or not variable_name.strip():
        raise InputDataError(f"{provider} API-key environment variable name is empty")
    value = os.environ.get(variable_name)
    if value is None or not value.strip():
        raise InputDataError(
            f"{provider} API key is missing from environment variable {variable_name!r}"
        )
    return value.strip()


def _load_receiver(path: Path) -> dict[str, str]:
    value = read_json(path)
    required = ("name", "mobile", "province", "city", "district", "address")
    if not isinstance(value, dict) or any(
        not isinstance(value.get(field), str) or not value[field].strip()
        for field in required
    ):
        raise InputDataError(
            f"HioBuy receiver {path} must contain non-empty {', '.join(required)}"
        )
    return {field: value[field].strip() for field in required}


def _managed_report(
    raw_part_number: str,
    candidate_source: dict[str, Any],
    *,
    providers: FunnelProviders,
    max_moq: int,
) -> dict[str, Any]:
    amazon = providers.amazon_competition.acquire(
        PartLookupRequest(raw_part_number)
    )
    canonical = normalize_part_number(raw_part_number)
    amazon_stage = evaluate_amazon_competition_gate(
        amazon,
        expected_canonical_part_number=canonical,
    )
    if amazon_stage["status"] != "PASSED":
        return evaluate_candidate(
            raw_part_number,
            None,
            amazon,
            None,
            max_acceptable_moq=max_moq,
            candidate_source=candidate_source,
        )

    ebay = providers.ebay_demand.acquire(PartLookupRequest(raw_part_number))
    validate_acquisition(
        ebay,
        label=(
            f"{providers.ebay_demand.provider_id} eBay acquisition for "
            f"{raw_part_number!r}"
        ),
    )
    ebay_stage = evaluate_ebay_demand_gate(
        ebay,
        expected_canonical_part_number=canonical,
    )
    if ebay_stage["status"] != "PASSED":
        return evaluate_candidate(
            raw_part_number,
            ebay,
            amazon,
            None,
            max_acceptable_moq=max_moq,
            candidate_source=candidate_source,
        )

    supply = providers.alibaba_1688_supply.acquire(
        SupplyLookupRequest(raw_part_number, max_moq)
    )
    return evaluate_candidate(
        raw_part_number,
        ebay,
        amazon,
        supply,
        max_acceptable_moq=max_moq,
        candidate_source=candidate_source,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the sequential V0.2 funnel and return a process exit code."""

    active_argv = list(argv) if argv is not None else sys.argv[1:]
    if active_argv[:2] == ["providers", "check"]:
        from proteus.providers.canary import main as provider_canary_main

        return provider_canary_main(active_argv[2:])

    parser = build_parser()
    args = parser.parse_args(active_argv)

    try:
        managed = args.nexscope or args.managed_providers
        if args.hiobuy_receiver is not None and not managed:
            raise InputDataError(
                "--hiobuy-receiver requires --nexscope or --managed-providers"
            )
        if managed and args.manual_evidence is not None:
            raise InputDataError(
                "--manual-evidence cannot be combined with managed providers"
            )

        candidate_inputs, discovery_diagnostics = _candidate_inputs(args)
        manual_by_part = (
            load_manual_evidence_bundle(args.manual_evidence)
            if args.manual_evidence is not None
            else {}
        )
        ebay_by_part = (
            load_ebay_evidence_bundle(args.ebay_evidence)
            if args.ebay_evidence is not None
            else {}
        )
        receiver = (
            _load_receiver(args.hiobuy_receiver)
            if args.hiobuy_receiver is not None
            else None
        )
        funnel_providers: FunnelProviders | None = None
        if managed:
            if args.nexscope:
                amazon_provider_id = NEXSCOPE_AMAZON_ID
                ebay_provider_id = NEXSCOPE_EBAY_ID
                supply_provider_id = (
                    HIOBUY_1688_ID
                    if receiver is not None
                    else NEXSCOPE_1688_LISTING_ID
                )
            else:
                amazon_provider_id = args.amazon_provider
                ebay_provider_id = args.ebay_provider
                supply_provider_id = args.supply_provider or (
                    HIOBUY_1688_ID
                    if receiver is not None
                    else NEXSCOPE_1688_LISTING_ID
                )
            nexscope_ids = {
                NEXSCOPE_AMAZON_ID,
                NEXSCOPE_EBAY_ID,
                NEXSCOPE_1688_LISTING_ID,
            }
            selected_ids = {
                amazon_provider_id,
                ebay_provider_id,
                supply_provider_id,
            }
            nexscope_key = (
                _secret_from_environment(args.nexscope_api_key_env, "Nexscope")
                if selected_ids & nexscope_ids
                else None
            )
            serpapi_key = (
                _secret_from_environment(args.serpapi_api_key_env, "SerpApi")
                if ebay_provider_id == SERPAPI_EBAY_ID
                else None
            )
            if supply_provider_id == HIOBUY_1688_ID and receiver is None:
                raise InputDataError(
                    "--supply-provider hiobuy-1688 requires --hiobuy-receiver"
                )
            hiobuy_key = (
                _secret_from_environment(args.hiobuy_api_key_env, "HioBuy")
                if supply_provider_id == HIOBUY_1688_ID
                else None
            )
            from proteus.providers.hiobuy import collect_1688_supply

            registry = build_provider_registry(
                nexscope_key=nexscope_key,
                serpapi_key=serpapi_key,
                hiobuy_key=hiobuy_key,
                receiver=receiver,
                collectors={
                    NEXSCOPE_AMAZON_ID: collect_amazon_search,
                    NEXSCOPE_EBAY_ID: collect_ebay_search,
                    NEXSCOPE_1688_LISTING_ID: collect_1688_search,
                    SERPAPI_EBAY_ID: collect_ebay_sold,
                    HIOBUY_1688_ID: collect_1688_supply,
                },
            )
            funnel_providers = FunnelProviders(
                amazon_competition=registry.select(
                    Capability.AMAZON_COMPETITION,
                    (amazon_provider_id,),
                    require_ready=False,
                ),
                ebay_demand=registry.select(
                    Capability.EBAY_DEMAND,
                    (ebay_provider_id,),
                    require_ready=False,
                ),
                alibaba_1688_supply=registry.select(
                    Capability.ALIBABA_1688_SUPPLY,
                    (supply_provider_id,),
                    require_ready=False,
                ),
            )

        reports: list[dict[str, Any]] = []
        for candidate_input in candidate_inputs:
            raw_part_number = candidate_input["raw_part_number"]
            candidate_source = candidate_input["source"]
            if managed:
                assert funnel_providers is not None
                report = _managed_report(
                    raw_part_number,
                    candidate_source,
                    providers=funnel_providers,
                    max_moq=args.max_moq,
                )
            else:
                manual = evidence_for_candidate(manual_by_part, raw_part_number) or {}
                amazon = manual.get("amazon")
                amazon_stage = evaluate_amazon_competition_gate(
                    amazon,
                    expected_canonical_part_number=normalize_part_number(
                        raw_part_number
                    ),
                )
                ebay = None
                if amazon_stage["status"] == "PASSED":
                    if args.live_ebay:
                        ebay = collect_ebay(
                            raw_part_number,
                            headless=not args.headed,
                            browser_channel=args.browser_channel,
                        )
                        validate_acquisition(
                            ebay,
                            label=f"live eBay acquisition for {raw_part_number!r}",
                        )
                    else:
                        ebay = evidence_for_candidate(ebay_by_part, raw_part_number)
                        if ebay is None:
                            raise InputDataError(
                                f"offline eBay evidence bundle {args.ebay_evidence} "
                                f"has no acquisition for candidate {raw_part_number!r}"
                            )
                report = evaluate_candidate(
                    raw_part_number,
                    ebay,
                    amazon,
                    manual.get("alibaba_1688"),
                    max_acceptable_moq=args.max_moq,
                    candidate_source=candidate_source,
                )

            validate_opportunity_report(
                report, label=f"opportunity report for {raw_part_number!r}"
            )
            reports.append(report)

        write_json_atomic(args.output, reports)
    except (InputDataError, ContractValidationError, DiscoveryError, ValueError) as exc:
        print(f"proteus: error: {exc}", file=sys.stderr)
        return 2

    counts = Counter(str(report["decision"]) for report in reports)
    print(
        f"Wrote {len(reports)} report(s) to {args.output} "
        f"(opportunities={counts['OPPORTUNITY_CANDIDATE']}, "
        f"rejected={counts['REJECTED']}, "
        f"review_required={counts['REVIEW_REQUIRED']}, "
        f"discovery_diagnostics={discovery_diagnostics})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
