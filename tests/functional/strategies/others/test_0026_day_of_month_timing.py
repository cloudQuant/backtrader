"""Inlined regression test for others/0026_day_of_month_timing.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Uses XAUUSD as the gold asset and BIL as the cash equivalent.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
GOLD_FILE = _REPO / "tests" / "datas" / "XAUUSD_1d.csv"
CASH_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "BIL_1d.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    df["datetime"] = parsed
    df = df.rename(columns={"<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low", "<CLOSE>": "close",
                             "<TICKVOL>": "tick_volume", "<VOL>": "real_volume"})
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def _signal_day_for_group(group, signal_day):
    dates = list(group.index)
    if not dates:
        return pd.Series(dtype=float)
    if signal_day <= 0:
        idx = max(0, len(dates) - 1 + int(signal_day))
    else:
        idx = min(len(dates) - 1, int(signal_day) - 1)
    target = dates[idx]
    return pd.Series([1.0 if dt == target else 0.0 for dt in dates], index=group.index)


def prepare_day_of_month_timing_inputs(asset_map, params):
    gold_df = asset_map["gold"][["open", "high", "low", "close", "volume", "openinterest"]].copy().sort_index()
    cash_df = asset_map["cash"][["open", "high", "low", "close", "volume", "openinterest"]].copy().sort_index()
    aligned_index = gold_df.index.intersection(cash_df.index).sort_values()
    if len(aligned_index) == 0:
        raise ValueError("No overlapping data available for day-of-month timing strategy")
    gold_df = gold_df.loc[aligned_index].copy()
    cash_df = cash_df.loc[aligned_index].copy()

    ma_period = int(params.get("ma_period", 200))
    confirm_days = int(params.get("confirm_days", 5))
    signal_day = int(params.get("signal_day", 0))
    use_seasonal_boost = bool(params.get("use_seasonal_boost", True))
    bullish_months = set(int(v) for v in params.get("bullish_months", [1, 9, 10, 11, 12]))
    bearish_months = set(int(v) for v in params.get("bearish_months", [6, 7, 8]))
    base_position = float(params.get("base_position", 0.95))
    bull_multiplier = float(params.get("seasonal_bull_multiplier", 1.1))
    bear_multiplier = float(params.get("seasonal_bear_multiplier", 0.75))

    signal_df = pd.DataFrame(index=aligned_index)
    signal_df["gold_close"] = gold_df["close"]
    signal_df["ma200"] = gold_df["close"].rolling(ma_period).mean()
    above_ma = (signal_df["gold_close"] > signal_df["ma200"]).astype(float)
    signal_df["confirm_count"] = above_ma.rolling(confirm_days).sum()
    signal_df["bullish_signal"] = (signal_df["confirm_count"] >= confirm_days).astype(float)

    month_groups = signal_df.groupby(signal_df.index.to_period("M"), group_keys=False)
    signal_df["is_signal_day"] = month_groups.apply(lambda grp: _signal_day_for_group(grp, signal_day))

    month_numbers = pd.Series(signal_df.index.month, index=signal_df.index)
    signal_df["seasonal_multiplier"] = 1.0
    if use_seasonal_boost:
        signal_df.loc[month_numbers.isin(list(bullish_months)), "seasonal_multiplier"] = bull_multiplier
        signal_df.loc[month_numbers.isin(list(bearish_months)), "seasonal_multiplier"] = bear_multiplier
    signal_df["target_asset"] = "cash"
    signal_df.loc[signal_df["bullish_signal"] > 0.5, "target_asset"] = "gold"
    signal_df["gold_target"] = 0.0
    signal_df.loc[signal_df["target_asset"] == "gold", "gold_target"] = base_position * signal_df["seasonal_multiplier"]
    signal_df["gold_target"] = signal_df["gold_target"].clip(lower=0.0, upper=1.0)
    signal_df["cash_target"] = 1.0 - signal_df["gold_target"]

    valid_rows = signal_df[["ma200", "confirm_count"]].notna().all(axis=1)
    signal_df = signal_df.loc[valid_rows].copy()
    gold_df = gold_df.loc[signal_df.index].copy()
    cash_df = cash_df.loc[signal_df.index].copy()
    return {"gold": gold_df, "cash": cash_df}, signal_df


class DayOfMonthTimingStrategy(bt.Strategy):
    params = dict(
        signal_lookup=None,
        rebalance_threshold=0.05,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.rebalance_count = 0
        self.pending_orders = []
        self.signal_lookup = self.p.signal_lookup or {}
        self.data_by_name = {data._name: data for data in self.datas}

    def _portfolio_weights(self):
        portfolio_value = float(self.broker.getvalue())
        if portfolio_value <= 0:
            return {"gold": 0.0, "cash": 0.0}
        weights = {}
        for name, data in self.data_by_name.items():
            position = self.getposition(data)
            weights[name] = float(position.size) * float(data.close[0]) / portfolio_value if position.size else 0.0
        return weights

    def _rebalance(self, targets):
        current_weights = self._portfolio_weights()
        for name, data in self.data_by_name.items():
            target = float(targets.get(name, 0.0))
            current = current_weights.get(name, 0.0)
            if target > current:
                self.buy_count += 1
            elif current > 0 and target < current:
                self.sell_count += 1
            order = self.order_target_percent(data=data, target=target)
            if order is not None:
                self.pending_orders.append(order)
        self.rebalance_count += 1

    def next(self):
        self.bar_num += 1
        current_dt = bt.num2date(self.datas[0].datetime[0]).replace(tzinfo=None)
        if self.pending_orders:
            return
        signal = self.signal_lookup.get(pd.Timestamp(current_dt))
        if signal is None:
            signal = self.signal_lookup.get(pd.Timestamp(current_dt.date()))
        if signal is None or float(signal.get("is_signal_day", 0.0)) <= 0.5:
            return
        targets = {
            "gold": float(signal.get("gold_target", 0.0)),
            "cash": float(signal.get("cash_target", 0.0)),
        }
        current_weights = self._portfolio_weights()
        if any(abs(current_weights.get(name, 0.0) - targets.get(name, 0.0)) > float(self.p.rebalance_threshold) for name in ("gold", "cash")):
            self._rebalance(targets)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_orders = [pending for pending in self.pending_orders if pending is not None and pending.ref != order.ref]

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_026_day_of_month_timing() -> None:
    """Migrated regression test for others/0026_day_of_month_timing."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    raw = {
        "gold": load_mt5_csv(GOLD_FILE, fromdate=fromdate, todate=todate),
        "cash": load_mt5_csv(CASH_FILE, fromdate=fromdate, todate=todate),
    }
    params = dict(
        signal_day=0, ma_period=200, confirm_days=5,
        base_position=0.95, use_seasonal_boost=True,
        bullish_months=[1, 9, 10, 11, 12], bearish_months=[6, 7, 8],
        seasonal_bull_multiplier=1.1, seasonal_bear_multiplier=0.75,
    )
    asset_data, signal_df = prepare_day_of_month_timing_inputs(raw, params)
    signal_lookup = signal_df.to_dict("index")

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(bt.feeds.PandasData(dataname=asset_data["gold"], timeframe=bt.TimeFrame.Days), name="gold")
    cerebro.adddata(bt.feeds.PandasData(dataname=asset_data["cash"], timeframe=bt.TimeFrame.Days), name="cash")
    cerebro.addstrategy(DayOfMonthTimingStrategy, signal_lookup=signal_lookup, rebalance_threshold=0.05)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"rebalance={strat.rebalance_count} win={strat.win_count} loss={strat.loss_count} "
          f"trade={strat.trade_count} total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4310
    assert strat.buy_count == 197
    assert strat.sell_count == 71
    assert strat.rebalance_count == 177
    assert strat.win_count == 4
    assert strat.loss_count == 16
    assert strat.trade_count == 20
    assert total_trades == 20
    assert abs(final_value - 3050417.2645) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
