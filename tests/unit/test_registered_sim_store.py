"""Focused fake-SDK contracts for the framework-owned registered-sim route."""

from __future__ import annotations

import collections
import copy
import os
import subprocess
import sys
import threading
import time
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtrader.stores.btapistore import BtApiStore, BtApiStoreError
from backtrader.order import OrderBase
from backtrader.stores.registered_sim import (
    RegisteredSimExecutionUnknown,
    RegisteredSimStore,
    RegisteredSimWrapper,
)


class FakeSdkTrader:
    def __init__(self):
        self.is_ready = True
        self._connection_generation = 1
        self._account_fingerprint = "fake-account-1"
        self._trading_day = "20261024"
        self._query_issuer = object()
        self.active_capability = None
        self.arm_calls = []
        self.disarm_calls = []
        self.native_calls = []
        self.fail_next_arm = False
        self.next_order_ref_value = 1000
        self.next_order_ref_calls = 0
        self.first_native_entered = threading.Event()
        self.release_first_native = threading.Event()
        self.block_first_native = False
        self.fail_next_insert = False
        self.fail_next_cancel = False

    def arm_execution_for_registered_sim(self, **kwargs):
        if self.fail_next_arm:
            self.fail_next_arm = False
            raise OSError("admission result is deliberately uncertain")
        capability = SimpleNamespace(
            instrument_id=kwargs["instrument_id"],
            exchange_id=kwargs["exchange_id"],
            connection_generation=self._connection_generation,
            trading_day=self._trading_day,
            scope_version="ctp-contract-bundle-v1",
            proof_sha256="{:064x}".format(len(self.arm_calls) + 1),
            environment_profile="simnow_demo",
            revocation_reason=None,
        )
        self.active_capability = capability
        self.arm_calls.append((kwargs, capability))
        return capability, {
            "managed": True,
            "armed": True,
            "instrument": capability.instrument_id,
            "connection_generation": capability.connection_generation,
            "trading_day": capability.trading_day,
            "authorized_instruments": [capability.instrument_id],
            "scope_version": capability.scope_version,
            "proof_sha256": capability.proof_sha256,
            "environment_profile": capability.environment_profile,
            "revocation_reason": capability.revocation_reason,
            "admission": "sdk-issued",
        }

    def disarm_execution_gate(self, capability, reason):
        assert capability is self.active_capability
        self.disarm_calls.append((capability, reason))
        self.active_capability = None
        return {"revoked": True}

    def get_query_session_scope(self):
        return SimpleNamespace(
            issuer=self._query_issuer,
            connection_generation=self._connection_generation,
            account_fingerprint=self._account_fingerprint,
            trading_day=self._trading_day,
            read_only_ready=True,
        )

    def get_session_state(self):
        return {
            "account_fingerprint": self._account_fingerprint,
            "connection_generation": self._connection_generation,
            "trading_day": self._trading_day,
            "trading_ready": self.is_ready,
            "read_only_ready": self.is_ready,
            "front_id": 4,
            "session_id": 7,
        }

    def get_execution_gate_state(self):
        capability = self.active_capability
        return {
            "managed": capability is not None,
            "armed": capability is not None,
            "instrument": capability.instrument_id if capability is not None else None,
            "connection_generation": (
                capability.connection_generation if capability is not None else None
            ),
            "trading_day": capability.trading_day if capability is not None else None,
            "authorized_instruments": (
                [capability.instrument_id] if capability is not None else None
            ),
            "scope_version": capability.scope_version if capability is not None else None,
            "proof_sha256": capability.proof_sha256 if capability is not None else None,
            "environment_profile": capability.environment_profile
            if capability is not None
            else None,
            "revocation_reason": capability.revocation_reason if capability is not None else None,
        }

    def next_order_ref(self):
        self.next_order_ref_calls += 1
        self.next_order_ref_value += 1
        return str(self.next_order_ref_value)

    def _submit(self, operation, field, request_id, execution_capability):
        capability = self.active_capability
        assert capability is execution_capability
        assert capability.instrument_id == field.InstrumentID
        assert capability.exchange_id == field.ExchangeID
        assert capability.connection_generation == self._connection_generation
        assert capability.trading_day == self._trading_day
        self.native_calls.append((operation, field.InstrumentID, field.ExchangeID, capability))
        if self.block_first_native and len(self.native_calls) == 1:
            self.first_native_entered.set()
            assert self.release_first_native.wait(2.0)
        if operation == "insert" and self.fail_next_insert:
            self.fail_next_insert = False
            raise OSError("transport result is deliberately ambiguous")
        if operation == "cancel" and self.fail_next_cancel:
            self.fail_next_cancel = False
            raise OSError("cancel result is deliberately ambiguous")
        return 0

    def submit_order_insert(self, field, request_id, *, execution_capability):
        return self._submit("insert", field, request_id, execution_capability)

    def submit_order_action(self, field, request_id, *, execution_capability):
        return self._submit("cancel", field, request_id, execution_capability)


class FakeCtpBase:
    def __init__(self, **kwargs):
        self.trader_client = FakeSdkTrader()
        self._execution_instrument_exchanges = {}
        self._pending_orders = {}
        self._next_fake_request_id = 100
        # The production generated CTP wrapper owns this deque and its Store
        # poller drains it. Recovery events must use this same normal path.
        self._order_updates = collections.deque()
        self._live_bar_event_notifier = None

    def set_live_bar_event_notifier(self, callback):
        self._live_bar_event_notifier = callback

    def _notify_live_bar_event(self):
        notifier = self._live_bar_event_notifier
        if notifier is not None:
            notifier()

    def poll_broker_update(self):
        if not self._order_updates:
            return None
        return self._order_updates.popleft()

    def _next_request_id(self):
        self._next_fake_request_id += 1
        return self._next_fake_request_id

    def submit_order(self, payload):
        """Mirror the stock direct CTP wrapper's synchronous native boundary."""
        instrument = payload["instrument_id"]
        exchange = payload["exchange_id"]
        request_id = self._next_request_id()
        order_ref = str(payload.get("order_ref") or "native-{}".format(payload["bt_order_ref"]))
        field = SimpleNamespace(
            InstrumentID=instrument,
            ExchangeID=exchange,
            OrderRef=order_ref,
            RequestID=request_id,
            FrontID=self.trader_client.get_session_state()["front_id"],
            SessionID=self.trader_client.get_session_state()["session_id"],
        )
        result = self._send_native_order_insert(field, request_id)
        assert result == 0
        self._pending_orders[order_ref] = {
            "order_ref": order_ref,
            "instrument": instrument,
            "exchange_id": exchange,
        }
        return {"order_ref": order_ref, "exchange_id": exchange}

    def cancel_order(self, order_ref, dataname=None):
        """Mirror the stock direct CTP wrapper's synchronous cancel boundary."""
        pending = self._pending_orders[order_ref]
        request_id = self._next_request_id()
        field = SimpleNamespace(
            InstrumentID=pending["instrument"],
            ExchangeID=pending["exchange_id"],
            OrderRef=pending["order_ref"],
            RequestID=request_id,
            FrontID=self.trader_client.get_session_state()["front_id"],
            SessionID=self.trader_client.get_session_state()["session_id"],
        )
        result = self._send_native_order_action(field, request_id)
        assert result == 0
        return {
            "order_ref": order_ref,
            "exchange_id": pending["exchange_id"],
        }

    def _handle_order(self, payload):
        self.last_order_event = payload


class FakeRegisteredSimWrapper(RegisteredSimWrapper, FakeCtpBase):
    pass


def _sha(character: str) -> str:
    return character * 64


def _templates():
    return {
        ("rb2510", "SHFE"): {
            "md_front": "tcp://127.0.0.1:1",
            "strategy_identity_sha256": _sha("a"),
            "execution_cycle_id": "cycle-rb",
            "preflight_sha256": _sha("b"),
        },
        ("i2509", "DCE"): {
            "md_front": "tcp://127.0.0.1:2",
            "strategy_identity_sha256": _sha("c"),
            "execution_cycle_id": "cycle-i",
            "preflight_sha256": _sha("d"),
        },
    }


def _three_route_templates():
    templates = _templates()
    templates[("cu2510", "SHFE")] = {
        "md_front": "tcp://127.0.0.1:3",
        "strategy_identity_sha256": _sha("e"),
        "execution_cycle_id": "cycle-cu",
        "preflight_sha256": _sha("f"),
    }
    return templates


def _wrapper(*, allow_writes=True, terminal_limit=4):
    wrapper = FakeRegisteredSimWrapper(
        registered_sim_allow_writes=allow_writes,
        registered_sim_terminal_order_limit=terminal_limit,
    )
    if allow_writes:
        wrapper.configure_registered_sim_arm_templates(_templates())
    return wrapper


def _field(instrument, exchange, order_ref="order-1", request_id=1):
    return SimpleNamespace(
        InstrumentID=instrument,
        ExchangeID=exchange,
        OrderRef=order_ref,
        RequestID=request_id,
    )


def _expected_session():
    return {
        "account_fingerprint": "fake-account-1",
        "connection_generation": 1,
        "trading_day": "20261024",
        "front_id": 4,
        "session_id": 7,
    }


def test_import_and_store_construction_do_not_import_a_provider():
    repo = Path(__file__).resolve().parents[2]
    code = (
        "import sys; import backtrader; "
        "from backtrader.stores.registered_sim import RegisteredSimStore; "
        "s=RegisteredSimStore(); "
        "assert s.allow_writes is False; "
        "assert 'bt_api_py' not in sys.modules; "
        "assert 'bt_api_ctp' not in sys.modules"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(repo),
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_registered_sim_tick_source_is_store_owned_and_stamped_on_consumed_ticks():
    api = _wrapper(allow_writes=False)
    raw_tick = SimpleNamespace(source="caller-supplied", instrument_id="rb2510")
    api.poll_tick = lambda _symbol: raw_tick
    store = RegisteredSimStore(
        api=api,
        live_tick_provenance={"source": "caller-supplied"},
    )
    store._connected = True

    assert store.registered_sim_tick_source == "ctp-native-live"
    with pytest.raises(AttributeError):
        store.registered_sim_tick_source = "caller-supplied"

    consumed = store.poll_tick("rb2510")
    assert consumed is not raw_tick
    assert consumed.source == "ctp-native-live"
    assert raw_tick.source == "caller-supplied"

    snapshot = store.get_latest_tick_snapshot("rb2510")
    assert snapshot is not raw_tick
    assert snapshot.source == "ctp-native-live"
    snapshot.source = "mutated-copy"
    assert store.get_latest_tick_snapshot("rb2510").source == "ctp-native-live"


def test_registered_sim_tick_source_stamps_mapping_without_mutating_raw_tick():
    api = _wrapper(allow_writes=False)
    raw_tick = {"source": "untrusted", "InstrumentID": "rb2510"}
    api.poll_tick = lambda _symbol: raw_tick
    store = RegisteredSimStore(api=api)
    store._connected = True

    consumed = store.poll_tick("rb2510")

    assert consumed == {"source": "ctp-native-live", "InstrumentID": "rb2510"}
    assert consumed is not raw_tick
    assert raw_tick["source"] == "untrusted"


def test_registered_sim_missing_tick_source_returns_detached_unstamped_event():
    class MissingTickSourceStore(RegisteredSimStore):
        def __getattribute__(self, name):
            if name == "registered_sim_tick_source":
                raise AttributeError(name)
            return super().__getattribute__(name)

    api = _wrapper(allow_writes=False)
    raw_tick = SimpleNamespace(source="untrusted", instrument_id="rb2510")
    api.poll_tick = lambda _symbol: raw_tick
    store = MissingTickSourceStore(api=api)
    store._connected = True

    consumed = store.poll_tick("rb2510")
    snapshot = store.get_latest_tick_snapshot("rb2510")

    assert consumed is not raw_tick
    assert snapshot is not raw_tick
    assert consumed.source == "untrusted"
    assert snapshot.source == "untrusted"


def test_shadow_store_refuses_arm_and_all_direct_ctp_writes():
    api = _wrapper(allow_writes=False)
    store = RegisteredSimStore(api=api)
    store._connected = True

    assert store.allow_writes is False
    assert store._is_ctp_write_provider() is True
    with pytest.raises(BtApiStoreError, match="shadow mode"):
        store.registered_sim_arm(
            instrument="rb2510",
            exchange="SHFE",
            md_front="tcp://127.0.0.1:1",
            strategy_identity_sha256=_sha("a"),
            execution_cycle_id="cycle",
            preflight_sha256=_sha("b"),
        )
    with pytest.raises(BtApiStoreError):
        store.submit_order(SimpleNamespace(ref=1))
    with pytest.raises(BtApiStoreError):
        store.cancel_order(SimpleNamespace(ref=1, data=None))
    with pytest.raises(BtApiStoreError):
        store.cancel_order_ref("order-1", dataname="rb2510.SHFE")
    assert not callable(getattr(store, "amend_order", None))
    with pytest.raises(AttributeError):
        store.allow_writes = True
    assert api.trader_client.arm_calls == []
    assert api.trader_client.native_calls == []
    assert store.sdk_api is None
    assert store.registered_sim_route_id == "simnow-registered-v1"
    eligibility = store.registered_sim_route_eligibility("rb2510", "SHFE")
    assert eligibility.allow_writes is False
    assert eligibility.instrument_eligible is None
    assert eligibility.capability_observed is True
    assert eligibility.sdk_capability_armed is False
    # This is an observed empty wrapper-local UNKNOWN set. Query/account
    # health remains unobserved below until source-owned facts are complete.
    assert eligibility.unknown_order_count == 0


def test_order_info_exact_instrument_and_exchange_override_data_name_payload():
    store = RegisteredSimStore()
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={"instrument_id": "rb2510", "exchange_id": "SHFE"},
        ref=17,
        isbuy=lambda: True,
        size=2,
        valid=None,
        tradeid=0,
    )
    payload = store._order_to_payload(order)

    assert payload["symbol"] == "SHFE.rb2510"
    assert payload["data_name"] == "SHFE.rb2510"
    assert payload["instrument_id"] == "rb2510"
    assert payload["exchange_id"] == "SHFE"

    order.info["instrument_id"] = "i2509"
    with pytest.raises(BtApiStoreError, match="does not match"):
        store._order_to_payload(order)


@pytest.mark.parametrize(
    "feed_dataname",
    ("rb2510", "rb2510.SHFE", "SHFE.rb2510", "rb2510_SHFE", "SHFE_rb2510"),
)
def test_order_route_accepts_only_exact_raw_feed_identity_forms(feed_dataname):
    store = RegisteredSimStore()
    store._broker = SimpleNamespace(
        _contract_metadata={
            "display-only": {"instrument_id": "rb2510", "exchange_id": "SHFE"},
        }
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(
            _name="display-only",
            _dataname=feed_dataname,
            _exchange_id="SHFE",
        ),
        info={
            "instrument_id": "rb2510",
            "exchange_id": "SHFE",
            "factor_intent_id": "intent-rb",
        },
        ref=20,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )

    payload = store._order_to_payload(order)
    assert payload["data_name"] == "SHFE.rb2510"
    assert payload["instrument_id"] == "rb2510"
    assert payload["exchange_id"] == "SHFE"


@pytest.mark.parametrize(
    "feed_dataname",
    (
        "SHFE.RB2510",  # Instrument case must remain exact.
        "shfe.rb2510",  # Exchange identity must remain exact.
        "DCE.rb2510",  # A display/feed route cannot substitute another exchange.
        "rb2510.DCE",
        "SHFE.rb2510.extra",  # Multi-segment aliases are ambiguous.
        "display-only",  # The display name is never a route identity.
    ),
)
def test_order_route_rejects_ambiguous_or_mismatched_raw_feed_identity(feed_dataname):
    store = RegisteredSimStore()
    store._broker = SimpleNamespace(
        _contract_metadata={
            "display-only": {"instrument_id": "rb2510", "exchange_id": "SHFE"},
        }
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="display-only", _dataname=feed_dataname),
        info={
            "instrument_id": "rb2510",
            "exchange_id": "SHFE",
            "factor_intent_id": "intent-rb",
        },
        ref=21,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )

    with pytest.raises(BtApiStoreError, match="subscribed feed"):
        store._order_to_payload(order)


def test_order_route_rejects_feed_exchange_conflicting_with_raw_pair():
    store = RegisteredSimStore()
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="rb-display", _dataname="rb2510.SHFE", _exchange_id="DCE"),
        info={"instrument_id": "rb2510", "exchange_id": "SHFE"},
        ref=22,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )

    with pytest.raises(BtApiStoreError, match="exchange does not match the subscribed feed"):
        store._order_to_payload(order)


def test_factor_order_uses_subscribed_contract_and_exact_broker_exchange_binding():
    store = RegisteredSimStore()
    store._broker = SimpleNamespace(
        _contract_metadata={
            "DCE.A": {"instrument_id": "A2612", "exchange_id": "DCE"},
        }
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_dataname="A2612", _name="DCE.A"),
        info={
            "instrument_id": "A2612",
            "exchange_id": "DCE",
            "factor_intent_id": "intent-a",
        },
        ref=18,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )

    payload = store._order_to_payload(order)
    assert payload["symbol"] == "DCE.A2612"
    assert payload["instrument_id"] == "A2612"
    assert payload["exchange_id"] == "DCE"

    # The target alias is display metadata only; it cannot override the feed's
    # subscribed contract identity or the Broker's exact route binding.
    order.info["instrument_id"] = "Y2612"
    with pytest.raises(BtApiStoreError, match="subscribed feed"):
        store._order_to_payload(order)

    order.info["instrument_id"] = "A2612"
    order.info["exchange_id"] = "SHFE"
    with pytest.raises(BtApiStoreError, match="Broker contract binding"):
        store._order_to_payload(order)

    order.info["exchange_id"] = "DCE"
    order.data._dataname = "Y2612"
    with pytest.raises(BtApiStoreError, match="subscribed feed"):
        store._order_to_payload(order)


def test_factor_order_requires_exact_broker_exchange_binding():
    store = RegisteredSimStore()
    store._broker = SimpleNamespace(_contract_metadata={"DCE.A": {"instrument_id": "A2612"}})
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_dataname="A2612", _name="DCE.A"),
        info={
            "instrument_id": "A2612",
            "exchange_id": "DCE",
            "factor_intent_id": "intent-a",
        },
        ref=19,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )
    with pytest.raises(BtApiStoreError, match="Broker contract binding is invalid"):
        store._order_to_payload(order)


@pytest.mark.parametrize("intent_field", ("factor_intent_id", "factor_cancel_intent_id"))
def test_blank_factor_intent_marker_still_requires_exact_broker_binding(intent_field):
    store = RegisteredSimStore()
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_dataname="A2612", _name="DCE.A"),
        info={"instrument_id": "A2612", "exchange_id": "DCE", intent_field: ""},
        ref=23,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )

    with pytest.raises(BtApiStoreError, match="factor order has no exact Broker contract binding"):
        store._order_route_from_info(order)


def test_stock_ctp_store_remains_fail_closed():
    stock = BtApiStore(provider="ctp")
    assert stock._is_ctp_write_provider() is True


def test_store_arm_uses_sdk_capability_and_preserves_exact_instrument_case():
    api = _wrapper()
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True

    result = store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )

    assert result["armed"] is True
    assert api.trader_client.arm_calls[0][0]["instrument_id"] == "rb2510"
    assert api.trader_client.arm_calls[0][1] is api._registered_sim_capability
    assert api._resolve_gate_exchange("rb2510", "") == "SHFE"
    assert api._resolve_gate_exchange("RB2510", "") == ""
    assert api._execution_instrument_exchanges == {}
    assert store.sdk_api is None
    assert store._is_ctp_write_provider() is False
    assert store.registered_sim_status()["armed"] is True


def test_ordinary_store_submit_cancel_hooks_are_synchronous_native_dispatches():
    # The unconfigured one-route compatibility path remains explicit. A
    # configured template map requires a query-session-bound Strategy intent.
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={"instrument_id": "rb2510", "exchange_id": "SHFE"},
        ref=17,
        isbuy=lambda: True,
        size=2,
        valid=None,
        tradeid=0,
    )

    response = store.submit_order(order)
    assert response == {"order_ref": "native-17", "exchange_id": "SHFE"}
    evidence = store.registered_sim_dispatch_history()
    assert len(evidence) == 1
    assert (evidence[0].operation, evidence[0].status, evidence[0].request_id) == (
        "insert",
        "KNOWN",
        101,
    )
    assert evidence[0].order_ref == response["order_ref"]
    assert (evidence[0].instrument_id, evidence[0].exchange_id) == ("rb2510", "SHFE")

    order.info["external_order_id"] = response["order_ref"]
    cancel_response = store.cancel_order(order)
    assert cancel_response["order_ref"] == response["order_ref"]
    evidence = store.registered_sim_dispatch_history()
    assert len(evidence) == 2
    assert (evidence[1].operation, evidence[1].status, evidence[1].request_id) == (
        "cancel",
        "KNOWN",
        102,
    )
    assert evidence[1].order_ref == response["order_ref"]
    assert [(call[0], call[1], call[2]) for call in api.trader_client.native_calls] == [
        ("insert", "rb2510", "SHFE"),
        ("cancel", "rb2510", "SHFE"),
    ]


def test_sdk_order_ref_reservation_is_local_monotonic_and_used_by_submit():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True

    order_ref = store.registered_sim_reserve_order_ref()
    assert order_ref == "1001"
    assert api.trader_client.next_order_ref_calls == 1
    assert api.trader_client.arm_calls == []
    assert api.trader_client.native_calls == []

    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={
            "instrument_id": "rb2510",
            "exchange_id": "SHFE",
            "order_ref": order_ref,
        },
        ref=17,
        isbuy=lambda: True,
        size=2,
        valid=None,
        tradeid=0,
    )
    response = store.submit_order(order)
    assert response["order_ref"] == order_ref
    assert store.registered_sim_dispatch_history()[0].order_ref == order_ref
    assert api.trader_client.next_order_ref_calls == 1


def test_order_ref_reservation_does_not_create_api_or_accept_bad_sdk_identity():
    unopened = RegisteredSimStore()
    with pytest.raises(BtApiStoreError, match="wrapper is unavailable"):
        unopened.registered_sim_reserve_order_ref()
    assert unopened._api is None

    api = _wrapper()
    store = RegisteredSimStore(api=api, allow_writes=False)
    api.trader_client.next_order_ref = lambda: " 1001"
    with pytest.raises(BtApiStoreError, match="invalid monotonic"):
        store.registered_sim_reserve_order_ref()
    assert api.trader_client.arm_calls == []
    assert api.trader_client.native_calls == []


def test_multileg_insert_cancel_switch_is_atomic_across_threads():
    wrapper = _wrapper()
    wrapper.trader_client.block_first_native = True
    wrapper.trader_client.release_first_native.clear()
    first_errors = []
    second_errors = []
    second_started = threading.Event()

    def first_insert():
        try:
            with wrapper.registered_sim_expected_session_scope(_expected_session()):
                wrapper._send_native_order_insert(_field("rb2510", "SHFE", "insert-rb", 11), 11)
        except Exception as exc:  # surfaced below as test evidence
            first_errors.append(exc)

    def second_cancel():
        second_started.set()
        try:
            with wrapper.registered_sim_expected_session_scope(_expected_session()):
                wrapper._send_native_order_action(_field("i2509", "DCE", "cancel-i", 12), 12)
        except Exception as exc:  # surfaced below as test evidence
            second_errors.append(exc)

    first = threading.Thread(target=first_insert)
    second = threading.Thread(target=second_cancel)
    first.start()
    try:
        assert wrapper.trader_client.first_native_entered.wait(1.0)
        assert wrapper.registered_sim_execution_facts()["dispatching_order_ids"] == ["insert-rb"]
        second.start()
        assert second_started.wait(1.0)
        assert second.is_alive()  # the per-leg switch waits behind the native insert
        assert len(wrapper.trader_client.arm_calls) == 1
    finally:
        wrapper.trader_client.release_first_native.set()
        first.join(2.0)
        if second.ident is not None:
            second.join(2.0)

    assert not first.is_alive() and not second.is_alive()
    assert first_errors == [] and second_errors == []
    assert [(call[0], call[1], call[2]) for call in wrapper.trader_client.native_calls] == [
        ("insert", "rb2510", "SHFE"),
        ("cancel", "i2509", "DCE"),
    ]
    assert [item["instrument"] for item in wrapper.registered_sim_arm_history()] == [
        "rb2510",
        "i2509",
    ]
    assert all(call[3].instrument_id == call[1] for call in wrapper.trader_client.native_calls)
    assert all(call[3].exchange_id == call[2] for call in wrapper.trader_client.native_calls)
    evidence = wrapper.registered_sim_dispatch_history()
    assert [(item.operation, item.status, item.request_id) for item in evidence] == [
        ("insert", "KNOWN", 11),
        ("cancel", "KNOWN", 12),
    ]
    assert evidence[0].order_ref == "insert-rb"
    assert evidence[1].order_ref == "cancel-i"
    assert all(item.resend_permitted is False for item in evidence)


def test_disarm_waits_for_native_dispatch_and_closes_capability_afterward():
    wrapper = _wrapper()
    wrapper.trader_client.block_first_native = True
    wrapper.trader_client.release_first_native.clear()
    errors = []
    disarm_started = threading.Event()

    def insert():
        try:
            with wrapper.registered_sim_expected_session_scope(_expected_session()):
                wrapper._send_native_order_insert(_field("rb2510", "SHFE", "insert-rb", 31), 31)
        except Exception as exc:
            errors.append(exc)

    def disarm():
        disarm_started.set()
        try:
            wrapper.disarm_registered_sim_execution("race-test")
        except Exception as exc:
            errors.append(exc)

    dispatch_thread = threading.Thread(target=insert)
    disarm_thread = threading.Thread(target=disarm)
    dispatch_thread.start()
    try:
        assert wrapper.trader_client.first_native_entered.wait(1.0)
        disarm_thread.start()
        assert disarm_started.wait(1.0)
        assert disarm_thread.is_alive()
    finally:
        wrapper.trader_client.release_first_native.set()
        dispatch_thread.join(2.0)
        disarm_thread.join(2.0)

    assert not dispatch_thread.is_alive() and not disarm_thread.is_alive()
    assert errors == []
    assert wrapper.trader_client.active_capability is None
    assert wrapper.registered_sim_execution_facts()["armed_key"] is None
    assert [item.status for item in wrapper.registered_sim_dispatch_history()] == ["KNOWN"]


def test_ambiguous_native_insert_freezes_and_unknown_survives_callback_and_cache_trim():
    wrapper = _wrapper(terminal_limit=2)
    wrapper.trader_client.fail_next_insert = True

    with wrapper.registered_sim_expected_session_scope(_expected_session()), pytest.raises(
        RegisteredSimExecutionUnknown
    ):
        wrapper._send_native_order_insert(_field("rb2510", "SHFE", "unknown-1", 21), 21)

    assert wrapper._registered_sim_frozen is True
    assert wrapper._registered_sim_capability is None
    assert wrapper.registered_sim_execution_facts()["unknown_ids"] == ["unknown-1"]
    wrapper._handle_order({"OrderRef": "unknown-1", "OrderStatus": "0"})
    for index in range(5):
        wrapper._handle_order({"OrderRef": "terminal-{}".format(index), "OrderStatus": "0"})
    facts = wrapper.registered_sim_execution_facts()
    assert facts["unknown_ids"] == ["unknown-1"]
    assert len(facts["terminal_order_ids"]) == 2
    assert len(wrapper.registered_sim_arm_history()) == 1
    evidence = wrapper.registered_sim_dispatch_history()
    assert len(evidence) == 1
    assert evidence[0].status == "UNKNOWN"
    assert evidence[0].operation == "insert"
    assert evidence[0].request_id == 21
    assert evidence[0].order_ref == "unknown-1"
    assert evidence[0].error_type == "OSError"
    assert evidence[0].resend_permitted is False
    with pytest.raises(FrozenInstanceError):
        evidence[0].status = "KNOWN"
    with pytest.raises(BtApiStoreError, match="frozen"):
        wrapper.ensure_registered_sim_arm_for("i2509", "DCE")


def test_arm_history_is_bounded_and_freeze_is_permanent():
    wrapper = FakeRegisteredSimWrapper(
        registered_sim_allow_writes=True, registered_sim_history_limit=2
    )
    wrapper.configure_registered_sim_arm_templates(_templates())
    for instrument, exchange in (("rb2510", "SHFE"), ("i2509", "DCE"), ("rb2510", "SHFE")):
        wrapper.ensure_registered_sim_arm_for(instrument, exchange)
        wrapper.disarm_registered_sim_execution("between-legs")
    assert len(wrapper.registered_sim_arm_history()) == 2

    wrapper.freeze_registered_sim_execution("test-freeze")
    with pytest.raises(BtApiStoreError, match="frozen"):
        wrapper.ensure_registered_sim_arm_for("rb2510", "SHFE")


def test_failed_instrument_switch_freezes_store_and_wrapper():
    api = _wrapper()
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_configure_arm_templates(_templates())
    store.registered_sim_ensure_arm("rb2510", "SHFE")
    api.trader_client.fail_next_arm = True

    with pytest.raises(BtApiStoreError, match="admission failed"):
        store.registered_sim_ensure_arm("i2509", "DCE")

    status = store.registered_sim_status()
    assert status["armed"] is False
    assert status["frozen"] is True
    assert api.registered_sim_execution_facts()["frozen"] is True
    assert api.trader_client.active_capability is None
    assert len(api.trader_client.arm_calls) == 1
    with pytest.raises(BtApiStoreError, match="frozen"):
        store.registered_sim_ensure_arm("rb2510", "SHFE")


def test_failed_initial_arm_freezes_store_and_wrapper():
    api = _wrapper()
    api.trader_client.fail_next_arm = True
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True

    with pytest.raises(BtApiStoreError, match="admission failed"):
        store.registered_sim_arm(
            instrument="rb2510",
            exchange="SHFE",
            md_front="tcp://127.0.0.1:1",
            strategy_identity_sha256=_sha("a"),
            execution_cycle_id="cycle-rb",
            preflight_sha256=_sha("b"),
        )

    status = store.registered_sim_status()
    assert status["armed"] is False
    assert status["frozen"] is True
    assert api.registered_sim_execution_facts()["frozen"] is True
    assert api.trader_client.active_capability is None
    assert api.trader_client.native_calls == []
    with pytest.raises(BtApiStoreError, match="frozen"):
        store.registered_sim_arm(
            instrument="rb2510",
            exchange="SHFE",
            md_front="tcp://127.0.0.1:1",
            strategy_identity_sha256=_sha("a"),
            execution_cycle_id="cycle-rb",
            preflight_sha256=_sha("b"),
        )


def test_unknown_store_dispatch_freezes_and_cannot_be_retried():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    api.trader_client.fail_next_insert = True
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={"instrument_id": "rb2510", "exchange_id": "SHFE"},
        ref=23,
        isbuy=lambda: True,
        size=2,
        valid=None,
        tradeid=0,
    )

    with pytest.raises(RegisteredSimExecutionUnknown) as caught:
        store.submit_order(order)
    error = caught.value
    assert error.execution_unknown is True
    evidence = error.evidence
    assert evidence.operation == "insert"
    assert evidence.status == "UNKNOWN"
    assert evidence.request_id == 101
    assert evidence.order_ref == "native-23"
    assert evidence.resend_permitted is False
    assert store.registered_sim_status()["frozen"] is True
    assert api.registered_sim_execution_facts()["frozen"] is True
    assert len(api.trader_client.native_calls) == 1
    with pytest.raises(BtApiStoreError, match="frozen"):
        store.submit_order(order)
    assert len(api.trader_client.native_calls) == 1


def test_unknown_retirement_append_failure_keeps_latch_and_exact_retry_queues_once():
    class FailOnceDeque(collections.deque):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def append(self, item):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("synthetic queue append failure")
            return super().append(item)

    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    api.trader_client.fail_next_insert = True
    api._order_updates = FailOnceDeque()
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={"instrument_id": "rb2510", "exchange_id": "SHFE"},
        ref=23,
        isbuy=lambda: True,
        size=2,
        valid=None,
        tradeid=0,
    )

    with pytest.raises(RegisteredSimExecutionUnknown) as caught:
        store.submit_order(order)
    assert caught.value.evidence.front_id == 4
    assert caught.value.evidence.session_id == 7
    assert len(api.trader_client.native_calls) == 1
    assert api.trader_client.active_capability is None
    assert api._registered_sim_frozen is True
    assert api.registered_sim_execution_facts()["unknown_ids"] == ["native-23"]
    assert store.registered_sim_status()["frozen"] is True

    original_identity = {
        "operation": "insert",
        "backtrader_order_ref": 23,
        "order_ref": "native-23",
        "instrument_id": "rb2510",
        "exchange_id": "SHFE",
        "account_fingerprint": "fake-account-1",
        "connection_generation": 1,
        "trading_day": "20261024",
        "front_id": 4,
        "session_id": 7,
    }
    terminal_event = {
        "kind": "order",
        "bt_order_ref": 23,
        "order_ref": "native-23",
        "instrument": "rb2510",
        "exchange_id": "SHFE",
        "front_id": 4,
        "session_id": 7,
        "status": "canceled",
        "terminal_confirmed": True,
        "execution_unknown": False,
        "filled": 0,
        "size": 2,
        "remaining": 2,
        "details": {
            "OrderRef": "native-23",
            "InstrumentID": "rb2510",
            "ExchangeID": "SHFE",
            "FrontID": 4,
            "SessionID": 7,
            "OrderStatus": "5",
            "VolumeTotalOriginal": 2,
            "VolumeTraded": 0,
            "VolumeTotal": 2,
        },
    }
    retirement = {
        "intent_id": "intent-23",
        "reconciliation_id": "reconciliation-23",
        "original_identity": original_identity,
        "expected_session": _expected_session(),
        "terminal_event": terminal_event,
    }

    with pytest.raises(BtApiStoreError, match="update enqueue failed"):
        store.registered_sim_retire_unknown(**retirement)

    assert api._order_updates.attempts == 1
    assert len(api._order_updates) == 0
    assert api._registered_sim_frozen is True
    assert api.registered_sim_execution_facts()["unknown_ids"] == ["native-23"]
    assert store.registered_sim_status()["frozen"] is True
    assert api.trader_client.active_capability is None
    assert api.trader_client.get_execution_gate_state()["armed"] is False
    assert len(api.trader_client.native_calls) == 1

    queued = store.registered_sim_retire_unknown(**retirement)
    assert queued.status == "QUEUED"
    assert queued.disarmed is True
    assert api._order_updates.attempts == 2
    assert len(api._order_updates) == 1
    assert api._registered_sim_frozen is False
    assert api.registered_sim_execution_facts()["unknown_ids"] == []
    assert store.registered_sim_status()["frozen"] is False
    assert len(api.trader_client.native_calls) == 1

    duplicate = store.registered_sim_retire_unknown(**retirement)
    assert duplicate.status == "ALREADY_ABSENT"
    assert len(api._order_updates) == 1
    assert api._order_updates.attempts == 2
    assert store.poll_broker_update() == terminal_event
    assert store.poll_broker_update() is None
    assert store.registered_sim_retire_unknown(**retirement).status == "ALREADY_ABSENT"
    assert len(api._order_updates) == 0


@pytest.mark.parametrize("mismatch", ["cancel_child", "parent_intent", "order_ref", "front_id"])
def test_unknown_cancel_retirement_rejects_mismatched_lineage_and_retries_after_queue_failure(
    mismatch,
):
    class FailOnceDeque(collections.deque):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        def append(self, item):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("synthetic queue append failure")
            return super().append(item)

    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    api._order_updates = FailOnceDeque()
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=12.5,
        pricelimit=None,
        created=SimpleNamespace(price=12.5),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={"instrument_id": "rb2510", "exchange_id": "SHFE"},
        ref=23,
        isbuy=lambda: True,
        size=2,
        valid=None,
        tradeid=0,
    )
    response = store.submit_order(order)
    order.info["external_order_id"] = response["order_ref"]
    api.trader_client.fail_next_cancel = True
    with pytest.raises(RegisteredSimExecutionUnknown) as caught:
        store.cancel_order(order)

    assert caught.value.evidence.operation == "cancel"
    assert caught.value.evidence.status == "UNKNOWN"
    assert caught.value.evidence.order_ref == response["order_ref"]
    assert (caught.value.evidence.front_id, caught.value.evidence.session_id) == (4, 7)
    assert len(api.trader_client.native_calls) == 2

    original_identity = {
        "operation": "cancel",
        "owner_intent_id": "open-intent",
        "backtrader_order_ref": 23,
        "order_ref": response["order_ref"],
        "instrument_id": "rb2510",
        "exchange_id": "SHFE",
        "account_fingerprint": "fake-account-1",
        "connection_generation": 1,
        "trading_day": "20261024",
        "front_id": 4,
        "session_id": 7,
    }
    terminal_event = {
        "kind": "order",
        "bt_order_ref": 23,
        "order_ref": response["order_ref"],
        "instrument": "rb2510",
        "exchange_id": "SHFE",
        "front_id": 4,
        "session_id": 7,
        "status": "canceled",
        "side": "buy",
        "size": 2,
        "filled": 0,
        "remaining": 2,
        "terminal_confirmed": True,
        "execution_unknown": False,
        "factor_intent_id": "open-intent",
        "factor_cancel_intent_id": "cancel-intent",
        "details": {
            "OrderRef": response["order_ref"],
            "InstrumentID": "rb2510",
            "ExchangeID": "SHFE",
            "FrontID": 4,
            "SessionID": 7,
            "OrderStatus": "5",
            "VolumeTotalOriginal": 2,
            "VolumeTraded": 0,
            "VolumeTotal": 2,
        },
    }
    retirement = {
        "intent_id": "cancel-intent",
        "reconciliation_id": "cancel-reconciliation",
        "original_identity": original_identity,
        "expected_session": _expected_session(),
        "terminal_event": terminal_event,
    }

    # A durable proof cannot clear the latch if publishing its one normal
    # Broker update fails. The same proof may retry the append once.
    with pytest.raises(BtApiStoreError, match="update enqueue failed"):
        store.registered_sim_retire_unknown(**retirement)
    assert api._registered_sim_frozen is True
    assert api.registered_sim_execution_facts()["unknown_ids"] == [response["order_ref"]]
    assert store.registered_sim_status()["frozen"] is True
    assert api._order_updates.attempts == 1
    assert len(api._order_updates) == 0
    assert len(api.trader_client.native_calls) == 2

    invalid = copy.deepcopy(retirement)
    if mismatch == "cancel_child":
        invalid["intent_id"] = "different-cancel-intent"
    elif mismatch == "parent_intent":
        invalid["terminal_event"]["factor_intent_id"] = "different-open-intent"
    elif mismatch == "order_ref":
        invalid["original_identity"]["order_ref"] = "native-999"
    else:
        invalid["original_identity"]["front_id"] = 5
    with pytest.raises(BtApiStoreError):
        store.registered_sim_retire_unknown(**invalid)
    assert api._registered_sim_frozen is True
    assert api.registered_sim_execution_facts()["unknown_ids"] == [response["order_ref"]]
    assert store.registered_sim_status()["frozen"] is True
    assert len(api._order_updates) == 0
    assert len(api.trader_client.native_calls) == 2

    result = store.registered_sim_retire_unknown(**retirement)
    assert result.status == "QUEUED"
    assert result.disarmed is True
    assert api._registered_sim_frozen is False
    assert api.registered_sim_execution_facts()["unknown_ids"] == []
    assert store.registered_sim_status()["frozen"] is False
    assert api._order_updates.attempts == 2
    assert len(api._order_updates) == 1
    assert len(api.trader_client.native_calls) == 2
    assert store.poll_broker_update() == terminal_event
    assert store.poll_broker_update() is None
    duplicate = store.registered_sim_retire_unknown(**retirement)
    assert duplicate.status == "ALREADY_ABSENT"
    assert len(api._order_updates) == 0
    assert api._order_updates.attempts == 2


def _complete_query_result(api, request_type, *, request_id, records=(), filters=()):
    started = datetime.now(timezone.utc)
    completed = datetime.now(timezone.utc)
    now = time.monotonic()
    source = SimpleNamespace(
        issuer=api.trader_client._query_issuer,
        request_type=request_type,
        request_id=request_id,
        connection_generation=1,
        account_fingerprint="fake-account-1",
        trading_day="20261024",
        started_at_utc=started,
        completed_at_utc=completed,
        started_monotonic=now - 0.001,
        completed_monotonic=now,
        trusted_expires_monotonic=now + 30.0,
        records_sha256=_sha("e"),
        explicit_request_filters=tuple(filters),
    )
    return SimpleNamespace(
        request_type=request_type,
        request_id=request_id,
        connection_generation=1,
        account_fingerprint="fake-account-1",
        started_at_utc=started,
        completed_at_utc=completed,
        is_last_seen=True,
        error_code=None,
        error_message="",
        timed_out=False,
        complete=True,
        records=tuple(records),
        late_callback_count=0,
        unsupported=False,
        submit_code=0,
        query_source=source,
    )


def test_missing_query_completion_facts_stay_unobserved_and_risk_health_closed():
    api = _wrapper(allow_writes=False)
    api.query_account_result = lambda **kwargs: SimpleNamespace(
        records=(),
        timed_out=False,
        request_id=1,
        connection_generation=1,
        account_fingerprint="fake-account-1",
        completed_at_utc=datetime.now(timezone.utc),
    )
    store = RegisteredSimStore(api=api)
    store._connected = True

    with pytest.raises(BtApiStoreError, match="unobserved or incomplete"):
        store.registered_sim_query("account_result", attempts=1)

    assert store.get_registered_sim_query_snapshot("account_result") is None
    health = store.get_ctp_query_health()
    assert store.supports_complete_ctp_queries() is False
    assert health["evidence_complete"] is False
    assert health["unknown_intent_count"] is None  # incomplete source facts are not zero
    assert health["unmatched_trade_count"] is None  # no completed trade query facts


def test_only_complete_current_source_queries_enable_query_health():
    api = _wrapper(allow_writes=False)
    api.query_account_result = lambda **kwargs: _complete_query_result(api, "account", request_id=1)
    api.query_positions_result = lambda **kwargs: _complete_query_result(
        api, "positions", request_id=2
    )
    api.query_orders_result = lambda **kwargs: _complete_query_result(api, "orders", request_id=3)
    api.query_trades_result = lambda **kwargs: _complete_query_result(api, "trades", request_id=4)
    api.query_instruments_result = lambda **kwargs: _complete_query_result(
        api,
        "instruments",
        records=[{"InstrumentID": "rb2510", "ExchangeID": "SHFE", "IsTrading": 1}],
        request_id=5,
    )
    store = RegisteredSimStore(api=api)
    store._connected = True

    for family in (
        "account_result",
        "positions_result",
        "orders_result",
        "trades_result",
        "instruments_result",
    ):
        assert store.registered_sim_query(family)["query_complete"] is True

    health = store.get_ctp_query_health()
    assert store.supports_complete_ctp_queries(include_reference_data=True) is True
    assert health["evidence_complete"] is True
    assert health["unknown_intent_count"] == 0
    assert health["unmatched_trade_count"] == 0
    assert health["instruments"] == [
        {"instrument_id": "rb2510", "exchange_id": "SHFE", "is_trading": True}
    ]

    api.trader_client._connection_generation = 2
    assert store.supports_complete_ctp_queries(include_reference_data=True) is False
    assert store.get_ctp_query_health()["evidence_complete"] is False


def test_route_eligibility_is_a_read_only_projection_not_write_authorization():
    api = _wrapper(allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True

    api.query_account_result = lambda **kwargs: _complete_query_result(api, "account", request_id=1)
    api.query_positions_result = lambda **kwargs: _complete_query_result(
        api, "positions", request_id=2
    )
    api.query_orders_result = lambda **kwargs: _complete_query_result(api, "orders", request_id=3)
    api.query_trades_result = lambda **kwargs: _complete_query_result(api, "trades", request_id=4)
    api.query_instruments_result = lambda **kwargs: _complete_query_result(
        api,
        "instruments",
        request_id=5,
        records=[{"InstrumentID": "rb2510", "ExchangeID": "SHFE", "IsTrading": 1}],
    )

    for family in (
        "account_result",
        "positions_result",
        "orders_result",
        "trades_result",
        "instruments_result",
    ):
        store.registered_sim_query(family, attempts=1)
    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    facts = store.registered_sim_route_eligibility("rb2510", "SHFE")

    assert facts.route_name == "ctp/direct/registered-sim"
    assert facts.instrument_id == "rb2510" and facts.exchange_id == "SHFE"
    assert facts.account_fingerprint == "fake-account-1"
    assert facts.connection_generation == 1 and facts.trading_day == "20261024"
    assert facts.allow_writes is True
    assert facts.instrument_query_complete is True
    assert facts.instrument_eligible is True
    assert facts.capability_observed is True
    assert facts.capability_matches_route is True
    assert facts.native_admission_required is True
    assert "shadow_mode" not in facts.reason_codes
    assert not hasattr(facts, "dispatch_authorized")


def test_template_routes_are_plannable_before_first_grant_and_switch_serially():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    templates = _three_route_templates()
    store.registered_sim_configure_arm_templates(templates)
    api.query_account_result = lambda **kwargs: _complete_query_result(api, "account", request_id=1)
    api.query_positions_result = lambda **kwargs: _complete_query_result(
        api, "positions", request_id=2
    )
    api.query_orders_result = lambda **kwargs: _complete_query_result(api, "orders", request_id=3)
    api.query_trades_result = lambda **kwargs: _complete_query_result(api, "trades", request_id=4)
    api.query_instruments_result = lambda **kwargs: _complete_query_result(
        api,
        "instruments",
        request_id=5,
        records=[
            {"InstrumentID": instrument, "ExchangeID": exchange, "IsTrading": 1}
            for instrument, exchange in templates
        ],
    )
    for family in (
        "account_result",
        "positions_result",
        "orders_result",
        "trades_result",
        "instruments_result",
    ):
        store.registered_sim_query(family, attempts=1)

    for instrument, exchange in templates:
        route = store.registered_sim_route_eligibility(instrument, exchange)
        assert route.instrument_query_complete is True
        assert route.instrument_eligible is True
        assert route.allow_writes is True
        assert route.capability_observed is True
        assert route.sdk_capability_managed is False
        assert route.sdk_capability_armed is False
        assert route.capability_matches_route is False
        assert route.arm_templates_configured is True
        assert route.arm_template_configured is True
        assert route.arm_api_available is True
        assert route.current_session_account_fingerprint == "fake-account-1"
        assert route.current_session_connection_generation == 1
        assert route.current_session_trading_day == "20261024"
        assert route.current_session_trading_ready is True

    # The configured template map is a wrapper-lifetime route allowlist. An
    # exact repeat is harmless; a changed or omitted route cannot widen it.
    store.registered_sim_configure_arm_templates(templates)
    changed = dict(templates)
    changed[("au2510", "SHFE")] = templates[("cu2510", "SHFE")]
    with pytest.raises(BtApiStoreError, match="immutable"):
        store.registered_sim_configure_arm_templates(changed)

    def make_order(instrument, exchange, ref):
        return SimpleNamespace(
            exectype=OrderBase.Limit,
            price=100.0,
            pricelimit=None,
            created=SimpleNamespace(price=100.0),
            data=SimpleNamespace(_name=instrument, _dataname=instrument),
            info={"instrument_id": instrument, "exchange_id": exchange},
            ref=ref,
            isbuy=lambda: True,
            size=1,
            valid=None,
            tradeid=0,
        )

    routes = [("rb2510", "SHFE"), ("i2509", "DCE"), ("cu2510", "SHFE")]
    expected_session = {
        "account_fingerprint": "fake-account-1",
        "connection_generation": 1,
        "trading_day": "20261024",
    }
    for ref, (instrument, exchange) in enumerate(routes, start=1):
        store.registered_sim_ensure_arm(instrument, exchange, expected_session=expected_session)
        order = make_order(instrument, exchange, ref)
        order.info.update(
            {
                "factor_session_account_fingerprint": expected_session["account_fingerprint"],
                "factor_session_connection_generation": expected_session["connection_generation"],
                "factor_session_trading_day": expected_session["trading_day"],
            }
        )
        store.submit_order(order)

    assert [call[0]["instrument_id"] for call in api.trader_client.arm_calls] == [
        "rb2510",
        "i2509",
        "cu2510",
    ]
    assert [(call[0], call[1], call[2]) for call in api.trader_client.native_calls] == [
        ("insert", "rb2510", "SHFE"),
        ("insert", "i2509", "DCE"),
        ("insert", "cu2510", "SHFE"),
    ]
    assert api.trader_client.active_capability.instrument_id == "cu2510"


def test_same_key_sdk_rearm_invalidates_cached_proof_and_route_projection():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    template = _templates()[("rb2510", "SHFE")]
    store.registered_sim_configure_arm_templates({("rb2510", "SHFE"): template})

    admitted = store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front=template["md_front"],
        strategy_identity_sha256=template["strategy_identity_sha256"],
        execution_cycle_id=template["execution_cycle_id"],
        preflight_sha256=template["preflight_sha256"],
    )
    # Mutating the returned diagnostic must not mutate the wrapper's cached
    # immutable proof tuple.
    admitted["state"]["authorized_instruments"].clear()
    route = store.registered_sim_route_eligibility("rb2510", "SHFE")
    assert route.capability_matches_route is True

    # Model an SDK-side same-instrument/same-session re-arm with a different
    # signed proof. The opaque core capability and local route key stay the
    # same, so only a proof-snapshot comparison detects the replacement.
    api.trader_client.active_capability.proof_sha256 = "f" * 64
    route = store.registered_sim_route_eligibility("rb2510", "SHFE")
    assert route.sdk_capability_armed is True
    assert route.capability_matches_route is False

    expected_session = {
        "account_fingerprint": "fake-account-1",
        "connection_generation": 1,
        "trading_day": "20261024",
    }
    with pytest.raises(BtApiStoreError, match="stale or mismatched"):
        store.registered_sim_ensure_arm("rb2510", "SHFE", expected_session=expected_session)
    assert api.trader_client.native_calls == []


def test_template_route_missing_from_nonempty_map_never_falls_back_to_current_grant():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_configure_arm_templates(
        {("rb2510", "SHFE"): _templates()[("rb2510", "SHFE")]}
    )

    route = store.registered_sim_route_eligibility("i2509", "DCE")
    assert route.arm_templates_configured is True
    assert route.arm_template_configured is None
    assert route.arm_api_available is True

    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=100.0,
        pricelimit=None,
        created=SimpleNamespace(price=100.0),
        data=SimpleNamespace(_name="i2509", _dataname="i2509"),
        info={"instrument_id": "i2509", "exchange_id": "DCE"},
        ref=9,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )
    with pytest.raises(BtApiStoreError, match="template"):
        store.registered_sim_ensure_arm("i2509", "DCE")
    with pytest.raises(BtApiStoreError):
        store.submit_order(order)
    assert api.trader_client.arm_calls == []
    assert api.trader_client.native_calls == []


def test_sealed_empty_template_map_rejects_active_grant_and_direct_writes():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_configure_arm_templates({})
    # Even an explicit SDK grant cannot expand a sealed empty route allowlist.
    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    route = store.registered_sim_route_eligibility("rb2510", "SHFE")
    assert route.arm_templates_configured is True
    assert route.arm_template_configured is False
    assert route.capability_matches_route is True
    assert route.arm_api_available is True

    session_info = {
        "factor_session_account_fingerprint": "fake-account-1",
        "factor_session_connection_generation": 1,
        "factor_session_trading_day": "20261024",
    }
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=100.0,
        pricelimit=None,
        created=SimpleNamespace(price=100.0),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={"instrument_id": "rb2510", "exchange_id": "SHFE", **session_info},
        ref=12,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )
    with pytest.raises(BtApiStoreError, match="arm template"):
        store.submit_order(order)
    assert api.trader_client.native_calls == []

    # Public direct cancel-ref is subject to the same route and session gate.
    api._pending_orders["native-12"] = {
        "order_ref": "native-12",
        "instrument": "rb2510",
        "exchange_id": "SHFE",
    }
    order.info["external_order_id"] = "native-12"
    with pytest.raises(BtApiStoreError, match="arm template"):
        store.cancel_order(order)
    with pytest.raises(BtApiStoreError, match="template-bound|arm template"):
        store.cancel_order_ref("native-12", dataname="rb2510.SHFE")
    assert api.trader_client.native_calls == []


def test_final_store_hook_rejects_stale_decision_session_before_native_call():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    templates = _templates()
    store.registered_sim_configure_arm_templates(templates)
    expected = {
        "account_fingerprint": "fake-account-1",
        "connection_generation": 1,
        "trading_day": "20261024",
    }
    store.registered_sim_ensure_arm("rb2510", "SHFE", expected_session=expected)
    api.trader_client._connection_generation = 2

    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=100.0,
        pricelimit=None,
        created=SimpleNamespace(price=100.0),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={
            "instrument_id": "rb2510",
            "exchange_id": "SHFE",
            "factor_session_account_fingerprint": expected["account_fingerprint"],
            "factor_session_connection_generation": expected["connection_generation"],
            "factor_session_trading_day": expected["trading_day"],
        },
        ref=10,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )
    with pytest.raises(BtApiStoreError, match="session identity is stale"):
        store.submit_order(order)
    assert api.trader_client.native_calls == []


def test_factor_intent_cannot_fall_back_to_unbound_legacy_store_hooks():
    api = FakeRegisteredSimWrapper(registered_sim_allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    store.registered_sim_arm(
        instrument="rb2510",
        exchange="SHFE",
        md_front="tcp://127.0.0.1:1",
        strategy_identity_sha256=_sha("a"),
        execution_cycle_id="cycle-rb",
        preflight_sha256=_sha("b"),
    )
    order = SimpleNamespace(
        exectype=OrderBase.Limit,
        price=100.0,
        pricelimit=None,
        created=SimpleNamespace(price=100.0),
        data=SimpleNamespace(_name="rb2510", _dataname="rb2510"),
        info={
            "instrument_id": "rb2510",
            "exchange_id": "SHFE",
            "factor_intent_id": "intent-1",
        },
        ref=11,
        isbuy=lambda: True,
        size=1,
        valid=None,
        tradeid=0,
    )

    with pytest.raises(BtApiStoreError, match="missing its expected session identity"):
        store.submit_order(order)
    assert api.trader_client.native_calls == []

    # Cancellation reuses the Order instance and has its own intent marker.
    # It must be bound to the current query-set identity as well.
    order.info.pop("factor_intent_id")
    order.info.update(
        {
            "factor_cancel_intent_id": "cancel-1",
            "external_order_id": "native-11",
        }
    )
    with pytest.raises(BtApiStoreError, match="missing its expected session identity"):
        store.cancel_order(order)
    assert api.trader_client.native_calls == []


def test_route_projection_keeps_session_identity_when_not_trading_ready():
    api = _wrapper(allow_writes=True)
    store = RegisteredSimStore(api=api, allow_writes=True)
    store._connected = True
    api.trader_client.is_ready = False

    route = store.registered_sim_route_eligibility("rb2510", "SHFE")
    assert route.current_session_account_fingerprint == "fake-account-1"
    assert route.current_session_connection_generation == 1
    assert route.current_session_trading_day == "20261024"
    assert route.current_session_trading_ready is False


def test_instrument_eligibility_stays_unobserved_for_malformed_full_query_rows():
    api = _wrapper(allow_writes=False)
    store = RegisteredSimStore(api=api)
    store._connected = True
    api.query_account_result = lambda **kwargs: _complete_query_result(api, "account", request_id=1)
    api.query_positions_result = lambda **kwargs: _complete_query_result(
        api, "positions", request_id=2
    )
    api.query_orders_result = lambda **kwargs: _complete_query_result(api, "orders", request_id=3)
    api.query_trades_result = lambda **kwargs: _complete_query_result(api, "trades", request_id=4)
    api.query_instruments_result = lambda **kwargs: _complete_query_result(
        api, "instruments", request_id=5, records=[{"InstrumentID": "rb2510"}]
    )
    for family in (
        "account_result",
        "positions_result",
        "orders_result",
        "trades_result",
        "instruments_result",
    ):
        store.registered_sim_query(family, attempts=1)

    facts = store.registered_sim_route_eligibility("rb2510", "SHFE")
    assert facts.instrument_query_complete is True
    assert facts.instrument_eligible is None
    assert "instrument_eligibility_unobserved" in facts.reason_codes


def test_filtered_queries_are_complete_but_do_not_claim_full_scope():
    api = _wrapper(allow_writes=False)
    api.query_orders_result = lambda **kwargs: _complete_query_result(
        api,
        "orders",
        request_id=8,
        filters=("InstrumentID",),
    )
    store = RegisteredSimStore(api=api)
    store._connected = True

    result = store.registered_sim_query("orders_result", instrument_id="rb2510", attempts=1)

    assert result["query_complete"] is True
    assert result["scope_complete"] is False
    snapshot = store.get_registered_sim_query_snapshot("orders_result", instrument_id="rb2510")
    assert snapshot["query_complete"] is True
    assert snapshot["scope_complete"] is False
    assert snapshot["query_filters"] == {"instrument_id": "rb2510"}
    assert store.supports_complete_ctp_queries() is False
    assert store.get_ctp_query_health()["evidence_complete"] is False


def test_query_snapshot_is_no_io_detached_and_bound_to_current_session():
    api = _wrapper(allow_writes=False)
    query_calls = []
    api.query_account_result = lambda **kwargs: (
        query_calls.append(dict(kwargs))
        or _complete_query_result(
            api,
            "account",
            request_id=1,
            records=[{"Available": 123.5}],
        )
    )
    store = RegisteredSimStore(api=api)
    store._connected = True

    assert store.get_registered_sim_query_snapshot("account_result") is None
    result = store.registered_sim_query("account_result", attempts=1)
    assert result["query_complete"] is True
    first = store.get_registered_sim_query_snapshot("account_result")
    assert first["family"] == "account_result"
    assert first["request_id"] == 1
    assert first["connection_generation"] == 1
    assert first["account_fingerprint"] == "fake-account-1"
    assert first["trading_day"] == "20261024"
    assert first["source_owned"] is True
    assert first["scope_complete"] is True
    assert first["source_explicit_request_filters"] == ()
    assert isinstance(first["completed_at_utc"], datetime)
    assert first["rows"] == [{"Available": 123.5}]
    assert query_calls == [{"timeout": 8.0}]

    first["rows"][0]["Available"] = -1
    second = store.get_registered_sim_query_snapshot("account_result")
    assert second["rows"] == [{"Available": 123.5}]
    assert query_calls == [{"timeout": 8.0}]  # snapshot reads never issue another SDK query

    api.trader_client._connection_generation = 2
    assert store.get_registered_sim_query_snapshot("account_result") is None


def test_margin_query_snapshots_are_keyed_by_exact_contract_filters():
    api = _wrapper(allow_writes=False)
    request_ids = iter((11, 12))

    def query_margin(*, instrument_id, exchange_id, hedge_flag, **kwargs):
        return _complete_query_result(
            api,
            "margin_rate",
            request_id=next(request_ids),
            records=[
                {
                    "InstrumentID": instrument_id,
                    "ExchangeID": exchange_id,
                    "HedgeFlag": hedge_flag,
                    "LongMarginRatioByMoney": 0.12,
                }
            ],
            filters=("HedgeFlag",),
        )

    api.query_instrument_margin_rate_result = query_margin
    store = RegisteredSimStore(api=api)
    store._connected = True
    store.registered_sim_query(
        "instrument_margin_rate_result",
        instrument_id="rb2510",
        exchange_id="SHFE",
        hedge_flag="1",
        attempts=1,
    )
    store.registered_sim_query(
        "instrument_margin_rate_result",
        instrument_id="cu2510",
        exchange_id="SHFE",
        hedge_flag="1",
        attempts=1,
    )

    rb = store.get_registered_sim_query_snapshot(
        "instrument_margin_rate_result",
        instrument_id="rb2510",
        exchange_id="SHFE",
        hedge_flag="1",
    )
    cu = store.get_registered_sim_query_snapshot(
        "instrument_margin_rate_result",
        instrument_id="cu2510",
        exchange_id="SHFE",
        hedge_flag="1",
    )
    assert rb["request_id"] == 11 and rb["rows"][0]["InstrumentID"] == "rb2510"
    assert cu["request_id"] == 12 and cu["rows"][0]["InstrumentID"] == "cu2510"
    assert rb["source_explicit_request_filters"] == ("HedgeFlag",)
    assert rb["scope_complete"] is False
    assert (
        store.get_registered_sim_query_snapshot(
            "instrument_margin_rate_result",
            instrument_id="rb2510",
            exchange_id="SHFE",
        )
        is None
    )
