"""Focused runtime-event integration tests for TradeLogger."""

from __future__ import annotations

import datetime as dt
import json

import backtrader as bt
import pytest

from backtrader.brokers.tickbroker import TickBroker
from backtrader.channel import DataChannel, StreamingEventQueue
from backtrader.events import TickEvent

from tests.fixtures.fake_btapi import DEFAULT_SYMBOL, FakeBtApiClient, make_bar, make_store, make_tick


def _read_json_lines(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class MemoryChannel(DataChannel):
    def __init__(self, channel_type, symbol, events):
        super().__init__(symbol=symbol, validate=False, auto_fix=False)
        self.channel_type = channel_type
        self._events = list(events)

    def load(self):
        for event in self._events:
            yield event


class _ScalarLine:
    def __init__(self, value=0.0):
        self.value = value

    def __getitem__(self, index):
        return self.value

    def __setitem__(self, index, value):
        self.value = value

    def datetime(self, index=0):
        return bt.num2date(self.value)

    def date(self, index=0):
        return self.datetime(index).date()


class _PlaceholderParams:
    def __init__(self):
        self.sessionend = dt.time(23, 59, 59, 999990)


class ChannelPlaceholderData:
    def __init__(self, symbol):
        self._name = symbol
        self.symbol = symbol
        self._compensate = None
        self._len = 0
        self.p = _PlaceholderParams()
        self.datetime = _ScalarLine(0.0)
        self.close = _ScalarLine(0.0)

    def __len__(self):
        return int(self._len)

    def __bool__(self):
        return True

    @staticmethod
    def date2num(value):
        return bt.date2num(value)

    @staticmethod
    def num2date(value):
        return bt.num2date(value)


@pytest.mark.integration
def test_trade_logger_records_store_and_data_runtime_events(tmp_path):
    """TradeLogger should persist structured store/data runtime events."""
    client = FakeBtApiClient(
        live_ticks={
            DEFAULT_SYMBOL: [
                make_tick(0, 100.0, volume=1.0),
                make_tick(6, 101.0, volume=1.0),
                make_tick(12, 102.0, volume=1.0),
            ]
        }
    )
    store = make_store(api=client)
    data = store.getdata(
        dataname=DEFAULT_SYMBOL,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
        backfill_start=False,
    )
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class RuntimeStrategy(bt.Strategy):
        def __init__(self):
            self._routed = False

        def next(self):
            if not self._routed:
                self._routed = True
                order = self.buy(data=self.datas[0], size=1, price=101.0, exectype=bt.Order.Limit)
                self.cancel(order)
                return
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(RuntimeStrategy)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run()

    assert len(results) == 1

    system_entries = _read_json_lines(tmp_path / "system.log")
    monitor_entries = _read_json_lines(tmp_path / "monitor.log")

    system_events = [entry["event_type"] for entry in system_entries]
    monitor_events = [entry["event_type"] for entry in monitor_entries]

    assert "session_started" in system_events
    assert "store_connecting" in system_events
    assert "store_connected" in system_events
    assert "store_ready" in system_events
    assert "market_data_subscribe_request" in system_events
    assert "data_status" in system_events
    assert "session_stopped" in system_events

    assert any(entry["status"] == "LIVE" for entry in system_entries if entry["event_type"] == "data_status")
    assert "order_submit_request" in monitor_events
    assert "order_submit_accepted" in monitor_events
    assert "order_cancel_request" in monitor_events
    assert "order_cancel_submitted" in monitor_events
    assert "monitoring_summary" in monitor_events


@pytest.mark.integration
def test_trade_logger_records_local_rejects_in_error_log(tmp_path):
    """Local broker rejections should be persisted to error.log."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
                make_bar(2, 101.0, 102.5, 100.5, 101.5),
            ]
        }
    )
    store = make_store(
        api=client,
        contract_metadata={DEFAULT_SYMBOL: {"min_price_tick": 0.5}},
    )
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class RejectingStrategy(bt.Strategy):
        def __init__(self):
            self._sent = False

        def next(self):
            if not self._sent:
                self._sent = True
                self.buy(data=self.datas[0], size=1, price=100.3, exectype=bt.Order.Limit)
                return
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(RejectingStrategy)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run()

    assert len(results) == 1

    error_entries = _read_json_lines(tmp_path / "error.log")
    error_events = [entry["event_type"] for entry in error_entries]

    assert "order_reject_local" in error_events
    assert "order_rejected" in error_events
    assert any(entry["error_code"] == "invalid_price_tick" for entry in error_entries)


@pytest.mark.integration
def test_trade_logger_records_monitor_thresholds_and_duplicates(tmp_path):
    """Threshold warnings and duplicate detection should be persisted to monitor.log."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
                make_bar(2, 101.0, 102.5, 100.5, 101.5),
                make_bar(3, 101.5, 103.0, 101.0, 102.0),
            ]
        }
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class MonitoringStrategy(bt.Strategy):
        def __init__(self):
            self.bar_count = 0
            self.orders = []

        def next(self):
            self.bar_count += 1
            if self.bar_count == 1:
                self.orders.append(
                    self.buy(data=self.datas[0], size=1, price=101.0, exectype=bt.Order.Limit)
                )
                return

            if self.bar_count == 2:
                self.orders.append(
                    self.buy(data=self.datas[0], size=1, price=101.0, exectype=bt.Order.Limit)
                )
                self.cancel(self.orders[0])
                return

            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(MonitoringStrategy)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir=str(tmp_path),
        log_format="json",
        submit_count_warn_threshold=2,
        cancel_count_warn_threshold=1,
        submit_cancel_total_warn_threshold=3,
        duplicate_order_warn_threshold=1,
        duplicate_order_window_seconds=60.0,
    )

    results = cerebro.run()

    assert len(results) == 1

    monitor_entries = _read_json_lines(tmp_path / "monitor.log")
    monitor_events = [entry["event_type"] for entry in monitor_entries]

    assert "duplicate_order_detected" in monitor_events
    assert "submit_count_threshold_reached" in monitor_events
    assert "cancel_count_threshold_reached" in monitor_events
    assert "submit_cancel_total_threshold_reached" in monitor_events
    assert "duplicate_order_threshold_reached" in monitor_events


@pytest.mark.integration
def test_trade_logger_records_batch_cancel_runtime_events(tmp_path):
    """Batch-cancel runtime events should be persisted into monitor.log."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
                make_bar(2, 101.0, 102.5, 100.5, 101.5),
            ]
        }
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class BatchCancelStrategy(bt.Strategy):
        def __init__(self):
            self.orders = []
            self.bar_count = 0

        def next(self):
            self.bar_count += 1
            if self.bar_count == 1:
                self.orders.append(
                    self.buy(data=self.datas[0], size=1, price=101.0, exectype=bt.Order.Limit)
                )
                self.orders.append(
                    self.sell(data=self.datas[0], size=1, price=99.0, exectype=bt.Order.Limit)
                )
                return

            if self.bar_count == 2:
                self.broker.batch_cancel(self.orders)
                return

            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(BatchCancelStrategy)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run()

    assert len(results) == 1

    monitor_entries = _read_json_lines(tmp_path / "monitor.log")
    monitor_events = [entry["event_type"] for entry in monitor_entries]

    assert "batch_cancel_requested" in monitor_events
    assert "batch_cancel_completed" in monitor_events
    assert monitor_events.count("order_cancel_request") == 2


@pytest.mark.integration
def test_trade_logger_records_batch_cancel_failures_in_error_log(tmp_path):
    """Batch-cancel failures should be persisted into error.log."""

    class FailingCancelClient(FakeBtApiClient):
        def cancel_order(self, order_ref, dataname=None):
            if order_ref == "btapi-2":
                raise RuntimeError("remote cancel rejected")
            return super().cancel_order(order_ref, dataname=dataname)

    client = FailingCancelClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
                make_bar(2, 101.0, 102.5, 100.5, 101.5),
            ]
        }
    )
    store = make_store(api=client)
    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class BatchCancelFailureStrategy(bt.Strategy):
        def __init__(self):
            self.orders = []
            self.bar_count = 0

        def next(self):
            self.bar_count += 1
            if self.bar_count == 1:
                self.orders.append(
                    self.buy(data=self.datas[0], size=1, price=101.0, exectype=bt.Order.Limit)
                )
                self.orders.append(
                    self.sell(data=self.datas[0], size=1, price=99.0, exectype=bt.Order.Limit)
                )
                return

            if self.bar_count == 2:
                self.broker.batch_cancel(self.orders)
                return

            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(BatchCancelFailureStrategy)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run()

    assert len(results) == 1

    error_entries = _read_json_lines(tmp_path / "error.log")
    error_events = [entry["event_type"] for entry in error_entries]

    assert "order_cancel_reject_remote" in error_events
    assert "batch_cancel_failed" in error_events
    assert any(entry["status"] == "partial" for entry in error_entries if entry["event_type"] == "batch_cancel_failed")


@pytest.mark.integration
def test_trade_logger_records_reconnect_success_in_system_log(tmp_path):
    """Reconnect-success runtime events should be persisted into system.log."""
    client = FakeBtApiClient(
        history={
            DEFAULT_SYMBOL: [
                make_bar(0, 100.0, 101.0, 99.0, 100.5),
                make_bar(1, 100.5, 102.0, 100.0, 101.0),
            ]
        }
    )
    store = make_store(api=client)
    store.start()
    store.stop()

    data = store.getdata(dataname=DEFAULT_SYMBOL)
    broker = store.getbroker()
    cerebro = bt.Cerebro()

    class ReconnectStrategy(bt.Strategy):
        def next(self):
            self.cerebro.runstop()

    cerebro.setbroker(broker)
    cerebro.adddata(data)
    cerebro.addstrategy(ReconnectStrategy)
    cerebro.addobserver(bt.observers.TradeLogger, log_dir=str(tmp_path), log_format="json")

    results = cerebro.run()

    assert len(results) == 1

    system_entries = _read_json_lines(tmp_path / "system.log")
    system_events = [entry["event_type"] for entry in system_entries]

    assert "store_reconnect_success" in system_events


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
        params = (("symbol", symbol),)

        def __init__(self):
            self.pending_order = None
            self.completed_orders = 0
            self._last_order_status = {}
            self.placeholder_data = {
                self.p.symbol: ChannelPlaceholderData(self.p.symbol)
            }

        @property
        def data_obj(self):
            return self.placeholder_data[self.p.symbol]

        def notify_tick(self, tick):
            if tick.symbol != self.p.symbol or self.pending_order is not None:
                return

            position = self.broker.getposition(self.data_obj).size
            if self.completed_orders == 0 and position <= 0:
                self.pending_order = self.buy(data=self.data_obj, size=1, exectype=bt.Order.Market)
            elif self.completed_orders == 1 and position > 0:
                self.pending_order = self.sell(data=self.data_obj, size=1, exectype=bt.Order.Market)

        def notify_order(self, order):
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
    assert any(entry["status"] == "Completed" and entry["data_name"] == symbol for entry in order_entries)
    assert any(entry["isclosed"] is True and entry["data_name"] == symbol for entry in trade_entries)
    assert len(value_entries) == 4
    assert any(entry["data_name"] == symbol for entry in position_entries)


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
