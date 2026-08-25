"""Command-line entry point for the Proteus V0.1 opportunity finder."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys
from typing import Sequence

from proteus.ebay import collect_ebay
from proteus.evaluation import evaluate_candidate
from proteus.io import (
    ContractValidationError,
    InputDataError,
    evidence_for_candidate,
    load_candidate_pool,
    load_ebay_evidence_bundle,
    load_manual_evidence_bundle,
    validate_acquisition,
    validate_opportunity_report,
    write_json_atomic,
)


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
            "Evaluate a small OEM/MPN candidate pool against the Proteus V0.1 "
            "three-gate opportunity contract."
        ),
    )
    parser.add_argument(
        "--candidate-pool",
        "--candidates",
        dest="candidate_pool",
        type=Path,
        required=True,
        help="candidate-pool JSON file",
    )
    parser.add_argument(
        "--manual-evidence",
        type=Path,
        help="optional Amazon/1688 manual-evidence JSON bundle",
    )

    ebay_source = parser.add_mutually_exclusive_group(required=True)
    ebay_source.add_argument(
        "--ebay-evidence",
        "--offline-ebay",
        dest="ebay_evidence",
        type=Path,
        help="offline eBay AcquisitionOutcome bundle",
    )
    ebay_source.add_argument(
        "--live-ebay",
        action="store_true",
        help="collect eBay evidence sequentially with the browser provider",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the sequential V0.1 pipeline and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        candidates = load_candidate_pool(args.candidate_pool)
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

        reports: list[dict[str, object]] = []
        for raw_part_number in candidates:
            if args.live_ebay:
                ebay_acquisition = collect_ebay(
                    raw_part_number,
                    headless=not args.headed,
                    browser_channel=args.browser_channel,
                )
                validate_acquisition(
                    ebay_acquisition,
                    label=f"live eBay acquisition for {raw_part_number!r}",
                )
            else:
                ebay_acquisition = evidence_for_candidate(
                    ebay_by_part, raw_part_number
                )
                if ebay_acquisition is None:
                    raise InputDataError(
                        f"offline eBay evidence bundle {args.ebay_evidence} "
                        f"has no acquisition for candidate {raw_part_number!r}"
                    )

            manual = evidence_for_candidate(manual_by_part, raw_part_number) or {}
            report = evaluate_candidate(
                raw_part_number,
                ebay_acquisition,
                manual.get("amazon"),
                manual.get("alibaba_1688"),
                max_acceptable_moq=args.max_moq,
            )
            validate_opportunity_report(
                report, label=f"opportunity report for {raw_part_number!r}"
            )
            reports.append(report)

        write_json_atomic(args.output, reports)
    except (InputDataError, ContractValidationError) as exc:
        print(f"proteus: error: {exc}", file=sys.stderr)
        return 2

    counts = Counter(str(report["decision"]) for report in reports)
    print(
        f"Wrote {len(reports)} report(s) to {args.output} "
        f"(opportunities={counts['OPPORTUNITY_CANDIDATE']}, "
        f"rejected={counts['REJECTED']}, "
        f"review_required={counts['REVIEW_REQUIRED']})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
