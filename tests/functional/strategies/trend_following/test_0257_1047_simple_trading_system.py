"""Regression test for ``Exp_Simple_Trading_System`` migration in trend_following.

Data Used:
    - CSV file: ``tests/datas/XAUUSD_M15.csv`` resolved from ``{repo}``.
    - Symbol: ``XAUUSD`` at 15-minute base granularity (`M15`).
    - Signal feed is built from a resampled `H6` (360-minute) frame using ATR + EMA derived arrows.
    - Backtest interval: ``2025-12-03 01:15:00`` to ``2026-03-10 09:00:00``.
    - The source bars are shifted by ``bar_shift_minutes=15`` before windowing.

Strategy Principle:
    The strategy emits buy/sell trigger points from an EMA trend-state filter and ATR-based
    leveling:

    - ``buy_arrow`` indicates a short-term long entry candidate.
    - ``sell_arrow`` indicates a short-term short entry candidate.
    - Position opening/closing obeys strategy flags for open-close permission and stop-loss /
      take-profit risk guardrails.

Strategy Logic:
    - Parse MT5 CSV into a normalized base DataFrame and resample to the signal timeframe.
    - Enrich signal data using EMA/ATR with directional arrow signals.
    - Backtest with two feeds (`M15` execution + `H6` signal feed) and feed events into strategy.
    - Track trade lifecycle counters and assert migration metrics from analyzer output.
"""
from __future__ import annotations
import math
from pathlib import Path
import io
import argparse
import datetime
import sys
import backtrader as bt
import numpy as np
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Exp_Simple_Trading_System',
        'source_ea': 'ea/1047_Exp_Simple_Trading_System',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'M15',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
        'signal_tf_minutes': 360,
    },
    'params': {
        'mm': 0.1,
        'mm_mode': 'LOT',
        'stop_loss': 1000,
        'take_profit': 2000,
        'deviation': 10,
        'buy_pos_open': True,
        'sell_pos_open': True,
        'buy_pos_close': True,
        'sell_pos_close': True,
        'ma_shift': 4,
        'ma_period': 2,
        'ma_type': 'EMA',
        'signal_bar': 1,
        'size': 0.1,
        'point': 0.01,
        'digits_adjust': 10,
        'price_digits': 2,
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


def _resolve_repo_paths(node):
    """Replace ``{repo}`` placeholders in all string nodes with the repo absolute path."""
    if isinstance(node, dict):
        return {k: _resolve_repo_paths(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_repo_paths(v) for v in node]
    if isinstance(node, str):
        return node.replace('{repo}', str(_REPO))
    return node


def load_config(*args, **kwargs):
    """Load the embedded regression configuration.

    Args:
        *args: Compatibility positional arguments retained for callers that forward args.
        **kwargs: Compatibility keyword arguments retained for callers that forward kwargs.

    Returns:
        dict: A deep copy of the module config with resolved repository placeholders.
    """
    import copy
    return _resolve_repo_paths(copy.deepcopy(_CONFIG))





def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load MT5-style tab-separated CSV into a canonical DataFrame.

    Args:
        filepath: Path to MT5 export file.
        fromdate: Optional inclusive datetime lower bound.
        todate: Optional inclusive datetime upper bound.
        bar_shift_minutes: Optional minute shift applied to index timestamps.

    Returns:
        pandas.DataFrame: Indexed OHLCV data for Backtrader consumption.
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    """Resample a minute-indexed DataFrame to the target bar rule.

    Args:
        df: Source DataFrame with datetime index and OHLCV fields.
        rule: Resample rule accepted by ``pandas.DataFrame.resample``.

    Returns:
        pandas.DataFrame: Resampled bars with cleaned OHLCV data.
    """
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def ema(series, period):
    """Compute exponential moving average.

    Args:
        series: Input series.
        period: EMA span/period.

    Returns:
        pandas.Series: EMA-smoothed series.
    """
    return series.ewm(span=int(period), adjust=False).mean()


def compute_atr(frame, period=15):
    """Compute a simple ATR-style rolling average from high/low/close.

    Args:
        frame: DataFrame containing OHLC columns.
        period: Lookback period for the rolling mean.

    Returns:
        pandas.Series: Average true range approximation.
    """
    prev_close = frame['close'].shift(1)
    tr = pd.concat([
        frame['high'] - frame['low'],
        (frame['high'] - prev_close).abs(),
        (frame['low'] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(int(period)).mean()


def compute_simple_trading_system(frame, ma_shift=4, ma_period=2, ma_type='EMA'):
    """Build directional arrow signals from MA and ATR logic.

    Args:
        frame: Base DataFrame with OHLC columns.
        ma_shift: Shift for EMA trend comparison.
        ma_period: EMA window.
        ma_type: Expected to be ``EMA`` in this migration.

    Returns:
        pandas.DataFrame: Input frame augmented with ``buy_arrow`` and ``sell_arrow``.
    """
    ma_shift = int(ma_shift)
    ma_period = int(ma_period)
    sum_period = ma_period + ma_shift
    ma_type = str(ma_type).upper()
    if ma_type != 'EMA':
        raise ValueError('Only EMA is reconstructed in this migration')
    atr = compute_atr(frame, 15)
    ma = ema(frame['close'], ma_period)
    buy_arrow = np.full(len(frame), np.nan, dtype=float)
    sell_arrow = np.full(len(frame), np.nan, dtype=float)
    sign = 0
    min_rates_total = max(15, ma_period + ma_shift)
    for idx in range(len(frame)):
        if idx < max(min_rates_total, sum_period, ma_shift) or np.isnan(float(atr.iloc[idx])) or np.isnan(float(ma.iloc[idx])):
            continue
        ma0 = float(ma.iloc[idx])
        ma1 = float(ma.iloc[idx - ma_shift])
        close0 = float(frame['close'].iloc[idx])
        close_shift = float(frame['close'].iloc[idx - ma_shift])
        close_sum = float(frame['close'].iloc[idx - sum_period])
        open0 = float(frame['open'].iloc[idx])
        if sign < 1 and ma0 <= ma1 and close0 >= close_shift and close0 <= close_sum and close0 < open0:
            buy_arrow[idx] = float(frame['low'].iloc[idx] - atr.iloc[idx] * 3.0 / 8.0)
            sign = 1
        elif sign > -1 and ma0 >= ma1 and close0 <= close_shift and close0 >= close_sum and close0 > open0:
            sell_arrow[idx] = float(frame['high'].iloc[idx] + atr.iloc[idx] * 3.0 / 8.0)
            sign = -1
    out = frame.copy()
    out['buy_arrow'] = buy_arrow
    out['sell_arrow'] = sell_arrow
    return out.dropna(subset=['buy_arrow', 'sell_arrow'], how='all')


class Mt5PandasFeed(bt.feeds.PandasData):
    """Base feed for OHLCV data from MT5 CSV."""
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SimpleTradingSystemFeed(bt.feeds.PandasData):
    """Signal feed carrying buy/sell arrow markers for strategy decisions."""
    lines = ('buy_arrow', 'sell_arrow')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5), ('buy_arrow', 6), ('sell_arrow', 7),
    )


class SimpleTradingSystemStrategy(bt.Strategy):
    """Simple trading system strategy that reacts to ATR/EMA signal arrows."""
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss=1000,
        take_profit=2000,
        deviation=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        ma_shift=4,
        ma_period=2,
        ma_type='EMA',
        signal_bar=1,
        size=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        """Bind feeds and initialize counters/risk state."""
        self.m15 = self.datas[0]
        self.h6 = self.datas[1]
        self.buy_arrow = self.h6.buy_arrow
        self.sell_arrow = self.h6.sell_arrow

        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.entry_order = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

    def log(self, text):
        """Print a timestamped message.

        Args:
            text: Message content.
        """
        dt = bt.num2date(self.m15.datetime[0])
        print('{0}, {1}'.format(dt.isoformat(), text))

    def _trade_unit(self):
        return self.p.point * self.p.digits_adjust

    def _has_buy_signal(self, idx):
        value = float(self.buy_arrow[-idx])
        return not math.isnan(value) and value != 0.0

    def _has_sell_signal(self, idx):
        value = float(self.sell_arrow[-idx])
        return not math.isnan(value) and value != 0.0

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            float(self.buy_arrow[-idx])
            float(self.sell_arrow[-idx])
        except (TypeError, ValueError, IndexError):
            return False
        return True

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.m15.high[0])
        low = float(self.m15.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.entry_order = self.close()
                return True
        return False

    def _set_risk_prices(self, side):
        price = float(self.m15.close[0])
        unit = self._trade_unit()
        if side == 'buy':
            self.stop_price = round(price - self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + self.p.stop_loss * unit, self.p.price_digits) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - self.p.take_profit * unit, self.p.price_digits) if self.p.take_profit > 0 else None

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        buy_open = buy_close = sell_open = sell_close = False
        has_buy = self._has_buy_signal(idx)
        has_sell = self._has_sell_signal(idx)
        if has_buy:
            if self.p.buy_pos_open:
                buy_open = True
                self.buy_signal_count += 1
            if self.p.sell_pos_close:
                sell_close = True
        if has_sell:
            if self.p.sell_pos_open:
                sell_open = True
                self.sell_signal_count += 1
            if self.p.buy_pos_close:
                buy_close = True
        if ((self.p.buy_pos_open and self.p.buy_pos_close) or (self.p.sell_pos_open and self.p.sell_pos_close)) and (not buy_close and not sell_close):
            bars_available = len(self.h6)
            for back in range(idx + 1, bars_available):
                if self.p.sell_pos_close and self._has_buy_signal(back):
                    sell_close = True
                    break
                if self.p.buy_pos_close and self._has_sell_signal(back):
                    buy_close = True
                    break
        return buy_open, buy_close, sell_open, sell_close, has_buy, has_sell

    def next(self):
        """Process one bar, evaluate risk, and handle entry/close signaling."""
        self.bar_num += 1
        if self.entry_order is not None:
            return
        if not self._enough_history():
            return
        if self._manage_risk():
            return
        signal_dt = bt.num2date(self.h6.datetime[-max(int(self.p.signal_bar), 1)])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, has_buy, has_sell = self._evaluate_signals()
        self.log('simple_trading_system buy_signal={0} sell_signal={1} buy_open={2} sell_open={3}'.format(has_buy, has_sell, buy_open, sell_open))
        if buy_close and self.position and self.position.size > 0:
            self.entry_order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.entry_order = self.close()
            return
        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('buy')
            self.entry_order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.entry_order = self.close()
                return
            self._set_risk_prices('sell')
            self.entry_order = self.sell(size=self.p.size)

    def notify_order(self, order):
        """Track order completion/cancellation and clear temporary order references."""
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        """Update aggregate closed-trade metrics."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1



BASE_DIR = Path(__file__).resolve().parent

WORKSPACE_DIR = BASE_DIR.parents[2]
LOCAL_BACKTRADER_REPO = WORKSPACE_DIR / 'backtrader'
if LOCAL_BACKTRADER_REPO.exists():
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))



MINUTES_PER_TRADING_YEAR = 24 * 60 * 252



def resolve_data_path(filename):
    """Resolve a data path under the test strategy directory.

    Args:
        filename: Relative file path.

    Returns:
        pathlib.Path: Absolute file path.

    Raises:
        FileNotFoundError: If the resolved path does not exist.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError('Data file not found: {0}'.format(path))
    return path


def load_backtest_frames(config):
    """Load and build both execution and signal frames for backtest.

    Args:
        config: Strategy configuration payload.

    Returns:
        dict: Contains loaded frame data and resolved date bounds.
    """
    data_cfg = config['data']
    params = config['params']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    base = load_mt5_csv(resolve_data_path(data_cfg['file']), fromdate=fromdate, todate=todate, bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if base.empty:
        raise ValueError('Loaded data frame is empty')
    h6 = resample_frame(base, '{0}min'.format(data_cfg.get('signal_tf_minutes', 360)))
    h6 = compute_simple_trading_system(h6, ma_shift=params['ma_shift'], ma_period=params['ma_period'], ma_type=params['ma_type'])
    print('Loaded bars: M15={0}, H6={1}'.format(len(base), len(h6)))
    return {'m15': base, 'h6': h6, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frame):
    """Create Backtrader engine, attach data feeds, strategy, and analyzers.

    Args:
        config: Backtest and strategy configuration.
        frame: Loaded data dictionary.

    Returns:
        bt.Cerebro: Prepared engine.
    """
    bt_cfg = config['backtest']
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type', 'fixed') == 'fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(commission=bt_cfg['commission'], margin=bt_cfg['margin'], mult=bt_cfg['multiplier'], commtype=comm_type, stocklike=bt_cfg.get('stocklike', False))
    feed_m15 = Mt5PandasFeed(dataname=frame['m15'], timeframe=bt.TimeFrame.Minutes, compression=15)
    feed_h6 = SimpleTradingSystemFeed(dataname=frame['h6'][['open', 'high', 'low', 'close', 'volume', 'openinterest', 'buy_arrow', 'sell_arrow']], timeframe=bt.TimeFrame.Minutes, compression=360)
    cerebro.adddata(feed_m15, name='XAUUSD_M15')
    cerebro.adddata(feed_h6, name='XAUUSD_H6_SIMPLE_TRADING_SYSTEM')
    cerebro.addstrategy(SimpleTradingSystemStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Collect metrics from analyzer output and strategy counters.

    Args:
        strat: Finished strategy instance.
        cerebro: Backtrader engine used in run.
        frame: Data frame bundle.
        config: Full configuration.

    Returns:
        dict: Metric dictionary for regression assertions.
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
        'fromdate': frame['fromdate'], 'todate': frame['todate'], 'bars_m15': len(frame['m15']), 'bars_h6': len(frame['h6']),
        'bar_num': strat.bar_num, 'buy_signal_count': strat.buy_signal_count, 'sell_signal_count': strat.sell_signal_count,
        'buy_count': strat.buy_count, 'sell_count': strat.sell_count, 'trade_count': strat.trade_count,
        'win_count': strat.win_count, 'loss_count': strat.loss_count, 'completed_order_count': strat.completed_order_count,
        'rejected_order_count': strat.rejected_order_count, 'initial_cash': initial_cash, 'final_value': final_value,
        'net_pnl': final_value - initial_cash, 'total_return_pct': (final_value / initial_cash - 1) * 100,
        'total_trades': total_trades, 'won': won, 'lost': lost, 'win_rate': (won / total_trades * 100) if total_trades else 0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None, 'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sharpe_ratio': sharpe.get('sharperatio'), 'annual_return_pct': (returns.get('rnorm') or 0) * 100, 'sqn': sqn.get('sqn'),
    }



def run(plot=False):
    """Run strategy backtest and return the results tuple used by legacy harness.

    Args:
        plot: Optional plot rendering flag.

    Returns:
        tuple: ``(results, metrics, cerebro)``.
    """
    config = load_config()
    frame = load_backtest_frames(config)
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


def test_256_0257_1047_simple_trading_system() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0257_1047_simple_trading_system.
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

    assert metrics.get('bar_num') == 4433, f"bar_num: expected=4433, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 2, f"buy_count: expected=2, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 0, f"sell_count: expected=0, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 1, f"win_count: expected=1, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 1, f"loss_count: expected=1, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 2, f"total_trades: expected=2, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 2, f"trade_count: expected=2, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 1, f"won: expected=1, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 1, f"lost: expected=1, got={metrics.get('lost')!r}"
    _close(metrics.get('bars_m15'), 6129.0, tol=6.129000e-03, key='bars_m15')
    _close(metrics.get('bars_h6'), 3.0, tol=3.000000e-06, key='bars_h6')
    _close(metrics.get('buy_signal_count'), 2.0, tol=2.000000e-06, key='buy_signal_count')
    _close(metrics.get('sell_signal_count'), 1.0, tol=1.000000e-06, key='sell_signal_count')
    _close(metrics.get('completed_order_count'), 4.0, tol=4.000000e-06, key='completed_order_count')
    _close(metrics.get('rejected_order_count'), 0.0, tol=1.000000e-06, key='rejected_order_count')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1001767.5000000007, tol=1.001768e+00, key='final_value')
    _close(metrics.get('net_pnl'), 1767.5000000006985, tol=1.767500e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.1767500000000588, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 50.0, tol=5.000000e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 8.796647551830587, tol=8.796648e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.09184846383294025, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), 7.924545445927433, tol=7.924545e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 11.021765746356705, tol=1.102177e-05, key='annual_return_pct')
    _close(metrics.get('sqn'), 1.1254997845443035, tol=1.125500e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
