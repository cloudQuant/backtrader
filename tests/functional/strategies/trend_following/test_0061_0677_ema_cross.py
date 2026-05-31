"""Simple EMA crossover trend-following strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Fast and slow exponential moving average crossovers signal the emergence of short-to-medium term trends.
    - **Indicators Used**:
        - *Fast EMA (9)*: Shorter-period exponential moving average.
        - *Slow EMA (45)*: Longer-period exponential moving average.
    - **Trading Rules**:
        - *Bullish (Buy)*: Fast EMA crosses above Slow EMA.
        - *Bearish (Sell)*: Fast EMA crosses below Slow EMA.
        - *Reverse Option*: Supports reversing the cross direction conditions based on `reverse` parameter.
        - *Exit/Take Profit*: Managed with fixed pip stop loss (`stop_loss`), take profit (`take_profit`), and trailing stops (`trailing_stop`).

Strategy Logic:
    1. **Initialization**: Configures parameters for Fast/Slow EMA periods, reverse signal flag, and SL/TP/trailing stop parameters.
    2. **Crossover Checking**:
        - Monitors closed bars to detect Fast/Slow EMA crossover signals.
    3. **Position Tracking**:
        - Syncs target exit price targets relative to entry on fills.
        - Applies trailing stop adjustments on active positions.
        - Evaluates high/low prices on each bar to enforce stop/take profit exits.
    4. **Reporting**: Extracts Sharpe ratio, net returns, drawdowns, win rate, and total executed transactions.
"""
from __future__ import annotations
import math
from pathlib import Path
import io
import argparse
import datetime
import sys
import backtrader as bt
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'ema_cross',
        'source_ea': 'ea/0677_EMA_CROSS/ema_cross.mq5',
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
        'reverse': True,
        'take_profit': 25,
        'stop_loss': 105,
        'lots': 0.5,
        'trailing_stop': 20,
        'short_ema': 9,
        'long_ema': 45,
        'point': 0.01,
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
    """Replace '{repo}' placeholder in config string values with absolute repo path."""
    if isinstance(node, dict):
        return {k: _resolve_repo_paths(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_repo_paths(v) for v in node]
    if isinstance(node, str):
        return node.replace('{repo}', str(_REPO))
    return node


def load_config(*args, **kwargs):
    """Inlined config (was config.yaml). Accepts any args for compatibility with strategies that pass a path."""
    import copy
    return _resolve_repo_paths(copy.deepcopy(_CONFIG))





def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Loads MT5 CSV data and parses it into a Pandas DataFrame.

    Cleans double quotes, strips whitespaces, and aligns the datetime index. Optionally shifts K-line datetime
    and filters by date range.

    Args:
        filepath (str or Path): Path to the CSV data file.
        fromdate (datetime, optional): Start date filter. Defaults to None.
        todate (datetime, optional): End date filter. Defaults to None.
        bar_shift_minutes (int, optional): Number of minutes to shift datetime index. Defaults to 0.

    Returns:
        pd.DataFrame: Processed OHLCV DataFrame indexed by datetime.
    """
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
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
        df['openinterest'] = 0
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    """Custom Pandas Data Feed for MT5 CSV format.

    Maps MT5 CSV columns (open, high, low, close, volume, openinterest) to Backtrader-compatible fields.
    """
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class EmaCrossStrategy(bt.Strategy):
    """Exponential Moving Average Crossover Strategy.

    Monitors dual EMAs for crossover entries, managed with trailing stops
    and fixed Stop Loss and Take Profit protection.
    """
    params = dict(
        reverse=True,
        take_profit=25,
        stop_loss=105,
        lots=0.5,
        trailing_stop=20,
        short_ema=9,
        long_ema=45,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initializes Fast and Slow EMA indicators, risk tracking variables, and trading counters."""
        self.ema_short = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.short_ema)
        self.ema_long = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.long_ema)
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._last_direction = 0
        self._first_time = True

    def log(self, text):
        """Logs strategy events with current datetime.

        Args:
            text (str): Log message.
        """
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _distance_unit(self):
        """Calculates adjusted pip price distance unit based on digits.

        Returns:
            float: Value of a pip adjusted for digits.
        """
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _crossed(self, line1, line2):
        """Monitors and detects direction crossovers between two lines.

        Args:
            line1 (float): Current value of the first line.
            line2 (float): Current value of the second line.

        Returns:
            int: 1 for upward cross, 2 for downward cross, 0 for no cross.
        """
        current_direction = 1 if line1 > line2 else 2
        if self._first_time:
            self._first_time = False
            self._last_direction = current_direction
            return 0
        if current_direction != self._last_direction:
            self._last_direction = current_direction
            return current_direction
        return 0

    def _sync_position_state(self):
        """Syncs entry price and initial SL/TP targets upon entering positions."""
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        distance_unit = self._distance_unit()
        stop_distance = float(self.p.stop_loss) * distance_unit
        take_distance = float(self.p.take_profit) * distance_unit
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance
            self._take_profit_price = self._entry_price + take_distance
        else:
            self._stop_price = self._entry_price + stop_distance
            self._take_profit_price = self._entry_price - take_distance

    def _update_trailing(self):
        """Calculates and updates trailing stop level based on market movements."""
        if not self.position or float(self.p.trailing_stop) <= 0:
            return
        distance = float(self.p.trailing_stop) * self._distance_unit()
        close = float(self.data.close[0])
        if self.position.size > 0 and close - self._entry_price > distance:
            candidate = round(close - distance, self.p.price_digits)
            if self._stop_price is None or candidate > self._stop_price:
                self._stop_price = candidate
        if self.position.size < 0 and self._entry_price - close > distance:
            candidate = round(close + distance, self.p.price_digits)
            if self._stop_price is None or candidate < self._stop_price:
                self._stop_price = candidate

    def _manage_risk(self):
        """Checks if current high/low prices hit stop loss or take profit limits.

        Returns:
            bool: True if position was closed, False otherwise.
        """
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'close long stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'close long tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'close short stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'close short tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Updates trailing stops, checks position protection limits, and scans
        EMA crossovers to trigger new trades.
        """
        self.bar_num += 1
        if len(self.data) < self.p.long_ema + 2:
            return
        if self.order is not None:
            return
        self._sync_position_state()
        self._update_trailing()
        if self._manage_risk():
            return
        crossed = self._crossed(float(self.ema_short[0]), float(self.ema_long[0])) if self.p.reverse else self._crossed(float(self.ema_long[0]), float(self.ema_short[0]))
        if self.position:
            return
        if crossed == 1:
            self.signal_count += 1
            self.log('buy signal on EMA cross')
            self.order = self.buy(size=float(self.p.lots))
            return
        if crossed == 2:
            self.signal_count += 1
            self.log('sell signal on EMA cross')
            self.order = self.sell(size=float(self.p.lots))

    def notify_order(self, order):
        """Tracks order status and updates protective target levels on completed fills.

        Args:
            order (bt.Order): Backtrader order status notification object.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Logs trade closure, resets risk states, and records trade win/loss statistics.

        Args:
            trade (bt.Trade): Backtrader trade notification object.
        """
        if trade.isopen and not self._position_was_open:
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



BASE_DIR = Path(__file__).resolve().parent

WORKSPACE_DIR = BASE_DIR.parents[2]
LOCAL_BACKTRADER_REPO = WORKSPACE_DIR / 'backtrader'
if LOCAL_BACKTRADER_REPO.exists() and str(LOCAL_BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(LOCAL_BACKTRADER_REPO))



MINUTES_PER_TRADING_YEAR = 24 * 60 * 252



def resolve_data_path(filename):
    """Resolves target data file path relative to strategy directory.

    Args:
        filename (str): Name or path string of the data file.

    Returns:
        Path: Absolute path to the existing data file.

    Raises:
        FileNotFoundError: If the resolved path does not exist.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Prepares and loads historical data frame based on configuration parameters.

    Args:
        config (dict): Strategy configuration dictionary containing data parameters.

    Returns:
        dict: Preprocessed data frame and datetime filters.

    Raises:
        ValueError: If loaded data frame is empty.
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
    print(f'Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}')
    return {'data': df, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frame):
    """Builds and configures the Backtrader Cerebro backtesting engine.

    Sets initial capital, commissions, margin, data feeds, strategy instance, and analytical monitors.

    Args:
        config (dict): Configuration dictionary containing backtest parameters.
        frame (dict): Loaded historical data frame dictionary with datetime filters.

    Returns:
        bt.Cerebro: Fully configured backtesting engine instance.
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
    feed = Mt5PandasFeed(
        dataname=frame['data'][['open', 'high', 'low', 'close', 'volume', 'openinterest']],
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
    )
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(EmaCrossStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Extracts performance metrics from completed strategy and engine analyzer outputs.

    Args:
        strat (bt.Strategy): Executed strategy instance.
        cerebro (bt.Cerebro): Completed backtesting engine.
        frame (dict): Loaded historical data frame dictionary.
        config (dict): Strategy configuration dictionary.

    Returns:
        dict: Performance summary statistics including Sharpe, return, drawdowns, and trade counts.
    """
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    total_trades = trades.get('total', {}).get('closed', won + lost)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {
        'fromdate': frame['fromdate'],
        'todate': frame['todate'],
        'bars': len(frame['data']),
        'bar_num': strat.bar_num,
        'signal_count': strat.signal_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'trade_count': strat.trade_count,
        'completed_orders': strat.completed_order_count,
        'rejected_orders': strat.rejected_order_count,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (final_value / initial_cash - 1) * 100,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
        'win_rate': (won / total_trades * 100) if total_trades else 0,
        'profit_factor': (gross_won / gross_lost) if gross_lost else None,
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sqn': sqn.get('sqn'),
    }



def run(plot=False):
    """Orchestrates strategy loading, execution, evaluation, and optional plotting.

    Args:
        plot (bool, optional): Whether to plot backtest chart. Defaults to False.

    Returns:
        tuple: (results, metrics, cerebro) containing strategy results, metrics dict, and engine.
    """
    config = load_config()
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


def test_61_0061_0677_ema_cross() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0061_0677_ema_cross.
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

    assert metrics.get('bar_num') == 6085, f"bar_num: expected=6085, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 93, f"buy_count: expected=93, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 92, f"sell_count: expected=92, got={metrics.get('sell_count')!r}"
    assert metrics.get('total_trades') == 185, f"total_trades: expected=185, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 185, f"trade_count: expected=185, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 86, f"won: expected=86, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 99, f"lost: expected=99, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('signal_count'), 185.0, tol=1.850000e-04, key='signal_count')
    _close(metrics.get('completed_orders'), 370.0, tol=3.700000e-04, key='completed_orders')
    _close(metrics.get('rejected_orders'), 0.0, tol=1.000000e-06, key='rejected_orders')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1006817.5, tol=1.006817e+00, key='final_value')
    _close(metrics.get('net_pnl'), 6817.5, tol=6.817500e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.6817499999999921, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 46.48648648648649, tol=4.648649e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.2242598684210482, tol=1.224260e-06, key='profit_factor')
    _close(metrics.get('sharpe_ratio'), 4.407197482584394, tol=4.407197e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 49.52214948523658, tol=4.952215e-05, key='annual_return_pct')
    _close(metrics.get('max_drawdown'), 0.49872893112731437, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sqn'), 0.5691963024373571, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
