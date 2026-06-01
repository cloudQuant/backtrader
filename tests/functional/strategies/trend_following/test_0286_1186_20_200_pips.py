"""20/200 Pips EA daily timezone momentum breakout trading strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars) as base feed, with an H1 (60-minute) resampled data feed as the signal feed.
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Price imbalances formed during specific trading hours of the day (e.g. 18:00) signal strong continuation or exhaustion momentum.
    - **Momentum Signal**:
        - Compares the open price of a bar from `t1` hours ago with the open price of a bar from `t2` hours ago on the H1 resampled data feed.
        - *Bearish Momentum (Sell)*: Open price from `t1` hours ago is greater than open price from `t2` hours ago plus `delta_points` (70 pips).
        - *Bullish Momentum (Buy)*: Open price from `t1` hours ago plus `delta_points` (70 pips) is less than open price from `t2` hours ago.
    - **Entry Restrictions**: Entries are placed precisely at the designated `trade_time_hour` (e.g. 18:00) once per day.

Strategy Logic:
    1. **Initialization**: Sets parameters for fixed breakout triggers (`trade_time_hour`, `t1`, `t2`, `delta_points`) and fixed pip protection targets (`stop_loss_points`, `take_profit_points`).
    2. **Signal Evaluation**:
        - Listens to the daily `trade_time_hour` on the H1 signal feed.
        - Calculates price differences over historical windows (`t1` and `t2` hours ago) to determine trend momentum.
    3. **Order Placement**:
        - Submits buy/sell orders of size `lot` based on momentum direction.
    4. **Position Protection**:
        - Once order completed, applies fixed pip Stop Loss (`stop_loss_points`) and Take Profit (`take_profit_points`) targets.
    5. **Reporting**: Extracts Sharpe ratio, net returns, drawdowns, win rate, and total executed transactions.
"""
from __future__ import annotations
import math
from pathlib import Path
import sys
import argparse
import datetime
import backtrader.feeds as btfeeds
import backtrader as bt
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': '20/200 Pips EA',
        'source_ea': 'ea/1186_20_200_Pips_-_Simple_Profitable_EA',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'M15',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
        'signal_tf_minutes': 60,
    },
    'params': {
        'take_profit_points': 200,
        'stop_loss_points': 2000,
        'trade_time_hour': 18,
        't1': 7,
        't2': 2,
        'delta_points': 70,
        'lot': 0.1,
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


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_SRC = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_SRC) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_SRC))


def resample_frame(df, rule):
    """Resamples OHLCV DataFrame into larger timeframe bars.

    Used to construct the signal timeframe bars from base timeframe data.

    Args:
        df (pd.DataFrame): Base timeframe OHLCV DataFrame.
        rule (str): Resampling frequency rule (e.g. '60min').

    Returns:
        pd.DataFrame: Resampled OHLCV DataFrame.
    """
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(btfeeds.PandasData):
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


class Twenty200PipsStrategy(bt.Strategy):
    """20/200 Pips Daily Breakout Momentum Strategy.

    Evaluates open price differences over t1/t2 hour windows at trade_time_hour to open long or short,
    employing fixed Stop Loss and Take Profit targets.
    """
    params = dict(
        take_profit_points=200,
        stop_loss_points=2000,
        trade_time_hour=18,
        t1=7,
        t2=2,
        delta_points=70,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initializes data feeds, states, trade statistics, and tracking parameters."""
        self.base = self.datas[0]
        self.h1 = self.datas[1]
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
        self.order = None
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

    def log(self, text):
        """Logs strategy events with current datetime.

        Args:
            text (str): Log message.
        """
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _clear_exit_levels(self):
        self.entry_side = None
        self.stop_price = None
        self.take_profit_price = None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.log(f'close long tp={self.take_profit_price:.2f}')
                self.order = self.close()
                return True
        elif self.position.size < 0:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.log(f'close short tp={self.take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Coordinates active position exit checks, and evaluates daily breakout momentum signals
        on the signal feed at trade_time_hour.
        """
        self.bar_num += 1
        if self.order is not None:
            return
        if len(self.h1) <= max(int(self.p.t1), int(self.p.t2)):
            return
        if self._manage_risk():
            return
        if self.position:
            return

        signal_dt = bt.num2date(self.h1.datetime[0])
        if signal_dt.hour != int(self.p.trade_time_hour):
            return
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        open_t1 = float(self.h1.open[-int(self.p.t1)])
        open_t2 = float(self.h1.open[-int(self.p.t2)])
        delta_price = float(self.p.delta_points) * float(self.p.point)
        size = abs(float(self.p.lot))
        if size <= 0:
            return

        if open_t1 > open_t2 + delta_price:
            self.signal_count += 1
            self.entry_side = 'short'
            self.log(f'sell signal h1_open_t1={open_t1:.2f} h1_open_t2={open_t2:.2f}')
            self.order = self.sell(size=size)
            return
        if open_t1 + delta_price < open_t2:
            self.signal_count += 1
            self.entry_side = 'long'
            self.log(f'buy signal h1_open_t1={open_t1:.2f} h1_open_t2={open_t2:.2f}')
            self.order = self.buy(size=size)

    def notify_order(self, order):
        """Tracks order status and sets SL/TP levels for completed transactions.

        Args:
            order (bt.Order): Backtrader order status notification object.
        """
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            self.completed_order_count += 1
            if order.isbuy() and self.entry_side == 'long' and self.position.size > 0:
                price = float(order.executed.price)
                self.stop_price = round(price - float(self.p.stop_loss_points) * float(self.p.point), int(self.p.price_digits))
                self.take_profit_price = round(price + float(self.p.take_profit_points) * float(self.p.point), int(self.p.price_digits))
                self.log(f'long filled price={price:.2f} sl={self.stop_price:.2f} tp={self.take_profit_price:.2f}')
            elif order.issell() and self.entry_side == 'short' and self.position.size < 0:
                price = float(order.executed.price)
                self.stop_price = round(price + float(self.p.stop_loss_points) * float(self.p.point), int(self.p.price_digits))
                self.take_profit_price = round(price - float(self.p.take_profit_points) * float(self.p.point), int(self.p.price_digits))
                self.log(f'short filled price={price:.2f} sl={self.stop_price:.2f} tp={self.take_profit_price:.2f}')
            elif not self.position:
                self._clear_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected, order.Expired]:
            self.rejected_order_count += 1
            if not self.position:
                self._clear_exit_levels()
            self.log(f'order {order.getstatusname()}')
        if self.order is not None and order.ref == self.order.ref and order.status not in [order.Submitted, order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Logs trade closure, resets exit parameters, and records trade win/loss statistics.

        Args:
            trade (bt.Trade): Backtrader trade notification object.
        """
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
        self._clear_exit_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_SRC = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_SRC) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_SRC))


BASE_DIR = Path(__file__).resolve().parent

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


def load_backtest_frames(config):
    """Prepares and loads base and resampled historical data frames based on configuration parameters.

    Args:
        config (dict): Strategy configuration dictionary containing data parameters.

    Returns:
        dict: Preprocessed data frames and datetime filters.

    Raises:
        ValueError: If loaded base data frame is empty.
    """
    data_cfg = config['data']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    base = load_mt5_csv(
        resolve_data_path(data_cfg['file']),
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )
    if base.empty:
        raise ValueError('Loaded data frame is empty')
    h1 = resample_frame(base, f"{data_cfg.get('signal_tf_minutes', 60)}min")
    print(f"Loaded bars: M15={len(base)}, H1={len(h1)}")
    return {'m15': base, 'h1': h1, 'fromdate': fromdate, 'todate': todate}


def build_cerebro(config, frames):
    """Builds and configures the Backtrader Cerebro backtesting engine.

    Sets initial capital, commissions, margin, data feeds, strategy instance, and analytical monitors.

    Args:
        config (dict): Configuration dictionary containing backtest parameters.
        frames (dict): Loaded historical data frames dictionary with datetime filters.

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
    feed_m15 = Mt5PandasFeed(dataname=frames['m15'], timeframe=bt.TimeFrame.Minutes, compression=15)
    feed_h1 = Mt5PandasFeed(dataname=frames['h1'], timeframe=bt.TimeFrame.Minutes, compression=60)
    cerebro.adddata(feed_m15, name='XAUUSD_M15')
    cerebro.adddata(feed_h1, name='XAUUSD_H1')
    cerebro.addstrategy(Twenty200PipsStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frames, config):
    """Extracts performance metrics from completed strategy and engine analyzer outputs.

    Args:
        strat (bt.Strategy): Executed strategy instance.
        cerebro (bt.Cerebro): Completed backtesting engine.
        frames (dict): Loaded historical data frames dictionary.
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
        'fromdate': frames['fromdate'],
        'todate': frames['todate'],
        'bars_m15': len(frames['m15']),
        'bars_h1': len(frames['h1']),
        'bar_num': strat.bar_num,
        'signal_count': strat.signal_count,
        'buy_count': strat.buy_count,
        'sell_count': strat.sell_count,
        'trade_count': strat.trade_count,
        'win_count': strat.win_count,
        'loss_count': strat.loss_count,
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
    frames = load_backtest_frames(config)
    cerebro = build_cerebro(config, frames)
    print('\nStarting backtest...')
    results = cerebro.run()
    strat = results[0]
    metrics = extract_metrics(strat, cerebro, frames, config)

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


def test_285_0286_1186_20_200_pips() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0286_1186_20_200_pips.
    """
    # Capture metrics by hooking extract_metrics() (or similar) and invoking the
    # original main()/run(). This reuses whatever loader / build_cerebro /
    # metrics-extraction signatures the strategy used internally.
    captured = {}

    import sys as _sys
    _mod = _sys.modules[__name__]

    # Hook any plausible metrics-extraction function.
    _hook_targets = []
    _metric_names = (
        "extract_metrics", "summarize", "build_metrics", "compute_metrics",
        "calculate_metrics", "collect_metrics", "gather_metrics", "extract_results",
    )
    for _name in _metric_names:
        _orig = getattr(_mod, _name, None)
        if callable(_orig):
            def _make_hook(orig):
                def _hook(*a, **kw):
                    m = orig(*a, **kw)
                    if isinstance(m, dict) and m and "metrics" not in captured:
                        captured["metrics"] = m
                    return m
                return _hook
            setattr(_mod, _name, _make_hook(_orig))
            _hook_targets.append((_name, _orig))

    # Force runonce=True for the cerebro.run() call inside main().
    import backtrader as _bt
    _orig_run = _bt.Cerebro.run
    def _forced_runonce(self, *args, **kwargs):
        kwargs["runonce"] = True
        return _orig_run(self, *args, **kwargs)
    _bt.Cerebro.run = _forced_runonce

    # Strip pytest argv so argparse-based main() functions don't see them.
    _saved_argv = _sys.argv
    _sys.argv = [_sys.argv[0]]

    try:
        try:
            if hasattr(_mod, "main") and callable(_mod.main):
                _mod.main()
            elif hasattr(_mod, "run") and callable(_mod.run):
                result = _mod.run()
                if isinstance(result, dict) and "metrics" not in captured:
                    captured["metrics"] = result
                elif isinstance(result, (list, tuple)):
                    for item in result:
                        if isinstance(item, dict) and "metrics" not in captured:
                            captured["metrics"] = item
                            break
            else:
                raise RuntimeError("Neither main() nor run() found in inlined module")
        except SystemExit:
            pass
        except Exception:
            if "metrics" not in captured:
                raise
    finally:
        _bt.Cerebro.run = _orig_run
        for _name, _orig in _hook_targets:
            setattr(_mod, _name, _orig)
        _sys.argv = _saved_argv

    metrics = captured.get("metrics")
    assert metrics is not None, "no metrics captured during run"

    assert metrics.get('bar_num') == 6133, f"bar_num: expected=6133, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 31, f"buy_count: expected=31, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 33, f"sell_count: expected=33, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 34, f"win_count: expected=34, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 30, f"loss_count: expected=30, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 64, f"total_trades: expected=64, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 64, f"trade_count: expected=64, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 34, f"won: expected=34, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 30, f"lost: expected=30, got={metrics.get('lost')!r}"
    _close(metrics.get('bars_m15'), 6129.0, tol=6.129000e-03, key='bars_m15')
    _close(metrics.get('bars_h1'), 1538.0, tol=1.538000e-03, key='bars_h1')
    _close(metrics.get('signal_count'), 64.0, tol=6.400000e-05, key='signal_count')
    _close(metrics.get('completed_orders'), 128.0, tol=1.280000e-04, key='completed_orders')
    _close(metrics.get('rejected_orders'), 0.0, tol=1.000000e-06, key='rejected_orders')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1000127.4, tol=1.000127e+00, key='final_value')
    _close(metrics.get('net_pnl'), 127.40000000002328, tol=1.274000e-04, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.012739999999999974, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 53.125, tol=5.312500e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.0324123543479549, tol=1.032412e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.20838637153132514, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), 0.5336691154050847, tol=1.000000e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 0.7562344158790831, tol=1.000000e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), 0.06868275978123607, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
