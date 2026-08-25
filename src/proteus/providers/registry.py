"""Explicit provider registry with no implicit or unapproved fallback."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from proteus.providers.base import Capability, Provider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[Capability, dict[str, Provider]] = defaultdict(dict)

    def register(self, provider: Provider) -> None:
        if not isinstance(provider.provider_id, str) or not provider.provider_id.strip():
            raise ValueError("provider_id must be non-empty")
        capability_providers = self._providers[provider.capability]
        if provider.provider_id in capability_providers:
            raise ValueError(
                f"provider {provider.provider_id!r} is already registered for "
                f"{provider.capability.value}"
            )
        capability_providers[provider.provider_id] = provider

    def available(self, capability: Capability) -> tuple[str, ...]:
        return tuple(self._providers.get(capability, {}))

    def select(
        self,
        capability: Capability,
        allowed_provider_ids: Iterable[str],
        *,
        require_ready: bool = True,
    ) -> Provider:
        allowed = tuple(allowed_provider_ids)
        registered = self._providers.get(capability, {})
        known_other_capabilities = {
            provider_id
            for other_capability, providers in self._providers.items()
            if other_capability != capability
            for provider_id in providers
        }
        for provider_id in allowed:
            provider = registered.get(provider_id)
            if provider is None:
                continue
            if not require_ready or provider.preflight().status == "READY":
                return provider
        mismatched = next(
            (provider_id for provider_id in allowed if provider_id in known_other_capabilities),
            None,
        )
        if mismatched is not None:
            raise LookupError(
                f"provider {mismatched!r} does not implement {capability.value}"
            )
        raise LookupError(
            f"no explicitly allowed provider is ready for {capability.value}; "
            f"allowed={allowed!r}"
        )
