from __future__ import absolute_import, division, print_function, unicode_literals

import csv
import json
import math
import os
from datetime import datetime
from pathlib import Path

import backtrader as bt
from backtrader.comminfo import ComminfoFuturesPercent
import yaml

from strategy_taa_risk_parity_trend import (
    ASSET_ORDER,
    TAARiskParityTrendStrategy,
    TAASignalFeed,
    load_mt5_csv,
    prepare_taa_inputs,
)

BASE_DIR = Path(__file__).parent.resolve()



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

def finite_or_none(x):
    return x if x and math.isfinite(x) else None


def calculate_ulcer_index(values):
    if len(values) < 2:
        return 0.0
    max_value = values[0]
    sum_squared = 0.0
    for v in values:
        if v > max_value:
            max_value = v
        drawdown = (max_value - v) / max_value * 100.0 if max_value > 0 else 0.0
        sum_squared += drawdown ** 2
    return math.sqrt(sum_squared / len(values))


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_inputs(config):
    data_cfg = config['data']
    fromdate = datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.fromisoformat(data_cfg['todate'])
    asset_frames = {
        symbol: load_mt5_csv((BASE_DIR / path).resolve(), fromdate=fromdate, todate=todate)
        for symbol, path in data_cfg['assets'].items()
    }
    aligned, signal_df = prepare_taa_inputs(asset_frames, config.get('params', {}))
    return {'asset_frames': aligned, 'signal_df': signal_df, 'fromdate': fromdate, 'todate': todate}



def add_trade_logger(cerebro):
    trade_log_root = os.environ.get('BT_TRADE_LOG_DIR', '').strip()
    if not trade_log_root:
        return
    log_dir = Path(trade_log_root) / 'python'
    log_dir.mkdir(parents=True, exist_ok=True)
    cerebro.addobserver(
        bt.observers.TradeLogger,
        log_dir=str(log_dir),
        log_orders=True,
        log_trades=True,
        log_positions=True,
        log_indicators=True,
        log_signals=True,
        log_position_snapshot=False,
        log_format='json',
    )


def build_cerebro(inputs, config):
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=False)
    cerebro.broker.setcash(float(bt_cfg['initial_cash']))
    signal_feed = TAASignalFeed(dataname=inputs['signal_df'], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(signal_feed, name='SIGNAL')
    comminfo = ComminfoFuturesPercent(
        commission=float(bt_cfg.get('commission', 0.001)),
        margin=float(bt_cfg.get('margin', 1.0)),
        mult=float(bt_cfg.get('multiplier', 1.0)),
    )
    for symbol in ASSET_ORDER:
        asset_feed = bt.feeds.PandasData(dataname=inputs['asset_frames'][symbol], timeframe=bt.TimeFrame.Days, compression=1)
        cerebro.adddata(asset_feed, name=symbol)
        cerebro.broker.addcommissioninfo(comminfo, name=symbol)
    cerebro.addstrategy(TAARiskParityTrendStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Months, compression=1, factor=12, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', tann=12)
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    add_trade_logger(cerebro)
    return cerebro


def extract_metrics(strat, cerebro, inputs, config):
    sharpe = strat.analyzers.sharpe.get_analysis().get('sharperatio')
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis().get('sqn')
    initial_cash = float(config['backtest']['initial_cash'])
    final_value = float(cerebro.broker.getvalue())
    equity_values = [value for _, value in getattr(strat, 'broker_value_series', [])] or [initial_cash, final_value]
    total_trades = trades.get('total', {}).get('closed', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    gross_profit = trades.get('won', {}).get('pnl', {}).get('total', 0.0) or 0.0
    gross_loss = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0.0) or 0.0)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    win_rate = won / total_trades * 100.0 if total_trades else 0.0
    total_return_pct = (final_value / initial_cash - 1.0) * 100.0
    annual_return_pct = (returns.get('rnorm') or 0.0) * 100.0
    max_dd = drawdown.get('max', {}).get('drawdown', 0.0) or 0.0
    return {
        'strategy_name': config['strategy']['name'],
        'fromdate': inputs['fromdate'].isoformat(),
        'todate': inputs['todate'].isoformat(),
        'bars': len(inputs['signal_df']),
        'bar_num': strat.bar_num,
        'rebalance_count': strat.rebalance_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': total_return_pct,
        'annual_return_pct': annual_return_pct,
        'max_drawdown': max_dd,
        'sharpe_ratio': finite_or_none(sharpe),
        'sqn': finite_or_none(sqn),
        'ulcer_index': calculate_ulcer_index(equity_values),
    }


def write_local_result(config, metrics):
    output_path = BASE_DIR / config['outputs']['local_result_json']
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)


def update_global_summary(config, metrics):
    csv_path = (BASE_DIR / config['outputs']['global_summary_csv']).resolve()
    fieldnames = [
        'strategy_id', 'strategy_name', 'strategy_type', 'strategy_dir', 'symbol', 'timeframe',
        'fromdate', 'todate', 'bars', 'total_trades', 'won', 'lost', 'win_rate', 'profit_factor',
        'total_return_pct', 'annual_return_pct', 'max_drawdown', 'sharpe_ratio', 'final_value',
        'net_pnl', 'sqn', 'ulcer_index',
    ]
    rows = []
    if csv_path.exists():
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
    rows = [row for row in rows if row.get('strategy_id') != config['strategy']['id']]
    rows.append({
        'strategy_id': config['strategy']['id'],
        'strategy_name': config['strategy']['name'],
        'strategy_type': BASE_DIR.parent.name,
        'strategy_dir': BASE_DIR.name,
        'symbol': ','.join(ASSET_ORDER) + ',CASH',
        'timeframe': config['data']['timeframe'],
        'fromdate': metrics['fromdate'],
        'todate': metrics['todate'],
        'bars': metrics['bars'],
        'total_trades': metrics['total_trades'],
        'won': metrics['won'],
        'lost': metrics['lost'],
        'win_rate': metrics['win_rate'],
        'profit_factor': metrics['profit_factor'],
        'total_return_pct': metrics['total_return_pct'],
        'annual_return_pct': metrics['annual_return_pct'],
        'max_drawdown': metrics['max_drawdown'],
        'sharpe_ratio': metrics['sharpe_ratio'],
        'final_value': metrics['final_value'],
        'net_pnl': metrics['net_pnl'],
        'sqn': metrics['sqn'],
        'ulcer_index': metrics['ulcer_index'],
    })
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_results(metrics):
    print('\n' + '=' * 60)
    print(f"BACKTEST RESULTS — {metrics['strategy_name']}")
    print('=' * 60)
    print(f"Period:         {metrics['fromdate']} -> {metrics['todate']}")
    print(f"Bars:           {metrics['bars']}")
    print(f"Rebalances:     {metrics['rebalance_count']}")
    print(f"Trades:         {metrics['total_trades']}")
    print(f"Win rate:       {metrics['win_rate']:.2f}%")
    print(f"Profit factor:  {metrics['profit_factor']}")
    print(f"Total return:   {metrics['total_return_pct']:.2f}%")
    print(f"Annual return:  {metrics['annual_return_pct']:.2f}%")
    print(f"Max drawdown:   {metrics['max_drawdown']:.2f}%")
    print(f"Sharpe:         {metrics['sharpe_ratio']}")
    print(f"SQN:            {metrics['sqn']}")
    print(f"Ulcer index:    {metrics['ulcer_index']:.2f}")
    print(f"Final value:    {metrics['final_value']:.2f}")
    print('=' * 60)


def main():
    config = load_config()
    inputs = load_inputs(config)
    cerebro = build_cerebro(inputs, config)
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, inputs, config)
    write_local_result(config, metrics)
    update_global_summary(config, metrics)
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
