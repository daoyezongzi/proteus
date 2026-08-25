"""Application service for the two-account managed opportunity pipeline."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from proteus.evaluation import (
    evaluate_amazon_competition_gate,
    evaluate_candidate,
    evaluate_ebay_demand_gate,
)
from proteus.io import (
    InputDataError,
    validate_acquisition,
    validate_candidate_discovery,
    validate_opportunity_report,
)
from proteus.normalization import normalize_part_number
from proteus.providers.adapters import (
    HIOBUY_1688_ID,
    SERPAPI_AMAZON_ID,
    SERPAPI_EBAY_DISCOVERY_ID,
    SERPAPI_EBAY_ID,
    FunnelProviders,
    build_provider_registry,
)
from proteus.providers.base import (
    CandidateDiscoveryRequest,
    Capability,
    PartLookupRequest,
    SupplyLookupRequest,
)
from proteus.providers.serpapi_ebay_discovery import (
    DEFAULT_CATEGORY_ID,
    SERPAPI_EBAY_DISCOVERY_PROVIDER,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _required_secret(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputDataError(
            f"{name} is not configured; run 'proteus setup' first"
        )
    return value.strip()


def _managed_report(
    raw_part_number: str,
    candidate_source: dict[str, Any],
    *,
    providers: FunnelProviders,
    max_moq: int,
) -> dict[str, Any]:
    amazon = providers.amazon_competition.acquire(PartLookupRequest(raw_part_number))
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
        label=f"{providers.ebay_demand.provider_id} acquisition for {raw_part_number!r}",
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


def _candidate_source(
    candidate: Mapping[str, Any],
    discovery: Mapping[str, Any],
) -> dict[str, Any]:
    category = discovery.get("category")
    return {
        "method": "EBAY_SOLD_DISCOVERY_API",
        "provider": SERPAPI_EBAY_DISCOVERY_PROVIDER,
        "source_reference": candidate["source_listing_url"],
        "source_row": candidate["source_listing_position"],
        "source_field": candidate["source_field"],
        "identifier_type": candidate["identifier_type"],
        "category": category.get("name") if isinstance(category, Mapping) else None,
        "brand": None,
        "item_name": candidate["source_listing_title"],
        "report_generated_at": discovery["retrieved_at"],
    }


def run_two_account_managed(
    *,
    serpapi_key: str | None,
    hiobuy_key: str | None,
    receiver: Mapping[str, str] | None,
    max_candidates: int = 20,
    max_moq: int,
    ebay_category_id: str = DEFAULT_CATEGORY_ID,
    discovery_pages: int = 1,
    collectors: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Discover and evaluate opportunities with exactly two upstream accounts."""

    serpapi_secret = _required_secret(serpapi_key, "SERPAPI_API_KEY")
    hiobuy_secret = _required_secret(hiobuy_key, "HIOBUY_API_KEY")
    if receiver is None:
        raise InputDataError(
            "HioBuy receiver is not configured; run 'proteus setup' first"
        )
    for name, value, upper in (
        ("max_candidates", max_candidates, 100),
        ("max_moq", max_moq, 100000),
        ("discovery_pages", discovery_pages, 10),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= upper:
            raise ValueError(f"{name} must be between 1 and {upper}")
    if not isinstance(ebay_category_id, str) or not ebay_category_id.isdigit():
        raise ValueError("ebay_category_id must contain digits only")

    registry = build_provider_registry(
        nexscope_key=None,
        serpapi_key=serpapi_secret,
        hiobuy_key=hiobuy_secret,
        receiver=receiver,
        collectors=collectors,
    )
    discovery_provider = registry.select(
        Capability.EBAY_CANDIDATE_SOURCE,
        (SERPAPI_EBAY_DISCOVERY_ID,),
        require_ready=False,
    )
    providers = FunnelProviders(
        amazon_competition=registry.select(
            Capability.AMAZON_COMPETITION,
            (SERPAPI_AMAZON_ID,),
            require_ready=False,
        ),
        ebay_demand=registry.select(
            Capability.EBAY_DEMAND,
            (SERPAPI_EBAY_ID,),
            require_ready=False,
        ),
        alibaba_1688_supply=registry.select(
            Capability.ALIBABA_1688_SUPPLY,
            (HIOBUY_1688_ID,),
            require_ready=False,
        ),
    )

    discovered: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    diagnostics: list[dict[str, Any]] = []
    seen: set[str] = set()
    pages_completed = 0
    for page in range(1, discovery_pages + 1):
        if len(discovered) >= max_candidates:
            break
        outcome = discovery_provider.acquire(
            CandidateDiscoveryRequest(
                ebay_category_id,
                max_candidates - len(discovered),
                page,
            )
        )
        validate_candidate_discovery(outcome, label=f"eBay discovery page {page}")
        pages_completed += 1
        for item in outcome["diagnostics"]:
            diagnostics.append({"page": page, **item})
        if outcome["status"] not in {"SUCCESS", "PARTIAL_SUCCESS"}:
            if not discovered:
                raise InputDataError(
                    "eBay sold discovery could not produce candidates "
                    f"(status={outcome['status']})"
                )
            break
        for item in outcome["candidates"]:
            canonical = item["canonical_part_number"]
            if canonical in seen:
                continue
            seen.add(canonical)
            discovered.append((item, outcome))
            if len(discovered) >= max_candidates:
                break
    if not discovered:
        raise InputDataError("eBay sold discovery yielded no usable part-number candidates")

    reports: list[dict[str, Any]] = []
    for candidate, discovery in discovered:
        report = _managed_report(
            candidate["raw_part_number"],
            _candidate_source(candidate, discovery),
            providers=providers,
            max_moq=max_moq,
        )
        validate_opportunity_report(
            report,
            label=f"opportunity report for {candidate['raw_part_number']!r}",
        )
        reports.append(report)

    counts = Counter(str(report["decision"]) for report in reports)
    return {
        "schema_version": "0.2",
        "profile": "two-account-managed",
        "execution": {
            "mode": "AUTOMATED_MANAGED",
            "account_count": 2,
            "provider_ids": [
                SERPAPI_EBAY_DISCOVERY_ID,
                SERPAPI_AMAZON_ID,
                SERPAPI_EBAY_ID,
                HIOBUY_1688_ID,
            ],
            "started_and_completed_in_process": True,
        },
        "discovery": {
            "category_id": ebay_category_id,
            "pages_requested": discovery_pages,
            "pages_completed": pages_completed,
            "candidate_count": len(discovered),
            "diagnostic_count": len(diagnostics),
            "diagnostics": diagnostics,
        },
        "reports": reports,
        "summary": {
            "opportunities": counts["OPPORTUNITY_CANDIDATE"],
            "rejected": counts["REJECTED"],
            "review_required": counts["REVIEW_REQUIRED"],
        },
        "completed_at": _utc_now(),
    }


__all__ = ["run_two_account_managed"]
