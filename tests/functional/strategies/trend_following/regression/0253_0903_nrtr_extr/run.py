from __future__ import absolute_import, division, print_function, unicode_literals
import argparse, datetime, sys
from pathlib import Path
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path: sys.path.insert(0, str(BACKTRADER_REPO))
import backtrader as bt, yaml
from strategy_nrtr_extr import ExpNRTRExtrStrategy, Mt5PandasFeed, load_mt5_csv
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
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as f: return yaml.safe_load(f)

def resolve_data_path(fn):
    p = (BASE_DIR / fn).resolve()
    if not p.exists(): raise FileNotFoundError(f'Data file not found: {p}')
    return p

def load_backtest_frame(cfg):
    dc = cfg['data']
    fd = datetime.datetime.fromisoformat(dc['fromdate'])
    td = datetime.datetime.fromisoformat(dc['todate'])
    df = load_mt5_csv(resolve_data_path(dc['file']), fromdate=fd, todate=td, bar_shift_minutes=dc.get('bar_shift_minutes', 0))
    if df.empty: raise ValueError('Empty data')
    print(f"Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}")
    return {'data': df, 'fromdate': fd, 'todate': td}

def build_signal_frame(df, mins):
    r = f'{int(mins)}min'
    s = df.resample(r, label='right', closed='right').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum','openinterest':'last'})
    s = s.dropna(subset=['open','high','low','close'])
    if 'openinterest' in s.columns: s['openinterest'] = s['openinterest'].fillna(0)
    return s

def build_cerebro(cfg, frame):
    bc = cfg['backtest']; p = cfg.get('params', {}); im = p.get('indicator_minutes', 60)
    sf = build_signal_frame(frame['data'], im)
    if sf.empty: raise ValueError('Empty signal frame')
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bc['initial_cash'])
    ct = bt.CommInfoBase.COMM_FIXED if bc.get('commission_type','fixed')=='fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(commission=bc['commission'], margin=bc['margin'], mult=bc['multiplier'], commtype=ct, stocklike=bc.get('stocklike', False))
    cerebro.adddata(Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15), name=f"{cfg['data']['symbol']}_{cfg['data']['timeframe']}")
    cerebro.adddata(Mt5PandasFeed(dataname=sf, timeframe=bt.TimeFrame.Minutes, compression=im), name=f"{cfg['data']['symbol']}_{cfg['data']['indicator_timeframe']}")
    sp = dict(p); sp.pop('indicator_minutes', None)
    cerebro.addstrategy(ExpNRTRExtrStrategy, **sp)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro

def extract_metrics(strat, cerebro, frame, cfg):
    sh = strat.analyzers.sharpe.get_analysis(); rt = strat.analyzers.returns.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis(); tr = strat.analyzers.trades.get_analysis()
    sq = strat.analyzers.sqn.get_analysis(); ic = cfg['backtest']['initial_cash']; fv = cerebro.broker.getvalue()
    tt = tr.get('total',{}).get('total',0); w = tr.get('won',{}).get('total',0); l = tr.get('lost',{}).get('total',0)
    gw = tr.get('won',{}).get('pnl',{}).get('total',0) or 0; gl = abs(tr.get('lost',{}).get('pnl',{}).get('total',0) or 0)
    return {'fromdate':frame['fromdate'],'todate':frame['todate'],'bars':len(frame['data']),'bar_num':strat.bar_num,
            'signal_count':strat.signal_count,'buy_count':strat.buy_count,'sell_count':strat.sell_count,
            'trade_count':strat.trade_count,'win_count':strat.win_count,'loss_count':strat.loss_count,
            'initial_cash':ic,'final_value':fv,'net_pnl':fv-ic,'total_return_pct':(fv/ic-1)*100,
            'total_trades':tt,'won':w,'lost':l,'win_rate':(w/tt*100) if tt else 0,
            'profit_factor':(gw/gl) if gl else None,'max_drawdown':dd.get('max',{}).get('drawdown',0),
            'sharpe_ratio':sh.get('sharperatio'),'annual_return_pct':(rt.get('rnorm') or 0)*100,'sqn':sq.get('sqn')}

def print_report(m):
    print('\n'+'='*60+'\nBACKTEST RESULTS — NRTR_extr\n'+'='*60)
    for k in ['fromdate','todate','bars','bar_num','signal_count','buy_count','sell_count','trade_count',
              'initial_cash','final_value','net_pnl','total_return_pct','total_trades','won','lost',
              'win_rate','profit_factor','sharpe_ratio','annual_return_pct','max_drawdown','sqn']:
        v = m[k]; print(f"  {k:20s}: {v:,.2f}" if isinstance(v, float) else f"  {k:20s}: {v}")
    print('='*60)

def run(plot=False):
    cfg = load_config(); frame = load_backtest_frame(cfg); cerebro = build_cerebro(cfg, frame)
    print('\nStarting backtest...'); results = cerebro.run(); strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, cfg); print_report(metrics)
    if plot: cerebro.plot()
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
    parser = argparse.ArgumentParser(); parser.add_argument('--plot', action='store_true')
    run(plot=parser.parse_args().plot)
