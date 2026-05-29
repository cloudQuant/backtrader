"""Inlined regression test for others/0010_intraday_momentum.

Self-contained single-file test (manually authored). Runs with runonce=True only.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path

import backtrader as bt
import pandas as pd

_REPO = Path(__file__).resolve().parents[6]
DATA_FILE = _REPO / "tests" / "datas" / "XAUUSD_M5.csv"


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = "\n".join(lines)
    sep = "\t" if "\t" in lines[0] else ","
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    dt_text = df["<DATE>"].astype(str) + " " + df["<TIME>"].astype(str)
    parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M:%S", errors="coerce")
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format="%Y.%m.%d %H:%M", errors="coerce")
    df["datetime"] = parsed
    df = df.rename(columns={
        "<OPEN>": "open", "<HIGH>": "high", "<LOW>": "low",
        "<CLOSE>": "close", "<TICKVOL>": "tick_volume", "<VOL>": "real_volume",
    })
    df["openinterest"] = 0
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    df = df[["datetime", "open", "high", "low", "close", "volume", "openinterest"]]
    df = df.dropna(subset=["datetime"]).set_index("datetime").sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_intraday_momentum_features(df, params):
    signal_bar_index = int(params.get("signal_bar_index", 11))
    signal_threshold = float(params.get("signal_threshold", 0.0015))
    gross_exposure = float(params.get("gross_exposure", 0.95))

    frame = df.copy()
    frame["session_date"] = frame.index.date
    frame["bar_slot"] = frame.groupby("session_date").cumcount()
    frame["session_open"] = frame.groupby("session_date")["open"].transform("first")
    frame["morning_return"] = frame["close"] / frame["session_open"] - 1.0
    frame["is_eod"] = frame["session_date"] != frame["session_date"].shift(-1)

    target_pct = []
    signal_change = []
    session_signal = 0.0
    prev_session = None
    prev_target = 0.0

    for row in frame.itertuples():
        session_date = row.session_date
        if session_date != prev_session:
            session_signal = 0.0
            prev_session = session_date
        if row.bar_slot == signal_bar_index:
            if row.morning_return >= signal_threshold:
                session_signal = gross_exposure
            elif row.morning_return <= -signal_threshold:
                session_signal = -gross_exposure
            else:
                session_signal = 0.0
        if bool(row.is_eod):
            target = 0.0
        else:
            target = session_signal
        target_pct.append(target)
        signal_change.append(1.0 if target != prev_target else 0.0)
        prev_target = target

    frame["target_pct"] = target_pct
    frame["signal_change"] = signal_change
    feature_cols = ["open", "high", "low", "close", "volume", "openinterest", "morning_return", "target_pct", "signal_change", "is_eod"]
    return frame[feature_cols].dropna()


class IntradayMomentumFeed(bt.feeds.PandasData):
    lines = ("morning_return", "target_pct", "signal_change", "is_eod")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2),
        ("close", 3), ("volume", 4), ("openinterest", 5),
        ("morning_return", 6), ("target_pct", 7), ("signal_change", 8), ("is_eod", 9),
    )


class GoldIntradayMomentumStrategy(bt.Strategy):
    params = dict(
        stop_loss_pct=0.004,
        take_profit_pct=0.008,
        signal_bar_index=11,
        signal_threshold=0.0015,
        gross_exposure=0.95,
        commission_pct=0.0002,
    )

    def __init__(self):
        self.pending_order = None
        self.bar_num = 0
        self.signal_change_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_price = None

    def next(self):
        self.bar_num += 1
        if self.pending_order is not None:
            return
        if self.position:
            pnl_pct = 0.0
            if self.entry_price:
                direction = 1.0 if self.position.size > 0 else -1.0
                pnl_pct = direction * (float(self.data.close[0]) / self.entry_price - 1.0)
            if pnl_pct <= -float(self.p.stop_loss_pct) or pnl_pct >= float(self.p.take_profit_pct):
                self.pending_order = self.close()
                return
        if float(self.data.signal_change[0]) <= 0.5:
            return
        self.signal_change_count += 1
        self.pending_order = self.order_target_percent(target=float(self.data.target_pct[0]))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if float(order.executed.size) > 0:
                self.buy_count += 1
            elif float(order.executed.size) < 0:
                self.sell_count += 1
            if order.size != 0 and self.position:
                self.entry_price = float(order.executed.price)
            elif not self.position:
                self.entry_price = None
        self.pending_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_10_0010_intraday_momentum() -> None:
    """Migrated regression test for others/0010_intraday_momentum."""
    fromdate = datetime.datetime(2025, 10, 1, 0, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 23, 59, 59)
    raw = load_mt5_csv(DATA_FILE, fromdate=fromdate, todate=todate)
    params = dict(
        signal_bar_index=11,
        signal_threshold=0.0015,
        gross_exposure=0.95,
        stop_loss_pct=0.004,
        take_profit_pct=0.008,
        commission_pct=0.0002,
    )
    frame = prepare_intraday_momentum_features(raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000.0)
    cerebro.broker.setcommission(commission=params["commission_pct"])
    cerebro.adddata(IntradayMomentumFeed(dataname=frame, timeframe=bt.TimeFrame.Minutes, compression=5), name="XAUUSD")
    cerebro.addstrategy(GoldIntradayMomentumStrategy, **params)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    assert strat.bar_num == 17754, f"bar_num: expected=17754, got={strat.bar_num}"
    assert strat.buy_count == 29, f"buy_count: expected=29, got={strat.buy_count}"
    assert strat.sell_count == 29, f"sell_count: expected=29, got={strat.sell_count}"
    assert strat.win_count == 9, f"win_count: expected=9, got={strat.win_count}"
    assert strat.loss_count == 20, f"loss_count: expected=20, got={strat.loss_count}"
    assert strat.trade_count == 29, f"trade_count: expected=29, got={strat.trade_count}"
    assert total_trades == 29, f"total_trades: expected=29, got={total_trades}"
    assert abs(final_value - 966374.82) < 1.0, f"final_value: expected≈966374.82, got={final_value}"
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
