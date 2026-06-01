"""Inlined regression test for tests/functional/strategies/others/regression/0042_probability_cones.

Data Used:
    - Symbol: XAUUSD, timeframe: D1.
    - Source file: ``{repo}/tests/datas/XAUUSD_1d.csv``.
    - Date range: ``2008-01-01 00:00:00`` to ``2025-12-31 00:00:00``.
    - Data flow: MT5 D1 bars with rolling return-cone signal features.

Strategy Principle:
    - Computes rolling mean and standard deviation of returns.
    - Builds upper/lower probability cones around expected price.
    - Enters long when price breaches the lower cone and short when it breaches the upper cone.

Strategy Logic:
    - ``load_mt5_csv`` loads and normalizes MT5 raw bars.
    - ``prepare_probability_cones_features`` enriches data with cone boundaries and signal.
    - ``Mt5ProbabilityConesFeed`` exposes cone and signal lines to Backtrader.
    - ``ProbabilityConesStrategy`` runs entries/exits in ``next`` and lifecycle hooks.
    - ``build_cerebro`` wires datafeed, strategy, and analyzers.
    - ``extract_metrics`` aggregates strategy and risk statistics for assertions.
    - ``main`` runs the test backtest and provides metric output.
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
        'id': '0334',
        'name': 'Probability Cones',
        'source_spec': 'research_papers_gold/strategy_specs/others/0334_Probability_Cones_Strategy.md',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'D1',
        'file': '{repo}/tests/datas/XAUUSD_1d.csv',
        'fromdate': '2008-01-01 00:00:00',
        'todate': '2025-12-31 00:00:00',
    },
    'params': {
        'lookback': 60,
        'num_std': 2.0,
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


def prepare_probability_cones_features(df, params):
    """Create rolling probability cone boundaries and directional entry signals.

    Args:
        df: Raw OHLCV dataframe.
        params: Strategy parameters.

    Returns:
        Dataframe with ``upper_cone``, ``lower_cone`` and ``signal`` columns.
    """
    lookback = int(params.get('lookback', 60))
    num_std = float(params.get('num_std', 2.0))

    out = df.copy()
    ret = out['close'].pct_change()
    mu = ret.rolling(lookback).mean()
    sigma = ret.rolling(lookback).std()
    expected_price = out['close'].shift(1) * (1 + mu)
    out['upper_cone'] = expected_price + num_std * sigma * out['close'].shift(1)
    out['lower_cone'] = expected_price - num_std * sigma * out['close'].shift(1)
    out['signal'] = 0.0
    out.loc[out['close'] < out['lower_cone'], 'signal'] = 1.0
    out.loc[out['close'] > out['upper_cone'], 'signal'] = -1.0

    out = out[['open', 'high', 'low', 'close', 'volume', 'openinterest',
               'upper_cone', 'lower_cone', 'signal']].copy()
    return out.dropna()


class Mt5ProbabilityConesFeed(bt.feeds.PandasData):
    """Pandas feed exposing upper/lower cone values and signal line."""
    lines = ('upper_cone', 'lower_cone', 'signal',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('upper_cone', 6),
        ('lower_cone', 7),
        ('signal', 8),
    )


class ProbabilityConesStrategy(bt.Strategy):
    """Strategy using probability cones to time breakout entries and reversals."""
    params = dict(
        lookback=60,
        num_std=2.0,
        lot_size=1.0,
    )

    def __init__(self):
        """Initialize counters and broker value tracking state."""
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
        """Execute signals: buy on downside cone breach and flatten on breakout reversal."""
        self.bar_num += 1
        self.broker_value_series.append((bt.num2date(self.data.datetime[0]), float(self.broker.getvalue())))
        if self.pending_order is not None:
            return
        signal = float(self.data.signal[0])
        if not self.position:
            if signal > 0.5:
                self.buy_count += 1
                self.pending_order = self.buy(size=self._get_position_size())
        else:
            if signal < -0.5 or abs(signal) < 0.01:
                self.sell_count += 1
                self.pending_order = self.close()

    def notify_order(self, order):
        """Clear pending-order reference when order is no longer active."""
        if order.status in (order.Submitted, order.Accepted):
            return
        self.pending_order = None

    def notify_trade(self, trade):
        """Keep a trade hook for compatibility with strategy lifecycle."""
        pass


#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probability Cones strategy backtest."""


BASE_DIR = Path(__file__).parent.resolve()


def get_sharpe_analyzer_kwargs(config):
    """Build Sharpe analyzer options based on configured timeframe.

    Args:
        config: Strategy/backtest configuration.

    Returns:
        Keyword arguments for ``bt.analyzers.SharpeRatio``.
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
    """Return a finite float value or ``None`` when non-finite."""
    return x if x and math.isfinite(x) else None


def calculate_ulcer_index(values):
    """Compute ulcer index from a time series of broker values."""
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
    """Load backtest data and add probability cone derived indicators.

    Args:
        config: Test configuration.

    Returns:
        Loaded and preprocessed payload.
    """
    data_cfg = config['data']
    fromdate = datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.fromisoformat(data_cfg['todate'])
    data_path = (BASE_DIR / data_cfg['file']).resolve()
    raw = load_mt5_csv(
        str(data_path),
        fromdate=fromdate, todate=todate,
    )
    df = prepare_probability_cones_features(raw, config.get('params', {}))
    return {'data': df, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(frame, config):
    """Create and configure a Backtrader cerebro engine.

    Args:
        frame: Backtest payload.
        config: Strategy/backtest configuration.

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
    feed = Mt5ProbabilityConesFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(ProbabilityConesStrategy, **config.get('params', {}))
    sharpe_kwargs = get_sharpe_analyzer_kwargs(config)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', **sharpe_kwargs)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Aggregate key metrics from executed strategy and analyzers.

    Args:
        strat: Executed strategy instance.
        cerebro: Completed cerebro engine.
        frame: Backtest payload.
        config: Test configuration.

    Returns:
        Dictionary of assertion targets.
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
    """Normalize datetimes and non-finite floats for JSON comparison."""
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def main():
    """Run strategy backtest and return computed metrics."""
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


def test_42_0042_probability_cones() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/others/0042_probability_cones.
    """
    # Capture metrics by hooking extract_metrics() (or similar) and invoking the
    # original main()/run(). This reuses whatever loader / build_cerebro /
    # metrics-extraction signatures the strategy used internally.
    captured = {}

    import sys as _sys
    _mod = _sys.modules[__name__]

    # Hook any plausible metrics-extraction function.
    _hook_targets = []
    _metric_names = (
        "extract_metrics", "summarize", "build_metrics", "compute_metrics",
        "calculate_metrics", "collect_metrics", "gather_metrics", "extract_results",
    )
    for _name in _metric_names:
        _orig = getattr(_mod, _name, None)
        if callable(_orig):
            def _make_hook(orig):
                def _hook(*a, **kw):
                    m = orig(*a, **kw)
                    if isinstance(m, dict) and m and "metrics" not in captured:
                        captured["metrics"] = m
                    return m
                return _hook
            setattr(_mod, _name, _make_hook(_orig))
            _hook_targets.append((_name, _orig))

    # Force runonce=True for the cerebro.run() call inside main().
    import backtrader as _bt
    _orig_run = _bt.Cerebro.run
    def _forced_runonce(self, *args, **kwargs):
        kwargs["runonce"] = True
        return _orig_run(self, *args, **kwargs)
    _bt.Cerebro.run = _forced_runonce

    # Strip pytest argv so argparse-based main() functions don't see them.
    _saved_argv = _sys.argv
    _sys.argv = [_sys.argv[0]]

    try:
        try:
            if hasattr(_mod, "main") and callable(_mod.main):
                _mod.main()
            elif hasattr(_mod, "run") and callable(_mod.run):
                result = _mod.run()
                if isinstance(result, dict) and "metrics" not in captured:
                    captured["metrics"] = result
                elif isinstance(result, (list, tuple)):
                    for item in result:
                        if isinstance(item, dict) and "metrics" not in captured:
                            captured["metrics"] = item
                            break
            else:
                raise RuntimeError("Neither main() nor run() found in inlined module")
        except SystemExit:
            pass
        except Exception:
            if "metrics" not in captured:
                raise
    finally:
        _bt.Cerebro.run = _orig_run
        for _name, _orig in _hook_targets:
            setattr(_mod, _name, _orig)
        _sys.argv = _saved_argv

    metrics = captured.get("metrics")
    assert metrics is not None, "no metrics captured during run"

    assert metrics.get('bar_num') == 4578, f"bar_num: expected=4578, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 122, f"buy_count: expected=122, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 122, f"sell_count: expected=122, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 59, f"win_count: expected=59, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 63, f"loss_count: expected=63, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 122, f"total_trades: expected=122, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 122, f"trade_count: expected=122, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 59, f"won: expected=59, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 63, f"lost: expected=63, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 4578.0, tol=4.578000e-03, key='bars')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 833534.6745580004, tol=8.335347e-01, key='final_value')
    _close(metrics.get('net_pnl'), -166465.3254419996, tol=1.664653e-01, key='net_pnl')
    _close(metrics.get('total_return_pct'), -16.646532544199953, tol=1.664653e-05, key='total_return_pct')
    _close(metrics.get('win_rate'), 48.36065573770492, tol=4.836066e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 0.7036369226091851, tol=1.000000e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 22.252957130982786, tol=2.225296e-05, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), -0.24881186768093252, tol=1.000000e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), -0.9972690618766208, tol=1.000000e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), -1.2376470285780041, tol=1.237647e-06, key='sqn')
    _close(metrics.get('ulcer_index'), 13.733275760379984, tol=1.373328e-05, key='ulcer_index')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
