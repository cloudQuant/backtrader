from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import csv
import datetime
import json
from pathlib import Path

import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent
import yaml

from strategy_gold_change_point_trading import GoldChangePointStrategy, Mt5ChangePointFeed, load_mt5_csv, prepare_change_point_features

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
TRADING_DAYS_PER_YEAR = 252


def get_sharpe_analyzer_kwargs(config):
    data_cfg = config.get('data', {}) if isinstance(config, dict) else {}
    timeframe_value = str(data_cfg.get('timeframe', 'D1')).upper()
    if timeframe_value.startswith('M') and timeframe_value[1:].isdigit():
        compression = max(1, int(timeframe_value[1:]))
        return dict(timeframe=bt.TimeFrame.Minutes, compression=compression, factor=252 * 24 * 60 / compression, annualize=True, riskfreerate=0)
    if timeframe_value.startswith('H') and timeframe_value[1:].isdigit():
        hours = max(1, int(timeframe_value[1:]))
        return dict(timeframe=bt.TimeFrame.Minutes, compression=hours * 60, factor=252 * 24 / hours, annualize=True, riskfreerate=0)
    return dict(timeframe=bt.TimeFrame.Days, compression=1, factor=252, annualize=True, riskfreerate=0)


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


def resolve_data_path(filename):
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    data_cfg = config['data']
    params = dict(config.get('params', {}))
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    raw = load_mt5_csv(
        resolve_data_path(data_cfg['file']),
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )
    frame = prepare_change_point_features(raw, params)
    if frame.empty:
        raise ValueError('Loaded data frame is empty after feature preparation')
    print(f"Loaded {len(frame)} bars: {frame.index[0]} -> {frame.index[-1]}")
    return {'data': frame, 'fromdate': fromdate, 'todate': todate, 'params': params}


def add_default_analyzers(cerebro, config):
    sharpe_kwargs = get_sharpe_analyzer_kwargs(config)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', **sharpe_kwargs)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Days, tann=TRADING_DAYS_PER_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')


def build_cerebro(config, frame):
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comminfo = ComminfoFuturesPercent(
        commission=float(bt_cfg.get('commission', 0.0)),
        margin=float(bt_cfg.get('margin', 0.01)),
        mult=float(bt_cfg.get('multiplier', 1.0)),
    )
    cerebro.broker.addcommissioninfo(comminfo)
    feed = Mt5ChangePointFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    strategy_params = dict(frame['params'])
    strategy_params['stop_loss_pct'] = float(frame['params'].get('stop_loss_pct', 0.02))
    strategy_params['take_profit_pct'] = float(frame['params'].get('take_profit_pct', 0.05))
    cerebro.addstrategy(GoldChangePointStrategy, **strategy_params)
    add_default_analyzers(cerebro, config)
    return cerebro


def normalize(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    isoformat = getattr(value, 'isoformat', None)
    if callable(isoformat):
        try:
            return value.isoformat(sep=' ')
        except TypeError:
            return value.isoformat()
    return str(value)


def finite_or_none(value):
    if value is None:
        return None
    if isinstance(value, float):
        if value != value:
            return None
        if value == float('inf') or value == float('-inf'):
            return None
    return value


def calculate_ulcer_index(equity_curve):
    if not equity_curve:
        return 0.0
    peak = None
    squared_drawdowns = []
    for value in equity_curve:
        peak = value if peak is None else max(peak, value)
        if peak and peak != 0:
            drawdown_pct = (value / peak - 1.0) * 100.0
            squared_drawdowns.append(drawdown_pct * drawdown_pct)
    if not squared_drawdowns:
        return 0.0
    return float(sum(squared_drawdowns) / len(squared_drawdowns)) ** 0.5


def extract_metrics(strat, cerebro, frame, config):
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    ta = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()

    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    broker_values = [value for _, value in getattr(strat, 'broker_value_series', [])] or [initial_cash, final_value]

    total_trades = ta.get('total', {}).get('total', 0)
    won = ta.get('won', {}).get('total', 0)
    lost = ta.get('lost', {}).get('total', 0)
    gross_won = ta.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(ta.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    long_signal_days = int((frame['data']['long_signal'] > 0.5).sum())
    short_signal_days = int((frame['data']['short_signal'] > 0.5).sum())

    return {
        'strategy_name': config['strategy']['name'],
        'fromdate': frame['fromdate'],
        'todate': frame['todate'],
        'bars': len(frame['data']),
        'bar_num': strat.bar_num,
        'long_signal_count': strat.long_signal_count,
        'short_signal_count': strat.short_signal_count,
        'long_signal_days': long_signal_days,
        'short_signal_days': short_signal_days,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'short_count': strat.short_count,
        'cover_count': strat.cover_count,
        'high_vol_exit_count': strat.high_vol_exit_count,
        'stop_exit_count': strat.stop_exit_count,
        'reverse_exit_count': strat.reverse_exit_count,
        'trade_count': total_trades,
        'win_count': won,
        'loss_count': lost,
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


def write_local_result(config, metrics):
    path = (BASE_DIR / config['outputs']['local_result_json']).resolve()
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({key: normalize(value) for key, value in metrics.items()}, handle, ensure_ascii=False, indent=2)


def upsert_global_summary(config, metrics):
    path = (BASE_DIR / config['outputs']['global_summary_csv']).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        'strategy_id', 'strategy_name', 'strategy_type', 'strategy_dir', 'symbol', 'timeframe',
        'fromdate', 'todate', 'bars', 'total_trades', 'won', 'lost', 'win_rate',
        'profit_factor', 'total_return_pct', 'annual_return_pct', 'max_drawdown',
        'sharpe_ratio', 'final_value', 'net_pnl', 'sqn', 'ulcer_index'
    ]
    row = {
        'strategy_id': config['strategy']['id'],
        'strategy_name': metrics['strategy_name'],
        'strategy_type': BASE_DIR.parent.name,
        'strategy_dir': BASE_DIR.name,
        'symbol': config['data']['symbol'],
        'timeframe': config['data']['timeframe'],
        'fromdate': normalize(metrics['fromdate']),
        'todate': normalize(metrics['todate']),
        'bars': metrics['bars'],
        'total_trades': metrics['total_trades'],
        'won': metrics['won'],
        'lost': metrics['lost'],
        'win_rate': metrics['win_rate'],
        'profit_factor': metrics['profit_factor'],
        'total_return_pct': metrics['total_return_pct'],
        'annual_return_pct': metrics['annual_return_pct'],
        'max_drawdown': metrics['max_drawdown'],
        'sharpe_ratio': metrics['sharpe_ratio'],
        'final_value': metrics['final_value'],
        'net_pnl': metrics['net_pnl'],
        'sqn': metrics['sqn'],
        'ulcer_index': metrics['ulcer_index'],
    }
    rows = []
    if path.exists():
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    rows = [existing for existing in rows if existing.get('strategy_id') != row['strategy_id']]
    rows.append({key: normalize(value) for key, value in row.items()})
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_report(metrics):
    print('\n' + '=' * 60)
    print('BACKTEST RESULTS — Gold Change Point Trading')
    print('=' * 60)
    print(f"  Period:            {metrics['fromdate']} -> {metrics['todate']}")
    print(f"  Bars:              {metrics['bars']}")
    print(f"  Processed bars:    {metrics['bar_num']}")
    print(f"  Long signal days:  {metrics['long_signal_days']}")
    print(f"  Short signal days: {metrics['short_signal_days']}")
    print(f"  Buy entries:       {metrics['buy_count']}")
    print(f"  Short entries:     {metrics['short_count']}")
    print(f"  Sell exits:        {metrics['sell_count']}")
    print(f"  Cover exits:       {metrics['cover_count']}")
    print(f"  High vol exits:    {metrics['high_vol_exit_count']}")
    print(f"  Reverse exits:     {metrics['reverse_exit_count']}")
    print(f"  Stop exits:        {metrics['stop_exit_count']}")
    print(f"  Initial capital:   {metrics['initial_cash']:,.2f}")
    print(f"  Final value:       {metrics['final_value']:,.2f}")
    print(f"  Net P&L:           {metrics['net_pnl']:,.2f}")
    print(f"  Return:            {metrics['total_return_pct']:.2f}%")
    print('-' * 60)
    print(f"  Total trades:      {metrics['total_trades']}")
    print(f"  Won:               {metrics['won']}")
    print(f"  Lost:              {metrics['lost']}")
    print(f"  Win rate:          {metrics['win_rate']:.2f}%")
    print(f"  Profit factor:     {metrics['profit_factor']}")
    print('-' * 60)
    print(f"  Sharpe ratio:      {metrics['sharpe_ratio']}")
    print(f"  Annual return:     {metrics['annual_return_pct']:.2f}%")
    print(f"  Max drawdown:      {metrics['max_drawdown']:.2f}%")
    print(f"  SQN:               {metrics['sqn']}")
    print(f"  Ulcer index:       {metrics['ulcer_index']:.2f}")
    print('=' * 60)


def run(plot=False):
    config = load_config()
    frame = load_backtest_frame(config)
    cerebro = build_cerebro(config, frame)
    print('\nStarting backtest...')
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, config)
    write_local_result(config, metrics)
    upsert_global_summary(config, metrics)
    print_report(metrics)
    if plot:
        cerebro.plot(style='candlestick')
    return results, metrics, cerebro




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
    parser = argparse.ArgumentParser(description='Run Gold Change Point Trading backtest.')
    parser.add_argument('--plot', action='store_true', help='Display backtrader chart after backtest')
    args = parser.parse_args()
    run(plot=args.plot)
