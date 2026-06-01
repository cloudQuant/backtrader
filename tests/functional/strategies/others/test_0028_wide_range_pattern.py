"""Inlined regression test for others/0028_wide_range_pattern.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
from backtrader.utils.load_data import load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"


def prepare_wide_range_pattern_features(df, params):
    """Build wide-range breakout features including direction, days-since and signal flags."""
    range_period = int(params.get("range_period", 14))
    wide_threshold = float(params.get("wide_threshold", 1.8))
    wait_days_min = int(params.get("wait_days_min", 1))
    wait_days_max = int(params.get("wait_days_max", 7))

    out = df.copy()
    out["range"] = out["high"] - out["low"]
    out["avg_range"] = out["range"].rolling(range_period).mean()
    out["is_wide_range"] = (out["range"] > out["avg_range"] * wide_threshold).astype(float)
    out["wide_direction"] = 0.0
    out.loc[(out["is_wide_range"] > 0) & (out["close"] > out["open"]), "wide_direction"] = 1.0
    out.loc[(out["is_wide_range"] > 0) & (out["close"] <= out["open"]), "wide_direction"] = -1.0

    wide_index = []
    wide_high = []
    wide_low = []
    days_since_wide = []
    breakout_signal = []
    breakout_direction = []

    last_wide_bar = None
    last_wide_high = None
    last_wide_low = None
    last_wide_direction = 0.0

    for i, (_, row) in enumerate(out.iterrows()):
        if float(row["is_wide_range"]) > 0.5:
            last_wide_bar = i
            last_wide_high = float(row["high"])
            last_wide_low = float(row["low"])
            last_wide_direction = float(row["wide_direction"])
            wide_index.append(float(i))
            wide_high.append(last_wide_high)
            wide_low.append(last_wide_low)
            days_since_wide.append(0.0)
            breakout_signal.append(0.0)
            breakout_direction.append(0.0)
            continue

        if last_wide_bar is None:
            wide_index.append(float("nan"))
            wide_high.append(float("nan"))
            wide_low.append(float("nan"))
            days_since_wide.append(float("nan"))
            breakout_signal.append(0.0)
            breakout_direction.append(0.0)
            continue

        since = i - last_wide_bar
        wide_index.append(float(last_wide_bar))
        wide_high.append(last_wide_high)
        wide_low.append(last_wide_low)
        days_since_wide.append(float(since))

        can_trade = wait_days_min <= since <= wait_days_max
        signal = 0.0
        direction = 0.0
        if can_trade and last_wide_direction > 0 and float(row["close"]) > float(last_wide_high):
            signal = 1.0
            direction = 1.0
        elif can_trade and last_wide_direction < 0 and float(row["close"]) < float(last_wide_low):
            signal = 1.0
            direction = -1.0
        breakout_signal.append(signal)
        breakout_direction.append(direction)

    out["wide_index"] = wide_index
    out["wide_high"] = wide_high
    out["wide_low"] = wide_low
    out["days_since_wide"] = days_since_wide
    out["breakout_signal"] = breakout_signal
    out["breakout_direction"] = breakout_direction
    out = out[[
        "open", "high", "low", "close", "volume", "openinterest",
        "range", "avg_range", "is_wide_range", "wide_direction",
        "wide_high", "wide_low", "days_since_wide", "breakout_signal", "breakout_direction",
    ]].copy()
    return out.dropna()


class Mt5WideRangePatternFeed(bt.feeds.PandasData):
    """PandasData feed with custom wide-range pattern feature columns."""
    lines = (
        "range", "avg_range", "is_wide_range", "wide_direction",
        "wide_high", "wide_low", "days_since_wide", "breakout_signal", "breakout_direction",
    )
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("range", 6), ("avg_range", 7), ("is_wide_range", 8), ("wide_direction", 9),
        ("wide_high", 10), ("wide_low", 11), ("days_since_wide", 12), ("breakout_signal", 13), ("breakout_direction", 14),
    )


class WideRangePatternStrategy(bt.Strategy):
    """Simple wide-range breakout strategy with directional entries and fixed risk targets."""
    params = dict(
        take_profit_ratio=2.5,
        max_holding_days=10,
        position_size=0.95,
        range_period=14,
        wide_threshold=1.8,
        wait_days_min=1,
        wait_days_max=7,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize signal counters, risk state, and running position metadata."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.trade_direction = 0

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, "mult", 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        direction = 1.0 if target_notional_pct >= 0 else -1.0
        size = broker_value * abs(float(target_notional_pct)) / (execution_price * multiplier)
        return direction * round(size, 2)

    def next(self):
        """Evaluate stop/target exits, holding duration, and open/close orders each bar."""
        self.bar_num += 1
        if self.pending_order is not None:
            return

        low = float(self.data.low[0])
        high = float(self.data.high[0])
        close = float(self.data.close[0])

        if self.position:
            if self.trade_direction > 0:
                if self.stop_price is not None and low <= self.stop_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and high >= self.take_profit_price:
                    self.sell_count += 1
                    self.pending_order = self.close()
                    return
            elif self.trade_direction < 0:
                if self.stop_price is not None and high >= self.stop_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
                if self.take_profit_price is not None and low <= self.take_profit_price:
                    self.buy_count += 1
                    self.pending_order = self.close()
                    return
            if self.bar_num - self.entry_bar >= int(self.p.max_holding_days):
                if self.trade_direction > 0:
                    self.sell_count += 1
                else:
                    self.buy_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.breakout_signal[0]) > 0.5:
            direction = int(float(self.data.breakout_direction[0]))
            wide_high = float(self.data.wide_high[0])
            wide_low = float(self.data.wide_low[0])
            self.entry_bar = self.bar_num
            self.entry_price = close
            self.trade_direction = direction
            if direction > 0:
                risk = max(close - wide_low, close * 0.005)
                self.stop_price = wide_low
                self.take_profit_price = close + risk * float(self.p.take_profit_ratio)
                self.buy_count += 1
            else:
                risk = max(wide_high - close, close * 0.005)
                self.stop_price = wide_high
                self.take_profit_price = close - risk * float(self.p.take_profit_ratio)
                self.sell_count += 1
            target_size = self._get_position_size(target_notional_pct=float(self.p.position_size) * direction)
            self.pending_order = self.order_target_size(target=target_size)

    def notify_order(self, order):
        """Clear pending order state and reset entry metadata when orders are finalized."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None
            self.trade_direction = 0

    def notify_trade(self, trade):
        """Update trade counters when a position is closed."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_028_wide_range_pattern() -> None:
    """Migrated regression test for others/0028_wide_range_pattern."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        range_period=14,
        wide_threshold=1.8,
        wait_days_min=1,
        wait_days_max=7,
    )
    frame = prepare_wide_range_pattern_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(Mt5WideRangePatternFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.addstrategy(WideRangePatternStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4624
    assert strat.buy_count == 112
    assert strat.sell_count == 112
    assert strat.win_count == 55
    assert strat.loss_count == 57
    assert strat.trade_count == 112
    assert total_trades == 112
    assert abs(final_value - 949150.0173) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
