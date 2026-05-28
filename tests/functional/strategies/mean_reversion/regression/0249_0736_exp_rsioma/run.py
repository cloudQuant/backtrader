from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import datetime
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

from strategy_exp_rsioma import ExpRSIOMAStrategy, Mt5PandasFeed, RSIOMAFeed, compute_rsioma, load_mt5_csv, resample_frame

MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def resolve_data_path(filename):
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frames(config):
    data_cfg = config['data']
    ind_cfg = config['indicator']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    base = load_mt5_csv(resolve_data_path(data_cfg['file']), fromdate=fromdate, todate=todate, bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if base.empty:
        raise ValueError('Loaded data frame is empty')
    indicator_tf = resample_frame(base, f"{data_cfg.get('indicator_timeframe_minutes', 240)}min")
    rsioma = compute_rsioma(
        indicator_tf,
        rsioma_method=ind_cfg.get('rsioma_method', 'ema'),
        rsioma=ind_cfg.get('rsioma', 14),
        marsioma_method=ind_cfg.get('marsioma_method', 'ema'),
        marsioma=ind_cfg.get('marsioma', 21),
        mom_period=ind_cfg.get('mom_period', 1),
        price_type=ind_cfg.get('price_type', 'close'),
    )
    print(f'Loaded bars: base={len(base)}, indicator_tf={len(indicator_tf)}, rsioma={len(rsioma)}')
    return {'base': base, 'rsioma': rsioma, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frame):
    bt_cfg = config['backtest']
    indicator_tf = config['data'].get('indicator_timeframe_minutes', 240)
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type', 'fixed') == 'fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(commission=bt_cfg['commission'], margin=bt_cfg['margin'], mult=bt_cfg['multiplier'], commtype=comm_type, stocklike=bt_cfg.get('stocklike', False))
    base_df = frame['base'].copy()
    base_df['volume'] = base_df['tick_volume']
    ind_df = frame['rsioma'][['open', 'high', 'low', 'close', 'volume', 'openinterest', 'rsioma', 'trigger']]
    cerebro.adddata(Mt5PandasFeed(dataname=base_df[['open', 'high', 'low', 'close', 'volume', 'openinterest']], timeframe=bt.TimeFrame.Minutes, compression=15), name='XAUUSD_M15')
    cerebro.adddata(RSIOMAFeed(dataname=ind_df, timeframe=bt.TimeFrame.Minutes, compression=indicator_tf), name='RSIOMA')
    cerebro.addstrategy(ExpRSIOMAStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
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
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'fromdate': frame['fromdate'],
        'todate': frame['todate'],
        'bars_base': len(frame['base']),
        'bars_rsioma': len(frame['rsioma']),
        'bar_num': strat.bar_num,
        'signal_count': strat.signal_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'trade_count': strat.trade_count,
        'completed_orders': strat.completed_order_count,
        'rejected_orders': strat.rejected_order_count,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1) * 100,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100) if total_trades else 0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sqn': sqn.get('sqn'),
    }


def print_report(metrics):
    print('\n' + '=' * 60 + '\nBACKTEST RESULTS — Exp_RSIOMA\n' + '=' * 60)
    for key in [
        'fromdate', 'todate', 'bars_base', 'bars_rsioma', 'bar_num', 'signal_count', 'buy_count', 'sell_count', 'trade_count',
        'completed_orders', 'rejected_orders', 'initial_cash', 'final_value', 'net_pnl', 'total_return_pct', 'total_trades',
        'won', 'lost', 'win_rate', 'profit_factor', 'sharpe_ratio', 'annual_return_pct', 'max_drawdown', 'sqn',
    ]:
        value = metrics[key]
        if isinstance(value, float):
            print(f'  {key:20s}: {value:,.2f}')
        else:
            print(f'  {key:20s}: {value}')
    print('=' * 60)


def run(plot=False):
    config = load_config()
    frame = load_backtest_frames(config)
    cerebro = build_cerebro(config, frame)
    print('\nStarting backtest...')
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, config)
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
