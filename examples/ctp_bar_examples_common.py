from __future__ import annotations

import json
import sys
from collections import defaultdict, deque
from pathlib import Path

import backtrader as bt
import pandas as pd
from backtrader.channel import StreamingEventQueue
from backtrader.events import BarEvent, TickEvent
from backtrader.feeds.mixed_channel import MixedChannel

from ctp_example_support import (
    BASE_FUTURES_STRATEGY_PARAMS,
    ConfigurableFuturesStrategyBase,
    MemoryChannel,
)

_EXAMPLES_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _EXAMPLES_ROOT.parent

for _path in (_EXAMPLES_ROOT, _REPO_ROOT):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)


BAR_STRATEGY_PARAMS = BASE_FUTURES_STRATEGY_PARAMS + (
    ("bar_source", "datafeed"),
    ("bar_seconds", 5),
    ("stop_after_bars", 0),
    ("stop_after_open_position", False),
    ("force_entry_after_bars", 0),
    ("force_exit_after_bars", 0),
    ("max_bar_history", 64),
)


class FiveSecondBarStrategyBase(ConfigurableFuturesStrategyBase):
    params = BAR_STRATEGY_PARAMS

    def __init__(self):
        super().__init__()
        self.bar_history = defaultdict(
            lambda: deque(maxlen=max(int(self.p.max_bar_history), 8))
        )
        self.bar_counts = defaultdict(int)
        self.latest_bars = {}
        self._last_bar_keys = {}
        self._tick_bars = {}

    def _bar_source(self):
        return str(self.p.bar_source or "datafeed").strip().lower()

    def _bar_key(self, timestamp):
        try:
            return int(round(float(timestamp) * 1000.0))
        except (TypeError, ValueError):
            return timestamp

    def _record_completed_bar(self, symbol, timestamp, open_, high, low, close, volume):
        symbol = str(symbol)
        key = self._bar_key(timestamp)
        if self._last_bar_keys.get(symbol) == key:
            return None

        bar = {
            "symbol": symbol,
            "timestamp": float(timestamp),
            "open": float(open_),
            "high": float(high),
            "low": float(low),
            "close": float(close),
            "volume": float(volume or 0.0),
        }
        self._last_bar_keys[symbol] = key
        self.latest_bars[symbol] = bar
        self.bar_history[symbol].append(bar)
        self.bar_counts[symbol] += 1
        return bar

    def _ingest_tick_as_bar(self, tick):
        bar_seconds = max(int(self.p.bar_seconds or 5), 1)
        symbol = str(tick.symbol)
        tick_timestamp = float(getattr(tick, "timestamp", getattr(tick, "local_time", 0.0)) or 0.0)
        bucket_start = int(tick_timestamp // bar_seconds) * bar_seconds
        bucket_end = bucket_start + bar_seconds
        price = float(tick.price)
        volume = float(getattr(tick, "volume", 0.0) or 0.0)

        completed = None
        current = self._tick_bars.get(symbol)
        if current is not None and current["bucket_start"] != bucket_start:
            completed = self._record_completed_bar(
                symbol=symbol,
                timestamp=current["bucket_end"],
                open_=current["open"],
                high=current["high"],
                low=current["low"],
                close=current["close"],
                volume=current["volume"],
            )
            current = None

        if current is None:
            current = {
                "bucket_start": bucket_start,
                "bucket_end": bucket_end,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": volume,
            }
        else:
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            current["volume"] += volume
        self._tick_bars[symbol] = current
        return completed

    def notify_tick(self, tick):
        self.reconcile_pending_order_states()
        if self._bar_source() != "ticks":
            return
        completed_bar = self._ingest_tick_as_bar(tick)
        if completed_bar is not None:
            self.on_completed_bar(completed_bar)

    def notify_bar(self, bar):
        self.reconcile_pending_order_states()
        if self._bar_source() not in {"channel_bar", "bar_event"}:
            return
        completed_bar = self._record_completed_bar(
            symbol=bar.symbol,
            timestamp=float(getattr(bar, "timestamp", getattr(bar, "local_time", 0.0)) or 0.0),
            open_=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=getattr(bar, "volume", 0.0),
        )
        if completed_bar is not None:
            self.on_completed_bar(completed_bar)

    def next(self):
        if self._bar_source() != "datafeed":
            return

        self.reconcile_pending_order_states()
        for data in self.datas:
            if len(data) <= 0:
                continue
            dt = data.datetime.datetime(0)
            completed_bar = self._record_completed_bar(
                symbol=getattr(data, "_name", getattr(data, "_dataname", "UNKNOWN")),
                timestamp=dt.timestamp(),
                open_=data.open[0],
                high=data.high[0],
                low=data.low[0],
                close=data.close[0],
                volume=getattr(data.volume, "__getitem__", lambda _i: 0.0)(0),
            )
            if completed_bar is not None:
                self.on_completed_bar(completed_bar)

    def maybe_stop_after_bar_limit(self):
        limit = int(self.p.stop_after_bars or 0)
        if limit > 0 and self.total_completed_bars() >= limit and not self.pending_refs:
            self.log(f"bar limit reached ({limit}), stopping")
            self.cerebro.runstop()
            return True
        return False

    def total_completed_bars(self):
        return sum(int(value) for value in self.bar_counts.values())

    def symbol_bar_count(self, symbol):
        return int(self.bar_counts.get(str(symbol), 0))

    def pair_bar_progress(self, symbol_a, symbol_b):
        return min(self.symbol_bar_count(symbol_a), self.symbol_bar_count(symbol_b))

    def mean_close(self, symbol, window):
        history = self.bar_history[str(symbol)]
        window = int(window)
        if window <= 0 or len(history) < window:
            return None
        values = [bar["close"] for bar in list(history)[-window:]]
        return sum(values) / float(window)

    def on_completed_bar(self, bar):
        raise NotImplementedError

    def get_summary(self):
        summary = super().get_summary()
        summary.update(
            {
                "bar_counts": {key: int(value) for key, value in sorted(self.bar_counts.items())},
                "latest_bars": {
                    key: {
                        "timestamp": float(value["timestamp"]),
                        "close": float(value["close"]),
                    }
                    for key, value in sorted(self.latest_bars.items())
                },
            }
        )
        return summary


class SingleSymbolMaStrategy(FiveSecondBarStrategyBase):
    params = BAR_STRATEGY_PARAMS + (
        ("symbol", "rb2605"),
        ("fast_window", 2),
        ("slow_window", 3),
        ("entry_bias", 0.0),
        ("exit_bias", 0.0),
        ("order_size", 1),
        ("max_roundtrips", 1),
    )

    def __init__(self):
        super().__init__()
        self._observed_open_position = False
        self._open_bar_at = None
        self._forced_phase = "idle"
        self._forced_entry_terminal_refs = set()
        self._forced_exit_terminal_refs = set()

    def _handle_forced_signals(self, position):
        current_bar = self.symbol_bar_count(self.p.symbol)
        if (
            self._forced_phase == "idle"
            and int(self.p.force_entry_after_bars or 0) > 0
            and current_bar >= int(self.p.force_entry_after_bars)
        ):
            self._submit_market(
                side="buy",
                symbol=self.p.symbol,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_bar_single_entry",
            )
            self._forced_phase = "entry_submitted"
            return True

        if (
            self._forced_phase == "open"
            and int(self.p.force_exit_after_bars or 0) > 0
            and self._open_bar_at is not None
            and current_bar - int(self._open_bar_at) >= int(self.p.force_exit_after_bars)
        ):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol,
                size=max(abs(position), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_bar_single_exit",
            )
            self._forced_phase = "exit_submitted"
            return True

        return False

    def on_completed_bar(self, bar):
        if bar["symbol"] != self.p.symbol:
            self.maybe_stop_after_bar_limit()
            return

        position = self._position_size(self.p.symbol)
        if position > 0:
            self._observed_open_position = True
            if self._open_bar_at is None:
                self._open_bar_at = self.symbol_bar_count(self.p.symbol)

        if self.pending_refs:
            self.maybe_stop_after_bar_limit()
            return

        if self._handle_forced_signals(position):
            self.maybe_stop_after_bar_limit()
            return

        fast = self.mean_close(self.p.symbol, self.p.fast_window)
        slow = self.mean_close(self.p.symbol, self.p.slow_window)
        if fast is None or slow is None:
            self.maybe_stop_after_bar_limit()
            return

        if int(self.p.max_roundtrips or 0) > 0 and self.completed_roundtrips >= int(self.p.max_roundtrips):
            self.maybe_stop_after_bar_limit()
            return

        if position <= 0 and fast >= slow + float(self.p.entry_bias):
            self._submit_market(
                side="buy",
                symbol=self.p.symbol,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="single_ma_entry",
            )
        elif position > 0 and fast <= slow - float(self.p.exit_bias):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol,
                size=max(abs(position), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="single_ma_exit",
            )
        self.maybe_stop_after_bar_limit()

    def after_terminal_order(self, order):
        def _maybe_stop_after_open_position():
            if bool(getattr(self.p, "stop_after_open_position", False)) and not self.pending_refs:
                self.log("open position observed, stopping")
                self.cerebro.runstop()

        info = getattr(order, "info", None)
        signal_tag = info.get("signal_tag", "") if hasattr(info, "get") else getattr(info, "signal_tag", "")
        if signal_tag == "forced_bar_single_entry":
            self._forced_entry_terminal_refs.add(order.ref)
            if not self.pending_refs:
                if order.status in (order.Canceled, order.Margin, order.Rejected):
                    self._forced_phase = "idle"
                    self._forced_entry_terminal_refs.clear()
                elif self._forced_entry_terminal_refs:
                    self._observed_open_position = True
                    self._open_bar_at = self.symbol_bar_count(self.p.symbol)
                    self._forced_phase = "open"
                    _maybe_stop_after_open_position()
            return

        if signal_tag == "forced_bar_single_exit":
            self._forced_exit_terminal_refs.add(order.ref)
            if not self.pending_refs:
                if order.status in (order.Canceled, order.Margin, order.Rejected):
                    self._forced_phase = "open"
                    self._forced_exit_terminal_refs.clear()
                elif self._forced_exit_terminal_refs:
                    self.completed_roundtrips += 1
                    self._observed_open_position = False
                    self._open_bar_at = None
                    self._forced_phase = "done"
                    self.log(f"single MA roundtrip completed: {self.completed_roundtrips}")
                    self.stop_if_roundtrips_complete(self.p.max_roundtrips)
            return

        position = self._position_size(self.p.symbol)
        if position > 0:
            self._observed_open_position = True
            if self._open_bar_at is None:
                self._open_bar_at = self.symbol_bar_count(self.p.symbol)
            _maybe_stop_after_open_position()
            return

        if abs(position) < 1e-12 and self._observed_open_position and not self.pending_refs:
            self.completed_roundtrips += 1
            self._observed_open_position = False
            self._open_bar_at = None
            self.log(f"single MA roundtrip completed: {self.completed_roundtrips}")
            self.stop_if_roundtrips_complete(self.p.max_roundtrips)


class PairSpreadStrategy(FiveSecondBarStrategyBase):
    params = BAR_STRATEGY_PARAMS + (
        ("symbol_a", "rb2605"),
        ("symbol_b", "hc2605"),
        ("spread_window", 3),
        ("entry_edge", 1.0),
        ("exit_edge", 0.2),
        ("order_size", 1),
        ("max_roundtrips", 1),
    )

    def __init__(self):
        super().__init__()
        self._observed_open_pair = False
        self._pair_open_bar_at = None
        self._forced_phase = "idle"
        self._forced_entry_terminal_refs = set()
        self._forced_exit_terminal_refs = set()

    def _pair_positions(self):
        return self._position_size(self.p.symbol_a), self._position_size(self.p.symbol_b)

    def _pair_is_flat(self):
        pos_a, pos_b = self._pair_positions()
        return abs(pos_a) < 1e-12 and abs(pos_b) < 1e-12

    def _pair_is_open(self):
        pos_a, pos_b = self._pair_positions()
        return pos_a < -1e-12 and pos_b > 1e-12

    def _mean_spread(self):
        window = int(self.p.spread_window)
        bars_a = self.bar_history[self.p.symbol_a]
        bars_b = self.bar_history[self.p.symbol_b]
        if len(bars_a) < window or len(bars_b) < window:
            return None
        spreads = []
        for bar_a, bar_b in zip(list(bars_a)[-window:], list(bars_b)[-window:]):
            spreads.append(float(bar_a["close"]) - float(bar_b["close"]))
        return sum(spreads) / float(window)

    def _handle_forced_signals(self):
        current_bar = self.pair_bar_progress(self.p.symbol_a, self.p.symbol_b)
        if (
            self._forced_phase == "idle"
            and int(self.p.force_entry_after_bars or 0) > 0
            and current_bar >= int(self.p.force_entry_after_bars)
        ):
            order_a = self._submit_market(
                side="sell",
                symbol=self.p.symbol_a,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_pair_bar_open_short_a",
            )
            order_b = self._submit_market(
                side="buy",
                symbol=self.p.symbol_b,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_pair_bar_open_long_b",
            )
            if order_a is not None or order_b is not None:
                self._forced_phase = "entry_submitted"
            return True

        if (
            self._forced_phase == "open"
            and int(self.p.force_exit_after_bars or 0) > 0
            and self._pair_open_bar_at is not None
            and current_bar - int(self._pair_open_bar_at) >= int(self.p.force_exit_after_bars)
        ):
            pos_a, pos_b = self._pair_positions()
            order_a = self._submit_market(
                side="buy",
                symbol=self.p.symbol_a,
                size=max(abs(pos_a), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_pair_bar_close_buy_a",
            )
            order_b = self._submit_market(
                side="sell",
                symbol=self.p.symbol_b,
                size=max(abs(pos_b), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_pair_bar_close_sell_b",
            )
            if order_a is not None or order_b is not None:
                self._forced_phase = "exit_submitted"
            return True

        return False

    def on_completed_bar(self, bar):
        if bar["symbol"] not in (self.p.symbol_a, self.p.symbol_b):
            self.maybe_stop_after_bar_limit()
            return

        if self._pair_is_open():
            self._observed_open_pair = True
            if self._pair_open_bar_at is None:
                self._pair_open_bar_at = self.pair_bar_progress(self.p.symbol_a, self.p.symbol_b)

        if self.pending_refs:
            self.maybe_stop_after_bar_limit()
            return

        if self._handle_forced_signals():
            self.maybe_stop_after_bar_limit()
            return

        mean_spread = self._mean_spread()
        latest_a = self.latest_bars.get(self.p.symbol_a)
        latest_b = self.latest_bars.get(self.p.symbol_b)
        if mean_spread is None or latest_a is None or latest_b is None:
            self.maybe_stop_after_bar_limit()
            return

        if int(self.p.max_roundtrips or 0) > 0 and self.completed_roundtrips >= int(self.p.max_roundtrips):
            self.maybe_stop_after_bar_limit()
            return

        current_spread = float(latest_a["close"]) - float(latest_b["close"])
        spread_edge = current_spread - mean_spread

        if self._pair_is_flat() and spread_edge >= float(self.p.entry_edge):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol_a,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="pair_bar_open_short_a",
            )
            self._submit_market(
                side="buy",
                symbol=self.p.symbol_b,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="pair_bar_open_long_b",
            )
        elif self._pair_is_open() and spread_edge <= float(self.p.exit_edge):
            pos_a, pos_b = self._pair_positions()
            self._submit_market(
                side="buy",
                symbol=self.p.symbol_a,
                size=max(abs(pos_a), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="pair_bar_close_buy_a",
            )
            self._submit_market(
                side="sell",
                symbol=self.p.symbol_b,
                size=max(abs(pos_b), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="pair_bar_close_sell_b",
            )
        self.maybe_stop_after_bar_limit()

    def after_terminal_order(self, order):
        def _maybe_stop_after_open_position():
            if bool(getattr(self.p, "stop_after_open_position", False)) and not self.pending_refs:
                self.log("open position observed, stopping")
                self.cerebro.runstop()

        info = getattr(order, "info", None)
        signal_tag = info.get("signal_tag", "") if hasattr(info, "get") else getattr(info, "signal_tag", "")
        if signal_tag.startswith("forced_pair_bar_open_"):
            self._forced_entry_terminal_refs.add(order.ref)
            if not self.pending_refs:
                if order.status in (order.Canceled, order.Margin, order.Rejected):
                    self._forced_phase = "idle"
                    self._forced_entry_terminal_refs.clear()
                elif len(self._forced_entry_terminal_refs) >= 2:
                    self._observed_open_pair = True
                    self._pair_open_bar_at = self.pair_bar_progress(self.p.symbol_a, self.p.symbol_b)
                    self._forced_phase = "open"
                    _maybe_stop_after_open_position()
            return

        if signal_tag.startswith("forced_pair_bar_close_"):
            self._forced_exit_terminal_refs.add(order.ref)
            if not self.pending_refs:
                if order.status in (order.Canceled, order.Margin, order.Rejected):
                    self._forced_phase = "open"
                    self._forced_exit_terminal_refs.clear()
                elif len(self._forced_exit_terminal_refs) >= 2:
                    self.completed_roundtrips += 1
                    self._observed_open_pair = False
                    self._pair_open_bar_at = None
                    self._forced_phase = "done"
                    self.log(f"pair bar roundtrip completed: {self.completed_roundtrips}")
                    self.stop_if_roundtrips_complete(self.p.max_roundtrips)
            return

        if self._pair_is_open():
            self._observed_open_pair = True
            if self._pair_open_bar_at is None:
                self._pair_open_bar_at = self.pair_bar_progress(self.p.symbol_a, self.p.symbol_b)
            _maybe_stop_after_open_position()
            return

        if self._pair_is_flat() and self._observed_open_pair and not self.pending_refs:
            self.completed_roundtrips += 1
            self._observed_open_pair = False
            self._pair_open_bar_at = None
            self.log(f"pair bar roundtrip completed: {self.completed_roundtrips}")
            self.stop_if_roundtrips_complete(self.p.max_roundtrips)


STRATEGIES = {
    "single_symbol": SingleSymbolMaStrategy,
    "pair_arbitrage": PairSpreadStrategy,
}


def get_strategy_class(name):
    normalized = str(name or "").strip().lower()
    if normalized not in STRATEGIES:
        raise ValueError(f"Unsupported 5s bar strategy: {name}")
    return STRATEGIES[normalized]


def _parse_bar_point(raw_point):
    if isinstance(raw_point, dict):
        return (
            float(raw_point["offset"]),
            float(raw_point["open"]),
            float(raw_point["high"]),
            float(raw_point["low"]),
            float(raw_point["close"]),
            float(raw_point.get("volume", 0.0)),
        )

    if isinstance(raw_point, (list, tuple)) and len(raw_point) >= 6:
        return (
            float(raw_point[0]),
            float(raw_point[1]),
            float(raw_point[2]),
            float(raw_point[3]),
            float(raw_point[4]),
            float(raw_point[5]),
        )

    raise ValueError(f"Unsupported bar point: {raw_point!r}")


def _build_bar_events(symbol, bar_points, start_timestamp):
    events = []
    for index, raw_point in enumerate(bar_points):
        offset, open_, high, low, close, volume = _parse_bar_point(raw_point)
        timestamp = float(start_timestamp) + offset
        events.append(
            BarEvent(
                timestamp=timestamp,
                symbol=str(symbol),
                exchange="SIM",
                asset_type="futures",
                local_time=timestamp,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                openinterest=0.0,
            )
        )
    return events


def _build_ticks_from_bars(symbol, bar_points, start_timestamp, bar_seconds, extra_tick=True):
    ticks = []
    parsed_points = [_parse_bar_point(point) for point in bar_points]
    for index, (offset, _open, _high, _low, close, volume) in enumerate(parsed_points):
        timestamp = float(start_timestamp) + offset + float(bar_seconds) - 0.001
        ticks.append(
            TickEvent(
                timestamp=timestamp,
                symbol=str(symbol),
                exchange="SIM",
                asset_type="futures",
                local_time=timestamp,
                price=float(close),
                volume=float(volume),
                direction="buy",
                trade_id=f"{symbol}-bar-tick-{index}",
            )
        )
    if extra_tick and parsed_points:
        last_offset, _open, _high, _low, last_close, last_volume = parsed_points[-1]
        timestamp = float(start_timestamp) + last_offset + float(bar_seconds) + 0.001
        ticks.append(
            TickEvent(
                timestamp=timestamp,
                symbol=str(symbol),
                exchange="SIM",
                asset_type="futures",
                local_time=timestamp,
                price=float(last_close),
                volume=float(last_volume or 1.0),
                direction="buy",
                trade_id=f"{symbol}-bar-tick-final",
            )
        )
    return ticks


def build_tick_backtest_channel(config):
    scenario = dict(config.get("scenario") or {})
    scenario_type = str(scenario.get("type") or "").strip().lower()
    start_timestamp = float(scenario.get("start_timestamp", 1710000000.0))
    bar_seconds = int(scenario.get("bar_seconds", config.get("bar_seconds", 5)))

    if scenario_type == "single_symbol_bars":
        symbol = str(scenario.get("symbol") or config["strategy_params"]["symbol"])
        ticks = _build_ticks_from_bars(symbol, scenario.get("bars") or [], start_timestamp, bar_seconds)
        return StreamingEventQueue(
            channels=[MemoryChannel("tick", symbol, ticks)],
            preload_window=1.0,
            adaptive=False,
        )

    if scenario_type == "pair_bars":
        channels = []
        for symbol, bars in dict(scenario.get("bars") or {}).items():
            ticks = _build_ticks_from_bars(symbol, bars, start_timestamp, bar_seconds)
            channels.append(MemoryChannel("tick", symbol, ticks))
        return StreamingEventQueue(channels=channels, preload_window=1.0, adaptive=False)

    raise ValueError(f"Unsupported tickbroker 5s scenario: {scenario_type}")


def build_mix_backtest_channel(config):
    scenario = dict(config.get("scenario") or {})
    scenario_type = str(scenario.get("type") or "").strip().lower()
    start_timestamp = float(scenario.get("start_timestamp", 1710000000.0))
    bar_seconds = int(scenario.get("bar_seconds", config.get("bar_seconds", 5)))

    if scenario_type == "single_symbol_bars":
        symbol = str(scenario.get("symbol") or config["strategy_params"]["symbol"])
        bars = scenario.get("bars") or []
        return MixedChannel(
            tick_channels=[MemoryChannel("tick", symbol, _build_ticks_from_bars(symbol, bars, start_timestamp, bar_seconds))],
            bars=[_build_bar_events(symbol, bars, start_timestamp)],
            adaptive=False,
            preload_window=1.0,
        )

    if scenario_type == "pair_bars":
        tick_channels = []
        bars = []
        for symbol, symbol_bars in dict(scenario.get("bars") or {}).items():
            tick_channels.append(
                MemoryChannel("tick", symbol, _build_ticks_from_bars(symbol, symbol_bars, start_timestamp, bar_seconds))
            )
            bars.append(_build_bar_events(symbol, symbol_bars, start_timestamp))
        return MixedChannel(
            tick_channels=tick_channels,
            bars=bars,
            adaptive=False,
            preload_window=1.0,
        )

    raise ValueError(f"Unsupported mixbroker 5s scenario: {scenario_type}")


def add_bbroker_backtest_feeds(cerebro, config):
    scenario = dict(config.get("scenario") or {})
    scenario_type = str(scenario.get("type") or "").strip().lower()
    start_timestamp = float(scenario.get("start_timestamp", 1710000000.0))

    if scenario_type == "single_symbol_bars":
        symbol = str(scenario.get("symbol") or config["strategy_params"]["symbol"])
        _add_single_dataframe(cerebro, symbol, scenario.get("bars") or [], start_timestamp)
        return

    if scenario_type == "pair_bars":
        for symbol, bars in dict(scenario.get("bars") or {}).items():
            _add_single_dataframe(cerebro, symbol, bars, start_timestamp)
        return

    raise ValueError(f"Unsupported backbroker 5s scenario: {scenario_type}")


def _add_single_dataframe(cerebro, symbol, bar_points, start_timestamp):
    rows = []
    for raw_point in bar_points:
        offset, open_, high, low, close, volume = _parse_bar_point(raw_point)
        dt = pd.to_datetime(float(start_timestamp) + offset, unit="s", utc=True)
        rows.append(
            {
                "datetime": dt,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "openinterest": 0.0,
            }
        )
    frame = pd.DataFrame(rows).set_index("datetime")
    data = bt.feeds.PandasData(
        dataname=frame,
        timeframe=bt.TimeFrame.Seconds,
        compression=5,
    )
    cerebro.adddata(data, name=str(symbol))


def format_summary(strategy):
    return json.dumps(strategy.get_summary(), ensure_ascii=False, indent=2, sort_keys=True)
