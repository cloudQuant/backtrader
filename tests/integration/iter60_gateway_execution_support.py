"""Shared fixtures for the iteration 60 R2-C Gateway execution-event tests.

Local only: a temp SQLite Gateway account journal written by the real Gateway
``GatewayExecutionEventPublisher`` (the account owner's producer), the real
``GatewayReadService`` called in-process (co-located service, no network),
the SDK ``ServiceExecutionEventConsumer`` and a real ``BtApiBroker`` with the
SDK strategy ledger and the standard notification journal.
"""

from __future__ import annotations

import datetime as dt
import itertools
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import backtrader as bt
from backtrader.brokers.btapibroker import BtApiBroker
from backtrader.metabase import OwnerContext

INSTRUMENT = "PAPER:SIM:SA2701"
ACCOUNT = "account-gateway"
ACCOUNT_SCOPE = "journal:account-gateway"
STATE_SCOPE = "journal:account-gateway-facts"
DOMAIN = "paper:account-gateway"
EXEC = {"strategy-a": "exec:strategy-a", "strategy-b": "exec:strategy-b"}
PREFIX = {"strategy-a": "sa-", "strategy-b": "sb-"}


def _key():
    from bt_api_base.account_protocol import AccountKey

    return AccountKey("paper", "sim", "paper", "acct-1")


def _instrument():
    from bt_api_base.market_protocol import MarketInstrumentKey

    return MarketInstrumentKey("paper", "sim", "paper", "futures", "SA2701", "SA2701")


def order_obs(order_id, client, status, filled, quantity, side="sell", price="1500"):
    from bt_api_base.account_protocol import AccountResourceKey
    from bt_api_base.execution_query_protocol import ExecutionOrderRecord
    from bt_api_base.execution_row_observation_protocol import AccountExecutionOrderObservation

    return AccountExecutionOrderObservation(
        _key(),
        ExecutionOrderRecord(
            AccountResourceKey("futures", "cross"),
            _instrument(),
            order_id,
            client,
            "verified",
            side,
            "unavailable",
            None,
            "unavailable",
            "limit",
            status,
            quantity,
            filled,
            "contracts",
            price,
            None,
            "unavailable",
            None,
            "unavailable",
            "2027-01-15T08:00:00Z",
        ),
    )


def trade_obs(trade_id, order_id, quantity, price="1500", side="sell"):
    from bt_api_base.account_protocol import AccountResourceKey
    from bt_api_base.execution_query_protocol import ExecutionTradeRecord
    from bt_api_base.execution_row_observation_protocol import AccountExecutionTradeObservation

    return AccountExecutionTradeObservation(
        _key(),
        ExecutionTradeRecord(
            AccountResourceKey("futures", "cross"),
            _instrument(),
            trade_id,
            order_id,
            "provider_order_identity",
            side,
            "unavailable",
            None,
            "unavailable",
            quantity,
            "contracts",
            price,
            None,
            "unavailable",
            None,
            "unavailable",
            "2027-01-15T08:00:01Z",
        ),
    )


# -- provider event script (neutral facts) ------------------------------------------

#: One SELL 2 @1500 of strategy A (client "sa-1", provider order "o-1"): two
#: fills, the second one reported *before* the partial order observation.
SCRIPT = (
    ("order", "o-1", "sa-1", "open", "0", "2"),
    ("trade", "t-1", "o-1", "1", "1500"),
    ("order", "o-1", "sa-1", "partially_filled", "1", "2"),
    ("trade", "t-2", "o-1", "1", "1510"),
    ("order", "o-1", "sa-1", "filled", "2", "2"),
)


def observations(script=SCRIPT):
    result = []
    for step in script:
        if step[0] == "order":
            result.append(order_obs(*step[1:]))
        else:
            result.append(trade_obs(*step[1:]))
    return result


def direct_rows(order, script=SCRIPT):
    """What a direct-mode SDK Store emits for ``script`` (written independently)."""

    terminal = {"filled": ("completed", True)}
    status_map = {"open": ("accepted", False), "partially_filled": ("partial", False)}
    rows = []
    for step in script:
        if step[0] == "order":
            _kind, order_id, client, status, filled, quantity = step
            canonical, confirmed = terminal.get(status) or status_map[status]
            rows.append(
                {
                    "kind": "order",
                    "local_ref": order.ref,
                    "client_order_id": client,
                    "external_order_id": order_id,
                    "order_id": order_id,
                    "status": canonical,
                    "terminal_confirmed": confirmed,
                    "execution_unknown": False,
                    "execution_source": "trades",
                    "filled_quantity": filled,
                    "quantity": quantity,
                    "side": "sell",
                    "quantity_unit": "contracts",
                    "data_name": INSTRUMENT,
                }
            )
        else:
            _kind, trade_id, order_id, quantity, price = step
            rows.append(
                {
                    "kind": "trade",
                    "local_ref": order.ref,
                    "trade_id": trade_id,
                    "external_order_id": order_id,
                    "order_id": order_id,
                    "side": "sell",
                    "quantity": quantity,
                    "price": price,
                    "quantity_unit": "contracts",
                    "data_name": INSTRUMENT,
                }
            )
    return rows


# -- Gateway side --------------------------------------------------------------------


def publish(journal_path, items):
    from bt_api_gateway import GatewayEventJournal
    from bt_api_gateway.execution_event_publisher import (
        GatewayExecutionEventPublisher,
        GatewayExecutionScopePolicy,
    )

    return GatewayExecutionEventPublisher(
        GatewayEventJournal(journal_path),
        account_key=_key(),
        journal_account_scope=ACCOUNT_SCOPE,
        policy=GatewayExecutionScopePolicy(
            {PREFIX[ref]: EXEC[ref] for ref in EXEC}, unattributed_scope="exec:unattributed"
        ),
    ).publish(items)


def local_call(journal_path, strategy_ref):
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_gateway import GatewayCommandKind, GatewayEventJournal, GatewayPrincipal
    from bt_api_gateway.service_component import GatewayReadService, GatewayServiceAccountScope

    service = GatewayReadService(
        GatewayEventJournal(journal_path),
        accounts={
            ACCOUNT: GatewayServiceAccountScope(
                account_ref=ACCOUNT,
                execution_domain_ref=DOMAIN,
                journal_account_scope=ACCOUNT_SCOPE,
                account_read_strategy_scope=STATE_SCOPE,
                execution_scope_map=dict(EXEC),
            )
        },
        principals={
            "bt-client": GatewayPrincipal(
                "bt-client",
                frozenset({ACCOUNT_SCOPE}),
                frozenset({*EXEC.values(), STATE_SCOPE}),
                frozenset({GatewayCommandKind.READ}),
            )
        },
    )

    def call(operation, arguments):
        return service.handle(
            operation,
            principal_ref="bt-client",
            scope=WireScope(DOMAIN, account_ref=ACCOUNT, strategy_ref=strategy_ref),
            arguments=arguments,
            identity=WireIdentity(WireRole.STRATEGY_CLIENT, "bt-client", strategy_ref),
        )

    return call


def consumer(journal_path, directory, strategy_ref):
    from bt_api_py.service_execution_event_consumer import ServiceExecutionEventConsumer

    Path(directory).mkdir(parents=True, exist_ok=True)
    return ServiceExecutionEventConsumer.over_call(
        local_call(journal_path, strategy_ref),
        binding_ref=f"co-located-gateway:{strategy_ref}",
        path=Path(directory) / f"{strategy_ref}.cursor.sqlite3",
        account_key=_key(),
        expected_account_scope=ACCOUNT_SCOPE,
        expected_strategy_scope=EXEC[strategy_ref],
    )


# -- Backtrader side -----------------------------------------------------------------


class SdkStore:
    """SDK-mode Store without provider dispatch; ``rows`` feed the direct drain."""

    _sdk_mode = True

    def __init__(self):
        self.rows = []

    def poll_broker_update(self):
        return self.rows.pop(0) if self.rows else None


class IdentifiedStrategy(bt.Strategy):
    params = (("strategy_ref", None), ("account_ref", None))


def ledger(path):
    from bt_api_py.strategy_ledger import InstrumentTerms, LedgerIntent, SqliteStrategyLedger
    from bt_api_py.strategy_ledger import StrategyBudget

    existed = Path(path).exists()
    book = SqliteStrategyLedger(
        path,
        account_ref=ACCOUNT,
        instruments={INSTRUMENT: InstrumentTerms(Decimal("10"), "CNY", "futures")},
        budgets={ref: StrategyBudget(Decimal("1000000000"), "CNY") for ref in EXEC},
    )
    if not existed:
        for ref, quantity in (("strategy-a", "2"), ("strategy-b", "3")):
            intent_id = f"seed-{ref}"
            book.reserve(
                LedgerIntent(intent_id, ref, INSTRUMENT, "BUY", Decimal(quantity), Decimal("1500"))
            )
            book.apply_execution(
                intent_id, cumulative_quantity=Decimal(quantity), average_price=1500
            )
    return book


def data():
    frame = pd.DataFrame(
        {"open": [1500.0], "high": [1501.0], "low": [1499.0], "close": [1500.0], "volume": [1.0]},
        index=pd.to_datetime(["2027-01-15 08:00"]),
    )
    feed = bt.feeds.PandasData(dataname=frame, name=INSTRUMENT)
    feed._start()
    assert feed.load()
    return feed


def strategies(broker, feed, *refs):
    cerebro = bt.Cerebro()
    cerebro.setbroker(broker)
    cerebro.stcount = itertools.count()
    cerebro.datas = [feed]
    cerebro.datasbyname = {INSTRUMENT: feed}
    result = []
    with OwnerContext.set_owner(cerebro):
        for ref in refs:
            strategy = IdentifiedStrategy.__new__(
                IdentifiedStrategy, strategy_ref=ref, account_ref=ACCOUNT
            )
            strategy.datas = [feed]
            strategy.data = feed
            result.append(strategy)
    return result


def recording(strategy, sink):
    """Record every delivery as (kind, status, notification_id, replayed)."""

    def notify_order(order):
        sink.append(("order", order.getstatusname(), order.notification_id, order.replayed))

    def notify_trade(trade):
        sink.append(("trade", trade.status, trade.notification_id, trade.replayed))

    strategy.notify_order = notify_order
    strategy.notify_trade = notify_trade


def stack(directory, mode, *, received=None, deployment="dep", acknowledge="after_apply"):
    """A ledger-bound BtApiBroker with notification recovery, in ``direct``/``gateway`` mode."""

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    book = ledger(directory / "ledger.sqlite3")
    store = SdkStore()
    broker = BtApiBroker(store=store)
    feed = data()
    (a,) = strategies(broker, feed, "strategy-a")
    received = [] if received is None else received
    recording(a, received)
    broker.bind_direct_strategy_ledger(a, book, unreconciled=True)
    replayed = broker.bind_strategy_notification_recovery(
        a, directory / "recovery", deployment_ref=deployment
    )
    rebuilt = None
    if mode == "gateway":
        rebuilt = broker.bind_gateway_execution_events(
            a,
            consumer(directory / "gateway.sqlite3", directory / "sdk", "strategy-a"),
            directory / "projection",
            data_names={"SA2701": INSTRUMENT},
            acknowledge=acknowledge,
        )
    return SimpleNamespace(
        ledger=book,
        broker=broker,
        store=store,
        data=feed,
        a=a,
        received=received,
        replayed=replayed,
        rebuilt=rebuilt,
        directory=directory,
    )


def place(s, size=2, price=1500.0, client="sa-1"):
    """Reserve a SELL in the ledger and report it Accepted, as a submit reply would."""

    from bt_api_py.strategy_ledger import LedgerIntent

    order = bt.SellOrder(
        owner=s.a, data=s.data, size=size, price=price, exectype=bt.Order.Limit, simulated=False
    )
    intent_id = f"intent-{client}"
    s.ledger.reserve(
        LedgerIntent(
            intent_id, "strategy-a", INSTRUMENT, "SELL", Decimal(size), Decimal(str(price))
        )
    )
    order.addinfo(
        strategy_ledger_intent_id=intent_id, client_order_id=client, quantity_unit="contracts"
    )
    order.addcomminfo(s.broker.getcommissioninfo(s.data))
    order.submit(s.broker)
    s.broker.orders[order.ref] = order
    order.accept(s.broker)
    s.broker.notify(order)
    return order


def cycle(s):
    """What Cerebro does each step: hand queued notifications to their owners."""

    while True:
        notification = s.broker.get_notification()
        if notification is None:
            break
        notification.owner._addnotification(notification, quicknotify=False)
    s.a._notify()
    s.a._orderspending = []  # as each Cerebro step does
    s.a._tradespending = []


def position(s):
    return s.ledger.positions("strategy-a").get(INSTRUMENT, Decimal("0"))


def shapes(received):
    return [(kind, status) for kind, status, _id, _replayed in received]


def ensure_path():
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


_ = dt  # keep the datetime import for spawned children's pickling of helpers
