"""Inlined regression test for pairs trading using cointegration spread.

Self-contained single-file test (manually authored). Runs with runonce=True only.
Engle-Granger cointegration spread on XAUUSD / XAGUSD daily.

Data Used:
    Daily XAUUSD and XAGUSD data from ``tests/datas/mt5_1d_data``.

Strategy Principle:
    Build a rolling cointegration beta and spread z-score from log prices. Enter
    long/short spread positions when the spread exceeds threshold and exit on
    reversion, loss, or when co-integration confidence drops.

Strategy Logic:
    ``prepare_cointegration_features`` computes spread beta, z-score, and signal
    flags. The strategy opens paired long/short legs according to z-score
    extremes, manages open positions through threshold-based exits, and uses
    callbacks to track order lifecycle and trade outcomes.
"""
from __future__ import annotations

import datetime
from pathlib import Path

import backtrader as bt
import numpy as np
from backtrader.utils.load_data import load_mt5_csv

try:
    from statsmodels.tsa.stattools import adfuller
except Exception:
    adfuller = None

_REPO = Path(__file__).resolve().parents[4]
GOLD_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAUUSD_1d.csv"
SILVER_FILE = _REPO / "tests" / "datas" / "mt5_1d_data" / "XAGUSD_1d.csv"


def prepare_pair_data(gold_df, silver_df):
    """Align gold and silver bars on a common datetime index.

    Args:
        gold_df: XAUUSD OHLCV DataFrame.
        silver_df: XAGUSD OHLCV DataFrame.

    Returns:
        Tuple of aligned ``(gold_df, silver_df)``.
    """
    common_index = gold_df.index.intersection(silver_df.index).sort_values()
    return gold_df.loc[common_index].copy(), silver_df.loc[common_index].copy()


def _cointegration_pass(residuals, pvalue_threshold):
    residuals = np.asarray(residuals, dtype=float)
    residuals = residuals[np.isfinite(residuals)]
    if len(residuals) < 30:
        return False, np.nan
    if adfuller is not None:
        try:
            result = adfuller(residuals, maxlag=1, regression="c", autolag=None)
            pvalue = float(result[1])
            return pvalue < pvalue_threshold, pvalue
        except Exception:
            pass
    lagged = residuals[:-1]
    current = residuals[1:]
    if len(lagged) < 10:
        return False, np.nan
    phi = np.dot(lagged, current) / max(np.dot(lagged, lagged), 1e-12)
    pseudo_p = 0.01 if phi < 0.98 else 0.5
    return phi < 0.98, pseudo_p


def prepare_cointegration_features(gold_df, silver_df, params):
    """Compute rolling cointegration features used by the strategy.

    Args:
        gold_df: Gold OHLCV DataFrame.
        silver_df: Silver OHLCV DataFrame.
        params: Parameter dict with window and p-value thresholds.

    Returns:
        Tuple ``(signal_df, gold_aligned, silver_aligned)`` with feature columns.
    """
    gold, silver = prepare_pair_data(gold_df, silver_df)
    window = int(params.get("coint_window", 252))
    pvalue_threshold = float(params.get("pvalue_threshold", 0.05))
    log_gold = np.log(gold["close"].clip(lower=1e-6))
    log_silver = np.log(silver["close"].clip(lower=1e-6))

    beta_arr = np.full(len(gold), np.nan)
    zscore_arr = np.full(len(gold), np.nan)
    coint_flag_arr = np.zeros(len(gold), dtype=float)
    pvalue_arr = np.full(len(gold), np.nan)

    for idx in range(window, len(gold)):
        y = log_gold.iloc[idx - window:idx].values
        x = log_silver.iloc[idx - window:idx].values
        design = np.column_stack([np.ones(len(x)), x])
        coeffs, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
        alpha, beta = coeffs
        spread_window = y - (alpha + beta * x)
        passed, pvalue = _cointegration_pass(spread_window, pvalue_threshold)
        current_spread = log_gold.iloc[idx] - (alpha + beta * log_silver.iloc[idx])
        std = np.std(spread_window)
        zscore = (current_spread - np.mean(spread_window)) / std if std > 0 else np.nan
        beta_arr[idx] = beta
        zscore_arr[idx] = zscore
        coint_flag_arr[idx] = 1.0 if passed else 0.0
        pvalue_arr[idx] = pvalue

    signal_df = gold[["open", "high", "low", "close", "volume", "openinterest"]].copy()
    signal_df["beta"] = beta_arr
    signal_df["zscore"] = zscore_arr
    signal_df["coint_flag"] = coint_flag_arr
    signal_df["coint_pvalue"] = pvalue_arr
    signal_df = signal_df.dropna(subset=["beta", "zscore", "coint_pvalue"])
    gold = gold.loc[signal_df.index].copy()
    silver = silver.loc[signal_df.index].copy()
    return signal_df, gold, silver


class GoldCointegrationSignalFeed(bt.feeds.PandasData):
    """PandasData feed exposing beta/z-score/cointegration signal lines."""
    lines = ("beta", "zscore", "coint_flag", "coint_pvalue")
    params = (
        ("datetime", None), ("open", 0), ("high", 1), ("low", 2), ("close", 3), ("volume", 4), ("openinterest", 5),
        ("beta", 6), ("zscore", 7), ("coint_flag", 8), ("coint_pvalue", 9),
    )


class GoldCointegrationSpreadStrategy(bt.Strategy):
    """Pairs strategy that trades long/short spreads on cointegration z-score signals."""
    params = dict(
        entry_threshold=2.0,
        exit_threshold=0.5,
        stop_threshold=3.0,
        max_notional_pct=0.05,
        commission_pct=0.0005,
    )

    def __init__(self):
        """Initialize strategy references, counters, and position state."""
        self.signal = self.datas[0]
        self.gold = self.getdatabyname("XAUUSD")
        self.silver = self.getdatabyname("XAGUSD")
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.current_spread_side = 0

    def _target_sizes(self, beta):
        portfolio_value = float(self.broker.getvalue())
        gold_price = max(float(self.gold.close[0]), 1e-6)
        silver_price = max(float(self.silver.close[0]), 1e-6)
        leg_notional = portfolio_value * float(self.p.max_notional_pct)
        gold_size = max(0.01, round(leg_notional / gold_price, 2))
        silver_size = max(0.01, round(leg_notional * abs(beta) / silver_price, 2))
        return gold_size, silver_size

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _close_all(self):
        gold_pos = self.getposition(self.gold).size
        silver_pos = self.getposition(self.silver).size
        if gold_pos:
            self._submit(self.close(data=self.gold))
            if gold_pos > 0:
                self.sell_count += 1
            else:
                self.buy_count += 1
        if silver_pos:
            self._submit(self.close(data=self.silver))
            if silver_pos > 0:
                self.sell_count += 1
            else:
                self.buy_count += 1
        self.current_spread_side = 0

    def _open_long_spread(self, beta):
        gold_size, silver_size = self._target_sizes(beta)
        self.buy_count += 1
        self.sell_count += 1
        self._submit(self.buy(data=self.gold, size=gold_size))
        self._submit(self.sell(data=self.silver, size=silver_size))
        self.current_spread_side = 1

    def _open_short_spread(self, beta):
        gold_size, silver_size = self._target_sizes(beta)
        self.sell_count += 1
        self.buy_count += 1
        self._submit(self.sell(data=self.gold, size=gold_size))
        self._submit(self.buy(data=self.silver, size=silver_size))
        self.current_spread_side = -1

    def next(self):
        """Evaluate spread signals and perform opens or exits each bar."""
        self.bar_num += 1
        if self.order_refs:
            return
        beta = float(self.signal.beta[0]) if self.signal.beta[0] == self.signal.beta[0] else None
        zscore = float(self.signal.zscore[0]) if self.signal.zscore[0] == self.signal.zscore[0] else None
        coint_flag = float(self.signal.coint_flag[0]) > 0.5
        if beta is None or zscore is None:
            return
        has_position = bool(self.getposition(self.gold).size or self.getposition(self.silver).size)
        if not has_position:
            if not coint_flag:
                return
            if zscore <= -float(self.p.entry_threshold):
                self._open_long_spread(beta)
            elif zscore >= float(self.p.entry_threshold):
                self._open_short_spread(beta)
            return
        if (not coint_flag) or abs(zscore) <= float(self.p.exit_threshold) or abs(zscore) >= float(self.p.stop_threshold):
            self._close_all()

    def notify_order(self, order):
        """Track and clear pending order references.

        Args:
            order: Order whose status changed.
        """
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        """Count completed trades and classify wins/losses."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1


def test_003_gold_cointegration_spread() -> None:
    """Migrated regression test for pairs_trading/0003_gold_cointegration_spread."""
    fromdate = datetime.datetime(2008, 1, 1, 0, 0)
    todate = datetime.datetime(2025, 12, 31, 0, 0)
    gold_raw = load_mt5_csv(GOLD_FILE, fromdate=fromdate, todate=todate)
    silver_raw = load_mt5_csv(SILVER_FILE, fromdate=fromdate, todate=todate)
    params = dict(coint_window=252, pvalue_threshold=0.05)
    signal_df, gold, silver = prepare_cointegration_features(gold_raw, silver_raw, params)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(1_000_000)
    cerebro.broker.setcommission(commission=0.0005)
    cerebro.adddata(GoldCointegrationSignalFeed(dataname=signal_df, timeframe=bt.TimeFrame.Days), name="SIGNAL")
    cerebro.adddata(bt.feeds.PandasData(dataname=gold[["open", "high", "low", "close", "volume", "openinterest"]],
                                          timeframe=bt.TimeFrame.Days), name="XAUUSD")
    cerebro.adddata(bt.feeds.PandasData(dataname=silver[["open", "high", "low", "close", "volume", "openinterest"]],
                                          timeframe=bt.TimeFrame.Days), name="XAGUSD")
    cerebro.addstrategy(GoldCointegrationSpreadStrategy)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trade")

    results = cerebro.run(runonce=True)
    strat = results[0]

    final_value = float(cerebro.broker.getvalue())
    trade_analysis = strat.analyzers.trade.get_analysis()
    total_trades = trade_analysis.get("total", {}).get("closed", 0)

    print(f"CAPTURED: bar={strat.bar_num} buy={strat.buy_count} sell={strat.sell_count} "
          f"win={strat.win_count} loss={strat.loss_count} trade={strat.trade_count} "
          f"total={total_trades} fv={final_value:.4f}")

    assert strat.bar_num == 4159
    assert strat.buy_count == 32
    assert strat.sell_count == 32
    assert strat.win_count == 16
    assert strat.loss_count == 16
    assert strat.trade_count == 32
    assert total_trades == 32
    assert abs(final_value - 999296.2740) < 1.0
    assert (strat.buy_count + strat.sell_count) > 0, "must have non-zero activity"
