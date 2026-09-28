"""Offline contract tests for the opt-in, exact-front TraderClient port."""

from __future__ import annotations

import hashlib
import hmac
import time
from contextlib import nullcontext
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from types import SimpleNamespace
from typing import Any

import pytest

from backtrader_runtime import RegisteredRuntime, load_runtime_config
from backtrader_runtime.ctp_simulation_execution import (
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    CtpSimulationDispatchReceipt,
    CtpSimulationOrderSnapshot,
    CtpSimulationQueryResult,
    CtpSimulationWriteApproval,
    CtpSimulationWriteRequest,
    HmacCtpSimulationApprovalVerifier,
    open_ctp_simulation_execution,
)
from backtrader_runtime.registry import RuntimeRegistry, resolve_runtime_config
import backtrader_runtime.config as runtime_config_module
import backtrader_runtime.ctp_trader_client_port as ctp_port_module
import backtrader_runtime.ctp_simulation_execution as execution_module
import backtrader_runtime.ctp_simnow_managed_composition as managed_composition_module
import backtrader_runtime.ctp_native_shutdown as ctp_native_shutdown_module
from backtrader_runtime.ctp_artifact_provenance import CtpArtifactProvenanceError
from backtrader_runtime.ctp_trader_client_port import (
    CtpSimulationTraderConfig,
    create_ctp_trader_client_simulation_port,
)
from backtrader_runtime.ctp_simnow_managed_composition import (
    create_sealed_ctp_simnow_managed_port,
    resolve_sealed_ctp_simnow_trader_config,
)


TD_FRONT = "tcp://simnow.invalid:10001"
MD_FRONT = "tcp://simnow.invalid:10002"
BROKER = "9999"
USER = "offline-user"
PROFILE = "config_front_pair"
CUSTOM_TD_FRONT = "tcp://custom-trade.invalid:20001"
CUSTOM_MD_FRONT = "tcp://custom-market.invalid:20002"
_FRONTS = (TD_FRONT, MD_FRONT)
MANAGED_ORDER_ID = "bt-managed-v1:" + "a" * 64
_TEST_APPROVAL_KEY_ID = "offline-key"
_TEST_APPROVAL_KEY = b"offline-managed-simnow-approval-key-32-bytes"


ACCOUNT_FP = hashlib.sha256(f"{BROKER}:{USER}".encode()).hexdigest()[:16]
ACCOUNT_DIGEST = hashlib.sha256(("acct_" + ACCOUNT_FP).encode()).hexdigest()
RECEIPT = "a" * 64
SECRET_REF = "os_secret_store:offline.ctp"


def _registration(fronts=_FRONTS) -> CtpSimulationExecutionRegistration:
    runtime = RegisteredRuntime(
        runtime_dir="offline-runtime",
        runtime_id="offline.ctp.simnow",
        strategy_id="offline.ctp.simnow",
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=(SECRET_REF,),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest=RECEIPT,
    )
    return CtpSimulationExecutionRegistration(
        runtime_registration=runtime,
        environment="simnow",
        sdk_profile=PROFILE,
        td_front=fronts[0],
        md_front=fronts[1],
        account_fingerprint_sha256=ACCOUNT_DIGEST,
        allowed_secrets_ref=SECRET_REF,
        instrument_id="rb2701",
        exchange_id="SHFE",
        hedge_flag="1",
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=3,
        max_gross_position=3,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("0.5"),
        approval_key_id="offline-key",
    )


def _config(**overrides: Any) -> CtpSimulationTraderConfig:
    values = {
        "td_front": TD_FRONT,
        "md_front": MD_FRONT,
        "broker_id": BROKER,
        "user_id": USER,
        "password": "offline-password",
        "auth_code": "offline-auth",
        "app_id": "offline-app",
        "auto_detect_fronts": False,
    }
    values.update(overrides)
    return CtpSimulationTraderConfig(**values)


@pytest.fixture(autouse=True)
def _install_exact_fake_sdk_types(monkeypatch):
    """Exercise the typed port contract without importing the provider SDK."""

    monkeypatch.setattr(ctp_port_module, "_sdk_trader_client_type", lambda: _FakeTraderClient)
    monkeypatch.setattr(ctp_port_module, "_sdk_simnow_binding_type", lambda: _FakeSdkBinding)
    monkeypatch.setattr(
        ctp_native_shutdown_module, "_native_stop_receipt_type", lambda: _FakeStopReceipt
    )


@dataclass(frozen=True)
class _FakeStopReceipt:
    connection_generation: int
    join_required: bool = False
    join_completed: bool = True
    native_released: bool = True
    thread_alive: bool = False
    timed_out: bool = False

    @property
    def complete(self) -> bool:
        return (
            self.native_released
            and (not self.join_required or self.join_completed)
            and self.thread_alive is False
            and self.timed_out is False
        )


@dataclass(frozen=True)
class _FakeSdkApproval:
    approval_id: str
    nonce: str
    payload_sha256: str


@dataclass(frozen=True)
class _FakeSdkBinding:
    td_front: str
    md_front: str
    environment_profile: str
    operation: str
    action_id: str | None
    approval: _FakeSdkApproval
    write_intent_verifier: Any


class _FakeTraderClient:
    def __init__(self, profile=PROFILE, fronts=None) -> None:
        self.profile = profile
        self.ctp_env_profile = profile
        self._bound_front = (fronts or _FRONTS)[0]
        self._bound_md_front = (fronts or _FRONTS)[1]
        self._bound_broker_id = BROKER
        self._bound_user_id = USER
        self._account_fingerprint = ACCOUNT_FP
        self.auto_settlement_confirm = False
        self.gate_armed = False
        self.trading_ready = True
        self.trading_day = "20260923"
        self.connection_generation = 8
        self._trading_day = self.trading_day
        self._connection_generation = self.connection_generation
        self._execution_gate_capability = None
        self._runtime_simnow_credential_binding = None
        self._native_api = object()
        self.request_id = 0
        self.insert_calls: list[tuple[Any, int, object]] = []
        self.action_calls: list[tuple[Any, int, object]] = []
        self.order_rows: tuple[dict[str, Any], ...] = ()
        self.trade_rows: tuple[dict[str, Any], ...] = ()
        self.position_rows: tuple[dict[str, Any], ...] = ()
        self.cancel_evidence: dict[tuple[int, str], Any] = {}
        self.insert_evidence: dict[tuple[int, str], Any] = {}
        self.insert_submit_code = 0
        self.action_submit_code = 0
        self.insert_evidence_overrides: dict[str, Any] = {}
        self.action_evidence_overrides: dict[str, Any] = {}
        self.stop_calls = 0
        self.stop_receipt: Any = None
        self.credential_bindings: list[tuple[object, object]] = []

    def configure_execution_gate(self, capability):
        if capability is None:
            raise ValueError("capability required")
        if self._execution_gate_capability not in (None, capability):
            raise ValueError("capability mismatch")
        self._execution_gate_capability = capability
        return self.get_execution_gate_state()

    def configure_runtime_simnow_credential_binding(self, capability, binding):
        if (
            capability is not self._execution_gate_capability
            or self.gate_armed
            or type(binding) is not _FakeSdkBinding
        ):
            raise ValueError("typed binding/capability rejected")
        self.credential_bindings.append((capability, binding))
        self._runtime_simnow_credential_binding = binding
        return {
            "configured": True,
            "environment_profile": self.profile,
            "connection_generation": self.connection_generation,
        }

    def get_query_session_scope(self):
        return SimpleNamespace(
            account_fingerprint=self._account_fingerprint,
            trading_day=self.trading_day,
            connection_generation=self.connection_generation,
            read_only_ready=True,
        )

    def get_execution_gate_state(self):
        return {
            "armed": self.gate_armed,
            "environment_profile": self.profile,
            "connection_generation": self.connection_generation,
            "runtime_simnow_credential_binding_configured": (
                self._runtime_simnow_credential_binding is not None
            ),
            "runtime_simnow_write_verifier_configured": (
                self._runtime_simnow_credential_binding is not None
                and callable(self._runtime_simnow_credential_binding.write_intent_verifier)
            ),
        }

    def get_session_state(self):
        return {
            "read_only_ready": True,
            "trading_ready": self.trading_ready,
            "auto_settlement_confirm": False,
        }

    def _bound_identity_is_current(self, *, require_active_front=False):
        return require_active_front

    def _next_request_id(self):
        self.request_id += 1
        return self.request_id

    def submit_order_insert(self, field, request_id, **kwargs):
        binding = self._runtime_simnow_credential_binding
        if binding.operation != "insert" or binding.action_id is not None:
            raise ValueError("insert requires entry approval")
        approval = binding.approval
        scope = MappingProxyType(
            {
                "schema_version": "ctp-simnow-managed-write-v1",
                "operation": "insert",
                "td_front": binding.td_front,
                "md_front": binding.md_front,
                "environment_profile": binding.environment_profile,
                "account_fingerprint": "acct_" + self._account_fingerprint,
                "trading_day": self.trading_day,
                "connection_generation": self.connection_generation,
                "instrument_id": field.InstrumentID,
                "exchange_id": field.ExchangeID,
                "runtime_order_id": kwargs["runtime_order_id"],
                "managed_intent_id": kwargs["managed_intent_id"],
                "runtime_action_id": None,
                "managed_cancel_intent_id": None,
                "request_id": request_id,
                "approval_id": approval.approval_id,
                "approval_nonce": approval.nonce,
                "approval_payload_sha256": approval.payload_sha256,
                "order_ref": field.OrderRef,
                "direction": field.Direction,
                "offset_flag": field.CombOffsetFlag,
                "hedge_flag": field.CombHedgeFlag,
                "volume_total_original": field.VolumeTotalOriginal,
                "limit_price": format(Decimal(str(field.LimitPrice)).normalize(), "f"),
                "order_price_type": field.OrderPriceType,
                "time_condition": field.TimeCondition,
                "volume_condition": field.VolumeCondition,
            }
        )
        if binding.write_intent_verifier(scope) is not True:
            raise ValueError("write intent rejected")
        self.insert_calls.append((field, request_id, kwargs))
        evidence = {
            "request_id": request_id,
            "order_ref": field.OrderRef,
            "status": "unknown",
            "account_fingerprint": "acct_" + self._account_fingerprint,
            "trading_day": self.trading_day,
            "connection_generation": self.connection_generation,
            "instrument_id": field.InstrumentID,
            "exchange_id": field.ExchangeID,
            "callback_received": False,
            "evidence_received": False,
            "submit_code": self.insert_submit_code,
        }
        evidence.update(self.insert_evidence_overrides)
        self.insert_evidence[(request_id, field.OrderRef)] = SimpleNamespace(**evidence)
        return self.insert_submit_code

    def submit_order_action(self, field, request_id, **kwargs):
        binding = self._runtime_simnow_credential_binding
        if (
            binding.operation != "cancel"
            or binding.action_id != kwargs.get("runtime_action_id")
            or binding.action_id != kwargs.get("managed_cancel_intent_id")
        ):
            raise ValueError("cancel requires exact recovery approval")
        approval = binding.approval
        scope = MappingProxyType(
            {
                "schema_version": "ctp-simnow-managed-write-v1",
                "operation": "cancel",
                "td_front": binding.td_front,
                "md_front": binding.md_front,
                "environment_profile": binding.environment_profile,
                "account_fingerprint": "acct_" + self._account_fingerprint,
                "trading_day": self.trading_day,
                "connection_generation": self.connection_generation,
                "instrument_id": field.InstrumentID,
                "exchange_id": field.ExchangeID,
                "runtime_order_id": kwargs["runtime_order_id"],
                "managed_intent_id": kwargs["managed_intent_id"],
                "runtime_action_id": kwargs["runtime_action_id"],
                "managed_cancel_intent_id": kwargs["managed_cancel_intent_id"],
                "request_id": request_id,
                "approval_id": approval.approval_id,
                "approval_nonce": approval.nonce,
                "approval_payload_sha256": approval.payload_sha256,
                "order_action_ref": field.OrderActionRef,
                "action_flag": field.ActionFlag,
                "target_order_ref": field.OrderRef,
                "target_front_id": field.FrontID,
                "target_session_id": field.SessionID,
                "target_order_sys_id": field.OrderSysID,
            }
        )
        if binding.write_intent_verifier(scope) is not True:
            raise ValueError("write intent rejected")
        self.action_calls.append((field, request_id, kwargs))
        evidence = {
            "request_id": request_id,
            "order_action_ref": str(field.OrderActionRef),
            "status": "unknown",
            "account_fingerprint": "acct_" + self._account_fingerprint,
            "trading_day": self.trading_day,
            "connection_generation": self.connection_generation,
            "order_ref": field.OrderRef,
            "order_sys_id": field.OrderSysID,
            "front_id": field.FrontID,
            "session_id": field.SessionID,
            "instrument_id": field.InstrumentID,
            "exchange_id": field.ExchangeID,
            "action_flag": field.ActionFlag,
            "callback_received": False,
            "evidence_received": False,
            "submit_code": self.action_submit_code,
        }
        evidence.update(self.action_evidence_overrides)
        self.cancel_evidence[(request_id, str(field.OrderActionRef))] = SimpleNamespace(**evidence)
        return self.action_submit_code

    def get_order_insert_evidence(self, request_id, *, order_ref=None):
        return self.insert_evidence.get((request_id, str(order_ref)))

    def get_order_action_evidence(self, request_id, *, order_action_ref=None):
        return self.cancel_evidence.get((request_id, str(order_action_ref)))

    def query_orders_result(self, **_kwargs):
        return _query_result("orders", self, self.order_rows)

    def query_trades_result(self, **_kwargs):
        return _query_result("trades", self, self.trade_rows)

    def query_positions_result(self, **_kwargs):
        return _query_result("positions", self, self.position_rows)

    def stop(self):
        self.stop_calls += 1

    def stop_and_wait(self, *, timeout):
        assert timeout > 0
        self.stop_calls += 1
        if self.stop_receipt is not None:
            return self.stop_receipt
        return _FakeStopReceipt(self.connection_generation)


def _query_result(request_type, client, records):
    return SimpleNamespace(
        request_type=request_type,
        complete=True,
        account_fingerprint=client._account_fingerprint,
        connection_generation=client.connection_generation,
        records=records,
        query_source=object(),
    )


class _Field:
    pass


def _port(
    client=None,
    *,
    capability=None,
    runtime_admission_check=None,
    bind_runtime_order=True,
    bind_managed_intent=True,
    bound_order_ref="000000000123",
    bound_client_order_id="000000000123",
    binding_overrides=None,
    omit_binding_fields=(),
    config=None,
    factory_calls=None,
):
    fronts = (config.td_front, config.md_front) if config is not None else _FRONTS
    client = client or _FakeTraderClient(PROFILE, fronts)
    calls = factory_calls if factory_calls is not None else []

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        return client

    def binding(runtime_order_id, reserve):
        result = {
            "runtime_order_id": runtime_order_id,
            "client_order_id": bound_client_order_id,
            "ctp_order_ref": bound_order_ref,
            "connection_generation": client.connection_generation,
            "trading_day": client.trading_day,
            "reserved": reserve,
        }
        result.update(binding_overrides or {})
        for name in omit_binding_fields:
            result.pop(name, None)
        if bind_managed_intent:
            result["managed_intent_id"] = "intent-offline-1"
        return result

    def credential_binding_factory(
        *, operation, request, runtime_approval, action_id, identity, write_intent_verifier
    ):
        sdk_approval = _FakeSdkApproval(
            approval_id="sdk-" + runtime_approval.approval_id,
            nonce="nonce-" + (action_id or "entry"),
            payload_sha256=hashlib.sha256(
                (runtime_approval.request_digest + ":" + (action_id or "entry")).encode()
            ).hexdigest(),
        )
        return _FakeSdkBinding(
            td_front=fronts[0],
            md_front=fronts[1],
            environment_profile=PROFILE,
            operation=operation,
            action_id=action_id,
            approval=sdk_approval,
            write_intent_verifier=write_intent_verifier,
        )

    port = create_ctp_trader_client_simulation_port(
        _registration(fronts),
        config or _config(td_front=fronts[0], md_front=fronts[1]),
        trader_client_factory=factory,
        execution_capability=capability,
        runtime_admission_check=runtime_admission_check,
        runtime_order_binding=binding if bind_runtime_order else None,
        runtime_credential_binding_factory=credential_binding_factory,
        runtime_approval_verifier=HmacCtpSimulationApprovalVerifier(
            _TEST_APPROVAL_KEY_ID, _TEST_APPROVAL_KEY
        ),
        sdk_approval_rechecker=lambda _binding, _scope: True,
        order_field_factory=_Field,
        action_field_factory=_Field,
    )
    return port, client, calls


def _signed_approval(
    port,
    request: CtpSimulationWriteRequest,
    *,
    approval_id="offline-approval-1",
):
    registration = port.registration
    issued_at = time.time()
    unsigned = CtpSimulationWriteApproval(
        approval_id=approval_id,
        key_id=registration.approval_key_id,
        registration_digest=registration.digest,
        receipt_digest=registration.runtime_registration.approval_receipt_digest,
        account_fingerprint_sha256=registration.account_fingerprint_sha256,
        environment=registration.environment,
        td_front=registration.td_front,
        md_front=registration.md_front,
        request_digest=request.digest,
        issued_at=issued_at,
        expires_at=issued_at + registration.approval_ttl_seconds,
        signature_hex="0" * 64,
    )
    signature = hmac.new(_TEST_APPROVAL_KEY, unsigned.signed_payload(), hashlib.sha256).hexdigest()
    return replace(unsigned, signature_hex=signature)


def _cancel_request(snapshot: CtpSimulationOrderSnapshot) -> CtpSimulationWriteRequest:
    return CtpSimulationWriteRequest(
        action="CANCEL",
        client_order_id=snapshot.client_order_id,
        instrument_id=snapshot.instrument_id,
        exchange_id=snapshot.exchange_id,
        side=snapshot.side,
        quantity=snapshot.quantity,
        limit_price=snapshot.limit_price,
        offset="OPEN",
        hedge_flag="1",
        target_order_sys_id=snapshot.order_sys_id,
        target_order_ref=snapshot.order_ref,
        target_front_id=snapshot.front_id,
        target_session_id=snapshot.session_id,
    )


def _order_row(*, order_status="3", traded=0):
    return {
        "InstrumentID": "rb2701",
        "ExchangeID": "SHFE",
        "OrderRef": "000000000123",
        "OrderSysID": "sys-order-8",
        "FrontID": 17,
        "SessionID": 19,
        "OrderStatus": order_status,
        "OrderSubmitStatus": "3",
        "Direction": "0",
        "LimitPrice": 125.5,
        "VolumeTotalOriginal": 2,
        "VolumeTraded": traded,
        "TradingDay": "20260923",
    }


def test_registered_configured_front_pair_is_required_before_client_construction():
    custom_fronts = ("tcp://custom-trade.invalid:12001", "tcp://custom-market.invalid:12002")
    custom_config = _config(td_front=custom_fronts[0], md_front=custom_fronts[1])
    port, client, calls = _port(config=custom_config)
    assert port.registration.td_front == custom_fronts[0]
    assert port.registration.md_front == custom_fronts[1]
    assert port.profile == PROFILE
    assert client._bound_front == custom_fronts[0]
    assert client._bound_md_front == custom_fronts[1]

    with pytest.raises(CtpSimulationExecutionError, match="front pair registration mismatch"):
        custom_config.validate(_registration())

    port, client, calls = _port()
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (TD_FRONT, BROKER, USER, "offline-password")
    assert kwargs == {
        "app_id": "offline-app",
        "auth_code": "offline-auth",
        "md_front": MD_FRONT,
        "ctp_env_profile": PROFILE,
        "auto_settlement_confirm": False,
    }
    assert client.stop_calls == 0
    assert port.write_admitted is False
    feed_kwargs = port.config.feed_kwargs(_registration())
    assert feed_kwargs["auto_detect_fronts"] is False
    assert feed_kwargs["ctp_env_profile"] == PROFILE
    assert "offline-password" not in repr(port.config)


def test_feed_factory_receives_all_sealed_values_and_is_checked_before_connect():
    config = _config()
    calls = []
    registration = _registration()

    def feed_factory(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            ctp_env_profile=PROFILE,
            ctp_env_readiness="explicit_config_pair",
            td_front=TD_FRONT,
            md_front=MD_FRONT,
            _execution_bound_profile=PROFILE,
            _execution_bound_td_front=TD_FRONT,
            _execution_bound_md_front=MD_FRONT,
            _execution_bound_broker_id=BROKER,
            _execution_bound_user_id=USER,
            auto_settlement_confirm=False,
            _trader=None,
        )

    feed = config.create_verified_feed(feed_factory, registration)
    assert feed._trader is None
    assert calls[0]["td_front"] == TD_FRONT and calls[0]["md_front"] == MD_FRONT
    assert calls[0]["ctp_env_profile"] == PROFILE
    assert calls[0]["auto_detect_fronts"] is False
    assert calls[0]["password"] == "offline-password"

    feed.md_front = "tcp://substituted.invalid:9"
    with pytest.raises(CtpSimulationExecutionError, match="resolved ctp feed binding mismatch"):
        config.assert_resolved_feed(feed, registration)


def test_sdk_gate_capability_controls_fake_submit_and_native_ctp_fields():
    capability = object()
    port, client, _ = _port(capability=capability)
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="SELL",
        quantity=2,
        limit_price=Decimal("125.5"),
        offset="OPEN",
        hedge_flag="1",
    )

    assert port.write_admitted is False
    with pytest.raises(CtpSimulationExecutionError, match="gate not admitted"):
        port.submit_order_insert(request)
    assert client.insert_calls == []

    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
    )
    assert port.write_admitted is False
    with pytest.raises(CtpSimulationExecutionError, match="gate not admitted"):
        port.submit_order_insert(request)
    port.authorize_write(request, _signed_approval(port, request))
    assert port.write_admitted is True
    receipt = port.submit_order_insert(request)
    assert receipt.outcome == "QUEUED" and receipt.submit_code == 0
    native, request_id, native_kwargs = client.insert_calls[0]
    assert native_kwargs["execution_capability"] is capability
    assert native_kwargs["runtime_order_id"] == MANAGED_ORDER_ID
    assert native_kwargs["managed_intent_id"] == "intent-offline-1"
    assert request_id == native.RequestID == 1
    assert native.BrokerID == BROKER and native.InvestorID == USER
    assert native.InstrumentID == "rb2701" and native.ExchangeID == "SHFE"
    assert native.OrderRef == "000000000123"
    assert native.Direction == "1" and native.CombOffsetFlag == "0"
    assert native.CombHedgeFlag == "1"
    assert native.LimitPrice == 125.5 and native.VolumeTotalOriginal == 2

    # A retained credential binding is only a verifier handle; it cannot be
    # replayed to create a second order without another reserved approval.
    with pytest.raises(CtpSimulationExecutionError, match="not authorized"):
        port.submit_order_insert(request)

    client.gate_armed = True
    assert port.write_admitted is False
    with pytest.raises(CtpSimulationExecutionError, match="gate not admitted"):
        port.submit_order_insert(request)
    assert len(client.insert_calls) == 1


def test_direct_runtime_gate_stays_closed_without_typed_credential_binding():
    port, client, _ = _port(
        capability=object(),
        runtime_admission_check=lambda: True,
    )
    assert port.write_admitted is False
    assert client.credential_bindings == []
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
        offset="OPEN",
        hedge_flag="1",
    )
    with pytest.raises(CtpSimulationExecutionError, match="gate not admitted"):
        port.submit_order_insert(request)
    assert client.insert_calls == []


def test_durable_order_binding_has_no_order_ref_fallback_or_intent_omission():
    capability = object()
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
        offset="OPEN",
        hedge_flag="1",
    )
    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
        bound_order_ref="000000000124",
        bound_client_order_id="000000000123",
    )
    port.authorize_write(request, _signed_approval(port, request))
    with pytest.raises(
        CtpSimulationExecutionError,
        match="durable runtime order reference mismatch",
    ):
        port.submit_order_insert(request)
    assert client.insert_calls == []

    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
        bind_managed_intent=False,
    )
    port.authorize_write(request, _signed_approval(port, request))
    with pytest.raises(
        CtpSimulationExecutionError,
        match="durable runtime managed intent binding invalid",
    ):
        port.submit_order_insert(request)
    assert client.insert_calls == []


def test_port_close_requires_complete_exact_stop_receipt_and_is_idempotent() -> None:
    port, client, _calls = _port()

    port.close()
    port.close()

    assert client.stop_calls == 1


def test_port_close_rejects_pending_join_and_does_not_retry() -> None:
    port, client, _calls = _port()
    client.stop_receipt = _FakeStopReceipt(
        connection_generation=8,
        join_required=True,
        join_completed=False,
        native_released=False,
        thread_alive=True,
        timed_out=True,
    )

    for _ in range(2):
        with pytest.raises(CtpSimulationExecutionError) as rejected:
            port.close()
        assert rejected.value.reason == "native_session_close_failed"

    assert client.stop_calls == 1


@pytest.mark.parametrize("missing_method", [False, True])
def test_port_close_rejects_unknown_or_missing_receipt_without_retry(
    missing_method: bool,
) -> None:
    port, client, _calls = _port()
    if missing_method:
        client.stop_and_wait = None
    else:
        client.stop_receipt = SimpleNamespace(complete=True)

    for _ in range(2):
        with pytest.raises(CtpSimulationExecutionError) as rejected:
            port.close()
        assert rejected.value.reason == "native_session_close_failed"

    assert client.stop_calls == (0 if missing_method else 1)


@pytest.mark.parametrize(
    ("binding_overrides", "omit_binding_fields", "reason"),
    (
        ({"reserved": 1}, (), "durable runtime order binding reservation unconfirmed"),
        ({}, ("trading_day",), "durable runtime order binding scope mismatch"),
        ({"trading_day": "20260922"}, (), "durable runtime order binding scope mismatch"),
        ({"connection_generation": True}, (), "durable runtime order binding scope mismatch"),
    ),
)
def test_order_binding_requires_exact_reservation_and_current_session(
    binding_overrides, omit_binding_fields, reason
):
    capability = object()
    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
        binding_overrides=binding_overrides,
        omit_binding_fields=omit_binding_fields,
    )
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
        offset="OPEN",
        hedge_flag="1",
    )
    port.authorize_write(request, _signed_approval(port, request))

    with pytest.raises(CtpSimulationExecutionError, match=reason):
        port.submit_order_insert(request)

    assert client.insert_calls == []


def test_cancel_binding_requires_lookup_receipt_and_current_session_before_native_call():
    port, client, _ = _port(
        capability=object(),
        runtime_admission_check=lambda: True,
        binding_overrides={"reserved": True},
    )
    snapshot = CtpSimulationOrderSnapshot(
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref="000000000123",
        order_sys_id="sys-order-8",
        front_id=17,
        session_id=19,
    )
    request = _cancel_request(snapshot)
    action_id = "cancel-offline-binding-check"
    port.authorize_write(request, _signed_approval(port, request), action_id=action_id)

    with pytest.raises(
        CtpSimulationExecutionError,
        match="durable runtime order binding reservation unconfirmed",
    ):
        port.submit_order_action(snapshot, action_id)

    assert client.action_calls == []


def test_runtime_gate_without_durable_order_reference_binding_stays_closed():
    capability = object()
    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
        bind_runtime_order=False,
    )
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
        offset="OPEN",
        hedge_flag="1",
    )

    assert port.write_admitted is False
    with pytest.raises(CtpSimulationExecutionError, match="gate not admitted"):
        port.submit_order_insert(request)
    assert client.insert_calls == []


def test_custom_configured_pair_has_neutral_scope_and_per_action_write_contract():
    custom_fronts = (CUSTOM_TD_FRONT, CUSTOM_MD_FRONT)
    config = _config(td_front=custom_fronts[0], md_front=custom_fronts[1])
    capability = object()
    port, client, _ = _port(
        config=config,
        capability=capability,
        runtime_admission_check=lambda: True,
    )
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
        offset="OPEN",
        hedge_flag="1",
    )

    identity = port.get_execution_identity()
    assert identity.environment == "simnow"
    assert identity.sdk_profile == PROFILE
    assert identity.td_front == custom_fronts[0]
    assert identity.md_front == custom_fronts[1]
    assert port.write_admitted is False
    client._bound_md_front = MD_FRONT
    with pytest.raises(CtpSimulationExecutionError, match="front pair scope mismatch"):
        port.get_execution_identity()
    client._bound_md_front = custom_fronts[1]
    wrong_front_approval = replace(_signed_approval(port, request), md_front=MD_FRONT)
    with pytest.raises(CtpSimulationExecutionError, match="approval scope mismatch"):
        port.authorize_write(request, wrong_front_approval)
    assert client.insert_calls == []
    port.authorize_write(request, _signed_approval(port, request))
    assert port.write_admitted is True
    receipt = port.submit_order_insert(request)
    assert type(receipt) is CtpSimulationDispatchReceipt
    assert receipt.operation == "SUBMIT" and receipt.outcome == "QUEUED"
    assert receipt.request_id == 1 and receipt.submit_code == 0
    assert receipt.request_digest == request.digest
    assert receipt.client_order_id == MANAGED_ORDER_ID
    assert receipt.managed_intent_id == "intent-offline-1"
    assert receipt.identity == port.get_execution_identity()
    assert receipt.provider_acknowledged is False
    assert len(client.insert_calls) == 1
    binding = client.credential_bindings[0][1]
    assert binding.td_front == custom_fronts[0]
    assert binding.md_front == custom_fronts[1]


def test_read_only_td_identity_never_implies_managed_write_admission():
    capability = object()
    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
    )
    client.trading_ready = False

    identity = port.get_execution_identity()
    assert identity.connection_generation == client.connection_generation
    assert identity.trading_day == client.trading_day
    assert port.write_admitted is False

    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
        offset="OPEN",
        hedge_flag="1",
    )
    with pytest.raises(CtpSimulationExecutionError, match="not trading ready"):
        port.authorize_write(request, _signed_approval(port, request))
    assert client.insert_calls == []
    assert client.credential_bindings == []


def test_native_queries_preserve_query_provenance_and_map_fills_and_positions():
    port, client, _ = _port()
    client.order_rows = (_order_row(order_status="1", traded=1),)
    client.trade_rows = (
        {
            "OrderRef": "000000000123",
            "TradeID": "trade-8",
            "Volume": 1,
            "InstrumentID": "rb2701",
            "ExchangeID": "SHFE",
            "Direction": "0",
        },
    )
    client.position_rows = (
        {
            "InstrumentID": "rb2701",
            "ExchangeID": "SHFE",
            "HedgeFlag": "1",
            "PosiDirection": "2",
            "Position": 4,
        },
        {
            "InstrumentID": "rb2701",
            "ExchangeID": "SHFE",
            "HedgeFlag": "1",
            "PosiDirection": "3",
            "Position": 2,
        },
    )

    order_result = port.query_orders(MANAGED_ORDER_ID)
    trade_result = port.query_trades(MANAGED_ORDER_ID)
    position_result = port.query_positions("rb2701", "SHFE")

    assert order_result.complete and order_result.native_evidence is not None
    assert order_result.records[0].status == "PARTIAL"
    assert order_result.records[0].client_order_id == MANAGED_ORDER_ID
    assert order_result.records[0].traded_quantity == 1
    assert trade_result.records[0].trade_id == "trade-8"
    assert trade_result.records[0].client_order_id == MANAGED_ORDER_ID
    assert trade_result.records[0].side == "BUY"
    assert {(row.side, row.quantity) for row in position_result.records} == {
        ("BUY", 4),
        ("SELL", 2),
    }


def test_cancel_callback_needs_matching_identity_and_order_readback():
    capability = object()
    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
    )
    snapshot = CtpSimulationOrderSnapshot(
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref="000000000123",
        order_sys_id="sys-order-8",
        front_id=17,
        session_id=19,
    )
    cancel = _cancel_request(snapshot)
    port.authorize_write(
        cancel,
        _signed_approval(port, cancel, approval_id="offline-cancel-approval-1"),
        action_id="cancel-attempt-1",
    )
    with pytest.raises(CtpSimulationExecutionError, match="not authorized"):
        port.submit_order_action(snapshot, "cancel-attempt-other")
    assert client.action_calls == []
    receipt = port.submit_order_action(snapshot, "cancel-attempt-1")
    assert type(receipt) is CtpSimulationDispatchReceipt
    assert receipt.operation == "CANCEL" and receipt.outcome == "QUEUED"
    assert receipt.action_id == "cancel-attempt-1"
    assert receipt.request_digest == cancel.digest
    assert receipt.request_id == 1 and receipt.submit_code == 0
    assert receipt.client_order_id == MANAGED_ORDER_ID
    assert receipt.managed_intent_id == "intent-offline-1"
    native, request_id, native_kwargs = client.action_calls[0]
    assert native_kwargs["execution_capability"] is capability
    assert native_kwargs["runtime_order_id"] == MANAGED_ORDER_ID
    assert native_kwargs["managed_intent_id"] == "intent-offline-1"
    assert native_kwargs["runtime_action_id"] == "cancel-attempt-1"
    assert native_kwargs["managed_cancel_intent_id"] == "cancel-attempt-1"
    assert native.ActionFlag == "0"
    assert native.OrderSysID == snapshot.order_sys_id
    assert native.OrderRef == snapshot.order_ref
    assert native.FrontID == 17 and native.SessionID == 19
    assert native.RequestID == native.OrderActionRef == request_id

    client.cancel_evidence[(request_id, str(request_id))] = SimpleNamespace(
        request_id=request_id,
        order_action_ref=str(request_id),
        status="accepted",
        account_fingerprint=ACCOUNT_FP,
        trading_day="20260923",
        connection_generation=8,
        order_ref=snapshot.order_ref,
        order_sys_id=snapshot.order_sys_id,
        front_id=17,
        session_id=19,
        instrument_id="rb2701",
        exchange_id="SHFE",
        action_flag="0",
        callback_received=True,
        evidence_received=True,
    )
    client.order_rows = (_order_row(order_status="5"),)

    result = port.query_cancel_requests(("cancel-attempt-1",))

    assert result.complete is True
    assert result.records[0].status == "CANCELED"
    assert result.native_evidence is not None
    # A fresh port has no callback correlation and must freeze recovery.
    restarted_port, _, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
    )
    restarted = restarted_port.query_cancel_requests(("cancel-attempt-1",))
    assert restarted.complete is False and restarted.records == ()


def test_submit_receipt_is_unknown_when_sdk_record_does_not_match_exact_account():
    port, client, _ = _port(
        capability=object(),
        runtime_admission_check=lambda: True,
    )
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
    )
    port.authorize_write(request, _signed_approval(port, request))
    client.insert_evidence_overrides["account_fingerprint"] = "acct_wrong-account"

    receipt = port.submit_order_insert(request)

    assert receipt.outcome == "UNKNOWN"
    assert receipt.local_rejection_verified is False


def test_cancel_dispatch_receipt_requires_exact_target_and_proves_only_local_rejection():
    snapshot = CtpSimulationOrderSnapshot(
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref="000000000123",
        order_sys_id="sys-order-8",
        front_id=17,
        session_id=19,
    )
    request = _cancel_request(snapshot)
    port, client, _ = _port(
        capability=object(),
        runtime_admission_check=lambda: True,
    )
    port.authorize_write(request, _signed_approval(port, request), action_id="cancel-exact")
    client.action_submit_code = -3

    receipt = port.submit_order_action(snapshot, "cancel-exact")

    assert receipt.operation == "CANCEL"
    assert receipt.outcome == "REJECTED"
    assert receipt.action_id == "cancel-exact"
    assert receipt.local_rejection_verified is True

    port, client, _ = _port(
        capability=object(),
        runtime_admission_check=lambda: True,
    )
    port.authorize_write(request, _signed_approval(port, request), action_id="cancel-mismatch")
    client.action_evidence_overrides["order_sys_id"] = "another-order"

    receipt = port.submit_order_action(snapshot, "cancel-mismatch")

    assert receipt.outcome == "UNKNOWN"
    assert receipt.local_rejection_verified is False


def test_negative_sdk_submit_code_requires_exact_no_callback_evidence():
    port, client, _ = _port(
        capability=object(),
        runtime_admission_check=lambda: True,
    )
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=1,
        limit_price=Decimal("125.5"),
    )
    port.authorize_write(request, _signed_approval(port, request))
    client.insert_submit_code = -3

    receipt = port.submit_order_insert(request)

    assert receipt.outcome == "REJECTED"
    assert receipt.submit_code == -3
    assert receipt.local_rejection_verified is True

    port, client, _ = _port(
        capability=object(),
        runtime_admission_check=lambda: True,
    )
    port.authorize_write(request, _signed_approval(port, request))
    client.insert_submit_code = -3
    client.insert_evidence_overrides["callback_received"] = True
    client.insert_evidence_overrides["evidence_received"] = True
    client.insert_evidence_overrides["status"] = "rejected"

    receipt = port.submit_order_insert(request)

    assert receipt.outcome == "UNKNOWN"
    assert receipt.local_rejection_verified is False


@pytest.mark.parametrize(
    ("mutation", "expected_id"),
    [
        ("OrderRef", "000000000124"),
        ("OrderSysID", "sys-order-other"),
        ("InstrumentID", "cu2701"),
        ("ExchangeID", "DCE"),
        ("missing", None),
        ("duplicate", None),
    ],
)
def test_cancel_acceptance_requires_one_exact_native_order_row(mutation, expected_id):
    capability = object()
    port, client, _ = _port(
        capability=capability,
        runtime_admission_check=lambda: True,
    )
    snapshot = CtpSimulationOrderSnapshot(
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref="000000000123",
        order_sys_id="sys-order-8",
        front_id=17,
        session_id=19,
    )
    cancel = _cancel_request(snapshot)
    port.authorize_write(
        cancel,
        _signed_approval(port, cancel, approval_id="offline-cancel-approval-2"),
        action_id="cancel-attempt-identity-check",
    )
    port.submit_order_action(snapshot, "cancel-attempt-identity-check")
    _, request_id, _native_kwargs = client.action_calls[0]
    client.cancel_evidence[(request_id, str(request_id))] = SimpleNamespace(
        request_id=request_id,
        order_action_ref=str(request_id),
        status="accepted",
        account_fingerprint=ACCOUNT_FP,
        trading_day="20260923",
        connection_generation=8,
        order_ref=snapshot.order_ref,
        order_sys_id=snapshot.order_sys_id,
        front_id=17,
        session_id=19,
        instrument_id=snapshot.instrument_id,
        exchange_id=snapshot.exchange_id,
        action_flag="0",
        callback_received=True,
        evidence_received=True,
    )

    if mutation == "missing":
        client.order_rows = ()
    else:
        row = _order_row(order_status="5")
        if mutation == "duplicate":
            client.order_rows = (row, dict(row))
        else:
            row[mutation] = expected_id
            client.order_rows = (row,)

    result = port.query_cancel_requests(("cancel-attempt-identity-check",))

    assert result.complete is False
    assert len(result.records) == 1
    assert result.records[0].status == "UNKNOWN"


def test_sealed_composition_runs_session_submit_and_recovery_approved_cancel(tmp_path, monkeypatch):
    """Local fakes exercise the full journal -> typed SDK callback composition."""

    # This bypass is limited to synthetic temp-file ACLs; it is not deployment
    # evidence for config permissions or the installed SDK.
    monkeypatch.setattr(
        runtime_config_module, "_require_private_config_security", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        execution_module, "_default_state_root", lambda: tmp_path / "execution-state"
    )
    runtime_dir = tmp_path / "registered-runtime"
    runtime_dir.mkdir()
    (runtime_dir / "config.yaml").write_text(
        "\n".join(
            (
                "config_schema_version: 4",
                "strategy:",
                "  id: offline.ctp.managed",
                "runtime:",
                "  mode: simulation",
                "  preset: sandbox",
                "parameters: {}",
                "secrets_ref: config_yaml",
                "ctp_simnow:",
                "  front_pairs:",
                "    - md_front: tcp://unused-market.invalid:12002",
                "      td_front: tcp://unused-trade.invalid:12001",
                "    - md_front: " + MD_FRONT,
                "      td_front: " + TD_FRONT,
                "  instrument_id: rb2701",
                "  exchange_id: SHFE",
                "  hedge_flag: '1'",
                "  broker_id: '" + BROKER + "'",
                "  user_id: " + USER,
                "  password: fake-password",
                "  app_id: fake-app",
                "  auth_code: fake-auth",
                "",
            )
        ),
        encoding="utf-8",
    )
    runtime = RegisteredRuntime(
        runtime_dir=runtime_dir,
        runtime_id="offline.ctp.managed",
        strategy_id="offline.ctp.managed",
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("config_yaml",),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest=RECEIPT,
    )
    registry = RuntimeRegistry((runtime,), registry_id="offline-managed-simnow")
    effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    registration = CtpSimulationExecutionRegistration(
        runtime_registration=runtime,
        environment="simnow",
        sdk_profile=PROFILE,
        td_front=TD_FRONT,
        md_front=MD_FRONT,
        account_fingerprint_sha256=ACCOUNT_DIGEST,
        allowed_secrets_ref="config_yaml",
        instrument_id="rb2701",
        exchange_id="SHFE",
        hedge_flag="1",
        allowed_sides=("BUY", "SELL"),
        quantity_step=1,
        max_quantity=3,
        max_gross_position=3,
        min_price=Decimal("100"),
        max_price=Decimal("200"),
        price_tick=Decimal("0.5"),
        approval_key_id=_TEST_APPROVAL_KEY_ID,
        approval_ttl_seconds=60.0,
    )
    config_path = runtime_dir / "config.yaml"
    original_config = config_path.read_text(encoding="utf-8")
    changed_config = original_config.replace(TD_FRONT, "tcp://custom-td.invalid:30001").replace(
        MD_FRONT, "tcp://custom-md.invalid:30002"
    )
    config_path.write_text(changed_config, encoding="utf-8")
    with pytest.raises(CtpSimulationExecutionError, match="runtime config changed"):
        resolve_sealed_ctp_simnow_trader_config(effective, registry, registration)
    changed_effective = resolve_runtime_config(
        load_runtime_config(runtime_dir, registry=registry), registry
    )
    with pytest.raises(CtpSimulationExecutionError, match="front pair registration mismatch"):
        resolve_sealed_ctp_simnow_trader_config(changed_effective, registry, registration)
    config_path.write_text(original_config, encoding="utf-8")

    capability = object()
    clients = []
    ports = []
    verifier = HmacCtpSimulationApprovalVerifier(_TEST_APPROVAL_KEY_ID, _TEST_APPROVAL_KEY)

    def trader_factory(td_front, broker_id, user_id, password, **kwargs):
        assert (td_front, broker_id, user_id, password) == (
            TD_FRONT,
            BROKER,
            USER,
            "fake-password",
        )
        assert kwargs == {
            "app_id": "fake-app",
            "auth_code": "fake-auth",
            "md_front": MD_FRONT,
            "ctp_env_profile": PROFILE,
            "auto_settlement_confirm": False,
        }
        client = _FakeTraderClient(PROFILE, (td_front, kwargs["md_front"]))
        clients.append(client)
        return client

    def reject_artifact_provenance(*, td_front, md_front):
        assert (td_front, md_front) == (registration.td_front, registration.md_front)
        raise CtpArtifactProvenanceError("artifact_pin_unavailable")

    resolved_credential_configs = []
    build_trader_config = managed_composition_module._trader_config_from_private

    def track_credential_config_resolution(private, route):
        resolved_credential_configs.append(route)
        return build_trader_config(private, route)

    # A failed provenance check must stop before either the client factory or
    # credential fields are extracted. The seams are patched here because this
    # test uses synthetic local SDK fakes.
    monkeypatch.setattr(
        managed_composition_module,
        "verify_ctp_simnow_managed_artifact_provenance_for_fronts",
        reject_artifact_provenance,
    )
    monkeypatch.setattr(
        managed_composition_module,
        "_trader_config_from_private",
        track_credential_config_resolution,
    )
    monkeypatch.setattr(
        managed_composition_module,
        "trusted_installed_capability_import_context",
        lambda _modules: nullcontext(),
    )
    with pytest.raises(CtpSimulationExecutionError, match="artifact provenance rejected"):
        create_sealed_ctp_simnow_managed_port(
            effective,
            registry,
            registration,
            execution_capability=capability,
            runtime_admission_check=lambda: True,
            runtime_order_binding=lambda *_args: {},
            runtime_credential_binding_factory=lambda **_kwargs: None,
            runtime_approval_verifier=verifier,
            sdk_approval_rechecker=lambda _binding, _scope: True,
            trader_client_factory=trader_factory,
            order_field_factory=_Field,
            action_field_factory=_Field,
        )
    assert clients == []
    assert resolved_credential_configs == []

    verified_pairs = []
    verified_import_modules = []

    def accept_test_artifact_provenance(*, td_front, md_front):
        verified_pairs.append((td_front, md_front))

    def record_trusted_import_modules(modules):
        verified_import_modules.append(tuple(modules))
        return nullcontext()

    monkeypatch.setattr(
        managed_composition_module,
        "verify_ctp_simnow_managed_artifact_provenance_for_fronts",
        accept_test_artifact_provenance,
    )
    monkeypatch.setattr(
        managed_composition_module,
        "trusted_installed_capability_import_context",
        record_trusted_import_modules,
    )

    def order_binding(runtime_order_id, reserve):
        assert runtime_order_id == MANAGED_ORDER_ID
        return {
            "runtime_order_id": runtime_order_id,
            "client_order_id": "000000000123",
            "ctp_order_ref": "000000000123",
            "managed_intent_id": "intent-offline-1",
            "connection_generation": 8,
            "trading_day": "20260923",
            "reserved": reserve,
        }

    def binding_factory(
        *, operation, request, runtime_approval, action_id, identity, write_intent_verifier
    ):
        assert request.action == ("SUBMIT" if operation == "insert" else "CANCEL")
        if operation == "cancel":
            assert action_id is not None
        sdk_approval = _FakeSdkApproval(
            approval_id="sdk-" + runtime_approval.approval_id,
            nonce="nonce-" + (action_id or "entry"),
            payload_sha256=hashlib.sha256(
                (runtime_approval.request_digest + ":" + (action_id or "entry")).encode()
            ).hexdigest(),
        )
        return _FakeSdkBinding(
            TD_FRONT,
            MD_FRONT,
            PROFILE,
            operation,
            action_id,
            sdk_approval,
            write_intent_verifier,
        )

    query_verifier = SimpleNamespace(
        verify=lambda _kind, result, *, expected_identity, registration_digest: (
            type(result) is CtpSimulationQueryResult
            and result.complete is True
            and result.identity == expected_identity
            and result.native_evidence is not None
            and len(registration_digest) == 64
        )
    )
    fence = SimpleNamespace(
        environment=registration.environment,
        account_fingerprint_sha256=registration.account_fingerprint_sha256,
        fence_id="offline-simnow-fence",
        assert_active=lambda: None,
    )

    def native_factory(route, _lease):
        assert route is registration
        port = create_sealed_ctp_simnow_managed_port(
            effective,
            registry,
            registration,
            execution_capability=capability,
            runtime_admission_check=lambda: True,
            runtime_order_binding=order_binding,
            runtime_credential_binding_factory=binding_factory,
            runtime_approval_verifier=verifier,
            sdk_approval_rechecker=lambda _binding, _scope: True,
            trader_client_factory=trader_factory,
            order_field_factory=_Field,
            action_field_factory=_Field,
        )
        ports.append(port)
        return port

    session = open_ctp_simulation_execution(
        effective=effective,
        registry=registry,
        registration=registration,
        native_session_factory=native_factory,
        approval_verifier=verifier,
        query_evidence_verifier=query_verifier,
        writer_fence=fence,
    )
    assert verified_pairs == [(registration.td_front, registration.md_front)]
    assert verified_import_modules == [("bt_api_base", "bt_api_ctp", "bt_api_py")]
    assert resolved_credential_configs == [registration]
    port, client = ports[0], clients[0]
    request = CtpSimulationWriteRequest(
        action="SUBMIT",
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        hedge_flag="1",
    )
    assert (
        session.submit_order(
            client_order_id=MANAGED_ORDER_ID,
            instrument_id="rb2701",
            exchange_id="SHFE",
            side="BUY",
            quantity=2,
            limit_price=Decimal("125.5"),
            approval=_signed_approval(port, request, approval_id="offline-entry-1"),
        )
        == "PENDING"
    )
    assert len(client.insert_calls) == 1
    assert client.gate_armed is False
    assert client.insert_calls[0][2]["execution_capability"] is capability

    client.order_rows = (_order_row(),)
    result = session.reconcile(MANAGED_ORDER_ID)
    assert result.complete is True and result.status == "OPEN"
    order_snapshot = CtpSimulationOrderSnapshot(
        client_order_id=MANAGED_ORDER_ID,
        instrument_id="rb2701",
        exchange_id="SHFE",
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref="000000000123",
        order_sys_id="sys-order-8",
        front_id=17,
        session_id=19,
    )
    cancel = _cancel_request(order_snapshot)
    assert (
        session.cancel_order(
            MANAGED_ORDER_ID,
            _signed_approval(port, cancel, approval_id="offline-recovery-1"),
        )
        == "CANCEL_PENDING"
    )
    native_action, action_request_id, action_kwargs = client.action_calls[0]
    action_id = action_kwargs["runtime_action_id"]
    assert action_id.startswith("cancel-")
    assert client.credential_bindings[-1][1].approval.nonce == "nonce-" + action_id
    assert native_action.ActionFlag == "0"

    client.cancel_evidence[(action_request_id, str(action_request_id))] = SimpleNamespace(
        request_id=action_request_id,
        order_action_ref=str(action_request_id),
        status="accepted",
        account_fingerprint=ACCOUNT_FP,
        trading_day="20260923",
        connection_generation=8,
        order_ref=order_snapshot.order_ref,
        order_sys_id=order_snapshot.order_sys_id,
        front_id=order_snapshot.front_id,
        session_id=order_snapshot.session_id,
        instrument_id=order_snapshot.instrument_id,
        exchange_id=order_snapshot.exchange_id,
        action_flag="0",
        callback_received=True,
        evidence_received=True,
    )
    client.order_rows = (_order_row(order_status="5"),)
    result = session.reconcile(MANAGED_ORDER_ID)
    assert result.complete is True and result.status == "CANCELED"
    assert len(client.credential_bindings) == 2
    assert client.gate_armed is False
    session.close()
    assert client.stop_calls == 1
