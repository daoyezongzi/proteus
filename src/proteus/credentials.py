"""One-time local credential setup backed by the operating-system keyring."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, MutableMapping, Sequence
from getpass import getpass
import json
import os
from pathlib import Path
from typing import Protocol

import keyring
from keyring.errors import KeyringError

from proteus.io import InputDataError, read_json


SERVICE_NAME = "proteus-opportunity-finder"
SERPAPI_API_KEY = "SERPAPI_API_KEY"
HIOBUY_API_KEY = "HIOBUY_API_KEY"
HIOBUY_RECEIVER = "HIOBUY_RECEIVER_JSON"
REQUIRED_RECEIVER_FIELDS = (
    "name",
    "mobile",
    "province",
    "city",
    "district",
    "address",
)


class CredentialStoreError(RuntimeError):
    """Raised when the OS credential store cannot be accessed safely."""


class SecretBackend(Protocol):
    def get(self, name: str) -> str | None: ...

    def set(self, name: str, value: str) -> None: ...


class KeyringSecretBackend:
    """Small wrapper that keeps keyring-specific failures out of business code."""

    def get(self, name: str) -> str | None:
        try:
            value = keyring.get_password(SERVICE_NAME, name)
        except KeyringError as exc:
            raise CredentialStoreError(
                "the operating-system credential store is unavailable"
            ) from exc
        return value.strip() if isinstance(value, str) and value.strip() else None

    def set(self, name: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("credential values must be non-empty")
        try:
            keyring.set_password(SERVICE_NAME, name, value.strip())
        except KeyringError as exc:
            raise CredentialStoreError(
                "the operating-system credential store rejected the update"
            ) from exc


def _backend(value: SecretBackend | None) -> SecretBackend:
    return value if value is not None else KeyringSecretBackend()


def _environment_value(
    name: str, environment: Mapping[str, str] | None
) -> str | None:
    source = os.environ if environment is None else environment
    value = source.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def resolve_secret(
    name: str,
    *,
    environment: Mapping[str, str] | None = None,
    backend: SecretBackend | None = None,
) -> str | None:
    """Resolve a secret with explicit environment override over OS keyring."""

    if name not in {SERPAPI_API_KEY, HIOBUY_API_KEY}:
        raise ValueError(f"unsupported credential alias {name!r}")
    from_environment = _environment_value(name, environment)
    if from_environment is not None:
        return from_environment
    return _backend(backend).get(name)


def _validated_receiver(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(value.get(field), str) or not str(value[field]).strip()
        for field in REQUIRED_RECEIVER_FIELDS
    ):
        raise InputDataError(
            "HioBuy receiver must contain non-empty "
            + ", ".join(REQUIRED_RECEIVER_FIELDS)
        )
    return {field: str(value[field]).strip() for field in REQUIRED_RECEIVER_FIELDS}


def resolve_receiver(
    path: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    backend: SecretBackend | None = None,
) -> dict[str, str] | None:
    """Load receiver from an explicit file, environment JSON, then keyring."""

    if path is not None:
        return _validated_receiver(read_json(path))
    raw = _environment_value(HIOBUY_RECEIVER, environment)
    if raw is None:
        raw = _backend(backend).get(HIOBUY_RECEIVER)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputDataError("stored HioBuy receiver is not valid JSON") from exc
    return _validated_receiver(value)


def _source_for(
    name: str,
    *,
    environment: Mapping[str, str] | None,
    backend: SecretBackend,
) -> str | None:
    if _environment_value(name, environment) is not None:
        return "environment"
    return "os_keyring" if backend.get(name) is not None else None


def configuration_status(
    *,
    environment: Mapping[str, str] | None = None,
    backend: SecretBackend | None = None,
) -> dict:
    """Return frontend-safe configuration presence, never credential values."""

    active_backend = _backend(backend)
    credentials = {}
    for name in (SERPAPI_API_KEY, HIOBUY_API_KEY):
        source = _source_for(
            name,
            environment=environment,
            backend=active_backend,
        )
        credentials[name] = {"configured": source is not None, "source": source}
    receiver_source = _source_for(
        HIOBUY_RECEIVER,
        environment=environment,
        backend=active_backend,
    )
    receiver_configured = False
    if receiver_source is not None:
        try:
            receiver_configured = (
                resolve_receiver(environment=environment, backend=active_backend)
                is not None
            )
        except InputDataError:
            receiver_configured = False
    ready = all(item["configured"] for item in credentials.values()) and receiver_configured
    return {
        "profile": "two-account-managed",
        "ready": ready,
        "account_count": 2,
        "credentials": credentials,
        "receiver": {
            "configured": receiver_configured,
            "source": receiver_source,
        },
    }


def _prompt_secret(name: str, backend: SecretBackend) -> None:
    existing = backend.get(name) is not None
    suffix = " (leave blank to keep existing)" if existing else ""
    value = getpass(f"{name}{suffix}: ")
    if value.strip():
        backend.set(name, value)
    elif not existing:
        print(f"{name} remains unconfigured.")


def _prompt_receiver(backend: SecretBackend) -> None:
    existing = backend.get(HIOBUY_RECEIVER) is not None
    answer = input(
        "Configure the HioBuy domestic receiver now? "
        + ("[y/N, existing value will be kept]: " if existing else "[y/N]: ")
    )
    if answer.strip().casefold() not in {"y", "yes"}:
        return
    receiver: MutableMapping[str, str] = {}
    for field in REQUIRED_RECEIVER_FIELDS:
        value = input(f"receiver.{field}: ").strip()
        if not value:
            raise InputDataError(f"receiver.{field} must not be empty")
        receiver[field] = value
    backend.set(HIOBUY_RECEIVER, json.dumps(receiver, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proteus setup",
        description="Store the two managed-provider credentials in the OS keyring.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="show redacted configuration presence without prompting",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backend = KeyringSecretBackend()
    try:
        if not args.status:
            _prompt_secret(SERPAPI_API_KEY, backend)
            _prompt_secret(HIOBUY_API_KEY, backend)
            _prompt_receiver(backend)
        status = configuration_status(backend=backend)
    except (CredentialStoreError, InputDataError, ValueError) as exc:
        print(f"proteus setup: error: {exc}", file=os.sys.stderr)
        return 2

    configured = sum(
        item["configured"] for item in status["credentials"].values()
    )
    print(
        "Proteus managed profile: "
        f"credentials={configured}/2, "
        f"receiver={'configured' if status['receiver']['configured'] else 'missing'}, "
        f"ready={str(status['ready']).lower()}."
    )
    return 0 if status["ready"] else 3


__all__ = [
    "CredentialStoreError",
    "HIOBUY_API_KEY",
    "HIOBUY_RECEIVER",
    "KeyringSecretBackend",
    "SERPAPI_API_KEY",
    "SERVICE_NAME",
    "SecretBackend",
    "configuration_status",
    "resolve_receiver",
    "resolve_secret",
]
