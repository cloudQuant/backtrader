from __future__ import absolute_import, division, print_function, unicode_literals

import csv
import json
import math
from datetime import datetime
from pathlib import Path

import backtrader as bt
import pandas as pd
import yaml

from strategy_pairs_trading_strategy import PairsTradingStrategy, load_mt5_csv, prepare_pair_inputs

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


def finite_or_none(value):
    return value if value is not None and math.isfinite(value) else None


def calculate_ulcer_index(values):
    if len(values) < 2:
        return 0.0
    peak = values[0]
    squared = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = (peak - value) / peak * 100.0 if peak > 0 else 0.0
        squared += drawdown ** 2
    return math.sqrt(squared / len(values))


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


def load_inputs(config):
    data_cfg = config['data']
    fromdate = datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.fromisoformat(data_cfg['todate'])
    frame_a = load_mt5_csv(data_cfg['asset_a_file'], fromdate=fromdate, todate=todate)
    frame_b = load_mt5_csv(data_cfg['asset_b_file'], fromdate=fromdate, todate=todate)
    frame_a, frame_b, signal_df = prepare_pair_inputs(frame_a, frame_b, config.get('params', {}))
    signal_lookup = {
        pd.Timestamp(index).tz_localize(None): {
            'corr': float(row['corr']),
            'beta': float(row['beta']),
            'zscore': float(row['zscore']),
        }
        for index, row in signal_df.iterrows()
    }
    return {'frame_a': frame_a, 'frame_b': frame_b, 'signal_df': signal_df, 'signal_lookup': signal_lookup, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(inputs, config):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(config['backtest']['initial_cash']))
    cerebro.broker.setcommission(commission=float(config['params'].get('commission_pct', 0.0005)))
    cerebro.adddata(bt.feeds.PandasData(dataname=inputs['frame_a'], timeframe=bt.TimeFrame.Days, compression=1), name=config['data']['asset_a_symbol'])
    cerebro.adddata(bt.feeds.PandasData(dataname=inputs['frame_b'], timeframe=bt.TimeFrame.Days, compression=1), name=config['data']['asset_b_symbol'])
    params = dict(config.get('params', {}))
    params['asset_a_symbol'] = config['data']['asset_a_symbol']
    params['asset_b_symbol'] = config['data']['asset_b_symbol']
    params['signal_lookup'] = inputs['signal_lookup']
    cerebro.addstrategy(PairsTradingStrategy, **params)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, compression=1, factor=252, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', tann=252)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, inputs, config):
    trades = strat.analyzers.trades.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = float(config['backtest']['initial_cash'])
    final_value = float(cerebro.broker.getvalue())
    broker_values = [value for _, value in getattr(strat, 'broker_value_series', [])] or [initial_cash, final_value]
    total_trades = trades.get('total', {}).get('total', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'strategy_name': config['strategy']['name'], 'fromdate': inputs['fromdate'], 'todate': inputs['todate'], 'bars': len(inputs['signal_df']),
        'bar_num': strat.bar_num, 'buy_count': strat.buy_count, 'sell_count': strat.sell_count,
        'long_spread_days': getattr(strat, 'long_spread_days', 0), 'short_spread_days': getattr(strat, 'short_spread_days', 0), 'flat_days': getattr(strat, 'flat_days', 0),
        'initial_cash': initial_cash, 'final_value': final_value, 'net_pnl': final_value - initial_cash, 'total_return_pct': (final_value / initial_cash - 1.0) * 100.0,
        'total_trades': total_trades, 'won': won, 'lost': lost, 'win_rate': (won / total_trades * 100.0) if total_trades else 0.0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None, 'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'sharpe_ratio': finite_or_none(sharpe.get('sharperatio')), 'annual_return_pct': (returns.get('rnorm') or 0.0) * 100.0, 'sqn': finite_or_none(sqn.get('sqn')),
        'ulcer_index': calculate_ulcer_index(broker_values),
    }


def normalize(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def write_local_result(config, metrics):
    path = (BASE_DIR / config['outputs']['local_result_json']).resolve()
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({key: normalize(value) for key, value in metrics.items()}, handle, ensure_ascii=False, indent=2)


def upsert_global_summary(config, metrics):
    path = (BASE_DIR / config['outputs']['global_summary_csv']).resolve()
    fieldnames = ['strategy_id', 'strategy_name', 'strategy_type', 'strategy_dir', 'symbol', 'timeframe', 'fromdate', 'todate', 'bars', 'total_trades', 'won', 'lost', 'win_rate', 'profit_factor', 'total_return_pct', 'annual_return_pct', 'max_drawdown', 'sharpe_ratio', 'final_value', 'net_pnl', 'sqn', 'ulcer_index']
    rows = []
    if path.exists():
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    rows = [row for row in rows if row.get('strategy_id') != config['strategy']['id']]
    rows.append({
        'strategy_id': config['strategy']['id'], 'strategy_name': config['strategy']['name'], 'strategy_type': BASE_DIR.parent.name, 'strategy_dir': BASE_DIR.name,
        'symbol': f"{config['data']['asset_a_symbol']}/{config['data']['asset_b_symbol']}", 'timeframe': config['data']['timeframe'],
        'fromdate': str(metrics.get('fromdate', '')), 'todate': str(metrics.get('todate', '')), 'bars': metrics.get('bars', 0), 'total_trades': metrics.get('total_trades', 0),
        'won': metrics.get('won', 0), 'lost': metrics.get('lost', 0), 'win_rate': metrics.get('win_rate', 0), 'profit_factor': metrics.get('profit_factor'),
        'total_return_pct': metrics.get('total_return_pct', 0), 'annual_return_pct': metrics.get('annual_return_pct', 0), 'max_drawdown': metrics.get('max_drawdown', 0),
        'sharpe_ratio': metrics.get('sharpe_ratio'), 'final_value': metrics.get('final_value', 0), 'net_pnl': metrics.get('net_pnl', 0), 'sqn': metrics.get('sqn'), 'ulcer_index': metrics.get('ulcer_index', 0),
    })
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def main():
    config = load_config()
    inputs = load_inputs(config)
    print(f"Loaded pairs-trading bars: {len(inputs['signal_df'])}")
    cerebro = build_cerebro(inputs, config)
    strat = cerebro.run()[0]
    metrics = extract_metrics(strat, cerebro, inputs, config)
    write_local_result(config, metrics)
    upsert_global_summary(config, metrics)
    print(metrics)




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
