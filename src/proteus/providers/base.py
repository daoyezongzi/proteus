"""Provider-neutral contracts for replaceable Proteus data sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from proteus.normalization import normalize_part_number


# Marketplace search engines generally cannot browse a category with no query,
# so discovery is keyword-shaped. This lives here, provider-neutral, because it
# constrains the request contract rather than one vendor's URL.
DEFAULT_DISCOVERY_KEYWORD = "OEM"


class Capability(str, Enum):
    AMAZON_CANDIDATE_SOURCE = "AMAZON_CANDIDATE_SOURCE"
    EBAY_CANDIDATE_SOURCE = "EBAY_CANDIDATE_SOURCE"
    EBAY_ANNUAL_SALES = "EBAY_ANNUAL_SALES"
    AMAZON_COMPETITION = "AMAZON_COMPETITION"
    US_VEHICLE_PARC = "US_VEHICLE_PARC"
    EBAY_DEMAND = "EBAY_DEMAND"
    ALIBABA_1688_SUPPLY = "ALIBABA_1688_SUPPLY"
    SEARCH_DISCOVERY = "SEARCH_DISCOVERY"


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PartLookupRequest:
    """Smallest request shared by competition and demand providers."""

    raw_part_number: str

    def __post_init__(self) -> None:
        normalize_part_number(self.raw_part_number)


@dataclass(frozen=True, slots=True)
class SupplyLookupRequest:
    """Supply request with the policy inputs needed for an order preview."""

    raw_part_number: str
    max_acceptable_moq: int

    def __post_init__(self) -> None:
        normalize_part_number(self.raw_part_number)
        if (
            isinstance(self.max_acceptable_moq, bool)
            or not isinstance(self.max_acceptable_moq, int)
            or self.max_acceptable_moq < 1
        ):
            raise ValueError("max_acceptable_moq must be a positive integer")


@dataclass(frozen=True, slots=True)
class CandidateDiscoveryRequest:
    """Provider-neutral inputs for one bounded candidate-discovery page."""

    category_id: str
    max_candidates: int
    page: int = 1
    keyword: str = DEFAULT_DISCOVERY_KEYWORD

    def __post_init__(self) -> None:
        if not isinstance(self.category_id, str) or not self.category_id.isdigit():
            raise ValueError("category_id must contain digits only")
        if not isinstance(self.keyword, str) or not self.keyword.strip():
            raise ValueError("keyword must be a non-empty string")
        for name, value in (
            ("max_candidates", self.max_candidates),
            ("page", self.page),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class AnnualSalesLookupRequest:
    """Strict trailing-year marketplace-sales lookup for one part number."""

    raw_part_number: str
    window_days: int = 365
    marketplace_id: str = "EBAY_US"

    def __post_init__(self) -> None:
        normalize_part_number(self.raw_part_number)
        if self.window_days != 365:
            raise ValueError("window_days must be 365")
        if self.marketplace_id != "EBAY_US":
            raise ValueError("marketplace_id must be EBAY_US")


@dataclass(frozen=True, slots=True)
class VehicleParcLookupRequest:
    """Compatible vehicles-in-operation lookup for one part number."""

    raw_part_number: str
    country_code: str = "US"

    def __post_init__(self) -> None:
        normalize_part_number(self.raw_part_number)
        if self.country_code != "US":
            raise ValueError("country_code must be US")


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    status: CheckStatus
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("readiness check name must be non-empty")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("readiness check message must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    provider_id: str
    capability: Capability
    checks: tuple[ReadinessCheck, ...]
    checked_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.provider_id, str) or not self.provider_id.strip():
            raise ValueError("provider_id must be non-empty")
        if not self.checks:
            raise ValueError("provider readiness must contain at least one check")
        names = [check.name for check in self.checks]
        if len(names) != len(set(names)):
            raise ValueError("provider readiness check names must be unique")

    @property
    def status(self) -> str:
        statuses = {check.status for check in self.checks}
        if CheckStatus.FAIL in statuses:
            return "BLOCKED"
        if CheckStatus.UNKNOWN in statuses:
            return "NOT_READY"
        return "READY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "capability": self.capability.value,
            "status": self.status,
            "checked_at": self.checked_at,
            "checks": [check.to_dict() for check in self.checks],
        }


@runtime_checkable
class Provider(Protocol):
    """Common lifecycle contract; acquisition payloads stay capability-specific."""

    provider_id: str
    capability: Capability

    def preflight(self) -> ProviderReadiness: ...

    def acquire(self, request: Any) -> Mapping[str, Any]: ...

    def estimate_cost(self, request: Any) -> float | None: ...
