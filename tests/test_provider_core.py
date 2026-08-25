from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from proteus.providers.base import (
    Capability,
    CheckStatus,
    PartLookupRequest,
    ProviderReadiness,
    ReadinessCheck,
)
from proteus.providers.registry import ProviderRegistry


@dataclass
class FakeProvider:
    provider_id: str
    capability: Capability

    def preflight(self) -> ProviderReadiness:
        return ProviderReadiness(
            provider_id=self.provider_id,
            capability=self.capability,
            checks=(
                ReadinessCheck("CREDENTIALS_AVAILABLE", CheckStatus.PASS, "fixture"),
                ReadinessCheck("PURPOSE_COMPATIBLE", CheckStatus.PASS, "fixture"),
            ),
        )

    def acquire(self, request: PartLookupRequest) -> Mapping[str, Any]:
        return {"part": request.raw_part_number, "provider": self.provider_id}

    def estimate_cost(self, request: PartLookupRequest) -> float | None:
        return 0.01


def test_readiness_is_blocked_by_fail_and_not_ready_by_unknown() -> None:
    blocked = ProviderReadiness(
        provider_id="blocked",
        capability=Capability.EBAY_DEMAND,
        checks=(ReadinessCheck("CREDENTIALS_AVAILABLE", CheckStatus.FAIL, "missing"),),
    )
    unknown = ProviderReadiness(
        provider_id="unknown",
        capability=Capability.EBAY_DEMAND,
        checks=(ReadinessCheck("CREDENTIALS_VALID", CheckStatus.UNKNOWN, "not tested"),),
    )
    ready = ProviderReadiness(
        provider_id="ready",
        capability=Capability.EBAY_DEMAND,
        checks=(ReadinessCheck("CREDENTIALS_VALID", CheckStatus.PASS, "tested"),),
    )

    assert blocked.status == "BLOCKED"
    assert unknown.status == "NOT_READY"
    assert ready.status == "READY"
    assert blocked.to_dict()["checks"][0]["message"] == "missing"


def test_registry_selects_only_explicit_provider_for_capability() -> None:
    registry = ProviderRegistry()
    first = FakeProvider("first", Capability.EBAY_DEMAND)
    second = FakeProvider("second", Capability.EBAY_DEMAND)
    registry.register(first)
    registry.register(second)

    selected = registry.select(Capability.EBAY_DEMAND, ("second", "first"))

    assert selected is second
    assert registry.available(Capability.EBAY_DEMAND) == ("first", "second")


def test_registry_never_falls_back_to_unallowlisted_provider() -> None:
    registry = ProviderRegistry()
    registry.register(FakeProvider("first", Capability.AMAZON_COMPETITION))

    with pytest.raises(LookupError, match="no explicitly allowed provider"):
        registry.select(Capability.AMAZON_COMPETITION, ("other",))


def test_registry_rejects_duplicate_ids_and_capability_mismatch() -> None:
    registry = ProviderRegistry()
    registry.register(FakeProvider("same", Capability.EBAY_DEMAND))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeProvider("same", Capability.EBAY_DEMAND))
    with pytest.raises(LookupError, match="does not implement"):
        registry.select(Capability.ALIBABA_1688_SUPPLY, ("same",))
