"""Regression test for `tests/functional/strategies/trend_following/regression/0146_1272_vinini_trend` after inline migration.

Data Used:
    - Input data file: `tests/datas/XAUUSD_M15.csv`.
    - Market/asset: `XAUUSD`.
    - Base timeframe: 15-minute bars (`M15`).
    - Backtest date range: from `2025-12-03 01:15:00` to `2026-03-10 09:00:00`.
    - Data flow: MT5 CSV → normalized dataframe → indicator `trend` line → strategy actions.

Strategy Principle:
    - Computes a multi-period MA-based trend score from selected applied price.
    - Smooths the score with a secondary MA to produce a bounded trend oscillator.
    - Triggers breakdown/twist mode signals from trend transitions around configured levels.
    - Tracks buy/sell counts, trade counts, and pnl outcomes for verification.

Strategy Logic:
    - `load_mt5_csv` ingests and filters bars.
    - `VininITrendIndicator` generates the trend line used for signaling.
    - `VininITrendStrategy` converts trend transitions into reversal/close actions.
    - `resolve_*`, `load_backtest_frame`, and `build_cerebro` set up deterministic backtest inputs.
    - `extract_metrics` collects analyzer summaries used by assertions.
"""
from __future__ import annotations
import backtrader as bt
import math
from pathlib import Path
import sys
import argparse
import datetime
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'VininI_Trend',
        'source_ea': 'ea/1272_Exp_VininI_Trend',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'M15',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
    },
    'params': {
        'mode': 'breakdown',
        'ma_method1': 'sma',
        'length1': 3,
        'phase1': 15,
        'ma_step': 10,
        'ma_count': 10,
        'ma_method2': 'jjma',
        'length2': 20,
        'phase2': 100,
        'ipc': 'price_close',
        'up_level': 10,
        'dn_level': -10,
        'signal_bar': 1,
        'lot': 0.1,
    },
    'backtest': {
        'initial_cash': 1000000,
        'commission': 0.0,
        'margin': 0.01,
        'multiplier': 100.0,
        'commission_type': 'fixed',
        'stocklike': False,
    },
}


REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class Mt5PandasFeed(bt.feeds.PandasData):
    """Base feed adapter for normalized M15 OHLCV data."""
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


def resolve_ma_class(name):
    """Resolve MA method identifier to a Backtrader MA class.

    Args:
        name: Method name from configuration.

    Returns:
        Backtrader MA class.
    """
    mode = str(name).lower()
    if mode in {'sma', 'mode_sma'}:
        return bt.indicators.SimpleMovingAverage
    if mode in {'ema', 'mode_ema'}:
        return bt.indicators.ExponentialMovingAverage
    if mode in {'smma', 'mode_smma'}:
        return bt.indicators.SmoothedMovingAverage
    return bt.indicators.WeightedMovingAverage


def resolve_price_line(data, mode):
    """Resolve an applied price variant from raw data lines.

    Args:
        data: Backtrader feed or data object.
        mode: Price selector key.

    Returns:
        backtrader line: Selected price series.
    """
    price_mode = str(mode).lower()
    if price_mode in {'price_open', 'open'}:
        return data.open
    if price_mode in {'price_high', 'high'}:
        return data.high
    if price_mode in {'price_low', 'low'}:
        return data.low
    if price_mode in {'price_median', 'median'}:
        return (data.high + data.low) / 2.0
    if price_mode in {'price_typical', 'typical'}:
        return (data.high + data.low + data.close) / 3.0
    if price_mode in {'price_weighted', 'weighted'}:
        return (data.high + data.low + data.close + data.close) / 4.0
    return data.close


class VininITrendStrategy(bt.Strategy):
    """Trend strategy using VininI Trend indicator in breakdown/twist mode."""
    params = dict(
        mode='breakdown',
        ma_method1='sma',
        length1=3,
        phase1=15,
        ma_step=10,
        ma_count=10,
        ma_method2='jjma',
        length2=20,
        phase2=100,
        ipc='price_close',
        up_level=10,
        dn_level=-10,
        signal_bar=1,
        lot=0.1,
    )

    def __init__(self):
        """Initialize indicator and trade counters."""
        self.indicator = bt.indicators.VininITrendIndicator(
            self.data,
            ma_method1=self.p.ma_method1,
            length1=self.p.length1,
            phase1=self.p.phase1,
            ma_step=self.p.ma_step,
            ma_count=self.p.ma_count,
            ma_method2=self.p.ma_method2,
            length2=self.p.length2,
            phase2=self.p.phase2,
            ipc=self.p.ipc,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        """Emit strategy log with data timestamp."""
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signals_breakdown(self, shift):
        value_prev = float(self.indicator.trend[-shift])
        value_cur = float(self.indicator.trend[-shift + 1]) if shift > 1 else float(self.indicator.trend[0])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value_prev > float(self.p.up_level):
            if value_cur <= float(self.p.up_level):
                buy_open = True
            sell_close = True
        if value_prev < float(self.p.dn_level):
            if value_cur >= float(self.p.dn_level):
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals_twist(self, shift):
        value0 = float(self.indicator.trend[-shift + 1]) if shift > 1 else float(self.indicator.trend[0])
        value1 = float(self.indicator.trend[-shift])
        value2 = float(self.indicator.trend[-shift - 1])
        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False
        if value1 < value2:
            if value0 > value1:
                buy_open = True
            sell_close = True
        if value1 > value2:
            if value0 < value1:
                sell_open = True
            buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _signals(self):
        shift = max(1, int(self.p.signal_bar))
        if str(self.p.mode).lower() == 'twist':
            return self._signals_twist(shift)
        return self._signals_breakdown(shift)

    def next(self):
        """Evaluate signal state, manage positions, and execute reversals/closures."""
        self.bar_num += 1
        warmup = int(self.p.length1 + self.p.ma_step * (self.p.ma_count - 1)) + int(self.p.length2) + int(self.p.signal_bar) + 10
        if len(self.data) < warmup:
            return
        buy_open, sell_open, buy_close, sell_close = self._signals()
        value = float(self.indicator.trend[0])
        if self.position:
            if self.position.size > 0:
                if buy_close and not sell_open:
                    self.log(f'close long trend={value:.4f}')
                    self.close()
                    return
                if sell_open:
                    self.log(f'close long & sell trend={value:.4f}')
                    self.close()
                    self.sell(size=self.p.lot)
                    return
            if self.position.size < 0:
                if sell_close and not buy_open:
                    self.log(f'close short trend={value:.4f}')
                    self.close()
                    return
                if buy_open:
                    self.log(f'close short & buy trend={value:.4f}')
                    self.close()
                    self.buy(size=self.p.lot)
                    return
        else:
            if buy_open:
                self.log(f'buy trend={value:.4f}')
                self.buy(size=self.p.lot)
                return
            if sell_open:
                self.log(f'sell trend={value:.4f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        """Update entry/exit counters and win/loss accounting."""
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')


REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


BASE_DIR = Path(__file__).resolve().parent

MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


def resolve_data_path(filename):
    """Resolve a configured data filename to an absolute path.

    Args:
        filename: Relative path string.

    Returns:
        pathlib.Path: Absolute validated file path.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Load normalized backtest data and return a frame dictionary.

    Args:
        config: Test configuration object.

    Returns:
        dict: Contains market data and parsed date boundaries.
    """
    data_cfg = config['data']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    df = load_mt5_csv(
        resolve_data_path(data_cfg['file']),
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )
    if df.empty:
        raise ValueError('Loaded data frame is empty')
    print(f"Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}")
    return {'data': df, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frame):
    """Create and configure Cerebro engine for this strategy.

    Args:
        config: Test configuration.
        frame: Data frame returned by `load_backtest_frame`.

    Returns:
        bt.Cerebro: Configured backtest engine.
    """
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type', 'fixed') == 'fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(
        commission=bt_cfg['commission'],
        margin=bt_cfg['margin'],
        mult=bt_cfg['multiplier'],
        commtype=comm_type,
        stocklike=bt_cfg.get('stocklike', False),
    )
    feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(VininITrendStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Assemble a deterministic metric payload from analyzer outputs.

    Args:
        strat: Finished strategy.
        cerebro: Executed Cerebro instance.
        frame: Backtest frame metadata.
        config: Strategy/backtest config.

    Returns:
        dict: Metrics used by regression assertions.
    """
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    total_trades = trades.get('total', {}).get('total', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'fromdate': frame['fromdate'],
        'todate': frame['todate'],
        'bars': len(frame['data']),
        'bar_num': strat.bar_num,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'trade_count': strat.trade_count,
        'win_count': strat.win_count,
        'loss_count': strat.loss_count,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1) * 100,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100) if total_trades else 0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'sqn': sqn.get('sqn'),
    }


def run(plot=False):
    """Run the backtest and return `(results, metrics, cerebro)`.

    Args:
        plot: Whether to render Backtrader plots after execution.

    Returns:
        tuple: `results, metrics, cerebro`.
    """
    config = _bt_load_config(_CONFIG, repo=_REPO)
    frame = load_backtest_frame(config)
    cerebro = build_cerebro(config, frame)
    print('\nStarting backtest...')
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frame, config)

    if plot:
        cerebro.plot()
    return results, metrics, cerebro


def _close(actual, expected, *, tol, key):
    """Assert ``actual`` is finite and within ``tol`` of ``expected``."""
    assert actual is not None, f"{key}: expected={expected}, got=None"
    a = float(actual)
    assert math.isfinite(a), f"{key}: expected={expected}, got non-finite {actual}"
    assert abs(a - float(expected)) <= tol, (
        f"{key}: expected={expected}, got={a} (tol={tol})"
    )


def _invoke_strategy_main():
    """Call main() or run() depending on what the original script defined."""
    import sys as _sys
    _mod = _sys.modules[__name__]
    if hasattr(_mod, "main") and callable(_mod.main):
        return _mod.main()
    if hasattr(_mod, "run") and callable(_mod.run):
        return _mod.run()
    raise RuntimeError("Neither main() nor run() found in inlined module")


def test_146_0146_1272_vinini_trend() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0146_1272_vinini_trend.
    """
    # Capture metrics by hooking extract_metrics() and invoking the original
    # main() (or run()). This reuses whatever loader / build_cerebro /
    # extract_metrics signatures the strategy used internally.
    captured = {}
    _orig_extract = extract_metrics
    def _capture_em(*a, **kw):
        m = _orig_extract(*a, **kw)
        if isinstance(m, dict):
            captured["metrics"] = m
        return m

    import sys as _sys
    _mod = _sys.modules[__name__]
    _mod.extract_metrics = _capture_em

    # Force runonce=True for the run inside main().
    import backtrader as _bt
    _orig_run = _bt.Cerebro.run
    def _forced_runonce(self, *args, **kwargs):
        kwargs["runonce"] = True
        return _orig_run(self, *args, **kwargs)
    _bt.Cerebro.run = _forced_runonce

    # Strip pytest argv so that argparse-based main() functions don't see them.
    _saved_argv = _sys.argv
    _sys.argv = [_sys.argv[0]]

    try:
        try:
            _invoke_strategy_main()
        except SystemExit:
            pass
        except Exception:
            if "metrics" not in captured:
                raise
    finally:
        _bt.Cerebro.run = _orig_run
        _mod.extract_metrics = _orig_extract
        _sys.argv = _saved_argv

    metrics = captured.get("metrics")
    assert metrics is not None, "extract_metrics() was not called"

    assert metrics.get('bar_num') == 6012, f"bar_num: expected=6012, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 54, f"buy_count: expected=54, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 55, f"sell_count: expected=55, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 48, f"win_count: expected=48, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 61, f"loss_count: expected=61, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 109, f"total_trades: expected=109, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 109, f"trade_count: expected=109, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 48, f"won: expected=48, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 61, f"lost: expected=61, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 998766.2000000003, tol=9.987662e-01, key='final_value')
    _close(metrics.get('net_pnl'), -1233.7999999996973, tol=1.233800e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), -0.12337999999997296, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 44.03669724770643, tol=4.403670e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 0.8707710999853261, tol=1.000000e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.7221983856507971, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), -2.0962673496483295, tol=2.096267e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), -7.048725275078784, tol=7.048725e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), -0.3891790824288644, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
