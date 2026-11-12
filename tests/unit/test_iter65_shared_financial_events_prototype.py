"""One synthetic fill stream through BackBroker and Gateway financial producer.

No provider, account, credentials or network is used.  Gateway commands are
pre-created in an isolated test journal before its schema upgrade; this does
not exercise Gateway's real close-order admission.  The market/rates, grant and
in-process transport are controlled substitutes.  These are bounded
single-strategy long/short futures vectors, not D63-44/45 or iteration acceptance.
"""

from decimal import Decimal
import itertools
from pathlib import Path
import sys
from types import SimpleNamespace

import backtrader as bt
import bt_api_base
import bt_api_gateway
import bt_api_py
import pandas as pd
import pytest

from bt_api_base.gateway_direct_protocol import GatewayCommandBinding
from bt_api_base.gateway_execution_stream_protocol import gateway_execution_consumer_ref
from bt_api_base.service_protocol import (
    WIRE_PROTOCOL_VERSION, WireEnvelope, WireHeader, WireIdentity, WireMessageKind, WireRole, WireScope,
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

WORKSPACE = Path(__file__).resolve().parents[3]
SDK = WORKSPACE / "bt_api_py"
_helper_paths = (str(SDK / "tests" / "unit"), str(SDK / "bt_api" / "bt_api_gateway" / "tests"))
sys.path[:0] = _helper_paths
try:
    from test_iter63_ctp_gateway_strategy_financial import World  # noqa: E402
    from test_iter63_direct_execution_journal import INSTRUMENT as LEDGER_INSTRUMENT  # noqa: E402
finally:
    for _helper_path in _helper_paths:
        sys.path.remove(_helper_path)

OP = "direct.strategy_financial"


@pytest.fixture(scope="module", autouse=True)
def isolated_sources():
    for module in (bt, bt_api_base, bt_api_gateway, bt_api_py):
        assert Path(module.__file__).resolve().is_relative_to(WORKSPACE)
    yield
    escaped = {}
    for name, module in tuple(sys.modules.items()):
        if name == "backtrader" or name.startswith(("backtrader.", "bt_api_py", "bt_api_")):
            source = getattr(module, "__file__", None)
            if source and not Path(source).resolve().is_relative_to(WORKSPACE):
                escaped[name] = source
    assert not escaped, f"non-worktree modules: {escaped}"


class FuturesVector(bt.Strategy):
    params = (("short", False),)

    def __init__(self):
        self.fills = []
        self.cuts = {}

    def notify_order(self, order):
        if order.status == order.Completed:
            self.fills.append({"side": "buy" if order.isbuy() else "sell",
                "quantity": abs(order.executed.size), "price": order.executed.price,
                "commission": order.executed.comm})

    def next(self):
        self.cuts[len(self)] = (self.get_strategy_cash(), self.get_strategy_value(),
                                self.get_strategy_position().size)
        if len(self) == 1:
            self.sell(size=1) if self.p.short else self.buy(size=1)
        elif len(self) == 3:
            self.buy(size=1) if self.p.short else self.sell(size=1)


def backbroker_vector(automargin, short=False):
    cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
    cerebro.broker.setcash(100000)
    # BackBroker's percentage fee applies to price*size; Gateway's 0.0001
    # applies to price*size*multiplier, hence these produce the same per-fill fee.
    cerebro.broker.setcommission(commission=0.001, margin=3600 if short else 3000, mult=10, automargin=automargin,
        commtype=bt.CommInfoBase.COMM_PERC, stocklike=False, percabs=True)
    prices = [3000., 3000., 2900., 2900.] if short else [3000., 3000., 3100., 3100.]
    bars = pd.DataFrame({"open": prices, "high": prices, "low": prices,
                         "close": prices, "volume": [1.] * len(prices)},
                        index=pd.date_range("2026-11-09", periods=len(prices), freq="min"))
    cerebro.adddata(bt.feeds.PandasData(dataname=bars, name="rb2601"))
    cerebro.addstrategy(FuturesVector, short=short)
    return cerebro.run()[0]


@pytest.mark.parametrize(("short", "automargin", "marked_bt_value"), [
    (False, False, 100997.), (False, 1.0, 101097.),
    (True, False, 100997.), (True, 1.2, 100877.),
], ids=["long_fixed_margin", "long_price_based_automargin",
        "short_fixed_margin", "short_price_based_automargin"])
def test_single_strategy_fills_reach_backbroker_and_gateway_getters(
        tmp_path, monkeypatch, short, automargin, marked_bt_value):
    strategy_bt = backbroker_vector(automargin, short)
    closing_price = 2900. if short else 3100.
    opening_side, closing_side = ("sell", "buy") if short else ("buy", "sell")
    opening_cash = 96397. if short else 96997.
    marked_cash = 97397. if short else 97997.
    closed_cash = 100994.1 if short else 100993.9
    assert strategy_bt.fills == [
        {"side": opening_side, "quantity": 1, "price": 3000., "commission": 3.},
        {"side": closing_side, "quantity": 1, "price": closing_price, "commission": closing_price * 0.001},
    ]
    assert strategy_bt.cuts[2] == pytest.approx((opening_cash, 99997., -1. if short else 1.))
    assert strategy_bt.cuts[3] == pytest.approx((marked_cash, marked_bt_value, -1. if short else 1.))
    assert strategy_bt.cuts[4] == pytest.approx((closed_cash, closed_cash, 0.))
    holder = {}

    def factory():
        world = World(tmp_path)
        # Existing World helper requires commands before upgrading the journal.
        # The synthetic close is therefore a pre-existing journal command;
        # this test does not claim a real close admission at this point.
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

        def replay_fill(index):
            fill = strategy_bt.fills[index]
            def apply():
                world.fill(f"order-{index}", fill["side"], "open" if index == 0 else "close",
                           str(fill["quantity"]), str(int(fill["price"])), f"synthetic-trade-{index}")
                world.step()
                return world.read(), world.ledger.position("s1", LEDGER_INSTRUMENT)
            return owner_call(apply)

        opened, open_position = replay_fill(0)
        assert (opened.cash, opened.value, Decimal(opened.fees), Decimal(open_position)) == (
            Decimal(str(opening_cash)), Decimal("99997"), Decimal("3"), Decimal("-1" if short else "1"))
        assert Decimal(opened.margin) == Decimal("3600" if short else "3000")
        assert (strategy_gateway.get_strategy_cash(), strategy_gateway.get_strategy_value()) == pytest.approx(
            strategy_bt.cuts[2][:2])

        def mark():
            world.tick(int(closing_price))
            world.step()
            return world.read()
        marked = owner_call(mark)
        assert (marked.cash, marked.value, Decimal(marked.unrealized_pnl)) == (
            Decimal("97517" if short else "97897"), Decimal("100997"), Decimal("1000"))
        assert Decimal(marked.margin) == Decimal("3480" if short else "3100")
        assert strategy_gateway.get_strategy_value() == pytest.approx(100997.)
        assert strategy_gateway.get_strategy_cash() == pytest.approx(97517. if short else 97897.)
        assert strategy_bt.cuts[3][0] - strategy_gateway.get_strategy_cash() == pytest.approx(-120. if short else 100.)
        # BackBroker's auto margin changes marked position value, not its
        # strategy cash; the observed value discrepancy is not normalized away.
        assert strategy_bt.cuts[3][1] - strategy_gateway.get_strategy_value() == pytest.approx(
            (-120. if short else 100.) if automargin else 0.)

        closed, close_position = replay_fill(1)
        assert (closed.cash, closed.value, Decimal(closed.fees), Decimal(close_position)) == (
            Decimal(str(closed_cash)), Decimal(str(closed_cash)), Decimal("5.9" if short else "6.1"), Decimal("0"))
        assert (strategy_gateway.get_strategy_cash(), strategy_gateway.get_strategy_value()) == pytest.approx(
            strategy_bt.cuts[4][:2])
    finally:
        if registry is not None:
            registry.close()
        assert owner.close(2)
