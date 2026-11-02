"""Focused runtime-event integration tests for TradeLogger."""

from __future__ import annotations

import datetime as dt
import json

import backtrader as bt
import pytest

from backtrader.brokers.tickbroker import TickBroker
from backtrader.channel import DataChannel, StreamingEventQueue
from backtrader.events import BarEvent, TickEvent

from tests.fixtures.fake_btapi import (
    DEFAULT_SYMBOL,
    FakeBtApiClient,
    make_bar,
    make_store,
    make_tick,
)


def _read_json_lines(path):
    """Read JSON lines from a file and return a list of parsed objects."""
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class MemoryChannel(DataChannel):
    """In-memory data channel for testing."""

    def __init__(self, channel_type, symbol, events):
        """Initialize the memory channel.

        Args:
            channel_type: Type of the channel.
            symbol: Symbol for the channel.
            events: Iterable of events to yield.
        """
        super().__init__(symbol=symbol, validate=False, auto_fix=False)
        self.channel_type = channel_type
        self._events = list(events)

    def load(self):
        """Yield events from the internal list."""
        for event in self._events:
            yield event


class _ScalarLine:
    """Minimal line-like object for testing."""

    def __init__(self, value=0.0):
        """Initialize with a scalar value.

        Args:
            value: Scalar value to return for all indices.
        """
        self.value = value

    def __getitem__(self, index):
        """Return the scalar value."""
        return self.value

    def __setitem__(self, index, value):
        """Set the scalar value."""
        self.value = value

    def datetime(self, index=0):
        """Convert value to datetime using backtrader's num2date."""
        return bt.num2date(self.value)

    def date(self, index=0):
        """Return date portion of datetime."""
        return self.datetime(index).date()


class _PlaceholderParams:
    """Placeholder params object with a default sessionend time."""

    def __init__(self):
        """Initialize with default session end time."""
        self.sessionend = dt.time(23, 59, 59, 999990)


class ChannelPlaceholderData:
    """Minimal data feed placeholder for testing."""

    def __init__(self, symbol):
        """Initialize with the given symbol.

        Args:
            symbol: The symbol name.
        """
        self._name = symbol
        self.symbol = symbol
        self._compensate = None
        self._len = 0
        self.p = _PlaceholderParams()
        self.datetime = _ScalarLine(0.0)
        self.close = _ScalarLine(0.0)

    def __len__(self):
        """Return the current length."""
        return int(self._len)

    def __bool__(self):
        """Always return True."""
        return True

    @staticmethod
    def date2num(value):
        """Convert date to backtrader numeric format."""
        return bt.date2num(value)

    @staticmethod
    def num2date(value):
        """Convert backtrader numeric format to date."""
        return bt.num2date(value)














@pytest.mark.integration
def test_trade_logger_records_channel_mode_runtime_logs_without_datas(tmp_path):
    """Channel-mode strategies without datas should still start TradeLogger and emit files."""
    symbol = "rb2610"
    tick_channel = MemoryChannel(
        "tick",
        symbol,
        [
            TickEvent(timestamp=1.0, symbol=symbol, price=100.0, volume=1.0),
            TickEvent(timestamp=2.0, symbol=symbol, price=101.0, volume=1.0),
            TickEvent(timestamp=3.0, symbol=symbol, price=99.0, volume=1.0),
            TickEvent(timestamp=4.0, symbol=symbol, price=98.0, volume=1.0),
        ],
    )
    queue = StreamingEventQueue(channels=[tick_channel], preload_window=1.0, adaptive=False)

    class ChannelTradeLoggerStrategy(bt.Strategy):
        """Strategy for testing channel mode TradeLogger logging."""

        params = (("symbol", symbol),)

        def __init__(self):
            """Initialize the strategy."""
            self.pending_order = None
            self.completed_orders = 0
            self._last_order_status = {}
            self.placeholder_data = {self.p.symbol: ChannelPlaceholderData(self.p.symbol)}

        @property
        def data_obj(self):
            """Return placeholder data for the symbol."""
            return self.placeholder_data[self.p.symbol]

        def notify_tick(self, tick):
            """Handle tick events: submit orders based on position."""
            if tick.symbol != self.p.symbol or self.pending_order is not None:
                return

            position = self.broker.getposition(self.data_obj).size
            if self.completed_orders == 0 and position <= 0:
                self.pending_order = self.buy(data=self.data_obj, size=1, exectype=bt.Order.Market)
            elif self.completed_orders == 1 and position > 0:
                self.pending_order = self.sell(data=self.data_obj, size=1, exectype=bt.Order.Market)

        def notify_order(self, order):
            """Track order status changes and count completions."""
            previous_status = self._last_order_status.get(order.ref)
            if previous_status == order.status:
                return
            self._last_order_status[order.ref] = order.status

            if order.status in (order.Submitted, order.Accepted):
                self.pending_order = order
                return

            if not order.alive():
                self.pending_order = None

            if order.status == order.Completed:
                self.completed_orders += 1

    cerebro = bt.Cerebro()
    broker = TickBroker(cash=10000.0)
    broker.setcommission(commission=0.0, name=symbol)
    cerebro.setbroker(broker)
    cerebro.addstrategy(ChannelTradeLoggerStrategy, symbol=symbol)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run(channel=queue)

    assert len(results) == 1
    assert results[0].datas == []

    system_entries = _read_json_lines(tmp_path / "system.log")
    tick_entries = _read_json_lines(tmp_path / "tick.log")
    order_entries = _read_json_lines(tmp_path / "order.log")
    trade_entries = _read_json_lines(tmp_path / "trade.log")
    value_entries = _read_json_lines(tmp_path / "value.log")
    position_entries = _read_json_lines(tmp_path / "position.log")

    system_events = [entry["event_type"] for entry in system_entries]

    assert "session_started" in system_events
    assert "session_stopped" in system_events
    assert [entry["price"] for entry in tick_entries] == [100.0, 101.0, 99.0, 98.0]
    assert any(
        entry["status"] == "Completed" and entry["data_name"] == symbol for entry in order_entries
    )
    assert any(
        entry["isclosed"] is True and entry["data_name"] == symbol for entry in trade_entries
    )
    assert len(value_entries) == 4
    assert any(entry["data_name"] == symbol for entry in position_entries)


@pytest.mark.integration
def test_trade_logger_generic_report_marks_channel_refs_and_counts_real_bars(tmp_path):
    """Channel-only reports retain positions and do not classify ticks as bars."""
    symbol = "BTC/USDT"

    class LegacyMarkForbiddenTickBroker(TickBroker):
        """Fail if the report regresses to an unspecified live mark hook."""

        def get_mark_price(self, data):
            raise AssertionError("generic report must call get_cached_mark_price only")

    tick_channel = MemoryChannel(
        "tick",
        symbol,
        [
            TickEvent(timestamp=1.0, symbol=symbol, price=100.0, volume=1.0),
            TickEvent(timestamp=2.0, symbol=symbol, price=100.0, volume=1.0),
            TickEvent(timestamp=3.0, symbol=symbol, price=120.0, volume=1.0),
        ],
    )
    bar_channel = MemoryChannel(
        "bar",
        symbol,
        [
            BarEvent(
                timestamp=4.0,
                symbol=symbol,
                open=120.0,
                high=120.0,
                low=120.0,
                close=120.0,
                volume=1.0,
            )
        ],
    )
    queue = StreamingEventQueue(
        channels=[tick_channel, bar_channel], preload_window=1.0, adaptive=False
    )

    class ChannelReferenceStrategy(bt.Strategy):
        """Submit through Cerebro's channel reference without a placeholder feed."""

        def __init__(self):
            self.submitted = False

        def start(self):
            self.trade_logger = self.stats.trade_logger

        def notify_tick(self, tick):
            if self.submitted:
                return
            self.submitted = True
            self.buy(data=self.get_hft_data(tick.symbol), size=1, exectype=bt.Order.Market)

    cerebro = bt.Cerebro(stdstats=False)
    broker = LegacyMarkForbiddenTickBroker(cash=1_000.0)
    broker.setcommission(commission=0.0, name=symbol)
    cerebro.setbroker(broker)
    cerebro.addstrategy(ChannelReferenceStrategy)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        obsname="trade_logger",
        log_dir=str(tmp_path),
        log_orders=False,
        log_trades=False,
        log_positions=False,
        log_indicators=False,
        log_signals=False,
        log_ticks=False,
        log_bars=False,
        log_system=False,
        log_monitoring=False,
        log_errors=False,
        log_value=False,
        log_position_snapshot=False,
    )

    strategy = cerebro.run(channel=queue)[0]
    report = strategy.stats.trade_logger.final_report()

    assert strategy.datas == []
    assert set(strategy._hft_data_refs) == {symbol}
    assert report is not None
    assert report["finalized"] is True
    assert report["event_counts"]["ticks"] == 3
    assert report["event_counts"]["bars"] == 1
    assert report["positions"][symbol]["size"] == 1
    assert report["positions"][symbol]["current_price"] == pytest.approx(120.0)
    assert report["positions"][symbol]["value"] == pytest.approx(120.0)
    assert report["portfolio"]["cash"] == pytest.approx(900.0)
    assert report["portfolio"]["value"] == pytest.approx(1_020.0)
    assert report["portfolio"]["cash"] + report["positions"][symbol]["value"] == pytest.approx(
        report["portfolio"]["value"]
    )


@pytest.mark.integration
def test_channel_placeholder_datetime_supports_market_order_construction():
    """Channel placeholder data should expose datetime() for order initialization."""
    data = ChannelPlaceholderData("rb2610")
    sample_dt = dt.datetime(2024, 1, 1, 9, 0, 0)
    data.datetime[0] = bt.date2num(sample_dt)

    order = bt.BuyOrder(
        owner=None,
        data=data,
        size=1,
        exectype=bt.Order.Market,
    )

    assert order is not None
    assert order.data is data
    assert order.created.dt == bt.date2num(sample_dt)
