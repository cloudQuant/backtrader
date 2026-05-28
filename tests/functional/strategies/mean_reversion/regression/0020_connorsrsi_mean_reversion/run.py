from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import csv
import datetime
import json
from pathlib import Path

import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent
import yaml

from strategy_connorsrsi_mean_reversion import ConnorsRSIMeanReversionStrategy, Mt5ConnorsFeed, load_mt5_csv, prepare_connors_features

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
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def resolve_data_path(filename):
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    data_cfg = config['data']
    raw = load_mt5_csv(
        resolve_data_path(data_cfg['file']),
        fromdate=datetime.datetime.fromisoformat(data_cfg['fromdate']),
        todate=datetime.datetime.fromisoformat(data_cfg['todate']),
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )
    frame = prepare_connors_features(raw, config.get('params', {}))
    if frame.empty:
        raise ValueError('Loaded data frame is empty after feature preparation')
    print(f"Loaded {len(frame)} bars: {frame.index[0]} -> {frame.index[-1]}")
    return frame


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
    cerebro.adddata(Mt5ConnorsFeed(dataname=frame, timeframe=bt.TimeFrame.Days, compression=1), name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(ConnorsRSIMeanReversionStrategy, **config.get('params', {}))
    sharpe_kwargs = get_sharpe_analyzer_kwargs(config)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', **sharpe_kwargs)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Days, tann=TRADING_DAYS_PER_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def normalize(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, 'isoformat'):
        try:
            return value.isoformat(sep=' ')
        except TypeError:
            return value.isoformat()
    return str(value)


def finite_or_none(value):
    if value is None:
        return None
    if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
        return None
    return value


def ulcer_index(values):
    if not values:
        return 0.0
    peak = values[0]
    squares = []
    for value in values:
        peak = max(peak, value)
        if peak:
            dd = (value / peak - 1.0) * 100.0
            squares.append(dd * dd)
    return (sum(squares) / len(squares)) ** 0.5 if squares else 0.0


def extract_metrics(strat, cerebro, frame, config):
    """提取回测指标 - 参考 trend_pullback 实现"""
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    ta = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    broker_values = [v for _, v in getattr(strat, 'broker_value_series', [])] or [initial_cash, final_value]
    
    # 从 TradeAnalyzer 获取交易统计
    total_trades = ta.get('total', {}).get('total', 0)
    won = ta.get('won', {}).get('total', 0)
    lost = ta.get('lost', {}).get('total', 0)
    gross_won = ta.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(ta.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    
    return {
        'strategy_name': config['strategy']['name'],
        'fromdate': config['data']['fromdate'],
        'todate': config['data']['todate'],
        'bars': len(frame),
        'bar_num': strat.bar_num,
        'setup_count': strat.setup_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'trade_count': total_trades,
        'win_count': won,
        'loss_count': lost,
        'expired_count': strat.expired_count,
        'cancelled_count': strat.cancelled_count,
        'rejected_count': strat.rejected_count,
        'precomputed_setup_days': int((frame['setup_signal'] >= 0.5).sum()),
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
        'ulcer_index': ulcer_index(broker_values),
    }


def save_outputs(config, metrics):
    local_path = (BASE_DIR / config['outputs']['local_result_json']).resolve()
    with open(local_path, 'w', encoding='utf-8') as f:
        json.dump({k: normalize(v) for k, v in metrics.items()}, f, ensure_ascii=False, indent=2)
    summary_path = (BASE_DIR / config['outputs']['global_summary_csv']).resolve()
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['strategy_id', 'strategy_name', 'strategy_type', 'strategy_dir', 'symbol', 'timeframe', 'fromdate', 'todate', 'bars', 'total_trades', 'won', 'lost', 'win_rate', 'profit_factor', 'total_return_pct', 'annual_return_pct', 'max_drawdown', 'sharpe_ratio', 'final_value', 'net_pnl', 'sqn', 'ulcer_index']
    row = {
        'strategy_id': config['strategy']['id'], 'strategy_name': metrics['strategy_name'], 'strategy_type': BASE_DIR.parent.name, 'strategy_dir': BASE_DIR.name,
        'symbol': config['data']['symbol'], 'timeframe': config['data']['timeframe'], 'fromdate': metrics['fromdate'], 'todate': metrics['todate'],
        'bars': metrics['bars'], 'total_trades': metrics['total_trades'], 'won': metrics['won'], 'lost': metrics['lost'], 'win_rate': metrics['win_rate'],
        'profit_factor': metrics['profit_factor'], 'total_return_pct': metrics['total_return_pct'], 'annual_return_pct': metrics['annual_return_pct'],
        'max_drawdown': metrics['max_drawdown'], 'sharpe_ratio': metrics['sharpe_ratio'], 'final_value': metrics['final_value'], 'net_pnl': metrics['net_pnl'],
        'sqn': metrics['sqn'], 'ulcer_index': metrics['ulcer_index'],
    }
    rows = []
    if summary_path.exists():
        with open(summary_path, 'r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
    rows = [r for r in rows if r.get('strategy_id') != row['strategy_id']]
    rows.append({k: normalize(v) for k, v in row.items()})
    with open(summary_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(plot=False):
    config = load_config()
    frame = load_backtest_frame(config)
    cerebro = build_cerebro(config, frame)
    print('\nStarting backtest...')
    results = cerebro.run()
    metrics = extract_metrics(results[0], cerebro, frame, config)
    save_outputs(config, metrics)
    print(json.dumps({k: normalize(v) for k, v in metrics.items()}, ensure_ascii=False, indent=2))
    if plot:
        cerebro.plot()
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
    parser = argparse.ArgumentParser(description='Run ConnorsRSI Mean Reversion backtest')
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()
    run(plot=args.plot)
