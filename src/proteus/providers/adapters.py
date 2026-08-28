"""Thin provider objects that keep vendor calls outside the funnel logic."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from proteus.providers.base import (
    CandidateDiscoveryRequest,
    Capability,
    CheckStatus,
    PartLookupRequest,
    ProviderReadiness,
    ReadinessCheck,
    SupplyLookupRequest,
)
from proteus.providers.hiobuy import collect_1688_supply
from proteus.providers.local_1688_cli import (
    DEFAULT_EXECUTABLE as DEFAULT_1688_CLI_EXECUTABLE,
    collect_1688_supplier,
    is_1688_cli_available,
)
from proteus.providers.nexscope import (
    collect_1688_search,
    collect_amazon_search,
    collect_ebay_search,
)
from proteus.providers.registry import ProviderRegistry
from proteus.providers.serpapi_ebay import collect_ebay_sold
from proteus.providers.serpapi_amazon import collect_amazon_competition
from proteus.providers.serpapi_ebay_discovery import collect_ebay_sold_candidates


NEXSCOPE_AMAZON_ID = "nexscope-amazon"
NEXSCOPE_EBAY_ID = "nexscope-ebay"
NEXSCOPE_1688_LISTING_ID = "nexscope-1688-listing"
SERPAPI_AMAZON_ID = "serpapi-amazon"
SERPAPI_EBAY_ID = "serpapi-ebay"
SERPAPI_EBAY_DISCOVERY_ID = "serpapi-ebay-discovery"
HIOBUY_1688_ID = "hiobuy-1688"
LOCAL_1688_CLI_ID = "local-1688-cli"

PartCollector = Callable[..., Mapping[str, Any]]
SupplyCollector = Callable[..., Mapping[str, Any]]
DiscoveryCollector = Callable[..., Mapping[str, Any]]


@dataclass(frozen=True, slots=True)
class FunnelProviders:
    """The only provider surface consumed by the business funnel."""

    amazon_competition: Any
    ebay_demand: Any
    alibaba_1688_supply: Any


def _credential_check(api_key: str | None, variable_name: str) -> ReadinessCheck:
    available = isinstance(api_key, str) and bool(api_key.strip())
    return ReadinessCheck(
        "CREDENTIALS_AVAILABLE",
        CheckStatus.PASS if available else CheckStatus.FAIL,
        (
            f"Credential alias {variable_name} is configured."
            if available
            else f"Credential alias {variable_name} is not configured."
        ),
    )


def _commercial_checks(
    *,
    api_key: str | None,
    variable_name: str,
    market_fixed: bool,
    freshness_known: bool,
    purpose_compatible: bool | None,
    required_fields_known: bool,
    cost_per_request_usd: float | None,
    extra: tuple[ReadinessCheck, ...] = (),
) -> tuple[ReadinessCheck, ...]:
    purpose_status = (
        CheckStatus.PASS
        if purpose_compatible is True
        else CheckStatus.FAIL
        if purpose_compatible is False
        else CheckStatus.UNKNOWN
    )
    return (
        ReadinessCheck(
            "ACCESS_AUTHORIZED",
            CheckStatus.UNKNOWN,
            "Authorization must be confirmed by a successful live canary.",
        ),
        ReadinessCheck(
            "PURPOSE_COMPATIBLE",
            purpose_status,
            (
                "Commercial purpose compatibility is confirmed."
                if purpose_compatible is True
                else "Commercial purpose compatibility is not approved."
                if purpose_compatible is False
                else "Commercial purpose compatibility is not yet confirmed."
            ),
        ),
        _credential_check(api_key, variable_name),
        ReadinessCheck(
            "CREDENTIALS_VALID",
            CheckStatus.UNKNOWN,
            "Credential validity must be confirmed by a live canary.",
        ),
        ReadinessCheck(
            "REQUIRED_FIELDS_AVAILABLE",
            CheckStatus.PASS if required_fields_known else CheckStatus.UNKNOWN,
            (
                "The adapter contract exposes the required fields."
                if required_fields_known
                else "Required fields still need a live benchmark."
            ),
        ),
        ReadinessCheck(
            "MARKET_CONTEXT_FIXED",
            CheckStatus.PASS if market_fixed else CheckStatus.UNKNOWN,
            "The adapter fixes the requested marketplace and locale."
            if market_fixed
            else "Marketplace binding still needs verification.",
        ),
        ReadinessCheck(
            "FRESHNESS_KNOWN",
            CheckStatus.PASS if freshness_known else CheckStatus.UNKNOWN,
            "The request contract disables provider cache for the canary."
            if freshness_known
            else "Provider freshness semantics are not yet confirmed.",
        ),
        ReadinessCheck(
            "FAILURE_CLASSIFICATION_TESTED",
            CheckStatus.PASS,
            "Auth, HTTP, timeout and parser failures are covered by contract tests.",
        ),
        ReadinessCheck(
            "CACHE_RETENTION_ALLOWED",
            CheckStatus.UNKNOWN,
            "Provider cache and evidence-retention terms are not yet recorded.",
        ),
        ReadinessCheck(
            "COST_KNOWN",
            CheckStatus.PASS if cost_per_request_usd is not None else CheckStatus.UNKNOWN,
            (
                f"Configured marginal cost is US${cost_per_request_usd:.4f} per request."
                if cost_per_request_usd is not None
                else "Marginal cost is not configured."
            ),
        ),
        *extra,
    )


@dataclass(slots=True)
class NexscopeAmazonProvider:
    api_key: str | None
    collector: PartCollector = collect_amazon_search
    purpose_compatible: bool | None = None
    cost_per_request_usd: float | None = None
    provider_id: str = NEXSCOPE_AMAZON_ID
    capability: Capability = Capability.AMAZON_COMPETITION

    def preflight(self) -> ProviderReadiness:
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            _commercial_checks(
                api_key=self.api_key,
                variable_name="NEXSCOPE_API_KEY",
                market_fixed=True,
                freshness_known=False,
                purpose_compatible=self.purpose_compatible,
                required_fields_known=False,
                cost_per_request_usd=self.cost_per_request_usd,
            ),
        )

    def acquire(self, request: PartLookupRequest) -> Mapping[str, Any]:
        return self.collector(request.raw_part_number, api_key=self.api_key or "")

    def estimate_cost(self, request: PartLookupRequest) -> float | None:
        return self.cost_per_request_usd


@dataclass(slots=True)
class NexscopeEbayProvider:
    api_key: str | None
    collector: PartCollector = collect_ebay_search
    purpose_compatible: bool | None = None
    cost_per_request_usd: float | None = None
    provider_id: str = NEXSCOPE_EBAY_ID
    capability: Capability = Capability.EBAY_DEMAND

    def preflight(self) -> ProviderReadiness:
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            _commercial_checks(
                api_key=self.api_key,
                variable_name="NEXSCOPE_API_KEY",
                market_fixed=True,
                freshness_known=False,
                purpose_compatible=self.purpose_compatible,
                required_fields_known=False,
                cost_per_request_usd=self.cost_per_request_usd,
            ),
        )

    def acquire(self, request: PartLookupRequest) -> Mapping[str, Any]:
        return self.collector(request.raw_part_number, api_key=self.api_key or "")

    def estimate_cost(self, request: PartLookupRequest) -> float | None:
        return self.cost_per_request_usd


@dataclass(slots=True)
class SerpApiEbayProvider:
    api_key: str | None
    collector: PartCollector = collect_ebay_sold
    purpose_compatible: bool | None = None
    cost_per_request_usd: float | None = None
    provider_id: str = SERPAPI_EBAY_ID
    capability: Capability = Capability.EBAY_DEMAND

    def preflight(self) -> ProviderReadiness:
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            _commercial_checks(
                api_key=self.api_key,
                variable_name="SERPAPI_API_KEY",
                market_fixed=True,
                freshness_known=True,
                purpose_compatible=self.purpose_compatible,
                required_fields_known=True,
                cost_per_request_usd=self.cost_per_request_usd,
            ),
        )

    def acquire(self, request: PartLookupRequest) -> Mapping[str, Any]:
        return self.collector(request.raw_part_number, api_key=self.api_key or "")

    def estimate_cost(self, request: PartLookupRequest) -> float | None:
        return self.cost_per_request_usd


@dataclass(slots=True)
class SerpApiAmazonProvider:
    api_key: str | None
    collector: PartCollector = collect_amazon_competition
    purpose_compatible: bool | None = None
    cost_per_request_usd: float | None = None
    provider_id: str = SERPAPI_AMAZON_ID
    capability: Capability = Capability.AMAZON_COMPETITION

    def preflight(self) -> ProviderReadiness:
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            _commercial_checks(
                api_key=self.api_key,
                variable_name="SERPAPI_API_KEY",
                market_fixed=True,
                freshness_known=True,
                purpose_compatible=self.purpose_compatible,
                required_fields_known=True,
                cost_per_request_usd=self.cost_per_request_usd,
            ),
        )

    def acquire(self, request: PartLookupRequest) -> Mapping[str, Any]:
        return self.collector(request.raw_part_number, api_key=self.api_key or "")

    def estimate_cost(self, request: PartLookupRequest) -> float | None:
        return self.cost_per_request_usd


@dataclass(slots=True)
class SerpApiEbayDiscoveryProvider:
    api_key: str | None
    collector: DiscoveryCollector = collect_ebay_sold_candidates
    purpose_compatible: bool | None = None
    cost_per_request_usd: float | None = None
    provider_id: str = SERPAPI_EBAY_DISCOVERY_ID
    capability: Capability = Capability.EBAY_CANDIDATE_SOURCE

    def preflight(self) -> ProviderReadiness:
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            _commercial_checks(
                api_key=self.api_key,
                variable_name="SERPAPI_API_KEY",
                market_fixed=True,
                freshness_known=True,
                purpose_compatible=self.purpose_compatible,
                required_fields_known=True,
                cost_per_request_usd=self.cost_per_request_usd,
            ),
        )

    def acquire(self, request: CandidateDiscoveryRequest) -> Mapping[str, Any]:
        return self.collector(
            api_key=self.api_key or "",
            category_id=request.category_id,
            keyword=request.keyword,
            max_candidates=request.max_candidates,
            page=request.page,
        )

    def estimate_cost(self, request: CandidateDiscoveryRequest) -> float | None:
        return self.cost_per_request_usd


@dataclass(slots=True)
class Nexscope1688ListingProvider:
    api_key: str | None
    collector: PartCollector = collect_1688_search
    purpose_compatible: bool | None = None
    cost_per_request_usd: float | None = None
    provider_id: str = NEXSCOPE_1688_LISTING_ID
    capability: Capability = Capability.ALIBABA_1688_SUPPLY

    def preflight(self) -> ProviderReadiness:
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            _commercial_checks(
                api_key=self.api_key,
                variable_name="NEXSCOPE_API_KEY",
                market_fixed=True,
                freshness_known=False,
                purpose_compatible=self.purpose_compatible,
                required_fields_known=False,
                cost_per_request_usd=self.cost_per_request_usd,
                extra=(
                    ReadinessCheck(
                        "ORDER_PREVIEW_AVAILABLE",
                        CheckStatus.FAIL,
                        "This provider exposes listing evidence only, not a bound order preview.",
                    ),
                ),
            ),
        )

    def acquire(self, request: SupplyLookupRequest) -> Mapping[str, Any]:
        return self.collector(request.raw_part_number, api_key=self.api_key or "")

    def estimate_cost(self, request: SupplyLookupRequest) -> float | None:
        return self.cost_per_request_usd


@dataclass(slots=True)
class HioBuy1688Provider:
    api_key: str | None
    receiver: Mapping[str, str] | None
    collector: SupplyCollector = collect_1688_supply
    purpose_compatible: bool | None = None
    cost_per_request_usd: float | None = None
    provider_id: str = HIOBUY_1688_ID
    capability: Capability = Capability.ALIBABA_1688_SUPPLY

    def preflight(self) -> ProviderReadiness:
        receiver_available = isinstance(self.receiver, Mapping) and bool(self.receiver)
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            _commercial_checks(
                api_key=self.api_key,
                variable_name="HIOBUY_API_KEY",
                market_fixed=True,
                freshness_known=False,
                purpose_compatible=self.purpose_compatible,
                required_fields_known=True,
                cost_per_request_usd=self.cost_per_request_usd,
                extra=(
                    ReadinessCheck(
                        "RECEIVER_AVAILABLE",
                        CheckStatus.PASS if receiver_available else CheckStatus.FAIL,
                        "A runtime-only domestic receiver is configured."
                        if receiver_available
                        else "A runtime-only domestic receiver is required for order preview.",
                    ),
                    ReadinessCheck(
                        "ORDER_PREVIEW_AVAILABLE",
                        CheckStatus.PASS,
                        "The adapter is restricted to search, detail and order preview.",
                    ),
                ),
            ),
        )

    def acquire(self, request: SupplyLookupRequest) -> Mapping[str, Any]:
        if self.receiver is None:
            raise ValueError("HioBuy receiver is required")
        return self.collector(
            request.raw_part_number,
            api_key=self.api_key or "",
            receiver=self.receiver,
            max_acceptable_moq=request.max_acceptable_moq,
        )

    def estimate_cost(self, request: SupplyLookupRequest) -> float | None:
        return self.cost_per_request_usd


@dataclass(slots=True)
class Local1688CliProvider:
    """Read-only local 1688 supplier lookup with a persistent CLI profile."""

    executable: str = DEFAULT_1688_CLI_EXECUTABLE
    collector: SupplyCollector = collect_1688_supplier
    provider_id: str = LOCAL_1688_CLI_ID
    capability: Capability = Capability.ALIBABA_1688_SUPPLY

    def preflight(self) -> ProviderReadiness:
        executable_available = is_1688_cli_available(self.executable)
        return ProviderReadiness(
            self.provider_id,
            self.capability,
            (
                ReadinessCheck(
                    "EXECUTABLE_AVAILABLE",
                    CheckStatus.PASS if executable_available else CheckStatus.FAIL,
                    "The local 1688 executable is available."
                    if executable_available
                    else "Install 1688 CLI before using local supplier filtering.",
                ),
                ReadinessCheck(
                    "READ_ONLY_SCOPE",
                    CheckStatus.PASS,
                    "The adapter only invokes shallow search and optional offer detail reads.",
                ),
                ReadinessCheck(
                    "SESSION_AUTHENTICATED",
                    CheckStatus.UNKNOWN,
                    "The persistent 1688 profile still needs a live login/doctor check.",
                ),
            ),
        )

    def acquire(self, request: SupplyLookupRequest) -> Mapping[str, Any]:
        return self.collector(
            request.raw_part_number,
            executable=self.executable,
            max_offers=5,
        )

    def estimate_cost(self, request: SupplyLookupRequest) -> float | None:
        return 0.0


def build_provider_registry(
    *,
    nexscope_key: str | None,
    serpapi_key: str | None,
    hiobuy_key: str | None,
    receiver: Mapping[str, str] | None,
    collectors: Mapping[str, Callable[..., Mapping[str, Any]]] | None = None,
    cli_1688_executable: str = DEFAULT_1688_CLI_EXECUTABLE,
) -> ProviderRegistry:
    """Build one explicit registry; injected collectors keep tests and swaps local."""

    functions = collectors or {}
    registry = ProviderRegistry()
    registry.register(
        NexscopeAmazonProvider(
            nexscope_key,
            collector=functions.get(NEXSCOPE_AMAZON_ID, collect_amazon_search),
        )
    )
    registry.register(
        NexscopeEbayProvider(
            nexscope_key,
            collector=functions.get(NEXSCOPE_EBAY_ID, collect_ebay_search),
        )
    )
    registry.register(
        SerpApiAmazonProvider(
            serpapi_key,
            collector=functions.get(SERPAPI_AMAZON_ID, collect_amazon_competition),
        )
    )
    registry.register(
        SerpApiEbayProvider(
            serpapi_key,
            collector=functions.get(SERPAPI_EBAY_ID, collect_ebay_sold),
        )
    )
    registry.register(
        SerpApiEbayDiscoveryProvider(
            serpapi_key,
            collector=functions.get(
                SERPAPI_EBAY_DISCOVERY_ID,
                collect_ebay_sold_candidates,
            ),
        )
    )
    registry.register(
        Nexscope1688ListingProvider(
            nexscope_key,
            collector=functions.get(NEXSCOPE_1688_LISTING_ID, collect_1688_search),
        )
    )
    registry.register(
        HioBuy1688Provider(
            hiobuy_key,
            receiver,
            collector=functions.get(HIOBUY_1688_ID, collect_1688_supply),
        )
    )
    registry.register(
        Local1688CliProvider(
            executable=cli_1688_executable,
            collector=functions.get(LOCAL_1688_CLI_ID, collect_1688_supplier),
        )
    )
    return registry
