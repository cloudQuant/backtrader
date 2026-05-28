from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import datetime as dt
import io
import json
import os
from pathlib import Path

import backtrader as bt
import pandas as pd
import yaml

from strategy_expotest import ExpotestStrategy

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


def load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = [line.strip().strip('\"') for line in f.readlines() if line.strip()]
    raw = '\n'.join(lines)
    df = pd.read_csv(io.StringIO(raw), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    df = df.sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


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


def calculate_ulcer_index(equity_curve):
    if not equity_curve:
        return 0.0
    peak = None
    squares = []
    for value in equity_curve:
        peak = value if peak is None else max(peak, value)
        if peak and peak != 0:
            dd = (value / peak - 1.0) * 100.0
            squares.append(dd * dd)
    return (sum(squares) / len(squares)) ** 0.5 if squares else 0.0


def build_signal_feed(cerebro, base_feed, signal_tf):
    tf_map = {
        'M1': (bt.TimeFrame.Minutes, 1),
        'M5': (bt.TimeFrame.Minutes, 5),
        'M15': (bt.TimeFrame.Minutes, 15),
        'M30': (bt.TimeFrame.Minutes, 30),
        'H1': (bt.TimeFrame.Minutes, 60),
        'H4': (bt.TimeFrame.Minutes, 240),
        'D1': (bt.TimeFrame.Days, 1),
    }
    tf, comp = tf_map.get(signal_tf, (bt.TimeFrame.Minutes, 15))
    if comp == 15:
        return None
    return cerebro.resampledata(base_feed, timeframe=tf, compression=comp, name=f'XAUUSD_{signal_tf}')


def run(cfg_path: str | None = None, plot=False):
    if cfg_path is None:
        cfg_path = str(BASE_DIR / 'config.yaml')
    cfg = load_config(cfg_path)

    data_cfg = cfg['data']
    params_cfg = cfg.get('params', {})
    bt_cfg = cfg.get('backtest', {})

    data_file = data_cfg['file']
    if not os.path.isabs(data_file):
        data_file = str((BASE_DIR / data_file).resolve())

    fromdate = dt.datetime.fromisoformat(data_cfg['fromdate'])
    todate = dt.datetime.fromisoformat(data_cfg['todate'])
    df = load_mt5_csv(
        data_file,
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )

    cerebro = bt.Cerebro()
    base_feed = bt.feeds.PandasData(
        dataname=df,
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
    )
    cerebro.adddata(base_feed, name='XAUUSD_M15')

    signal_tf = data_cfg.get('signal_timeframe', 'M15')
    signal_data = build_signal_feed(cerebro, base_feed, signal_tf)
    if signal_data is not None:
        pass
    else:
        signal_data = base_feed

    strat_kwargs = {
        'signal_timeframe': signal_tf,
    }
    for key in (
        'sl_points', 'tp_points', 'volume', 'risk', 'magic',
        'slippage_points', 'sar_step', 'sar_maximum', 'point', 'min_lot', 'max_lot',
        'lot_step', 'contract_size', 'margin_per_lot', 'loss_multiplier',
    ):
        if key in params_cfg:
            strat_kwargs[key] = params_cfg[key]

    cerebro.addstrategy(ExpotestStrategy, **strat_kwargs)
    cerebro.broker.setcash(bt_cfg.get('initial_cash', 100000.0))
    cerebro.broker.setcommission(
        commission=bt_cfg.get('commission', 0.0),
        margin=bt_cfg.get('margin', 1000.0),
        mult=bt_cfg.get('multiplier', 100.0),
        stocklike=bt_cfg.get('stocklike', False),
    )
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=252 * 24 * 60, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=252 * 24 * 60)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

    print(f'数据文件:  {data_file}')
    print(f'信号周期:  {signal_tf}')
    print(f'回测区间:  {fromdate} ~ {todate}')
    print(f'初始资金:  {cerebro.broker.getvalue():.2f}')
    print('-' * 50)

    results = cerebro.run()
    strategy = results[0]
    final_value = cerebro.broker.getvalue()

    trades = strategy.analyzers.trades.get_analysis()
    returns = strategy.analyzers.returns.get_analysis()
    sharpe = strategy.analyzers.sharpe.get_analysis()
    drawdown = strategy.analyzers.drawdown.get_analysis()
    sqn = strategy.analyzers.sqn.get_analysis()

    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    total_trades = trades.get('total', {}).get('closed', won + lost)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    initial_cash = bt_cfg.get('initial_cash', 0)

    metrics = {
        'bars': len(df),
        'bar_num': len(df),
        'buy_count': strategy.buy_count,
        'sell_count': strategy.sell_count,
        'trade_count': strategy.trade_count,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100.0) if total_trades else 0.0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1.0) * 100.0 if initial_cash else 0.0,
        'annual_return_pct': (returns.get('rnorm') or 0.0) * 100.0,
        'sharpe_ratio': sharpe.get('sharperatio'),
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'sqn': sqn.get('sqn'),
        'ulcer_index': calculate_ulcer_index([initial_cash, final_value]),
    }

    with open(BASE_DIR / 'backtest_result.json', 'w', encoding='utf-8') as f:
        json.dump({key: normalize(value) for key, value in metrics.items()}, f, ensure_ascii=False, indent=2)

    if plot:
        cerebro.plot()
    print(f'\\n最终权益: {final_value:.2f}')
    return results, metrics, cerebro


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(BASE_DIR / 'config.yaml'))
    parser.add_argument('--plot', action='store_true')
    return parser.parse_args()




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
    args = parse_args()
    if args.config and args.config != str(BASE_DIR / 'config.yaml'):
        cfg = args.config
    else:
        cfg = None
    run(cfg, plot=args.plot)
