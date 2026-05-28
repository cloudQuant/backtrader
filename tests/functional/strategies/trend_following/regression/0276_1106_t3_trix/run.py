from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import json
from pathlib import Path

import backtrader.analyzers as btanalyzers
from backtrader.cerebro import Cerebro
from backtrader.comminfo import CommInfoBase
from backtrader.dataseries import TimeFrame
import pandas as pd
import yaml

from strategy_t3_trix import Mt5PandasFeed, T3TrixStrategy, load_mt5_csv

MINUTES_PER_TRADING_YEAR = 252 * 24 * 60



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

def load_config(config_path):
    with open(config_path, 'r', encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def prepare_frame(config, base_dir):
    data_cfg = config['data']
    fromdate = pd.Timestamp(data_cfg['fromdate']) if data_cfg.get('fromdate') else None
    todate = pd.Timestamp(data_cfg['todate']) if data_cfg.get('todate') else None
    filepath = (base_dir / data_cfg['file']).resolve()
    data = load_mt5_csv(
        filepath,
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=int(data_cfg.get('bar_shift_minutes', 0)),
    )
    return {'data': data, 'fromdate': fromdate, 'todate': todate, 'filepath': str(filepath)}


def build_cerebro(config, frame):
    bt_cfg = config['backtest']
    cerebro = Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type', 'fixed') == 'fixed' else CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(
        commission=bt_cfg['commission'],
        margin=bt_cfg['margin'],
        mult=bt_cfg['multiplier'],
        commtype=comm_type,
        stocklike=bt_cfg.get('stocklike', False),
    )
    feed = Mt5PandasFeed(dataname=frame['data'], timeframe=TimeFrame.Minutes, compression=15)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(T3TrixStrategy, **config.get('params', {}))
    cerebro.addanalyzer(
        btanalyzers.SharpeRatio,
        _name='sharpe',
        timeframe=TimeFrame.Minutes,
        factor=MINUTES_PER_TRADING_YEAR,
        annualize=True,
        riskfreerate=0,
    )
    cerebro.addanalyzer(
        btanalyzers.Returns,
        _name='returns',
        timeframe=TimeFrame.Minutes,
        compression=15,
        tann=MINUTES_PER_TRADING_YEAR,
    )
    cerebro.addanalyzer(btanalyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(btanalyzers.SQN, _name='sqn')
    return cerebro


def _get_nested(mapping, *keys, default=0):
    current = mapping
    for key in keys:
        if current is None:
            return default
        if hasattr(current, key):
            current = getattr(current, key)
        elif isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def extract_metrics(strategy, cerebro):
    sharpe = strategy.analyzers.sharpe.get_analysis()
    returns = strategy.analyzers.returns.get_analysis()
    drawdown = strategy.analyzers.drawdown.get_analysis()
    trades = strategy.analyzers.trades.get_analysis()
    sqn = strategy.analyzers.sqn.get_analysis()

    return {
        'final_value': round(cerebro.broker.getvalue(), 2),
        'net_pnl': round(cerebro.broker.getvalue() - cerebro.broker.startingcash, 2),
        'total_trades': int(_get_nested(trades, 'total', 'closed', default=0)),
        'won_trades': int(_get_nested(trades, 'won', 'total', default=0)),
        'lost_trades': int(_get_nested(trades, 'lost', 'total', default=0)),
        'buy_signals': int(getattr(strategy, 'buy_signal_count', 0)),
        'sell_signals': int(getattr(strategy, 'sell_signal_count', 0)),
        'buy_orders': int(getattr(strategy, 'buy_count', 0)),
        'sell_orders': int(getattr(strategy, 'sell_count', 0)),
        'completed_orders': int(getattr(strategy, 'completed_order_count', 0)),
        'rejected_orders': int(getattr(strategy, 'rejected_order_count', 0)),
        'max_drawdown_pct': round(float(_get_nested(drawdown, 'max', 'drawdown', default=0.0)), 4),
        'returns_rtot': round(float(returns.get('rtot', 0.0)), 6),
        'returns_rnorm': round(float(returns.get('rnorm', 0.0)), 6),
        'returns_rnorm100': round(float(returns.get('rnorm100', 0.0)), 4),
        'sharpe': None if sharpe.get('sharperatio') is None else round(float(sharpe.get('sharperatio')), 6),
        'sqn': None if sqn.get('sqn') is None else round(float(sqn.get('sqn')), 6),
    }


def main():
    parser = argparse.ArgumentParser(description='Run the 1106 T3 TRIX Backtrader example')
    parser.add_argument('--config', default='config.yaml', help='Path to config.yaml')
    parser.add_argument('--plot', action='store_true', help='Plot after backtest')
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    config_path = (base_dir / args.config).resolve()
    config = load_config(config_path)
    frame = prepare_frame(config, base_dir)
    cerebro = build_cerebro(config, frame)
    results = cerebro.run()
    strategy = results[0]
    metrics = extract_metrics(strategy, cerebro)

    print(json.dumps({
        'strategy': config['strategy']['name'],
        'source_ea': config['strategy']['source_ea'],
        'data_file': frame['filepath'],
        'fromdate': None if frame['fromdate'] is None else str(frame['fromdate']),
        'todate': None if frame['todate'] is None else str(frame['todate']),
        'params': config.get('params', {}),
        'metrics': metrics,
    }, ensure_ascii=False, indent=2))

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
