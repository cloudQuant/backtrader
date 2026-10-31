"""Plain CTP direct Store route without RegisteredSimStore or service plugins.

The Store owns the Backtrader order mapping and lifecycle.  The legacy CTP
wrapper owns native field construction and delegates every write to the SDK's
typed ``submit_order_insert`` / ``submit_order_action`` entry with the opaque
capability returned by the SDK admission.  These tests use a synthetic trader
client only: no CTP SDK, login, account or provider request is involved.
"""

import types

import pytest

import backtrader as bt
from backtrader.stores.btapistore import (
    BtApiStore,
    BtApiStoreError,
    _create_ctp_wrapper_class,
)


class _Data:
    def __init__(self, name):
        self._dataname = name


class _RawApi:
    """Raw SWIG surface that the direct route must never reach."""

    def __init__(self):
        self.insert_calls = 0
        self.action_calls = 0

    def ReqOrderInsert(self, field, request_id):
        self.insert_calls += 1
        raise AssertionError("raw ReqOrderInsert must not be reached")

    def ReqOrderAction(self, field, request_id):
        self.action_calls += 1
        raise AssertionError("raw ReqOrderAction must not be reached")


class _FakeTraderClient:
    """Synthetic SDK trader client exposing only the typed write entries."""

    is_ready = True

    def __init__(self, insert_result=0, action_result=0):
        self._req_id = 100
        self._front_id = 7
        self._session_id = 9
        self.api = _RawApi()
        self.insert_result = insert_result
        self.action_result = action_result
        self.arm_calls = []
        self.insert_calls = []
        self.action_calls = []
        self.disarm_calls = []

    def arm_execution_for_registered_sim(self, **kwargs):
        self.arm_calls.append(dict(kwargs))
        return ("opaque-capability", {"armed": True})

    def disarm_execution_gate(self, capability, reason):
        self.disarm_calls.append((capability, reason))
        return {"armed": False, "reason": reason}

    def submit_order_insert(self, field, request_id, *, execution_capability):
        self.insert_calls.append((field, request_id, execution_capability))
        return self.insert_result

    def submit_order_action(self, field, request_id, *, execution_capability):
        self.action_calls.append((field, request_id, execution_capability))
        return self.action_result


def _make_store(insert_result=0, action_result=0):
    wrapper_cls = _create_ctp_wrapper_class()
    wrapper = wrapper_cls(
        md_address="tcp://md",
        td_address="tcp://td",
        broker_id="9999",
        investor_id="direct-user",
        password="secret",
    )
    wrapper.trader_client = _FakeTraderClient(
        insert_result=insert_result,
        action_result=action_result,
    )
    store = BtApiStore(provider="ctp", api=wrapper)
    # The synthetic wrapper has no transport; mark the Store connected so the
    # write path reads the injected client without touching ``connect()``.
    store._connected = True
    return store, wrapper


def _order(symbol="IF2506", buy=True, size=1, price=4010.0, ref=42, offset="open"):
    order = types.SimpleNamespace(
        ref=ref,
        size=size,
        price=price,
        pricelimit=None,
        exectype=bt.Order.Limit,
        valid=None,
        tradeid=0,
        data=_Data("CFFEX." + symbol),
        info={"offset": offset},
    )
    order.isbuy = lambda: buy
    order.created = types.SimpleNamespace(price=price)
    return order


def _arm(store, instrument="IF2506", exchange="CFFEX"):
    return store.arm_registered_sim_execution(
        instrument,
        exchange,
        strategy_identity_sha256="a" * 64,
        execution_cycle_id="cycle-1",
        preflight_sha256="b" * 64,
    )


def test_direct_submit_without_admission_fails_closed_before_native_access():
    store, wrapper = _make_store()

    with pytest.raises(BtApiStoreError, match="requires an armed execution gate"):
        store.submit_order(_order())

    assert wrapper.trader_client.insert_calls == []
    assert wrapper.trader_client.api.insert_calls == 0


def test_direct_submit_builds_native_fields_and_uses_typed_entry():
    store, wrapper = _make_store()
    _arm(store)

    response = store.submit_order(_order())

    assert response["order_ref"] == "42"
    assert response["front_id"] == 7
    assert response["session_id"] == 9
    ((field, request_id, capability),) = wrapper.trader_client.insert_calls
    assert capability == "opaque-capability"
    assert request_id == field.RequestID == 101
    assert field.BrokerID == "9999"
    assert field.InvestorID == "direct-user"
    assert field.UserID == "direct-user"
    assert field.InstrumentID == "IF2506"
    assert field.Direction == "0"
    assert field.CombOffsetFlag == "0"
    assert field.CombHedgeFlag == "1"
    assert field.VolumeTotalOriginal == 1
    assert field.OrderRef == "42"
    assert field.OrderPriceType == "2"
    assert field.TimeCondition == "3"
    assert field.VolumeCondition == "1"
    assert field.LimitPrice == pytest.approx(4010.0)
    assert field.ExchangeID == "CFFEX"
    assert wrapper.trader_client.api.insert_calls == 0


def test_direct_arm_delegates_identity_and_remembers_exchange():
    store, wrapper = _make_store()

    state = _arm(store)

    assert state == {"armed": True}
    (call,) = wrapper.trader_client.arm_calls
    assert call == {
        "instrument_id": "IF2506",
        "exchange_id": "CFFEX",
        "md_front": "tcp://md",
        "strategy_identity_sha256": "a" * 64,
        "execution_cycle_id": "cycle-1",
        "preflight_sha256": "b" * 64,
    }
    # A later bare-symbol order reuses the admitted exchange identity.
    response = store.submit_order(_order(symbol="IF2506", ref=7))
    assert response["exchange_id"] == "CFFEX"


def test_direct_cancel_uses_typed_action_and_pending_identity():
    store, wrapper = _make_store()
    _arm(store)
    store.submit_order(_order(ref=42))

    response = store.cancel_order_ref("42", dataname="CFFEX.IF2506")

    ((field, request_id, capability),) = wrapper.trader_client.action_calls
    assert capability == "opaque-capability"
    assert request_id == field.RequestID == 102
    assert field.ActionFlag == "0"
    assert field.OrderRef == "42"
    assert field.InstrumentID == "IF2506"
    assert field.ExchangeID == "CFFEX"
    assert field.FrontID == 7
    assert field.SessionID == 9
    assert response["order_ref"] == "42"
    assert wrapper.trader_client.api.action_calls == 0


def test_direct_native_rejection_code_is_surfaced():
    store, wrapper = _make_store(insert_result=-3)
    _arm(store)

    with pytest.raises(BtApiStoreError, match="CTP order send failed: ret=-3"):
        store.submit_order(_order())

    assert len(wrapper.trader_client.insert_calls) == 1


def test_direct_action_rejection_code_is_surfaced():
    store, wrapper = _make_store(action_result=-4)
    _arm(store)
    store.submit_order(_order(ref=42))

    with pytest.raises(BtApiStoreError, match="CTP cancel send failed: ret=-4"):
        store.cancel_order_ref("42", dataname="CFFEX.IF2506")


def test_direct_disarm_revokes_the_capability():
    store, wrapper = _make_store()
    _arm(store)

    result = store._api.disarm_registered_sim_execution("test_disarm")

    assert result["native"] is True
    assert result["state"] == {"armed": False, "reason": "test_disarm"}
    with pytest.raises(BtApiStoreError, match="requires an armed execution gate"):
        store.submit_order(_order())


def test_direct_submit_propagates_sdk_gate_error_without_raw_fallback():
    store, wrapper = _make_store()
    _arm(store)

    def reject(field, request_id, *, execution_capability):
        raise BtApiStoreError("ctp_execution_gate_capability_mismatch")

    wrapper.trader_client.submit_order_insert = reject

    with pytest.raises(BtApiStoreError, match="ctp_execution_gate_capability_mismatch"):
        store.submit_order(_order())
    assert wrapper.trader_client.api.insert_calls == 0
