"""Simple FX dual-EMA trend-following trading strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Fast and slow moving average crossovers calculated on specialized prices (median, typical, weighted etc.) represent major trend shifts.
    - **Indicators Used**:
        - *Short MA (50)*: Shorter-period moving average.
        - *Long MA (200)*: Longer-period moving average.
    - **Trading Rules**:
        - *Bullish (Buy)*: Short MA is above Long MA on the last two bars (`short_ma[0] > long_ma[0]` and `short_ma[-1] > long_ma[-1]`).
        - *Bearish (Sell)*: Short MA is below Long MA on the last two bars (`short_ma[0] < long_ma[0]` and `short_ma[-1] < long_ma[-1]`).
        - *Position Management*: Closes active trades on trend reversals (e.g., exit long when the trend flips to BEAR), and employs fixed stop loss (`stop_loss`) and take profit (`take_profit`) targets.

Strategy Logic:
    1. **Initialization**: Configures parameters for Fast/Slow MA periods, MA methodologies (SMA, smoothed, weighted, EMA), applied price types, and SL/TP pips.
    2. **Trend Detection**:
        - On each bar, compares short and long MAs over two bars back to determine trend state (BULL, BEAR, or NEUTRAL).
    3. **Trade Exits**:
        - Checks price action on high/low against active stop/take profit limits.
        - Triggers immediate closure on trend reversal conditions.
    4. **Entry Triggers**:
        - Initiates long or short positions upon trend regime flips when currently flat.
    5. **Reporting**: Extracts Sharpe ratio, net returns, drawdowns, win rate, and total executed transactions.
"""
from __future__ import annotations
import backtrader as bt
import math
from pathlib import Path
import argparse
import datetime
import sys
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Simple_FX',
        'source_ea': 'ea/0772_Simple_FX',
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
        'lots': 0.1,
        'stop_loss': 30,
        'take_profit': 50,
        'short_ma_period': 50,
        'short_ma_method': 'EMA',
        'short_ma_applied_price': 'median',
        'long_ma_period': 200,
        'long_ma_method': 'EMA',
        'long_ma_applied_price': 'median',
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


BULL = 111111
BEAR = 222222


class Mt5PandasFeed(bt.feeds.PandasData):
    """Pandas feed mapping the normalized MT5 OHLCV columns to backtrader lines."""
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SimpleFXStrategy(bt.Strategy):
    """Dual-EMA trend regime strategy with point-based stop loss and take profit.

    Compares a short EMA against a long EMA on the median price to classify a
    bullish/bearish regime, entering on regime flips and exiting on reversal or
    the configured stop/take levels.
    """
    params = dict(
        lots=0.1,
        stop_loss=30,
        take_profit=50,
        short_ma_period=50,
        short_ma_method='EMA',
        short_ma_applied_price='median',
        long_ma_period=200,
        long_ma_method='EMA',
        long_ma_applied_price='median',
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initializes moving averages using chosen price lines, methods, and periods, and configures order tracking."""
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.last_trend_direction = 0
        self.stop_price = None
        self.take_profit_price = None
        self.exit_reason = None

        short_price = self._price_line(self.p.short_ma_applied_price)
        long_price = self._price_line(self.p.long_ma_applied_price)
        self.short_ma = self._make_ma(short_price, self.p.short_ma_period, self.p.short_ma_method)
        self.long_ma = self._make_ma(long_price, self.p.long_ma_period, self.p.long_ma_method)

        self.addminperiod(max(int(self.p.short_ma_period), int(self.p.long_ma_period)) + 2)

    def log(self, text):
        """Logs strategy events with current datetime.

        Args:
            text (str): Log message.
        """
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _price_line(self, applied_price):
        name = str(applied_price).strip().lower()
        if name == 'open':
            return self.data.open
        if name == 'high':
            return self.data.high
        if name == 'low':
            return self.data.low
        if name == 'median':
            return (self.data.high + self.data.low) / 2.0
        if name == 'typical':
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if name == 'weighted':
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close

    def _make_ma(self, price_line, period, method):
        method_name = str(method).strip().upper()
        if method_name == 'SMA':
            return bt.indicators.SimpleMovingAverage(price_line, period=int(period))
        if method_name == 'SMMA':
            return bt.indicators.SmoothedMovingAverage(price_line, period=int(period))
        if method_name == 'LWMA' or method_name == 'WMA':
            return bt.indicators.WeightedMovingAverage(price_line, period=int(period))
        return bt.indicators.ExponentialMovingAverage(price_line, period=int(period))

    def _trend_detection(self):
        short_0 = float(self.short_ma[0])
        short_1 = float(self.short_ma[-1])
        long_0 = float(self.long_ma[0])
        long_1 = float(self.long_ma[-1])
        if short_0 > long_0 and short_1 > long_1:
            return BULL
        if short_0 < long_0 and short_1 < long_1:
            return BEAR
        return 0

    def _distance(self, points):
        return float(points) * float(self.p.point)

    def _reset_exit_levels(self):
        self.stop_price = None
        self.take_profit_price = None
        self.exit_reason = None

    def _set_exit_levels(self, side, entry_price):
        stop_dist = self._distance(self.p.stop_loss)
        take_dist = self._distance(self.p.take_profit)
        self.stop_price = None if float(self.p.stop_loss) <= 0 else round(
            entry_price - stop_dist if side == 'buy' else entry_price + stop_dist,
            int(self.p.price_digits),
        )
        self.take_profit_price = None if float(self.p.take_profit) <= 0 else round(
            entry_price + take_dist if side == 'buy' else entry_price - take_dist,
            int(self.p.price_digits),
        )

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            stop_hit = self.stop_price is not None and low <= self.stop_price
            take_hit = self.take_profit_price is not None and high >= self.take_profit_price
        else:
            stop_hit = self.stop_price is not None and high >= self.stop_price
            take_hit = self.take_profit_price is not None and low <= self.take_profit_price
        if not stop_hit and not take_hit:
            return False
        self.exit_reason = 'take_profit' if take_hit and not stop_hit else 'stop_loss'
        self.log(f'close by {self.exit_reason}')
        self.order = self.close()
        return True

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Evaluates active trades for SL/TP hits or trend reversal exits,
        and opens new entries on moving average crossovers.
        """
        self.bar_num += 1
        if len(self.data) < max(int(self.p.short_ma_period), int(self.p.long_ma_period)) + 1:
            return
        if self.order is not None:
            return
        if self._check_exit_levels():
            return

        trend = self._trend_detection()
        if self.last_trend_direction == 0:
            if trend in (BULL, BEAR):
                self.last_trend_direction = trend
            return
        if trend == 0:
            return

        if self.position:
            if self.position.size > 0 and trend == BEAR:
                self.exit_reason = 'trend_reverse_to_bear'
                self.log('close buy on bearish trend')
                self.order = self.close()
                return
            if self.position.size < 0 and trend == BULL:
                self.exit_reason = 'trend_reverse_to_bull'
                self.log('close sell on bullish trend')
                self.order = self.close()
                return
            return

        size = float(self.p.lots)
        if trend == BULL and self.last_trend_direction == BEAR:
            self.signal_count += 1
            self.last_trend_direction = BULL
            self.log(f'open buy size={size:.2f}')
            self.order = self.buy(size=size)
            return
        if trend == BEAR and self.last_trend_direction == BULL:
            self.signal_count += 1
            self.last_trend_direction = BEAR
            self.log(f'open sell size={size:.2f}')
            self.order = self.sell(size=size)

    def notify_order(self, order):
        """Tracks order status and configures position exit targets on completed fills.

        Args:
            order (bt.Order): Backtrader order status notification object.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                side = 'buy' if self.position.size > 0 else 'sell'
                self._set_exit_levels(side, float(order.executed.price))
                if side == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(
                    f'{side} filled price={float(order.executed.price):.2f} size={abs(float(order.executed.size)):.2f} '
                    f'sl={self.stop_price} tp={self.take_profit_price}'
                )
            else:
                self.log(f'position closed price={float(order.executed.price):.2f} reason={self.exit_reason}')
                self._reset_exit_levels()
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Logs trade closure, resets risk parameters, and records trade win/loss statistics.

        Args:
            trade (bt.Trade): Backtrader trade notification object.
        """
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
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
    print(f"Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}")
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
    feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(SimpleFXStrategy, **config.get('params', {}))
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
        'signal_count': strat.signal_count,
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
        'open_position_size': strat.position.size,
        'open_position_price': strat.position.price,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'sqn': sqn.get('sqn'),
    }


def run(plot=False):
    """Orchestrates strategy loading, execution, evaluation, and optional plotting.

    Args:
        plot (bool, optional): Whether to plot backtest chart. Defaults to False.

    Returns:
        tuple: (results, metrics, cerebro) containing strategy results, metrics dict, and engine.
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


def test_73_0073_0772_simple_fx() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0073_0772_simple_fx.
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

    assert metrics.get('bar_num') == 5930, f"bar_num: expected=5930, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 14, f"buy_count: expected=14, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 13, f"sell_count: expected=13, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 14, f"win_count: expected=14, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 13, f"loss_count: expected=13, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 27, f"total_trades: expected=27, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 27, f"trade_count: expected=27, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 14, f"won: expected=14, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 13, f"lost: expected=13, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('signal_count'), 27.0, tol=2.700000e-05, key='signal_count')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 999619.7999999998, tol=9.996198e-01, key='final_value')
    _close(metrics.get('net_pnl'), -380.20000000018626, tol=3.802000e-04, key='net_pnl')
    _close(metrics.get('total_return_pct'), -0.038020000000016374, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 51.85185185185185, tol=5.185185e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 0.7131215573832508, tol=1.000000e-06, key='profit_factor')
    _close(metrics.get('open_position_size'), 0.0, tol=1.000000e-06, key='open_position_size')
    _close(metrics.get('open_position_price'), 0.0, tol=1.000000e-06, key='open_position_price')
    _close(metrics.get('max_drawdown'), 0.10721597290048697, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), -3.6798104759712618, tol=3.679810e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), -2.226323357293427, tol=2.226323e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), -0.4887282371431784, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
