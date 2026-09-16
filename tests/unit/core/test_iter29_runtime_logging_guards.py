"""Logging must preserve runtime fallbacks and bounded diagnostic volume."""

import collections
import logging
from types import SimpleNamespace

import pytest

import backtrader as bt
import backtrader._cerebro.channel as channel_module
import backtrader.brokers.btapibroker as broker_module
import backtrader.feeds.btapifeed as feed_module
import backtrader.functions as functions_module
import backtrader.linebuffer as linebuffer_module
import backtrader.lineiterator as lineiterator_module
import backtrader.lineseries as lineseries_module
import backtrader.stores.btapistore as store_module
import backtrader.strategy as strategy_module
from backtrader.channel import Event
from backtrader.events import BarEvent, TickEvent
from backtrader.utils import log_message
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store


class RecordingHandler(logging.Handler):
    def __init__(self, fail=False):
        super().__init__()
        self.records = []
        self.fail = fail

    def emit(self, record):
        self.records.append(record)
        if self.fail:
            raise RuntimeError("diagnostic sink unavailable")


def install_logger(monkeypatch, module, fail=False):
    """Install an in-memory logger on ``module`` and return its handler.

    Args:
        monkeypatch: Pytest fixture used to swap the module logger.
        module: Module whose ``logger`` attribute is replaced.
        fail: When True, the handler raises to exercise sink-failure paths.

    Returns:
        RecordingHandler: The attached handler capturing emitted records.
    """
    logger = logging.Logger(module.__name__, logging.DEBUG)
    handler = RecordingHandler(fail)
    logger.addHandler(handler)
    monkeypatch.setattr(module, "logger", logger)
    return handler


@pytest.mark.parametrize("module", [feed_module, broker_module, store_module])
@pytest.mark.parametrize("level", ["debug", "warning", "error"])
def test_failed_sink_is_counted_once_without_retry(monkeypatch, module, level):
    handler = install_logger(monkeypatch, module, fail=True)
    monkeypatch.setattr(module, "_LOGGING_HEALTH", collections.Counter())

    module._safe_log(level, "callback failed: %s", {"api_secret": "synthetic-secret"})

    assert module._LOGGING_HEALTH["logging_errors"] == 1
    assert len(handler.records) == 1
    assert "synthetic-secret" not in handler.records[0].getMessage()


@pytest.mark.parametrize("broken_sink", [False, True])
def test_broker_start_failure_keeps_cleanup_and_original_exception(monkeypatch, broken_sink):
    handler = install_logger(monkeypatch, broker_module, fail=broken_sink)
    original = RuntimeError("SDK response includes synthetic-secret")
    frozen = []

    def failed_start(*, broker):
        # Simulate an SDK startup failure after partially hydrating its broker.
        broker._live_started = True
        broker._positions_snapshot_loaded = True
        broker.positions["partial"] = object()
        broker._remote_open_orders_snapshot = [{"id": "partial"}]
        raise original

    store = SimpleNamespace(_sdk_mode=True, start=failed_start, freeze_openings=frozen.append)
    broker = broker_module.BtApiBroker(store=store)
    with pytest.raises(RuntimeError) as caught:
        broker.start()

    assert caught.value is original
    assert not broker._live_started
    assert not broker._startup_ready
    assert not broker._trading_enabled
    assert not broker._positions_snapshot_loaded
    assert not broker.positions
    assert not broker._remote_open_orders_snapshot
    assert frozen == ["broker_start_failed"]
    assert handler.records
    assert all(not record.exc_info for record in handler.records)
    assert "synthetic-secret" not in "\n".join(r.getMessage() for r in handler.records)


@pytest.mark.parametrize("raise_errors", [False, True])
def test_account_query_log_failure_preserves_cached_fallback(monkeypatch, raise_errors):
    handler = install_logger(monkeypatch, store_module, fail=True)
    original = RuntimeError("account response includes synthetic-secret")
    client = FakeBtApiClient()
    store = make_store(api=client)
    monkeypatch.setattr(store, "_ensure_api_ready", lambda: client)
    store._last_balance_refresh = 1.0
    store._cash, store._value = 123.0, 456.0

    def failed_balance():
        raise original

    monkeypatch.setattr(client, "get_balance", failed_balance)
    if raise_errors:
        with pytest.raises(RuntimeError) as caught:
            store.get_balance(force=True, raise_errors=True)
        assert caught.value is original
    else:
        assert store.get_balance(force=True) == {"cash": 123.0, "value": 456.0}
    assert all(not record.exc_info for record in handler.records)
    assert "synthetic-secret" not in "\n".join(r.getMessage() for r in handler.records)


@pytest.mark.parametrize("missing_value", [False, True])
def test_expected_strategy_clock_probes_remain_silent(monkeypatch, missing_value):
    handler = install_logger(monkeypatch, strategy_module)

    class UnreadableClock:
        def __len__(self):
            raise TypeError("clock has no comparable length")

    class Action:
        advances = 0

        def __len__(self):
            return 0

        def __getitem__(self, index):
            raise IndexError("buffer not populated yet")

        def _next(self):
            self.advances += 1

    action = Action()
    clock = [] if missing_value else UnreadableClock()
    owner = SimpleNamespace(_get_strategy_next_lineactions=lambda: [(action, clock)])
    for _ in range(250):
        bt.Strategy._next_strategy_lineactions(owner)
    assert action.advances == (0 if missing_value else 250)
    assert handler.records == []


def test_if_dynamic_operand_storm_is_bounded_and_keeps_values(monkeypatch):
    handler = install_logger(monkeypatch, functions_module)
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(log_message, "_throttle_enabled", True)

    class UnavailableOperand:
        def __getitem__(self, index):
            raise IndexError("operand has no value yet")

    operation = SimpleNamespace(
        array=[float("nan")] * 250,
        a=UnavailableOperand(),
        b=UnavailableOperand(),
        cond=UnavailableOperand(),
        bindings=[],
    )
    functions_module.If._once_batch(operation, 0, 250)

    assert operation.array == [0.0] * 250
    # Two one-off scalar probes plus three first occurrences/two summaries.
    assert len(handler.records) == 11
    assert sum("repeated" in record.getMessage() for record in handler.records) == 6
    states = list(log_message._throttle_state.values())
    assert len(states) == 3
    assert all(state["total"] == 250 and state["count"] == 49 for state in states)


def test_optional_operand_lengths_do_not_log_each_sample(monkeypatch):
    handler = install_logger(monkeypatch, linebuffer_module)

    class Operand:
        _clock = object()
        advances = 0

        def __len__(self):
            raise TypeError("optional length unavailable")

        def __getitem__(self, index):
            return 42.0

        def _next(self):
            self.advances += 1

    operand = Operand()
    for _ in range(250):
        assert (
            linebuffer_module.LinesOperation._operand_value(None, operand, guard_minperiod=True)
            == 42.0
        )
        linebuffer_module.LinesOperation._next_operand_if_due(None, operand)
    assert operand.advances == 250
    assert handler.records == []


def test_slotted_clock_cache_fallback_stays_silent(monkeypatch):
    handler = install_logger(monkeypatch, lineiterator_module)

    class SlottedAction:
        __slots__ = ("_clock",)

    action = SlottedAction()
    action._clock = object()
    for _ in range(250):
        assert lineiterator_module._lineaction_source_clock(action) is action._clock
        assert lineiterator_module._clock_is_replaying(action._clock) is False
    assert handler.records == []


def test_broken_clock_replay_property_is_throttled(monkeypatch):
    handler = install_logger(monkeypatch, lineiterator_module)
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(log_message, "_throttle_enabled", True)

    class BrokenClock:
        @property
        def replaying(self):
            raise RuntimeError("invalid replay state")

    clock = BrokenClock()
    for _ in range(250):
        assert lineiterator_module._clock_is_replaying(clock) is False
    assert len(handler.records) == 3
    assert sum(state["total"] for state in log_message._throttle_state.values()) == 250


@pytest.mark.parametrize("invalid_timestamp", [False, True])
def test_channel_event_failures_are_bounded_and_do_not_log_payload(monkeypatch, invalid_timestamp):
    handler = install_logger(monkeypatch, channel_module)
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(log_message, "_throttle_enabled", True)
    placeholder = SimpleNamespace(_len="invalid", datetime=(), close=())
    strategy = SimpleNamespace(
        datas=[],
        forward=lambda: None,
        lines=SimpleNamespace(datetime=[0.0]),
        placeholder_data={"TEST": placeholder},
    )
    event = SimpleNamespace(
        timestamp="synthetic-secret" if invalid_timestamp else 1,
        data=SimpleNamespace(symbol="TEST", price="synthetic-secret"),
    )
    for _ in range(250):
        channel_module.ChannelMixin._advance_channel_strategy_clock(None, strategy, event)
    keys = 1 if invalid_timestamp else 3
    assert len(handler.records) == 3 * keys
    assert sum(state["total"] for state in log_message._throttle_state.values()) == 250 * keys
    assert all(not record.exc_info for record in handler.records)
    assert "synthetic-secret" not in "\n".join(r.getMessage() for r in handler.records)


def test_channel_forward_failure_is_throttled_without_payload(monkeypatch):
    """A broken no-data strategy must not emit one traceback per event."""
    handler = install_logger(monkeypatch, channel_module)
    monkeypatch.setattr(log_message, "_throttle_state", {})
    monkeypatch.setattr(log_message, "_throttle_enabled", True)

    class BrokenStrategy:
        datas = []

        @staticmethod
        def forward():
            raise RuntimeError("unclassified-channel-payload")

    event = SimpleNamespace(timestamp=None)
    for _ in range(250):
        channel_module.ChannelMixin._advance_channel_strategy_clock(None, BrokenStrategy(), event)

    assert len(handler.records) == 3
    assert all(not record.exc_info for record in handler.records)
    assert "unclassified-channel-payload" not in "\n".join(r.getMessage() for r in handler.records)
    assert sum(state["total"] for state in log_message._throttle_state.values()) == 250


def test_channel_without_placeholder_mapping_skips_lines_fallback_debug(monkeypatch):
    """The optional map must not resolve through LineSeries for every event."""
    placeholder_lookups = []
    original_getattr = lineseries_module.LineSeries.__getattr__

    def tracking_getattr(instance, name):
        if name == "placeholder_data":
            placeholder_lookups.append(name)
        return original_getattr(instance, name)

    monkeypatch.setattr(lineseries_module.LineSeries, "__getattr__", tracking_getattr)

    class NoPlaceholderStrategy(bt.Strategy):
        def __init__(self):
            self.tick_count = 0
            self.bar_count = 0

        def notify_tick(self, tick):
            self.tick_count += 1

        def notify_bar(self, bar):
            self.bar_count += 1

    events = []
    for index in range(100):
        events.extend(
            (
                Event(
                    data=TickEvent(timestamp=index, symbol="TEST", price=100.0, volume=1.0),
                    channel_type="tick",
                    channel_name="TEST",
                ),
                Event(
                    data=BarEvent(
                        timestamp=index,
                        symbol="TEST",
                        open=100.0,
                        high=101.0,
                        low=99.0,
                        close=100.5,
                        volume=1.0,
                    ),
                    channel_type="bar",
                    channel_name="TEST",
                ),
            )
        )

    cerebro = bt.Cerebro()
    cerebro.addstrategy(NoPlaceholderStrategy)
    strategy = cerebro.run(channel=True)[0]
    placeholder_lookups.clear()
    for event in events:
        cerebro._advance_channel_strategy_clock(strategy, event)
        cerebro.dispatch_channel_event(event)

    assert (strategy.tick_count, strategy.bar_count, strategy._event_count) == (100, 100, 200)
    assert placeholder_lookups == []
    assert cerebro.close_channel() is True


def test_channel_placeholder_mapping_property_is_supported():
    """Direct optional lookup retains descriptor-backed strategy mappings."""
    placeholder = SimpleNamespace(_len=0, datetime=[0.0], close=[0.0])

    class DescriptorStrategy:
        datas = []
        lines = SimpleNamespace(datetime=[0.0])

        @property
        def placeholder_data(self):
            return {"TEST": placeholder}

        @staticmethod
        def forward():
            return None

        def __len__(self):
            return 2

    channel_module.ChannelMixin._advance_channel_strategy_clock(
        None,
        DescriptorStrategy(),
        SimpleNamespace(timestamp=1, data=SimpleNamespace(symbol="TEST", price=123.0)),
    )

    assert placeholder._len == 2
    assert placeholder.datetime[0] > 0.0
    assert placeholder.close[0] == 123.0


def test_channel_placeholder_mapping_custom_attribute_accessor_is_supported():
    """A strategy may dynamically expose its optional placeholder mapping."""
    placeholder = SimpleNamespace(_len=0, datetime=[0.0], close=[0.0])

    class DynamicAccessorStrategy(bt.Strategy):
        def __init__(self):
            self._dynamic_placeholder_data = {"TEST": placeholder}

        def __getattribute__(self, name):
            if name == "placeholder_data":
                return object.__getattribute__(self, "_dynamic_placeholder_data")
            return super().__getattribute__(name)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(DynamicAccessorStrategy)
    strategy = cerebro.run(channel=True)[0]
    channel_module.ChannelMixin._advance_channel_strategy_clock(
        cerebro,
        strategy,
        SimpleNamespace(timestamp=1, data=SimpleNamespace(symbol="TEST", price=321.0)),
    )

    assert placeholder._len == len(strategy)
    assert placeholder.datetime[0] > 0.0
    assert placeholder.close[0] == 321.0
    assert cerebro.close_channel() is True


def test_channel_placeholder_mapping_custom_getattr_is_supported():
    """A custom __getattr__ remains eligible for dynamic placeholder data."""
    placeholder = SimpleNamespace(_len=0, datetime=[0.0], close=[0.0])

    class DynamicGetattrStrategy(bt.Strategy):
        def __init__(self):
            self._dynamic_placeholder_data = {"TEST": placeholder}

        def __getattr__(self, name):
            if name == "placeholder_data":
                return object.__getattribute__(self, "_dynamic_placeholder_data")
            return super().__getattr__(name)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(DynamicGetattrStrategy)
    strategy = cerebro.run(channel=True)[0]
    channel_module.ChannelMixin._advance_channel_strategy_clock(
        cerebro,
        strategy,
        SimpleNamespace(timestamp=1, data=SimpleNamespace(symbol="TEST", price=456.0)),
    )

    assert placeholder._len == len(strategy)
    assert placeholder.datetime[0] > 0.0
    assert placeholder.close[0] == 456.0
    assert cerebro.close_channel() is True
