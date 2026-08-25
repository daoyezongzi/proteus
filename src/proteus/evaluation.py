"""Deterministic three-gate evaluation for Proteus V0.1."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from urllib.parse import parse_qs, urlparse

from proteus.models import (
    ACQUISITION_STATUS_VALUES,
    AMAZON_US_CONTEXT,
    EBAY_US_CONTEXT,
    MATCH_TYPE_VALUES,
    MAX_AMAZON_RELEVANT_RESULTS,
    MIN_EBAY_AGGREGATE_OBSERVED_SOLD,
    SCHEMA_VERSION,
    SOURCE_METHOD_VALUES,
    STAGE_STATUS_VALUES,
    AcquisitionStatus,
    MatchType,
    OpportunityDecision,
    StageStatus,
    SUCCESSFUL_ACQUISITION_STATUSES,
    make_not_checked_amazon_stage,
    make_not_checked_supply_stage,
)
from proteus.normalization import build_part_query, normalize_part_number


_EVIDENCE_EXTRACTION_METHODS = frozenset(
    {
        "OFFICIAL_API",
        "VISIBLE_TEXT",
        "JSON_LD",
        "EMBEDDED_STATE",
        "SEARCH_SNIPPET",
        "MANUAL_FIXTURE",
        "MANUAL_REVIEW",
    }
)
_EBAY_REVIEW_MATCH_TYPES = frozenset(
    {
        MatchType.CROSS_REFERENCE.value,
        MatchType.REPLACEMENT.value,
        MatchType.LEFT_RIGHT_PAIR.value,
        MatchType.AMBIGUOUS.value,
        MatchType.UNKNOWN.value,
    }
)
_SUPPLY_PASS_MATCH_TYPES = frozenset(
    {MatchType.EXACT.value, MatchType.NORMALIZED_EXACT.value}
)


def _plain_value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _nonempty_string(value: object) -> str | None:
    return value if isinstance(value, str) and bool(value.strip()) else None


def _nonnegative_integer(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _positive_integer(value: object) -> int | None:
    integer = _nonnegative_integer(value)
    return integer if integer is not None and integer >= 1 else None


def _nonnegative_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or not math.isfinite(value):
        return None
    return value


def _boolean_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _valid_uri(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlparse(value)
    return value if parsed.scheme and (parsed.netloc or parsed.path) else None


def _is_real_amazon_url(value: str | None) -> bool:
    if value is None:
        return False
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (hostname == "amazon.com" or hostname.endswith(".amazon.com"))
    )


def _amazon_search_url_matches_query(value: str, query: str) -> bool:
    if not _is_real_amazon_url(value):
        return False
    parameters = parse_qs(urlparse(value).query)
    candidates = [
        candidate
        for key in ("k", "keywords", "field-keywords")
        for candidate in parameters.get(key, [])
    ]
    expected = normalize_part_number(query)
    for candidate in candidates:
        try:
            if normalize_part_number(candidate) == expected:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _valid_datetime_string(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo is not None else None


def _sanitize_market_context(value: object) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    required = (
        "marketplace_id",
        "site",
        "locale",
        "ship_to_country",
        "ship_to_postal_code",
        "currency",
    )
    context = {key: value.get(key) for key in required}
    if not all(_nonempty_string(context[key]) for key in required):
        return None
    if len(context["ship_to_country"]) != 2 or not context["ship_to_country"].isupper():
        return None
    if len(context["currency"]) != 3 or not context["currency"].isupper():
        return None
    return context


def _is_exact_context(context: Mapping | None, expected: Mapping[str, str]) -> bool:
    if context is None:
        return False
    return all(context.get(key) == value for key, value in expected.items())


def _sanitize_evidence_record(value: object) -> dict | None:
    if not isinstance(value, Mapping):
        return None
    metric = _nonempty_string(value.get("metric"))
    source = _nonempty_string(value.get("source"))
    url = _valid_uri(value.get("url"))
    retrieved_at = _valid_datetime_string(value.get("retrieved_at"))
    extraction_method = _plain_value(value.get("extraction_method"))
    raw_evidence = _nonempty_string(value.get("raw_evidence"))
    confidence = _nonnegative_number(value.get("confidence"))
    if (
        metric is None
        or source is None
        or url is None
        or retrieved_at is None
        or extraction_method not in _EVIDENCE_EXTRACTION_METHODS
        or raw_evidence is None
        or confidence is None
        or confidence > 1
        or "value" not in value
    ):
        return None
    return {
        "metric": metric,
        "value": deepcopy(value["value"]),
        "source": source,
        "url": url,
        "retrieved_at": retrieved_at,
        "extraction_method": extraction_method,
        "raw_evidence": raw_evidence,
        "confidence": confidence,
    }


def _sanitize_evidence_list(value: object) -> tuple[list[dict], bool]:
    if not isinstance(value, list):
        return [], False
    records: list[dict] = []
    for item in value:
        record = _sanitize_evidence_record(item)
        if record is None:
            return [], False
        records.append(record)
    return records, True


def _coerce_generated_at(value: str | datetime | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("generated_at datetime must include a timezone")
        return value.isoformat(timespec="seconds").replace("+00:00", "Z")
    valid = _valid_datetime_string(value)
    if valid is None:
        raise ValueError("generated_at must be an ISO 8601 date-time with timezone")
    return valid


def _validate_moq_policy(max_acceptable_moq: object) -> int:
    if (
        isinstance(max_acceptable_moq, bool)
        or not isinstance(max_acceptable_moq, int)
        or max_acceptable_moq < 1
    ):
        raise ValueError("max_acceptable_moq must be an integer greater than or equal to 1")
    return max_acceptable_moq


def _prepare_ebay_acquisition(acquisition: Mapping) -> dict:
    required = {
        "schema_version",
        "platform",
        "provider",
        "source_method",
        "query",
        "market_context",
        "status",
        "retrieved_at",
        "listings",
        "observed_demand",
        "diagnostics",
    }
    if not required.issubset(acquisition):
        missing = ", ".join(sorted(required.difference(acquisition)))
        raise ValueError(f"ebay_acquisition is missing required fields: {missing}")
    outcome = deepcopy({key: acquisition[key] for key in required})
    status = _plain_value(outcome["status"])
    source_method = _plain_value(outcome["source_method"])
    if outcome["schema_version"] != SCHEMA_VERSION or outcome["platform"] != "EBAY":
        raise ValueError("ebay_acquisition must be a V0.1 EBAY AcquisitionOutcome")
    if status not in ACQUISITION_STATUS_VALUES:
        raise ValueError("ebay_acquisition contains an unsupported status")
    if source_method not in SOURCE_METHOD_VALUES:
        raise ValueError("ebay_acquisition contains an unsupported source_method")
    if not isinstance(outcome["listings"], list):
        raise ValueError("ebay_acquisition.listings must be an array")
    if not isinstance(outcome["diagnostics"], list):
        raise ValueError("ebay_acquisition.diagnostics must be an array")
    if _valid_datetime_string(outcome["retrieved_at"]) is None:
        raise ValueError("ebay_acquisition.retrieved_at must include a timezone")
    if not isinstance(outcome["query"], Mapping):
        raise ValueError("ebay_acquisition.query must be an object")
    if _sanitize_market_context(outcome["market_context"]) is None:
        raise ValueError("ebay_acquisition.market_context is incomplete or invalid")

    outcome["status"] = status
    outcome["source_method"] = source_method
    outcome["query"] = deepcopy(dict(outcome["query"]))
    outcome["market_context"] = _sanitize_market_context(outcome["market_context"])
    return outcome


def _summarize_eligible_ebay_listings(listings: Sequence[object]) -> tuple[dict, bool]:
    seen_listing_ids: set[str] = set()
    sold_counts: list[int] = []
    requires_review = False

    for listing in listings:
        if not isinstance(listing, Mapping):
            requires_review = True
            continue
        listing_id = _nonempty_string(listing.get("listing_id"))
        match_type = _plain_value(listing.get("match_type"))
        decision = _plain_value(listing.get("decision"))
        if decision == "HUMAN_REVIEW" or match_type in _EBAY_REVIEW_MATCH_TYPES:
            requires_review = True
        if listing_id is None or listing_id in seen_listing_ids:
            continue
        seen_listing_ids.add(listing_id)
        sold_count = _positive_integer(listing.get("sold_count"))
        if (
            match_type in _SUPPLY_PASS_MATCH_TYPES
            and listing.get("condition") == "NEW"
            and sold_count is not None
            and decision == "ACCEPT_DEMAND_EVIDENCE"
        ):
            sold_counts.append(sold_count)

    return (
        {
            "eligible_listing_count": len(sold_counts),
            "max_single_listing_sold": max(sold_counts, default=None),
            "aggregate_observed_sold": sum(sold_counts),
        },
        requires_review,
    )


def evaluate_ebay_demand_gate(
    ebay_acquisition: Mapping,
    *,
    expected_canonical_part_number: str | None = None,
) -> dict:
    """Evaluate the eBay observed-demand gate and retain its acquisition record."""

    if not isinstance(ebay_acquisition, Mapping):
        raise ValueError("ebay_acquisition must be an object")
    acquisition = _prepare_ebay_acquisition(ebay_acquisition)
    status = acquisition["status"]
    observed_demand, has_ambiguous_listing = _summarize_eligible_ebay_listings(
        acquisition["listings"]
    )
    acquisition["observed_demand"] = observed_demand

    stage = {
        "status": StageStatus.REVIEW_REQUIRED.value,
        "acquisition": acquisition,
        "reason": "eBay demand evidence requires review.",
    }

    if expected_canonical_part_number is not None:
        actual = acquisition["query"].get("canonical_part_number")
        if actual != expected_canonical_part_number:
            stage["reason"] = "The eBay acquisition query does not match the candidate."
            return stage

    if status not in SUCCESSFUL_ACQUISITION_STATUSES and status != AcquisitionStatus.ZERO_RESULTS.value:
        stage["reason"] = f"eBay acquisition status {status} cannot establish demand."
        return stage
    if not _is_exact_context(acquisition["market_context"], EBAY_US_CONTEXT):
        stage["reason"] = "The eBay market context is not the fixed EBAY_US context."
        return stage
    if status == AcquisitionStatus.ZERO_RESULTS.value:
        stage["status"] = StageStatus.REJECTED.value
        stage["reason"] = "The valid eBay US search returned zero results."
        return stage
    if observed_demand["aggregate_observed_sold"] >= MIN_EBAY_AGGREGATE_OBSERVED_SOLD:
        stage["status"] = StageStatus.PASSED.value
        stage["reason"] = "Eligible eBay listings contain observed sold evidence."
        return stage
    if has_ambiguous_listing:
        stage["reason"] = "The eBay results contain unresolved part-number relations."
        return stage

    stage["status"] = StageStatus.REJECTED.value
    stage["reason"] = "The valid eBay US result page has no eligible sold evidence."
    return stage


def evaluate_amazon_competition_gate(
    amazon_evidence: Mapping | None,
    *,
    expected_canonical_part_number: str | None = None,
) -> dict:
    """Evaluate the manually imported or approved-provider Amazon evidence."""

    if amazon_evidence is None:
        return {
            "status": StageStatus.REVIEW_REQUIRED.value,
            "acquisition_status": None,
            "source_method": None,
            "query": None,
            "market_context": None,
            "relevance_reviewed": None,
            "relevant_result_count": None,
            "evidence": [],
            "reason": "Amazon competition evidence was not provided.",
        }
    if not isinstance(amazon_evidence, Mapping):
        raise ValueError("amazon_evidence must be an object or None")

    raw_acquisition_status = _plain_value(amazon_evidence.get("acquisition_status"))
    raw_source_method = _plain_value(amazon_evidence.get("source_method"))
    acquisition_status = (
        raw_acquisition_status if raw_acquisition_status in ACQUISITION_STATUS_VALUES else None
    )
    source_method = raw_source_method if raw_source_method in SOURCE_METHOD_VALUES else None
    query = _nonempty_string(amazon_evidence.get("query"))
    market_context = _sanitize_market_context(amazon_evidence.get("market_context"))
    relevance_reviewed = _boolean_or_none(amazon_evidence.get("relevance_reviewed"))
    relevant_result_count = _nonnegative_integer(
        amazon_evidence.get("relevant_result_count")
    )
    evidence, evidence_well_formed = _sanitize_evidence_list(
        amazon_evidence.get("evidence")
    )
    stage = {
        "status": StageStatus.REVIEW_REQUIRED.value,
        "acquisition_status": acquisition_status,
        "source_method": source_method,
        "query": query,
        "market_context": market_context,
        "relevance_reviewed": relevance_reviewed,
        "relevant_result_count": relevant_result_count,
        "evidence": evidence,
        "reason": "Amazon competition evidence requires review.",
    }

    if acquisition_status not in SUCCESSFUL_ACQUISITION_STATUSES:
        label = acquisition_status or "MISSING_OR_INVALID"
        stage["reason"] = f"Amazon acquisition status {label} cannot establish competition."
        return stage
    if source_method is None:
        stage["reason"] = "Amazon evidence has no valid source method."
        return stage
    if query is None:
        stage["reason"] = "Amazon evidence does not preserve the executed query."
        return stage
    if expected_canonical_part_number is not None:
        try:
            query_matches_candidate = (
                normalize_part_number(query) == expected_canonical_part_number
            )
        except (TypeError, ValueError):
            query_matches_candidate = False
        if not query_matches_candidate:
            stage["reason"] = "The Amazon query does not match the candidate."
            return stage
    if not _is_exact_context(market_context, AMAZON_US_CONTEXT):
        stage["reason"] = "The Amazon market context is not the fixed AMAZON_US context."
        return stage
    if relevance_reviewed is not True:
        stage["reason"] = "Amazon result relevance has not been manually reviewed."
        return stage
    if relevant_result_count is None:
        stage["reason"] = "Amazon relevant_result_count is missing or invalid."
        return stage
    if not evidence_well_formed or not evidence:
        stage["reason"] = "Amazon source evidence is missing or incomplete."
        return stage
    count_records = [
        record for record in evidence if record["metric"] == "relevant_result_count"
    ]
    if not count_records:
        stage["reason"] = (
            "Amazon evidence does not bind relevant_result_count to its recorded value."
        )
        return stage
    if any(
        _nonnegative_integer(record["value"]) != relevant_result_count
        for record in count_records
    ):
        stage["reason"] = "Amazon relevant_result_count evidence conflicts with its summary."
        return stage
    if any(not _is_real_amazon_url(record["url"]) for record in count_records):
        stage["reason"] = "Amazon count evidence does not use a real amazon.com source URL."
        return stage
    if source_method == "MANUAL" and any(
        not _amazon_search_url_matches_query(record["url"], query)
        for record in count_records
    ):
        stage["reason"] = "Amazon count evidence URL does not preserve the executed query."
        return stage
    if relevant_result_count > MAX_AMAZON_RELEVANT_RESULTS:
        stage["status"] = StageStatus.REJECTED.value
        stage["reason"] = "Amazon has more than five manually reviewed relevant results."
        return stage

    stage["status"] = StageStatus.PASSED.value
    stage["reason"] = "Amazon has at most five manually reviewed relevant results."
    return stage


def _sanitize_matched_part_numbers(evidence: Mapping) -> tuple[list[str], bool]:
    raw_values = evidence.get("matched_part_numbers", [])
    if isinstance(raw_values, str) or not isinstance(raw_values, list):
        return [], False
    values: list[str] = []
    valid = True
    for value in raw_values:
        part_number = _nonempty_string(value)
        if part_number is None:
            valid = False
            continue
        if part_number not in values:
            values.append(part_number)

    singular = evidence.get("matched_part_number")
    if singular is not None:
        part_number = _nonempty_string(singular)
        if part_number is None:
            valid = False
        elif part_number not in values:
            values.append(part_number)
    return values, valid


def _is_real_1688_url(value: str | None) -> bool:
    if value is None:
        return False
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (hostname == "1688.com" or hostname.endswith(".1688.com"))
    )


def _supply_metric_binding_issue(
    evidence: Sequence[Mapping],
    *,
    metric: str,
    expected_value: object,
    offer_url: str,
) -> str | None:
    records = [record for record in evidence if record.get("metric") == metric]
    if not records:
        return f"1688 evidence is missing the {metric} metric binding."

    for record in records:
        if record.get("url") != offer_url or not _is_real_1688_url(record.get("url")):
            return f"1688 {metric} evidence URL does not match the 1688 offer URL."

        raw_value = record.get("value")
        if metric == "purchasable":
            matches = isinstance(raw_value, bool) and raw_value is expected_value
        elif metric == "price_cny":
            normalized = _nonnegative_number(raw_value)
            matches = normalized is not None and normalized == expected_value
        elif metric == "moq":
            normalized = _positive_integer(raw_value)
            matches = normalized is not None and normalized == expected_value
        else:
            raise ValueError(f"unsupported supply evidence metric: {metric}")

        if not matches:
            return f"1688 {metric} evidence conflicts with the summary value."
    return None


def evaluate_supply_gate(
    supply_evidence: Mapping | None,
    *,
    max_acceptable_moq: int,
    expected_canonical_part_number: str | None = None,
) -> dict:
    """Evaluate the 1688 purchasable-supply gate."""

    max_moq = _validate_moq_policy(max_acceptable_moq)
    if supply_evidence is None:
        stage = make_not_checked_supply_stage(
            "1688 supply evidence was not provided."
        )
        stage["status"] = StageStatus.REVIEW_REQUIRED.value
        return stage
    if not isinstance(supply_evidence, Mapping):
        raise ValueError("supply_evidence must be an object or None")

    raw_acquisition_status = _plain_value(supply_evidence.get("acquisition_status"))
    raw_source_method = _plain_value(supply_evidence.get("source_method"))
    raw_match_type = _plain_value(supply_evidence.get("match_type"))
    acquisition_status = (
        raw_acquisition_status if raw_acquisition_status in ACQUISITION_STATUS_VALUES else None
    )
    source_method = raw_source_method if raw_source_method in SOURCE_METHOD_VALUES else None
    match_type = raw_match_type if raw_match_type in MATCH_TYPE_VALUES else None
    matched_part_numbers, part_numbers_well_formed = _sanitize_matched_part_numbers(
        supply_evidence
    )
    supplier = _nonempty_string(supply_evidence.get("supplier"))
    offer_url = _valid_uri(supply_evidence.get("offer_url"))
    purchasable = _boolean_or_none(supply_evidence.get("purchasable"))
    price_cny = _nonnegative_number(supply_evidence.get("price_cny"))
    moq = _positive_integer(supply_evidence.get("moq"))
    evidence, evidence_well_formed = _sanitize_evidence_list(supply_evidence.get("evidence"))
    stage = {
        "status": StageStatus.REVIEW_REQUIRED.value,
        "acquisition_status": acquisition_status,
        "source_method": source_method,
        "matched_part_numbers": matched_part_numbers,
        "match_type": match_type,
        "supplier": supplier,
        "offer_url": offer_url,
        "purchasable": purchasable,
        "price_cny": price_cny,
        "moq": moq,
        "evidence": evidence,
        "reason": "1688 supply evidence requires review.",
    }

    if acquisition_status not in SUCCESSFUL_ACQUISITION_STATUSES:
        label = acquisition_status or "MISSING_OR_INVALID"
        stage["reason"] = f"1688 acquisition status {label} cannot establish supply."
        return stage
    if source_method is None:
        stage["reason"] = "1688 evidence has no valid source method."
        return stage
    if match_type not in _SUPPLY_PASS_MATCH_TYPES:
        stage["reason"] = "The 1688 part-number relation is not exact."
        return stage
    if not part_numbers_well_formed or not matched_part_numbers:
        stage["reason"] = "1688 evidence does not identify a matched part number."
        return stage
    if expected_canonical_part_number is not None:
        try:
            matches_candidate = any(
                normalize_part_number(part_number) == expected_canonical_part_number
                for part_number in matched_part_numbers
            )
        except (TypeError, ValueError):
            matches_candidate = False
        if not matches_candidate:
            stage["reason"] = "The 1688 matched part number does not match the candidate."
            return stage
    if supplier is None or offer_url is None or not evidence_well_formed or not evidence:
        stage["reason"] = "1688 source evidence is missing or incomplete."
        return stage
    if not _is_real_1688_url(offer_url):
        stage["reason"] = "The 1688 offer URL does not use a real 1688 host."
        return stage
    if purchasable is None:
        stage["reason"] = "1688 purchasability is missing or invalid."
        return stage

    binding_issue = _supply_metric_binding_issue(
        evidence,
        metric="purchasable",
        expected_value=purchasable,
        offer_url=offer_url,
    )
    if binding_issue is not None:
        stage["reason"] = binding_issue
        return stage
    if purchasable is False:
        stage["status"] = StageStatus.REJECTED.value
        stage["reason"] = "The evidenced 1688 offer is not purchasable."
        return stage
    if moq is None:
        stage["reason"] = "1688 MOQ is missing or invalid."
        return stage
    binding_issue = _supply_metric_binding_issue(
        evidence,
        metric="moq",
        expected_value=moq,
        offer_url=offer_url,
    )
    if binding_issue is not None:
        stage["reason"] = binding_issue
        return stage
    if moq > max_moq:
        stage["status"] = StageStatus.REJECTED.value
        stage["reason"] = "The evidenced 1688 MOQ exceeds the configured maximum."
        return stage
    if price_cny is None:
        stage["reason"] = "1688 price evidence is missing or invalid."
        return stage
    binding_issue = _supply_metric_binding_issue(
        evidence,
        metric="price_cny",
        expected_value=price_cny,
        offer_url=offer_url,
    )
    if binding_issue is not None:
        stage["reason"] = binding_issue
        return stage

    stage["status"] = StageStatus.PASSED.value
    stage["reason"] = "An exact, purchasable 1688 offer satisfies the MOQ policy."
    return stage


def decide_opportunity(
    amazon_competition: str,
    ebay_demand: str,
    alibaba_1688_supply: str,
) -> str:
    """Apply the contract's final three-stage decision truth table."""

    statuses = tuple(
        _plain_value(status)
        for status in (amazon_competition, ebay_demand, alibaba_1688_supply)
    )
    if any(status not in STAGE_STATUS_VALUES for status in statuses):
        raise ValueError("all stage statuses must be valid V0.1 stage statuses")
    if StageStatus.REJECTED.value in statuses:
        return OpportunityDecision.REJECTED.value
    if all(status == StageStatus.PASSED.value for status in statuses):
        return OpportunityDecision.OPPORTUNITY_CANDIDATE.value
    return OpportunityDecision.REVIEW_REQUIRED.value


def _decision_reasons(decision: str, stages: Mapping[str, Mapping]) -> list[str]:
    if decision == OpportunityDecision.OPPORTUNITY_CANDIDATE.value:
        return ["All three opportunity gates passed."]
    reasons = [
        f"{name}: {stage['reason']}"
        for name, stage in stages.items()
        if stage["status"] in {StageStatus.REJECTED.value, StageStatus.REVIEW_REQUIRED.value}
    ]
    return reasons or ["One or more opportunity gates did not pass."]


def evaluate_candidate(
    raw_part_number: str,
    ebay_acquisition: Mapping,
    amazon_evidence: Mapping | None,
    supply_evidence: Mapping | None,
    *,
    max_acceptable_moq: int,
    generated_at: str | datetime | None = None,
) -> dict:
    """Evaluate one candidate in the fixed eBay -> Amazon -> 1688 order."""

    max_moq = _validate_moq_policy(max_acceptable_moq)
    candidate = build_part_query(raw_part_number)
    canonical = candidate["canonical_part_number"]

    ebay_stage = evaluate_ebay_demand_gate(
        ebay_acquisition,
        expected_canonical_part_number=canonical,
    )
    if ebay_stage["status"] != StageStatus.PASSED.value:
        amazon_stage = make_not_checked_amazon_stage(
            "Not checked because the eBay demand gate did not pass."
        )
        supply_stage = make_not_checked_supply_stage(
            "Not checked because the eBay demand gate did not pass."
        )
    else:
        amazon_stage = evaluate_amazon_competition_gate(
            amazon_evidence,
            expected_canonical_part_number=canonical,
        )
        if amazon_stage["status"] != StageStatus.PASSED.value:
            supply_stage = make_not_checked_supply_stage(
                "Not checked because the Amazon competition gate did not pass."
            )
        else:
            supply_stage = evaluate_supply_gate(
                supply_evidence,
                max_acceptable_moq=max_moq,
                expected_canonical_part_number=canonical,
            )

    stages = {
        "amazon_competition": amazon_stage,
        "ebay_demand": ebay_stage,
        "alibaba_1688_supply": supply_stage,
    }
    decision = decide_opportunity(
        amazon_stage["status"],
        ebay_stage["status"],
        supply_stage["status"],
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "candidate": candidate,
        "policy": {
            "max_amazon_relevant_results": MAX_AMAZON_RELEVANT_RESULTS,
            "min_ebay_aggregate_observed_sold": MIN_EBAY_AGGREGATE_OBSERVED_SOLD,
            "max_acceptable_moq": max_moq,
        },
        "stages": stages,
        "decision": decision,
        "reasons": _decision_reasons(decision, stages),
        "generated_at": _coerce_generated_at(generated_at),
    }
