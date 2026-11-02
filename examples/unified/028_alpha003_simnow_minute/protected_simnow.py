"""Unavailable legacy protected SimNow configuration handoff.

The former helper depended on the retired Backtrader runtime and a CTP-specific
credential/admission registry. The unified SDK currently exposes neither a
provider-neutral protected-config handoff nor equivalent admission proof, so
this example reports the precise capability gap before reading configuration
or credentials.
"""

from contextlib import contextmanager


class ProtectedSimNowConfigError(ValueError):
    """Finite, value-free reason for an unavailable protected-config feature."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@contextmanager
def protected_simnow_store_config(*, selected_config_index: int):
    """Reject until ``bt_api_py`` supplies a neutral protected-config facade."""
    if type(selected_config_index) is not int or not 0 <= selected_config_index < 8:
        raise ProtectedSimNowConfigError("CONFIG_INDEX_INVALID")
    raise ProtectedSimNowConfigError(
        "SDK_PROTECTED_SIMNOW_ADMISSION_CAPABILITY_UNAVAILABLE"
    )
    yield None  # pragma: no cover - preserves the context-manager API shape
