"""Fail-closed gate for unregistered SimNow TD settlement readiness.

The available readiness adapter only consumes a SettlementInfoConfirm query.
Its native row has ConfirmDate and SettlementID, but no TradingDay. A trusted
current-session TradingDay therefore cannot be associated with the confirmed
settlement without a separately verified SettlementInfo query joined by
account and SettlementID. This module does not have that query pair and
refuses before issuing a provider query.

The offline join contract lives in
``ctp_simnow_settlement_callback_candidate``. It validates shape only and does
not establish provider provenance or trading readiness. Nothing here grants
write authority or registers a runtime route.
"""

from __future__ import annotations

import hashlib
import hmac
import math
from dataclasses import dataclass
from typing import Any, Callable

from .ctp_simnow_managed_operator import CtpSimNowManagedScopeSelection
from .ctp_simnow_managed_runtime import (
    CtpSimNowNativeReadiness,
    CtpSimulationExecutionError,
)
from .ctp_native_shutdown import stop_ctp_native_client
from .ctp_simulation_execution import CtpSimulationExecutionRegistration


class CtpSimNowTdTradingReadinessError(CtpSimulationExecutionError):
    """Redacted failure while checking current TD settlement readiness."""

    def __init__(self, reason: str, *, close_state: str = "not_started") -> None:
        self.close_state = close_state
        super().__init__(reason)


@dataclass(frozen=True)
class CtpSimNowTdTradingReadinessConfig:
    """Non-secret startup identity used to bind the public TD observation."""

    md_front: str
    td_front: str
    broker_id: str
    user_id: str


@dataclass(frozen=True)
class CtpSimNowTdTradingReadiness:
    """Conservative DTO; this adapter currently cannot issue a positive result."""

    config_digest: str
    registration_digest: str
    front_pair_set_sha256: str
    account_fingerprint_sha256: str
    account_fingerprint: str
    md_front: str
    td_front: str
    connection_generation: int
    trading_day: str
    settlement_query_request_id: int
    settlement_proof_source: str = "none"
    settlement_readback_verified: bool = False
    td_trading_ready: bool = False
    md_ready: bool = True
    execution_gate_armed: bool = False
    write_authority_granted: bool = False


def _reject(reason: str) -> None:
    raise CtpSimNowTdTradingReadinessError(reason)


def _account_fingerprints(broker_id: str, user_id: str) -> tuple[str, str]:
    short = hashlib.sha256("{0}:{1}".format(broker_id, user_id).encode("utf-8")).hexdigest()[:16]
    return short, hashlib.sha256(("acct_" + short).encode("ascii")).hexdigest()


def _validate_selection(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    config: CtpSimNowTdTradingReadinessConfig,
    native_readiness: CtpSimNowNativeReadiness,
    timeout_seconds: float,
) -> CtpSimulationExecutionRegistration:
    if type(selection) is not CtpSimNowManagedScopeSelection:
        _reject("managed_simnow_selection_required")
    registration = selection.execution_registration
    if type(registration) is not CtpSimulationExecutionRegistration:
        _reject("managed_simnow_registration_required")
    if type(config) is not CtpSimNowTdTradingReadinessConfig:
        _reject("managed_simnow_td_config_required")
    if type(native_readiness) is not CtpSimNowNativeReadiness:
        _reject("managed_simnow_prior_native_readiness_required")
    if (
        type(timeout_seconds) not in (int, float)
        or not math.isfinite(float(timeout_seconds))
        or not 0 < float(timeout_seconds) <= 60
    ):
        _reject("managed_simnow_td_timeout_invalid")
    identity_values = (config.md_front, config.td_front, config.broker_id, config.user_id)
    if any(
        type(value) is not str or not value or value != value.strip() for value in identity_values
    ):
        _reject("managed_simnow_td_config_invalid")
    if (
        registration.environment != "simnow"
        or registration.sdk_profile != "config_front_pair"
        or registration.config_digest != selection.config_digest
        or registration.front_pair_set_sha256 != selection.front_pair_set_sha256
        or registration.effective_digest != selection.effective_digest
        or registration.md_front != selection.front_pair_selection.pair.md_front
        or registration.td_front != selection.front_pair_selection.pair.td_front
        or config.md_front != registration.md_front
        or config.td_front != registration.td_front
    ):
        _reject("managed_simnow_td_selected_scope_mismatch")
    if (
        native_readiness.config_digest != selection.config_digest
        or native_readiness.registration_digest != registration.digest
        or native_readiness.account_fingerprint_sha256 != registration.account_fingerprint_sha256
        or native_readiness.md_front != registration.md_front
        or native_readiness.td_front != registration.td_front
        or native_readiness.td_ready is not True
        or native_readiness.md_ready is not True
        or native_readiness.td_trading_ready is not False
    ):
        _reject("managed_simnow_td_prior_readiness_scope_mismatch")
    _, account_digest = _account_fingerprints(config.broker_id, config.user_id)
    if not hmac.compare_digest(account_digest, registration.account_fingerprint_sha256):
        _reject("managed_simnow_td_account_mismatch")
    for name in (
        "get_session_state",
        "get_front_binding_state",
        "get_query_session_scope",
        "get_request_counts",
        "verify_settlement_confirmation",
        "stop",
    ):
        if not callable(getattr(trader_client, name, None)):
            _reject("managed_simnow_td_public_api_unavailable")
    return registration


def _close_after_failure(trader_client: Any, failure_cleanup: Callable[[], None] | None) -> bool:
    if callable(failure_cleanup):
        try:
            failure_cleanup()
        except BaseException:
            # Do not retry a native stop after the shared owner had an
            # incomplete close result.
            return False
        return True
    stop_ctp_native_client(trader_client)
    return False


def verify_ctp_simnow_td_trading_readiness(
    trader_client: Any,
    selection: CtpSimNowManagedScopeSelection,
    config: CtpSimNowTdTradingReadinessConfig,
    *,
    native_readiness: CtpSimNowNativeReadiness,
    failure_cleanup: Callable[[], None] | None = None,
    timeout_seconds: float = 5.0,
) -> CtpSimNowTdTradingReadiness:
    """Reject confirmation-only evidence before issuing a provider query.

    A SettlementInfoConfirm row's ``ConfirmDate`` is not the active session's
    ``TradingDay``. The current adapter has no separately attested
    SettlementInfo query to join by exact ``SettlementID``, account, and
    session generation. Until that source path exists, this readiness gate
    closes the owned session and remains unavailable.
    """

    try:
        if not callable(failure_cleanup):
            _reject("managed_simnow_td_failure_cleanup_required")
        _validate_selection(
            trader_client,
            selection,
            config,
            native_readiness,
            timeout_seconds,
        )
        _reject("managed_simnow_td_settlement_day_binding_unavailable")
    except CtpSimNowTdTradingReadinessError as exc:
        closed = _close_after_failure(trader_client, failure_cleanup)
        raise CtpSimNowTdTradingReadinessError(
            exc.reason,
            close_state="closed" if closed else "close_failed",
        ) from None


__all__ = [
    "CtpSimNowTdTradingReadiness",
    "CtpSimNowTdTradingReadinessConfig",
    "CtpSimNowTdTradingReadinessError",
    "verify_ctp_simnow_td_trading_readiness",
]
