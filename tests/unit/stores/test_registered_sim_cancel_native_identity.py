"""End-to-end fake-SDK proof for RegisteredSim's CTP cancel Action identity.

The Store and RegisteredSimWrapper are real.  The CTP client class is produced
by ``BtApiStore._create_ctp_wrapper_class`` with only its generated native
field class and SDK leaves replaced.  In particular, the fake SDK receives the
Action built by the production CtpClientWrapper.cancel_order method.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import sqlite3
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType, ModuleType, SimpleNamespace

import pytest

from backtrader.stores import execution_decision_journal as execution_decision_journal_module
from backtrader.stores import registered_sim as registered_sim_module
from backtrader.stores import btapistore
from backtrader.stores.btapistore import BtApiStoreError
from tests.test_utils.execution_journal_schema import (
    drop_empty_fee_pair_tables_from_version,
)
from tests.unit.stores import test_factor_execution as factor_helpers
from tests.unit.stores import test_factor_execution_facts as facts_helpers


class _NativeActionField:
    """Simple replacement for the generated SWIG CTP Action struct."""

    _fields = (
        "BrokerID",
        "InvestorID",
        "UserID",
        "InstrumentID",
        "InvestUnitID",
        "ActionFlag",
        "ExchangeID",
        "OrderSysID",
        "OrderRef",
        "FrontID",
        "SessionID",
        "RequestID",
        "OrderActionRef",
    )

    def __init__(self):
        for name in self._fields:
            setattr(self, name, None)


class _NativeTrader(facts_helpers._QueryClient):
    """Synthetic SDK leaf that captures, but never constructs, native fields."""

    def __init__(self):
        super().__init__()
        self._req_id = 100
        self._active_capability = None
        self.native_actions = []
        self.native_action_deadlines = []
        self.native_inserts = []
        self.provider_insert_identity = None

    def arm_execution_for_registered_sim(self, **kwargs):
        state = dict(self._gate_state)
        state.update(
            {
                "managed": True,
                "armed": True,
                "instrument": kwargs["instrument_id"],
                "authorized_instruments": [kwargs["instrument_id"]],
                "connection_generation": self._connection_generation,
                "trading_day": self._trading_day,
            }
        )
        self._gate_state = state
        capability = SimpleNamespace(
            instrument_id=kwargs["instrument_id"],
            exchange_id=kwargs["exchange_id"],
            connection_generation=self._connection_generation,
            trading_day=self._trading_day,
        )
        self._active_capability = capability
        return capability, dict(state)

    def next_order_ref(self):
        self._next_order_reference = getattr(self, "_next_order_reference", 500) + 1
        return str(self._next_order_reference)

    def disarm_execution_gate(self, capability, _reason):
        assert capability is self._active_capability
        self._active_capability = None
        self._gate_state.update(
            {
                "managed": False,
                "armed": False,
                "instrument": None,
                "authorized_instruments": [],
            }
        )
        return {"revoked": True}

    def _receive(self, operation, field, request_id, execution_capability):
        assert execution_capability is self._active_capability
        assert type(request_id) is int and request_id > 0
        assert field.RequestID == request_id
        assert field.InstrumentID == execution_capability.instrument_id
        assert field.ExchangeID == execution_capability.exchange_id
        if operation == "cancel":
            self.native_actions.append((field, request_id, execution_capability))
        else:
            self.native_inserts.append((field, request_id, execution_capability))
        return 0

    def submit_order_insert(self, field, request_id, *, execution_capability):
        # A narrow legacy-provider fixture can persist a KNOWN submit receipt
        # that already carries SysID/account identity.  This models the
        # no-query-binding compatibility branch; it does not claim that CTP
        # insert requests normally contain these response fields.
        if self.provider_insert_identity is not None:
            for name, value in self.provider_insert_identity.items():
                setattr(field, name, value)
        return self._receive("insert", field, request_id, execution_capability)

    def submit_order_action(
        self, field, request_id, *, execution_capability, deadline_monotonic=None
    ):
        # Store the exact object passed by CtpClientWrapper; do not derive any
        # field from a target, order, callback, or private provider map here.
        self.native_action_deadlines.append(deadline_monotonic)
        return self._receive("cancel", field, request_id, execution_capability)


class _SdkNativeApi:
    """A no-network CTP API leaf for the real SDK TraderClient source."""

    def __init__(self):
        self.calls = []
        self.order_action_error = None
        self.order_action_hook = None
        self.trader = None
        self.trader_spi = None

    def ReqOrderInsert(self, field, request_id):
        provider_identity = getattr(self.trader, "provider_insert_identity", None)
        if provider_identity is not None:
            for name, value in provider_identity.items():
                setattr(field, name, value)
        self.calls.append(("insert", field, request_id))
        # Drive the real SDK callback entrypoint for a successful native
        # response. This advances the canonical TraderClient evidence history
        # used by query-derived SysID binding; the fake leaf never edits SDK
        # history or manufactures a callback receipt itself.
        if provider_identity is None:
            assert self.trader_spi is not None
            self.trader_spi.OnRspOrderInsert(
                field,
                SimpleNamespace(ErrorID=0, ErrorMsg=""),
                request_id,
                True,
            )
        return 0

    def ReqOrderAction(self, field, request_id):
        self.calls.append(("cancel", field, request_id))
        if self.order_action_hook is not None:
            self.order_action_hook(field, request_id)
        if self.order_action_error is not None:
            raise self.order_action_error
        return 0


class _ObservedRLock:
    """Expose a real RLock contention boundary for the SDK deadline test."""

    def __init__(self):
        self._lock = threading.RLock()
        self._owner_lock = threading.Lock()
        self._owner_thread_id = None
        self._owner_depth = 0
        self._pause_after_release_thread = None
        self._pause_consumed = False
        self.outer_release_paused = threading.Event()
        self.allow_outer_release = threading.Event()
        self.contended = threading.Event()
        self.native_lock_waited = threading.Event()

    def acquire(self, blocking=True, timeout=-1):
        thread_id = threading.get_ident()
        with self._owner_lock:
            blocked_by_other = (
                self._owner_thread_id is not None and self._owner_thread_id != thread_id
            )
        if blocked_by_other:
            self.contended.set()
            acquired = self._lock.acquire(timeout=0.01)
            if not acquired:
                self.native_lock_waited.set()
                acquired = self._lock.acquire(blocking, timeout)
        else:
            acquired = self._lock.acquire(blocking, timeout)
        if acquired:
            with self._owner_lock:
                if self._owner_thread_id == thread_id:
                    self._owner_depth += 1
                else:
                    self._owner_thread_id = thread_id
                    self._owner_depth = 1
        return acquired

    def release(self):
        thread_id = threading.get_ident()
        pause_after_release = False
        with self._owner_lock:
            if self._owner_thread_id != thread_id:
                raise RuntimeError("SDK state lock released by a non-owner")
            self._owner_depth -= 1
            if self._owner_depth == 0:
                self._owner_thread_id = None
                pause_after_release = (
                    self._pause_after_release_thread == thread_id and not self._pause_consumed
                )
                if pause_after_release:
                    self._pause_consumed = True
        self._lock.release()
        if pause_after_release:
            self.outer_release_paused.set()
            if not self.allow_outer_release.wait(timeout=5):
                raise RuntimeError("SDK lock holder did not take the released lock")

    def pause_after_next_outer_release(self, thread_id):
        with self._owner_lock:
            self._pause_after_release_thread = thread_id

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("controlled SDK lock wait timed out")
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        self.release()
        return False


class _FakeMonotonicClock:
    def __init__(self, now=None):
        self.now = now
        self._real_monotonic = time.monotonic

    def monotonic(self):
        return self._real_monotonic() if self.now is None else self.now


class _InterruptingMapping(Mapping):
    """Mapping whose Store-side publication raises one exact interruption."""

    def __init__(self, interrupt):
        self.interrupt = interrupt

    def __getitem__(self, key):
        raise KeyError(key)

    def __iter__(self):
        raise self.interrupt

    def __len__(self):
        return 0

    def keys(self):
        raise self.interrupt


def _load_sdk_source(monkeypatch):
    """Import the sibling bt_api_py CTP source, never an installed old copy."""

    sdk_source_root = next(
        (
            parent / "bt_api_py" / "bt_api" / "bt_api_ctp" / "src"
            for parent in Path(__file__).resolve().parents
            if (parent / "bt_api_py" / "bt_api" / "bt_api_ctp" / "src").is_dir()
        ),
        None,
    )
    if sdk_source_root is None:
        pytest.skip("the bt_api_ctp source checkout is not available")
    sdk_base_source_root = sdk_source_root.parents[1] / "bt_api_base" / "src"
    if not sdk_base_source_root.is_dir():
        pytest.skip("the bt_api_base source checkout is not available")

    for module_name in tuple(sys.modules):
        if module_name == "bt_api_ctp" or module_name.startswith("bt_api_ctp."):
            monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.syspath_prepend(str(sdk_base_source_root))
    monkeypatch.syspath_prepend(str(sdk_source_root))
    sdk_client = importlib.import_module("bt_api_ctp.ctp.client")
    # Store the selector in sys.modules before the fake struct modules are
    # installed below; TraderClient imports it lazily while arming.
    importlib.import_module("bt_api_ctp.ctp_env_selector")
    expected_path = sdk_source_root / "bt_api_ctp" / "ctp" / "client.py"
    assert Path(sdk_client.__file__).resolve() == expected_path.resolve()
    assert inspect.signature(sdk_client.TraderClient.submit_order_action).parameters[
        "deadline_monotonic"
    ].kind is inspect.Parameter.KEYWORD_ONLY
    return sdk_client


def _real_sdk_trader(sdk_client_module, *, trader_type=None):
    """Build a trading-ready SDK client using only a synthetic native leaf."""

    td_front = "tcp://182.254.243.31:30002"
    native = _SdkNativeApi()
    client_cls = trader_type or sdk_client_module.TraderClient
    client = client_cls(
        td_front, "fake-broker", "fake-investor", "synthetic-password"
    )
    native.trader = client
    native.trader_spi = sdk_client_module._TraderSpi(client)
    client._api = native
    client._session_native_api = native
    client._session_native_front = td_front
    # The provider-query fixture emits deterministic receipts through its
    # private _QuerySource shape. Bind that issuer/account view to the actual
    # TraderClient's synthetic authenticated query scope.
    client._query_issuer = client._query_evidence_issuer
    client._broker_id = "fake-broker"
    client._investor_id = "fake-investor"
    client._connected = True
    client._authentication_state = "authenticated"
    client._login_state = "logging_in"
    client._connection_generation = 1
    client._login_request_id = 1
    client._login_connection_generation = 1
    native.trader_spi.OnRspUserLogin(
        SimpleNamespace(
            BrokerID="fake-broker",
            UserID="fake-investor",
            FrontID=4,
            SessionID=7,
            TradingDay=facts_helpers._TRADING_DAY,
            MaxOrderRef="7",
        ),
        SimpleNamespace(ErrorID=0),
        1,
        True,
    )
    client._settlement_state = "confirmed"
    client._settlement_readback_verified = True
    client._settlement_account_fingerprint = client._account_fingerprint
    client._settlement_trading_day = client._trading_day
    client._settlement_connection_generation = 1
    client._ready = True
    client._has_current_settlement_readback_locked = lambda: True
    return client, native


def _fake_ctp_modules(monkeypatch, *, sdk_client_module=None):
    """Load the production CTP wrapper against small synthetic SDK modules."""

    root = ModuleType("bt_api_ctp")
    root.__path__ = []
    if sdk_client_module is not None:
        real_package = sys.modules.get("bt_api_ctp")
        root.__version__ = getattr(real_package, "__version__", None)
    ctp = ModuleType("bt_api_ctp.ctp")
    ctp.__path__ = []
    client = (
        ModuleType("bt_api_ctp.ctp.client")
        if sdk_client_module is None
        else sdk_client_module
    )
    md_api = ModuleType("bt_api_ctp.ctp.ctp_md_api")
    order_structs = ModuleType("bt_api_ctp.ctp.ctp_structs_order")
    trader_api = ModuleType("bt_api_ctp.ctp.ctp_trader_api")

    class _SdkClientStub:
        pass

    class _SpiStub:
        pass

    if sdk_client_module is None:
        client.MdClient = _SdkClientStub
        client.TraderClient = _SdkClientStub
        client._MdSpi = _SpiStub
        client._TraderSpi = _SpiStub
    md_api.CThostFtdcMdSpi = _SpiStub
    order_structs.CThostFtdcInputOrderActionField = _NativeActionField
    order_structs.CThostFtdcInputOrderField = _NativeActionField
    trader_api.CThostFtdcTraderSpi = _SpiStub
    root.ctp = ctp
    ctp.client = client
    ctp.ctp_md_api = md_api
    ctp.ctp_structs_order = order_structs
    ctp.ctp_trader_api = trader_api
    for name, module in (
        ("bt_api_ctp", root),
        ("bt_api_ctp.ctp", ctp),
        ("bt_api_ctp.ctp.client", client),
        ("bt_api_ctp.ctp.ctp_md_api", md_api),
        ("bt_api_ctp.ctp.ctp_structs_order", order_structs),
        ("bt_api_ctp.ctp.ctp_trader_api", trader_api),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    return btapistore._create_ctp_wrapper_class()


def _production_test_api_base(
    monkeypatch,
    *,
    provider_insert_identity=None,
    trader_factory=None,
    sdk_client_module=None,
):
    ctp_client_wrapper = _fake_ctp_modules(
        monkeypatch, sdk_client_module=sdk_client_module
    )
    query_provider_base = factor_helpers._FakeProviderClient

    class ProductionCtpClientWithQueryLeaves(query_provider_base, ctp_client_wrapper):
        def __init__(self, **kwargs):
            ctp_client_wrapper.__init__(
                self,
                broker_id="fake-broker",
                investor_id="fake-investor",
                **kwargs,
            )
            query_provider_base.__init__(self, **kwargs)
            self.broker_id = "fake-broker"
            self.user_id = "fake-investor"
            self.trader_client = _NativeTrader() if trader_factory is None else trader_factory()
            if provider_insert_identity is not None:
                self.trader_client.provider_insert_identity = dict(provider_insert_identity)

        def cancel_order(
            self, order_ref, dataname=None, *, registered_sim_cancel_target=None
        ):
            # This fixture seam can inject a session race only after the real
            # RegisteredSimWrapper has checked/activated its one-shot target.
            # The production CTP builder still constructs the Action below.
            before_forward = getattr(
                self.trader_client, "_before_registered_sim_cancel_forward", None
            )
            if registered_sim_cancel_target is not None and callable(before_forward):
                before_forward(registered_sim_cancel_target)
            # The shared fake query base installs an integer instance counter
            # with this name.  Queries are complete before a cancel is
            # dispatched; expose the production CTP wrapper's request-ID
            # method for the final Action construction.
            self.__dict__.pop("_next_request_id", None)
            return ctp_client_wrapper.cancel_order(
                self,
                order_ref,
                dataname=dataname,
                registered_sim_cancel_target=registered_sim_cancel_target,
            )

    return ProductionCtpClientWithQueryLeaves


def _known_provider_identity_system(now):
    """Build one real known submit while retaining a fake provider SysID receipt."""

    api, store, broker, journal, coordinator, target, data, strategy, _cerebro = (
        factor_helpers._system(now=now)
    )
    initial = facts_helpers._refresh_all(store, target)
    store.registered_sim_configure_arm_templates(
        {
            (facts_helpers._INSTRUMENT, facts_helpers._EXCHANGE): {
                "md_front": "tcp://127.0.0.1:1",
                "strategy_identity_sha256": "a" * 64,
                "execution_cycle_id": "sysid-binding-test",
                "preflight_sha256": "b" * 64,
            }
        }
    )
    assert facts_helpers._consume_quote(store) is not None
    facts = facts_helpers._project(store, broker, target, now, query_set=initial.query_set)
    assert facts.open_risk_ready is True, facts.blockers
    key = factor_helpers.ExecutionIntentKey(
        action="SUBMIT",
        instrument=facts_helpers._INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    economics = {
        "instrument": facts_helpers._INSTRUMENT,
        "exchange": facts_helpers._EXCHANGE,
        "side": "BUY",
        "position_effect": "OPEN",
        "quantity": "1",
        "limit_price": "100",
        "factor_stop_price": "95",
        "risk_policy_id": "sysid-binding-test",
        "risk_policy": {"stop_loss_ticks": 5, "max_loss_per_position": "25"},
        "entry_grid_ordinal": 1,
        "batch_id": "sysid-binding-test",
        "price": "100",
    }
    with factor_helpers._live_scope(
        coordinator,
        strategy,
        facts,
        now=now,
        intent_key=key,
        economics=economics,
    ):
        order = strategy.buy(
            data=data,
            size=1,
            price=100,
            exectype=factor_helpers.Order.Limit,
            instrument_id=facts_helpers._INSTRUMENT,
            exchange_id=facts_helpers._EXCHANGE,
            factor_position_effect="OPEN",
            factor_strategy_scope=factor_helpers._SCOPE,
            offset="open",
        )
    assert order is not None and order.alive()
    assert order.info["factor_dispatch_state"] == "KNOWN"
    assert journal.intent(order.info["factor_intent_id"]).provider_identity[
        "order_sys_id"
    ] == "SYS-CANCEL-501"
    return api, store, broker, journal, coordinator, target, order


def _prepare_provider_identity_order(monkeypatch, *, provider_insert_identity):
    """Create KNOWN provider identity without a query-derived SysID binding."""

    sdk_client_module, trader, native = _sdk_trader_fixture(monkeypatch)
    trader.provider_insert_identity = dict(provider_insert_identity)
    provider_base = _production_test_api_base(
        monkeypatch,
        provider_insert_identity=provider_insert_identity,
        trader_factory=lambda: trader,
        sdk_client_module=sdk_client_module,
    )
    monkeypatch.setattr(factor_helpers, "_FakeProviderClient", provider_base)
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, order = (
        _known_provider_identity_system(now)
    )
    api._use_observed_query_clock = True
    order_ref = order.info["external_order_ref"]
    provider_order = api._provider_orders[order_ref]
    provider_order["order_sys_id"] = "SYS-CANCEL-501"
    api.emit_provider_order_callback(order_ref, status="accepted", filled=0, remaining=1)
    broker._drain_store_updates()
    row = _active_order_query_row(order)
    api.query_rows = facts_helpers._query_rows(orders=(row,))
    receipt = facts_helpers._refresh_all(store, target)
    # Facts normally opportunistically persist a complete-query binding. Keep
    # this compatibility case on the provider-identity route so it specifically
    # exercises the durable KNOWN provider SysID + callback lineage contract.
    monkeypatch.setattr(coordinator, "bind_known_order_sysids_from_current_query", lambda: ())
    assert journal.intent(order.info["factor_intent_id"]).order_sys_id_binding is None
    assert order.info["registered_sim_ctp_order_sys_id"] == "SYS-CANCEL-501"
    facts = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc),
        query_set=receipt.query_set,
    )
    assert journal.intent(order.info["factor_intent_id"]).order_sys_id_binding is None
    assert api.trader_client is trader
    assert native.trader is trader
    return api, store, broker, journal, coordinator, target, order, facts, trader, native


def _active_order_query_row(order, **overrides):
    row = {
        "BrokerID": "fake-broker",
        "InvestorID": "fake-investor",
        "TradingDay": facts_helpers._TRADING_DAY,
        "OrderRef": order.info["external_order_ref"],
        "InstrumentID": facts_helpers._INSTRUMENT,
        "ExchangeID": facts_helpers._EXCHANGE,
        "OrderStatus": "3",
        "Direction": "0",
        "CombOffsetFlag": "0",
        "VolumeTotalOriginal": "1",
        "VolumeTraded": "0",
        "VolumeTotal": "1",
        "FrontID": 4,
        "SessionID": 7,
        "OrderSysID": "SYS-CANCEL-501",
    }
    row.update(overrides)
    return row


def _expose_production_ctp_request_counter(api):
    # The fake query base shadows the generated wrapper method with an
    # instance counter. Remove that test-only attribute only after the final
    # query, so cancel RequestID comes from production CtpClientWrapper code.
    api.__dict__.pop("_next_request_id", None)


def _prepare_bound_order(
    monkeypatch,
    *,
    journal_path=None,
    trader_factory=None,
    sdk_client_module=None,
):
    """Create a real Broker order and bind it through the current CTP query."""

    provider_base = _production_test_api_base(
        monkeypatch,
        trader_factory=trader_factory,
        sdk_client_module=sdk_client_module,
    )
    monkeypatch.setattr(factor_helpers, "_FakeProviderClient", provider_base)
    if journal_path is not None:
        original_system = factor_helpers._system

        def persistent_journal_system(**kwargs):
            return original_system(journal_path=journal_path, **kwargs)

        monkeypatch.setattr(factor_helpers, "_system", persistent_journal_system)
    now = datetime.now(timezone.utc)
    api, store, broker, journal, coordinator, target, order = (
        factor_helpers._known_order_sysid_binding_system(now)
    )
    api._use_observed_query_clock = True
    row = _active_order_query_row(order)
    api.query_rows = facts_helpers._query_rows(orders=(row,))
    receipt = facts_helpers._refresh_all(store, target)
    failures = coordinator.bind_known_order_sysids_from_current_query()
    assert failures == ()
    page = coordinator.execution_intent_snapshot(limit=1024)
    bound = next(
        item for item in page.items if item.intent_id == order.info["factor_intent_id"]
    )
    assert bound.order_sys_id_binding["order_sys_id"] == "SYS-CANCEL-501"
    facts = facts_helpers._project(
        store,
        broker,
        target,
        datetime.now(timezone.utc),
        query_set=receipt.query_set,
    )
    return api, store, broker, journal, coordinator, target, order, facts


def _sdk_trader_fixture(
    monkeypatch, *, trader_type=None, additional_arm_templates=None
):
    """Build a synthetic-session TraderClient from the sibling SDK source."""
    sdk_client_module = _load_sdk_source(monkeypatch)
    trader, native = _real_sdk_trader(
        sdk_client_module, trader_type=trader_type
    )

    # The factor fixture publishes this identity into its complete query and
    # Journal.  It is the actual SDK's synthetic broker/user fingerprint, so
    # RegisteredSim can validate the same account without weakening a check.
    monkeypatch.setattr(facts_helpers, "_ACCOUNT", trader._account_fingerprint)

    # The shared factor fixture's default loopback MD front is appropriate for
    # its fake SDK only.  Bind this synthetic real-SDK case to the SDK's frozen
    # official SimNow front pair; no network connection is started.
    configure_templates = (
        registered_sim_module.RegisteredSimStore.registered_sim_configure_arm_templates
    )

    def configure_with_sdk_front(store, templates):
        normalized = {key: dict(value) for key, value in templates.items()}
        for key, value in (additional_arm_templates or {}).items():
            normalized[key] = dict(value)
        for value in normalized.values():
            value["md_front"] = "tcp://182.254.243.31:30012"
        return configure_templates(store, normalized)

    monkeypatch.setattr(
        registered_sim_module.RegisteredSimStore,
        "registered_sim_configure_arm_templates",
        configure_with_sdk_front,
    )
    return sdk_client_module, trader, native


def _prepare_bound_order_with_sdk(
    monkeypatch,
    *,
    trader_type=None,
    journal_path=None,
    additional_arm_templates=None,
):
    """Use the sibling SDK's actual TraderClient with a synthetic native API."""

    sdk_client_module, trader, native = _sdk_trader_fixture(
        monkeypatch,
        trader_type=trader_type,
        additional_arm_templates=additional_arm_templates,
    )
    system = _prepare_bound_order(
        monkeypatch,
        trader_factory=lambda: trader,
        sdk_client_module=sdk_client_module,
        journal_path=journal_path,
    )
    assert system[0].trader_client is trader
    return (*system, trader, sdk_client_module, native)


def _fresh_sdk_store_without_order(monkeypatch):
    """Build the production wrapper with a logged-in SDK client and no arm."""
    sdk_client_module, trader, native = _sdk_trader_fixture(monkeypatch)
    provider_base = _production_test_api_base(
        monkeypatch,
        trader_factory=lambda: trader,
        sdk_client_module=sdk_client_module,
    )
    monkeypatch.setattr(factor_helpers, "_FakeProviderClient", provider_base)
    system = factor_helpers._system(
        now=datetime.now(timezone.utc),
        api_cls=provider_base,
    )
    api, store, broker, journal, coordinator, target, _data, _strategy, _cerebro = system
    assert api.trader_client is trader
    assert api._registered_sim_capability is None
    assert api._registered_sim_frozen is False
    return api, store, broker, journal, coordinator, target, trader, sdk_client_module, native


def _downgrade_cancel_journal_to_v21(path):
    """Model a process opening a v21 journal with an unresolved cancel claim."""

    with sqlite3.connect(path) as connection:
        # Remove the v23 single-row tape/quarantine objects and the v24/v25
        # amount lifecycle projection; a genuine v21 journal cannot contain
        # any of them.
        drop_empty_fee_pair_tables_from_version(connection, first_version=23)
        # v23 also replaced the workflow durable-reservation trigger, so
        # restore the exact v20 DDL that the v21 validator requires.
        connection.execute(
            "DROP TRIGGER IF EXISTS execution_fee_pair_workflow_durable_reservation_state"
        )
        connection.execute(
            execution_decision_journal_module._FEE_PAIR_WORKFLOW_DURABLE_RESERVATION_TRIGGER_SQL_V20
        )
        for trigger in (
            "execution_registered_sim_cancel_dispatch_claim_no_update",
            "execution_registered_sim_cancel_dispatch_claim_no_delete",
            "execution_registered_sim_cancel_dispatch_tombstone_no_update",
            "execution_registered_sim_cancel_dispatch_tombstone_no_delete",
        ):
            connection.execute("DROP TRIGGER IF EXISTS " + trigger)
        connection.execute(
            "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_claims"
        )
        connection.execute(
            "DROP TABLE IF EXISTS execution_registered_sim_cancel_dispatch_tombstones"
        )
        connection.execute("PRAGMA user_version=21")


def _cancel_scope(coordinator, order, facts):
    cancel_key = factor_helpers.ExecutionIntentKey(
        action="CANCEL",
        instrument=facts_helpers._INSTRUMENT,
        side="BUY",
        position_effect="OPEN",
        leg=0,
    )
    economics = {
        "instrument": facts_helpers._INSTRUMENT,
        "exchange": facts_helpers._EXCHANGE,
        "side": "BUY",
        "position_effect": "OPEN",
        "owner_intent_id": order.info["factor_intent_id"],
        "reason": "synthetic native-identity regression",
    }
    decision_key = factor_helpers.ExecutionDecisionKey(
        account_scope=factor_helpers._ACCOUNT_SCOPE,
        strategy_scope=factor_helpers._SCOPE,
        logical_run_id="run-1",
        cohort_id="registered-sim-cancel-native-identity",
        close_time=facts.available_at.isoformat().replace("+00:00", "Z"),
        decision_kind="ALPHA003_RISK_REDUCTION",
    )
    return coordinator.risk_decision_scope(
        owner=order.owner,
        key=decision_key,
        economic_payload={"intent_economics": (economics,)},
        intent_keys=(cancel_key,),
        execution_facts=facts,
        inputs_complete=True,
        expected_run_order_intents_used=coordinator.run_order_count(),
        remaining_exit_intent_reserve=0,
    )


def test_registered_sim_passes_complete_verified_identity_in_production_ctp_action(
    monkeypatch,
):
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    issued_deadlines = []
    trader._before_registered_sim_cancel_forward = lambda target: issued_deadlines.append(
        target.source_expires_monotonic
    )
    assert facts.order_cancel_ready is True, facts.order_cancel_blockers
    try:
        with _cancel_scope(coordinator, order, facts):
            _expose_production_ctp_request_counter(api)
            broker.cancel(order)

        cancel_calls = [call for call in native.calls if call[0] == "cancel"]
        assert len(cancel_calls) == 1
        _operation, field, request_id = cancel_calls[0]
        assert type(field) is _NativeActionField
        assert {
            "BrokerID": field.BrokerID,
            "InvestorID": field.InvestorID,
            "UserID": field.UserID,
            "OrderRef": field.OrderRef,
            "OrderSysID": field.OrderSysID,
            "ExchangeID": field.ExchangeID,
            "InstrumentID": field.InstrumentID,
            "FrontID": field.FrontID,
            "SessionID": field.SessionID,
            "RequestID": field.RequestID,
            "ActionFlag": field.ActionFlag,
        } == {
            "BrokerID": "fake-broker",
            "InvestorID": "fake-investor",
            "UserID": "fake-investor",
            "OrderRef": order.info["external_order_ref"],
            "OrderSysID": "SYS-CANCEL-501",
            "ExchangeID": facts_helpers._EXCHANGE,
            "InstrumentID": facts_helpers._INSTRUMENT,
            "FrontID": 4,
            "SessionID": 7,
            "RequestID": request_id,
            "ActionFlag": "0",
        }
        assert request_id > 0
        assert field.OrderActionRef == request_id
        assert len(issued_deadlines) == 1
        assert field.RequestID == request_id
        assert field.BrokerID == trader.broker_id
        assert field.InvestorID == trader.user_id
        assert order.info["cancel_acknowledged"] is True
        cancel_intent = journal.intent(order.info["factor_cancel_intent_id"])
        assert cancel_intent.state == "KNOWN"
        assert cancel_intent.original_identity["order_sys_id"] == "SYS-CANCEL-501"
        assert cancel_intent.original_identity["front_id"] == 4
        assert cancel_intent.original_identity["session_id"] == 7
    finally:
        journal.close()


@pytest.mark.parametrize(
    ("identity_field", "changed_value"),
    [
        ("account_fingerprint", "different-account"),
        ("connection_generation", 2),
        ("trading_day", "20261025"),
        ("front_id", 5),
        ("session_id", 8),
    ],
)
def test_registered_sim_refuses_session_drift_after_target_issue_before_native_action(
    monkeypatch, identity_field, changed_value
):
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)

    def drift_after_store_target_handoff(_target):
        attribute = "_" + identity_field
        setattr(trader, attribute, changed_value)

    trader._before_registered_sim_cancel_forward = drift_after_store_target_handoff
    try:
        with _cancel_scope(coordinator, order, facts):
            try:
                _expose_production_ctp_request_counter(api)
                broker.cancel(order)
            except BtApiStoreError:
                pass
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert order.info.get("factor_cancel_dispatch_state") != "KNOWN"
    finally:
        journal.close()


def test_registered_sim_expired_source_receipt_is_rejected_before_sdk_action(monkeypatch):
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    real_clock = registered_sim_module.time

    class ExpiringClock:
        def __init__(self, delegate):
            self._delegate = delegate
            self.deadline = None

        def monotonic(self):
            current = self._delegate.monotonic()
            if self.deadline is None:
                return current
            return max(current, self.deadline + 0.001)

        def __getattr__(self, name):
            return getattr(self._delegate, name)

    clock = ExpiringClock(real_clock)
    monkeypatch.setattr(registered_sim_module, "time", clock)
    issued_expiries = []

    def expire_after_wrapper_admission(target):
        issued_expiries.append(target.source_expires_monotonic)
        clock.deadline = target.source_expires_monotonic

    trader._before_registered_sim_cancel_forward = expire_after_wrapper_admission
    try:
        with _cancel_scope(coordinator, order, facts), pytest.raises(BtApiStoreError):
            _expose_production_ctp_request_counter(api)
            broker.cancel(order)
        assert len(issued_expiries) == 1
        assert clock.monotonic() > issued_expiries[0]
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert api._registered_sim_unknown_dispatch is None
        assert api._registered_sim_frozen is False
        facts_projection = api.registered_sim_execution_facts()
        assert facts_projection["frozen"] is False
        assert facts_projection["unknown_ids"] == []
    finally:
        journal.close()


def test_registered_sim_canonical_sdk_local_deadline_error_without_history_is_not_unknown(
    monkeypatch,
):
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    submitted = []
    submit_code = sdk_client_module.TraderClient.submit_order_action.__code__
    prior_profile = sys.getprofile()

    def observe_submit_entry(frame, event, _arg):
        if event == "call" and frame.f_code is submit_code:
            submitted.append((frame.f_locals["field"], frame.f_locals["request_id"]))

    def reject_before_history(*_args, **_kwargs):
        raise sdk_client_module._CtpNativeRequestDeadlineExpired(
            "ctp_execution_gate_cancel_deadline_expired"
        )

    # Isolate the SDK's canonical pre-history gate boundary while leaving the
    # canonical submit/invoke/evidence methods and their identities intact.
    trader._require_execution_write_locked = reject_before_history
    request_count_before = trader.get_request_counts()["order_action"]
    try:
        sys.setprofile(observe_submit_entry)
        with _cancel_scope(coordinator, order, facts):
            with pytest.raises(BtApiStoreError):
                _expose_production_ctp_request_counter(api)
                broker.cancel(order)
            with pytest.raises(BtApiStoreError):
                store.cancel_order(order)
        assert len(submitted) == 1
        field, request_id = submitted[0]
        assert trader.get_order_action_evidence(
            request_id,
            order_action_ref=field.OrderActionRef,
        ) is None
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert trader.get_request_counts()["order_action"] == request_count_before
        assert api._registered_sim_unknown_dispatch is None
        assert api._registered_sim_frozen is False
        assert store._registered_sim_gate["frozen"] is False
    finally:
        sys.setprofile(prior_profile)
        journal.close()


@pytest.mark.parametrize("signature_kind", ["legacy", "kwargs_only"])
def test_registered_sim_legacy_sdk_cancel_signature_fails_closed_and_burns_claim(
    monkeypatch, signature_kind
):
    (
        api,
        store,
        _broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    sdk_calls = []
    if signature_kind == "legacy":

        def legacy_submit(self, field, request_id, *, execution_capability):
            sdk_calls.append((field, request_id, execution_capability))
            return 0

        trader.submit_order_action = MethodType(legacy_submit, trader)
    else:

        def kwargs_only_submit(self, field, request_id, **kwargs):
            sdk_calls.append((field, request_id, kwargs))
            return 0

        trader.submit_order_action = MethodType(kwargs_only_submit, trader)

    try:
        with _cancel_scope(coordinator, order, facts):
            scope = coordinator.active_scope_for_order(order)
            scope.begin_order(order, action="CANCEL")
            _expose_production_ctp_request_counter(api)
            with pytest.raises(BtApiStoreError, match="explicitly support query deadlines"):
                store.cancel_order(order)
            # The durable admission is intentionally one-shot even though no
            # SDK call was made; a retry cannot reuse the same cancellation.
            with pytest.raises(BtApiStoreError):
                store.cancel_order(order)

        assert sdk_calls == []
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert api._registered_sim_unknown_dispatch is None
        assert api._registered_sim_frozen is False
    finally:
        journal.close()


def test_registered_sim_production_action_forwards_expiry_to_real_sdk_client(monkeypatch):
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    issued_deadlines = []
    forwarded = []
    trader._before_registered_sim_cancel_forward = lambda target: issued_deadlines.append(
        target.source_expires_monotonic
    )
    submit_code = sdk_client_module.TraderClient.submit_order_action.__code__
    invoke_code = sdk_client_module.TraderClient._invoke_session_native_request.__code__
    prior_profile = sys.getprofile()

    def observe_sdk_arguments(frame, event, _arg):
        if event != "call":
            return
        if frame.f_code is submit_code:
            forwarded.append(
                (
                    "submit",
                    frame.f_locals["field"],
                    frame.f_locals["request_id"],
                    frame.f_locals["deadline_monotonic"],
                )
            )
        elif frame.f_code is invoke_code:
            forwarded.append(
                (
                    "invoke",
                    frame.f_locals["args"][0],
                    frame.f_locals["args"][1],
                    frame.f_locals["deadline_monotonic"],
                    frame.f_locals["dispatch_outcome"],
                )
            )

    try:
        sys.setprofile(observe_sdk_arguments)
        with _cancel_scope(coordinator, order, facts):
            _expose_production_ctp_request_counter(api)
            broker.cancel(order)

        assert len(issued_deadlines) == 1
        submit_observations = [item for item in forwarded if item[0] == "submit"]
        invoke_observations = [item for item in forwarded if item[0] == "invoke"]
        assert len(submit_observations) == 1
        assert len(invoke_observations) == 1
        _kind, action_field, request_id, deadline = submit_observations[0]
        _kind, invoke_field, invoke_request_id, invoke_deadline, dispatch_outcome = (
            invoke_observations[0]
        )
        assert deadline == issued_deadlines[0]
        assert invoke_field is action_field
        assert invoke_request_id == request_id
        assert invoke_deadline == deadline
        assert type(dispatch_outcome) is sdk_client_module._CtpNativeRequestDispatchOutcome
        assert dispatch_outcome.native_call_started is True
        assert action_field.OrderActionRef == request_id
        cancel_calls = [call for call in native.calls if call[0] == "cancel"]
        assert len(cancel_calls) == 1
        assert cancel_calls[0][1] is action_field
        assert cancel_calls[0][2] == request_id
        assert order.info["cancel_acknowledged"] is True
        assert api._registered_sim_unknown_dispatch is None
        assert api._registered_sim_frozen is False
    finally:
        sys.setprofile(prior_profile)
        journal.close()


def test_registered_sim_real_sdk_deadline_reaches_native_boundary_and_lock_expiry_is_known(
    monkeypatch,
):
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    issued_deadlines = []
    trader._before_registered_sim_cancel_forward = lambda target: issued_deadlines.append(
        target.source_expires_monotonic
    )

    # The SDK method itself is left untouched so its exact canonical method
    # identity and real action-evidence getter participate in classification.
    clock = _FakeMonotonicClock()
    monkeypatch.setattr(sdk_client_module, "time", clock)
    monkeypatch.setattr(registered_sim_module, "time", clock)
    observed_lock = trader._query_state_lock
    assert type(observed_lock) is type(threading.RLock())
    sdk_submit_code = sdk_client_module.TraderClient.submit_order_action.__code__
    sdk_invoke_code = sdk_client_module.TraderClient._invoke_session_native_request.__code__
    sdk_native_calls = []
    invoke_observations = []
    holder_acquired = threading.Event()
    holder_errors = []
    lock_holders = []
    prior_profile = sys.getprofile()

    def observe_real_sdk_frames(frame, event, _arg):
        if event == "call" and frame.f_code is sdk_submit_code:
            sdk_native_calls.append(
                (
                    frame.f_locals["field"],
                    frame.f_locals["request_id"],
                    frame.f_locals["deadline_monotonic"],
                )
            )
        elif event == "call" and frame.f_code is sdk_invoke_code:
            invoke_observations.append(
                (
                    frame.f_locals["deadline_monotonic"],
                    frame.f_locals["dispatch_outcome"],
                )
            )
            # At this exact production-method entry the submit method's prior
            # state-lock scope has ended. Acquire the same canonical RLock on
            # a helper thread before returning from the profile hook; the SDK
            # then has to wait on that real lock before its final deadline
            # check and native leaf.
            def hold_real_sdk_lock():
                try:
                    with observed_lock:
                        holder_acquired.set()
                        time.sleep(0.05)
                        assert issued_deadlines
                        clock.now = issued_deadlines[0] + 0.25
                except BaseException as exc:
                    holder_errors.append(exc)

            holder = threading.Thread(target=hold_real_sdk_lock)
            lock_holders.append(holder)
            holder.start()
            if not holder_acquired.wait(timeout=5):
                holder_errors.append(AssertionError("SDK lock holder did not acquire RLock"))

    request_count_before = trader.get_request_counts()["order_action"]
    try:
        sys.setprofile(observe_real_sdk_frames)
        with _cancel_scope(coordinator, order, facts), pytest.raises(BtApiStoreError):
            _expose_production_ctp_request_counter(api)
            broker.cancel(order)
        for holder in lock_holders:
            holder.join(timeout=5)
        sys.setprofile(prior_profile)

        assert holder_errors == []
        assert all(not holder.is_alive() for holder in lock_holders)
        assert len(issued_deadlines) == 1
        assert clock.monotonic() > issued_deadlines[0]
        assert len(sdk_native_calls) == 1
        action_field, request_id, forwarded_deadline = sdk_native_calls[0]
        assert forwarded_deadline == issued_deadlines[0]
        assert action_field.OrderActionRef == request_id
        assert len(invoke_observations) == 1
        invoke_deadline, dispatch_outcome = invoke_observations[0]
        assert invoke_deadline == issued_deadlines[0]
        assert type(dispatch_outcome) is sdk_client_module._CtpNativeRequestDispatchOutcome
        assert dispatch_outcome.native_call_started is False
        assert [call[0] for call in native.calls].count("cancel") == 0
        assert trader._native_request_inflight_refs == 0
        assert trader.get_order_action_evidence(
            request_id,
            order_action_ref=action_field.OrderActionRef,
        ) is None
        assert trader.get_request_counts()["order_action"] == request_count_before
        assert api._registered_sim_unknown_dispatch is None
        assert api._registered_sim_frozen is False
        assert store._registered_sim_gate["frozen"] is False
        with _cancel_scope(coordinator, order, facts), pytest.raises(BtApiStoreError):
            store.cancel_order(order)
        assert [call[0] for call in native.calls].count("cancel") == 0
    finally:
        sys.setprofile(prior_profile)
        for holder in lock_holders:
            if holder.ident is not None:
                holder.join(timeout=5)
        journal.close()


def test_registered_sim_real_sdk_native_deadline_exception_with_evidence_is_unknown(
    monkeypatch,
):
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    native.order_action_error = sdk_client_module._CtpNativeRequestDeadlineExpired(
        "ctp_execution_gate_cancel_deadline_expired"
    )
    try:
        with _cancel_scope(coordinator, order, facts):
            scope = coordinator.active_scope_for_order(order)
            scope.begin_order(order, action="CANCEL")
            _expose_production_ctp_request_counter(api)
            with pytest.raises(Exception) as raised:
                store.cancel_order(order)

        assert getattr(raised.value, "execution_unknown", False) is True
        cancel_calls = [call for call in native.calls if call[0] == "cancel"]
        assert len(cancel_calls) == 1
        _operation, field, request_id = cancel_calls[0]
        assert field.OrderActionRef == request_id
        sdk_evidence = trader.get_order_action_evidence(
            request_id,
            order_action_ref=field.OrderActionRef,
        )
        assert sdk_evidence is not None
        assert sdk_evidence.status == "unknown"
        assert sdk_evidence.reason == "native_submit_exception"
        assert api._registered_sim_unknown_dispatch is not None
        assert api._registered_sim_unknown_dispatch.status == "UNKNOWN"
        assert api._registered_sim_frozen is True
        assert store._registered_sim_gate["frozen"] is True
        with pytest.raises(BtApiStoreError):
            store.cancel_order(order)
        assert len([call for call in native.calls if call[0] == "cancel"]) == 1
    finally:
        journal.close()


class _OrderActionHistoryGetInterrupt(dict):
    def get(self, *_args, **_kwargs):
        raise KeyboardInterrupt("synthetic evidence lookup interruption")


@pytest.mark.parametrize("interrupt_at", ["native", "evidence_getter"])
def test_registered_sim_keyboard_interrupt_after_possible_native_entry_freezes_and_burns_claim(
    monkeypatch, interrupt_at
):
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    if interrupt_at == "native":
        native.order_action_error = KeyboardInterrupt("synthetic native leaf interruption")
    else:
        def interrupt_evidence_lookup(_field, _request_id):
            trader._order_action_history = _OrderActionHistoryGetInterrupt(
                trader._order_action_history
            )
            raise sdk_client_module._CtpNativeRequestDeadlineExpired(
                "ctp_execution_gate_cancel_deadline_expired"
            )

        native.order_action_hook = interrupt_evidence_lookup

    try:
        with _cancel_scope(coordinator, order, facts), pytest.raises(KeyboardInterrupt):
            _expose_production_ctp_request_counter(api)
            broker.cancel(order)

        assert len([call for call in native.calls if call[0] == "cancel"]) == 1
        assert api._registered_sim_unknown_dispatch is not None
        assert api._registered_sim_unknown_dispatch.status == "UNKNOWN"
        assert api._registered_sim_frozen is True
        assert store._registered_sim_gate["frozen"] is True
        with pytest.raises(BtApiStoreError):
            store.cancel_order(order)
        assert len([call for call in native.calls if call[0] == "cancel"]) == 1
    finally:
        journal.close()


def test_registered_sim_sdk_subclass_override_fails_closed_before_sdk_or_native(
    monkeypatch,
):
    sdk_client_module = _load_sdk_source(monkeypatch)
    override_entries = []

    class NativeThenGateErrorTrader(sdk_client_module.TraderClient):
        def submit_order_action(
            self,
            field,
            request_id,
            *,
            execution_capability,
            deadline_monotonic=None,
        ):
            override_entries.append((field, request_id))
            self._api.ReqOrderAction(field, request_id)
            raise sdk_client_module._CtpNativeRequestDeadlineExpired(
                "ctp_execution_gate_cancel_deadline_expired"
            )

    sdk_client_module, trader, native = _sdk_trader_fixture(
        monkeypatch, trader_type=NativeThenGateErrorTrader
    )
    api_cls = _production_test_api_base(
        monkeypatch,
        trader_factory=lambda: trader,
        sdk_client_module=sdk_client_module,
    )
    monkeypatch.setattr(factor_helpers, "_FakeProviderClient", api_cls)
    api, store, _broker, journal, _coordinator, _target, _data, _strategy, _cerebro = (
        factor_helpers._system(now=datetime.now(timezone.utc))
    )
    try:
        # Exact canonical SDK query bindings are part of the production
        # admission boundary. A subclass override is rejected while preparing
        # the first query receipt; do not invent query support for the subclass.
        receipt = facts_helpers.refresh_factor_execution_queries(
            store,
            targets=(_target,),
            overall_timeout=4.0,
        )
        assert receipt.blockers
        assert len(receipt.attempted_families) == 6
        assert all(blocker.startswith("query_refresh_failed:") for blocker in receipt.blockers)

        assert override_entries == []
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert [call for call in native.calls if call[0] == "insert"] == []
        assert api._registered_sim_unknown_dispatch is None
        assert api._registered_sim_frozen is False
        assert store._registered_sim_gate["frozen"] is False
    finally:
        journal.close()


@pytest.mark.parametrize(
    "mutation",
    [
        "fake_sys_id",
        "foreign_owner",
        "unknown",
        "missing_order_ref",
    ],
)
def test_registered_sim_refuses_forged_or_incomplete_framework_cancel_identity(
    monkeypatch, mutation
):
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    try:
        with _cancel_scope(coordinator, order, facts):
            if mutation == "fake_sys_id":
                order.addinfo(order_sys_id="FORGED-SYS-ID")
            elif mutation == "foreign_owner":
                order.addinfo(factor_intent_id="foreign-owner-intent")
            elif mutation == "unknown":
                order.addinfo(execution_unknown=True)
            elif mutation == "missing_order_ref":
                order.addinfo(external_order_ref=None, ctp_order_ref=None, order_ref=None)
            try:
                _expose_production_ctp_request_counter(api)
                broker.cancel(order)
            except BtApiStoreError:
                pass
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert order.info.get("factor_cancel_dispatch_state") != "KNOWN"
        assert order.info.get("cancel_rejected_local") is True or order.info.get(
            "execution_unknown"
        ) is True
    finally:
        journal.close()


def test_registered_sim_refuses_cancel_when_current_complete_query_loses_order_sys_id(
    monkeypatch,
):
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        order,
        facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    row = _active_order_query_row(order)
    row.pop("OrderSysID")
    try:
        cancel_scope = _cancel_scope(coordinator, order, facts)
        api.query_rows = facts_helpers._query_rows(orders=(row,))
        facts_helpers._refresh_all(store, target)
        api.__dict__.pop("_next_request_id", None)
        with cancel_scope, pytest.raises(BtApiStoreError):
            broker.cancel(order)
        assert [call for call in native.calls if call[0] == "cancel"] == []
    finally:
        journal.close()


@pytest.mark.parametrize(
    ("provider_identity", "should_dispatch"),
    [
        (
            {
                "OrderSysID": "SYS-CANCEL-501",
                "BrokerID": "fake-broker",
                "InvestorID": "fake-investor",
            },
            True,
        ),
        (
            {
                "OrderSysID": "SYS-CANCEL-501",
                "BrokerID": "foreign-broker",
                "InvestorID": "fake-investor",
            },
            False,
        ),
        (
            {
                "OrderSysID": "SYS-CANCEL-501",
                "BrokerID": "fake-broker",
                "InvestorID": "foreign-investor",
            },
            False,
        ),
    ],
    ids=("matching-pair", "foreign-broker", "foreign-investor"),
)
def test_registered_sim_no_binding_provider_sysid_requires_exact_account_pair(
    monkeypatch, provider_identity, should_dispatch
):
    """Exercise the durable provider-identity path without a query binding."""

    api, store, broker, journal, coordinator, _target, order, facts, trader, native = (
        _prepare_provider_identity_order(
            monkeypatch, provider_insert_identity=provider_identity
        )
    )
    try:
        assert facts.order_cancel_ready is True, facts.order_cancel_blockers
        with _cancel_scope(coordinator, order, facts):
            _expose_production_ctp_request_counter(api)
            if should_dispatch:
                broker.cancel(order)
            else:
                scope = coordinator.active_scope_for_order(order)
                scope.begin_order(order, action="CANCEL")
                records = journal.registered_sim_cancel_dispatch_records(
                    order.info["factor_cancel_intent_id"]
                )
                assert records["binding"] is None
                with pytest.raises(BtApiStoreError):
                    store.cancel_order(order)
        cancel_calls = [call for call in native.calls if call[0] == "cancel"]
        assert len(cancel_calls) == (1 if should_dispatch else 0)
        if should_dispatch:
            _operation, field, request_id = cancel_calls[0]
            assert field.OrderSysID == "SYS-CANCEL-501"
            assert field.BrokerID == "fake-broker"
            assert field.InvestorID == "fake-investor"
            assert field.RequestID == request_id > 0
        else:
            assert order.info.get("cancel_acknowledged") is not True
            assert order.info.get("factor_cancel_dispatch_state") != "KNOWN"
    finally:
        journal.close()


def test_registered_sim_store_rejects_migrated_v21_dispatching_cancel_before_sdk(
    monkeypatch, tmp_path
):
    path = tmp_path / "legacy-v21-dispatching-cancel.sqlite3"
    (
        api,
        store,
        _broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch, journal_path=path)
    migrated = None
    try:
        with _cancel_scope(coordinator, order, facts):
            scope = coordinator.active_scope_for_order(order)
            attempt = scope.begin_order(order, action="CANCEL")
            cancel_intent_id = attempt.intent.intent_id
        assert journal.intent(cancel_intent_id).state == "DISPATCHING"
        assert journal.intent(cancel_intent_id).dispatch_state is None

        # Closing the unresolved Journal releases only its dispatch lease. The
        # durable old intent remains and is then opened through v22 migration.
        journal.close()
        _downgrade_cancel_journal_to_v21(path)
        migrated = factor_helpers.ExecutionDecisionJournal(path)
        coordinator.journal = migrated
        with pytest.raises(BtApiStoreError):
            store.cancel_order(order)
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert migrated.intent(cancel_intent_id).state == "DISPATCHING"
        tombstone = migrated._connection.execute(
            "SELECT reason FROM execution_registered_sim_cancel_dispatch_tombstones "
            "WHERE cancel_intent_id=?",
            (cancel_intent_id,),
        ).fetchone()
        assert tombstone is not None
        assert tombstone["reason"] == "LEGACY_DISPATCHING_CANCEL_AMBIGUOUS"
    finally:
        if migrated is not None:
            migrated.close()
        elif not journal._closed:
            journal.close()


@pytest.mark.parametrize(
    ("binding_field", "foreign_value"),
    [("BrokerID", "foreign-broker"), ("InvestorID", "foreign-investor")],
)
def test_registered_sim_refuses_current_query_broker_investor_binding_drift(
    monkeypatch, binding_field, foreign_value
):
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        order,
        facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    try:
        cancel_scope = _cancel_scope(coordinator, order, facts)
        row = _active_order_query_row(order, **{binding_field: foreign_value})
        api.query_rows = facts_helpers._query_rows(orders=(row,))
        facts_helpers._refresh_all(store, target)
        api.__dict__.pop("_next_request_id", None)
        with cancel_scope, pytest.raises(BtApiStoreError):
            broker.cancel(order)
        assert [call for call in native.calls if call[0] == "cancel"] == []
    finally:
        journal.close()


def test_registered_sim_refuses_current_query_order_without_broker_id(monkeypatch):
    """A missing BrokerID in the fresh query cannot authorize a cancel."""
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        order,
        facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    try:
        cancel_scope = _cancel_scope(coordinator, order, facts)
        row = _active_order_query_row(order)
        # The shared row helper supplies a default BrokerID when a key is
        # absent; explicit None models a source row with no usable value.
        row["BrokerID"] = None
        api.query_rows = facts_helpers._query_rows(orders=(row,))
        receipt = facts_helpers.refresh_factor_execution_queries(
            store,
            targets=(target,),
            overall_timeout=4.0,
        )
        assert receipt.blockers == ()
        with cancel_scope:
            scope = coordinator.active_scope_for_order(order)
            scope.begin_order(order, action="CANCEL")
            with pytest.raises(BtApiStoreError):
                store.cancel_order(order)
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert order.info.get("cancel_acknowledged") is not True
    finally:
        journal.close()


@pytest.mark.parametrize(
    ("instrument_id", "exchange_id"),
    [("i2510", "SHFE"), ("rb2510", "DCE")],
    ids=("foreign-instrument", "foreign-exchange"),
)
def test_registered_sim_refuses_current_query_order_on_foreign_route(
    monkeypatch, instrument_id, exchange_id
):
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        target,
        order,
        facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    try:
        cancel_scope = _cancel_scope(coordinator, order, facts)
        row = _active_order_query_row(
            order,
            InstrumentID=instrument_id,
            ExchangeID=exchange_id,
        )
        api.query_rows = facts_helpers._query_rows(orders=(row,))
        facts_helpers._refresh_all(store, target)
        api.__dict__.pop("_next_request_id", None)
        with cancel_scope, pytest.raises(BtApiStoreError):
            broker.cancel(order)
        assert [call for call in native.calls if call[0] == "cancel"] == []
        assert order.info.get("cancel_acknowledged") is not True
    finally:
        journal.close()


def test_registered_sim_scalar_grant_switches_exact_route_before_cancel(
    monkeypatch,
):
    second_route = ("i2510", "DCE")
    additional_templates = {
        second_route: {
            "md_front": "tcp://127.0.0.1:1",
            "strategy_identity_sha256": "c" * 64,
            "execution_cycle_id": "second-contract-cycle",
            "preflight_sha256": "d" * 64,
        }
    }
    (
        api,
        store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(
        monkeypatch,
        additional_arm_templates=additional_templates,
    )
    first_route = (facts_helpers._INSTRUMENT, facts_helpers._EXCHANGE)
    expected_first_instrument = sdk_client_module.canonical_ctp_instrument(*first_route)
    expected_second_instrument = sdk_client_module.canonical_ctp_instrument(*second_route)
    try:
        before = api.registered_sim_execution_facts()
        assert before["armed_key"] == first_route
        assert before["current_grant_matches_sdk"] is True
        assert trader.get_execution_gate_state()["instrument"] == expected_first_instrument

        expected_session = {
            "account_fingerprint": order.info["factor_session_account_fingerprint"],
            "connection_generation": order.info["factor_session_connection_generation"],
            "trading_day": order.info["factor_session_trading_day"],
        }
        with _cancel_scope(coordinator, order, facts):
            switched = store.registered_sim_ensure_arm(
                second_route[0],
                second_route[1],
                expected_session=expected_session,
            )
            assert switched["armed"] is True
            after = api.registered_sim_execution_facts()
            assert after["armed_key"] == second_route
            assert after["current_grant_matches_sdk"] is True
            assert after["sdk_gate_projection"]["instrument"] == expected_second_instrument
            assert trader.get_execution_gate_state()["instrument"] == expected_second_instrument
            second_route_history = api.registered_sim_arm_history()
            assert second_route_history[-1]["instrument"] == second_route[0]
            assert second_route_history[-1]["exchange"] == second_route[1]

            broker.cancel(order)

        arm_history = api.registered_sim_arm_history()
        assert [
            (item["instrument"], item["exchange"]) for item in arm_history[-2:]
        ] == [second_route, first_route]
        after_old_order_attempt = api.registered_sim_execution_facts()
        assert after_old_order_attempt["armed_key"] == first_route
        assert after_old_order_attempt["current_grant_matches_sdk"] is True
        cancel_calls = [call for call in native.calls if call[0] == "cancel"]
        assert len(cancel_calls) == 1
        _operation, action_field, request_id = cancel_calls[0]
        assert action_field.InstrumentID == first_route[0]
        assert action_field.ExchangeID == first_route[1]
        assert action_field.OrderRef == order.info["external_order_ref"]
        assert action_field.RequestID == request_id
        assert order.info.get("cancel_acknowledged") is True
    finally:
        journal.close()


def test_registered_sim_arm_keyboard_interrupt_freezes_and_rejects_rearm(monkeypatch):
    api, store, _broker, journal, _coordinator, _target, trader, sdk_client_module, native = (
        _fresh_sdk_store_without_order(monkeypatch)
    )
    interrupt = KeyboardInterrupt("synthetic SDK arm interruption")
    arm_calls = []
    disarm_calls = []
    original_disarm = trader.disarm_execution_gate

    def interrupt_arm(**kwargs):
        arm_calls.append(dict(kwargs))
        raise interrupt

    def record_disarm(capability, reason):
        disarm_calls.append((capability, reason))
        return original_disarm(capability, reason)

    monkeypatch.setattr(trader, "arm_execution_for_registered_sim", interrupt_arm)
    monkeypatch.setattr(trader, "disarm_execution_gate", record_disarm)
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            store.registered_sim_arm(
                instrument=facts_helpers._INSTRUMENT,
                exchange=facts_helpers._EXCHANGE,
                md_front="tcp://182.254.243.31:30012",
                strategy_identity_sha256="a" * 64,
                execution_cycle_id="synthetic-arm-interrupt",
                preflight_sha256="b" * 64,
            )

        assert raised.value is interrupt
        assert len(arm_calls) == 1
        assert disarm_calls == []
        assert [call[0] for call in native.calls if call[0] == "cancel"] == []
        assert api._registered_sim_frozen is True
        assert api._registered_sim_capability is None
        assert api._registered_sim_armed_key is None
        assert store.registered_sim_status()["frozen"] is True
        assert store.registered_sim_status()["armed"] is False
        assert trader.get_execution_gate_state()["armed"] is False
        with pytest.raises(BtApiStoreError):
            store.registered_sim_arm(
                instrument=facts_helpers._INSTRUMENT,
                exchange=facts_helpers._EXCHANGE,
                md_front="tcp://182.254.243.31:30012",
                strategy_identity_sha256="a" * 64,
                execution_cycle_id="synthetic-arm-interrupt-retry",
                preflight_sha256="b" * 64,
            )
        assert len(arm_calls) == 1
    finally:
        journal.close()


@pytest.mark.parametrize("disarm_also_interrupts", [False, True])
def test_registered_sim_arm_readback_keyboard_interrupt_disarms_and_preserves_original(
    monkeypatch, disarm_also_interrupts
):
    api, store, _broker, journal, _coordinator, _target, trader, sdk_client_module, native = (
        _fresh_sdk_store_without_order(monkeypatch)
    )
    getter_interrupt = KeyboardInterrupt("synthetic SDK gate readback interruption")
    disarm_interrupt = KeyboardInterrupt("synthetic SDK disarm interruption")
    getter_calls = []
    disarm_calls = []
    original_getter = trader.get_execution_gate_state
    original_disarm = trader.disarm_execution_gate

    def interrupt_post_arm_getter(client):
        getter_calls.append(None)
        if client is trader and len(getter_calls) == 1:
            raise getter_interrupt
        return original_getter()

    def record_disarm(capability, reason):
        disarm_calls.append((capability, reason))
        result = original_disarm(capability, reason)
        if disarm_also_interrupts and len(disarm_calls) == 1:
            raise disarm_interrupt
        return result

    # Patch the canonical public method at the class boundary so the Store's
    # exact-SDK type/method capability check remains exercised. The injected
    # failure occurs only after the SDK returns its real arm token and state.
    monkeypatch.setattr(
        sdk_client_module.TraderClient,
        "get_execution_gate_state",
        interrupt_post_arm_getter,
    )
    monkeypatch.setattr(trader, "disarm_execution_gate", record_disarm)
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            store.registered_sim_arm(
                instrument=facts_helpers._INSTRUMENT,
                exchange=facts_helpers._EXCHANGE,
                md_front="tcp://182.254.243.31:30012",
                strategy_identity_sha256="a" * 64,
                execution_cycle_id="synthetic-arm-readback-interrupt",
                preflight_sha256="b" * 64,
            )

        assert raised.value is getter_interrupt
        assert len(getter_calls) == 1
        assert len(disarm_calls) == 1
        assert [call[0] for call in native.calls if call[0] == "cancel"] == []
        assert api._registered_sim_frozen is True
        assert api._registered_sim_capability is None
        assert api._registered_sim_armed_key is None
        assert store.registered_sim_status()["frozen"] is True
        assert store.registered_sim_status()["armed"] is False
        assert original_getter()["armed"] is False
        with pytest.raises(BtApiStoreError):
            store.registered_sim_arm(
                instrument=facts_helpers._INSTRUMENT,
                exchange=facts_helpers._EXCHANGE,
                md_front="tcp://182.254.243.31:30012",
                strategy_identity_sha256="a" * 64,
                execution_cycle_id="synthetic-arm-readback-retry",
                preflight_sha256="b" * 64,
            )
        assert len(disarm_calls) == 1
    finally:
        journal.close()


def test_registered_sim_repeated_cancel_action_is_single_shot(monkeypatch):
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    try:
        with _cancel_scope(coordinator, order, facts):
            _expose_production_ctp_request_counter(api)
            broker.cancel(order)
            try:
                broker.cancel(order)
            except BtApiStoreError:
                pass
        assert len([call for call in native.calls if call[0] == "cancel"]) == 1
    finally:
        journal.close()


def test_registered_sim_concurrent_same_owner_cancel_claim_sends_at_most_once(monkeypatch):
    (
        api,
        _store,
        broker,
        journal,
        coordinator,
        _target,
        order,
        facts,
        trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    start = threading.Barrier(3)
    first_forward = threading.Event()
    release_first = threading.Event()
    forward_lock = threading.Lock()
    forward_count = 0
    errors = []

    def hold_first_forward(_target):
        nonlocal forward_count
        with forward_lock:
            forward_count += 1
            should_hold = forward_count == 1
        if should_hold:
            first_forward.set()
            if not release_first.wait(5):
                raise RuntimeError("timed out holding the first CTP cancel forward")

    trader._before_registered_sim_cancel_forward = hold_first_forward
    _expose_production_ctp_request_counter(api)

    def cancel_once():
        try:
            start.wait(5)
            with _cancel_scope(coordinator, order, facts):
                broker.cancel(order)
        except BaseException as error:
            errors.append(error)

    workers = [threading.Thread(target=cancel_once) for _ in range(2)]
    try:
        for worker in workers:
            worker.start()
        start.wait(5)
        assert first_forward.wait(5), "neither same-owner cancel reached the CTP boundary"
        release_first.set()
        for worker in workers:
            worker.join(5)
        assert all(not worker.is_alive() for worker in workers)
        assert all(isinstance(error, BtApiStoreError) for error in errors), errors
        assert len([call for call in native.calls if call[0] == "cancel"]) == 1
    finally:
        release_first.set()
        for worker in workers:
            worker.join(5)
        journal.close()


@pytest.mark.parametrize("bypass", ["markerless_order", "raw_sys_id"])
def test_registered_sim_rejects_markerless_or_raw_ref_owner_bypass(monkeypatch, bypass):
    (
        api,
        store,
        _broker,
        journal,
        _coordinator,
        _target,
        order,
        _facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    try:
        if bypass == "markerless_order":
            markerless_fields = (
                "instrument_id",
                "exchange_id",
                "external_order_ref",
                "external_order_id",
                "ctp_order_ref",
                "order_ref",
                "order_sys_id",
                "factor_intent_id",
                "factor_cancel_intent_id",
                "factor_strategy_scope",
                "factor_position_effect",
                "factor_session_account_fingerprint",
                "factor_session_connection_generation",
                "factor_session_trading_day",
                "factor_session_front_id",
                "factor_session_id",
            )
            order.addinfo(**dict.fromkeys(markerless_fields))
            _expose_production_ctp_request_counter(api)
            with pytest.raises(BtApiStoreError):
                store.cancel_order(order)
        else:
            _expose_production_ctp_request_counter(api)
            with pytest.raises(BtApiStoreError):
                store.cancel_order_ref(
                    "SYS-CANCEL-501",
                    dataname="{}.{}".format(facts_helpers._EXCHANGE, facts_helpers._INSTRUMENT),
                )
        assert [call for call in native.calls if call[0] == "cancel"] == []
    finally:
        journal.close()


def test_registered_sim_rejects_legacy_cancel_after_durable_coordinator_detach(monkeypatch):
    (
        api,
        store,
        broker,
        journal,
        _coordinator,
        _target,
        order,
        _facts,
        _trader,
        _sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(monkeypatch)
    try:
        assert store._registered_sim_durable_owner_configured is True
        broker.factor_execution_coordinator = None
        dataname = "{}.{}".format(facts_helpers._EXCHANGE, facts_helpers._INSTRUMENT)
        for raw_ref in (order.info["external_order_ref"], "SYS-CANCEL-501"):
            with pytest.raises(BtApiStoreError, match="durable cancel coordinator is unavailable"):
                store.cancel_order_ref(raw_ref, dataname=dataname)

        # Removing every order identity field must not turn the same managed
        # Store into the base Broker's targetless legacy fallback.
        order.info.clear()
        with pytest.raises(BtApiStoreError, match="durable cancel coordinator is unavailable"):
            store.cancel_order(order)
        assert [call for call in native.calls if call[0] == "cancel"] == []
    finally:
        journal.close()


def test_store_arm_publication_keyboard_interrupt_freezes_and_disarms(monkeypatch):
    (
        api,
        store,
        _broker,
        journal,
        _coordinator,
        _target,
        trader,
        _sdk_client_module,
        native,
    ) = _fresh_sdk_store_without_order(monkeypatch)
    interrupt = KeyboardInterrupt("synthetic Store arm publication interruption")
    original_arm = api.arm_registered_sim_execution
    successful_grants = []

    def arm_then_return_interrupting_mapping(*args, **kwargs):
        result = original_arm(*args, **kwargs)
        successful_grants.append(result)
        assert result["armed"] is True
        assert trader.get_execution_gate_state()["armed"] is True
        return _InterruptingMapping(interrupt)

    monkeypatch.setattr(api, "arm_registered_sim_execution", arm_then_return_interrupting_mapping)
    native_call_count = len(native.calls)
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            store.registered_sim_arm(
                instrument=facts_helpers._INSTRUMENT,
                exchange=facts_helpers._EXCHANGE,
                md_front="tcp://182.254.243.31:30012",
                strategy_identity_sha256="a" * 64,
                execution_cycle_id="synthetic-arm-publication-interrupt",
                preflight_sha256="b" * 64,
            )

        assert raised.value is interrupt
        assert len(successful_grants) == 1
        assert len(native.calls) == native_call_count
        assert api._registered_sim_frozen is True
        assert api._registered_sim_capability is None
        assert api._registered_sim_armed_key is None
        assert trader.get_execution_gate_state()["armed"] is False
        status = store.registered_sim_status()
        assert status["frozen"] is True
        assert status["armed"] is False
        assert status["instrument"] is None
        assert status["exchange"] is None

        with pytest.raises(BtApiStoreError):
            store.registered_sim_arm(
                instrument=facts_helpers._INSTRUMENT,
                exchange=facts_helpers._EXCHANGE,
                md_front="tcp://182.254.243.31:30012",
                strategy_identity_sha256="a" * 64,
                execution_cycle_id="synthetic-arm-publication-retry",
                preflight_sha256="b" * 64,
            )
        with pytest.raises(BtApiStoreError):
            store.cancel_order_ref("5001", dataname="SHFE.rb2510")
        assert len(successful_grants) == 1
        assert len(native.calls) == native_call_count
    finally:
        journal.close()


def test_store_ensure_arm_publication_keyboard_interrupt_freezes_and_disarms(
    monkeypatch,
):
    second_route = ("i2510", "DCE")
    additional_templates = {
        second_route: {
            "md_front": "tcp://127.0.0.1:1",
            "strategy_identity_sha256": "c" * 64,
            "execution_cycle_id": "publication-switch-cycle",
            "preflight_sha256": "d" * 64,
        }
    }
    (
        api,
        store,
        _broker,
        journal,
        _coordinator,
        _target,
        order,
        _facts,
        trader,
        sdk_client_module,
        native,
    ) = _prepare_bound_order_with_sdk(
        monkeypatch,
        additional_arm_templates=additional_templates,
    )
    interrupt = KeyboardInterrupt("synthetic Store ensure publication interruption")
    original_ensure = api.ensure_registered_sim_arm_for
    successful_grants = []
    expected_session = {
        "account_fingerprint": order.info["factor_session_account_fingerprint"],
        "connection_generation": order.info["factor_session_connection_generation"],
        "trading_day": order.info["factor_session_trading_day"],
    }
    first_route = (facts_helpers._INSTRUMENT, facts_helpers._EXCHANGE)
    assert api._registered_sim_armed_key == first_route
    assert trader.get_execution_gate_state()["armed"] is True

    def ensure_then_return_interrupting_mapping(*args, **kwargs):
        result = original_ensure(*args, **kwargs)
        successful_grants.append(result)
        assert result["armed"] is True
        assert result["switched"] is True
        assert api._registered_sim_armed_key == second_route
        assert trader.get_execution_gate_state()["armed"] is True
        assert trader.get_execution_gate_state()["instrument"] == (
            sdk_client_module.canonical_ctp_instrument(*second_route)
        )
        return _InterruptingMapping(interrupt)

    monkeypatch.setattr(api, "ensure_registered_sim_arm_for", ensure_then_return_interrupting_mapping)
    native_call_count = len(native.calls)
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            store.registered_sim_ensure_arm(
                second_route[0],
                second_route[1],
                expected_session=expected_session,
            )

        assert raised.value is interrupt
        assert len(successful_grants) == 1
        assert len(native.calls) == native_call_count
        assert api._registered_sim_frozen is True
        assert api._registered_sim_capability is None
        assert api._registered_sim_armed_key is None
        assert trader.get_execution_gate_state()["armed"] is False
        status = store.registered_sim_status()
        assert status["frozen"] is True
        assert status["armed"] is False
        assert status["instrument"] is None
        assert status["exchange"] is None

        with pytest.raises(BtApiStoreError):
            store.registered_sim_ensure_arm(
                second_route[0],
                second_route[1],
                expected_session=expected_session,
            )
        with pytest.raises(BtApiStoreError):
            store.cancel_order(order)
        assert len(successful_grants) == 1
        assert len(native.calls) == native_call_count
    finally:
        journal.close()
