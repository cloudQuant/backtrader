from __future__ import absolute_import, division, print_function, unicode_literals

import json
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CURRENT_DIR.parents[1]
BACKTRADER_LOCAL = REPO_ROOT.parent / 'backtrader'
if BACKTRADER_LOCAL.exists() and str(BACKTRADER_LOCAL) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_LOCAL))

import backtrader as bt
import yaml

from strategy_renko_line_break_vs_rsi_ea import RenkoLineBreakVsRsiStrategy, Mt5PandasFeed, load_mt5_csv



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

def load_config():
    config_path = CURRENT_DIR / 'config.yaml'
    with config_path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def build_cerebro(config):
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(config['backtest']['initial_cash']))
    commission = float(config['backtest'].get('commission', 0.0))
    margin = float(config['backtest'].get('margin', 1.0))
    mult = float(config['backtest'].get('multiplier', 1.0))
    stocklike = bool(config['backtest'].get('stocklike', False))
    commission_type = str(config['backtest'].get('commission_type', 'fixed')).lower()

    if commission_type == 'percent':
        cerebro.broker.setcommission(commission=commission, margin=margin, mult=mult, stocklike=stocklike)
    else:
        cerebro.broker.setcommission(commission=commission, margin=margin, mult=mult, commtype=bt.CommInfoBase.COMM_FIXED, stocklike=stocklike)

    data_cfg = config['data']
    data_path = (CURRENT_DIR / data_cfg['file']).resolve()
    fromdate = data_cfg.get('fromdate')
    todate = data_cfg.get('todate')
    df = load_mt5_csv(
        str(data_path),
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=int(data_cfg.get('bar_shift_minutes', 0)),
    )
    data = Mt5PandasFeed(dataname=df)
    cerebro.adddata(data, name=data_cfg.get('symbol', 'DATA'))

    cerebro.addstrategy(RenkoLineBreakVsRsiStrategy, **config['params'])
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trade_analyzer')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    return cerebro


def analyzer_to_dict(value):
    if hasattr(value, '_asdict'):
        return {k: analyzer_to_dict(v) for k, v in value._asdict().items()}
    if isinstance(value, dict):
        return {k: analyzer_to_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [analyzer_to_dict(v) for v in value]
    return value


def extract_metrics(config, cerebro, strategy, df):
    start_value = float(config['backtest']['initial_cash'])
    end_value = float(cerebro.broker.getvalue())
    end_cash = float(cerebro.broker.getcash())
    trades = analyzer_to_dict(strategy.analyzers.trade_analyzer.get_analysis())
    drawdown = analyzer_to_dict(strategy.analyzers.drawdown.get_analysis())
    returns = analyzer_to_dict(strategy.analyzers.returns.get_analysis())
    total_trades = int(trades.get('total', {}).get('total', 0) or 0)
    won = int(trades.get('won', {}).get('total', 0) or 0)
    lost = int(trades.get('lost', {}).get('total', 0) or 0)
    gross_won = float(trades.get('won', {}).get('pnl', {}).get('total', 0) or 0)
    gross_lost = abs(float(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0))
    return {
        'fromdate': str(df.index[0]) if len(df.index) else str(config['data'].get('fromdate')),
        'todate': str(df.index[-1]) if len(df.index) else str(config['data'].get('todate')),
        'bars': int(len(df)),
        'bar_num': int(strategy.bar_num),
        'signal_count': int(strategy.signal_count),
        'buy_count': int(strategy.buy_count),
        'sell_count': int(strategy.sell_count),
        'trade_count': int(strategy.trade_count),
        'win_count': int(strategy.win_count),
        'loss_count': int(strategy.loss_count),
        'initial_cash': round(start_value, 2),
        'final_cash': round(end_cash, 2),
        'final_value': round(end_value, 2),
        'net_pnl': round(end_value - start_value, 2),
        'total_return_pct': round((end_value / start_value - 1.0) * 100.0, 2),
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': round((won / total_trades * 100.0), 2) if total_trades else 0.0,
        'profit_factor': round(gross_won / gross_lost, 4) if gross_lost else None,
        'open_position_size': float(strategy.position.size),
        'open_position_price': round(float(strategy.position.price), 5),
        'max_drawdown': round(float(drawdown.get('max', {}).get('drawdown', 0) or 0), 2),
        'annual_return_pct': round(float((returns.get('rnorm') or 0) * 100.0), 2),
        'trade_analyzer': trades,
        'drawdown': drawdown,
        'returns': returns,
    }


def main():
    config = load_config()
    cerebro = build_cerebro(config)
    strategies = cerebro.run()
    strategy = strategies[0]
    df = cerebro.datas[0].p.dataname
    report = extract_metrics(config, cerebro, strategy, df)
    print(json.dumps(report, ensure_ascii=False, indent=2))




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
