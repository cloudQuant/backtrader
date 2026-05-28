from __future__ import absolute_import, division, print_function, unicode_literals
import argparse, datetime
from pathlib import Path
import backtrader as bt
import yaml
from strategy_darkcloud_stoch import Mt5PandasFeed, DarkCloudStochStrategy, load_mt5_csv

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
    if not path.exists(): raise FileNotFoundError(f'Data file not found: {path}')
    return path

def load_backtest_frame(config):
    data_cfg = config['data']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    df = load_mt5_csv(resolve_data_path(data_cfg['file']), fromdate=fromdate, todate=todate,
                      bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if df.empty: raise ValueError('Loaded data frame is empty')
    print(f"Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}")
    return {'data': df, 'fromdate': fromdate, 'todate': todate}

def build_cerebro(config, frame):
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type','fixed')=='fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(commission=bt_cfg['commission'], margin=bt_cfg['margin'],
        mult=bt_cfg['multiplier'], commtype=comm_type, stocklike=bt_cfg.get('stocklike',False))
    feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(DarkCloudStochStrategy, **config.get('params', {}))
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
    ic = config['backtest']['initial_cash']; fv = cerebro.broker.getvalue()
    tt = trades.get('total',{}).get('total',0); w = trades.get('won',{}).get('total',0)
    l = trades.get('lost',{}).get('total',0)
    gw = trades.get('won',{}).get('pnl',{}).get('total',0) or 0
    gl = abs(trades.get('lost',{}).get('pnl',{}).get('total',0) or 0)
    return {'fromdate':frame['fromdate'],'todate':frame['todate'],'bars':len(frame['data']),
        'bar_num':strat.bar_num,'buy_count':strat.buy_count,'sell_count':strat.sell_count,
        'trade_count':strat.trade_count,'win_count':strat.win_count,'loss_count':strat.loss_count,
        'initial_cash':ic,'final_value':fv,'net_pnl':fv-ic,'total_return_pct':(fv/ic-1)*100,
        'total_trades':tt,'won':w,'lost':l,'win_rate':(w/tt*100) if tt else 0,
        'profit_factor':(gw/gl) if gl else None,'max_drawdown':drawdown.get('max',{}).get('drawdown',0),
        'sharpe_ratio':sharpe.get('sharperatio'),'annual_return_pct':(returns.get('rnorm') or 0)*100,
        'sqn':sqn.get('sqn')}

def print_report(m):
    print('\n'+'='*60+'\nBACKTEST RESULTS — Dark Cloud / Piercing + Stochastic\n'+'='*60)
    for k in ['fromdate','todate','bars','bar_num','buy_count','sell_count','trade_count',
              'initial_cash','final_value','net_pnl','total_return_pct','total_trades',
              'won','lost','win_rate','profit_factor','sharpe_ratio','annual_return_pct',
              'max_drawdown','sqn']:
        v=m[k]; print(f"  {k:20s}: {v:,.2f}" if isinstance(v,float) else f"  {k:20s}: {v}")
    print('='*60)

def run(plot=False):
    config=load_config(); frame=load_backtest_frame(config); cerebro=build_cerebro(config,frame)
    print('\nStarting backtest...'); results=cerebro.run(); strat=results[0]
    metrics=extract_metrics(strat,cerebro,frame,config); print_report(metrics)
    if plot: cerebro.plot()
    return results,metrics,cerebro



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


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--plot',action='store_true'); a=p.parse_args()
    run(plot=a.plot)
