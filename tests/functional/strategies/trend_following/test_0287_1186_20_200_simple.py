"""20/200 Simple EA daily timezone momentum breakout bracket trading strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars) as base feed, with an H1 (60-minute) resampled data feed as the signal feed.
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Imbalances formed during specific daily trading hours (e.g. 18:00) produce robust breakout continuation setups.
    - **Momentum Evaluation**:
        - Compares the open price of a bar from `t1` hours ago with the open price of a bar from `t2` hours ago on the H1 resampled data feed.
        - *Bearish Momentum (Sell)*: Open price from `t1` hours ago is greater than open price from `t2` hours ago plus `delta` (70 pips).
        - *Bullish Momentum (Buy)*: Open price from `t1` hours ago plus `delta` (70 pips) is less than open price from `t2` hours ago.
    - **Bracket Order System**:
        - Places entries at `trade_hour` once per day.
        - Employs `buy_bracket()` or `sell_bracket()` orders to submit market entry along with linked stop-loss (`stop_loss_points`) and take-profit (`take_profit_points`) orders.

Strategy Logic:
    1. **Initialization**: Configures entry time (`trade_hour`), lookback offsets (`t1`, `t2`), breakout trigger (`delta`), and bracket levels.
    2. **Triggering**:
        - At exactly `trade_hour`, checks momentum on the resampled H1 signal feed.
    3. **Execution**:
        - Launches linked bracket orders containing the target lot size and target SL and TP boundaries.
    4. **Reporting**: Extracts Sharpe ratio, net returns, drawdowns, win rate, and total executed transactions.
"""
from __future__ import annotations
import math
from pathlib import Path
import io
import sys
import argparse
import datetime
import backtrader.feeds as btfeeds
import backtrader as bt
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': '20/200 Simple',
        'source_ea': 'ea/1186_20_200_Pips_-_Simple_Profitable_EA',
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
        'take_profit_points': 200,
        'stop_loss_points': 2000,
        'trade_hour': 18,
        't1': 7,
        't2': 2,
        'delta': 70,
        'lot': 0.1,
        'point': 0.01,
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



WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))



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


class Mt5PandasFeed(btfeeds.PandasData):
    """Custom Pandas Data Feed for MT5 CSV format.

    Maps MT5 CSV columns (open, high, low, close, volume, openinterest) to Backtrader-compatible fields.
    """
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TwentyTwoHundredSimpleStrategy(bt.Strategy):
    """20/200 Simple Daily Breakout Strategy with Bracket Orders.

    Uses t1/t2 hour open price delta at trade_hour on H1 signal feed to enter positions,
    leveraging automatic bracket orders for precise Stop Loss and Take Profit protection.
    """
    params = dict(
        take_profit_points=200,
        stop_loss_points=2000,
        trade_hour=18,
        t1=7,
        t2=2,
        delta=70,
        lot=0.1,
        point=0.01,
    )

    def __init__(self):
        """Initializes base and resampled data feeds, states, bracket order refs, and trading counters."""
        self.base = self.datas[0]
        self.h1 = self.datas[1]
        self.cantrade = True
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.entry_order_ref = None
        self.stop_order = None
        self.stop_order_ref = None
        self.limit_order = None
        self.limit_order_ref = None

    def log(self, text):
        """Logs strategy events with current datetime.

        Args:
            text (str): Log message.
        """
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _has_pending_orders(self):
        return any(order is not None for order in (self.entry_order, self.stop_order, self.limit_order))

    def _reset_orders(self):
        self.entry_order = None
        self.entry_order_ref = None
        self.stop_order = None
        self.stop_order_ref = None
        self.limit_order = None
        self.limit_order_ref = None

    def _entry_prices(self, is_long):
        price = float(self.base.close[0])
        stop_distance = float(self.p.stop_loss_points) * float(self.p.point)
        take_distance = float(self.p.take_profit_points) * float(self.p.point)
        if is_long:
            return price - stop_distance, price + take_distance
        return price + stop_distance, price - take_distance

    def _signal_open_buy(self):
        op1 = float(self.h1.open[-self.p.t1])
        op2 = float(self.h1.open[-self.p.t2])
        return (op1 + self.p.delta * self.p.point) < op2

    def _signal_open_sell(self):
        op1 = float(self.h1.open[-self.p.t1])
        op2 = float(self.h1.open[-self.p.t2])
        return op1 > (op2 + self.p.delta * self.p.point)

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Coordinates trading eligibility resets, and checks H1 breakout momentum signals at trade_hour
        to trigger connected bracket orders.
        """
        self.bar_num += 1
        if len(self.h1) <= max(self.p.t1, self.p.t2) + 1:
            return

        dt = bt.num2date(self.base.datetime[0])
        if dt.hour > self.p.trade_hour:
            self.cantrade = True

        if self.position or self._has_pending_orders():
            return
        if not self.cantrade or dt.hour != self.p.trade_hour:
            return

        open_buy = self._signal_open_buy()
        open_sell = self._signal_open_sell()
        if open_buy == open_sell:
            return

        size = abs(float(self.p.lot))
        self.signal_count += 1
        self.cantrade = False

        if open_buy:
            stop_price, limit_price = self._entry_prices(is_long=True)
            self.log(
                f'buy size={size:.2f} h1_open_t1={float(self.h1.open[-self.p.t1]):.2f} '
                f'h1_open_t2={float(self.h1.open[-self.p.t2]):.2f} stop={stop_price:.2f} limit={limit_price:.2f}'
            )
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=stop_price, limitprice=limit_price)
        else:
            stop_price, limit_price = self._entry_prices(is_long=False)
            self.log(
                f'sell size={size:.2f} h1_open_t1={float(self.h1.open[-self.p.t1]):.2f} '
                f'h1_open_t2={float(self.h1.open[-self.p.t2]):.2f} stop={stop_price:.2f} limit={limit_price:.2f}'
            )
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=stop_price, limitprice=limit_price)

        self.entry_order, self.stop_order, self.limit_order = orders
        self.entry_order_ref = self.entry_order.ref if self.entry_order is not None else None
        self.stop_order_ref = self.stop_order.ref if self.stop_order is not None else None
        self.limit_order_ref = self.limit_order.ref if self.limit_order is not None else None

    def notify_order(self, order):
        """Tracks the status of entry, stop, and limit orders in the bracket system.

        Args:
            order (bt.Order): Backtrader order status notification object.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return

        if self.entry_order_ref is not None and order.ref == self.entry_order_ref:
            if order.status == bt.Order.Completed:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
                self.cantrade = True
                self.log(f'entry failed status={order.getstatusname()}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.entry_order = None
                self.entry_order_ref = None
            return

        if self.stop_order_ref is not None and order.ref == self.stop_order_ref:
            if order.status == bt.Order.Completed:
                self.log(f'stop filled price={order.executed.price:.2f}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.stop_order = None
                self.stop_order_ref = None
            return

        if self.limit_order_ref is not None and order.ref == self.limit_order_ref:
            if order.status == bt.Order.Completed:
                self.log(f'take profit filled price={order.executed.price:.2f}')
            if order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
                self.limit_order = None
                self.limit_order_ref = None
            return

    def notify_trade(self, trade):
        """Logs trade closure, resets tracking orders, and records trade win/loss statistics.

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
        self._reset_orders()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')



WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))



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
    params = config.get('params', {})
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

    base_feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    h1_source = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    cerebro.adddata(base_feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.resampledata(h1_source, timeframe=bt.TimeFrame.Minutes, compression=60, name=f"{config['data']['symbol']}_H1")
    cerebro.addstrategy(TwentyTwoHundredSimpleStrategy, **params)
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


def test_286_0287_1186_20_200_simple() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0287_1186_20_200_simple.
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

    assert metrics.get('bar_num') == 6126, f"bar_num: expected=6126, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 31, f"buy_count: expected=31, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 33, f"sell_count: expected=33, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 46, f"win_count: expected=46, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 18, f"loss_count: expected=18, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 64, f"total_trades: expected=64, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 64, f"trade_count: expected=64, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 46, f"won: expected=46, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 18, f"lost: expected=18, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('signal_count'), 64.0, tol=6.400000e-05, key='signal_count')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 999493.8000000004, tol=9.994938e-01, key='final_value')
    _close(metrics.get('net_pnl'), -506.1999999996042, tol=5.062000e-04, key='net_pnl')
    _close(metrics.get('total_return_pct'), -0.05061999999995681, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 71.875, tol=7.187500e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 0.8894783956682192, tol=1.000000e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.25658799168198926, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), -2.049673586552664, tol=2.049674e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), -2.953330667608555, tol=2.953331e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), -0.26535951228884436, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
