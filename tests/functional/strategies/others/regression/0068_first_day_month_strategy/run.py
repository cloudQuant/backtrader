#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import absolute_import, division, print_function, unicode_literals

import csv
import json
import math
from datetime import datetime
from pathlib import Path

import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent
import yaml

from strategy_first_day_month import (
    FirstDayMonthFeed,
    FirstDayMonthStrategy,
    load_mt5_csv,
    prepare_first_day_month_features,
)

BASE_DIR = Path(__file__).resolve().parent

# Vendored benchmark output hook (auto-edited by migrate_regression.py)
from pathlib import Path as _BenchmarkPath
import sys as _benchmark_sys
_BENCHMARK_BASE_DIR = _BenchmarkPath(__file__).resolve().parent
_REPO_ROOT = _BenchmarkPath(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in _benchmark_sys.path:
    _benchmark_sys.path.insert(0, str(_REPO_ROOT))
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


def resolve_data_file(file_value):
    path_value = Path(str(file_value))
    candidates = []
    if path_value.is_absolute():
        candidates.append(path_value)
    candidates.append((BASE_DIR / path_value).resolve())
    candidates.append((Path(__file__).resolve().parents[6] / 'tests' / 'datas' / path_value.name).resolve())
    candidates.append((Path(__file__).resolve().parents[6] / 'tests' / 'datas' / 'mt5_1d_data' / path_value.name).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError('Could not resolve data file from config: {0}'.format(file_value))


def load_backtest_frame(config):
    data_cfg = config['data']
    fromdate = datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.fromisoformat(data_cfg['todate'])
    price_df = load_mt5_csv(resolve_data_file(data_cfg['file']), fromdate=fromdate, todate=todate)
    feature_df = prepare_first_day_month_features(price_df, config.get('params', {}))
    if feature_df.empty:
        raise ValueError('Loaded data frame is empty after feature preparation')
    return {'data': feature_df, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frame):
    cerebro = bt.Cerebro(stdstats=True)
    bt_cfg = config['backtest']
    cerebro.broker.setcash(float(bt_cfg['initial_cash']))
    comminfo = ComminfoFuturesPercent(
        commission=float(bt_cfg.get('commission', 0.0)),
        margin=float(bt_cfg.get('margin', 0.01)),
        mult=float(bt_cfg.get('multiplier', 1.0)),
    )
    cerebro.broker.addcommissioninfo(comminfo)
    feed = FirstDayMonthFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(feed, name=config['data']['symbol'])
    cerebro.addstrategy(FirstDayMonthStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, compression=1, factor=252, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Days, tann=252)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
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
        'strategy_name': config['strategy']['name'],
        'fromdate': frame['fromdate'],
        'todate': frame['todate'],
        'bars': len(frame['data']),
        'bar_num': strat.bar_num,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'signal_days': getattr(strat, 'signal_days', 0),
        'skipped_month_days': getattr(strat, 'skipped_month_days', 0),
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1.0) * 100.0,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100.0) if total_trades else 0.0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'sharpe_ratio': finite_or_none(sharpe.get('sharperatio')),
        'annual_return_pct': (returns.get('rnorm') or 0.0) * 100.0,
        'sqn': finite_or_none(sqn.get('sqn')),
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
    rows = [row for row in rows if row.get('strategy_id') != str(config['strategy']['id'])]
    rows.append({
        'strategy_id': config['strategy']['id'],
        'strategy_name': config['strategy']['name'],
        'strategy_type': BASE_DIR.parent.name,
        'strategy_dir': BASE_DIR.name,
        'symbol': config['data']['symbol'],
        'timeframe': config['data']['timeframe'],
        'fromdate': str(metrics.get('fromdate', '')),
        'todate': str(metrics.get('todate', '')),
        'bars': metrics.get('bars', 0),
        'total_trades': metrics.get('total_trades', 0),
        'won': metrics.get('won', 0),
        'lost': metrics.get('lost', 0),
        'win_rate': f"{metrics.get('win_rate', 0):.2f}",
        'profit_factor': f"{metrics.get('profit_factor'):.4f}" if metrics.get('profit_factor') else '',
        'total_return_pct': f"{metrics.get('total_return_pct', 0):.2f}",
        'annual_return_pct': f"{metrics.get('annual_return_pct', 0):.2f}",
        'max_drawdown': f"{metrics.get('max_drawdown', 0):.2f}",
        'sharpe_ratio': f"{metrics.get('sharpe_ratio'):.4f}" if metrics.get('sharpe_ratio') else '',
        'final_value': f"{metrics.get('final_value', 0):.2f}",
        'net_pnl': f"{metrics.get('net_pnl', 0):.2f}",
        'sqn': f"{metrics.get('sqn'):.4f}" if metrics.get('sqn') else '',
        'ulcer_index': f"{metrics.get('ulcer_index', 0):.2f}",
    })
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def print_results(metrics):
    print('\n' + '=' * 60)
    print(f"BACKTEST RESULTS — {metrics['strategy_name']}")
    print('=' * 60)
    print(f"  Period:              {metrics['fromdate']} -> {metrics['todate']}")
    print(f"  Bars:                {metrics['bars']}")
    print(f"  Buy entries:         {metrics['buy_count']}")
    print(f"  Sell exits:          {metrics['sell_count']}")
    print(f"  Signal days:         {metrics['signal_days']}")
    print(f"  Skipped month days:  {metrics['skipped_month_days']}")
    print(f"  Final value:         {metrics['final_value']:,.2f}")
    print(f"  Return:              {metrics['total_return_pct']:.2f}%")
    print(f"  Total trades:        {metrics['total_trades']}")
    print(f"  Won/Lost:            {metrics['won']}/{metrics['lost']}")
    print(f"  Win rate:            {metrics['win_rate']:.2f}%")
    print(f"  Sharpe ratio:        {metrics['sharpe_ratio']}")
    print(f"  Annual return:       {metrics['annual_return_pct']:.2f}%")
    print(f"  Max drawdown:        {metrics['max_drawdown']:.2f}%")
    print('=' * 60)


def run(plot=False):
    config = load_config()
    frame = load_backtest_frame(config)
    print(f"Loaded first-day bars: {len(frame['data'])}")
    cerebro = build_cerebro(config, frame)
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, config)
    write_local_result(config, metrics)
    upsert_global_summary(config, metrics)
    print_results(metrics)
    if plot:
        cerebro.plot()
    return metrics




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
    run()
