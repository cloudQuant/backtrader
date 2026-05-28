from __future__ import absolute_import, division, print_function, unicode_literals

import csv
import json
import math
from datetime import datetime
from pathlib import Path

import backtrader as bt
from backtrader.comminfo import CommInfoBase
import yaml

from strategy_regime_switching_modeling import (
    RegimeSwitchingFeed,
    RegimeSwitchingModelingStrategy,
    load_mt5_csv,
    prepare_regime_switching_features,
)

BASE_DIR = Path(__file__).parent.resolve()



# Vendored benchmark output hook (auto-edited by migrate_regression.py)
from pathlib import Path as _BenchmarkPath
import sys as _benchmark_sys
_BENCHMARK_BASE_DIR = _BenchmarkPath(__file__).resolve().parent
_REPO_ROOT = _BenchmarkPath(__file__).resolve().parents[5]
if str(_REPO_ROOT) not in _benchmark_sys.path:
    _benchmark_sys.path.insert(0, str(_REPO_ROOT))
from tests.test_utils.benchmark_metrics import (
    install_benchmark_metrics_hook as _install_benchmark_metrics_hook,
    load_benchmark_result as _load_benchmark_result,
    write_benchmark_result as _write_benchmark_result,
)
_install_benchmark_metrics_hook(_BENCHMARK_BASE_DIR)

class SpotCommissionInfo(CommInfoBase):
    params = (
        ('commission', 0.0002),
        ('stocklike', True),
        ('commtype', CommInfoBase.COMM_PERC),
        ('percabs', True),
    )


def finite_or_none(x):
    return x if x is not None and math.isfinite(x) else None


def calculate_ulcer_index(values):
    if len(values) < 2:
        return 0.0
    max_value = values[0]
    sum_squared = 0.0
    for value in values:
        if value > max_value:
            max_value = value
        drawdown = (max_value - value) / max_value * 100.0 if max_value > 0 else 0.0
        sum_squared += drawdown ** 2
    return math.sqrt(sum_squared / len(values))


def load_config():
    with open(BASE_DIR / 'config.yaml', 'r', encoding='utf-8') as handle:
        return yaml.safe_load(handle) or {}


def resolve_data_file(file_value):
    path_value = Path(str(file_value))
    candidates = []
    if path_value.is_absolute():
        candidates.append(path_value)
    candidates.append((BASE_DIR / path_value).resolve())
    candidates.append((Path(__file__).resolve().parents[6] / 'tests' / 'datas' / path_value.name).resolve())
    candidates.append((Path(__file__).resolve().parents[6] / 'tests' / 'datas' / 'mt5_1d_data' / path_value.name).resolve())
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError('Could not resolve data file from config: {0}'.format(file_value))


def load_data(config):
    data_cfg = config['data']
    fromdate = datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.fromisoformat(data_cfg['todate'])
    raw = load_mt5_csv(resolve_data_file(data_cfg['file']), fromdate=fromdate, todate=todate)
    features = prepare_regime_switching_features(raw, config.get('params', {}))
    if features.empty:
        raise ValueError('Loaded data frame is empty after feature preparation')
    return {'data': features, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(frame, config):
    cerebro = bt.Cerebro(stdstats=False)
    bt_cfg = config['backtest']
    cerebro.broker.setcash(float(bt_cfg['initial_cash']))
    comminfo = SpotCommissionInfo(commission=float(bt_cfg.get('commission', 0.0002)))
    feed = RegimeSwitchingFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.broker.addcommissioninfo(comminfo)
    cerebro.addstrategy(RegimeSwitchingModelingStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days, compression=1, factor=252, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', tann=252)
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
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
    if total_trades == 0:
        total_trades = int(getattr(strat, 'signal_change_count', 0))
    bull_days = int((frame['data']['bull_signal'] > 0.5).sum())
    bear_days = int((frame['data']['bear_signal'] > 0.5).sum())
    neutral_days = int((frame['data']['neutral_signal'] > 0.5).sum())
    avg_state_confidence = float(frame['data']['state_confidence'].mean()) if len(frame['data']) else None
    avg_persistence_prob = float(frame['data']['persistence_prob'].mean()) if len(frame['data']) else None
    return {
        'strategy_name': config['strategy']['name'],
        'fromdate': frame['fromdate'].isoformat(),
        'todate': frame['todate'].isoformat(),
        'bars': len(frame['data']),
        'bar_num': strat.bar_num,
        'retrain_count': strat.retrain_count,
        'signal_change_count': strat.signal_change_count,
        'bull_days': bull_days,
        'bear_days': bear_days,
        'neutral_days': neutral_days,
        'avg_state_confidence': avg_state_confidence,
        'avg_persistence_prob': avg_persistence_prob,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1.0) * 100.0,
        'annual_return_pct': (returns.get('rnorm') or 0.0) * 100.0,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0) or 0.0,
        'sharpe_ratio': finite_or_none(sharpe),
        'sqn': finite_or_none(sqn),
        'ulcer_index': calculate_ulcer_index(equity_values),
    }


def write_local_result(config, metrics):
    output_path = BASE_DIR / config['outputs']['local_result_json']
    with open(output_path, 'w', encoding='utf-8') as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2)


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
        with open(csv_path, 'r', encoding='utf-8-sig', newline='') as handle:
            rows = list(csv.DictReader(handle))
    rows = [row for row in rows if row.get('strategy_id') != config['strategy']['id']]
    rows.append({
        'strategy_id': config['strategy']['id'],
        'strategy_name': config['strategy']['name'],
        'strategy_type': BASE_DIR.parent.name,
        'strategy_dir': BASE_DIR.name,
        'symbol': config['data']['symbol'],
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
    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_results(metrics):
    print('\n' + '=' * 60)
    print(f"BACKTEST RESULTS — {metrics['strategy_name']}")
    print('=' * 60)
    print(f"Period:         {metrics['fromdate']} -> {metrics['todate']}")
    print(f"Bars:           {metrics['bars']}")
    print(f"Retrains:       {metrics['retrain_count']}")
    print(f"Signal changes: {metrics['signal_change_count']}")
    print(f"Bull days:      {metrics['bull_days']}")
    print(f"Bear days:      {metrics['bear_days']}")
    print(f"Neutral days:   {metrics['neutral_days']}")
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
    frame = load_data(config)
    cerebro = build_cerebro(frame, config)
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, config)
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
