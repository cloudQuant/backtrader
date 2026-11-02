"""Provider-neutral helpers for the iteration-52 external paper example.

This module contains no provider parser, native record access, endpoint
selection, account/session identity construction, or write authorization. The
SDK owns provider configuration and route composition. A trusted host may
inject its exact runtime binding and authorization capabilities into the
runner; this example never manufactures them.
"""

from __future__ import annotations

from typing import Any


class SimNowPaperError(RuntimeError):
    """Finite, value-free error at the neutral paper-example boundary."""

    def __init__(self, code: str) -> None:
        safe = code if type(code) is str and code.isascii() and code.replace("_", "").isalnum() else "SIMNOW_PAPER_FAILED"
        self.code = safe
        super().__init__(safe)


def load_configuration(
    *,
    exchange_name: str,
    config_path: Any,
    credential_env_file: Any = None,
    credential_values: dict[str, str] | None = None,
    credential_names: dict[str, str] | None = None,
) -> Any:
    """Ask the SDK's exact-route provider configuration facade to normalize input."""

    try:
        from bt_api_py.provider_configuration import load_provider_configuration

        return load_provider_configuration(
            exchange_name,
            config_path,
            credential_values=credential_values or {},
            credential_names=credential_names or {},
            credential_env_file=credential_env_file,
        )
    except Exception as exc:  # noqa: BLE001 - expose only finite codes/types
        code = getattr(exc, "code", None)
        if type(code) is str and code.isascii() and code.replace("_", "").isalnum():
            raise SimNowPaperError(code) from None
        raise SimNowPaperError("PROVIDER_CONFIGURATION_UNAVAILABLE") from None


def compose_runtime(
    configuration: Any,
    *,
    runtime_binding: object,
    access_mode: str,
    authorization_source: object | None = None,
    operator_grant: object | None = None,
) -> Any:
    """Compose only through the SDK's managed exact-route runtime facade."""

    if runtime_binding is None:
        raise SimNowPaperError("MANAGED_RUNTIME_BINDING_UNAVAILABLE")
    if access_mode not in {"read_only", "managed_execution"}:
        raise SimNowPaperError("MANAGED_RUNTIME_ACCESS_MODE_INVALID")
    if access_mode == "read_only" and (
        authorization_source is not None or operator_grant is not None
    ):
        raise SimNowPaperError("READ_ONLY_RUNTIME_WRITE_INPUT_INVALID")
    if access_mode == "managed_execution" and (
        authorization_source is None or operator_grant is None
    ):
        raise SimNowPaperError("MANAGED_RUNTIME_AUTHORIZATION_UNAVAILABLE")
    try:
        from bt_api_py.managed_runtime_composition import compose_managed_runtime

        return compose_managed_runtime(
            configuration,
            runtime_binding=runtime_binding,
            access_mode=access_mode,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        )
    except Exception as exc:  # noqa: BLE001 - never surface provider details
        code = getattr(exc, "code", None)
        if type(code) is str and code.isascii() and code.replace("_", "").isalnum():
            raise SimNowPaperError(code) from None
        raise SimNowPaperError("MANAGED_RUNTIME_COMPOSITION_UNAVAILABLE") from None


def collect_readonly_preflight(
    api: Any,
    configuration: Any,
    *,
    timeout_seconds: float = 15.0,
    lease_seconds: float = 10.0,
) -> dict[str, Any]:
    """Project the SDK's bounded read-only preflight into example errors."""
    from bt_api_py.query_preflight import (
        ReadOnlyPreflightError,
        collect_readonly_preflight as collect_sdk_preflight,
    )

    try:
        return collect_sdk_preflight(
            api, configuration,
            timeout_seconds=timeout_seconds,
            lease_seconds=lease_seconds,
            request_ref_prefix="i52-simnow-",
            lease_purpose="iteration52.simnow.readonly_preflight",
        )
    except ReadOnlyPreflightError as exc:
        raise SimNowPaperError(exc.code) from None


__all__ = [
    "SimNowPaperError",
    "collect_readonly_preflight",
    "compose_runtime",
    "load_configuration",
]
