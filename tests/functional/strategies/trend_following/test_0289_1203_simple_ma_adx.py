"""Simple MA and ADX trend-following momentum strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Strong trends are characterized by a combination of directional moving averages and trend strength verification.
    - **Indicators Used**:
        - *EMA (8)*: Moving Average representing the primary trend direction.
        - *ADX (8)*: Average Directional Index used to measure overall trend strength.
        - *+DI / -DI (8)*: Plus and Minus Directional Indicators used to confirm trend direction.
    - **Trading Rules**:
        - *Bullish (Buy)*: EMA rises on the last three bars (`ma0 > ma1 > ma2`), the previous close is above `ma1`, ADX is above `adx_min` (22.0), and `+DI` is greater than `-DI`.
        - *Bearish (Sell)*: EMA falls on the last three bars (`ma0 < ma1 < ma2`), the previous close is below `ma1`, ADX is above `adx_min` (22.0), and `+DI` is less than `-DI`.
        - *Position Management*: Closes opposite positions when a new signal occurs, and applies fixed stop loss (`stop_loss_points`) and take profit (`take_profit_points`) protection.

Strategy Logic:
    1. **Initialization**: Configures parameters for Moving Average and ADX periods, trend strength threshold (`adx_min`), and stop/take-profit targets.
    2. **Signal Scanning**:
        - On each bar, checks if EMA trend direction aligns with price relative to the EMA.
        - Verifies whether ADX confirms a sufficiently strong trend and uses DIs to filter buy vs sell.
    3. **Order Control**:
        - Opens buy/sell positions and executes early closure for opposite active trades.
        - Checks price limits on each bar for stop loss or take profit hits.
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
        'name': 'Simple MA ADX EA',
        'source_ea': 'ea/1203_Simple_EA_Based_on_Simple_MA_and_ADX',
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
        'stop_loss_points': 30,
        'take_profit_points': 100,
        'adx_period': 8,
        'ma_period': 8,
        'adx_min': 22.0,
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


class SimpleMaAdxStrategy(bt.Strategy):
    """Simple Moving Average and ADX Trend Strength Strategy.

    Combines EMA direction, close price filters, and ADX/DI trend strength conditions
    to initiate trades, protected by fixed Stop Loss and Take Profit levels.
    """
    params = dict(
        stop_loss_points=30,
        take_profit_points=100,
        adx_period=8,
        ma_period=8,
        adx_min=22.0,
        lot=0.1,
        point=0.01,
    )

    def __init__(self):
        """Initializes EMA, ADX, DI indicators, position indicators, and trading counters."""
        self.base = self.datas[0]
        self.ma = bt.ind.EMA(self.base.close, period=int(self.p.ma_period))
        self.adx = bt.ind.AverageDirectionalMovementIndex(self.base, period=int(self.p.adx_period))
        self.plus_di = bt.ind.PlusDirectionalIndicator(self.base, period=int(self.p.adx_period))
        self.minus_di = bt.ind.MinusDirectionalIndicator(self.base, period=int(self.p.adx_period))
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        """Logs strategy events with current datetime.

        Args:
            text (str): Log message.
        """
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        close_price = float(self.base.close[0])
        stop_distance = float(self.p.stop_loss_points) * float(self.p.point) if self.p.stop_loss_points > 0 else None
        take_distance = float(self.p.take_profit_points) * float(self.p.point) if self.p.take_profit_points > 0 else None
        entry_price = float(self.position.price)

        if self.position.size > 0:
            if stop_distance is not None and close_price <= entry_price - stop_distance:
                self.log(f'close long by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price >= entry_price + take_distance:
                self.log(f'close long by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        elif self.position.size < 0:
            if stop_distance is not None and close_price >= entry_price + stop_distance:
                self.log(f'close short by stop loss close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
            if take_distance is not None and close_price <= entry_price - take_distance:
                self.log(f'close short by take profit close={close_price:.2f} entry={entry_price:.2f}')
                self.close()
                return True
        return False

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Evaluates active positions for protection rules, and scans EMA/ADX/DI indicators
        for trend-following buy or sell entries.
        """
        self.bar_num += 1
        if len(self.base) < 4:
            return

        if self._check_exit_levels():
            return

        ma0 = float(self.ma[0])
        ma1 = float(self.ma[-1])
        ma2 = float(self.ma[-2])
        adx0 = float(self.adx[0])
        plus_di0 = float(self.plus_di[0])
        minus_di0 = float(self.minus_di[0])
        p_close = float(self.base.close[-1])
        size = abs(float(self.p.lot))
        if size <= 0:
            return

        buy_condition_1 = ma0 > ma1 and ma1 > ma2
        buy_condition_2 = p_close > ma1
        buy_condition_3 = adx0 > float(self.p.adx_min)
        buy_condition_4 = plus_di0 > minus_di0

        sell_condition_1 = ma0 < ma1 and ma1 < ma2
        sell_condition_2 = p_close < ma1
        sell_condition_3 = adx0 > float(self.p.adx_min)
        sell_condition_4 = plus_di0 < minus_di0

        close_price = float(self.base.close[0])
        if buy_condition_1 and buy_condition_2 and buy_condition_3 and buy_condition_4:
            self.signal_count += 1
            self.log(f'buy signal close={close_price:.2f} ma0={ma0:.5f} adx={adx0:.2f} +di={plus_di0:.2f} -di={minus_di0:.2f}')
            if self.position.size < 0:
                self.close()
            self.buy(size=size)
            return

        if sell_condition_1 and sell_condition_2 and sell_condition_3 and sell_condition_4:
            self.signal_count += 1
            self.log(f'sell signal close={close_price:.2f} ma0={ma0:.5f} adx={adx0:.2f} +di={plus_di0:.2f} -di={minus_di0:.2f}')
            if self.position.size > 0:
                self.close()
            self.sell(size=size)

    def notify_trade(self, trade):
        """Logs trade closure and records trade win/loss statistics.

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
    cerebro.adddata(base_feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(SimpleMaAdxStrategy, **params)
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


def test_288_0289_1203_simple_ma_adx() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0289_1203_simple_ma_adx.
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

    assert metrics.get('bar_num') == 6114, f"bar_num: expected=6114, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 917, f"buy_count: expected=917, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 821, f"sell_count: expected=821, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 781, f"win_count: expected=781, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 956, f"loss_count: expected=956, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 1738, f"total_trades: expected=1738, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 1737, f"trade_count: expected=1737, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 781, f"won: expected=781, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 956, f"lost: expected=956, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('signal_count'), 1927.0, tol=1.927000e-03, key='signal_count')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1000101.39999998, tol=1.000101e+00, key='final_value')
    _close(metrics.get('net_pnl'), 101.39999997999985, tol=1.014000e-04, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.01013999999799342, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 44.936708860759495, tol=4.493671e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.0015567593581642, tol=1.001557e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.3641715694815926, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), 0.16395024464400548, tol=1.000000e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 0.6021346211751508, tol=1.000000e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), 0.019427551452022445, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
