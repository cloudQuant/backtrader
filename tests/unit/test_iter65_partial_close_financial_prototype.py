"""Synthetic partial close through BackBroker and the local Gateway financial path.

Commands are pre-created before journal upgrade; market, source fence, grant and
transport are synthetic. This does not establish real admission, final fees,
cross-day recovery, multi-strategy behavior, or complete D63-44 acceptance.
"""
from decimal import Decimal
import itertools
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt
import bt_api_base
import bt_api_gateway
import bt_api_py
import pandas as pd
import pytest

from bt_api_base.direct_write_protocol import DirectExecutionEventKind
from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.service_protocol import (
    WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader, WireIdentity, WireMessageKind,
    WireRole, WireScope,
)
from bt_api_gateway.direct_dispatch import GatewayDirectDispatcher
from bt_api_py.gateway_direct_client import GatewayClientRoute
from bt_api_py.gateway_direct_owner import GatewayDirectOwner, GatewayDirectOwnerResources
from bt_api_py.gateway_direct_service import GatewayDirectGrant, GatewayDirectServiceBinding
from bt_api_py.gateway_execution_time import GatewayExecutionTimePolicy
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant, ServiceCapability, ServiceRegistry
from bt_api_py.service_runtime_thread import BindingSnapshot, RuntimeSnapshot
from backtrader.live_state import StrategyStateDir
from backtrader.live_state.gateway_pending import GatewayPendingHost
from tests.unit.brokers.test_iter63_gateway_stream_consumer import INSTRUMENT, framework
from tests.unit.test_iter65_gateway_strategy_value_prototype import make_session
from tests.unit.test_iter65_shared_financial_events_prototype import World, LEDGER_INSTRUMENT

WORKSPACE = Path(__file__).resolve().parents[3]
OP = "direct.strategy_financial"


class PartialClose(bt.Strategy):
    def __init__(self):
        self.fills = []
        self.cuts = {}

    def notify_order(self, order):
        if order.status == order.Completed:
            self.fills.append({"side": "buy" if order.isbuy() else "sell",
                "quantity": abs(order.executed.size), "price": order.executed.price,
                "commission": order.executed.comm, "realized": order.executed.pnl})

    def next(self):
        self.cuts[len(self)] = {
            "cash": self.get_strategy_cash(), "value": self.get_strategy_value(),
            "position": self.get_strategy_position().size,
            "realized": sum(fill["realized"] for fill in self.fills),
            "fees": sum(fill["commission"] for fill in self.fills),
            "unrealized": (self.data.close[0] - self.position.price) * self.position.size * 10,
        }
        if len(self) == 1:
            self.buy(size=2)
        elif len(self) == 2:
            self.sell(size=1)


def _backbroker():
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.broker.setcash(100000)
    # BT fee is price * quantity * 0.001; Gateway uses notional * 0.0001.
    cerebro.broker.setcommission(commission=0.001, margin=3000, mult=10,
        commtype=bt.CommInfoBase.COMM_PERC, stocklike=False, percabs=True)
    prices = [3000., 3000., 3100., 3200.]
    bars = pd.DataFrame({"open": prices, "high": prices, "low": prices,
                         "close": prices, "volume": [1.] * len(prices)},
                        index=pd.date_range("2026-11-09", periods=len(prices), freq="min"))
    cerebro.adddata(bt.feeds.PandasData(dataname=bars, name="rb2601"))
    cerebro.addstrategy(PartialClose)
    return cerebro.run()[0]


def test_partial_close_shared_actual_fills_and_duplicate(tmp_path, monkeypatch):
    for module in (bt, bt_api_base, bt_api_gateway, bt_api_py):
        assert Path(module.__file__).resolve().is_relative_to(WORKSPACE)
    strategy_bt = _backbroker()
    assert strategy_bt.fills == [
        {"side": "buy", "quantity": 2, "price": 3000., "commission": 6., "realized": 0.},
        {"side": "sell", "quantity": 1, "price": 3100., "commission": 3.1, "realized": 1000.},
    ]
    # Independent arithmetic: 100000 + realized + unrealized - cumulative fees.
    expected_bt = {
        2: dict(position=2, realized=0, unrealized=0, fees=6, value=99994, cash=93994),
        3: dict(position=1, realized=1000, unrealized=1000, fees=9.1, value=101990.9, cash=98990.9),
        4: dict(position=1, realized=1000, unrealized=2000, fees=9.1, value=102990.9, cash=99990.9),
    }
    for cut, expected in expected_bt.items():
        assert strategy_bt.cuts[cut] == pytest.approx(expected)

    holder = {}
    def factory():
        world = World(tmp_path)
        for index, fill in enumerate(strategy_bt.fills):
            world.order("s1", f"order-{index}", fill["side"], "open" if index == 0 else "close",
                        quantity=str(fill["quantity"]), price=str(int(fill["price"])))
        world.upgrade()
        world.tick(3000)
        world.producer(refresh_seconds=1, price_max_age_seconds=60)
        def never_dispatch(*_args, **_kwargs):
            raise AssertionError("synthetic comparison does not dispatch")
        dispatcher = GatewayDirectDispatcher(world.journal, "CTP", world.guard, never_dispatch,
                                              lambda _: ("synthetic-anchor",), lambda _: False)
        holder["world"] = world
        def cleanup():
            world.source.close()
            world.guard.release()
        return GatewayDirectOwnerResources(dispatcher, world.journal, cleanup)

    owner = GatewayDirectOwner(factory, queue_size=8, max_queue_wait_seconds=1, busy_timeout_seconds=1)
    assert owner.start(2)
    registry = None
    try:
        world = holder["world"]
        journal = world.journal
        identity = WireIdentity(WireRole.STRATEGY_CLIENT, "p", "s1")
        scope = WireScope("synthetic-domain", account_ref="acct", strategy_ref="s1", run_id="run1")
        grant_scope = WireScope("synthetic-domain", account_ref="acct", strategy_ref="s1")
        ops = frozenset({OP})
        registry = ServiceRegistry(":memory:", service_id="gateway-service",
            capabilities=(ServiceCapability("gateway", "service.direct_write", ops, frozenset()),),
            grants={"p": (PrincipalGrant(identity, (ResourceGrant("gateway", "service.direct_write",
                "scope", grant_scope, ops),)),)}, policy_version="p", requirements_version="r")
        service = GatewayDirectServiceBinding(journal, {"p": GatewayDirectGrant("s1", frozenset({"rb"}))},
                                               owner=owner, strategy_financial_enabled=True)
        registry.register_handler("gateway", OP, lambda ctx, args: service.handle(OP, context=ctx, arguments=args))
        ids = itertools.count(1)
        def request(operation, payload):
            return WireEnvelope(header=WireHeader(protocol_version=WIRE_PROTOCOL_VERSION,
                kind=WireMessageKind.REQUEST, message_id="message-" + str(next(ids)), correlation_id=None,
                identity=identity, scope=scope, operation=operation,
                schema_id="sdk.service.control" if operation.startswith("service.") else "sdk.service.call",
                schema_version=1, sent_at_utc="2026-11-09T00:00:00Z"), payload=payload)
        registered = registry.handle("p", request("service.register", {
            "registration_key": "synthetic-registration", "client_session_id": "synthetic-session",
            "instance_id": "gateway", "port": "service.direct_write", "scope_ref": "scope",
            "operations": (OP,)}))
        assert registered["ok"]
        rec = registered["result"]
        route = GatewayClientRoute("broker.direct_write", "gateway-service", "gateway", "scope", scope, identity)
        bt_dir = tmp_path / "bt-state"
        bt_dir.mkdir()
        state = StrategyStateDir.initialize(bt_dir)
        binding = GatewayCommandBinding(journal.journal_id, "acct", "s1", "p")
        GatewayPendingHost.upgrade_for_gateway(bt_dir, state.strategy_uuid, binding)
        GatewayPendingHost.upgrade_for_cancellation(bt_dir, state.strategy_uuid, binding)
        consumer = gateway_execution_consumer_ref(principal_ref="p", actor_ref="s1",
            execution_domain_ref="synthetic-domain", account_scope="acct", strategy_scope="s1")
        host = GatewayPendingHost.upgrade_for_execution(bt_dir, state.strategy_uuid, binding, consumer_ref=consumer)
        session, api = make_session(host, route)
        reg = BindingSnapshot(rec["registration_id"], rec["service_epoch"], True, route.mount,
            route.service_id, route.instance_id, route.scope_ref, scope, ops, True)
        runtime_snapshot = RuntimeSnapshot("running", True, True, None, (reg,), 0, 0, identity, "run1")
        monkeypatch.setattr(session.runtime, "status", lambda: runtime_snapshot)
        def in_process_call(_mount, operation, arguments, **_kwargs):
            response = registry.handle("p", request(operation, {"registration_id": rec["registration_id"],
                "service_epoch": rec["service_epoch"], "instance_id": "gateway", "arguments": arguments}))
            assert response["ok"]
            return response["result"]
        monkeypatch.setattr(session.runtime, "call", in_process_call)
        data, broker, strategy_gateway = framework()
        broker.store = SimpleNamespace(_gateway_mode=True, is_connected=True, gateway_api=api,
            gateway_strategy_config=SimpleNamespace(strategy_finance_currency="CNY"))
        broker.bind_gateway_execution_stream(strategy_gateway, api=api, host=host, data_by_ref={"rb": data},
            orders_by_key={}, instrument_by_ref={"rb": INSTRUMENT},
            time_policy=GatewayExecutionTimePolicy("CTP___FUTURE", "UTC"))

        def owner_call(fn):
            return owner.submit_service_call(fn).result(timeout_seconds=2)
        def apply_fill(index):
            fill = strategy_bt.fills[index]
            world.fill(f"order-{index}", fill["side"], "open" if index == 0 else "close",
                       str(fill["quantity"]), str(int(fill["price"])), f"synthetic-trade-{index}")
            world.step()
        def inspect():
            return world.read(), Decimal(world.ledger.position("s1", LEDGER_INSTRUMENT))
        def check(expected, cut):
            snap, position = owner_call(inspect)
            assert (position, Decimal(snap.realized_pnl), Decimal(snap.unrealized_pnl),
                    Decimal(snap.fees), Decimal(snap.margin), Decimal(snap.reservations),
                    snap.value, snap.cash) == tuple(Decimal(str(x)) for x in expected)
            assert (strategy_gateway.get_strategy_cash(), strategy_gateway.get_strategy_value()) == pytest.approx(
                (float(snap.cash), float(snap.value)))
            assert strategy_bt.cuts[cut]["value"] == pytest.approx(float(snap.value))
            return snap

        owner_call(lambda: apply_fill(0))
        check((2, 0, 0, 6, 6000, 0, 99994, 93994), 2)
        def close_and_mark():
            world.tick(3100)
            apply_fill(1)
        owner_call(close_and_mark)
        closed = check((1, 1000, 1000, 9.1, 3100, 0, 101990.9, 98890.9), 3)
        assert strategy_bt.cuts[3]["cash"] - float(closed.cash) == pytest.approx(100)
        def duplicate():
            return world.ledger.ingest(world._fact("order-1", kind=DirectExecutionEventKind.TRADE,
                side="sell", offset="close", quantity="1", price="3100",
                trade_key=("SHFE", "synthetic-trade-1")))
        result = owner_call(duplicate)
        assert not result.applied and result.reason == "TRADE_DUPLICATE"
        owner_call(world.step)
        check((1, 1000, 1000, 9.1, 3100, 0, 101990.9, 98890.9), 3)
        def mark():
            world.tick(3200)
            world.step()
        owner_call(mark)
        marked = check((1, 1000, 2000, 9.1, 3200, 0, 102990.9, 99790.9), 4)
        assert strategy_bt.cuts[4]["cash"] - float(marked.cash) == pytest.approx(200)
    finally:
        if registry is not None:
            registry.close()
        assert owner.close(2)
