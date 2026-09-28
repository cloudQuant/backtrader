"""Runonce/runnext parity for managed multi-data fill projection.

The fixture uses real Backtrader Cerebro, BtApiStore, BtApiBroker and
TradeLogger objects.  Its provider and execution journal are local fakes; it
does not open a socket or load a native SDK.  The assertions are a reference
oracle for this fixture's exact fill stream, not inherited master-branch
strategy metrics.
"""

from __future__ import annotations

import collections
import socket
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from typing import Any, Optional

import backtrader as bt
import pandas as pd

from backtrader.stores.btapistore import BtApiStore
from backtrader_runtime.managed_execution import (
    ManagedExecutionBridge,
    ManagedExecutionBindingError,
)


_SYMBOLS = ("fixture/alpha", "fixture/beta")
_METADATA_DIGEST = "a" * 64


class _ExecutionState(Enum):
    ACKED = "ACKED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class _Side(Enum):
    BUY = "BUY"
    SELL = "SELL"


class _PositionEffect(Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    CLOSE_TODAY = "CLOSE_TODAY"
    CLOSE_YESTERDAY = "CLOSE_YESTERDAY"


@dataclass(frozen=True)
class _Intent:
    scope: object
    intent_id: str
    signal_id: str
    instrument: str
    side: _Side
    quantity: Decimal
    price: Decimal
    position_effect: _PositionEffect
    reduce_only: bool
    metadata_version: str
    tags: dict[str, str]


class _OrderIntent:
    @staticmethod
    def limit(**kwargs: Any) -> _Intent:
        return _Intent(**kwargs)


@dataclass(frozen=True)
class _ProviderObservation:
    intent_id: str
    state: _ExecutionState
    provider_order_id: Optional[str] = None
    filled_quantity: Decimal = Decimal("0")
    average_price: Optional[Decimal] = None
    reason_code: Optional[str] = None
    cumulative_commission: Optional[Decimal] = None

    @classmethod
    def accepted(cls, intent_id: str, provider_order_id: str) -> "_ProviderObservation":
        return cls(intent_id, _ExecutionState.ACKED, provider_order_id=provider_order_id)

    @classmethod
    def rejected(cls, intent_id: str, reason: str) -> "_ProviderObservation":
        return cls(intent_id, _ExecutionState.REJECTED, reason_code=reason)


class _Execution:
    Side = _Side
    PositionEffect = _PositionEffect
    OrderIntent = _OrderIntent
    ProviderObservation = _ProviderObservation
    ExecutionState = _ExecutionState


class _FakeManagedRuntime:
    """Minimal scoped event journal accepted by the real managed bridge."""

    def __init__(self, state_directory) -> None:
        self.execution = _Execution
        self.scope = SimpleNamespace(
            key="scope:" + ("b" * 64),
            strategy_id="fixture.managed.multidata",
            environment="offline",
        )
        self.state_directory = state_directory
        self.framework_projection_session_id = "fixture-session-multidata"
        self.journal_generation = "c" * 32
        self._sequence = 0
        self._events: list[SimpleNamespace] = []
        self._observations: dict[str, _ProviderObservation] = {}
        runtime = self

        class _ExecutionStore:
            def assert_writer_lease(self, _scope: object, _lease: object) -> None:
                return None

            def journal_source_identity(self) -> dict[str, object]:
                return {
                    "generation_kind": "EXECUTION_JOURNAL",
                    "generation": runtime.journal_generation,
                    "epoch": 1,
                }

            def read_outbox(self, *, after_sequence=0, limit=100, scope=None):
                if scope is not runtime.scope:
                    raise AssertionError("outbox read must use the exact fake execution scope")
                return tuple(event for event in runtime._events if event.sequence > after_sequence)[
                    :limit
                ]

        class _Facade:
            def acquire_writer_lease(self) -> object:
                return SimpleNamespace(fencing_token=1)

            def record_provider_observation_event(self, observation: _ProviderObservation):
                previous = runtime._observations.get(observation.intent_id)
                if previous == observation:
                    return None
                runtime._sequence += 1
                runtime._observations[observation.intent_id] = observation
                event = SimpleNamespace(
                    sequence=runtime._sequence,
                    event_id="fixture-event-" + str(runtime._sequence),
                    intent_id=observation.intent_id,
                    scope_key=runtime.scope.key,
                    event_type="reconciled_observation",
                    state=observation.state,
                    created_at_ns=1_900_000_000_000_000_000 + runtime._sequence,
                    journal_incarnation_id=runtime.journal_generation,
                    payload={
                        "provider_order_id": observation.provider_order_id,
                        "filled_quantity": format(observation.filled_quantity, "f"),
                        "average_price": (
                            None
                            if observation.average_price is None
                            else format(observation.average_price, "f")
                        ),
                        "cumulative_commission": (
                            None
                            if observation.cumulative_commission is None
                            else format(observation.cumulative_commission, "f")
                        ),
                        "reason_code": observation.reason_code,
                        "source": "reconcile",
                    },
                )
                runtime._events.append(event)
                return event

        self.execution_store = _ExecutionStore()
        self.facade = _Facade()

    def submit(self, intent: _Intent, dispatch):
        observation = dispatch(intent)
        return SimpleNamespace(
            state=observation.state,
            provider_order_id=observation.provider_order_id,
            filled_quantity=observation.filled_quantity,
            average_price=observation.average_price,
            cumulative_commission=observation.cumulative_commission,
            payload_sha256="d" * 64,
        )


class _FakeProvider:
    """No-network BtApiClient-shaped provider with deterministic callbacks."""

    def __init__(self) -> None:
        self.connected = False
        self.submitted_orders: list[dict[str, Any]] = []
        self.broker_updates = collections.deque()
        self._provider_ids: collections.deque[str] = collections.deque(
            ("provider-alpha", "provider-beta")
        )

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def get_balance(self) -> dict[str, float]:
        return {"cash": 100_000.0, "value": 100_000.0}

    def get_positions(self) -> list[dict[str, Any]]:
        return []

    def fetch_open_orders(self) -> list[dict[str, Any]]:
        return []

    def submit_order(self, payload: dict[str, Any]) -> dict[str, str]:
        self.submitted_orders.append(dict(payload))
        return {"status": "accepted", "id": self._provider_ids.popleft()}

    def poll_broker_update(self):
        if self.broker_updates:
            return self.broker_updates.popleft()
        return None

    def push_broker_update(self, update: dict[str, Any]) -> None:
        self.broker_updates.append(dict(update))


def _managed_info(intent_id: str, symbol: str) -> dict[str, Any]:
    return {
        "managed_order_type": "LIMIT",
        "managed_intent_id": intent_id,
        "managed_signal_id": "signal." + intent_id,
        "managed_instrument": symbol,
        "managed_position_effect": "OPEN",
        "managed_metadata_version": "fixture.metadata.v1",
        "managed_instrument_metadata_digest": _METADATA_DIGEST,
        "offset": "open",
        "reduce_only": False,
    }


def _provider_observation(runtime, intent, update):
    state_by_status = {
        "partial": _ExecutionState.PARTIALLY_FILLED,
        "completed": _ExecutionState.FILLED,
    }
    status = update.get("status")
    if status not in state_by_status:
        raise ManagedExecutionBindingError("fixture callback status is unsupported")
    return _ProviderObservation(
        intent_id=intent.intent_id,
        state=state_by_status[status],
        provider_order_id=update.get("id"),
        filled_quantity=Decimal(str(update.get("filled"))),
        average_price=Decimal(str(update.get("avg_price"))),
        cumulative_commission=Decimal(str(update.get("cumulative_commission"))),
    )


def _frame(base_price: float) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    closes = [base_price + offset for offset in range(8)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
            "volume": [10.0] * len(closes),
            "openinterest": [0.0] * len(closes),
        },
        index=dates,
    )


def _push_update(provider, order, symbol, *, status, filled, average, commission):
    provider.push_broker_update(
        {
            "kind": "order",
            "bt_order_ref": order.ref,
            "data_name": symbol,
            "side": "buy",
            "status": status,
            "id": "provider-alpha" if symbol == _SYMBOLS[0] else "provider-beta",
            "filled": str(filled),
            "avg_price": str(average),
            "cumulative_commission": str(commission),
        }
    )


def _run_fixture(runonce: bool, tmp_path) -> dict[str, Any]:
    runtime = _FakeManagedRuntime(tmp_path / ("once" if runonce else "next"))
    provider = _FakeProvider()
    bridge = ManagedExecutionBridge(
        runtime,
        provider_observation_from_update=_provider_observation,
    )
    store = BtApiStore(
        provider="fixture",
        api=provider,
        managed_execution_adapter=bridge,
    )
    broker = store.getbroker(
        validation_enabled=False,
        cash_check_enabled=False,
        account_refresh_interval=3600.0,
        positions_refresh_interval=3600.0,
        open_orders_refresh_interval=3600.0,
    )

    class _ObservedCerebro(bt.Cerebro):
        def __init__(self):
            super().__init__(stdstats=False, runonce=runonce)
            self.engine_calls = {"_runonce": 0, "_runnext": 0}

        def _runonce(self, runstrats):
            self.engine_calls["_runonce"] += 1
            return super()._runonce(runstrats)

        def _runnext(self, runstrats):
            self.engine_calls["_runnext"] += 1
            return super()._runnext(runstrats)

    cerebro = _ObservedCerebro()
    cerebro.setbroker(broker)
    for symbol, base in zip(_SYMBOLS, (100.0, 200.0)):
        cerebro.adddata(bt.feeds.PandasData(dataname=_frame(base)), name=symbol)

    class _Strategy(bt.Strategy):
        def __init__(self):
            self.orders_by_symbol: dict[str, Any] = {}
            self.order_notifications: list[tuple[str, str, float, float]] = []
            self.trade_notifications: list[tuple[str, bool, float, float, float]] = []
            self.secondary_signal: Optional[tuple[str, int, float, float]] = None
            self._partial_sent = False
            self._complete_sent = False
            self._duplicate_sent = False

        def notify_order(self, order):
            self.order_notifications.append(
                (
                    order.data._name,
                    order.getstatusname(),
                    float(order.executed.size),
                    float(order.executed.comm),
                )
            )

        def notify_trade(self, trade):
            self.trade_notifications.append(
                (
                    trade.data._name,
                    bool(trade.isclosed),
                    round(float(trade.size), 10),
                    round(float(trade.price), 10),
                    round(float(trade.commission), 10),
                )
            )

        def next(self):
            # The secondary feed is the actual trigger source.  Keep its
            # observed identity and exact current/previous closes for the
            # output assertions; the primary feed is not used as a signal.
            secondary_signal = (
                len(self.datas[1]) >= 2 and self.datas[1].close[0] > self.datas[1].close[-1]
            )
            if secondary_signal and not self.orders_by_symbol:
                self.secondary_signal = (
                    self.datas[1]._name,
                    len(self.datas[1]),
                    float(self.datas[1].close[0]),
                    float(self.datas[1].close[-1]),
                )
                for symbol, data, limit_price in zip(_SYMBOLS, self.datas, (105.0, 205.0)):
                    intent_id = "multidata." + symbol.rsplit("/", 1)[-1]
                    self.orders_by_symbol[symbol] = self.buy(
                        data=data,
                        size=2,
                        price=limit_price,
                        exectype=bt.Order.Limit,
                        **_managed_info(intent_id, symbol),
                    )
            elif len(self.data1) == 3 and not self._partial_sent:
                _push_update(
                    provider,
                    self.orders_by_symbol[_SYMBOLS[0]],
                    _SYMBOLS[0],
                    status="partial",
                    filled=1,
                    average=100,
                    commission="0.05",
                )
                _push_update(
                    provider,
                    self.orders_by_symbol[_SYMBOLS[1]],
                    _SYMBOLS[1],
                    status="partial",
                    filled=1,
                    average=200,
                    commission="0.10",
                )
                self._partial_sent = True
            elif len(self.data1) == 4 and not self._complete_sent:
                _push_update(
                    provider,
                    self.orders_by_symbol[_SYMBOLS[0]],
                    _SYMBOLS[0],
                    status="completed",
                    filled=2,
                    average=101,
                    commission="0.12",
                )
                _push_update(
                    provider,
                    self.orders_by_symbol[_SYMBOLS[1]],
                    _SYMBOLS[1],
                    status="completed",
                    filled=2,
                    average=201,
                    commission="0.23",
                )
                self._complete_sent = True
            elif len(self.data1) == 5 and not self._duplicate_sent:
                # Exact duplicate terminal callbacks must not create a second
                # outbox event or a second Broker execution bit.
                for symbol, average, commission in (
                    (_SYMBOLS[0], 101, "0.12"),
                    (_SYMBOLS[1], 201, "0.23"),
                ):
                    _push_update(
                        provider,
                        self.orders_by_symbol[symbol],
                        symbol,
                        status="completed",
                        filled=2,
                        average=average,
                        commission=commission,
                    )
                self._duplicate_sent = True

    cerebro.addstrategy(_Strategy)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(tmp_path / ("trade-logger-once" if runonce else "trade-logger-next")),
        log_format="json",
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_position_snapshot=False,
        report_max_records=100,
    )

    try:
        strategy = cerebro.run()[0]
        report = strategy.stats.trade_logger.final_report()
        by_symbol = {}
        for symbol in _SYMBOLS:
            order = strategy.orders_by_symbol[symbol]
            by_symbol[symbol] = {
                "status": order.getstatusname(),
                "size": round(float(order.executed.size), 10),
                "average_price": round(float(order.executed.price), 10),
                "commission": round(float(order.executed.comm), 10),
                "execution_bits": [
                    (
                        round(float(bit.size), 10),
                        round(float(bit.price), 10),
                        round(float(bit.comm), 10),
                    )
                    for bit in order.executed.exbits
                ],
                "position": round(float(broker.positions[symbol].size), 10),
            }
        completed_summaries = sorted(
            (
                item["data_name"],
                item["status"],
                round(float(item["executed_size"]), 10),
                round(float(item["executed_price"]), 10),
                round(float(item["commission"]), 10),
            )
            for item in report["order_summaries"]
            if item.get("status") == "Completed"
        )
        notification_economics_by_symbol = {
            symbol: [
                (status, round(size, 10), round(commission, 10))
                for observed_symbol, status, size, commission in strategy.order_notifications
                if observed_symbol == symbol and status in {"Partial", "Completed"}
            ]
            for symbol in _SYMBOLS
        }
        trade_notifications = sorted(strategy.trade_notifications)
        final_open_trades = []
        for symbol, data in zip(_SYMBOLS, strategy.datas):
            trades = strategy._trades[data][0]
            assert trades, f"the opening fill for {symbol} did not create a trade"
            trade = trades[-1]
            final_open_trades.append(
                (
                    symbol,
                    bool(trade.isclosed),
                    round(float(trade.size), 10),
                    round(float(trade.price), 10),
                    round(float(trade.commission), 10),
                )
            )
        assert cerebro.engine_calls == (
            {"_runonce": 1, "_runnext": 0} if runonce else {"_runonce": 0, "_runnext": 1}
        )
        assert len(provider.submitted_orders) == 2
        assert runtime._sequence == 4
        return {
            "orders": by_symbol,
            "trade_logger_completed": completed_summaries,
            "notifications": notification_economics_by_symbol,
            "trade_notifications": trade_notifications,
            "final_open_trades": sorted(final_open_trades),
            "secondary_signal": strategy.secondary_signal,
            "event_count": runtime._sequence,
            "account_cash": round(float(broker.getcash()), 10),
            "account_value": round(float(broker.getvalue()), 10),
            "engine_calls": dict(cerebro.engine_calls),
        }
    finally:
        broker.stop()
        bridge.close()


def test_managed_multidata_partial_fee_projection_matches_runonce_and_runnext(
    tmp_path, monkeypatch
) -> None:
    """Both engines consume the same exact two-feed cumulative fill stream."""

    network_attempts = []

    class _DeniedSocket(socket.socket):
        def connect(self, *args, **kwargs):
            network_attempts.append((args, kwargs))
            raise AssertionError("managed parity fixture must remain offline")

        def connect_ex(self, *args, **kwargs):
            network_attempts.append((args, kwargs))
            raise AssertionError("managed parity fixture must remain offline")

    monkeypatch.setattr(socket, "socket", _DeniedSocket)
    runonce_result = _run_fixture(True, tmp_path)
    runnext_result = _run_fixture(False, tmp_path)

    # Exact-input fixture oracle. The bridge's exact Fraction delta preparation
    # yields incremental prices (2*101 - 1*100) == 102 and
    # (2*201 - 1*200) == 202; fees are cumulative totals reconciled to deltas.
    expected = {
        "orders": {
            _SYMBOLS[0]: {
                "status": "Completed",
                "size": 2.0,
                "average_price": 101.0,
                "commission": 0.12,
                "execution_bits": [(1.0, 100.0, 0.05), (1.0, 102.0, 0.07)],
                "position": 2.0,
            },
            _SYMBOLS[1]: {
                "status": "Completed",
                "size": 2.0,
                "average_price": 201.0,
                "commission": 0.23,
                "execution_bits": [(1.0, 200.0, 0.1), (1.0, 202.0, 0.13)],
                "position": 2.0,
            },
        },
        "trade_logger_completed": sorted(
            [
                (_SYMBOLS[0], "Completed", 2.0, 101.0, 0.12),
                (_SYMBOLS[1], "Completed", 2.0, 201.0, 0.23),
            ]
        ),
        "notifications": {
            _SYMBOLS[0]: [("Partial", 1.0, 0.05), ("Completed", 2.0, 0.12)],
            _SYMBOLS[1]: [("Partial", 1.0, 0.10), ("Completed", 2.0, 0.23)],
        },
        "trade_notifications": sorted(
            [
                (_SYMBOLS[0], False, 1.0, 100.0, 0.05),
                (_SYMBOLS[1], False, 1.0, 200.0, 0.10),
            ]
        ),
        "final_open_trades": sorted(
            [
                (_SYMBOLS[0], False, 2.0, 101.0, 0.12),
                (_SYMBOLS[1], False, 2.0, 201.0, 0.23),
            ]
        ),
        "secondary_signal": (_SYMBOLS[1], 2, 201.0, 200.0),
        "event_count": 4,
        "account_cash": 100_000.0,
        "account_value": 100_000.0,
    }
    assert {
        key: value for key, value in runonce_result.items() if key != "engine_calls"
    } == expected
    assert {
        key: value for key, value in runnext_result.items() if key != "engine_calls"
    } == expected
    assert runonce_result["engine_calls"] == {"_runonce": 1, "_runnext": 0}
    assert runnext_result["engine_calls"] == {"_runonce": 0, "_runnext": 1}
    assert runonce_result["account_cash"] == runnext_result["account_cash"] == 100_000.0
    assert runonce_result["account_value"] == runnext_result["account_value"] == 100_000.0
    assert runonce_result == {
        **runnext_result,
        "engine_calls": {"_runonce": 1, "_runnext": 0},
    }
    assert network_attempts == []
