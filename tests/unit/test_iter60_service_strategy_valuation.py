"""Iteration 60 (R2-D): positive strategy valuation in service mode.

The SDK host answers a strategy ``OWNER_BOOK`` from its strategy ledger: one
ledger transaction yields positions, cash, costs, instrument terms and the
reconciliation verdict with one declared cut id (Base snapshot contract 2).
BT consumes that typed snapshot through ``ServiceStrategyAccountBookView`` and
values it with the same rules as direct mode: same-transaction cut, BALANCED
verdict, and the live-mark contract (``BtApiFeed`` mark on the Broker's Store
route, absolute age ``strategy_mark_max_age_seconds``).

Evidence: UNIT/FAKE. The real SDK read adapter, real SDK typed-reply decoder,
temp SQLite ledger/execution store and a subscription state fed by the test;
the RPC transport is replaced by a MessagePack round trip (no network).
"""

from __future__ import annotations

import datetime as dt
import itertools
import threading
from decimal import Decimal

import pytest

pytest.importorskip("bt_api_execution")
msgpack = pytest.importorskip("msgpack")

import backtrader as bt  # noqa: E402
from backtrader.metabase import OwnerContext  # noqa: E402
from backtrader.service.service_strategy_account_book import (  # noqa: E402
    ServiceStrategyAccountBookError,
    ServiceStrategyAccountBookView,
    value_strategy_book,
)
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope  # noqa: E402
from bt_api_execution import ExecutionScope, SqliteExecutionStore  # noqa: E402
from bt_api_py.account_position_stream import StreamedAccountPositions  # noqa: E402
from bt_api_py.service_account_book_client import ServiceStrategyAccountBookClient  # noqa: E402
from bt_api_py.service_execution_account_books import (  # noqa: E402
    ExecutionAccountBookReadAdapter,
    StrategyLedgerBookSourceV1,
)
from bt_api_py.strategy_ledger import (  # noqa: E402
    InstrumentTerms,
    LedgerIntent,
    SqliteStrategyLedger,
    StrategyBudget,
    StrategyCapital,
)
from tests.unit import test_iter60_live_mark_eligibility as marks  # noqa: E402
from tests.unit import test_iter60_target_orders_scope as scope  # noqa: E402

DOMAIN = "paper:bt-iter60-service-valuation"
ACCOUNT = "acct-service-valuation"
STRATEGY = "A"
PRINCIPAL = "strategy-a-principal"
WIRE = WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=STRATEGY)
IDENTITY = WireIdentity(WireRole.STRATEGY_CLIENT, PRINCIPAL, STRATEGY)


class _HostSource:
    """Host-bound account-book resource binding the account's strategy ledger."""

    def __init__(self, ledger, positions):
        self.ledger = ledger
        self.positions = positions

    def authorize_account_view(self, **_kwargs):
        return False

    def read_inputs(self, **_kwargs):  # pragma: no cover - strategy views never use it
        raise AssertionError("execution inputs are not read for strategy ledger views")

    def read_strategy_ledger(self, *, account_key):
        return StrategyLedgerBookSourceV1(self.ledger, self.positions)


class _WireClient:
    """The SDK client's real typed decoder behind an in-process "RPC"."""

    def __init__(self, adapter, tamper=None):
        decoder = object.__new__(ServiceStrategyAccountBookClient)
        object.__setattr__(decoder, "strategy_ref", STRATEGY)
        object.__setattr__(decoder, "account_ref", ACCOUNT)
        self._decoder = decoder
        self._adapter = adapter
        self.tamper = tamper

    def snapshot(self):
        reply = self._adapter.handle(
            "execution.account_books.query",
            principal_ref=PRINCIPAL,
            identity=IDENTITY,
            scope=WIRE,
            arguments={},
        )
        reply = msgpack.unpackb(msgpack.packb(reply, use_bin_type=True), raw=False)
        if self.tamper is not None:
            self.tamper(reply["result"]["strategy_account_book"])
        return self._decoder._typed_snapshot(reply)


def _service_view(client):
    view = object.__new__(ServiceStrategyAccountBookView)
    object.__setattr__(view, "_client", client)
    object.__setattr__(view, "strategy_ref", STRATEGY)
    object.__setattr__(view, "account_ref", ACCOUNT)
    object.__setattr__(view, "_owner_thread_id", threading.get_ident())
    object.__setattr__(view, "_frozen", True)
    return view


@pytest.fixture
def service(tmp_path):
    store = SqliteExecutionStore(str(tmp_path / "execution.sqlite3"))
    ledger = SqliteStrategyLedger(
        tmp_path / "ledger.sqlite3",
        account_ref=ACCOUNT,
        instruments={"X": InstrumentTerms(Decimal("1"), "CNY", "spot")},
        budgets={STRATEGY: StrategyBudget(Decimal("1000000000"), "CNY")},
        capital={STRATEGY: StrategyCapital(Decimal("20000"), "CNY")},
    )
    ledger.reserve(LedgerIntent("A-X", STRATEGY, "X", "BUY", Decimal("2"), Decimal("100")))
    ledger.apply_execution("A-X", cumulative_quantity=Decimal("2"), average_price=Decimal("100"))
    stream = StreamedAccountPositions(ACCOUNT, "gateway:account-stream")
    stream.apply_snapshot({("X", "net"): Decimal("2")})
    targets = {WIRE: ExecutionScope("PAPER", "simulation", ACCOUNT, STRATEGY, "20261104")}
    adapter = ExecutionAccountBookReadAdapter(
        store, targets, _HostSource(ledger, stream.report)
    )
    try:
        yield adapter, ledger, stream
    finally:
        ledger.close()
        store.close()


def _strategy(view, datas, *, route=marks.ROUTE):
    broker = scope._AccountBroker()  # account-wide values must never be used
    broker.store = route
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = datas
    cerebro.datasbyname = {data._name: data for data in datas}
    with OwnerContext.set_owner(cerebro):
        strategy = scope._Strategy.__new__(scope._Strategy)
    strategy.datas = datas
    strategy.data = datas[0]
    strategy.account_book = view
    orders = []
    strategy.__dict__["buy"] = lambda **kw: orders.append(("buy", kw["size"])) or "order"
    strategy.__dict__["sell"] = lambda **kw: orders.append(("sell", kw["size"])) or "order"
    return strategy, orders


def test_service_book_is_valued_like_a_direct_book(service):
    adapter, _ledger, _stream = service
    view = _service_view(_WireClient(adapter))
    snapshot = view.snapshot()
    assert snapshot.position_cut_id == snapshot.financial_cut_id
    assert snapshot.reconciliation_state == "BALANCED"
    valuation = value_strategy_book(
        snapshot, marks={"X": Decimal("110")}, multipliers={"X": Decimal("1")}
    )
    assert valuation.cash == Decimal("19800") and valuation.equity == Decimal("20020")


def test_service_target_value_uses_a_fresh_final_bar(service):
    adapter, _ledger, _stream = service
    feed, _clock = marks._feed()
    strategy, orders = _strategy(_service_view(_WireClient(adapter)), [feed])
    strategy.order_target_value(data=feed, target=300.0)  # holds 2 * 100 = 200
    assert orders == [("buy", 1.0)]


def test_service_target_percent_uses_a_fresh_eligible_tick(service):
    adapter, _ledger, _stream = service
    feed, _clock = marks._tick_feed(marks._tick())
    strategy, orders = _strategy(_service_view(_WireClient(adapter)), [feed])
    strategy.order_target_percent(data=feed, target=0.1)
    assert len(orders) == 1 and orders[0][0] == "buy"
    assert orders[0][1] == pytest.approx((0.1 * (19800 + 202) - 202) / 101, abs=1)


def test_service_mode_keeps_the_live_mark_contract(service):
    adapter, _ledger, _stream = service
    view = _service_view(_WireClient(adapter))
    stale, clock = marks._feed()
    clock.wall = marks.T0 + dt.timedelta(hours=1)
    strategy, orders = _strategy(view, [stale])
    with pytest.raises(ValueError, match="STRATEGY_MARK_STALE"):
        strategy.order_target_value(data=stale, target=300.0)
    unbound, _ = marks._feed(store=marks._Store())
    strategy, orders = _strategy(view, [unbound])
    with pytest.raises(ValueError, match="STRATEGY_MARK_ROUTE_UNBOUND"):
        strategy.order_target_value(data=unbound, target=300.0)
    assert orders == []


def test_unreconciled_service_books_are_not_valued(service):
    adapter, ledger, stream = service
    feed, _clock = marks._feed()
    strategy, orders = _strategy(_service_view(_WireClient(adapter)), [feed])
    ledger.reserve(LedgerIntent("A-X2", STRATEGY, "X", "SELL", Decimal("1"), Decimal("100")))
    stream.apply_snapshot({("X", "net"): Decimal("1")})  # IN_FLIGHT: no financials
    with pytest.raises(ValueError, match="STRATEGY_BOOK_RECONCILIATION_IN_FLIGHT"):
        strategy.order_target_value(data=feed, target=300.0)
    stream.mark_interrupted("SEQUENCE_GAP")  # UNVERIFIED: the whole book is refused
    with pytest.raises(ValueError, match="STRATEGY_BOOK_RECONCILIATION_UNVERIFIED"):
        strategy.order_target_value(data=feed, target=300.0)
    assert orders == []


def _set(field, value):
    return lambda part: part["data"].__setitem__(field, value)


@pytest.mark.parametrize(
    "tamper,code",
    [
        (_set("financial_cut_id", "another-transaction"), "STRATEGY_FINANCIAL_CUT_MISMATCH"),
        (_set("position_cut_id", None), "STRATEGY_FINANCIAL_CUT_MISMATCH"),
        (_set("contract_version", 1), "ACCOUNT_BOOK_TYPED_VERSION_UNSUPPORTED"),
    ],
)
def test_mismatched_cuts_and_old_versions_are_refused(service, tamper, code):
    adapter, _ledger, _stream = service
    feed, _clock = marks._feed()
    strategy, orders = _strategy(_service_view(_WireClient(adapter, tamper)), [feed])
    with pytest.raises(ValueError, match=code):
        strategy.order_target_value(data=feed, target=300.0)
    assert orders == []


def test_old_failure_form_version_is_refused(service):
    adapter, _ledger, stream = service
    stream.mark_interrupted("SEQUENCE_GAP")

    def downgrade(part):
        part["schema_version"] = 2

    view = _service_view(_WireClient(adapter, downgrade))
    with pytest.raises(ServiceStrategyAccountBookError, match="TYPED_VERSION_UNSUPPORTED"):
        view.snapshot()
