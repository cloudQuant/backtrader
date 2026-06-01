"""Inlined regression test for tests/functional/strategies/others/regression/0044_cheap_stocks_factor.

Data Used:
    - Symbol: XAUUSD, timeframe: D1.
    - Source file: ``{repo}/tests/datas/XAUUSD_1d.csv``.
    - Date range: ``2008-01-01 00:00:00`` to ``2025-12-31 00:00:00``.
    - Data flow: MT5 D1 bars with percentile-based value feature and signal.

Strategy Principle:
    - Computes rolling percentile rank of close price as a cheapness indicator.
    - Generates a long signal when the percentile is below a configured low threshold.
    - Exits positions after the configured holding period.

Strategy Logic:
    - ``load_mt5_csv`` loads and normalizes MT5 data.
    - ``prepare_cheap_stocks_factor_features`` creates percentile and signal columns.
    - ``Mt5CheapStocksFactorFeed`` exposes engineered features to Backtrader.
    - ``CheapStocksFactorStrategy`` handles entries/exits and tracking metrics.
    - ``build_cerebro`` wires feed, strategy, and analyzers.
    - ``extract_metrics`` aggregates outputs used by assertions.
    - ``main`` runs backtest and collects metrics.
"""
from __future__ import annotations
import math
from pathlib import Path
import json
from datetime import datetime
from backtrader.comminfo import ComminfoFuturesPercent
import backtrader as bt
import numpy as np
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'id': '0336',
        'name': 'Cheap Stocks Factor',
        'source_spec': 'research_papers_gold/strategy_specs/others/0336_Cheap_Stocks_Factor_Strategy.md',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'D1',
        'file': '{repo}/tests/datas/XAUUSD_1d.csv',
        'fromdate': '2008-01-01 00:00:00',
        'todate': '2025-12-31 00:00:00',
    },
    'params': {
        'lookback': 252,
        'percentile_low': 20,
        'holding_days': 63,
        'lot_size': 1.0,
    },
    'backtest': {
        'initial_cash': 1000000,
        'commission': 0.0002,
        'margin': 0.01,
        'multiplier': 100.0,
        'commission_type': 'percent',
        'stocklike': False,
    },
    'outputs': {
        'local_result_json': 'backtest_result.json',
        'global_summary_csv': '../strategy_backtest_results.csv',
    },
}


def prepare_cheap_stocks_factor_features(df, params):
    """Calculate rolling percentile rank features used by the strategy.

    Args:
        df: Raw OHLCV dataframe.
        params: Strategy parameters.

    Returns:
        Dataframe with ``price_percentile`` and ``entry_signal`` columns.
    """
    lookback = int(params.get('lookback', 252))
    pct_low = float(params.get('percentile_low', 20))

    out = df.copy()
    out['price_percentile'] = out['close'].rolling(min(lookback, len(out))).rank(pct=True) * 100
    out['entry_signal'] = (out['price_percentile'] < pct_low).astype(float)

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'price_percentile', 'entry_signal']].copy()
    return out.dropna()


class Mt5CheapStocksFactorFeed(bt.feeds.PandasData):
    """Pandas feed exposing cheap-stock factor signal lines."""
    lines = ('price_percentile', 'entry_signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('price_percentile', 6),
        ('entry_signal', 7),
    )


class CheapStocksFactorStrategy(bt.Strategy):
    """Long-only percentile-factor strategy with fixed holding duration."""
    params = dict(
        lookback=252,
        percentile_low=20,
        holding_days=63,
        lot_size=1.0,
    )

    def __init__(self):
        """Initialize state counters and broker-value tracker."""
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.pending_order = None
        self.entry_bar = 0
        self.broker_value_series = []

    def _get_position_size(self, target_notional_pct=1.0, price=None):
        if target_notional_pct <= 0:
            return 0.0
        broker_value = float(self.broker.getvalue())
        execution_price = float(self.data.close[0] if price is None else price)
        if broker_value <= 0 or execution_price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(self.data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * float(target_notional_pct) / (execution_price * multiplier)
        return max(0.01, round(size, 2))


    def next(self):
        """Execute trading logic each bar based on the precomputed signal."""
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        entry = float(self.data.entry_signal[0]) > 0.5
        if not self.position:
            if entry:
                self.buy_count += 1
                self.entry_bar = self.bar_num
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if self.bar_num - self.entry_bar >= self.p.holding_days:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        """Clear pending order state once submitted order is finalized."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Keep trade lifecycle hook for compatibility."""
        pass


#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Cheap stocks factor strategy backtest."""


BASE_DIR = Path(__file__).parent.resolve()


def get_sharpe_analyzer_kwargs(config):
    """Build Sharpe analyzer keyword arguments from timeframe settings.

    Args:
        config: Configuration dictionary.

    Returns:
        Sharpe analyzer kwargs.
    """
    data_cfg = config.get('data', {}) if isinstance(config, dict) else {}
    timeframe_value = str(data_cfg.get('timeframe', 'D1')).upper()
    if timeframe_value.startswith('M') and timeframe_value[1:].isdigit():
        compression = max(1, int(timeframe_value[1:]))
        return dict(timeframe=bt.TimeFrame.Minutes, compression=compression, factor=252 * 24 * 60 / compression, annualize=True, riskfreerate=0)
    if timeframe_value.startswith('H') and timeframe_value[1:].isdigit():
        hours = max(1, int(timeframe_value[1:]))
        return dict(timeframe=bt.TimeFrame.Minutes, compression=hours * 60, factor=252 * 24 / hours, annualize=True, riskfreerate=0)
    return dict(timeframe=bt.TimeFrame.Days, compression=1, factor=252, annualize=True, riskfreerate=0)


def finite_or_none(x):
    """Return a finite number, otherwise ``None``."""
    return x if x and math.isfinite(x) else None


def calculate_ulcer_index(values):
    """Compute ulcer index from the broker-value series."""
    if len(values) < 2:
        return 0.0
    max_value = values[0]
    sum_squared = 0.0
    for v in values:
        if v > max_value:
            max_value = v
        drawdown = (max_value - v) / max_value * 100.0 if max_value > 0 else 0.0
        sum_squared += drawdown ** 2
    return math.sqrt(sum_squared / len(values))


def load_data(config):
    """Load data and attach strategy features for backtest.

    Args:
        config: Strategy/backtest configuration.

    Returns:
        Dictionary of prepared data and boundaries.
    """
    data_cfg = config['data']
    fromdate = datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.fromisoformat(data_cfg['todate'])
    data_path = (BASE_DIR / data_cfg['file']).resolve()
    raw = load_mt5_csv(
        str(data_path),
        fromdate=fromdate, todate=todate,
    )
    df = prepare_cheap_stocks_factor_features(raw, config.get('params', {}))
    return {'data': df, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(frame, config):
    """Create and configure ``bt.Cerebro`` with analyzers and strategy.

    Args:
        frame: Prepared payload.
        config: Backtest config.

    Returns:
        Configured ``bt.Cerebro`` object.
    """
    cerebro = bt.Cerebro(stdstats=False)
    bt_cfg = config['backtest']
    cerebro.broker.setcash(float(bt_cfg['initial_cash']))
    comminfo = ComminfoFuturesPercent(
        commission=float(bt_cfg.get('commission', 0.0)),
        margin=float(bt_cfg.get('margin', 0.01)),
        mult=float(bt_cfg.get('multiplier', 1.0)),
    )
    cerebro.broker.addcommissioninfo(comminfo)
    feed = Mt5CheapStocksFactorFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(CheapStocksFactorStrategy, **config.get('params', {}))
    sharpe_kwargs = get_sharpe_analyzer_kwargs(config)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', **sharpe_kwargs)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Extract trade and return metrics for test assertions.

    Args:
        strat: Executed strategy instance.
        cerebro: Completed cerebro engine.
        frame: Backtest payload.
        config: Backtest config.

    Returns:
        Dictionary of result metrics.
    """
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    ta = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    broker_values = [v for _, v in getattr(strat, 'broker_value_series', [])] or [initial_cash, final_value]
    total_trades = ta.get('total', {}).get('total', 0)
    won = ta.get('won', {}).get('total', 0)
    lost = ta.get('lost', {}).get('total', 0)
    gross_won = ta.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(ta.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'strategy_name': config['strategy']['name'],
        'fromdate': frame['fromdate'], 'todate': frame['todate'],
        'bars': len(frame['data']), 'bar_num': strat.bar_num,
        'buy_count': strat.buy_count, 'sell_count': strat.sell_count,
        'trade_count': total_trades, 'win_count': won, 'loss_count': lost,
        'initial_cash': initial_cash, 'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1.0) * 100.0,
        'total_trades': total_trades, 'won': won, 'lost': lost,
        'win_rate': (won / total_trades * 100.0) if total_trades else 0.0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'sharpe_ratio': finite_or_none(sharpe.get('sharperatio')),
        'annual_return_pct': (returns.get('rnorm') or 0.0) * 100.0,
        'sqn': finite_or_none(sqn.get('sqn')),
        'ulcer_index': calculate_ulcer_index(broker_values),
    }


def normalize(v):
    """Normalize values for JSON serialization and comparison."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def main():
    """Run the strategy and generate its result metrics."""
    config = _bt_load_config(_CONFIG, repo=_REPO)
    frame = load_data(config)
    print(f"Loaded {len(frame['data'])} bars")
    cerebro = build_cerebro(frame, config)
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, config)


def _close(actual, expected, *, tol, key):
    """Assert ``actual`` is finite and within ``tol`` of ``expected``."""
    assert actual is not None, f"{key}: expected={expected}, got=None"
    a = float(actual)
    assert math.isfinite(a), f"{key}: expected={expected}, got non-finite {actual}"
    assert abs(a - float(expected)) <= tol, (
        f"{key}: expected={expected}, got={a} (tol={tol})"
    )


def _invoke_strategy_main():
    """Call main() or run() depending on what the original script defined."""
    import sys as _sys
    _mod = _sys.modules[__name__]
    if hasattr(_mod, "main") and callable(_mod.main):
        return _mod.main()
    if hasattr(_mod, "run") and callable(_mod.run):
        return _mod.run()
    raise RuntimeError("Neither main() nor run() found in inlined module")


def test_44_0044_cheap_stocks_factor() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/others/0044_cheap_stocks_factor.
    """
    # Capture metrics by hooking extract_metrics() and invoking the original
    # main() (or run()). This reuses whatever loader / build_cerebro /
    # extract_metrics signatures the strategy used internally.
    captured = {}
    _orig_extract = extract_metrics
    def _capture_em(*a, **kw):
        m = _orig_extract(*a, **kw)
        if isinstance(m, dict):
            captured["metrics"] = m
        return m

    import sys as _sys
    _mod = _sys.modules[__name__]
    _mod.extract_metrics = _capture_em

    # Force runonce=True for the run inside main().
    import backtrader as _bt
    _orig_run = _bt.Cerebro.run
    def _forced_runonce(self, *args, **kwargs):
        kwargs["runonce"] = True
        return _orig_run(self, *args, **kwargs)
    _bt.Cerebro.run = _forced_runonce

    # Strip pytest argv so that argparse-based main() functions don't see them.
    _saved_argv = _sys.argv
    _sys.argv = [_sys.argv[0]]

    try:
        try:
            _invoke_strategy_main()
        except SystemExit:
            pass
        except Exception:
            if "metrics" not in captured:
                raise
    finally:
        _bt.Cerebro.run = _orig_run
        _mod.extract_metrics = _orig_extract
        _sys.argv = _saved_argv

    metrics = captured.get("metrics")
    assert metrics is not None, "extract_metrics() was not called"

    assert metrics.get('bar_num') == 4387, f"bar_num: expected=4387, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 21, f"buy_count: expected=21, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 21, f"sell_count: expected=21, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 13, f"win_count: expected=13, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 8, f"loss_count: expected=8, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 21, f"total_trades: expected=21, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 21, f"trade_count: expected=21, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 13, f"won: expected=13, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 8, f"lost: expected=8, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 4387.0, tol=4.387000e-03, key='bars')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1097671.6447940012, tol=1.097672e+00, key='final_value')
    _close(metrics.get('net_pnl'), 97671.64479400124, tol=9.767164e-02, key='net_pnl')
    _close(metrics.get('total_return_pct'), 9.767164479400115, tol=9.767164e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 61.904761904761905, tol=6.190476e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.2148981035960047, tol=1.214898e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 29.234044196411517, tol=2.923404e-05, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), 0.10562064590799901, tol=1.000000e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 0.5367486733118402, tol=1.000000e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), 0.3524623402527423, tol=1.000000e-06, key='sqn')
    _close(metrics.get('ulcer_index'), 9.738787261355416, tol=9.738787e-06, key='ulcer_index')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
