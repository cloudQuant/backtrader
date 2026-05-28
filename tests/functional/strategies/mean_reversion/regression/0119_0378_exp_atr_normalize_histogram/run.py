from pathlib import Path
import os
import sys
import yaml
import datetime as dt
import io
import math
import backtrader as bt
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from strategy_exp_atr_normalize_histogram import ExpAtrNormalizeHistogramStrategy


MINUTES_PER_TRADING_YEAR = 24 * 60 * 252



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

class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, minutes):
    rule = f'{int(minutes)}min'
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
        'spread': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    out['spread'] = out['spread'].fillna(0)
    return out


def load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_backtest_frame(config: dict) -> dict:
    data_cfg = config['data']
    data_file = data_cfg['file']
    if not os.path.isabs(data_file):
        data_file = os.path.normpath(os.path.join(SCRIPT_DIR, data_file))
    fromdate = dt.datetime.strptime(data_cfg['fromdate'], '%Y-%m-%d %H:%M:%S')
    todate = dt.datetime.strptime(data_cfg['todate'], '%Y-%m-%d %H:%M:%S')
    frame = load_mt5_csv(data_file, fromdate=fromdate, todate=todate)
    if frame.empty:
        raise ValueError('Loaded data frame is empty')
    signal = resample_frame(frame, data_cfg.get('signal_compression_minutes', 240))
    return {'data': frame, 'signal': signal}


def add_default_analyzers(cerebro):
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=60, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')


def finite_or_none(value):
    if value is None:
        return None
    if isinstance(value, (int, float)) and not math.isfinite(value):
        return None
    return value


def extract_metrics(strat, start_value, frame):
    end_value = strat.broker.getvalue()
    drawdown = strat.analyzers.drawdown.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    total_closed = trades.get('total', {}).get('closed', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    win_rate = (won / total_closed * 100.0) if total_closed else 0.0
    return {
        'initial_cash': start_value,
        'final_value': end_value,
        'net_pnl': end_value - start_value,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0.0),
        'total_trades': total_closed,
        'win_count': won,
        'loss_count': lost,
        'win_rate': win_rate,
        'sharpe_ratio': finite_or_none(sharpe.get('sharperatio')),
        'sqn': finite_or_none(sqn.get('sqn')),
        'total_return_pct': returns.get('rtot', 0.0) * 100.0,
        'annual_return_pct': returns.get('rnorm', 0.0) * 100.0,
        'bars': len(frame['data']),
    }


def run(cfg_path: str | None = None):
    if cfg_path is None:
        cfg_path = os.path.join(SCRIPT_DIR, 'config.yaml')
    cfg = load_config(cfg_path)

    data_cfg = cfg['data']
    params_cfg = cfg.get('params', {})
    bt_cfg = cfg.get('backtest', {})

    frame = load_backtest_frame(cfg)
    data0 = Mt5PandasFeed(
        dataname=frame['data'],
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
    )
    signal_data = Mt5PandasFeed(
        dataname=frame['signal'],
        timeframe=bt.TimeFrame.Minutes,
        compression=240,
    )

    cerebro = bt.Cerebro()
    cerebro.adddata(data0, name='XAUUSD_M15')
    cerebro.adddata(signal_data, name='XAUUSD_H4')

    strat_kwargs = {}
    for key in (
        'mm', 'mm_mode', 'stop_loss_points', 'take_profit_points', 'deviation_points',
        'buy_pos_open', 'sell_pos_open', 'buy_pos_close', 'sell_pos_close',
        'ma_method1', 'length1', 'phase1', 'ma_method2', 'length2', 'phase2',
        'high_level', 'middle_level', 'low_level', 'signal_bar', 'lot', 'point',
    ):
        if key in params_cfg:
            strat_kwargs[key] = params_cfg[key]

    cerebro.addstrategy(ExpAtrNormalizeHistogramStrategy, **strat_kwargs)
    add_default_analyzers(cerebro)

    cerebro.broker.setcash(bt_cfg.get('initial_cash', 100000.0))
    cerebro.broker.setcommission(
        commission=bt_cfg.get('commission', 0.0),
        margin=bt_cfg.get('margin', 1000.0),
        mult=bt_cfg.get('multiplier', 100.0),
        stocklike=bt_cfg.get('stocklike', False),
    )

    print(f'数据文件:  {os.path.normpath(os.path.join(SCRIPT_DIR, data_cfg["file"]))}')
    print(f'信号周期:  {data_cfg.get("signal_timeframe", "H4")}')
    print(f'回测区间:  {data_cfg["fromdate"]} ~ {data_cfg["todate"]}')
    print(f'初始资金:  {cerebro.broker.getvalue():.2f}')
    print('-' * 50)

    start_value = cerebro.broker.getvalue()
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    print(f'\n最终权益: {final_value:.2f}')
    metrics = extract_metrics(results[0], start_value, frame)
    return results, metrics




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
    cfg = sys.argv[1] if len(sys.argv) > 1 else None
    run(cfg)