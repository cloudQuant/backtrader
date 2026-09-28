"""Offline tests for the TraderClient query evidence verifier."""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

pytest.importorskip("bt_api_ctp")
pytest.importorskip("bt_api_ctp.order_action")

from bt_api_ctp.ctp.client import (
    TraderClient,
    _TRADER_LOGIN_IDENTITY_SEAL,
    _TraderLoginIdentityObservation,
)
from bt_api_ctp.order_action import CtpOrderActionEvidence

from backtrader_runtime import RegisteredRuntime
from backtrader_runtime.ctp_simulation_execution import (
    CtpSimulationCancelRequestSnapshot,
    CtpSimulationExecutionError,
    CtpSimulationExecutionRegistration,
    CtpSimulationOrderSnapshot,
    CtpSimulationQueryResult,
    CtpSimulationSessionIdentity,
)
from backtrader_runtime.ctp_simulation_query_evidence import (
    CtpTraderClientQueryEvidenceVerifier,
)


TD_FRONT = "tcp://simnow.invalid:10001"
MD_FRONT = "tcp://simnow.invalid:10002"
BROKER_ID = "9999"
INVESTOR_ID = "offline-user"
INSTRUMENT_ID = "rb2701"
EXCHANGE_ID = "SHFE"
TRADING_DAY = "20260923"
GENERATION = 7
ORDER_REF = "000000000123"
ORDER_SYS_ID = "offline-order-123"
CLIENT_ORDER_ID = "bt-managed-v1:" + "a" * 64


def registration() -> CtpSimulationExecutionRegistration:
    runtime = RegisteredRuntime(
        runtime_dir="offline-runtime",
        runtime_id="offline.ctp.simnow.query",
        strategy_id="offline.ctp.simnow.query",
        allowed_presets=("sandbox",),
        allowed_parameter_keys=(),
        allowed_secrets_refs=("os_secret_store:offline",),
        available_capabilities=("execution", "risk", "monitor"),
        sandbox_write_policy="receipt_required",
        approval_receipt_digest="a" * 64,
    )
    account_fingerprint = hashlib.sha256(f"{BROKER_ID}:{INVESTOR_ID}".encode("utf-8")).hexdigest()[
        :16
    ]
    return CtpSimulationExecutionRegistration(
        runtime_registration=runtime,
        environment="simnow",
        sdk_profile="config_front_pair",
        td_front=TD_FRONT,
        md_front=MD_FRONT,
        account_fingerprint_sha256=hashlib.sha256(
            ("acct_" + account_fingerprint).encode("ascii")
        ).hexdigest(),
        allowed_secrets_ref="os_secret_store:offline",
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
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


def offline_client() -> TraderClient:
    client = TraderClient(
        TD_FRONT,
        BROKER_ID,
        INVESTOR_ID,
        "offline-password",
        md_front=MD_FRONT,
        ctp_env_profile="config_front_pair",
        auto_settlement_confirm=False,
    )
    client._connected = True
    client._authentication_state = "authenticated"
    client._login_state = "logged_in"
    client._trading_day = TRADING_DAY
    client._connection_generation = GENERATION
    client._api = object()
    client._session_native_api = client._api
    client._session_native_front = TD_FRONT
    client._front_connected_front = TD_FRONT
    client._login_identity_observation = _TraderLoginIdentityObservation(
        _seal=_TRADER_LOGIN_IDENTITY_SEAL,
        broker_id=BROKER_ID,
        user_id=INVESTOR_ID,
        trading_day=TRADING_DAY,
        connection_generation=GENERATION,
        request_id=1,
    )
    client.get_front_binding_state = lambda: {
        "configured_front": TD_FRONT,
        "registered_front": TD_FRONT,
        "connection_confirmed_front": TD_FRONT,
        "connected": True,
        "native_api_current": True,
        "bound_identity_current": True,
        "connection_generation": GENERATION,
    }
    client._query_interval = 0.0
    client._req_id = 100
    return client


def identity(reg: CtpSimulationExecutionRegistration) -> CtpSimulationSessionIdentity:
    return CtpSimulationSessionIdentity(
        environment=reg.environment,
        sdk_profile=reg.sdk_profile,
        td_front=reg.td_front,
        md_front=reg.md_front,
        account_fingerprint_sha256=reg.account_fingerprint_sha256,
        trading_day=TRADING_DAY,
        connection_generation=GENERATION,
        production=False,
        native_gate_armed=False,
        native_simnow_managed_mode=True,
    )


def row(*, status: str = "3") -> dict[str, object]:
    return {
        "BrokerID": BROKER_ID,
        "InvestorID": INVESTOR_ID,
        "TradingDay": TRADING_DAY,
        "InstrumentID": INSTRUMENT_ID,
        "ExchangeID": EXCHANGE_ID,
        "OrderRef": ORDER_REF,
        "OrderSysID": ORDER_SYS_ID,
        "FrontID": 17,
        "SessionID": 19,
        "Direction": "0",
        "LimitPrice": 125.5,
        "VolumeTotalOriginal": 2,
        "VolumeTraded": 0,
        "OrderSubmitStatus": "3",
        "OrderStatus": status,
    }


class _FakeNativeApi:
    """Drive the installed TraderClient query path without a provider socket."""

    def __init__(self, client: TraderClient, records: tuple[dict[str, object], ...]):
        self.client = client
        self.records = records
        self.last_request_filters = None

    @staticmethod
    def _field(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("ascii", errors="ignore").rstrip("\x00 ")
        return str(value or "").rstrip("\x00 ")

    def ReqQryOrder(self, request: object, request_id: int) -> int:
        filters = {
            "BrokerID": self._field(getattr(request, "BrokerID", "")),
            "InvestorID": self._field(getattr(request, "InvestorID", "")),
            "InstrumentID": self._field(getattr(request, "InstrumentID", "")),
            "ExchangeID": self._field(getattr(request, "ExchangeID", "")),
            "OrderSysID": self._field(getattr(request, "OrderSysID", "")),
        }
        self.last_request_filters = filters
        for record in self.records:
            if any(
                filters[name]
                and self._field(record.get(row_name, "")) != filters[name]
                for name, row_name in (
                    ("BrokerID", "BrokerID"),
                    ("InvestorID", "InvestorID"),
                    ("InstrumentID", "InstrumentID"),
                    ("ExchangeID", "ExchangeID"),
                    ("OrderSysID", "OrderSysID"),
                )
            ):
                continue
            self.client._handle_query_callback("orders", record, None, request_id, False)
        self.client._handle_query_callback("orders", None, None, request_id, True)
        return 0


def native_orders_query(
    client: TraderClient,
    records: tuple[dict[str, object], ...],
    *,
    instrument_id: str = "",
    exchange_id: str = "",
    order_sys_id: str = "",
):
    api = _FakeNativeApi(client, records)
    client._api = api
    client._session_native_api = api
    # Reinstall the test-only login callback fact after changing the backing
    # fake API. The SDK invalidates that fact whenever its API binding changes.
    client._login_identity_observation = _TraderLoginIdentityObservation(
        _seal=_TRADER_LOGIN_IDENTITY_SEAL,
        broker_id=BROKER_ID,
        user_id=INVESTOR_ID,
        trading_day=TRADING_DAY,
        connection_generation=GENERATION,
        request_id=2,
    )
    assert client.is_read_only_ready, client.get_session_state()
    native = client.query_orders_result(
        instrument_id=instrument_id,
        exchange_id=exchange_id,
        order_sys_id=order_sys_id,
        timeout=0.1,
    )
    assert api.last_request_filters is not None, native
    return native, api.last_request_filters


def open_orders_filters() -> dict[str, str]:
    return {
        "BrokerID": BROKER_ID,
        "InvestorID": INVESTOR_ID,
        "InstrumentID": "",
        "ExchangeID": "",
        "OrderSysID": "",
    }


def target_scope_and_reservation():
    scope = SimpleNamespace(
        account_key="offline-account-key",
        trading_day=TRADING_DAY,
        scope_key="offline-scope-key",
    )
    reservation = SimpleNamespace(
        account_key=scope.account_key,
        trading_day=scope.trading_day,
        scope_key=scope.scope_key,
        managed_intent_id="offline.intent.target",
        runtime_order_id="bt-managed-v1:" + "c" * 64,
        order_ref=ORDER_REF,
    )
    return scope, reservation


def test_order_target_observation_comes_from_real_trader_client_query_source():
    reg = registration()
    client = offline_client()
    verifier = CtpTraderClientQueryEvidenceVerifier(client, reg)
    native, filters = native_orders_query(client, (row(),))
    projected = verifier._order_snapshot(native.records[0], client_order_id=None)
    result = CtpSimulationQueryResult(True, identity(reg), (projected,), native)
    scope, reservation = target_scope_and_reservation()

    observation = verifier.verify_order_target(scope, reservation, result)

    assert observation.request_id == native.request_id
    assert observation.request_type == "orders"
    assert observation.request_digest == verifier._order_target_source_digests(
        native.query_source
    )[0]
    assert len(observation.source_digest) == 64
    assert observation.trading_day == TRADING_DAY
    assert observation.connection_generation == GENERATION
    assert observation.order_ref == ORDER_REF
    assert observation.order_sys_id == ORDER_SYS_ID
    assert observation.exchange_id == EXCHANGE_ID
    assert observation.front_id == 17
    assert observation.session_id == 19
    assert observation.quantity == 2
    assert observation.traded_quantity == 0
    assert observation.remaining_quantity == 2
    assert observation.authorizes_cancel is False
    assert observation.is_fresh is True
    assert 0 < observation.expires_monotonic_ns - observation.issued_monotonic_ns <= 2_000_000_000
    assert filters == open_orders_filters()


def test_order_target_observation_rejects_caller_projected_row_substitution():
    reg = registration()
    client = offline_client()
    verifier = CtpTraderClientQueryEvidenceVerifier(client, reg)
    native, _filters = native_orders_query(client, (row(),))
    projected = verifier._order_snapshot(native.records[0], client_order_id=None)
    caller_row = replace(projected, order_sys_id="caller-selected-order")
    result = CtpSimulationQueryResult(True, identity(reg), (caller_row,), native)
    scope, reservation = target_scope_and_reservation()

    with pytest.raises(CtpSimulationExecutionError) as exc_info:
        verifier.verify_order_target(scope, reservation, result)

    assert exc_info.value.reason == "native_query_order_projection_mismatch"


def test_unfiltered_account_open_orders_require_native_terminal_source_and_projection():
    reg = registration()
    client = offline_client()
    verifier = CtpTraderClientQueryEvidenceVerifier(client, reg)
    native, filters = native_orders_query(client, (row(),))
    assert filters == open_orders_filters()
    assert native.query_source.request_filters == tuple(sorted(filters.items()))
    projected = CtpSimulationOrderSnapshot(
        client_order_id=ORDER_REF,
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref=ORDER_REF,
        order_sys_id=ORDER_SYS_ID,
        front_id=17,
        session_id=19,
    )
    result = CtpSimulationQueryResult(True, identity(reg), (projected,), native)

    assert verifier.verify(
        "account_open_orders",
        result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )

    client._handle_query_callback("orders", None, None, native.request_id, True)
    assert not verifier.verify(
        "account_open_orders",
        result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )
    assert verifier.last_error_code == "native_query_late_callback_detected"


def test_filtered_orders_cannot_be_used_as_an_account_wide_snapshot():
    reg = registration()
    client = offline_client()
    verifier = CtpTraderClientQueryEvidenceVerifier(client, reg)
    native, filters = native_orders_query(
        client, (row(),), instrument_id=INSTRUMENT_ID, exchange_id=EXCHANGE_ID
    )
    assert filters["InstrumentID"] == INSTRUMENT_ID
    assert filters["ExchangeID"] == EXCHANGE_ID
    projected = CtpSimulationOrderSnapshot(
        client_order_id=CLIENT_ORDER_ID,
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref=ORDER_REF,
        order_sys_id=ORDER_SYS_ID,
        front_id=17,
        session_id=19,
    )
    result = CtpSimulationQueryResult(True, identity(reg), (projected,), native)

    assert not verifier.verify(
        "account_open_orders",
        result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )
    assert verifier.last_error_code == "native_query_sdk_source_scope_mismatch"


def test_terminal_cancel_needs_exact_sdk_callback_and_canceled_target_query():
    reg = registration()
    client = offline_client()
    verifier = CtpTraderClientQueryEvidenceVerifier(client, reg)
    now = datetime.now(timezone.utc)
    action = CtpOrderActionEvidence(
        request_id=145,
        order_action_ref="145",
        status="accepted",
        account_fingerprint="acct_" + client._account_fingerprint,
        trading_day=TRADING_DAY,
        connection_generation=GENERATION,
        order_ref=ORDER_REF,
        order_sys_id=ORDER_SYS_ID,
        front_id=17,
        session_id=19,
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        action_flag="0",
        evidence_source="OnRspOrderAction",
        callback_received=True,
        evidence_received=True,
        error_code=0,
        error_message="",
        reason="cancel_request_accepted",
        submitted_at_utc=now,
        observed_at_utc=now,
        submit_code=0,
    )
    client._order_action_history[(145, "145")] = action
    target, _filters = native_orders_query(
        client,
        (row(status="5"),),
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        order_sys_id=ORDER_SYS_ID,
    )
    cancel = CtpSimulationCancelRequestSnapshot(
        action_id="cancel-145",
        client_order_id=CLIENT_ORDER_ID,
        target_order_sys_id=ORDER_SYS_ID,
        target_order_ref=ORDER_REF,
        target_front_id=17,
        target_session_id=19,
        status="CANCELED",
    )
    result = CtpSimulationQueryResult(
        True,
        identity(reg),
        (cancel,),
        (action, target),
    )

    assert verifier.verify(
        "cancel_requests",
        result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )

    substituted_action = CtpOrderActionEvidence(
        **{
            **action.__dict__,
            "reason": "cancel_request_accepted",
        }
    )
    substituted = CtpSimulationQueryResult(
        True,
        identity(reg),
        (cancel,),
        (substituted_action, target),
    )
    assert not verifier.verify(
        "cancel_requests",
        substituted,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )
    assert verifier.last_error_code == "native_cancel_query_history_mismatch"


def test_query_history_eviction_fails_closed_on_final_quiescence_readback():
    reg = registration()
    client = offline_client()
    verifier = CtpTraderClientQueryEvidenceVerifier(client, reg)
    native, _filters = native_orders_query(client, (row(),))
    projected = CtpSimulationOrderSnapshot(
        client_order_id=ORDER_REF,
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref=ORDER_REF,
        order_sys_id=ORDER_SYS_ID,
        front_id=17,
        session_id=19,
    )
    result = CtpSimulationQueryResult(True, identity(reg), (projected,), native)
    assert verifier.verify(
        "account_open_orders",
        result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )

    for _ in range(260):
        native_orders_query(client, ())

    assert not verifier.verify(
        "account_open_orders",
        result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )
    assert verifier.last_error_code == "native_query_history_evicted"


def test_quiescence_rechecks_issuer_freshness_for_every_accepted_query(monkeypatch):
    import backtrader_runtime.ctp_simulation_query_evidence as query_evidence

    reg = registration()
    client = offline_client()
    verifier = CtpTraderClientQueryEvidenceVerifier(client, reg)
    first_native, _first_filters = native_orders_query(client, (row(),))
    first_projection = CtpSimulationOrderSnapshot(
        client_order_id=ORDER_REF,
        instrument_id=INSTRUMENT_ID,
        exchange_id=EXCHANGE_ID,
        side="BUY",
        quantity=2,
        limit_price=Decimal("125.5"),
        traded_quantity=0,
        status="OPEN",
        order_ref=ORDER_REF,
        order_sys_id=ORDER_SYS_ID,
        front_id=17,
        session_id=19,
    )
    first_result = CtpSimulationQueryResult(True, identity(reg), (first_projection,), first_native)
    assert verifier.verify(
        "account_open_orders",
        first_result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )

    # Mint a later, still-fresh result, then place the verifier wall clock
    # between the SDK-issued UTC expiry bounds. The test follows the evidence
    # timestamps; it does not depend on a particular issuer TTL value.
    time.sleep(0.002)
    second_native, _second_filters = native_orders_query(client, ())
    first_source = first_native.query_source
    second_source = second_native.query_source
    assert first_source.trusted_expires_at_utc < second_source.trusted_expires_at_utc
    midpoint_utc = (
        first_source.trusted_expires_at_utc
        + (second_source.trusted_expires_at_utc - first_source.trusted_expires_at_utc) / 2
    )
    second_result = CtpSimulationQueryResult(True, identity(reg), (), second_native)
    monkeypatch.setattr(query_evidence, "datetime", SimpleNamespace(now=lambda _tz: midpoint_utc))

    assert not verifier.verify(
        "account_open_orders",
        second_result,
        expected_identity=identity(reg),
        registration_digest=reg.digest,
    )
    assert verifier.last_error_code == "query_expired_during_quiescence"
