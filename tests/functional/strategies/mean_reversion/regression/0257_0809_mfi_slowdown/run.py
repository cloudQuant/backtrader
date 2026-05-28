from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import datetime
import json
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import yaml


class MoneyFlowIndex(bt.Indicator):
    lines = ('mfi',)
    params = (('period', 14),)

    def __init__(self):
        self.addminperiod(self.p.period + 1)

    def next(self):
        positive_flow = 0.0
        negative_flow = 0.0
        for i in range(self.p.period):
            curr_tp = (float(self.data.high[-i]) + float(self.data.low[-i]) + float(self.data.close[-i])) / 3.0
            prev_tp = (float(self.data.high[-i - 1]) + float(self.data.low[-i - 1]) + float(self.data.close[-i - 1])) / 3.0
            raw_flow = curr_tp * float(self.data.volume[-i])
            if curr_tp > prev_tp:
                positive_flow += raw_flow
            elif curr_tp < prev_tp:
                negative_flow += raw_flow
        if negative_flow == 0.0:
            self.lines.mfi[0] = 100.0
        else:
            money_ratio = positive_flow / negative_flow
            self.lines.mfi[0] = 100.0 - (100.0 / (1.0 + money_ratio))


bt.indicators.MFI = MoneyFlowIndex

from strategy_mfi_slowdown import ExpMFISlowdownStrategy, Mt5PandasFeed, load_mt5_csv

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


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def resolve_data_path(filename):
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def load_frame(config):
    dc = config['data']
    fd = datetime.datetime.fromisoformat(dc['fromdate'])
    td = datetime.datetime.fromisoformat(dc['todate'])
    return load_mt5_csv(resolve_data_path(dc['file']), fromdate=fd, todate=td, bar_shift_minutes=dc.get('bar_shift_minutes', 0))


def build_signal_frame(df, minutes):
    out = df.resample(f'{int(minutes)}min', label='right', closed='right').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'openinterest': 'sum'})
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def run(plot=False):
    config = load_config()
    df = load_frame(config)
    params = dict(config['params'])
    minutes = params.pop('indicator_minutes')
    signal_df = build_signal_frame(df, minutes)
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(config['backtest']['initial_cash'])
    cerebro.broker.setcommission(commission=config['backtest']['commission'], margin=config['backtest']['margin'], mult=config['backtest']['multiplier'], commtype=bt.CommInfoBase.COMM_FIXED, stocklike=False)
    cerebro.adddata(Mt5PandasFeed(dataname=df, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.adddata(Mt5PandasFeed(dataname=signal_df, timeframe=bt.TimeFrame.Minutes, compression=minutes))
    cerebro.addstrategy(ExpMFISlowdownStrategy, **params)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    results = cerebro.run()
    strat = results[0]
    trades = strat.analyzers.trades.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    total_trades = trades.get('total', {}).get('closed', won + lost)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    broker_values = [initial_cash, final_value]
    metrics = {
        'bars': len(df),
        'bar_num': strat.bar_num,
        'signal_count': strat.signal_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'trade_count': strat.trade_count,
        'trade_num': total_trades,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1.0) * 100.0,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100.0) if total_trades else 0.0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0.0) * 100.0,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'sqn': sqn.get('sqn'),
        'ulcer_index': calculate_ulcer_index(broker_values),
    }
    if plot:
        cerebro.plot()
    local_result_path = BASE_DIR / 'backtest_result.json'
    with open(local_result_path, 'w', encoding='utf-8') as handle:
        json.dump({key: normalize(value) for key, value in metrics.items()}, handle, ensure_ascii=False, indent=2)
    print(json.dumps({key: normalize(value) for key, value in metrics.items()}, ensure_ascii=False, indent=2))
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
