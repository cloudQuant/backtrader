"""Example HFT quote-builder strategies and input requirements.

Provides sample market-making/quoting components (e.g. a GLFT-style quote
builder) and the :class:`InputRequirement` descriptors that document the data
inputs each example needs. Reference material, not part of the core engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class InputRequirement:
    name: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class StrategyConfig:
    builder: str
    parameters: dict[str, float]
    interval_ns: int
    recorder_capacity: int
    expected_metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class HFTExampleSpec:
    name: str
    source_notebook: str
    symbol: str
    input_requirements: tuple[InputRequirement, ...]
    asset_parameters: dict[str, object]
    strategy: StrategyConfig
    demo_supported: bool = False


def _as_tuple(value):
    if isinstance(value, tuple):
        return value
    return tuple(value)


def _context_value(context, name, default=None):
    if context is None:
        return default
    if isinstance(context, dict):
        return context.get(name, default)
    return getattr(context, name, default)


def _measure_trading_intensity(order_arrival_depth, scale=0.5, size=500):
    out = [0.0] * int(size)
    max_tick = 0
    for depth in order_arrival_depth:
        if not math.isfinite(depth):
            continue
        tick = round(float(depth) / float(scale)) - 1
        if tick < 0 or tick >= len(out):
            continue
        for index in range(tick):
            out[index] += 1.0
        max_tick = max(max_tick, tick)
    return out[:max_tick]


def _linear_regression(x_values, y_values):
    if len(x_values) != len(y_values) or len(x_values) < 2:
        return math.nan, math.nan
    sx = sum(float(value) for value in x_values)
    sy = sum(float(value) for value in y_values)
    sx2 = sum(float(value) ** 2 for value in x_values)
    sxy = sum(float(x) * float(y) for x, y in zip(x_values, y_values))
    weight = float(len(x_values))
    denominator = weight * sx2 - sx**2
    if abs(denominator) <= 1e-12:
        return math.nan, math.nan
    slope = (weight * sxy - sx * sy) / denominator
    intercept = (sy - slope * sx) / weight
    return slope, intercept


def _compute_coeff(xi, gamma, delta, intensity_a, intensity_k):
    if not all(math.isfinite(value) for value in (xi, gamma, delta, intensity_a, intensity_k)):
        return math.nan, math.nan
    if delta <= 0.0 or intensity_a <= 0.0 or intensity_k <= 0.0:
        return math.nan, math.nan
    inv_k = 1.0 / intensity_k
    c1 = 1.0 / (xi * delta) * math.log(1.0 + xi * delta * inv_k)
    c2 = math.sqrt(
        gamma
        / (2.0 * intensity_a * delta * intensity_k)
        * ((1.0 + xi * delta * inv_k) ** (intensity_k / (xi * delta) + 1.0))
    )
    return c1, c2


class PlainGridQuoteBuilder:
    def __init__(
        self,
        tick_size=1.0,
        grid_num=20,
        max_position=5.0,
        grid_interval=10.0,
        half_spread=20.0,
        skew=0.0,
        order_qty=0.1,
    ):
        self.tick_size = tick_size
        self.grid_num = int(grid_num)
        self.max_position = float(max_position)
        self.grid_interval = float(grid_interval)
        self.half_spread = float(half_spread)
        self.skew = float(skew)
        self.order_qty = float(order_qty)
        self.current_order_qty = float(order_qty)

    def __call__(self, position, snapshot, context=None):
        self.current_order_qty = self.order_qty
        best_bid = snapshot.bids[0][0]
        best_ask = snapshot.asks[0][0]
        mid_price = (best_bid + best_ask) / 2.0
        normalized_position = 0.0 if self.order_qty == 0.0 else position / self.order_qty
        reservation_price = mid_price - self.skew * normalized_position
        bid_price = min(reservation_price - self.half_spread, best_bid)
        ask_price = max(reservation_price + self.half_spread, best_ask)
        bid_price = (bid_price // self.grid_interval) * self.grid_interval
        ask_price = (-(-ask_price // self.grid_interval)) * self.grid_interval

        quotes = {}
        if position < self.max_position:
            quotes["buy"] = [
                float(bid_price - i * self.grid_interval) for i in range(self.grid_num)
            ]
        if position > -self.max_position:
            quotes["sell"] = [
                float(ask_price + i * self.grid_interval) for i in range(self.grid_num)
            ]
        return quotes


class QueueMarketMakingQuoteBuilder:
    def __init__(
        self,
        tick_size=1.0,
        order_qty=1.0,
        grid_num=10,
        max_position=10.0,
        half_spread=0.49,
        grid_interval=1.0,
        skew_adj=1.0,
    ):
        self.tick_size = float(tick_size)
        self.order_qty = float(order_qty)
        self.grid_num = int(grid_num)
        self.max_position = float(max_position)
        self.half_spread = float(half_spread)
        self.grid_interval = float(grid_interval)
        self.skew_adj = float(skew_adj)
        self.current_order_qty = float(order_qty)

    def __call__(self, position, snapshot, context=None):
        self.current_order_qty = self.order_qty
        best_bid = snapshot.bids[0][0]
        best_ask = snapshot.asks[0][0]
        best_bid_qty = snapshot.bids[0][1]
        best_ask_qty = snapshot.asks[0][1]
        book_pressure = (best_bid * best_ask_qty + best_ask * best_bid_qty) / (
            best_bid_qty + best_ask_qty
        )
        skew = self.half_spread / self.grid_num * self.skew_adj
        normalized_position = 0.0 if self.order_qty == 0.0 else position / self.order_qty
        reservation_price = book_pressure - skew * normalized_position
        bid_price = min(reservation_price - self.half_spread, best_bid)
        ask_price = max(reservation_price + self.half_spread, best_ask)
        bid_price = float((bid_price // self.grid_interval) * self.grid_interval)
        ask_price = float(((-(-ask_price // self.grid_interval))) * self.grid_interval)

        quotes = {}
        if position < self.max_position:
            quotes["buy"] = [
                float(bid_price - i * self.grid_interval) for i in range(self.grid_num)
            ]
        if position > -self.max_position:
            quotes["sell"] = [
                float(ask_price + i * self.grid_interval) for i in range(self.grid_num)
            ]
        return quotes


class OBIAlphaQuoteBuilder:
    def __init__(
        self,
        tick_size=1.0,
        depth_levels=2,
        half_spread=1.0,
        skew=0.5,
        c1=1.0,
        order_qty=1.0,
        max_position=1.0,
        window=3,
        grid_num=1,
        grid_interval=None,
    ):
        self.tick_size = float(tick_size)
        self.depth_levels = int(depth_levels)
        self.half_spread = float(half_spread)
        self.skew = float(skew)
        self.c1 = float(c1)
        self.order_qty = float(order_qty)
        self.max_position = float(max_position)
        self.window = int(window)
        self.grid_num = int(grid_num)
        self.grid_interval = float(grid_interval if grid_interval is not None else tick_size)
        self.imbalance_history = []
        self.current_order_qty = float(order_qty)

    def __call__(self, position, snapshot, context=None):
        self.current_order_qty = self.order_qty
        best_bid = snapshot.bids[0][0]
        best_ask = snapshot.asks[0][0]
        mid_price = (best_bid + best_ask) / 2.0
        sum_bid_qty = sum(level[1] for level in snapshot.bids[: self.depth_levels])
        sum_ask_qty = sum(level[1] for level in snapshot.asks[: self.depth_levels])
        imbalance = sum_bid_qty - sum_ask_qty
        self.imbalance_history.append(imbalance)

        window_values = self.imbalance_history[-self.window :]
        mean_value = sum(window_values) / len(window_values)
        variance = sum((value - mean_value) ** 2 for value in window_values) / len(window_values)
        std_value = variance**0.5
        alpha = 0.0 if std_value == 0.0 else (imbalance - mean_value) / std_value

        fair_price = mid_price + self.c1 * alpha
        normalized_position = 0.0 if self.order_qty == 0.0 else position / self.order_qty
        reservation_price = fair_price - self.skew * normalized_position
        bid_price = min(round(reservation_price - self.half_spread), best_bid)
        ask_price = max(round(reservation_price + self.half_spread), best_ask)
        bid_price = float((bid_price // self.grid_interval) * self.grid_interval)
        ask_price = float(((-(-ask_price // self.grid_interval))) * self.grid_interval)

        quotes = {}
        if position < self.max_position:
            quotes["buy"] = [
                float(bid_price - i * self.grid_interval) for i in range(self.grid_num)
            ]
        if position > -self.max_position:
            quotes["sell"] = [
                float(ask_price + i * self.grid_interval) for i in range(self.grid_num)
            ]
        return quotes


class BasisAlphaQuoteBuilder:
    def __init__(
        self,
        tick_size=0.1,
        lot_size=0.001,
        half_spread=0.0003,
        skew=0.000015,
        order_qty_dollar=50_000.0,
        max_position_dollar=1_000_000.0,
        grid_num=1,
        grid_interval=0.1,
        precompute_data=None,
    ):
        self.tick_size = float(tick_size)
        self.lot_size = float(lot_size)
        self.half_spread = float(half_spread)
        self.skew = float(skew)
        self.order_qty_dollar = float(order_qty_dollar)
        self.max_position_dollar = float(max_position_dollar)
        self.grid_num = int(grid_num)
        self.grid_interval = float(grid_interval)
        self.precompute_data = precompute_data
        self.data_index = 0
        self.last_spot = math.nan
        self.last_basis = math.nan
        self.order_qty = float(lot_size)
        self.current_order_qty = float(lot_size)

    def _advance(self, timestamp_ns):
        if self.precompute_data is None or timestamp_ns is None:
            return
        while self.data_index < len(self.precompute_data):
            if float(self.precompute_data[self.data_index][0]) > float(timestamp_ns):
                if self.data_index > 0:
                    self.last_spot = float(self.precompute_data[self.data_index - 1][1])
                    self.last_basis = float(self.precompute_data[self.data_index - 1][2])
                return
            self.data_index += 1
        if len(self.precompute_data) > 0:
            self.last_spot = float(self.precompute_data[-1][1])
            self.last_basis = float(self.precompute_data[-1][2])

    def __call__(self, position, snapshot, context=None):
        best_bid = float(snapshot.bids[0][0])
        best_ask = float(snapshot.asks[0][0])
        mid_price = (best_bid + best_ask) / 2.0
        self.current_order_qty = max(
            round((self.order_qty_dollar / mid_price) / self.lot_size) * self.lot_size,
            self.lot_size,
        )
        self.order_qty = self.current_order_qty
        normalized_position = position / self.current_order_qty if self.current_order_qty else 0.0
        self._advance(_context_value(context, "timestamp_ns"))
        fair_price = (
            self.last_spot + self.last_basis
            if math.isfinite(self.last_spot) and math.isfinite(self.last_basis)
            else mid_price
        )
        relative_bid_depth = self.half_spread + self.skew * normalized_position
        relative_ask_depth = self.half_spread - self.skew * normalized_position
        bid_price = min(fair_price * (1.0 - relative_bid_depth), best_bid)
        ask_price = max(fair_price * (1.0 + relative_ask_depth), best_ask)
        bid_price = math.floor(bid_price / self.tick_size) * self.tick_size
        ask_price = math.ceil(ask_price / self.tick_size) * self.tick_size
        quotes = {}
        if position * mid_price < self.max_position_dollar and math.isfinite(bid_price):
            quotes["buy"] = [
                float(bid_price - i * self.grid_interval) for i in range(self.grid_num)
            ]
        if position * mid_price > -self.max_position_dollar and math.isfinite(ask_price):
            quotes["sell"] = [
                float(ask_price + i * self.grid_interval) for i in range(self.grid_num)
            ]
        return quotes


class APTQuoteBuilder:
    def __init__(
        self,
        tick_size=0.1,
        lot_size=0.001,
        half_spread=0.0003,
        skew=0.000015,
        order_qty_dollar=50_000.0,
        max_position_dollar=1_000_000.0,
        grid_num=1,
        grid_interval=0.1,
        precompute_data=None,
    ):
        self.tick_size = float(tick_size)
        self.lot_size = float(lot_size)
        self.half_spread = float(half_spread)
        self.skew = float(skew)
        self.order_qty_dollar = float(order_qty_dollar)
        self.max_position_dollar = float(max_position_dollar)
        self.grid_num = int(grid_num)
        self.grid_interval = float(grid_interval)
        self.precompute_data = precompute_data
        self.data_index = 0
        self.spot_return = math.nan
        self.futures_past_px = math.nan
        self.order_qty = float(lot_size)
        self.current_order_qty = float(lot_size)

    def _advance(self, timestamp_ns):
        if self.precompute_data is None or timestamp_ns is None:
            return
        while self.data_index < len(self.precompute_data):
            if float(self.precompute_data[self.data_index][0]) > float(timestamp_ns):
                if self.data_index > 0:
                    self.spot_return = float(self.precompute_data[self.data_index - 1][1])
                    self.futures_past_px = float(self.precompute_data[self.data_index - 1][4])
                return
            self.data_index += 1
        if len(self.precompute_data) > 0:
            self.spot_return = float(self.precompute_data[-1][1])
            self.futures_past_px = float(self.precompute_data[-1][4])

    def __call__(self, position, snapshot, context=None):
        best_bid = float(snapshot.bids[0][0])
        best_ask = float(snapshot.asks[0][0])
        mid_price = (best_bid + best_ask) / 2.0
        self.current_order_qty = max(
            round((self.order_qty_dollar / mid_price) / self.lot_size) * self.lot_size,
            self.lot_size,
        )
        self.order_qty = self.current_order_qty
        normalized_position = position / self.current_order_qty if self.current_order_qty else 0.0
        self._advance(_context_value(context, "timestamp_ns"))
        return_ = self.spot_return if math.isfinite(self.spot_return) else 0.0
        fair_price = (
            (1.0 + return_) * self.futures_past_px
            if math.isfinite(self.futures_past_px)
            else mid_price
        )
        relative_bid_depth = self.half_spread + self.skew * normalized_position
        relative_ask_depth = self.half_spread - self.skew * normalized_position
        bid_price = min(fair_price * (1.0 - relative_bid_depth), best_bid)
        ask_price = max(fair_price * (1.0 + relative_ask_depth), best_ask)
        bid_price = math.floor(bid_price / self.tick_size) * self.tick_size
        ask_price = math.ceil(ask_price / self.tick_size) * self.tick_size
        dynamic_grid_interval = max(
            self.tick_size, round(self.grid_interval * fair_price / self.tick_size) * self.tick_size
        )
        bid_price = math.floor(bid_price / dynamic_grid_interval) * dynamic_grid_interval
        ask_price = math.ceil(ask_price / dynamic_grid_interval) * dynamic_grid_interval
        quotes = {}
        if position * mid_price < self.max_position_dollar and math.isfinite(bid_price):
            quotes["buy"] = [
                float(bid_price - i * dynamic_grid_interval) for i in range(self.grid_num)
            ]
        if position * mid_price > -self.max_position_dollar and math.isfinite(ask_price):
            quotes["sell"] = [
                float(ask_price + i * dynamic_grid_interval) for i in range(self.grid_num)
            ]
        return quotes


class GLFTQuoteBuilder:
    def __init__(
        self,
        tick_size=0.01,
        lot_size=0.001,
        gamma=0.05,
        delta=1.0,
        order_qty=1.0,
        max_position=20.0,
        grid_num=1,
        grid_interval=None,
    ):
        self.tick_size = float(tick_size)
        self.lot_size = float(lot_size)
        self.gamma = float(gamma)
        self.delta = float(delta)
        self.order_qty = float(order_qty)
        self.current_order_qty = float(order_qty)
        self.max_position = float(max_position)
        self.grid_num = int(grid_num)
        self.grid_interval = float(grid_interval if grid_interval is not None else tick_size)
        self.arrival_depth_history = []
        self.mid_price_chg_history = []
        self.mid_price_tick = math.nan
        self.intensity_a = math.nan
        self.intensity_k = math.nan
        self.volatility = math.nan
        self.step = 0

    def __call__(self, position, snapshot, context=None):
        last_trades = _context_value(context, "last_trades", ()) or ()
        if math.isfinite(self.mid_price_tick):
            arrival_depth = -math.inf
            for trade in last_trades:
                trade_price = float(getattr(trade, "price", getattr(trade, "px", math.nan)))
                trade_direction = str(getattr(trade, "direction", "")).lower()
                if not math.isfinite(trade_price):
                    continue
                trade_tick = trade_price / self.tick_size
                if trade_direction == "buy":
                    arrival_depth = max(trade_tick - self.mid_price_tick, arrival_depth)
                else:
                    arrival_depth = max(self.mid_price_tick - trade_tick, arrival_depth)
            self.arrival_depth_history.append(arrival_depth)
        else:
            self.arrival_depth_history.append(math.nan)

        best_bid_tick = float(snapshot.bids[0][0]) / self.tick_size
        best_ask_tick = float(snapshot.asks[0][0]) / self.tick_size
        previous_mid_price_tick = self.mid_price_tick
        self.mid_price_tick = (best_bid_tick + best_ask_tick) / 2.0
        self.mid_price_chg_history.append(
            self.mid_price_tick - previous_mid_price_tick
            if math.isfinite(previous_mid_price_tick)
            else math.nan
        )

        if self.step % 50 == 0 and self.step >= 5_999:
            intensity_window = _measure_trading_intensity(self.arrival_depth_history[-6_000:])
            if len(intensity_window) > 2:
                x_values = []
                y_values = []
                for index, value in enumerate(intensity_window[:70]):
                    rate = float(value) / 600.0
                    if rate <= 0.0:
                        continue
                    x_values.append(index + 0.5)
                    y_values.append(math.log(rate))
                slope, intercept = _linear_regression(x_values, y_values)
                if math.isfinite(slope) and math.isfinite(intercept):
                    self.intensity_a = math.exp(intercept)
                    self.intensity_k = -slope
            window = [
                value for value in self.mid_price_chg_history[-6_000:] if math.isfinite(value)
            ]
            if window:
                mean_value = sum(window) / len(window)
                variance = sum((value - mean_value) ** 2 for value in window) / len(window)
                self.volatility = math.sqrt(variance) * math.sqrt(10.0)

        c1, c2 = _compute_coeff(
            self.gamma, self.gamma, self.delta, self.intensity_a, self.intensity_k
        )
        half_spread_tick = (
            c1 + self.delta / 2.0 * c2 * self.volatility
            if all(math.isfinite(value) for value in (c1, c2, self.volatility))
            else 0.0
        )
        skew = (
            c2 * self.volatility
            if all(math.isfinite(value) for value in (c2, self.volatility))
            else 0.0
        )
        reservation_price_tick = self.mid_price_tick - skew * position
        bid_price_tick = min(round(reservation_price_tick - half_spread_tick), round(best_bid_tick))
        ask_price_tick = max(round(reservation_price_tick + half_spread_tick), round(best_ask_tick))
        bid_price = bid_price_tick * self.tick_size
        ask_price = ask_price_tick * self.tick_size
        self.step += 1
        quotes = {}
        if position < self.max_position and math.isfinite(bid_price):
            quotes["buy"] = [
                float(bid_price - i * self.grid_interval) for i in range(self.grid_num)
            ]
        if position > -self.max_position and math.isfinite(ask_price):
            quotes["sell"] = [
                float(ask_price + i * self.grid_interval) for i in range(self.grid_num)
            ]
        return quotes


def get_hftbacktest_example_specs():
    return [
        HFTExampleSpec(
            name="plain_grid",
            source_notebook="High-Frequency Grid Trading.ipynb",
            symbol="ETHUSDT",
            demo_supported=True,
            input_requirements=(
                InputRequirement(
                    name="market_data",
                    patterns=(
                        "data/ethusdt_20221003.npz",
                        "data/ethusdt_20221004.npz",
                        "data/ethusdt_20221005.npz",
                        "data/ethusdt_20221006.npz",
                        "data/ethusdt_20221007.npz",
                    ),
                ),
                InputRequirement(
                    name="initial_snapshot", patterns=("data/ethusdt_20221002_eod.npz",)
                ),
                InputRequirement(
                    name="latency_data",
                    patterns=(
                        "latency/feed_latency_20221003.npz",
                        "latency/feed_latency_20221004.npz",
                        "latency/feed_latency_20221005.npz",
                        "latency/feed_latency_20221006.npz",
                        "latency/feed_latency_20221007.npz",
                    ),
                ),
            ),
            asset_parameters={
                "asset_type": "linear",
                "mult": 1.0,
                "tick_size": 0.01,
                "lot_size": 0.001,
                "roi_lb": 0.0,
                "roi_ub": 3000.0,
                "queue_model": "power_prob_queue_model",
                "queue_model_power": 2.0,
                "exchange_model": "no_partial_fill_exchange",
                "maker_commission": -0.00005,
                "taker_commission": 0.0007,
            },
            strategy=StrategyConfig(
                builder="PlainGridQuoteBuilder",
                interval_ns=100_000_000,
                recorder_capacity=5_000_000,
                parameters={
                    "grid_num": 20,
                    "max_position": 5.0,
                    "grid_interval": 0.1,
                    "half_spread": 0.2,
                    "skew": 0.0,
                    "order_qty": 0.1,
                },
            ),
        ),
        HFTExampleSpec(
            name="queue_market_making",
            source_notebook="Queue-Based Market Making in Large Tick Size Assets.ipynb",
            symbol="CRVUSDT",
            demo_supported=True,
            input_requirements=(
                InputRequirement(
                    name="market_data",
                    patterns=_as_tuple(
                        [
                            f"data/CRVUSDT_{date}.npz"
                            for date in list(range(20240701, 20240732))
                            + list(range(20240801, 20240832))
                        ]
                    ),
                ),
                InputRequirement(
                    name="latency_data",
                    patterns=_as_tuple(
                        [
                            f"latency/amp_feed_latency_{date}.npz"
                            for date in list(range(20240701, 20240732))
                            + list(range(20240801, 20240832))
                        ]
                    ),
                ),
            ),
            asset_parameters={
                "asset_type": "linear",
                "mult": 1.0,
                "tick_size": 0.001,
                "lot_size": 0.1,
                "roi_lb": 0.0,
                "roi_ub": 2.0,
                "queue_model": "power_prob_queue_model",
                "queue_model_power": 3.0,
                "exchange_model": "no_partial_fill_exchange",
                "maker_commission": -0.00005,
                "taker_commission": 0.0007,
                "last_trades_capacity": 1000,
            },
            strategy=StrategyConfig(
                builder="QueueMarketMakingQuoteBuilder",
                interval_ns=100_000_000,
                recorder_capacity=100_000_000,
                parameters={
                    "order_qty": 1.0,
                    "grid_num": 10,
                    "max_position": 10.0,
                    "half_spread": 0.00049,
                    "grid_interval": 0.001,
                    "skew_adj": 1.0,
                },
                expected_metrics={
                    "Return": 2.848749,
                    "MaxDrawdown": 0.096359,
                    "DailyNumberOfTrades": 106.774393,
                    "DailyTradingValue": 30.241524,
                },
            ),
        ),
        HFTExampleSpec(
            name="obi_alpha_market_making",
            source_notebook="Market Making with Alpha - Order Book Imbalance.ipynb",
            symbol="BTCUSDT",
            demo_supported=True,
            input_requirements=(
                InputRequirement(
                    name="market_data",
                    patterns=_as_tuple(
                        [f"data2/btcusdt_{date}.npz" for date in range(20230501, 20230532)]
                    ),
                ),
                InputRequirement(
                    name="initial_snapshot", patterns=("data2/btcusdt_20230430_eod.npz",)
                ),
                InputRequirement(
                    name="latency_data",
                    patterns=_as_tuple(
                        [
                            f"latency/live_order_latency_{date}.npz"
                            for date in range(20230501, 20230532)
                        ]
                    ),
                ),
            ),
            asset_parameters={
                "asset_type": "linear",
                "mult": 1.0,
                "tick_size": 0.1,
                "lot_size": 0.001,
                "roi_lb": 10000.0,
                "roi_ub": 50000.0,
                "queue_model": "power_prob_queue_model",
                "queue_model_power": 2.0,
                "exchange_model": "no_partial_fill_exchange",
                "maker_commission": -0.00005,
                "taker_commission": 0.0007,
            },
            strategy=StrategyConfig(
                builder="OBIAlphaQuoteBuilder",
                interval_ns=1_000_000_000,
                recorder_capacity=30_000_000,
                parameters={
                    "tick_size": 0.1,
                    "depth_levels": 2,
                    "half_spread": 80.0,
                    "skew": 3.5,
                    "c1": 160.0,
                    "order_qty": 0.001,
                    "max_position": 50.0,
                    "window": 3600,
                    "grid_num": 1,
                    "grid_interval": 0.1,
                },
                expected_metrics={
                    "Return": 0.342371,
                    "MaxDrawdown": 0.037249,
                    "DailyNumberOfTrades": 4119.876838,
                    "DailyTurnover": 82.397448,
                },
            ),
        ),
        HFTExampleSpec(
            name="basis_alpha_market_making",
            source_notebook="Market Making with Alpha - Basis.ipynb",
            symbol="BTCUSDT",
            input_requirements=(
                InputRequirement(
                    name="market_data",
                    patterns=_as_tuple(
                        [
                            f"data2/btcusdt_{date}.npz"
                            for date in list(range(20240901, 20240931))
                            + list(range(20241001, 20241032))
                        ]
                    ),
                ),
                InputRequirement(
                    name="initial_snapshot", patterns=("data2/btcusdt_20240831_eod.npz",)
                ),
                InputRequirement(
                    name="latency_data",
                    patterns=_as_tuple(
                        [
                            f"latency/order_latency_{date}.npz"
                            for date in list(range(20240901, 20240931))
                            + list(range(20241001, 20241032))
                        ]
                    ),
                ),
                InputRequirement(name="precompute_data", patterns=("px_basis_BTCUSDT_5m.npz",)),
            ),
            asset_parameters={
                "asset_type": "linear",
                "mult": 1.0,
                "tick_size": 0.1,
                "lot_size": 0.001,
                "roi_lb": 10000.0,
                "roi_ub": 90000.0,
                "queue_model": "power_prob_queue_model",
                "queue_model_power": 3.0,
                "exchange_model": "no_partial_fill_exchange",
                "maker_commission": -0.00005,
                "taker_commission": 0.0007,
            },
            strategy=StrategyConfig(
                builder="BasisAlphaQuoteBuilder",
                interval_ns=100_000_000,
                recorder_capacity=60_000_000,
                parameters={
                    "tick_size": 0.1,
                    "lot_size": 0.001,
                    "half_spread": 0.0003,
                    "skew": 0.000015,
                    "order_qty_dollar": 50_000.0,
                    "max_position_dollar": 1_000_000.0,
                    "grid_num": 1,
                    "grid_interval": 0.1,
                },
            ),
        ),
        HFTExampleSpec(
            name="apt_alpha_market_making",
            source_notebook="Market Making with Alpha - APT.ipynb",
            symbol="BTCUSDT",
            input_requirements=(
                InputRequirement(
                    name="market_data",
                    patterns=_as_tuple(
                        [
                            f"data2/btcusdt_{date}.npz"
                            for date in list(range(20240901, 20240931))
                            + list(range(20241001, 20241032))
                        ]
                    ),
                ),
                InputRequirement(
                    name="initial_snapshot", patterns=("data2/btcusdt_20240831_eod.npz",)
                ),
                InputRequirement(
                    name="latency_data",
                    patterns=_as_tuple(
                        [
                            f"latency/order_latency_{date}.npz"
                            for date in list(range(20240901, 20240931))
                            + list(range(20241001, 20241032))
                        ]
                    ),
                ),
                InputRequirement(
                    name="precompute_data", patterns=("precompute_px_return_BTCUSDT_5m.npz",)
                ),
            ),
            asset_parameters={
                "asset_type": "linear",
                "mult": 1.0,
                "tick_size": 0.1,
                "lot_size": 0.001,
                "roi_lb": 10000.0,
                "roi_ub": 90000.0,
                "queue_model": "power_prob_queue_model",
                "queue_model_power": 3.0,
                "exchange_model": "no_partial_fill_exchange",
                "maker_commission": -0.00005,
                "taker_commission": 0.0007,
            },
            strategy=StrategyConfig(
                builder="APTQuoteBuilder",
                interval_ns=100_000_000,
                recorder_capacity=60_000_000,
                parameters={
                    "tick_size": 0.1,
                    "lot_size": 0.001,
                    "half_spread": 0.0003,
                    "skew": 0.000015,
                    "order_qty_dollar": 50_000.0,
                    "max_position_dollar": 1_000_000.0,
                    "grid_num": 1,
                    "grid_interval": 0.1,
                },
            ),
        ),
        HFTExampleSpec(
            name="glft_market_making",
            source_notebook="GLFT Market Making Model and Grid Trading.ipynb",
            symbol="ETHUSDT",
            input_requirements=(
                InputRequirement(name="market_data", patterns=("data/ethusdt_20221003.npz",)),
                InputRequirement(
                    name="initial_snapshot", patterns=("data/ethusdt_20221002_eod.npz",)
                ),
                InputRequirement(
                    name="latency_data", patterns=("latency/feed_latency_20221003.npz",)
                ),
            ),
            asset_parameters={
                "asset_type": "linear",
                "mult": 1.0,
                "tick_size": 0.01,
                "lot_size": 0.001,
                "roi_lb": 0.0,
                "roi_ub": 3000.0,
                "queue_model": "power_prob_queue_model",
                "queue_model_power": 2.0,
                "exchange_model": "no_partial_fill_exchange",
                "maker_commission": -0.00005,
                "taker_commission": 0.0007,
                "last_trades_capacity": 10000,
            },
            strategy=StrategyConfig(
                builder="GLFTQuoteBuilder",
                interval_ns=100_000_000,
                recorder_capacity=5_000_000,
                parameters={
                    "tick_size": 0.01,
                    "lot_size": 0.001,
                    "gamma": 0.05,
                    "delta": 1.0,
                    "order_qty": 1.0,
                    "max_position": 20.0,
                    "grid_num": 1,
                    "grid_interval": 0.01,
                },
            ),
        ),
    ]


def get_hftbacktest_example_spec(name):
    return next(spec for spec in get_hftbacktest_example_specs() if spec.name == name)


def get_hftbacktest_demo_example_specs():
    return tuple(spec for spec in get_hftbacktest_example_specs() if spec.demo_supported)


def build_input_manifest(spec, base_path):
    base = Path(base_path)
    resolved = {}
    missing = {}
    for requirement in spec.input_requirements:
        resolved_paths = []
        missing_patterns = []
        for pattern in requirement.patterns:
            matches = sorted(str(path) for path in base.glob(pattern))
            if matches:
                resolved_paths.extend(matches)
            else:
                missing_patterns.append(pattern)
        resolved[requirement.name] = tuple(resolved_paths)
        if missing_patterns:
            missing[requirement.name] = tuple(missing_patterns)
    return {
        "ready": not missing,
        "resolved": resolved,
        "missing": missing,
    }


def build_quote_builder(spec):
    mapping = {
        "PlainGridQuoteBuilder": PlainGridQuoteBuilder,
        "QueueMarketMakingQuoteBuilder": QueueMarketMakingQuoteBuilder,
        "OBIAlphaQuoteBuilder": OBIAlphaQuoteBuilder,
        "BasisAlphaQuoteBuilder": BasisAlphaQuoteBuilder,
        "APTQuoteBuilder": APTQuoteBuilder,
        "GLFTQuoteBuilder": GLFTQuoteBuilder,
    }
    builder_cls = mapping[spec.strategy.builder]
    return builder_cls(**spec.strategy.parameters)
