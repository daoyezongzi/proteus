"""Deterministic three-gate evaluation for Proteus V0.2."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from enum import Enum
from urllib.parse import parse_qs, urlparse

from proteus.models import (
    ACQUISITION_STATUS_VALUES,
    AMAZON_US_CONTEXT,
    EBAY_US_CONTEXT,
    MATCH_TYPE_VALUES,
    MAX_AMAZON_RELEVANT_RESULTS,
    MIN_EBAY_AGGREGATE_OBSERVED_SOLD,
    RELEVANCE_METHOD_VALUES,
    SCHEMA_VERSION,
    SOURCE_METHOD_VALUES,
    STAGE_STATUS_VALUES,
    SUPPORTED_INPUT_SCHEMA_VERSIONS,
    AcquisitionStatus,
    MatchType,
    OpportunityDecision,
    StageStatus,
    SUCCESSFUL_ACQUISITION_STATUSES,
    make_not_checked_amazon_stage,
    make_not_checked_ebay_stage,
    make_not_checked_supply_stage,
)
from proteus.normalization import build_part_query, normalize_part_number


_EVIDENCE_EXTRACTION_METHODS = frozenset(
    {
        "OFFICIAL_API",
        "MANAGED_API",
        "DETERMINISTIC_RULE",
        "ORDER_PREVIEW",
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
_CANDIDATE_REPORT_MAX_AGE_HOURS = 192
_STAGE_EVIDENCE_MAX_AGE_HOURS = 24
_ORDER_PREVIEW_MAX_AGE_MINUTES = 15
_FUTURE_CLOCK_SKEW_MINUTES = 5
_CANDIDATE_REPORT_MAX_AGE = timedelta(hours=_CANDIDATE_REPORT_MAX_AGE_HOURS)
_STAGE_EVIDENCE_MAX_AGE = timedelta(hours=_STAGE_EVIDENCE_MAX_AGE_HOURS)
_ORDER_PREVIEW_MAX_AGE = timedelta(minutes=_ORDER_PREVIEW_MAX_AGE_MINUTES)
_FUTURE_CLOCK_SKEW = timedelta(minutes=_FUTURE_CLOCK_SKEW_MINUTES)


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


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _valid_datetime_string(value: object) -> str | None:
    return value if isinstance(value, str) and _parse_datetime(value) is not None else None


def _is_fresh(
    timestamp: object,
    reference: datetime,
    max_age: timedelta,
) -> bool:
    parsed = _parse_datetime(timestamp)
    if parsed is None:
        return False
    age = reference - parsed
    return -_FUTURE_CLOCK_SKEW <= age <= max_age


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


def _sanitize_preview_binding(value: object) -> tuple[dict | None, bool]:
    if value is None:
        return None, True
    if not isinstance(value, Mapping):
        return None, False
    provider = _nonempty_string(value.get("provider"))
    request_id = _nonempty_string(value.get("request_id"))
    offer_id = _nonempty_string(value.get("offer_id"))
    sku_id = _nonempty_string(value.get("sku_id"))
    quantity = _positive_integer(value.get("quantity"))
    if any(item is None for item in (provider, request_id, offer_id, sku_id, quantity)):
        return None, False
    return (
        {
            "provider": provider,
            "request_id": request_id,
            "offer_id": offer_id,
            "sku_id": sku_id,
            "quantity": quantity,
        },
        True,
    )


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
    preview_binding, preview_binding_well_formed = _sanitize_preview_binding(
        value.get("preview_binding")
    )
    if (
        metric is None
        or source is None
        or url is None
        or retrieved_at is None
        or extraction_method not in _EVIDENCE_EXTRACTION_METHODS
        or raw_evidence is None
        or confidence is None
        or confidence > 1
        or not preview_binding_well_formed
        or "value" not in value
    ):
        return None
    record = {
        "metric": metric,
        "value": deepcopy(value["value"]),
        "source": source,
        "url": url,
        "retrieved_at": retrieved_at,
        "extraction_method": extraction_method,
        "raw_evidence": raw_evidence,
        "confidence": confidence,
    }
    if "preview_binding" in value:
        record["preview_binding"] = preview_binding
    return record


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


def _prepare_candidate_source(value: Mapping | None) -> dict:
    if value is None:
        return {
            "method": "SUPPLIED_POOL",
            "provider": "USER_INPUT",
            "source_reference": None,
            "source_row": None,
            "source_field": None,
            "identifier_type": None,
            "category": None,
            "brand": None,
            "item_name": None,
            "report_generated_at": None,
        }
    if not isinstance(value, Mapping):
        raise ValueError("candidate_source must be an object or None")

    method = _plain_value(value.get("method"))
    if method not in {
        "SUPPLIED_POOL",
        "AMAZON_B2B_REPORT_REPLAY",
        "AMAZON_B2B_REPORT_API",
    }:
        raise ValueError("candidate_source.method is unsupported")
    provider = _nonempty_string(value.get("provider"))
    if provider is None:
        raise ValueError("candidate_source.provider must be a non-empty string")

    source_reference = value.get("source_reference")
    if source_reference is not None:
        source_reference = _nonempty_string(source_reference)
        if source_reference is None:
            raise ValueError(
                "candidate_source.source_reference must be non-empty or null"
            )
    source_row = value.get("source_row")
    if source_row is not None:
        source_row = _positive_integer(source_row)
        if source_row is None:
            raise ValueError("candidate_source.source_row must be positive or null")
    source_field = value.get("source_field")
    if source_field is not None:
        source_field = _nonempty_string(source_field)
        if source_field is None:
            raise ValueError(
                "candidate_source.source_field must be non-empty or null"
            )
    identifier_type = value.get("identifier_type")
    if identifier_type not in {None, "partNumber", "modelNumber", "EAN", "UPC", "ISBN"}:
        raise ValueError("candidate_source.identifier_type is unsupported")
    optional_text: dict[str, str | None] = {}
    for field_name in ("category", "brand", "item_name"):
        field_value = value.get(field_name)
        if field_value is None:
            optional_text[field_name] = None
            continue
        text_value = _nonempty_string(field_value)
        if text_value is None:
            raise ValueError(
                f"candidate_source.{field_name} must be non-empty or null"
            )
        optional_text[field_name] = text_value

    report_generated_at = value.get("report_generated_at")
    if report_generated_at is not None:
        report_generated_at = _valid_datetime_string(report_generated_at)
        if report_generated_at is None:
            raise ValueError(
                "candidate_source.report_generated_at must be a date-time with "
                "timezone or null"
            )

    if method in {"AMAZON_B2B_REPORT_REPLAY", "AMAZON_B2B_REPORT_API"} and any(
        item is None
        for item in (source_reference, source_row, source_field, identifier_type)
    ):
        raise ValueError(
            "Amazon B2B candidate source requires reference, row, field, and identifier type"
        )

    return {
        "method": method,
        "provider": provider,
        "source_reference": source_reference,
        "source_row": source_row,
        "source_field": source_field,
        "identifier_type": identifier_type,
        "report_generated_at": report_generated_at,
        **optional_text,
    }


def _evidence_is_fresh(
    evidence: object,
    reference: datetime,
    *,
    require_nonempty: bool = True,
) -> bool:
    if not isinstance(evidence, list) or (require_nonempty and not evidence):
        return False
    return all(
        isinstance(record, Mapping)
        and _is_fresh(
            record.get("retrieved_at"),
            reference,
            _STAGE_EVIDENCE_MAX_AGE,
        )
        for record in evidence
    )


def _candidate_source_is_automation_provenance(value: Mapping) -> bool:
    category = _nonempty_string(value.get("category"))
    return bool(
        value.get("method") == "AMAZON_B2B_REPORT_API"
        and value.get("provider") == "AMAZON_SP_API"
        and _nonempty_string(value.get("source_reference")) is not None
        and _positive_integer(value.get("source_row")) is not None
        and _nonempty_string(value.get("source_field")) is not None
        and value.get("identifier_type")
        in {"partNumber", "modelNumber", "EAN", "UPC", "ISBN"}
        and category is not None
        and category.casefold() == "automotive"
    )


def _evidence_uses_only_methods(evidence: object, allowed: set[str]) -> bool:
    return bool(
        isinstance(evidence, list)
        and evidence
        and all(
            isinstance(record, Mapping)
            and record.get("extraction_method") in allowed
            for record in evidence
        )
    )


def _ebay_evidence_is_fresh(acquisition: Mapping, reference: datetime) -> bool:
    if not _is_fresh(
        acquisition.get("retrieved_at"),
        reference,
        _STAGE_EVIDENCE_MAX_AGE,
    ):
        return False
    listings = acquisition.get("listings")
    if not isinstance(listings, list) or not listings:
        return False
    saw_evidence = False
    for listing in listings:
        if not isinstance(listing, Mapping):
            return False
        listing_evidence = listing.get("evidence")
        if not isinstance(listing_evidence, list) or not listing_evidence:
            return False
        saw_evidence = True
        if not _evidence_is_fresh(
            listing_evidence,
            reference,
            require_nonempty=True,
        ):
            return False
    return saw_evidence


def _ebay_evidence_is_official(acquisition: Mapping) -> bool:
    listings = acquisition.get("listings")
    return bool(
        isinstance(listings, list)
        and listings
        and all(
            isinstance(listing, Mapping)
            and _evidence_uses_only_methods(
                listing.get("evidence"), {"OFFICIAL_API"}
            )
            for listing in listings
        )
    )


def _supply_evidence_is_official(supply: Mapping) -> bool:
    evidence = supply.get("evidence")
    if not _evidence_uses_only_methods(evidence, {"OFFICIAL_API", "ORDER_PREVIEW"}):
        return False
    required_methods = {
        "price_cny": "OFFICIAL_API",
        "moq": "OFFICIAL_API",
        "purchasable": "ORDER_PREVIEW",
        "preview_payment_cny": "ORDER_PREVIEW",
        "preview_shipping_cny": "ORDER_PREVIEW",
    }
    return all(
        any(
            isinstance(record, Mapping)
            and record.get("metric") == metric
            and record.get("extraction_method") == method
            for record in evidence
        )
        for metric, method in required_methods.items()
    )


def _has_bound_preview_metric(
    supply: Mapping,
    order_preview: Mapping,
    metric: str,
    expected_value: int | float,
) -> bool:
    evidence = supply.get("evidence")
    if not isinstance(evidence, list):
        return False
    for record in evidence:
        if not isinstance(record, Mapping):
            continue
        if (
            record.get("metric") != metric
            or record.get("extraction_method") != "ORDER_PREVIEW"
            or record.get("url") != supply.get("offer_url")
            or record.get("retrieved_at") != order_preview.get("retrieved_at")
            or not _preview_binding_matches(record, order_preview)
        ):
            continue
        value = _nonnegative_number(record.get("value"))
        if value is not None and value == expected_value:
            return True
    return False


def _is_automation_qualified(
    candidate_source: Mapping,
    stages: Mapping[str, Mapping],
    decision: str,
    generated_at: object,
) -> bool:
    reference = _parse_datetime(generated_at)
    if (
        reference is None
        or decision != OpportunityDecision.OPPORTUNITY_CANDIDATE.value
        or not _candidate_source_is_automation_provenance(candidate_source)
        or not _is_fresh(
            candidate_source.get("report_generated_at"),
            reference,
            _CANDIDATE_REPORT_MAX_AGE,
        )
        or not isinstance(stages, Mapping)
    ):
        return False
    amazon = stages.get("amazon_competition")
    ebay = stages.get("ebay_demand")
    supply = stages.get("alibaba_1688_supply")
    if not all(isinstance(stage, Mapping) for stage in (amazon, ebay, supply)):
        return False
    ebay_acquisition = ebay.get("acquisition")
    order_preview = supply.get("order_preview")
    if not isinstance(ebay_acquisition, Mapping) or not isinstance(
        order_preview, Mapping
    ):
        return False
    if _order_preview_binding_issue(
        order_preview,
        offer_url=supply.get("offer_url"),
        moq=supply.get("moq"),
        evidence=supply.get("evidence"),
        expected_purchasable=True,
    ) is not None:
        return False
    payment_cny = _nonnegative_number(order_preview.get("payment_cny"))
    shipping_cny = _nonnegative_number(order_preview.get("shipping_cny"))
    if payment_cny is None or shipping_cny is None:
        return False
    return bool(
        all(
            stage.get("status") == StageStatus.PASSED.value
            for stage in (amazon, ebay, supply)
        )
        and amazon.get("relevance_method") == "DETERMINISTIC_EXACT"
        and amazon.get("source_method") == "OFFICIAL_API"
        and _evidence_is_fresh(amazon.get("evidence"), reference)
        and _evidence_uses_only_methods(
            amazon.get("evidence"), {"OFFICIAL_API"}
        )
        and ebay_acquisition.get("source_method") == "OFFICIAL_API"
        and _ebay_evidence_is_fresh(ebay_acquisition, reference)
        and _ebay_evidence_is_official(ebay_acquisition)
        and supply.get("source_method") == "OFFICIAL_API"
        and _evidence_is_fresh(supply.get("evidence"), reference)
        and _supply_evidence_is_official(supply)
        and _is_fresh(
            order_preview.get("retrieved_at"),
            reference,
            _ORDER_PREVIEW_MAX_AGE,
        )
        and _has_bound_preview_metric(
            supply, order_preview, "preview_payment_cny", payment_cny
        )
        and _has_bound_preview_metric(
            supply, order_preview, "preview_shipping_cny", shipping_cny
        )
    )


def is_report_automation_qualified(report: Mapping) -> bool:
    """Recompute whether a V0.2 report satisfies the automation boundary."""

    if not isinstance(report, Mapping):
        return False
    candidate_source = report.get("candidate_source")
    stages = report.get("stages")
    if not isinstance(candidate_source, Mapping) or not isinstance(stages, Mapping):
        return False
    try:
        return _is_automation_qualified(
            candidate_source,
            stages,
            _plain_value(report.get("decision")),
            report.get("generated_at"),
        )
    except (KeyError, TypeError, ValueError):
        return False


def is_report_opportunity_candidate_semantically_valid(report: Mapping) -> bool:
    """Re-run all three gates for a claimed V0.2 opportunity candidate."""

    if (
        not isinstance(report, Mapping)
        or _plain_value(report.get("decision"))
        != OpportunityDecision.OPPORTUNITY_CANDIDATE.value
    ):
        return False
    try:
        candidate = report["candidate"]
        policy = report["policy"]
        stages = report["stages"]
        if not all(isinstance(value, Mapping) for value in (candidate, policy, stages)):
            return False
        canonical = normalize_part_number(candidate.get("raw_part_number"))
        if candidate.get("canonical_part_number") != canonical:
            return False
        amazon = evaluate_amazon_competition_gate(
            stages["amazon_competition"],
            expected_canonical_part_number=canonical,
        )
        ebay_stage = stages["ebay_demand"]
        ebay = evaluate_ebay_demand_gate(
            ebay_stage["acquisition"],
            expected_canonical_part_number=canonical,
        )
        supply = evaluate_supply_gate(
            stages["alibaba_1688_supply"],
            max_acceptable_moq=policy["max_acceptable_moq"],
            expected_canonical_part_number=canonical,
        )
        return all(
            stage.get("status") == StageStatus.PASSED.value
            for stage in (amazon, ebay, supply)
        )
    except (KeyError, TypeError, ValueError):
        return False


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
    if (
        outcome["schema_version"] not in SUPPORTED_INPUT_SCHEMA_VERSIONS
        or outcome["platform"] != "EBAY"
    ):
        raise ValueError("ebay_acquisition must be a supported EBAY AcquisitionOutcome")
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
    outcome["schema_version"] = SCHEMA_VERSION
    outcome["query"] = deepcopy(dict(outcome["query"]))
    outcome["market_context"] = _sanitize_market_context(outcome["market_context"])
    return outcome


def _is_real_ebay_url(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urlparse(value)
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and (hostname == "ebay.com" or hostname.endswith(".ebay.com"))
    )


def _has_bound_ebay_sold_evidence(
    listing: Mapping,
    sold_count: int,
    source_method: str,
) -> bool:
    evidence_items = listing.get("evidence")
    if not isinstance(evidence_items, list):
        return False
    for evidence in evidence_items:
        if not isinstance(evidence, Mapping):
            continue
        if evidence.get("metric") not in {"sold_count", "salesQuantity"}:
            continue
        if _positive_integer(evidence.get("value")) != sold_count:
            continue
        extraction_method = _plain_value(evidence.get("extraction_method"))
        evidence_url = evidence.get("url")
        if source_method in {"OFFICIAL_API", "MANAGED_API"}:
            if extraction_method != source_method:
                continue
            if _valid_uri(evidence_url) is not None:
                return True
        elif source_method == "MANUAL":
            if (
                extraction_method == "MANUAL_REVIEW"
                and _is_real_ebay_url(evidence_url)
            ):
                return True
        elif (
            extraction_method
            in {
                "VISIBLE_TEXT",
                "JSON_LD",
                "EMBEDDED_STATE",
                "SEARCH_SNIPPET",
                "DETERMINISTIC_RULE",
            }
            and _is_real_ebay_url(evidence_url)
        ):
            return True
    return False


def _summarize_eligible_ebay_listings(
    listings: Sequence[object],
    source_method: str,
) -> tuple[dict, bool]:
    seen_listing_ids: set[str] = set()
    sold_counts: list[int] = []
    requires_review = False

    for listing in listings:
        if not isinstance(listing, Mapping):
            requires_review = True
            continue
        listing_id = _nonempty_string(listing.get("listing_id"))
        listing_url_is_valid = _is_real_ebay_url(listing.get("url"))
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
            and listing_url_is_valid
            and _has_bound_ebay_sold_evidence(
                listing, sold_count, source_method
            )
        ):
            sold_counts.append(sold_count)
        elif decision == "ACCEPT_DEMAND_EVIDENCE" and sold_count is not None:
            requires_review = True

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
        acquisition["listings"], acquisition["source_method"]
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
    if status == AcquisitionStatus.PARTIAL_SUCCESS.value:
        stage["reason"] = (
            "Partial eBay results cannot establish the absence of observed demand."
        )
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
    """Evaluate deterministic-provider or legacy manual Amazon evidence."""

    if amazon_evidence is None:
        return {
            "status": StageStatus.REVIEW_REQUIRED.value,
            "acquisition_status": None,
            "source_method": None,
            "query": None,
            "market_context": None,
            "relevance_method": None,
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
    raw_relevance_method = _plain_value(amazon_evidence.get("relevance_method"))
    relevance_method = (
        raw_relevance_method
        if raw_relevance_method in RELEVANCE_METHOD_VALUES
        else None
    )
    if (
        relevance_method is None
        and _boolean_or_none(amazon_evidence.get("relevance_reviewed")) is True
        and source_method == "MANUAL"
    ):
        relevance_method = "MANUAL_REVIEW"
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
        "relevance_method": relevance_method,
        "relevant_result_count": relevant_result_count,
        "evidence": evidence,
        "reason": "Amazon competition evidence requires review.",
    }

    if acquisition_status not in (
        SUCCESSFUL_ACQUISITION_STATUSES | {AcquisitionStatus.ZERO_RESULTS.value}
    ):
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
    if relevance_method is None:
        stage["reason"] = "Amazon result relevance has no valid evaluation method."
        return stage
    if relevance_method == "MANUAL_REVIEW" and source_method != "MANUAL":
        stage["reason"] = "Manual Amazon relevance review requires MANUAL provenance."
        return stage
    if relevance_method == "DETERMINISTIC_EXACT" and source_method not in {
        "OFFICIAL_API",
        "MANAGED_API",
    }:
        stage["reason"] = (
            "Deterministic Amazon relevance requires an API source method."
        )
        return stage
    if (
        relevance_method == "DETERMINISTIC_EXACT"
        and acquisition_status == AcquisitionStatus.PARTIAL_SUCCESS.value
    ):
        stage["reason"] = (
            "Partial Amazon API results cannot prove the competition threshold."
        )
        return stage
    if relevant_result_count is None:
        stage["reason"] = "Amazon relevant_result_count is missing or invalid."
        return stage
    if (
        acquisition_status == AcquisitionStatus.ZERO_RESULTS.value
        and relevant_result_count != 0
    ):
        stage["reason"] = "Amazon ZERO_RESULTS conflicts with a non-zero exact count."
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
    if source_method == "MANUAL" and any(
        record["extraction_method"] != "MANUAL_REVIEW"
        for record in count_records
    ):
        stage["reason"] = "Manual Amazon count lacks manual-review provenance."
        return stage
    if relevance_method == "DETERMINISTIC_EXACT" and any(
        record["extraction_method"] != source_method for record in count_records
    ):
        stage["reason"] = (
            "Amazon deterministic count provenance does not match its API source."
        )
        return stage
    if relevant_result_count > MAX_AMAZON_RELEVANT_RESULTS:
        stage["status"] = StageStatus.REJECTED.value
        stage["reason"] = "Amazon has more than five relevant exact results."
        return stage

    stage["status"] = StageStatus.PASSED.value
    stage["reason"] = "Amazon has at most five relevant exact results."
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


def _sanitize_order_preview(value: object) -> tuple[dict | None, bool]:
    if value is None:
        return None, True
    if not isinstance(value, Mapping):
        return None, False
    required = {
        "provider",
        "request_id",
        "offer_id",
        "sku_id",
        "quantity",
        "currency",
        "payment_cny",
        "shipping_cny",
        "retrieved_at",
    }
    if not required.issubset(value):
        return None, False
    provider = _nonempty_string(value.get("provider"))
    request_id = _nonempty_string(value.get("request_id"))
    offer_id = _nonempty_string(value.get("offer_id"))
    sku_id = _nonempty_string(value.get("sku_id"))
    quantity = _positive_integer(value.get("quantity"))
    currency = _nonempty_string(value.get("currency"))
    payment_cny = value.get("payment_cny")
    shipping_cny = value.get("shipping_cny")
    retrieved_at = _valid_datetime_string(value.get("retrieved_at"))
    if payment_cny is not None:
        payment_cny = _nonnegative_number(payment_cny)
    if shipping_cny is not None:
        shipping_cny = _nonnegative_number(shipping_cny)
    if (
        provider is None
        or request_id is None
        or offer_id is None
        or sku_id is None
        or quantity is None
        or currency != "CNY"
        or (value.get("payment_cny") is not None and payment_cny is None)
        or (value.get("shipping_cny") is not None and shipping_cny is None)
        or retrieved_at is None
    ):
        return None, False
    return (
        {
            "provider": provider,
            "request_id": request_id,
            "offer_id": offer_id,
            "sku_id": sku_id,
            "quantity": quantity,
            "currency": currency,
            "payment_cny": payment_cny,
            "shipping_cny": shipping_cny,
            "retrieved_at": retrieved_at,
        },
        True,
    )


def _offer_id_from_1688_url(value: object) -> str | None:
    if not isinstance(value, str) or not _is_real_1688_url(value):
        return None
    match = re.fullmatch(r"/offer/([^/]+)\.html", urlparse(value).path)
    return match.group(1) if match else None


def _order_preview_binding_issue(
    order_preview: object,
    *,
    offer_url: object,
    moq: object,
    evidence: object,
    expected_purchasable: bool,
) -> str | None:
    preview, well_formed = _sanitize_order_preview(order_preview)
    if not well_formed or preview is None:
        return "1688 API supply requires a complete structured order preview."
    if preview["offer_id"] != _offer_id_from_1688_url(offer_url):
        return "1688 order preview offer_id does not match the 1688 offer URL."
    if preview["quantity"] != _positive_integer(moq):
        return "1688 order preview quantity does not match the evidenced MOQ."
    if not isinstance(evidence, list):
        return "1688 order preview is not bound to source evidence."
    for record in evidence:
        if not isinstance(record, Mapping):
            continue
        if (
            record.get("metric") == "purchasable"
            and record.get("value") is expected_purchasable
            and record.get("extraction_method") == "ORDER_PREVIEW"
            and record.get("url") == offer_url
            and record.get("retrieved_at") == preview["retrieved_at"]
            and _preview_binding_matches(record, preview)
        ):
            if not expected_purchasable:
                return None
            bound_metrics = {
                candidate.get("metric")
                for candidate in evidence
                if isinstance(candidate, Mapping)
                and candidate.get("metric") in {"price_cny", "moq"}
                and candidate.get("url") == offer_url
                and _preview_binding_matches(candidate, preview)
            }
            if {"price_cny", "moq"}.issubset(bound_metrics):
                return None
            return (
                "1688 price/MOQ evidence is not bound to the previewed offer, "
                "SKU, request, and quantity."
            )
    return "1688 order preview is not bound to matching purchasability evidence."


def _preview_binding_matches(record: Mapping, preview: Mapping) -> bool:
    binding, well_formed = _sanitize_preview_binding(record.get("preview_binding"))
    return bool(
        well_formed
        and binding is not None
        and all(
            binding.get(field_name) == preview.get(field_name)
            for field_name in (
                "provider",
                "request_id",
                "offer_id",
                "sku_id",
                "quantity",
            )
        )
    )


def _supply_metric_binding_issue(
    evidence: Sequence[Mapping],
    *,
    metric: str,
    expected_value: object,
    offer_url: str,
    source_method: str,
) -> str | None:
    records = [record for record in evidence if record.get("metric") == metric]
    if not records:
        return f"1688 evidence is missing the {metric} metric binding."

    for record in records:
        if record.get("url") != offer_url or not _is_real_1688_url(record.get("url")):
            return f"1688 {metric} evidence URL does not match the 1688 offer URL."

        expected_extraction = (
            "MANUAL_REVIEW" if source_method == "MANUAL" else "ORDER_PREVIEW"
        )
        if (
            metric == "purchasable"
            and record.get("extraction_method") != expected_extraction
        ):
            if expected_extraction == "ORDER_PREVIEW":
                return "1688 API purchasability must come from an order preview."
                return "Manual 1688 purchasability requires manual-review provenance."

        detail_extraction = {
            "OFFICIAL_API": "OFFICIAL_API",
            "MANAGED_API": "MANAGED_API",
            "MANUAL": "MANUAL_REVIEW",
        }.get(source_method)
        if (
            metric in {"price_cny", "moq"}
            and detail_extraction is not None
            and record.get("extraction_method") != detail_extraction
        ):
            return (
                f"1688 {metric} evidence provenance does not match its "
                "source method."
            )

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
    order_preview, order_preview_well_formed = _sanitize_order_preview(
        supply_evidence.get("order_preview")
    )
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
        "order_preview": order_preview,
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
        source_method=source_method,
    )
    if binding_issue is not None:
        stage["reason"] = binding_issue
        return stage
    if not order_preview_well_formed:
        stage["reason"] = "1688 order preview is malformed."
        return stage
    if source_method != "MANUAL":
        preview_issue = _order_preview_binding_issue(
            order_preview,
            offer_url=offer_url,
            moq=moq,
            evidence=evidence,
            expected_purchasable=purchasable,
        )
        if preview_issue is not None:
            stage["reason"] = preview_issue
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
        source_method=source_method,
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
        source_method=source_method,
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
        raise ValueError("all stage statuses must be valid V0.2 stage statuses")
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
    ebay_acquisition: Mapping | None,
    amazon_evidence: Mapping | None,
    supply_evidence: Mapping | None,
    *,
    max_acceptable_moq: int,
    candidate_source: Mapping | None = None,
    generated_at: str | datetime | None = None,
) -> dict:
    """Evaluate one candidate in the fixed Amazon -> eBay -> 1688 order."""

    max_moq = _validate_moq_policy(max_acceptable_moq)
    candidate = build_part_query(raw_part_number)
    canonical = candidate["canonical_part_number"]

    amazon_stage = evaluate_amazon_competition_gate(
        amazon_evidence,
        expected_canonical_part_number=canonical,
    )
    if amazon_stage["status"] != StageStatus.PASSED.value:
        ebay_stage = make_not_checked_ebay_stage(
            "Not checked because the Amazon competition gate did not pass."
        )
        supply_stage = make_not_checked_supply_stage(
            "Not checked because the Amazon competition gate did not pass."
        )
    else:
        if ebay_acquisition is None:
            raise ValueError(
                "ebay_acquisition is required after the Amazon gate passes"
            )
        ebay_stage = evaluate_ebay_demand_gate(
            ebay_acquisition,
            expected_canonical_part_number=canonical,
        )
        if ebay_stage["status"] != StageStatus.PASSED.value:
            supply_stage = make_not_checked_supply_stage(
                "Not checked because the eBay demand gate did not pass."
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
    prepared_candidate_source = _prepare_candidate_source(candidate_source)
    generated_timestamp = _coerce_generated_at(generated_at)
    report = {
        "schema_version": SCHEMA_VERSION,
        "candidate": candidate,
        "candidate_source": prepared_candidate_source,
        "policy": {
            "max_amazon_relevant_results": MAX_AMAZON_RELEVANT_RESULTS,
            "min_ebay_aggregate_observed_sold": MIN_EBAY_AGGREGATE_OBSERVED_SOLD,
            "max_acceptable_moq": max_moq,
            "candidate_report_max_age_hours": _CANDIDATE_REPORT_MAX_AGE_HOURS,
            "stage_evidence_max_age_hours": _STAGE_EVIDENCE_MAX_AGE_HOURS,
            "order_preview_max_age_minutes": _ORDER_PREVIEW_MAX_AGE_MINUTES,
            "future_clock_skew_minutes": _FUTURE_CLOCK_SKEW_MINUTES,
        },
        "stages": stages,
        "decision": decision,
        "reasons": _decision_reasons(decision, stages),
        "generated_at": generated_timestamp,
    }
    report["automation_qualified"] = _is_automation_qualified(
        prepared_candidate_source,
        stages,
        decision,
        generated_timestamp,
    )
    return report
