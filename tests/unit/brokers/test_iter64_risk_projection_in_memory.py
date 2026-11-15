"""64.08 synthetic BT projection and counterfactual checks, entirely in memory.

The API result is an authenticated-result *stand-in*: neither SDK first-send
proof nor provider, service, persistence, or account behavior is exercised.
"""
import ast
import inspect
import itertools
import textwrap
from collections.abc import Mapping
from types import SimpleNamespace

import pytest
import backtrader as bt
import pandas as pd
from bt_api_base.market_protocol import MarketInstrumentKey
from bt_api_py.gateway_api import GatewayRiskRoutedResult
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy

import backtrader.brokers.btapibroker as broker_module
import backtrader.stores.btapistore as store_module
from backtrader.metabase import OwnerContext


class Strategy(bt.Strategy):
    pass


def framework():
    frame = pd.DataFrame(
        {"open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0], "volume": [1.0]},
        index=pd.to_datetime(["2026-11-03 09:00"]),
    )
    data = bt.feeds.PandasData(dataname=frame, name="rb")
    data._start()
    assert data.load()
    broker = bt.brokers.BtApiBroker()
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas, cerebro.datasbyname = [data], {"rb": data}
    with OwnerContext.set_owner(cerebro):
        strategy = Strategy.__new__(Strategy)
    strategy.datas, strategy.data = [data], data
    strategy._tradehistoryon, strategy._quicknotify = True, False
    return data, broker, strategy


class NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass


class ThreadingStub:
    def __init__(self, original):
        self.original = original

    def Lock(self):
        return NoLock()

    def RLock(self):
        return NoLock()

    def __getattr__(self, name):
        return getattr(self.original, name)


class MemoryHost:
    def __init__(self):
        self._binding = SimpleNamespace(account_scope="account")
        self.intents, self.snapshots, self.notices = {}, {}, {}
        self.saved_path = None
        self.ticket = object()

    def save(self, intent, *, local_seq, bt_ref, snapshot):
        self.saved_path = "ticket"
        self._save(intent, snapshot)
        return self.ticket

    def save_submitted_order_intent(self, intent, *, local_seq, bt_ref, snapshot):
        self.saved_path = "legacy"
        self._save(intent, snapshot)

    def _save(self, intent, snapshot):
        key = intent.request_key
        self.intents[key], self.snapshots[key] = intent, snapshot
        self.notices[key] = {"notification_id": "submitted"}

    def consume(self, *_args):
        raise AssertionError("synthetic reserve must not consume a real ticket")

    def validate(self, *_args):
        raise AssertionError("synthetic reserve must not validate a real ticket")

    def load_intent(self, key):
        return self.intents.get(key)

    def load_record(self, _key):
        return None

    def load_order_snapshot(self, key):
        return self.snapshots.get(key)

    def local_order_notifications(self):
        return self.notices

    def save_rejected_order_notification(self, key, *, bt_ref, snapshot, code):
        self.snapshots[key] = snapshot
        self.notices["reject:" + key] = {"notification_id": "rejected", "code": code}
        return self.notices["reject:" + key]


class SyntheticApi:
    risk_selected = True
    risk_available = True

    def __init__(self, host, result):
        self.host, self.result, self.calls = host, result, []
        self.reserve_path = None

    def risk_first_send_reserve_contract(self):
        return ("local-first-send-ticket-v1", self.reserve,
                ("local-first-send-host-v1", self.host.save, self.host.consume, self.host.validate))

    def reserve(self, route, request, *, first_send_ticket, **_kwargs):
        assert self.host.saved_path == "ticket" and first_send_ticket is self.host.ticket
        self.reserve_path = "ticket"
        return self._result(route, request)

    def reserve_order(self, route, request, *, timeout_seconds):
        assert self.host.saved_path == "legacy"
        self.reserve_path = "legacy"
        return self._result(route, request)

    def _result(self, route, request):
        assert self.host.load_intent(request.idempotency_key) is not None
        self.calls.append((route, request.idempotency_key))
        return self.result

    def dispatch_order(self, *_args, **_kwargs):
        pytest.fail("a refusal must never dispatch")


class Sequence:
    strategy_uuid = "00000000-0000-0000-0000-000000000001"

    def allocate(self, _ref):
        return 1


def submit_synthetic(monkeypatch, result):
    # Only Broker's unused lock fields are replaced; the framework is real.
    monkeypatch.setattr(broker_module, "threading", ThreadingStub(broker_module.threading))
    data, broker, strategy = framework()
    key = MarketInstrumentKey("ctp", "exchange", "paper", "future", "rb", "rb")
    host = MemoryHost()
    api = SyntheticApi(host, result)
    policy = GatewayExecutionTimePolicy("CTP___FUTURE", "UTC")
    broker.store = SimpleNamespace(_gateway_mode=True,
        gateway_strategy_config=SimpleNamespace(risk_selection=object()), gateway_api=api,
        contract_metadata={"rb": {"instrument_key": key.to_dict(), "exchange_name": policy.route,
                                  "quantity_unit": "lots", "time_in_force": "GFD"}})
    notice = SimpleNamespace(strategy=strategy, host=host, feeds={"rb": data}, orders={},
                             fault=None, armed=None, receipt=None, restored=None)
    binding = SimpleNamespace(strategy=strategy, host=host, feeds={"rb": data}, instruments={"rb": key},
        api=api, policy=policy, sequence=Sequence(), stream=SimpleNamespace(_route=object()),
        state="ACTIVE", timeout=1, reserve_unknown={}, local_deferred=[])
    broker._gateway_stream_binding = binding
    monkeypatch.setattr(broker, "_gateway_binding", lambda *_args, **_kwargs: notice)
    monkeypatch.setattr(broker, "_gateway_stream_check", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(broker, "_gateway_require_trade_qualification", lambda *_args: {})
    import bt_api_py.gateway_direct_client as client
    monkeypatch.setattr(client, "build_gateway_order_intent", lambda _b, _r, req:
                        SimpleNamespace(request_key=req.idempotency_key))
    order = bt.BuyOrder(owner=strategy, data=data, size=1, price=10, exectype=bt.Order.Limit)
    order.addinfo(offset="open", quantity_unit="lots", time_in_force="GFD")
    broker.submit(order)
    return broker, host, api, order


def assert_projection(monkeypatch, result, *, risk, summary):
    broker, host, api, order = submit_synthetic(monkeypatch, result)
    key = order.info.gateway_request_key
    assert api.calls == [("CTP___FUTURE", key)]
    assert api.reserve_path == host.saved_path and api.reserve_path in {"legacy", "ticket"}
    assert order.status == order.Rejected and order.executed.size == 0
    assert order.info.get("risk_denied") == risk, "projected risk_denied differs"
    assert order.info.get("gateway_request_denied") == (None if risk else result.code)
    assert host.notices["reject:" + key]["code"] == result.code
    notices = [broker.get_notification(), broker.get_notification()]
    assert [n.status for n in notices] == [order.Submitted, order.Rejected]
    assert notices[1].info.get("risk_denied") == risk
    assert broker.get_execution_summary()["risk"] == {
        "selected": True, "available": True, "refusals": summary}


def test_synthetic_risk_denial_reaches_broker_notice_and_execution_summary(monkeypatch):
    result = GatewayRiskRoutedResult("REQUEST_DENIED", code="RISK_ORDER_QUANTITY_EXCEEDS_CAP",
        risk_code="risk_order_quantity_exceeds_cap", risk_denied="risk_order_quantity_exceeds_cap")
    assert_projection(monkeypatch, result, risk="risk_order_quantity_exceeds_cap",
                      summary={"risk_order_quantity_exceeds_cap": 1})


def test_synthetic_gateway_denial_does_not_invent_risk_denial(monkeypatch):
    result = GatewayRiskRoutedResult("REQUEST_DENIED", code="CONTROL_STOP_NEW")
    assert_projection(monkeypatch, result, risk=None, summary={})


def mutated_method(method, old, new, second=None):
    """Compile an isolated counterfactual; do not modify or write product code."""
    source = textwrap.dedent(inspect.getsource(method))
    assert source.count(old) == 1
    source = source.replace(old, new, 1)
    if second is not None:
        assert source.count(second[0]) == 1
        source = source.replace(second[0], second[1], 1)
    source = source.replace("super().__init__()", "super(BtApiStore, self).__init__()")
    namespace = dict(method.__globals__)
    exec(compile(ast.parse(source), "<in-memory mutation>", "exec"), namespace)
    return namespace[method.__name__]


class LazyMapping(Mapping):
    def __init__(self, items):
        self.items = items

    def __getitem__(self, key):
        return self.items[key]

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __contains__(self, _key):
        return False


def assert_rejected(**kwargs):
    with pytest.raises(store_module.BtApiStoreError) as error:
        store_module.BtApiStore(**kwargs)
    assert error.value.code == "risk_requires_gateway"


@pytest.mark.parametrize("case,old,new", [
    ("top", 'if "risk" in source:', 'if False:'),
    ("nested", 'isinstance(section, Mapping) and "risk" in section', 'False'),
    ("sources", 'enumerate((config, api_kwargs, kwargs))', 'enumerate((config,))'),
    ("snapshot", 'snapshot[section_name] = dict(section)', 'snapshot[section_name] = section'),
])
def test_store_checks_have_counterfactual_detection(monkeypatch, case, old, new):
    cases = {
        "top": {"config": {"risk": None}},
        "nested": {"config": {"gateway": {"risk": None}}},
        "sources": {"config": {"gateway": {}}, "api_kwargs": {"gateway": {"risk": None}}},
        "snapshot": {"config": {"gateway": LazyMapping({"risk": None})}},
    }
    # Stop immediately after validation if a mutant erroneously permits input.
    class Escaped(Exception):
        pass
    monkeypatch.setattr(store_module, "StoreRouteIdentityPolicy", lambda *_a, **_kw: (_ for _ in ()).throw(Escaped()))
    assert_rejected(**cases[case])
    mutant = mutated_method(store_module.BtApiStore.__init__, old, new)
    monkeypatch.setattr(store_module.BtApiStore, "__init__", mutant)
    with pytest.raises(Escaped):
        store_module.BtApiStore(**cases[case])


def test_refusal_projection_counterfactual_is_detected(monkeypatch):
    from backtrader.brokers._btapi_gateway_stream import GatewayExecutionStreamBrokerMixin
    original = GatewayExecutionStreamBrokerMixin._gateway_finalize_rejection
    mutant = mutated_method(original, 'info if info is not None else {"gateway_request_denied": code}',
                             '{"gateway_request_denied": code}')
    result = GatewayRiskRoutedResult("REQUEST_DENIED", code="RISK_ORDER_QUANTITY_EXCEEDS_CAP",
        risk_code="risk_order_quantity_exceeds_cap", risk_denied="risk_order_quantity_exceeds_cap")
    monkeypatch.setattr(GatewayExecutionStreamBrokerMixin, "_gateway_finalize_rejection", mutant)
    with pytest.raises(AssertionError, match="^projected risk_denied differs"):
        assert_projection(monkeypatch, result, risk="risk_order_quantity_exceeds_cap",
                          summary={"risk_order_quantity_exceeds_cap": 1})


def test_consumed_snapshot_cannot_change_after_validation(monkeypatch):
    class ChangingSection(Mapping):
        def __init__(self):
            self.reads = 0

        def __iter__(self):
            self.reads += 1
            return iter(("marker",) if self.reads == 1 else ("risk",))

        def __getitem__(self, key):
            return "safe" if key == "marker" else None

        def __len__(self):
            return 1

    class Reached(Exception):
        pass

    captured = []
    class CapturePolicy:
        def __init__(self, store, **_kwargs):
            self.store = store

        def write_route_names(self, *_args, **_kwargs):
            captured.append(self.store._config["gateway"])
            raise Reached()

    monkeypatch.setattr(store_module, "StoreRouteIdentityPolicy", CapturePolicy)

    def check():
        section = ChangingSection()
        with pytest.raises(Reached):
            store_module.BtApiStore(config={"gateway": section}, api_kwargs={"gateway": {}})
        assert captured.pop() == {"marker": "safe"}, "consumed configuration is not the validated snapshot"
        assert section.reads == 1

    check()
    mutant = mutated_method(store_module.BtApiStore.__init__,
        "snapshots = []", "original_config = config\n        snapshots = []",
        second=("self._config = config", "self._config = original_config"))
    monkeypatch.setattr(store_module.BtApiStore, "__init__", mutant)
    with pytest.raises(AssertionError, match="^consumed configuration is not the validated snapshot"):
        check()
