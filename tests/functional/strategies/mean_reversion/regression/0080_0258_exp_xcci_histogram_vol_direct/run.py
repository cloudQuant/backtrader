from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import datetime
import math
from pathlib import Path

import backtrader as bt
import yaml

from strategy_xcci_histogram_vol_direct import Mt5PandasFeed, ExpXCCIHistogramVolDirectStrategy, load_mt5_csv

BASE_DIR = Path(__file__).resolve().parent

# Vendored benchmark output hook (auto-edited by migrate_regression.py)
from pathlib import Path as _BenchmarkPath
import sys as _benchmark_sys
_BENCHMARK_BASE_DIR = _BenchmarkPath(__file__).resolve().parent
_REPO_ROOT = _BenchmarkPath(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in _benchmark_sys.path:
    _benchmark_sys.path.insert(0, str(_REPO_ROOT))

# Auto-added: ensure repo root is on sys.path so tests.test_utils resolves
import sys as _migration_sys
from pathlib import Path as _MigrationPath
_REPO_ROOT_FOR_VENDORED = _MigrationPath(__file__).resolve().parents[6]
if str(_REPO_ROOT_FOR_VENDORED) not in _migration_sys.path:
    _migration_sys.path.insert(0, str(_REPO_ROOT_FOR_VENDORED))

from tests.test_utils.benchmark_metrics import (
    install_benchmark_metrics_hook as _install_benchmark_metrics_hook,
    load_benchmark_result as _load_benchmark_result,
    write_benchmark_result as _write_benchmark_result,
)
_install_benchmark_metrics_hook(_BENCHMARK_BASE_DIR)
MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def resolve_data_path(filename):
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def parse_dt(value):
    if not value:
        return None
    return datetime.datetime.fromisoformat(value)


def load_backtest_frame(config):
    data_cfg = config['data']
    fromdate = parse_dt(data_cfg.get('fromdate'))
    todate = parse_dt(data_cfg.get('todate'))
    df = load_mt5_csv(resolve_data_path(data_cfg['file']), fromdate=fromdate, todate=todate, bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if df.empty:
        raise ValueError('Loaded data frame is empty')
    print(f'Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}')
    return {'data': df}


def add_default_analyzers(cerebro):
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=60, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')


def resample_frame(df, minutes):
    rule = f'{minutes}min'
    resampled = df.resample(rule, label='right', closed='right').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'openinterest': 'last', 'spread': 'last'})
    resampled = resampled.dropna(subset=['open', 'high', 'low', 'close'])
    resampled['openinterest'] = resampled['openinterest'].fillna(0)
    resampled['spread'] = resampled['spread'].fillna(0)
    return resampled


def build_cerebro(config, frame):
    bt_cfg = config['backtest']
    data_cfg = config['data']
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type', 'fixed') == 'fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(commission=bt_cfg['commission'], margin=bt_cfg['margin'], mult=bt_cfg['multiplier'], commtype=comm_type, stocklike=bt_cfg.get('stocklike', False))
    execution_feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=data_cfg.get('execution_compression_minutes', 15))
    signal_df = resample_frame(frame['data'], data_cfg['signal_compression_minutes'])
    signal_feed = Mt5PandasFeed(dataname=signal_df, timeframe=bt.TimeFrame.Minutes, compression=data_cfg['signal_compression_minutes'])
    cerebro.adddata(execution_feed, name=f"{data_cfg['symbol']}_{data_cfg['base_timeframe']}")
    cerebro.adddata(signal_feed, name=f"{data_cfg['symbol']}_{data_cfg['signal_timeframe']}")
    cerebro.addstrategy(ExpXCCIHistogramVolDirectStrategy, **config.get('params', {}))
    add_default_analyzers(cerebro)
    return cerebro


def finite_or_none(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not math.isfinite(value):
        return None
    return value


def summarize(results, start_value):
    strat = results[0]
    end_value = strat.broker.getvalue()
    drawdown = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    total_closed = trades.get('total', {}).get('closed', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    strike_rate = (won / total_closed * 100.0) if total_closed else 0.0
    print('\n# Backtest Summary')
    print(f'- Start Value: {start_value:.2f}')
    print(f'- End Value: {end_value:.2f}')
    print(f'- Net PnL: {end_value - start_value:.2f}')
    print(f'- Max Drawdown: {drawdown.get("max", {}).get("drawdown", 0.0):.2f}%')
    print(f'- Total Closed Trades: {total_closed}')
    print(f'- Won Trades: {won}')
    print(f'- Lost Trades: {lost}')
    print(f'- Strike Rate: {strike_rate:.2f}%')
    print(f'- Sharpe: {finite_or_none(sharpe.get("sharperatio"))}')
    print(f'- SQN: {finite_or_none(sqn.get("sqn"))}')
    print(f'- Total Return: {returns.get("rtot", 0.0):.6f}')


def main():
    parser = argparse.ArgumentParser(description='Run Exp_XCCI_Histogram_Vol_Direct backtest')
    parser.add_argument('--plot', action='store_true', help='Plot result chart')
    args = parser.parse_args()
    config = load_config()
    frame = load_backtest_frame(config)
    cerebro = build_cerebro(config, frame)
    start_value = cerebro.broker.getvalue()
    results = cerebro.run(runonce=False)
    summarize(results, start_value)
    if args.plot:
        cerebro.plot(style='candlestick')




# Canonical benchmark run() wrapper.
try:
    _BENCHMARK_ORIGINAL_RUN = run
except NameError:
    _BENCHMARK_ORIGINAL_RUN = None
try:
    _BENCHMARK_ORIGINAL_MAIN = main
except NameError:
    _BENCHMARK_ORIGINAL_MAIN = None


def _benchmark_call_original_run(*args, plot=False, **kwargs):
    if _BENCHMARK_ORIGINAL_RUN is not None:
        call_kwargs = dict(kwargs)
        call_kwargs.setdefault("plot", plot)
        try:
            return _BENCHMARK_ORIGINAL_RUN(*args, **call_kwargs)
        except TypeError as original_error:
            call_kwargs.pop("plot", None)
            try:
                return _BENCHMARK_ORIGINAL_RUN(*args, **call_kwargs)
            except TypeError:
                raise original_error
    if _BENCHMARK_ORIGINAL_MAIN is not None:
        return _BENCHMARK_ORIGINAL_MAIN()
    return None


def run(*args, plot=False, **kwargs):
    result = _benchmark_call_original_run(*args, plot=plot, **kwargs)
    result_path = _BENCHMARK_BASE_DIR / "backtest_result.json"
    metrics = _load_benchmark_result(result_path, fallback=result)
    if metrics:
        _write_benchmark_result(result_path, metrics)
    return metrics


if __name__ == '__main__':
    main()
