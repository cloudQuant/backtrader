from __future__ import annotations

import datetime as _dt
import json
import sys
from collections import defaultdict, deque
from pathlib import Path

_EXAMPLES_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _EXAMPLES_ROOT.parent

for _path in (_EXAMPLES_ROOT, _REPO_ROOT):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)

from backtrader.events import BarEvent, TickEvent
from backtrader.feeds.mixed_channel import MixedChannel

from ctp_example_support import (
    BASE_FUTURES_STRATEGY_PARAMS,
    ConfigurableFuturesStrategyBase,
    MemoryChannel,
)


class SingleSymbolMixStrategy(ConfigurableFuturesStrategyBase):
    params = BASE_FUTURES_STRATEGY_PARAMS + (
        ("symbol", "rb2610"),
        ("bar_window", 3),
        ("bar_source", "bars"),
        ("bar_seconds", 1),
        ("entry_bias", 1.0),
        ("exit_bias", 0.5),
        ("order_size", 1),
        ("max_roundtrips", 1),
        ("max_bar_history", 16),
    )

    def __init__(self):
        super().__init__()
        self.latest_tick_price = None
        self.bar_closes = deque(maxlen=max(int(self.p.max_bar_history), int(self.p.bar_window)))
        self._observed_open_position = False
        self._open_tick_at = None
        self._forced_phase = "idle"
        self._forced_entry_terminal_refs = set()
        self._forced_exit_terminal_refs = set()
        self._tick_bar_state = None

    def _use_tick_bars(self):
        return str(getattr(self.p, "bar_source", "bars") or "bars").strip().lower() == "ticks"

    def _tick_bucket_start(self, tick):
        tick_dt = getattr(tick, "datetime", None)
        if tick_dt is None:
            tick_dt = _dt.datetime.fromtimestamp(float(getattr(tick, "timestamp", 0.0) or 0.0))
        tick_dt = tick_dt.replace(microsecond=0)
        bar_seconds = max(int(getattr(self.p, "bar_seconds", 1) or 1), 1)
        second = (tick_dt.second // bar_seconds) * bar_seconds
        return tick_dt.replace(second=second)

    def _ingest_tick_bar(self, tick):
        bucket_start = self._tick_bucket_start(tick)
        price = float(tick.price)
        current = self._tick_bar_state
        if current is None:
            self._tick_bar_state = {"bucket_start": bucket_start, "close": price}
            return
        if bucket_start == current["bucket_start"]:
            current["close"] = price
            return
        self.bar_closes.append(float(current["close"]))
        self._tick_bar_state = {"bucket_start": bucket_start, "close": price}

    def _handle_forced_signals(self, position):
        force_entry_after_ticks = int(self.p.force_entry_after_ticks or 0)
        force_exit_after_ticks = int(self.p.force_exit_after_ticks or 0)

        if self._forced_phase == "idle" and force_entry_after_ticks > 0 and self._tick_count >= force_entry_after_ticks:
            self._submit_market(
                side="buy",
                symbol=self.p.symbol,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_mix_single_entry",
            )
            self._forced_phase = "entry_submitted"
            return True

        if (
            self._forced_phase == "open"
            and force_exit_after_ticks > 0
            and self._open_tick_at is not None
            and self._tick_count - int(self._open_tick_at) >= force_exit_after_ticks
        ):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol,
                size=max(abs(position), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_mix_single_exit",
            )
            self._forced_phase = "exit_submitted"
            return True

        return False

    def notify_bar(self, bar):
        if self._use_tick_bars():
            return
        if bar.symbol != self.p.symbol:
            return
        self.bar_closes.append(float(bar.close))

    def notify_tick(self, tick):
        if tick.symbol != self.p.symbol:
            return

        self.latest_tick_price = float(tick.price)
        if self._use_tick_bars():
            self._ingest_tick_bar(tick)
        position = self._position_size(self.p.symbol)
        if position > 0:
            self._observed_open_position = True
            if self._open_tick_at is None:
                self._open_tick_at = int(self._tick_count)

        self.maybe_cancel_stale_orders()
        if self.maybe_stop_after_tick_limit():
            return
        if self.pending_refs:
            return
        if self.forced_order_mode_enabled():
            self._handle_forced_signals(position)
            return
        if len(self.bar_closes) < int(self.p.bar_window):
            return
        if int(self.p.max_roundtrips or 0) > 0 and self.completed_roundtrips >= int(self.p.max_roundtrips):
            return

        bar_mean = sum(list(self.bar_closes)[-int(self.p.bar_window):]) / float(int(self.p.bar_window))
        if position <= 0 and self.latest_tick_price >= bar_mean + float(self.p.entry_bias):
            self._submit_market(
                side="buy",
                symbol=self.p.symbol,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="mix_single_entry",
            )
        elif position > 0 and self.latest_tick_price <= bar_mean - float(self.p.exit_bias):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol,
                size=max(abs(position), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="mix_single_exit",
            )

    def after_terminal_order(self, order):
        info = getattr(order, "info", None)
        signal_tag = info.get("signal_tag", "") if hasattr(info, "get") else getattr(info, "signal_tag", "")
        if self.forced_order_mode_enabled():
            if signal_tag == "forced_mix_single_entry":
                self._forced_entry_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "idle"
                        self._forced_entry_terminal_refs.clear()
                    elif self._forced_entry_terminal_refs:
                        self._observed_open_position = True
                        self._open_tick_at = int(getattr(self, "_tick_count", 0))
                        self._forced_phase = "open"
                return

            if signal_tag == "forced_mix_single_exit":
                self._forced_exit_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "open"
                        self._forced_exit_terminal_refs.clear()
                    elif self._forced_exit_terminal_refs:
                        self.completed_roundtrips += 1
                        self._observed_open_position = False
                        self._open_tick_at = None
                        self._forced_phase = "done"
                        self.log(f"mix single roundtrip completed: {self.completed_roundtrips}")
                        self.stop_if_roundtrips_complete(self.p.max_roundtrips)
                return

        position = self._position_size(self.p.symbol)
        if position > 0:
            self._observed_open_position = True
            if self._open_tick_at is None:
                self._open_tick_at = int(getattr(self, "_tick_count", 0))
            return

        if abs(position) < 1e-12 and self._observed_open_position and not self.pending_refs:
            self.completed_roundtrips += 1
            self._observed_open_position = False
            self._open_tick_at = None
            self.log(f"mix single roundtrip completed: {self.completed_roundtrips}")
            self.stop_if_roundtrips_complete(self.p.max_roundtrips)

    def get_summary(self):
        summary = super().get_summary()
        summary.update(
            {
                "symbol": self.p.symbol,
                "latest_tick_price": self.latest_tick_price,
                "bar_closes": [float(value) for value in self.bar_closes],
            }
        )
        return summary


class PairMixArbitrageStrategy(ConfigurableFuturesStrategyBase):
    params = BASE_FUTURES_STRATEGY_PARAMS + (
        ("symbol_a", "rb2610"),
        ("symbol_b", "hc2610"),
        ("bar_window", 3),
        ("bar_source", "bars"),
        ("bar_seconds", 1),
        ("entry_edge", 5.0),
        ("exit_edge", 1.0),
        ("order_size", 1),
        ("max_roundtrips", 1),
        ("max_bar_history", 16),
    )

    def __init__(self):
        super().__init__()
        self.latest_prices = {}
        self.bar_closes = defaultdict(
            lambda: deque(maxlen=max(int(self.p.max_bar_history), int(self.p.bar_window)))
        )
        self._observed_open_pair = False
        self._pair_open_tick_at = None
        self._forced_phase = "idle"
        self._forced_entry_terminal_refs = set()
        self._forced_exit_terminal_refs = set()
        self._tick_bar_state = {}

    def _use_tick_bars(self):
        return str(getattr(self.p, "bar_source", "bars") or "bars").strip().lower() == "ticks"

    def _tick_bucket_start(self, tick):
        tick_dt = getattr(tick, "datetime", None)
        if tick_dt is None:
            tick_dt = _dt.datetime.fromtimestamp(float(getattr(tick, "timestamp", 0.0) or 0.0))
        tick_dt = tick_dt.replace(microsecond=0)
        bar_seconds = max(int(getattr(self.p, "bar_seconds", 1) or 1), 1)
        second = (tick_dt.second // bar_seconds) * bar_seconds
        return tick_dt.replace(second=second)

    def _ingest_tick_bar(self, tick):
        symbol = str(tick.symbol)
        bucket_start = self._tick_bucket_start(tick)
        price = float(tick.price)
        current = self._tick_bar_state.get(symbol)
        if current is None:
            self._tick_bar_state[symbol] = {"bucket_start": bucket_start, "close": price}
            return
        if bucket_start == current["bucket_start"]:
            current["close"] = price
            return
        self.bar_closes[symbol].append(float(current["close"]))
        self._tick_bar_state[symbol] = {"bucket_start": bucket_start, "close": price}

    def notify_bar(self, bar):
        if self._use_tick_bars():
            return
        if bar.symbol not in (self.p.symbol_a, self.p.symbol_b):
            return
        self.bar_closes[bar.symbol].append(float(bar.close))

    def _pair_positions(self):
        pos_a = self._position_size(self.p.symbol_a)
        pos_b = self._position_size(self.p.symbol_b)
        return pos_a, pos_b

    def _pair_is_flat(self):
        pos_a, pos_b = self._pair_positions()
        return abs(pos_a) < 1e-12 and abs(pos_b) < 1e-12

    def _pair_is_open(self):
        pos_a, pos_b = self._pair_positions()
        return pos_a < -1e-12 and pos_b > 1e-12

    def _handle_forced_signals(self):
        force_entry_after_ticks = int(self.p.force_entry_after_ticks or 0)
        force_exit_after_ticks = int(self.p.force_exit_after_ticks or 0)

        if (
            self._forced_phase == "idle"
            and force_entry_after_ticks > 0
            and self._tick_count >= force_entry_after_ticks
            and len(self.latest_prices) >= 2
            and len(self.bar_closes[self.p.symbol_a]) >= int(self.p.bar_window)
            and len(self.bar_closes[self.p.symbol_b]) >= int(self.p.bar_window)
        ):
            order_a = self._submit_market(
                side="sell",
                symbol=self.p.symbol_a,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_mix_pair_open_short_a",
            )
            order_b = self._submit_market(
                side="buy",
                symbol=self.p.symbol_b,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="forced_mix_pair_open_long_b",
            )
            if order_a is not None or order_b is not None:
                self._forced_phase = "entry_submitted"
            return True

        if (
            self._forced_phase == "open"
            and force_exit_after_ticks > 0
            and self._pair_open_tick_at is not None
            and self._tick_count - int(self._pair_open_tick_at) >= force_exit_after_ticks
        ):
            pos_a, pos_b = self._pair_positions()
            order_a = self._submit_market(
                side="buy",
                symbol=self.p.symbol_a,
                size=max(abs(pos_a), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_mix_pair_close_buy_a",
            )
            order_b = self._submit_market(
                side="sell",
                symbol=self.p.symbol_b,
                size=max(abs(pos_b), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="forced_mix_pair_close_sell_b",
            )
            if order_a is not None or order_b is not None:
                self._forced_phase = "exit_submitted"
            return True

        return False

    def _fair_spread(self):
        if len(self.bar_closes[self.p.symbol_a]) < int(self.p.bar_window):
            return None
        if len(self.bar_closes[self.p.symbol_b]) < int(self.p.bar_window):
            return None

        window = int(self.p.bar_window)
        mean_a = sum(list(self.bar_closes[self.p.symbol_a])[-window:]) / float(window)
        mean_b = sum(list(self.bar_closes[self.p.symbol_b])[-window:]) / float(window)
        return mean_a - mean_b

    def notify_tick(self, tick):
        if tick.symbol not in (self.p.symbol_a, self.p.symbol_b):
            return

        self.latest_prices[tick.symbol] = float(tick.price)
        if self._use_tick_bars():
            self._ingest_tick_bar(tick)
        self.maybe_cancel_stale_orders()
        if self.maybe_stop_after_tick_limit():
            return
        if len(self.latest_prices) < 2:
            return

        if self._pair_is_open():
            self._observed_open_pair = True
            if self._pair_open_tick_at is None:
                self._pair_open_tick_at = int(self._tick_count)

        if self.forced_order_mode_enabled():
            if self.pending_refs:
                return
            self._handle_forced_signals()
            return

        fair_spread = self._fair_spread()
        if fair_spread is None:
            return

        if self._pair_is_open():
            self._observed_open_pair = True
        if self.pending_refs:
            return

        current_spread = self.latest_prices[self.p.symbol_a] - self.latest_prices[self.p.symbol_b]
        spread_edge = current_spread - fair_spread

        if (
            self._pair_is_flat()
            and (int(self.p.max_roundtrips or 0) <= 0 or self.completed_roundtrips < int(self.p.max_roundtrips))
            and spread_edge >= float(self.p.entry_edge)
        ):
            self._submit_market(
                side="sell",
                symbol=self.p.symbol_a,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="mix_pair_open_short_a",
            )
            self._submit_market(
                side="buy",
                symbol=self.p.symbol_b,
                size=self.p.order_size,
                offset=self.p.open_offset,
                signal_tag="mix_pair_open_long_b",
            )
        elif self._pair_is_open() and spread_edge <= float(self.p.exit_edge):
            pos_a, pos_b = self._pair_positions()
            self._submit_market(
                side="buy",
                symbol=self.p.symbol_a,
                size=max(abs(pos_a), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="mix_pair_close_buy_a",
            )
            self._submit_market(
                side="sell",
                symbol=self.p.symbol_b,
                size=max(abs(pos_b), float(self.p.order_size)),
                offset=self.p.close_offset,
                signal_tag="mix_pair_close_sell_b",
            )

    def after_terminal_order(self, order):
        info = getattr(order, "info", None)
        signal_tag = info.get("signal_tag", "") if hasattr(info, "get") else getattr(info, "signal_tag", "")
        if self.forced_order_mode_enabled():
            if signal_tag.startswith("forced_mix_pair_open_"):
                self._forced_entry_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "idle"
                        self._forced_entry_terminal_refs.clear()
                    elif len(self._forced_entry_terminal_refs) >= 2:
                        self._observed_open_pair = True
                        self._pair_open_tick_at = int(getattr(self, "_tick_count", 0))
                        self._forced_phase = "open"
                return

            if signal_tag.startswith("forced_mix_pair_close_"):
                self._forced_exit_terminal_refs.add(order.ref)
                if not self.pending_refs:
                    if order.status in (order.Canceled, order.Margin, order.Rejected):
                        self._forced_phase = "open"
                        self._forced_exit_terminal_refs.clear()
                    elif len(self._forced_exit_terminal_refs) >= 2:
                        self.completed_roundtrips += 1
                        self._observed_open_pair = False
                        self._pair_open_tick_at = None
                        self._forced_phase = "done"
                        self.log(f"mix pair roundtrip completed: {self.completed_roundtrips}")
                        self.stop_if_roundtrips_complete(self.p.max_roundtrips)
                return

        if self._pair_is_open():
            self._observed_open_pair = True
            if self._pair_open_tick_at is None:
                self._pair_open_tick_at = int(getattr(self, "_tick_count", 0))
            return

        if self._pair_is_flat() and self._observed_open_pair and not self.pending_refs:
            self.completed_roundtrips += 1
            self._observed_open_pair = False
            self._pair_open_tick_at = None
            self.log(f"mix pair roundtrip completed: {self.completed_roundtrips}")
            self.stop_if_roundtrips_complete(self.p.max_roundtrips)

    def get_summary(self):
        summary = super().get_summary()
        summary.update(
            {
                "symbols": [self.p.symbol_a, self.p.symbol_b],
                "latest_prices": {key: float(value) for key, value in sorted(self.latest_prices.items())},
                "bar_closes": {
                    key: [float(item) for item in value]
                    for key, value in sorted(self.bar_closes.items())
                },
            }
        )
        return summary


STRATEGIES = {
    "single_symbol": SingleSymbolMixStrategy,
    "pair_arbitrage": PairMixArbitrageStrategy,
}


def get_strategy_class(name):
    normalized = str(name or "").strip().lower()
    if normalized not in STRATEGIES:
        raise ValueError(f"Unsupported mixbroker strategy: {name}")
    return STRATEGIES[normalized]


def _parse_tick_point(raw_point, index, default_step):
    if isinstance(raw_point, (int, float)):
        return float(index) * float(default_step), float(raw_point), 1.0

    if isinstance(raw_point, dict):
        offset = float(raw_point.get("offset", index * default_step))
        price = float(raw_point["price"])
        volume = float(raw_point.get("volume", 1.0))
        return offset, price, volume

    if isinstance(raw_point, (list, tuple)):
        if len(raw_point) == 2:
            return float(raw_point[0]), float(raw_point[1]), 1.0
        if len(raw_point) >= 3:
            return float(raw_point[0]), float(raw_point[1]), float(raw_point[2])

    raise ValueError(f"Unsupported tick point: {raw_point!r}")


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


def _build_tick_events(symbol, tick_points, start_timestamp, time_step):
    events = []
    for index, raw_point in enumerate(tick_points):
        offset, price, volume = _parse_tick_point(raw_point, index, time_step)
        timestamp = float(start_timestamp) + offset
        events.append(
            TickEvent(
                timestamp=timestamp,
                symbol=str(symbol),
                exchange="SIM",
                asset_type="futures",
                local_time=timestamp,
                price=float(price),
                volume=float(volume),
                direction="buy",
                trade_id=f"{symbol}-tick-{index}",
            )
        )
    return events


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


def build_backtest_channel(config):
    scenario = dict(config.get("scenario") or {})
    scenario_type = str(scenario.get("type") or "").strip().lower()
    start_timestamp = float(scenario.get("start_timestamp", 1710000000.0))
    time_step = float(scenario.get("time_step", 1.0))

    if scenario_type == "single_symbol_mix":
        symbol = str(scenario.get("symbol") or config["strategy_params"]["symbol"])
        tick_events = _build_tick_events(symbol, scenario.get("ticks") or [], start_timestamp, time_step)
        bar_events = _build_bar_events(symbol, scenario.get("bars") or [], start_timestamp)
        return MixedChannel(
            tick_channels=[MemoryChannel("tick", symbol, tick_events)],
            bars=[bar_events],
            adaptive=False,
            preload_window=1.0,
        )

    if scenario_type == "pair_mix":
        tick_map = dict(scenario.get("ticks") or {})
        bar_map = dict(scenario.get("bars") or {})
        tick_channels = []
        bars = []
        for symbol, points in tick_map.items():
            tick_channels.append(
                MemoryChannel("tick", symbol, _build_tick_events(symbol, points, start_timestamp, time_step))
            )
        for symbol, points in bar_map.items():
            bars.append(_build_bar_events(symbol, points, start_timestamp))
        return MixedChannel(
            tick_channels=tick_channels,
            bars=bars,
            adaptive=False,
            preload_window=1.0,
        )

    raise ValueError(f"Unsupported mixbroker scenario: {scenario_type}")


def format_summary(strategy):
    return json.dumps(strategy.get_summary(), ensure_ascii=False, indent=2, sort_keys=True)
