from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import datetime
import os
from pathlib import Path
import sys

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
WORKSPACE_DIR = BASE_DIR.parents[2]
LOCAL_BACKTRADER_REPO = WORKSPACE_DIR / 'backtrader'
if LOCAL_BACKTRADER_REPO.exists() and str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))

import backtrader as bt
import yaml

from strategy_exp_price_position import ExpPricePositionStrategy, Mt5PandasFeed, load_mt5_csv, resample_ohlc

MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def resolve_data_path(filename):
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_frames(config):
    data_cfg = config['data']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    base = load_mt5_csv(
        resolve_data_path(data_cfg['file']),
        fromdate=fromdate - datetime.timedelta(days=40),
        todate=todate,
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )
    if base.empty:
        raise ValueError('Loaded data frame is empty')
    h1 = resample_ohlc(base, '1h')
    d1 = resample_ohlc(base, '1D')
    h1 = h1[(h1.index >= fromdate) & (h1.index <= todate)]
    d1 = d1[d1.index <= todate]
    if h1.empty or d1.empty:
        raise ValueError('Required resampled frame is empty')
    print(f'Loaded H1 bars: {len(h1)} | D1 bars: {len(d1)}')
    return {'h1': h1, 'd1': d1, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frames):
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type', 'fixed') == 'fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(
        commission=bt_cfg['commission'],
        margin=bt_cfg['margin'],
        mult=bt_cfg['multiplier'],
        commtype=comm_type,
        stocklike=bt_cfg.get('stocklike', False),
    )
    h1_feed = Mt5PandasFeed(
        dataname=frames['h1'][['open', 'high', 'low', 'close', 'volume', 'openinterest']],
        timeframe=bt.TimeFrame.Minutes,
        compression=60,
    )
    d1_feed = Mt5PandasFeed(
        dataname=frames['d1'][['open', 'high', 'low', 'close', 'volume', 'openinterest']],
        timeframe=bt.TimeFrame.Days,
        compression=1,
    )
    cerebro.adddata(h1_feed, name=f"{config['data']['symbol']}_H1")
    cerebro.adddata(d1_feed, name=f"{config['data']['symbol']}_D1")
    cerebro.addstrategy(ExpPricePositionStrategy, **config.get('params', {}))
    trade_log_root = os.environ.get('BT_TRADE_LOG_DIR', '').strip()
    if trade_log_root:
        log_dir = Path(trade_log_root) / 'python'
        log_dir.mkdir(parents=True, exist_ok=True)
        cerebro.addobserver(
            bt.observers.TradeLogger,
            log_dir=str(log_dir),
            log_orders=True,
            log_trades=True,
            log_positions=True,
            log_indicators=True,
            log_signals=True,
            log_position_snapshot=False,
            log_format='json',
        )
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=60, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frames, config):
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    total_trades = trades.get('total', {}).get('closed', won + lost)
    return {
        'fromdate': frames['fromdate'],
        'todate': frames['todate'],
        'bars_h1': len(frames['h1']),
        'bars_d1': len(frames['d1']),
        'bar_num': strat.bar_num,
        'signal_count': strat.signal_count,
        'trade_count': strat.trade_count,
        'completed_orders': strat.completed_order_count,
        'rejected_orders': strat.rejected_order_count,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (returns.get('rtot') or 0) * 100,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100) if total_trades else 0,
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sqn': sqn.get('sqn'),
    }


def print_report(metrics):
    print('\n' + '=' * 60 + '\nBACKTEST RESULTS — EXP PRICE POSITION\n' + '=' * 60)
    for key in [
        'fromdate', 'todate', 'bars_h1', 'bars_d1', 'bar_num', 'signal_count',
        'trade_count', 'completed_orders', 'rejected_orders', 'initial_cash', 'final_value', 'net_pnl',
        'total_return_pct', 'total_trades', 'won', 'lost', 'win_rate', 'sharpe_ratio',
        'annual_return_pct', 'max_drawdown', 'sqn',
    ]:
        value = metrics[key]
        if isinstance(value, float):
            print(f'  {key:20s}: {value:,.2f}')
        else:
            print(f'  {key:20s}: {value}')
    print('=' * 60)


def run(plot=False):
    config = load_config()
    frames = load_frames(config)
    cerebro = build_cerebro(config, frames)
    print('\nStarting backtest...')
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frames, config)
    print_report(metrics)
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--plot', action='store_true')
    args = parser.parse_args()
    run(plot=args.plot)
