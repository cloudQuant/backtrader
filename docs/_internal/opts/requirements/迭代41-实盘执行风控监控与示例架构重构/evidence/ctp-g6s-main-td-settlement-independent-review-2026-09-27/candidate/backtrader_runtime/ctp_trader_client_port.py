"""Explicit-front, gated adapter from the SimNow session to CTP TraderClient.

This adapter is intentionally not connected to the runtime inventory or CLI.
Its factory constructs a ``TraderClient`` with the exact sealed TD front and
never starts it. The internal SDK policy profile is always ``config_front_pair``;
the exact TD/MD pair comes from the sealed config and code-owned registration.
Managed writes keep the general execution gate disarmed and require an explicitly injected
runtime approval verifier, durable order identity resolver, per-action SDK
binding factory, fresh SDK approval rechecker, and runtime admission check.
The SDK checks the immutable operation scope under its lock at the final
ReqOrderInsert/ReqOrderAction boundary.

The port preserves native QueryResult objects for an injected evidence
verifier.  It does not claim that a terminal query alone proves account-wide
coverage, and cancellation outcomes remain UNKNOWN after restart because the
SDK currently keeps action callback history only in memory.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping

from .ctp_simulation_execution import (
    CtpSimulationCancelRequestSnapshot,
    CtpSimulationDispatchReceipt,
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    CtpSimulationNativePort,
    CtpSimulationOrderSnapshot,
    CtpSimulationPositionSnapshot,
    CtpSimulationQueryResult,
    CtpSimulationSessionIdentity,
    CtpSimulationTradeSnapshot,
    CtpSimulationWriteApproval,
    CtpSimulationWriteRequest,
)
from .ctp_native_shutdown import stop_ctp_native_client


_SIMNOW_ENVIRONMENT = "simnow"
_SIMNOW_SDK_PROFILE = "config_front_pair"
_SIDE_BY_DIRECTION = {"0": "BUY", "1": "SELL"}


def _reject(reason: str) -> None:
    raise CtpSimulationExecutionError(reason)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("ascii", errors="ignore").rstrip("\x00 ")
    return str(value).rstrip("\x00 ")


def _value(row: Any, *names: str) -> Any:
    if isinstance(row, Mapping):
        for name in names:
            if name in row:
                return row[name]
    for name in names:
        result = getattr(row, name, None)
        if result is not None:
            return result
    return None


def _int_field(row: Any, *names: str, required: bool = True) -> int:
    value = _value(row, *names)
    if isinstance(value, bool):
        _reject("native_query_integer_invalid")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        if not required and value in (None, ""):
            return 0
        _reject("native_query_integer_invalid")
    return result


def _decimal_field(row: Any, *names: str) -> Decimal:
    value = _value(row, *names)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        _reject("native_query_decimal_invalid")
    if not result.is_finite():
        _reject("native_query_decimal_invalid")
    return result


def _sdk_simnow_binding_type() -> type | None:
    """Return the installed SDK's exact typed SimNow binding, when available."""

    try:
        from bt_api_ctp.ctp.client import CtpRuntimeSimNowCredentialBinding
    except Exception:
        return None
    return CtpRuntimeSimNowCredentialBinding


def _sdk_trader_client_type() -> type | None:
    try:
        from bt_api_ctp.ctp.client import TraderClient
    except Exception:
        return None
    return TraderClient


def _require_sdk_simnow_binding(
    binding: Any, profile: str, config: "CtpSimulationTraderConfig"
) -> None:
    binding_type = _sdk_simnow_binding_type()
    if binding_type is None or type(binding) is not binding_type:
        _reject("native_runtime_credential_binding_unavailable")
    if (
        getattr(binding, "td_front", None) != config.td_front
        or getattr(binding, "md_front", None) != config.md_front
        or getattr(binding, "environment_profile", None) != profile
        or not callable(getattr(binding, "write_intent_verifier", None))
    ):
        _reject("native_runtime_credential_binding_scope_mismatch")


@dataclass(frozen=True)
class CtpSimulationTraderConfig:
    """Private CTP inputs resolved by the sealed runtime before this factory.

    Callers must supply every field.  This object does not read environment
    variables, choose a profile, or select a reachable endpoint. Its exact
    TD/MD pair must equal the code-owned registration's explicitly selected
    pair. The SDK receives the neutral ``config_front_pair`` policy profile;
    endpoint reachability or a SimNow set label never changes that pair.
    """

    td_front: str
    md_front: str
    broker_id: str
    user_id: str
    password: str = field(repr=False)
    auth_code: str = field(repr=False)
    app_id: str = field(repr=False)
    auto_detect_fronts: bool = False

    def validate(
        self,
        registration: CtpSimulationExecutionRegistration,
    ) -> str:
        if type(registration) is not CtpSimulationExecutionRegistration:
            _reject("code_owned_registration_required")
        if self.auto_detect_fronts is not False:
            _reject("ctp_front_auto_selection_forbidden")
        values = (
            self.td_front,
            self.md_front,
            self.broker_id,
            self.user_id,
            self.password,
            self.auth_code,
            self.app_id,
        )
        if any(type(value) is not str or not value or value != value.strip() for value in values):
            _reject("sealed_ctp_configuration_incomplete")
        if (
            registration.environment != _SIMNOW_ENVIRONMENT
            or registration.sdk_profile != _SIMNOW_SDK_PROFILE
            or self.td_front != registration.td_front
            or self.md_front != registration.md_front
        ):
            _reject("sealed_ctp_front_pair_registration_mismatch")
        return _SIMNOW_SDK_PROFILE

    def feed_kwargs(
        self,
        registration: CtpSimulationExecutionRegistration,
    ) -> dict[str, Any]:
        """Return explicit constructor inputs for a future feed composition."""
        profile = self.validate(registration)
        return {
            "broker_id": self.broker_id,
            "user_id": self.user_id,
            "password": self.password,
            "auth_code": self.auth_code,
            "app_id": self.app_id,
            "td_front": self.td_front,
            "md_front": self.md_front,
            "ctp_env_profile": profile,
            "auto_detect_fronts": False,
            "auto_settlement_confirm": False,
        }

    def assert_resolved_feed(
        self,
        feed: Any,
        registration: CtpSimulationExecutionRegistration,
    ) -> None:
        """Check the constructed feed still carries the exact sealed fronts.

        A managed composition must call this after constructing a feed from
        :meth:`feed_kwargs` and before ``connect()`` creates a native client.
        The readiness marker must say the pair was explicit; TCP probing or a
        mixed/environment-selected pair is insufficient for this route.
        """
        profile = self.validate(registration)
        expected = {
            "ctp_env_profile": profile,
            "td_front": self.td_front,
            "md_front": self.md_front,
            "_execution_bound_profile": profile,
            "_execution_bound_td_front": self.td_front,
            "_execution_bound_md_front": self.md_front,
            "_execution_bound_broker_id": self.broker_id,
            "_execution_bound_user_id": self.user_id,
        }
        if any(_text(getattr(feed, name, "")) != value for name, value in expected.items()):
            _reject("resolved_ctp_feed_binding_mismatch")
        if getattr(feed, "ctp_env_readiness", None) != "explicit_config_pair":
            _reject("resolved_ctp_feed_pair_not_explicit")
        if getattr(feed, "auto_settlement_confirm", None) is not False:
            _reject("ctp_automatic_settlement_confirmation_forbidden")

    def create_verified_feed(
        self,
        feed_factory: Callable[..., Any],
        registration: CtpSimulationExecutionRegistration,
    ) -> Any:
        """Build an unconnected feed with explicit inputs, then pin-check it."""
        if not callable(feed_factory):
            _reject("ctp_feed_factory_required")
        try:
            feed = feed_factory(**self.feed_kwargs(registration))
        except Exception as exc:
            raise CtpSimulationExecutionError("ctp_feed_construction_failed") from exc
        self.assert_resolved_feed(feed, registration)
        return feed


class CtpTraderClientSimulationPort(CtpSimulationNativePort):
    """Map the managed SimNow protocol to an already constructed TraderClient.

    The constructor does not start or connect the client.  ``write_admitted``
    remains false unless the caller supplies the SDK's opaque capability,
    durable order identity resolver, runtime approval verifier, per-action
    binding factory, and current SDK approval rechecker. SimNow keeps the
    general gate disarmed; each managed insert/cancel instead needs
    a distinct typed SDK binding whose immutable final-write scope is checked
    immediately before native dispatch.
    """

    def __init__(
        self,
        trader_client: Any,
        registration: CtpSimulationExecutionRegistration,
        config: CtpSimulationTraderConfig,
        *,
        execution_capability: object | None = None,
        runtime_admission_check: Callable[[], bool] | None = None,
        runtime_order_binding: Callable[[str, bool], Mapping[str, Any]] | None = None,
        runtime_credential_binding: Any | None = None,
        runtime_credential_binding_factory: Callable[..., Any] | None = None,
        runtime_approval_verifier: Any | None = None,
        sdk_approval_rechecker: Callable[[Any, Mapping[str, Any]], bool] | None = None,
        order_field_factory: Callable[[], Any] | None = None,
        action_field_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.profile = config.validate(registration)
        if trader_client is None:
            _reject("native_trader_client_required")
        if (
            _text(getattr(trader_client, "_bound_front", "")) != config.td_front
            or _text(getattr(trader_client, "_bound_md_front", "")) != config.md_front
            or _text(getattr(trader_client, "_bound_broker_id", "")) != config.broker_id
            or _text(getattr(trader_client, "_bound_user_id", "")) != config.user_id
            or getattr(trader_client, "auto_settlement_confirm", None) is not False
        ):
            _reject("native_trader_client_front_or_account_mismatch")
        account_fingerprint = _text(getattr(trader_client, "_account_fingerprint", ""))
        expected_account_fingerprint = hashlib.sha256(
            f"{config.broker_id}:{config.user_id}".encode("utf-8")
        ).hexdigest()[:16]
        account_digest = hashlib.sha256(
            ("acct_" + expected_account_fingerprint).encode("ascii")
        ).hexdigest()
        if (
            account_fingerprint != expected_account_fingerprint
            or account_digest != registration.account_fingerprint_sha256
        ):
            _reject("native_trader_client_account_mismatch")
        factories = (order_field_factory, action_field_factory)
        if any(factory is not None and not callable(factory) for factory in factories):
            _reject("native_ctp_field_factory_invalid")
        if runtime_credential_binding_factory is not None and not callable(
            runtime_credential_binding_factory
        ):
            _reject("native_runtime_credential_binding_factory_invalid")
        if sdk_approval_rechecker is not None and not callable(sdk_approval_rechecker):
            _reject("native_sdk_approval_rechecker_invalid")
        if runtime_credential_binding is not None and runtime_credential_binding_factory is None:
            _reject("native_runtime_credential_binding_factory_required")
        self._trader = trader_client
        self.registration = registration
        self.config = config
        self._execution_capability = execution_capability
        self._runtime_admission_check = runtime_admission_check
        self._runtime_order_binding = runtime_order_binding
        self._runtime_credential_binding = runtime_credential_binding
        self._runtime_credential_binding_generation: int | None = None
        self._runtime_credential_binding_factory = runtime_credential_binding_factory
        self._runtime_approval_verifier = runtime_approval_verifier
        self._sdk_approval_rechecker = sdk_approval_rechecker
        self._write_lock = threading.RLock()
        self._staged_write: (
            tuple[CtpSimulationWriteRequest, CtpSimulationWriteApproval, str | None] | None
        ) = None
        self._pending_sdk_intent: dict[str, Any] | None = None
        self._pending_sdk_intent_consumed = False
        self._sdk_write_intent_callback = self._verify_sdk_write_intent
        self._order_field_factory = order_field_factory
        self._action_field_factory = action_field_factory
        self._actions: dict[str, tuple[int, CtpSimulationOrderSnapshot]] = {}
        self._closed = False
        self._close_failed = False
        if execution_capability is not None:
            client_type = _sdk_trader_client_type()
            configure_gate = getattr(trader_client, "configure_execution_gate", None)
            if (
                client_type is None
                or type(trader_client) is not client_type
                or not callable(configure_gate)
            ):
                _reject("native_managed_trader_client_unavailable")
            try:
                state = configure_gate(execution_capability)
            except Exception as exc:
                raise CtpSimulationExecutionError("native_execution_capability_rejected") from exc
            if not isinstance(state, Mapping) or state.get("armed") is not False:
                _reject("native_simnow_managed_gate_must_start_disarmed")
        if runtime_credential_binding is not None:
            # A static binding cannot carry a request-specific, single-use
            # runtime verifier.  It is deliberately never installed here.
            _reject("native_per_action_credential_binding_required")

    @property
    def write_admitted(self) -> bool:
        """Report admission only when both native and runtime gates are present."""
        if (
            self._execution_capability is None
            or self._runtime_admission_check is None
            or self._runtime_order_binding is None
            or self._runtime_credential_binding_factory is None
            or self._runtime_credential_binding is None
            or self._runtime_approval_verifier is None
            or not callable(getattr(self._runtime_approval_verifier, "verify", None))
            or self._sdk_approval_rechecker is None
            or self.profile != _SIMNOW_SDK_PROFILE
        ):
            return False
        try:
            session = self._trader.get_session_state()
            # A valid read-only CTP session is not proof that settlement has
            # been confirmed or that a trading request may be sent.
            if not isinstance(session, Mapping) or session.get("trading_ready") is not True:
                return False
            self.get_execution_identity()
            self._require_installed_runtime_binding()
            admitted = self._runtime_admission_check()
        except CtpSimulationExecutionError:
            return False
        except Exception:
            return False
        return admitted is True

    def _new_order_field(self) -> Any:
        if self._order_field_factory is not None:
            return self._order_field_factory()
        try:
            from bt_api_ctp.ctp.ctp_structs_order import CThostFtdcInputOrderField

            return CThostFtdcInputOrderField()
        except Exception as exc:
            raise CtpSimulationExecutionError("native_ctp_order_field_unavailable") from exc

    def _new_action_field(self) -> Any:
        if self._action_field_factory is not None:
            return self._action_field_factory()
        try:
            from bt_api_ctp.ctp.ctp_structs_order import CThostFtdcInputOrderActionField

            return CThostFtdcInputOrderActionField()
        except Exception as exc:
            raise CtpSimulationExecutionError("native_ctp_action_field_unavailable") from exc

    def _require_write(self) -> CtpSimulationSessionIdentity:
        if self.profile != _SIMNOW_SDK_PROFILE:
            _reject("native_simnow_config_front_pair_required")
        self._require_td_trading_ready()
        if not self.write_admitted:
            _reject("native_execution_gate_not_admitted")
        return self.get_execution_identity()

    def _require_td_trading_ready(self) -> None:
        """Keep authenticated read-only identity separate from write readiness."""

        try:
            state = self._trader.get_session_state()
        except Exception:
            _reject("native_trader_session_state_unavailable")
        if not isinstance(state, Mapping) or state.get("trading_ready") is not True:
            _reject("native_trader_session_not_trading_ready")

    def _verify_runtime_approval(
        self,
        request: CtpSimulationWriteRequest,
        approval: CtpSimulationWriteApproval,
    ) -> None:
        verifier = self._runtime_approval_verifier
        registration = self.registration
        now = time.time()
        if (
            type(request) is not CtpSimulationWriteRequest
            or type(approval) is not CtpSimulationWriteApproval
            or approval.key_id != registration.approval_key_id
            or approval.registration_digest != registration.digest
            or approval.receipt_digest != registration.runtime_registration.approval_receipt_digest
            or approval.account_fingerprint_sha256 != registration.account_fingerprint_sha256
            or approval.environment != registration.environment
            or approval.td_front != registration.td_front
            or approval.md_front != registration.md_front
            or approval.request_digest != request.digest
            or approval.expires_at - approval.issued_at > registration.approval_ttl_seconds
            or approval.issued_at > now + 1.0
            or approval.expires_at <= now
            or verifier is None
        ):
            _reject("native_runtime_write_approval_scope_mismatch")
        try:
            verified = verifier.verify(approval)
        except Exception:
            verified = False
        if verified is not True:
            _reject("native_runtime_write_approval_rejected")

    def _install_action_binding(
        self,
        request: CtpSimulationWriteRequest,
        approval: CtpSimulationWriteApproval,
        action_id: str | None,
        identity: CtpSimulationSessionIdentity,
    ) -> Any:
        factory = self._runtime_credential_binding_factory
        if not callable(factory):
            _reject("native_per_action_credential_binding_required")
        if request.action == "CANCEL" and (
            type(action_id) is not str or not action_id or action_id != action_id.strip()
        ):
            _reject("native_cancel_action_id_invalid")
        if request.action == "SUBMIT" and action_id is not None:
            _reject("native_submit_action_id_forbidden")
        try:
            binding = factory(
                operation="insert" if request.action == "SUBMIT" else "cancel",
                request=request,
                runtime_approval=approval,
                action_id=action_id,
                identity=identity,
                write_intent_verifier=self._sdk_write_intent_callback,
            )
        except Exception as exc:
            raise CtpSimulationExecutionError("native_sdk_write_binding_creation_failed") from exc
        _require_sdk_simnow_binding(binding, self.profile, self.config)
        if getattr(binding, "write_intent_verifier", None) is not self._sdk_write_intent_callback:
            _reject("native_sdk_write_verifier_not_bound")
        configure_binding = getattr(
            self._trader, "configure_runtime_simnow_credential_binding", None
        )
        if not callable(configure_binding):
            _reject("native_runtime_credential_binding_unavailable")
        try:
            result = configure_binding(self._execution_capability, binding)
        except Exception as exc:
            raise CtpSimulationExecutionError("native_runtime_credential_binding_rejected") from exc
        if (
            not isinstance(result, Mapping)
            or result.get("configured") is not True
            or result.get("environment_profile") != self.profile
            or result.get("connection_generation") != identity.connection_generation
        ):
            _reject("native_runtime_credential_binding_result_invalid")
        self._runtime_credential_binding = binding
        self._runtime_credential_binding_generation = identity.connection_generation
        self._require_installed_runtime_binding()
        return binding

    def authorize_write(
        self,
        request: CtpSimulationWriteRequest,
        approval: CtpSimulationWriteApproval,
        *,
        action_id: str | None = None,
    ) -> None:
        """Stage one signed managed intent before its typed SDK dispatch.

        The execution session calls this only after it reserves the durable
        journal row and verifies the runtime approval. This adapter repeats
        signature and scope checks, installs the matching typed SDK entry or
        recovery binding, and gives the SDK one exact callback scope to consume.
        """

        with self._write_lock:
            if self._staged_write is not None or self._pending_sdk_intent is not None:
                _reject("native_managed_write_already_staged")
            self._require_td_trading_ready()
            identity = self.get_execution_identity()
            if not identity.native_simnow_managed_mode:
                _reject("native_simnow_managed_capability_unproven")
            self._verify_runtime_approval(request, approval)
            if self._runtime_admission_check is None:
                _reject("native_runtime_admission_verifier_required")
            try:
                admitted = self._runtime_admission_check()
            except Exception:
                admitted = False
            if admitted is not True:
                _reject("native_runtime_admission_rejected")
            binding = self._install_action_binding(request, approval, action_id, identity)
            self._staged_write = (request, approval, action_id)
            # Keep this exact SDK binding with the staged approval. A later
            # callback cannot switch the SDK verifier or the recovery approval.
            if self._runtime_credential_binding is not binding:
                self._staged_write = None
                _reject("native_runtime_credential_binding_changed")

    def _require_staged_write(
        self,
        request: CtpSimulationWriteRequest,
        *,
        action_id: str | None = None,
    ) -> tuple[CtpSimulationWriteApproval, Any]:
        with self._write_lock:
            staged = self._staged_write
            if staged is None or staged[0] != request or staged[2] != action_id:
                _reject("native_managed_write_not_authorized")
            approval = staged[1]
            binding = self._require_installed_runtime_binding()
            self._verify_runtime_approval(request, approval)
            self._staged_write = None
            return approval, binding

    def _set_pending_sdk_intent(
        self,
        *,
        request: CtpSimulationWriteRequest,
        approval: CtpSimulationWriteApproval,
        binding: Any,
        identity: CtpSimulationSessionIdentity,
        managed_intent_id: str,
        order_ref: str,
        request_id: int,
        action_id: str | None,
    ) -> None:
        sdk_approval = getattr(binding, "approval", None)
        approval_id = getattr(sdk_approval, "approval_id", None)
        approval_nonce = getattr(sdk_approval, "nonce", None)
        approval_payload_sha256 = getattr(sdk_approval, "payload_sha256", None)
        if (
            type(approval_id) is not str
            or not approval_id
            or type(approval_nonce) not in (str, int)
            or type(approval_payload_sha256) is not str
            or len(approval_payload_sha256) != 64
            or any(character not in "0123456789abcdef" for character in approval_payload_sha256)
        ):
            _reject("native_sdk_approval_identity_invalid")
        expected = {
            "schema_version": "ctp-simnow-managed-write-v1",
            "operation": "insert" if request.action == "SUBMIT" else "cancel",
            "td_front": self.config.td_front,
            "md_front": self.config.md_front,
            "environment_profile": self.profile,
            "account_fingerprint": "acct_"
            + _text(getattr(self._trader, "_account_fingerprint", "")),
            "trading_day": identity.trading_day,
            "connection_generation": identity.connection_generation,
            "instrument_id": request.instrument_id,
            "exchange_id": request.exchange_id,
            "runtime_order_id": request.client_order_id,
            "managed_intent_id": managed_intent_id,
            "runtime_action_id": action_id,
            "managed_cancel_intent_id": action_id,
            "request_id": request_id,
            "approval_id": approval_id,
            "approval_nonce": str(approval_nonce),
            "approval_payload_sha256": approval_payload_sha256,
        }
        if request.action == "SUBMIT":
            expected.update(
                {
                    "order_ref": order_ref,
                    "direction": "0" if request.side == "BUY" else "1",
                    "offset_flag": "0",
                    "hedge_flag": request.hedge_flag,
                    "volume_total_original": request.quantity,
                    "limit_price": format(request.limit_price.normalize(), "f"),
                    "order_price_type": "2",
                    "time_condition": "3",
                    "volume_condition": "1",
                }
            )
        else:
            expected.update(
                {
                    "order_action_ref": request_id,
                    "action_flag": "0",
                    "target_order_ref": request.target_order_ref,
                    "target_front_id": request.target_front_id,
                    "target_session_id": request.target_session_id,
                    "target_order_sys_id": request.target_order_sys_id,
                }
            )
        with self._write_lock:
            if self._pending_sdk_intent is not None:
                _reject("native_sdk_write_intent_already_pending")
            self._pending_sdk_intent = {
                "expected": expected,
                "request": request,
                "runtime_approval": approval,
                "binding": binding,
            }
            self._pending_sdk_intent_consumed = False

    def _verify_sdk_write_intent(self, scope: Mapping[str, Any]) -> bool:
        """Callback installed into the SDK binding for its final locked gate."""

        with self._write_lock:
            pending = self._pending_sdk_intent
            if (
                pending is None
                or self._pending_sdk_intent_consumed
                or not isinstance(scope, Mapping)
            ):
                return False
            expected = pending["expected"]
            if set(scope) != set(expected) or any(
                scope.get(key) != value for key, value in expected.items()
            ):
                return False
            request = pending["request"]
            approval = pending["runtime_approval"]
            binding = pending["binding"]
            try:
                self._verify_runtime_approval(request, approval)
                if self._runtime_credential_binding is not binding:
                    return False
                if self._sdk_approval_rechecker is None:
                    return False
                sdk_valid = self._sdk_approval_rechecker(binding, scope)
            except Exception:
                return False
            if sdk_valid is not True:
                return False
            self._pending_sdk_intent_consumed = True
            return True

    def _clear_pending_sdk_intent(self) -> None:
        with self._write_lock:
            self._pending_sdk_intent = None
            self._pending_sdk_intent_consumed = False

    def get_execution_identity(self) -> CtpSimulationSessionIdentity:
        try:
            scope = self._trader.get_query_session_scope()
            gate = self._trader.get_execution_gate_state()
            session = self._trader.get_session_state()
            active_front = self._trader._bound_identity_is_current(require_active_front=True)
        except Exception as exc:
            raise CtpSimulationExecutionError("native_trader_session_unavailable") from exc
        if not isinstance(gate, Mapping) or not isinstance(session, Mapping):
            _reject("native_trader_session_identity_invalid")
        if (
            _text(getattr(self._trader, "_bound_front", "")) != self.config.td_front
            or _text(getattr(self._trader, "_bound_md_front", "")) != self.config.md_front
            or getattr(self._trader, "ctp_env_profile", None) != self.profile
        ):
            _reject("native_trader_front_pair_scope_mismatch")
        account = _text(getattr(scope, "account_fingerprint", ""))
        if account.startswith("acct_"):
            account = account[5:]
        trading_day = _text(getattr(scope, "trading_day", ""))
        generation = getattr(scope, "connection_generation", None)
        if (
            account != _text(getattr(self._trader, "_account_fingerprint", ""))
            or type(generation) is not int
            or generation <= 0
            or type(trading_day) is not str
            or len(trading_day) != 8
            or not trading_day.isascii()
            or not trading_day.isdigit()
            or getattr(scope, "read_only_ready", None) is not True
            or session.get("read_only_ready") is not True
            or session.get("auto_settlement_confirm") is not False
            or active_front is not True
        ):
            _reject("native_trader_read_only_session_scope_unproven")

        gate_armed = gate.get("armed")
        if type(gate_armed) is not bool:
            _reject("native_trader_gate_state_invalid")
        simnow_managed_mode = False
        if self.profile != _SIMNOW_SDK_PROFILE:
            _reject("native_trader_session_profile_unsupported")
        # SimNow authorizes each typed managed request under the SDK lock;
        # its general CTP gate must remain disarmed. A bool in the public
        # gate-state mapping is insufficient: the exact installed SDK
        # TraderClient, private capability identity, typed SDK binding,
        # and per-action verifier are all checked separately.
        if gate_armed is True:
            _reject("native_simnow_general_execution_arm_forbidden")
        gate_generation = gate.get("connection_generation")
        if gate_generation not in (None, generation):
            _reject("native_trader_session_scope_unproven")
        if self._execution_capability is not None:
            client_type = _sdk_trader_client_type()
            if (
                client_type is None
                or type(self._trader) is not client_type
                or getattr(self._trader, "_execution_gate_capability", None)
                is not self._execution_capability
            ):
                _reject("native_simnow_managed_capability_unproven")
            simnow_managed_mode = True
        if gate.get("environment_profile") not in (None, self.profile):
            _reject("native_trader_session_scope_unproven")

        return CtpSimulationSessionIdentity(
            environment=_SIMNOW_ENVIRONMENT,
            sdk_profile=self.profile,
            td_front=self.config.td_front,
            md_front=self.config.md_front,
            account_fingerprint_sha256=self.registration.account_fingerprint_sha256,
            trading_day=trading_day,
            connection_generation=generation,
            production=False,
            native_gate_armed=gate_armed,
            native_simnow_managed_mode=simnow_managed_mode,
        )

    def _require_installed_runtime_binding(self) -> Any:
        binding = self._runtime_credential_binding
        _require_sdk_simnow_binding(binding, self.profile, self.config)
        if (
            getattr(self._trader, "_runtime_simnow_credential_binding", None) is not binding
            or getattr(binding, "write_intent_verifier", None)
            is not self._sdk_write_intent_callback
        ):
            _reject("native_runtime_credential_binding_not_installed")
        try:
            gate = self._trader.get_execution_gate_state()
        except Exception as exc:
            raise CtpSimulationExecutionError("native_trader_session_unavailable") from exc
        if (
            not isinstance(gate, Mapping)
            or gate.get("armed") is not False
            or gate.get("runtime_simnow_credential_binding_configured") is not True
            or gate.get("runtime_simnow_write_verifier_configured") is not True
            or self._runtime_credential_binding_generation
            != getattr(self._trader, "_connection_generation", None)
            or gate.get("connection_generation")
            not in (None, self._runtime_credential_binding_generation)
        ):
            _reject("native_simnow_managed_gate_state_unproven")
        return binding

    def _request_id(self) -> int:
        method = getattr(self._trader, "_next_request_id", None)
        if not callable(method):
            _reject("native_trader_request_id_unavailable")
        value = method()
        if type(value) is not int or value <= 0:
            _reject("native_trader_request_id_invalid")
        return value

    @staticmethod
    def _require_native_ref(value: str) -> str:
        try:
            encoded = value.encode("ascii")
        except (AttributeError, UnicodeEncodeError):
            _reject("native_order_ref_invalid")
        if len(encoded) != 12 or not encoded.isdigit() or b"\x00" in encoded:
            _reject("native_order_ref_invalid")
        return value

    def _resolve_runtime_order_binding(
        self,
        runtime_order_id: str,
        *,
        reserve: bool,
        expected_identity: CtpSimulationSessionIdentity | None = None,
    ) -> Mapping[str, Any]:
        resolver = self._runtime_order_binding
        if not callable(resolver):
            _reject("durable_runtime_order_binding_unavailable")
        if type(reserve) is not bool:
            _reject("durable_runtime_order_binding_invalid")
        identity = self.get_execution_identity()
        try:
            binding = resolver(runtime_order_id, reserve)
        except Exception as exc:
            raise CtpSimulationExecutionError("durable_runtime_order_binding_failed") from exc
        if identity != self.get_execution_identity() or (
            expected_identity is not None and identity != expected_identity
        ):
            _reject("durable_runtime_order_binding_session_changed")
        if not isinstance(binding, Mapping):
            _reject("durable_runtime_order_binding_invalid")
        if (
            binding.get("runtime_order_id") != runtime_order_id
            or type(binding.get("connection_generation")) is not int
            or binding.get("connection_generation") != identity.connection_generation
            or type(binding.get("trading_day")) is not str
            or binding.get("trading_day") != identity.trading_day
        ):
            _reject("durable_runtime_order_binding_scope_mismatch")
        if type(binding.get("reserved")) is not bool or binding.get("reserved") is not reserve:
            _reject("durable_runtime_order_binding_reservation_unconfirmed")
        return binding

    def _resolve_runtime_order_ref(
        self,
        runtime_order_id: str,
        *,
        reserve: bool,
        expected_identity: CtpSimulationSessionIdentity | None = None,
    ) -> str:
        binding = self._resolve_runtime_order_binding(
            runtime_order_id,
            reserve=reserve,
            expected_identity=expected_identity,
        )
        ref = self._require_native_ref(_text(binding.get("ctp_order_ref")))
        client_order_id = _text(binding.get("client_order_id"))
        if client_order_id and client_order_id != ref:
            _reject("durable_runtime_order_reference_mismatch")
        return ref

    @staticmethod
    def _managed_intent_id(binding: Mapping[str, Any]) -> str:
        value = binding.get("managed_intent_id")
        if (
            type(value) is not str
            or not value
            or value != value.strip()
            or len(value) > 256
            or not value.isascii()
            or any(not (char.isalnum() or char in "._:-") for char in value)
        ):
            _reject("durable_runtime_managed_intent_binding_invalid")
        return value

    def _dispatch_receipt(
        self,
        *,
        operation: str,
        request: CtpSimulationWriteRequest,
        managed_intent_id: str,
        request_id: int,
        identity: CtpSimulationSessionIdentity,
        native_result: Any,
        evidence: Any,
        order_ref: str,
        action_id: str | None = None,
        snapshot: CtpSimulationOrderSnapshot | None = None,
    ) -> CtpSimulationDispatchReceipt:
        """Translate the SDK's raw submit code and immutable evidence.

        A zero code plus an exact request record proves only local queueing. A
        negative code is a local rejection only when the SDK record proves the
        exact request and confirms that no callback arrived. Everything else
        stays UNKNOWN so the execution journal freezes the action.
        """
        result_code = native_result if type(native_result) is int else None
        try:
            evidence_code = _value(evidence, "submit_code") if evidence is not None else None
        except Exception:
            evidence_code = None
        evidence_code = evidence_code if type(evidence_code) is int else None
        receipt_code = result_code if result_code is not None else evidence_code
        outcome = "UNKNOWN"
        rejection_verified = False

        evidence_matches = False
        callback_received = None
        evidence_received = None
        status = ""
        try:
            callback_received = _value(evidence, "callback_received")
            evidence_received = _value(evidence, "evidence_received")
            status = _text(_value(evidence, "status")).lower()
            account = _text(_value(evidence, "account_fingerprint"))
            evidence_matches = bool(
                evidence is not None
                and type(_value(evidence, "request_id")) is int
                and _value(evidence, "request_id") == request_id
                and evidence_code is not None
                and evidence_code == result_code
                and account == "acct_" + _text(getattr(self._trader, "_account_fingerprint", ""))
                and _text(_value(evidence, "trading_day")) == identity.trading_day
                and type(_value(evidence, "connection_generation")) is int
                and _value(evidence, "connection_generation") == identity.connection_generation
                and _text(_value(evidence, "instrument_id")) == request.instrument_id
                and _text(_value(evidence, "exchange_id")) == request.exchange_id
                and type(callback_received) is bool
                and type(evidence_received) is bool
                and evidence_received is callback_received
                and status in {"unknown", "accepted", "rejected"}
                and identity == self.get_execution_identity()
            )
            if operation == "SUBMIT":
                evidence_matches = evidence_matches and (
                    _text(_value(evidence, "order_ref")) == order_ref
                )
            else:
                evidence_matches = evidence_matches and snapshot is not None and (
                    _text(_value(evidence, "order_action_ref")) == str(request_id)
                    and _text(_value(evidence, "order_ref")) == snapshot.order_ref
                    and _text(_value(evidence, "order_sys_id")) == snapshot.order_sys_id
                    and _int_field(evidence, "front_id", required=False) == snapshot.front_id
                    and _int_field(evidence, "session_id", required=False) == snapshot.session_id
                    and _text(_value(evidence, "action_flag")) == "0"
                )
        except Exception:
            evidence_matches = False

        if evidence_matches and result_code is not None and result_code == evidence_code:
            if result_code == 0:
                outcome = "QUEUED"
            elif (
                result_code < 0
                and callback_received is False
                and evidence_received is False
                and status == "unknown"
            ):
                outcome = "REJECTED"
                rejection_verified = True

        return CtpSimulationDispatchReceipt(
            operation=operation,
            outcome=outcome,
            request_digest=request.digest,
            client_order_id=request.client_order_id,
            managed_intent_id=managed_intent_id,
            action_id=action_id,
            request_id=request_id,
            submit_code=receipt_code,
            identity=identity,
            local_rejection_verified=rejection_verified,
        )

    def _build_order_field(
        self, request: CtpSimulationWriteRequest, request_id: int, order_ref: str
    ) -> Any:
        if request.action != "SUBMIT" or request.offset != "OPEN":
            _reject("native_order_request_scope_invalid")
        field = self._new_order_field()
        values = {
            "BrokerID": self.config.broker_id,
            "InvestorID": self.config.user_id,
            "UserID": self.config.user_id,
            "InstrumentID": request.instrument_id,
            "ExchangeID": request.exchange_id,
            "OrderRef": self._require_native_ref(order_ref),
            "OrderPriceType": "2",
            "Direction": "0" if request.side == "BUY" else "1",
            "CombOffsetFlag": "0",
            "CombHedgeFlag": request.hedge_flag,
            "LimitPrice": float(request.limit_price),
            "VolumeTotalOriginal": request.quantity,
            "TimeCondition": "3",
            "VolumeCondition": "1",
            "MinVolume": 1,
            "ContingentCondition": "1",
            "ForceCloseReason": "0",
            "IsAutoSuspend": 0,
            "UserForceClose": 0,
            "RequestID": request_id,
        }
        for name, value in values.items():
            setattr(field, name, value)
        return field

    def submit_order_insert(
        self, request: CtpSimulationWriteRequest
    ) -> CtpSimulationDispatchReceipt:
        self._require_write()
        if type(request) is not CtpSimulationWriteRequest:
            _reject("native_order_request_invalid")
        approval, credential_binding = self._require_staged_write(request)
        request_id = self._request_id()
        order_binding = self._resolve_runtime_order_binding(
            request.client_order_id,
            reserve=True,
        )
        order_ref = self._require_native_ref(_text(order_binding.get("ctp_order_ref")))
        client_order_id = _text(order_binding.get("client_order_id"))
        if client_order_id and client_order_id != order_ref:
            _reject("durable_runtime_order_reference_mismatch")
        managed_intent_id = self._managed_intent_id(order_binding)
        field = self._build_order_field(request, request_id, order_ref)
        submit = getattr(self._trader, "submit_order_insert", None)
        if not callable(submit):
            _reject("native_order_insert_unavailable")
        self._require_write()
        identity = self.get_execution_identity()
        self._set_pending_sdk_intent(
            request=request,
            approval=approval,
            binding=credential_binding,
            identity=identity,
            managed_intent_id=managed_intent_id,
            order_ref=order_ref,
            request_id=request_id,
            action_id=None,
        )
        try:
            result = submit(
                field,
                request_id,
                execution_capability=self._execution_capability,
                runtime_order_id=request.client_order_id,
                managed_intent_id=managed_intent_id,
            )
            if not self._pending_sdk_intent_consumed:
                _reject("native_sdk_write_verifier_not_invoked")
            evidence_getter = getattr(self._trader, "get_order_insert_evidence", None)
            try:
                evidence = (
                    evidence_getter(request_id, order_ref=order_ref)
                    if callable(evidence_getter)
                    else None
                )
            except Exception:
                evidence = None
            return self._dispatch_receipt(
                operation="SUBMIT",
                request=request,
                managed_intent_id=managed_intent_id,
                request_id=request_id,
                identity=identity,
                native_result=result,
                evidence=evidence,
                order_ref=order_ref,
            )
        finally:
            self._clear_pending_sdk_intent()

    def _build_action_field(self, snapshot: CtpSimulationOrderSnapshot, request_id: int) -> Any:
        field = self._new_action_field()
        for name, value in {
            "BrokerID": self.config.broker_id,
            "InvestorID": self.config.user_id,
            "InstrumentID": snapshot.instrument_id,
            "ExchangeID": snapshot.exchange_id,
            "ActionFlag": "0",
            "OrderSysID": snapshot.order_sys_id,
            "OrderRef": self._require_native_ref(snapshot.order_ref),
            "FrontID": snapshot.front_id,
            "SessionID": snapshot.session_id,
            "RequestID": request_id,
            "OrderActionRef": request_id,
        }.items():
            setattr(field, name, value)
        return field

    def submit_order_action(
        self, snapshot: CtpSimulationOrderSnapshot, action_id: str
    ) -> CtpSimulationDispatchReceipt:
        self._require_write()
        if type(snapshot) is not CtpSimulationOrderSnapshot:
            _reject("native_cancel_order_snapshot_invalid")
        if not isinstance(action_id, str) or not action_id or action_id != action_id.strip():
            _reject("native_cancel_action_id_invalid")
        if action_id in self._actions:
            _reject("native_cancel_action_id_reused")
        if self._staged_write is None:
            _reject("native_managed_write_not_authorized")
        request = self._staged_write[0]
        if (
            request.action != "CANCEL"
            or request.client_order_id != snapshot.client_order_id
            or request.instrument_id != snapshot.instrument_id
            or request.exchange_id != snapshot.exchange_id
            or request.side != snapshot.side
            or request.quantity != snapshot.quantity
            or request.limit_price != snapshot.limit_price
            or request.target_order_sys_id != snapshot.order_sys_id
            or request.target_order_ref != snapshot.order_ref
            or request.target_front_id != snapshot.front_id
            or request.target_session_id != snapshot.session_id
        ):
            _reject("native_cancel_request_target_mismatch")
        approval, credential_binding = self._require_staged_write(request, action_id=action_id)
        identity = self.get_execution_identity()
        binding = self._resolve_runtime_order_binding(
            snapshot.client_order_id,
            reserve=False,
            expected_identity=identity,
        )
        bound_order_ref = self._require_native_ref(_text(binding.get("ctp_order_ref")))
        client_order_id = _text(binding.get("client_order_id"))
        if (client_order_id and client_order_id != bound_order_ref) or self._require_native_ref(
            snapshot.order_ref
        ) != bound_order_ref:
            _reject("durable_runtime_order_reference_mismatch")
        managed_intent_id = self._managed_intent_id(binding)
        request_id = self._request_id()
        field = self._build_action_field(snapshot, request_id)
        self._require_write()
        # Record before calling the native API: an exception may mean CTP saw
        # the request.  The outer durable journal then keeps the order UNKNOWN.
        self._actions[action_id] = (request_id, snapshot)
        submit = getattr(self._trader, "submit_order_action", None)
        if not callable(submit):
            _reject("native_order_action_unavailable")
        self._set_pending_sdk_intent(
            request=request,
            approval=approval,
            binding=credential_binding,
            identity=identity,
            managed_intent_id=managed_intent_id,
            order_ref=bound_order_ref,
            request_id=request_id,
            action_id=action_id,
        )
        try:
            result = submit(
                field,
                request_id,
                execution_capability=self._execution_capability,
                runtime_order_id=snapshot.client_order_id,
                managed_intent_id=managed_intent_id,
                runtime_action_id=action_id,
                managed_cancel_intent_id=action_id,
            )
            if not self._pending_sdk_intent_consumed:
                _reject("native_sdk_write_verifier_not_invoked")
            evidence_getter = getattr(self._trader, "get_order_action_evidence", None)
            try:
                evidence = (
                    evidence_getter(request_id, order_action_ref=request_id)
                    if callable(evidence_getter)
                    else None
                )
            except Exception:
                evidence = None
            return self._dispatch_receipt(
                operation="CANCEL",
                request=request,
                managed_intent_id=managed_intent_id,
                request_id=request_id,
                identity=identity,
                native_result=result,
                evidence=evidence,
                order_ref=bound_order_ref,
                action_id=action_id,
                snapshot=snapshot,
            )
        finally:
            self._clear_pending_sdk_intent()

    def _query(self, name: str, **kwargs: Any) -> tuple[Any, CtpSimulationSessionIdentity]:
        identity = self.get_execution_identity()
        method = getattr(self._trader, name, None)
        if not callable(method):
            _reject("native_query_method_unavailable")
        try:
            result = method(**kwargs)
        except Exception as exc:
            raise CtpSimulationExecutionError("native_query_failed") from exc
        if getattr(
            result, "connection_generation", None
        ) != identity.connection_generation or _text(
            getattr(result, "account_fingerprint", "")
        ) != _text(getattr(self._trader, "_account_fingerprint", "")):
            _reject("native_query_identity_mismatch")
        return result, identity

    def query_orders(self, client_order_id: str) -> CtpSimulationQueryResult:
        result, identity = self._query(
            "query_orders_result",
            instrument_id=self.registration.instrument_id,
            exchange_id=self.registration.exchange_id,
        )
        native_ref = self._resolve_runtime_order_ref(
            client_order_id, reserve=False, expected_identity=identity
        )
        records = tuple(
            self._order_snapshot(row, client_order_id=client_order_id)
            for row in getattr(result, "records", ())
            if _text(_value(row, "OrderRef", "order_ref")) == native_ref
        )
        return CtpSimulationQueryResult(
            bool(getattr(result, "complete", False)), identity, records, native_evidence=result
        )

    def query_trades(self, client_order_id: str) -> CtpSimulationQueryResult:
        result, identity = self._query(
            "query_trades_result",
            instrument_id=self.registration.instrument_id,
            exchange_id=self.registration.exchange_id,
        )
        native_ref = self._resolve_runtime_order_ref(
            client_order_id, reserve=False, expected_identity=identity
        )
        records = tuple(
            CtpSimulationTradeSnapshot(
                client_order_id=client_order_id,
                trade_id=_text(_value(row, "TradeID", "trade_id")),
                quantity=_int_field(row, "Volume", "quantity"),
                instrument_id=_text(_value(row, "InstrumentID", "instrument_id")),
                exchange_id=_text(_value(row, "ExchangeID", "exchange_id")),
                side=_SIDE_BY_DIRECTION.get(_text(_value(row, "Direction", "direction")), ""),
            )
            for row in getattr(result, "records", ())
            if _text(_value(row, "OrderRef", "order_ref")) == native_ref
        )
        return CtpSimulationQueryResult(
            bool(getattr(result, "complete", False)), identity, records, native_evidence=result
        )

    def query_positions(self, instrument_id: str, exchange_id: str) -> CtpSimulationQueryResult:
        if (instrument_id, exchange_id) != (
            self.registration.instrument_id,
            self.registration.exchange_id,
        ):
            _reject("native_position_query_scope_invalid")
        result, identity = self._query("query_positions_result")
        totals = {"BUY": 0, "SELL": 0}
        for row in getattr(result, "records", ()):
            if (
                _text(_value(row, "InstrumentID", "instrument_id")) != instrument_id
                or _text(_value(row, "ExchangeID", "exchange_id")) != exchange_id
            ):
                continue
            if _text(_value(row, "HedgeFlag", "hedge_flag")) != self.registration.hedge_flag:
                _reject("native_position_hedge_scope_mismatch")
            direction = _text(_value(row, "PosiDirection", "position_direction"))
            side = {"2": "BUY", "3": "SELL"}.get(direction)
            if side is None:
                _reject("native_position_direction_unproven")
            totals[side] += _int_field(row, "Position", "quantity")
        records = tuple(
            CtpSimulationPositionSnapshot(instrument_id, exchange_id, side, quantity)
            for side, quantity in totals.items()
        )
        return CtpSimulationQueryResult(
            bool(getattr(result, "complete", False)), identity, records, native_evidence=result
        )

    def query_account_open_orders(self) -> CtpSimulationQueryResult:
        result, identity = self._query("query_orders_result")
        snapshots = tuple(
            self._order_snapshot(row)
            for row in getattr(result, "records", ())
            if self._is_open(row)
        )
        return CtpSimulationQueryResult(
            bool(getattr(result, "complete", False)), identity, snapshots, native_evidence=result
        )

    def query_cancel_requests(self, action_ids: tuple[str, ...]) -> CtpSimulationQueryResult:
        """Resolve in-process action callbacks; never guess after restart.

        CTP exposes callback evidence for one request in the live TraderClient,
        but no durable native action-query endpoint.  If the adapter has no
        local correlation for any requested action, return incomplete evidence
        so the outer journal keeps the order UNKNOWN.
        """
        identity = self.get_execution_identity()
        if not action_ids or any(action_id not in self._actions for action_id in action_ids):
            return CtpSimulationQueryResult(False, identity, ())
        records = []
        evidence_bundle = []
        for action_id in action_ids:
            request_id, snapshot = self._actions[action_id]
            try:
                evidence = self._trader.get_order_action_evidence(
                    request_id, order_action_ref=request_id
                )
            except Exception:
                evidence = None
            evidence_bundle.append(evidence)
            status = "UNKNOWN"
            if self._action_evidence_matches(evidence, request_id, snapshot, identity):
                callback_status = _text(_value(evidence, "status")).lower()
                if callback_status == "rejected":
                    status = "REJECTED"
                elif callback_status == "accepted":
                    try:
                        latest, _ = self._query(
                            "query_orders_result",
                            instrument_id=snapshot.instrument_id,
                            exchange_id=snapshot.exchange_id,
                            order_sys_id=snapshot.order_sys_id,
                        )
                        evidence_bundle.append(latest)
                        latest_rows = tuple(getattr(latest, "records", ()))
                        exact_target = (
                            len(latest_rows) == 1
                            and _text(_value(latest_rows[0], "OrderRef", "order_ref"))
                            == snapshot.order_ref
                            and _text(_value(latest_rows[0], "OrderSysID", "order_sys_id"))
                            == snapshot.order_sys_id
                            and _text(_value(latest_rows[0], "InstrumentID", "instrument_id"))
                            == snapshot.instrument_id
                            and _text(_value(latest_rows[0], "ExchangeID", "exchange_id"))
                            == snapshot.exchange_id
                        )
                        if getattr(latest, "complete", False) is True and exact_target:
                            latest_snapshot = self._order_snapshot(latest_rows[0])
                            status = (
                                "CANCELED" if latest_snapshot.status == "CANCELED" else "PENDING"
                            )
                    except CtpSimulationExecutionError:
                        status = "UNKNOWN"
            records.append(
                CtpSimulationCancelRequestSnapshot(
                    action_id=action_id,
                    client_order_id=snapshot.client_order_id,
                    target_order_sys_id=snapshot.order_sys_id,
                    target_order_ref=snapshot.order_ref,
                    target_front_id=snapshot.front_id,
                    target_session_id=snapshot.session_id,
                    status=status,
                )
            )
        complete = all(record.status in {"CANCELED", "REJECTED"} for record in records)
        return CtpSimulationQueryResult(
            complete,
            identity,
            tuple(records),
            native_evidence=tuple(evidence_bundle),
        )

    def _action_evidence_matches(
        self,
        evidence: Any,
        request_id: int,
        snapshot: CtpSimulationOrderSnapshot,
        identity: CtpSimulationSessionIdentity,
    ) -> bool:
        if evidence is None:
            return False
        account = _text(_value(evidence, "account_fingerprint"))
        if account.startswith("acct_"):
            account = account[5:]
        return bool(
            type(_value(evidence, "request_id")) is int
            and _value(evidence, "request_id") == request_id
            and _text(_value(evidence, "order_action_ref")) == str(request_id)
            and _value(evidence, "callback_received") is True
            and _value(evidence, "evidence_received") is True
            and account == _text(getattr(self._trader, "_account_fingerprint", ""))
            and _value(evidence, "connection_generation") == identity.connection_generation
            and _text(_value(evidence, "trading_day")) == identity.trading_day
            and _text(_value(evidence, "order_ref")) == snapshot.order_ref
            and _text(_value(evidence, "order_sys_id")) == snapshot.order_sys_id
            and _int_field(evidence, "front_id", required=False) == snapshot.front_id
            and _int_field(evidence, "session_id", required=False) == snapshot.session_id
            and _text(_value(evidence, "instrument_id")) == snapshot.instrument_id
            and _text(_value(evidence, "exchange_id")) == snapshot.exchange_id
            and _text(_value(evidence, "action_flag")) == "0"
        )

    @staticmethod
    def _is_open(row: Any) -> bool:
        status = _text(_value(row, "OrderStatus", "order_status")).lower()
        if status in {"0", "2", "4", "5"}:
            return False
        if status not in {"1", "3", "a", "b", "c"}:
            _reject("native_order_status_unproven")
        return True

    @classmethod
    def _order_snapshot(
        cls, row: Any, *, client_order_id: str | None = None
    ) -> CtpSimulationOrderSnapshot:
        order_ref = _text(_value(row, "OrderRef", "order_ref"))
        submit_status = _text(_value(row, "OrderSubmitStatus", "order_submit_status"))
        raw_status = _text(_value(row, "OrderStatus", "order_status")).lower()
        traded = _int_field(row, "VolumeTraded", "traded_quantity", required=False)
        quantity = _int_field(row, "VolumeTotalOriginal", "quantity")
        if submit_status == "4":
            status = "REJECTED"
        elif raw_status == "0":
            status = "FILLED"
        elif raw_status in {"1", "3"}:
            status = "PARTIAL" if traded else "OPEN"
        elif raw_status in {"2", "4", "5"}:
            status = "CANCELED"
        else:
            _reject("native_order_status_unproven")
        return CtpSimulationOrderSnapshot(
            client_order_id=client_order_id or order_ref,
            instrument_id=_text(_value(row, "InstrumentID", "instrument_id")),
            exchange_id=_text(_value(row, "ExchangeID", "exchange_id")),
            side=_SIDE_BY_DIRECTION.get(_text(_value(row, "Direction", "side")), ""),
            quantity=quantity,
            limit_price=_decimal_field(row, "LimitPrice", "limit_price"),
            traded_quantity=traded,
            status=status,
            order_ref=order_ref,
            order_sys_id=_text(_value(row, "OrderSysID", "order_sys_id")),
            front_id=_int_field(row, "FrontID", "front_id"),
            session_id=_int_field(row, "SessionID", "session_id"),
        )

    def close(self) -> None:
        """Require a complete bounded SDK receipt before reporting close."""
        with self._write_lock:
            if self._closed:
                if self._close_failed:
                    _reject("native_session_close_failed")
                return
            self._closed = True
            self._close_failed = not stop_ctp_native_client(self._trader)
            if self._close_failed:
                _reject("native_session_close_failed")


def create_ctp_trader_client_simulation_port(
    registration: CtpSimulationExecutionRegistration,
    config: CtpSimulationTraderConfig,
    *,
    trader_client_factory: Callable[..., Any] | None = None,
    execution_capability: object | None = None,
    runtime_admission_check: Callable[[], bool] | None = None,
    runtime_order_binding: Callable[[str, bool], Mapping[str, Any]] | None = None,
    runtime_credential_binding: Any | None = None,
    runtime_credential_binding_factory: Callable[..., Any] | None = None,
    runtime_approval_verifier: Any | None = None,
    sdk_approval_rechecker: Callable[[Any, Mapping[str, Any]], bool] | None = None,
    order_field_factory: Callable[[], Any] | None = None,
    action_field_factory: Callable[[], Any] | None = None,
) -> CtpTraderClientSimulationPort:
    """Construct, but do not start, a client against the exact sealed front.

    The injected factory seam is used by offline tests.  The production
    default imports only ``TraderClient`` after the code-owned profile/front
    contract passes; it performs no connection or provider request.
    """
    config.validate(registration)
    factory = trader_client_factory
    if factory is None:
        try:
            from bt_api_ctp.ctp.client import TraderClient

            factory = TraderClient
        except Exception as exc:
            raise CtpSimulationExecutionError("native_trader_client_unavailable") from exc
    try:
        trader = factory(
            config.td_front,
            config.broker_id,
            config.user_id,
            config.password,
            app_id=config.app_id,
            auth_code=config.auth_code,
            md_front=config.md_front,
            ctp_env_profile=_SIMNOW_SDK_PROFILE,
            auto_settlement_confirm=False,
        )
    except Exception as exc:
        raise CtpSimulationExecutionError("native_trader_client_construction_failed") from exc
    return CtpTraderClientSimulationPort(
        trader,
        registration,
        config,
        execution_capability=execution_capability,
        runtime_admission_check=runtime_admission_check,
        runtime_order_binding=runtime_order_binding,
        runtime_credential_binding=runtime_credential_binding,
        runtime_credential_binding_factory=runtime_credential_binding_factory,
        runtime_approval_verifier=runtime_approval_verifier,
        sdk_approval_rechecker=sdk_approval_rechecker,
        order_field_factory=order_field_factory,
        action_field_factory=action_field_factory,
    )


__all__ = [
    "CtpSimulationTraderConfig",
    "CtpTraderClientSimulationPort",
    "create_ctp_trader_client_simulation_port",
]
