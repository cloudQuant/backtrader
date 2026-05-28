from __future__ import absolute_import, division, print_function, unicode_literals

import csv, json, math
from datetime import datetime
from pathlib import Path

import backtrader as bt
import yaml
from strategy_fifty_fifty import FiftyFiftyFeed, FiftyFiftyStrategy, load_mt5_csv, prepare_fifty_fifty_features

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


def finite_or_none(v):
    return v if v is not None and math.isfinite(v) else None


def ulcer(vals):
    if len(vals) < 2:
        return 0.0
    peak = vals[0]
    sq = 0.0
    for v in vals:
        peak = max(peak, v)
        dd = (peak - v) / peak * 100.0 if peak > 0 else 0.0
        sq += dd ** 2
    return math.sqrt(sq / len(vals))


def load_config():
    return yaml.safe_load((BASE_DIR / 'config.yaml').read_text(encoding='utf-8')) or {}


def load_frame(config):
    d = config['data']
    fd, td = datetime.fromisoformat(d['fromdate']), datetime.fromisoformat(d['todate'])
    raw = load_mt5_csv(d['file'], fromdate=fd, todate=td)
    df = prepare_fifty_fifty_features(raw, config.get('params', {}))
    return {'data': df, 'fromdate': fd, 'todate': td}


def build_cerebro(frame, config):
    c = bt.Cerebro(stdstats=False)
    c.broker.setcash(float(config['backtest']['initial_cash']))
    c.broker.setcommission(commission=float(config['params'].get('commission_pct', 0.0005)))
    c.adddata(FiftyFiftyFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Days, compression=1), name=config['data']['symbol'])
    c.addstrategy(FiftyFiftyStrategy, **config.get('params', {}))
    c.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, compression=1, factor=252, annualize=True, riskfreerate=0)
    c.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Days, tann=252)
    c.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    c.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    c.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return c


def metrics(strat, cerebro, frame, config):
    t = strat.analyzers.trades.get_analysis()
    s = strat.analyzers.sharpe.get_analysis()
    r = strat.analyzers.returns.get_analysis()
    d = strat.analyzers.drawdown.get_analysis()
    q = strat.analyzers.sqn.get_analysis()
    ic = float(config['backtest']['initial_cash'])
    fv = float(cerebro.broker.getvalue())
    vals = [v for _, v in getattr(strat, 'broker_value_series', [])] or [ic, fv]
    total = t.get('total', {}).get('total', 0)
    won = t.get('won', {}).get('total', 0)
    lost = t.get('lost', {}).get('total', 0)
    gw = t.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gl = abs(t.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'strategy_name': config['strategy']['name'], 'fromdate': frame['fromdate'], 'todate': frame['todate'], 'bars': len(frame['data']),
        'bar_num': strat.bar_num, 'buy_count': strat.buy_count, 'sell_count': strat.sell_count, 'rebalance_count': getattr(strat, 'rebalance_count', 0),
        'initial_cash': ic, 'final_value': fv, 'net_pnl': fv - ic, 'total_return_pct': (fv / ic - 1.0) * 100.0,
        'total_trades': total, 'won': won, 'lost': lost, 'win_rate': (won / total * 100.0) if total else 0.0,
        'profit_factor': (gw / gl) if gl else None, 'max_drawdown': d.get('max', {}).get('drawdown', 0.0),
        'sharpe_ratio': finite_or_none(s.get('sharperatio')), 'annual_return_pct': (r.get('rnorm') or 0.0) * 100.0,
        'sqn': finite_or_none(q.get('sqn')), 'ulcer_index': ulcer(vals),
    }


def norm(v):
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def write_outputs(config, m):
    (BASE_DIR / config['outputs']['local_result_json']).write_text(json.dumps({k: norm(v) for k, v in m.items()}, ensure_ascii=False, indent=2), encoding='utf-8')
    path = (BASE_DIR / config['outputs']['global_summary_csv']).resolve()
    fields = ['strategy_id','strategy_name','strategy_type','strategy_dir','symbol','timeframe','fromdate','todate','bars','total_trades','won','lost','win_rate','profit_factor','total_return_pct','annual_return_pct','max_drawdown','sharpe_ratio','final_value','net_pnl','sqn','ulcer_index']
    rows = list(csv.DictReader(open(path, 'r', encoding='utf-8-sig', newline=''))) if path.exists() else []
    rows = [x for x in rows if x.get('strategy_id') != config['strategy']['id']]
    rows.append({'strategy_id': config['strategy']['id'], 'strategy_name': config['strategy']['name'], 'strategy_type': BASE_DIR.parent.name, 'strategy_dir': BASE_DIR.name, 'symbol': config['data']['symbol'], 'timeframe': config['data']['timeframe'], 'fromdate': str(m.get('fromdate', '')), 'todate': str(m.get('todate', '')), 'bars': m.get('bars', 0), 'total_trades': m.get('total_trades', 0), 'won': m.get('won', 0), 'lost': m.get('lost', 0), 'win_rate': m.get('win_rate', 0), 'profit_factor': m.get('profit_factor'), 'total_return_pct': m.get('total_return_pct', 0), 'annual_return_pct': m.get('annual_return_pct', 0), 'max_drawdown': m.get('max_drawdown', 0), 'sharpe_ratio': m.get('sharpe_ratio'), 'final_value': m.get('final_value', 0), 'net_pnl': m.get('net_pnl', 0), 'sqn': m.get('sqn'), 'ulcer_index': m.get('ulcer_index', 0)})
    with open(path, 'w', encoding='utf-8-sig', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def main():
    config = load_config()
    frame = load_frame(config)
    print(f"Loaded fifty-fifty bars: {len(frame['data'])}")
    cerebro = build_cerebro(frame, config)
    strat = cerebro.run()[0]
    m = metrics(strat, cerebro, frame, config)
    write_outputs(config, m)
    print(m)




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
