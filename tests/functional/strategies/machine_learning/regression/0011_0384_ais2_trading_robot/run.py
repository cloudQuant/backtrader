from __future__ import absolute_import, division, print_function, unicode_literals
from pathlib import Path

import io
import os
import sys
import yaml
import datetime as dt
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR)))
LOCAL_BACKTRADER_REPO = os.path.join(WORKSPACE_DIR, 'backtrader')
if os.path.isdir(LOCAL_BACKTRADER_REPO) and LOCAL_BACKTRADER_REPO not in sys.path:
    sys.path.insert(0, LOCAL_BACKTRADER_REPO)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import backtrader as bt

from strategy_ais2_trading_robot import Ais2TradingRobotStrategy



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

class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


def load_mt5_csv(filepath: str, fromdate=None, todate=None, bar_shift_minutes: int = 0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def load_config(path: str | None = None) -> dict:
    if path is None:
        path = os.path.join(SCRIPT_DIR, 'config.yaml')
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def run(cfg_path: str | None = None, plot: bool = False):
    cfg = load_config(cfg_path)

    data_cfg = cfg['data']
    params_cfg = cfg.get('params', {})
    bt_cfg = cfg.get('backtest', {})

    data_file = data_cfg['file']
    if not os.path.isabs(data_file):
        data_file = os.path.normpath(os.path.join(SCRIPT_DIR, data_file))
    if not os.path.exists(data_file):
        raise FileNotFoundError(f'Data file not found: {data_file}')

    fromdate = dt.datetime.strptime(data_cfg['fromdate'], '%Y-%m-%d %H:%M:%S')
    todate = dt.datetime.strptime(data_cfg['todate'], '%Y-%m-%d %H:%M:%S')
    frame = load_mt5_csv(data_file, fromdate=fromdate, todate=todate, bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if frame.empty:
        raise ValueError('Loaded data frame is empty')

    cerebro = bt.Cerebro()
    base_feed = Mt5PandasFeed(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=1)
    tf1_source = Mt5PandasFeed(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=1)
    tf2_source = Mt5PandasFeed(dataname=frame.copy(), timeframe=bt.TimeFrame.Minutes, compression=1)
    symbol = data_cfg.get('symbol', 'XAUUSD')
    tf1_minutes = 15 if data_cfg.get('signal_timeframe_1', 'M15') == 'M15' else 15
    tf2_minutes = 1 if data_cfg.get('signal_timeframe_2', 'M1') == 'M1' else 1
    cerebro.adddata(base_feed, name=f'{symbol}_M1')
    cerebro.resampledata(tf1_source, timeframe=bt.TimeFrame.Minutes, compression=tf1_minutes, name=f'{symbol}_{data_cfg.get("signal_timeframe_1", "M15")}')
    cerebro.resampledata(tf2_source, timeframe=bt.TimeFrame.Minutes, compression=tf2_minutes, name=f'{symbol}_{data_cfg.get("signal_timeframe_2", "M1")}')

    strat_kwargs = {}
    for key in (
        'account_reserve', 'order_reserve', 'symbol', 'take_factor', 'stop_factor', 'trail_factor',
        'lot_min', 'lot_step', 'lot_max', 'margin_per_lot', 'contract_size', 'point',
    ):
        if key in params_cfg:
            strat_kwargs[key] = params_cfg[key]

    cerebro.addstrategy(Ais2TradingRobotStrategy, **strat_kwargs)

    cerebro.broker.setcash(bt_cfg.get('initial_cash', 100000.0))
    cerebro.broker.setcommission(
        commission=bt_cfg.get('commission', 0.0),
        margin=bt_cfg.get('margin', 1000.0),
        mult=bt_cfg.get('multiplier', 100000.0),
        stocklike=bt_cfg.get('stocklike', False),
    )

    print(f'数据文件:  {data_file}')
    print(f'信号周期1: {data_cfg.get("signal_timeframe_1", "M15")}')
    print(f'信号周期2: {data_cfg.get("signal_timeframe_2", "M1")}')
    print(f'回测区间:  {fromdate} ~ {todate}')
    print(f'初始资金:  {cerebro.broker.getvalue():.2f}')
    print('-' * 50)

    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    print(f'\n最终权益: {final_value:.2f}')
    initial_cash = bt_cfg.get('initial_cash', 100000.0)
    metrics = {
        'fromdate': fromdate,
        'todate': todate,
        'bars': len(frame),
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': ((final_value / initial_cash) - 1.0) * 100.0 if initial_cash else 0.0,
        'total_trades': 0,
    }
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
    cfg = sys.argv[1] if len(sys.argv) > 1 else None
    run(cfg)