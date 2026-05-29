"""Inlined regression test for others/0024_rut_spx_divergence.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Trade asset is IWM (Russell 2000 ETF), signal is IVV (S&P 500 ETF).
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[4]
TRADE_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IWM_1d.csv"
SIGNAL_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "IVV_1d.csv"


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


def prepare_rut_spx_divergence_features(trade_df, signal_df, params):
    rut_down_days = int(params.get("rut_down_days", 3))
    spx_new_high_period = int(params.get("spx_new_high_period", 3))
    aligned_index = trade_df.index.intersection(signal_df.index).sort_values()
    trade_df = trade_df.loc[aligned_index][["open", "high", "low", "close", "volume", "openinterest"]].copy()
    signal_close = signal_df.loc[aligned_index, "close"].astype(float)
    trade_close = trade_df["close"].astype(float)

    out = trade_df.copy()
    out["trade_down"] = (trade_close < trade_close.shift(1)).astype(float)
    consecutive_down = pd.Series(0, index=aligned_index, dtype=float)
    streak = 0
    for dt in aligned_index:
        if out.at[dt, "trade_down"] > 0.5:
            streak += 1
        else:
            streak = 0
        consecutive_down.at[dt] = float(streak)
    out["consecutive_down"] = consecutive_down
    out["signal_new_high"] = (signal_close >= signal_close.rolling(spx_new_high_period).max()).astype(float)
    out["entry_signal"] = ((out["consecutive_down"] >= rut_down_days) & (out["signal_new_high"] > 0.5)).astype(float)
    return out.dropna()


class RutSpxDivergenceFeed(bt.feeds.PandasData):
    lines = ("trade_down", "consecutive_down", "signal_new_high", "entry_signal",)
    params = (
        ("datetime", None),
        ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("trade_down", 6), ("consecutive_down", 7), ("signal_new_high", 8), ("entry_signal", 9),
    )


class RutSpxDivergenceStrategy(bt.Strategy):
    params = dict(
        holding_days=4,
        position_size=0.95,
        stop_loss=0.03,
        take_profit=0.05,
        rut_down_days=3,
        spx_new_high_period=3,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_days = 0
        self.pending_order = None
        self.entry_bar = 0
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def next(self):
        self.bar_num += 1
        if self.pending_order is not None:
            return

        close = float(self.data.close[0])
        low = float(self.data.low[0])
        high = float(self.data.high[0])

        if self.position:
            if self.stop_price is not None and low <= self.stop_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.sell_count += 1
                self.pending_order = self.close()
                return
            if self.bar_num - self.entry_bar >= int(self.p.holding_days):
                self.sell_count += 1
                self.pending_order = self.close()
                return
            return

        if float(self.data.entry_signal[0]) > 0.5:
            self.signal_days += 1
            self.buy_count += 1
            self.entry_bar = self.bar_num
            self.entry_price = close
            self.stop_price = close * (1.0 - float(self.p.stop_loss))
            self.take_profit_price = close * (1.0 + float(self.p.take_profit))
            self.pending_order = self.order_target_percent(target=float(self.p.position_size))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None
        if not self.position:
            self.entry_price = None
            self.stop_price = None
            self.take_profit_price = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_024_rut_spx_divergence() -> None:
    """Migrated regression test for others/0024_rut_spx_divergence."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    trade = load_mt5_csv(TRADE_FILE, fromdate=fromdate, todate=todate)
    signal = load_mt5_csv(SIGNAL_FILE, fromdate=fromdate, todate=todate)
    frame = prepare_rut_spx_divergence_features(trade, signal, params=dict())

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(RutSpxDivergenceFeed(dataname=frame, timeframe=bt.TimeFrame.Days), name="IWM")
    cerebro.addstrategy(RutSpxDivergenceStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4519
    assert strat.buy_count == 22
    assert strat.sell_count == 22
    assert strat.win_count == 14
    assert strat.loss_count == 8
    assert strat.trade_count == 22
    assert total_trades == 22
    assert abs(final_value - 1085700.5488) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
