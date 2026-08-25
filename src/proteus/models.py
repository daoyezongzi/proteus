"""Shared V0.2 policy values and schema-shaped stage constructors."""

from __future__ import annotations

from enum import Enum


SCHEMA_VERSION = "0.2"
LEGACY_SCHEMA_VERSION = "0.1"
SUPPORTED_INPUT_SCHEMA_VERSIONS = frozenset(
    {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION}
)
MAX_AMAZON_RELEVANT_RESULTS = 5
MIN_EBAY_AGGREGATE_OBSERVED_SOLD = 1


class StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class AcquisitionStatus(StringEnum):
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    ZERO_RESULTS = "ZERO_RESULTS"
    HTTP_ERROR = "HTTP_ERROR"
    TIMEOUT = "TIMEOUT"
    CHALLENGE = "CHALLENGE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    BLOCKED_BY_CREDENTIALS = "BLOCKED_BY_CREDENTIALS"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    MARKET_CONTEXT_MISMATCH = "MARKET_CONTEXT_MISMATCH"
    PARSER_FAILED = "PARSER_FAILED"


class StageStatus(StringEnum):
    PASSED = "PASSED"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    NOT_CHECKED = "NOT_CHECKED"


class OpportunityDecision(StringEnum):
    OPPORTUNITY_CANDIDATE = "OPPORTUNITY_CANDIDATE"
    REJECTED = "REJECTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class SourceMethod(StringEnum):
    OFFICIAL_API = "OFFICIAL_API"
    MANAGED_API = "MANAGED_API"
    HTTP = "HTTP"
    SEARCH = "SEARCH"
    BROWSER = "BROWSER"
    MANUAL = "MANUAL"


class MatchType(StringEnum):
    EXACT = "EXACT"
    NORMALIZED_EXACT = "NORMALIZED_EXACT"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    REPLACEMENT = "REPLACEMENT"
    LEFT_RIGHT_PAIR = "LEFT_RIGHT_PAIR"
    SIDE_MISMATCH = "SIDE_MISMATCH"
    AMBIGUOUS = "AMBIGUOUS"
    IRRELEVANT = "IRRELEVANT"
    UNKNOWN = "UNKNOWN"


class RelevanceMethod(StringEnum):
    DETERMINISTIC_EXACT = "DETERMINISTIC_EXACT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


SUCCESSFUL_ACQUISITION_STATUSES = frozenset(
    {AcquisitionStatus.SUCCESS.value, AcquisitionStatus.PARTIAL_SUCCESS.value}
)
ACQUISITION_STATUS_VALUES = frozenset(status.value for status in AcquisitionStatus)
SOURCE_METHOD_VALUES = frozenset(method.value for method in SourceMethod)
MATCH_TYPE_VALUES = frozenset(match_type.value for match_type in MatchType)
RELEVANCE_METHOD_VALUES = frozenset(method.value for method in RelevanceMethod)
STAGE_STATUS_VALUES = frozenset(status.value for status in StageStatus)

EBAY_US_CONTEXT = {
    "marketplace_id": "EBAY_US",
    "site": "www.ebay.com",
    "locale": "en-US",
    "ship_to_country": "US",
    "ship_to_postal_code": "10001",
    "currency": "USD",
}

AMAZON_US_CONTEXT = {
    "marketplace_id": "AMAZON_US",
    "site": "www.amazon.com",
    "locale": "en-US",
    "ship_to_country": "US",
    "currency": "USD",
}


def make_not_checked_amazon_stage(reason: str) -> dict:
    return {
        "status": StageStatus.NOT_CHECKED.value,
        "acquisition_status": None,
        "source_method": None,
        "query": None,
        "market_context": None,
        "relevance_method": None,
        "relevant_result_count": None,
        "evidence": [],
        "reason": reason,
    }


def make_not_checked_supply_stage(reason: str) -> dict:
    return {
        "status": StageStatus.NOT_CHECKED.value,
        "acquisition_status": None,
        "source_method": None,
        "matched_part_numbers": [],
        "match_type": None,
        "supplier": None,
        "offer_url": None,
        "purchasable": None,
        "price_cny": None,
        "moq": None,
        "order_preview": None,
        "evidence": [],
        "reason": reason,
    }


def make_not_checked_ebay_stage(reason: str) -> dict:
    return {
        "status": StageStatus.NOT_CHECKED.value,
        "acquisition": None,
        "reason": reason,
    }
