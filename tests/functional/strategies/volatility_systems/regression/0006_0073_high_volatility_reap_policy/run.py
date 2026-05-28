from __future__ import absolute_import, division, print_function, unicode_literals

import csv
import json
from datetime import datetime
from pathlib import Path

import backtrader as bt
import yaml

from strategy_high_volatility_reap_policy import (
    HighVolatilityReapPolicyStrategy,
    RebalancingSignalFeed,
    load_mt5_csv,
    prepare_rebalancing_inputs,
)

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
TRADING_DAYS_PER_YEAR = 252


class AssetCommissionInfo(bt.CommInfoBase):
    params = (
        ('commission', 0.0002),
        ('margin', 1.0),
        ('mult', 1.0),
        ('stocklike', False),
        ('commtype', bt.CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * price * self.p.mult * self.p.commission


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


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


def finite_or_none(value):
    if value is None:
        return None
    if isinstance(value, float) and (value != value or value in (float('inf'), float('-inf'))):
        return None
    return value


def calculate_ulcer_index(equity_curve):
    if not equity_curve:
        return 0.0
    peak = None
    squared_drawdowns = []
    for value in equity_curve:
        peak = value if peak is None else max(peak, value)
        if peak and peak != 0:
            drawdown_pct = (value / peak - 1.0) * 100.0
            squared_drawdowns.append(drawdown_pct * drawdown_pct)
    if not squared_drawdowns:
        return 0.0
    return float(sum(squared_drawdowns) / len(squared_drawdowns)) ** 0.5


def load_inputs(config):
    data_cfg = config['data']
    fromdate = datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.fromisoformat(data_cfg['todate'])
    gold_df = load_mt5_csv((BASE_DIR / data_cfg['gold_file']).resolve(), fromdate=fromdate, todate=todate)
    benchmark_df = load_mt5_csv((BASE_DIR / data_cfg['benchmark_file']).resolve(), fromdate=fromdate, todate=todate)
    gold_df, benchmark_df, signal_df = prepare_rebalancing_inputs(gold_df, benchmark_df, config.get('params', {}))
    common_index = signal_df.index
    return {
        'gold_df': gold_df.loc[common_index].copy(),
        'benchmark_df': benchmark_df.loc[common_index].copy(),
        'signal_df': signal_df,
        'fromdate': fromdate,
        'todate': todate,
    }


def build_cerebro(inputs, config):
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(bt_cfg['initial_cash']))
    signal_feed = RebalancingSignalFeed(dataname=inputs['signal_df'], timeframe=bt.TimeFrame.Days, compression=1)
    gold_feed = bt.feeds.PandasData(dataname=inputs['gold_df'], timeframe=bt.TimeFrame.Days, compression=1)
    benchmark_feed = bt.feeds.PandasData(dataname=inputs['benchmark_df'], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(signal_feed, name='SIGNAL')
    cerebro.adddata(gold_feed, name='XAUUSD')
    cerebro.adddata(benchmark_feed, name='IVV')
    cerebro.broker.addcommissioninfo(AssetCommissionInfo(
        commission=float(bt_cfg.get('gold_commission', 0.0002)),
        margin=float(bt_cfg.get('gold_margin', 0.01)),
        mult=float(bt_cfg.get('gold_multiplier', 100.0)),
        stocklike=False,
    ), name='XAUUSD')
    cerebro.broker.addcommissioninfo(AssetCommissionInfo(
        commission=float(bt_cfg.get('benchmark_commission', 0.0002)),
        margin=float(bt_cfg.get('benchmark_margin', 1.0)),
        mult=float(bt_cfg.get('benchmark_multiplier', 1.0)),
        stocklike=True,
    ), name='IVV')
    cerebro.addstrategy(HighVolatilityReapPolicyStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, compression=1, factor=252, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Days, tann=TRADING_DAYS_PER_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, inputs, config):
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = float(config['backtest']['initial_cash'])
    final_value = float(cerebro.broker.getvalue())
    broker_values = [value for _, value in getattr(strat, 'broker_value_series', [])] or [initial_cash, final_value]
    total_trades = trades.get('total', {}).get('total', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'strategy_name': config['strategy']['name'],
        'fromdate': inputs['fromdate'],
        'todate': inputs['todate'],
        'bars': len(inputs['signal_df']),
        'bar_num': strat.bar_num,
        'rebalance_count': strat.rebalance_count,
        'switch_count': strat.switch_count,
        'stop_loss_count': strat.stop_loss_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1.0) * 100.0,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100.0) if total_trades else 0.0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'sharpe_ratio': finite_or_none(sharpe.get('sharperatio')),
        'annual_return_pct': (returns.get('rnorm') or 0.0) * 100.0,
        'sqn': finite_or_none(sqn.get('sqn')),
        'ulcer_index': calculate_ulcer_index(broker_values),
    }


def write_local_result(config, metrics):
    path = (BASE_DIR / config['outputs']['local_result_json']).resolve()
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump({key: normalize(value) for key, value in metrics.items()}, handle, ensure_ascii=False, indent=2)


def upsert_global_summary(config, metrics):
    path = (BASE_DIR / config['outputs']['global_summary_csv']).resolve()
    fieldnames = ['strategy_id', 'strategy_name', 'strategy_type', 'strategy_dir', 'symbol', 'timeframe', 'fromdate', 'todate', 'bars', 'total_trades', 'won', 'lost', 'win_rate', 'profit_factor', 'total_return_pct', 'annual_return_pct', 'max_drawdown', 'sharpe_ratio', 'final_value', 'net_pnl', 'sqn', 'ulcer_index']
    rows = []
    if path.exists():
        with open(path, 'r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    rows = [row for row in rows if row.get('strategy_id') != config['strategy']['id']]
    rows.append({
        'strategy_id': config['strategy']['id'],
        'strategy_name': config['strategy']['name'],
        'strategy_type': BASE_DIR.parent.name,
        'strategy_dir': BASE_DIR.name,
        'symbol': config['data']['gold_symbol'],
        'timeframe': config['data']['timeframe'],
        'fromdate': str(metrics.get('fromdate', '')),
        'todate': str(metrics.get('todate', '')),
        'bars': metrics.get('bars', 0),
        'total_trades': metrics.get('total_trades', 0),
        'won': metrics.get('won', 0),
        'lost': metrics.get('lost', 0),
        'win_rate': metrics.get('win_rate', 0),
        'profit_factor': metrics.get('profit_factor'),
        'total_return_pct': metrics.get('total_return_pct', 0),
        'annual_return_pct': metrics.get('annual_return_pct', 0),
        'max_drawdown': metrics.get('max_drawdown', 0),
        'sharpe_ratio': metrics.get('sharpe_ratio'),
        'final_value': metrics.get('final_value', 0),
        'net_pnl': metrics.get('net_pnl', 0),
        'sqn': metrics.get('sqn'),
        'ulcer_index': metrics.get('ulcer_index', 0),
    })
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def print_results(metrics):
    print('\n' + '=' * 60)
    print(f"BACKTEST RESULTS — {metrics['strategy_name']}")
    print('=' * 60)
    print(f"  Period:              {metrics['fromdate']} -> {metrics['todate']}")
    print(f"  Bars:                {metrics['bars']}")
    print(f"  Final value:         {metrics['final_value']:,.2f}")
    print(f"  Return:              {metrics['total_return_pct']:.2f}%")
    print(f"  Rebalances:          {metrics['rebalance_count']}")
    print(f"  Stop-loss count:     {metrics['stop_loss_count']}")
    print(f"  Total trades:        {metrics['total_trades']}")
    print(f"  Win rate:            {metrics['win_rate']:.2f}%")
    print(f"  Sharpe ratio:        {metrics['sharpe_ratio']}")
    print(f"  Annual return:       {metrics['annual_return_pct']:.2f}%")
    print(f"  Max drawdown:        {metrics['max_drawdown']:.2f}%")
    print(f"  SQN:                 {metrics['sqn']}")
    print(f"  Ulcer index:         {metrics['ulcer_index']:.2f}")
    print('=' * 60)


def main():
    config = load_config()
    inputs = load_inputs(config)
    cerebro = build_cerebro(inputs, config)
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, inputs, config)
    write_local_result(config, metrics)
    upsert_global_summary(config, metrics)
    print_results(metrics)




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
