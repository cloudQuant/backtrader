
"""Provider-neutral composition helper for an explicitly selected SDK route."""

from pathlib import Path
from typing import Any


CTP_FUTURE_ROUTE = "CTP___FUTURE"


class SimNowRuntimeError(RuntimeError):
    """Finite status without provider values."""

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or not code.isascii()
            or len(code) > 128
            or any(not (char.isupper() or char.isdigit() or char == "_") for char in code)
        ):
            code = "MANAGED_RUNTIME_COMPOSITION_FAILED"
        self.code = code
        super().__init__(self.code)


def validate_runtime_inputs(
    *,
    runtime_binding: object,
    access_mode: str,
    authorization_source: object | None = None,
    operator_grant: object | None = None,
) -> None:
    """Validate carrier shape before opening configuration or a provider route."""

    if runtime_binding is None:
        raise SimNowRuntimeError("MANAGED_RUNTIME_BINDING_UNAVAILABLE")
    try:
        from bt_api_py.facade_protocol import ManagedRuntimeBinding, OperatorWriteGrant
    except Exception:
        raise SimNowRuntimeError("MANAGED_RUNTIME_BINDING_UNAVAILABLE") from None
    if type(runtime_binding) is not ManagedRuntimeBinding:
        raise SimNowRuntimeError("MANAGED_RUNTIME_BINDING_UNAVAILABLE")
    if runtime_binding.exchange_name != CTP_FUTURE_ROUTE:
        raise SimNowRuntimeError("MANAGED_RUNTIME_BINDING_ROUTE_MISMATCH")
    if type(access_mode) is not str or access_mode not in {"read_only", "managed_execution"}:
        raise SimNowRuntimeError("MANAGED_RUNTIME_ACCESS_MODE_INVALID")
    if access_mode == "read_only":
        if authorization_source is not None or operator_grant is not None:
            raise SimNowRuntimeError("MANAGED_RUNTIME_ACCESS_MODE_INVALID")
        return
    if type(operator_grant) is not OperatorWriteGrant:
        raise SimNowRuntimeError("MANAGED_RUNTIME_OPERATOR_GRANT_INVALID")
    if (
        authorization_source is None
        or type(authorization_source) in (bool, str, bytes, int, float)
        or authorization_source is runtime_binding
        or authorization_source is operator_grant
    ):
        raise SimNowRuntimeError("MANAGED_RUNTIME_AUTHORIZATION_SOURCE_UNAVAILABLE")


def compose_provider_runtime(
    *,
    config_path: Path,
    credential_env_file: Path,
    runtime_binding: object,
    access_mode: str,
    authorization_source: object | None = None,
    operator_grant: object | None = None,
) -> tuple[Any, Any]:
    """Pass a secret-free config DTO and opaque host inputs through bt_api_py."""

    validate_runtime_inputs(
        runtime_binding=runtime_binding,
        access_mode=access_mode,
        authorization_source=authorization_source,
        operator_grant=operator_grant,
    )
    if not isinstance(config_path, Path) or not isinstance(credential_env_file, Path):
        raise SimNowRuntimeError("PROVIDER_CONFIGURATION_REQUEST_INVALID")
    try:
        from bt_api_py.provider_configuration import (
            ProviderConfigurationError,
            load_provider_configuration,
        )
        from bt_api_py.managed_runtime_composition import (
            ManagedRuntimeCompositionError,
            compose_managed_runtime,
        )
    except Exception:
        raise SimNowRuntimeError("PROVIDER_CONFIGURATION_CAPABILITY_UNAVAILABLE") from None

    try:
        configuration = load_provider_configuration(
            CTP_FUTURE_ROUTE,
            config_path=config_path,
            credential_env_file=credential_env_file,
        )
    except ProviderConfigurationError as exc:
        raise SimNowRuntimeError(exc.code) from None
    except Exception:
        raise SimNowRuntimeError("PROVIDER_CONFIGURATION_FAILED") from None

    try:
        composition = compose_managed_runtime(
            configuration,
            runtime_binding=runtime_binding,
            access_mode=access_mode,
            authorization_source=authorization_source,
            operator_grant=operator_grant,
        )
    except ManagedRuntimeCompositionError as exc:
        raise SimNowRuntimeError(exc.code) from None
    except Exception:
        raise SimNowRuntimeError("MANAGED_RUNTIME_COMPOSITION_FAILED") from None
    return configuration, composition


__all__ = [
    "CTP_FUTURE_ROUTE",
    "SimNowRuntimeError",
    "compose_provider_runtime",
    "validate_runtime_inputs",
]
