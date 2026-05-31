"""Daily breakout channel timezone breakout trading strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars) as base feed, with resampled daily ('1D') data feed as the second feed.
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Breakthroughs across the previous day's high/low range during specific daily session times signal strong and sustained intraday breakout continuation momentum.
    - **Breakout Levels**:
        - Instantiates a daily breakout boundary using the prior day's high and low prices.
        - Calculates target entry prices (`buy_price` and `sell_price`) by shifting the boundaries by `delta` pips and validating against broker minimum stop levels.
    - **Session Timing**:
        - Triggers the establishment of breakout boundaries exactly at `time_set` (e.g. 07:30) once per day.
        - Virtual stop order entries (`_place_stop_orders`) are placed and active for the session day.

Strategy Logic:
    1. **Initialization**: Configures setup hours (`time_set`), offset spacing (`delta`), risk percent levels, and protective targets (SL/TP, break-even shift, trailing).
    2. **Triggering**:
        - At exactly `time_set` each day, computes prior day high/low values to store virtual breakout buy/sell prices.
    3. **Order Placement**:
        - Scans current bar high/low values against the virtual buy/sell price boundaries.
        - If a level is crossed, launches a market order of size `lots` (or capital-risk scaled lot size) with attached SL/TP targets.
    4. **Risk Management**:
        - Evaluates high/low prices on each bar against active position SL and TP targets.
        - Adjusts active stop loss levels using `no_loss` (break-even shift) and `trailing` stop parameters.
    5. **Reporting**: Extracts Sharpe ratio, net returns, drawdowns, win rate, and total executed transactions.
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
        'name': 'BreakdownLevelDay',
        'source_ea': 'ea/0734_BreakdownLevelDay',
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
        'time_set': '07:30',
        'delta': 0,
        'sl': 120,
        'tp': 90,
        'risk': 0.0,
        'no_loss': 0,
        'trailing': 0,
        'lot': 0.1,
        'open_stop': True,
        'point': 0.01,
        'digits_adjust': 10,
        'price_digits': 2,
        'last_day': 0,
    },
    'backtest': {
        'initial_cash': 1000000,
        'commission': 0.0,
        'margin': 0.01,
        'multiplier': 100.0,
        'commission_type': 'fixed',
        'stocklike': False,
        'min_lot': 0.01,
        'max_lot': 100.0,
        'lot_precision': 2,
        'stop_level': 0,
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
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
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


def resample_daily(df):
    """Resamples OHLCV DataFrame into daily ('1D') interval bars.

    Used to extract high/low range boundaries from historical daily trading blocks.

    Args:
        df (pd.DataFrame): Base timeframe OHLCV DataFrame.

    Returns:
        pd.DataFrame: Daily resampled OHLCV DataFrame.
    """
    out = df.resample('1D', label='right', closed='right').agg({
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


class Mt5PandasFeed(bt.feeds.PandasData):
    """Custom Pandas Data Feed for MT5 CSV format.

    Maps MT5 CSV columns (open, high, low, close, volume, openinterest) to Backtrader-compatible fields.
    """
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class BreakdownLevelDayStrategy(bt.Strategy):
    """Breakdown Level Day Strategy.

    Coordinates virtual breakout stop levels calculated off of prior day high/low channels at trade_set hour,
    supporting dynamically scaled lot sizes, trailing stops, and break-even shifting.
    """
    params = dict(
        time_set='07:32',
        delta=6,
        sl=120,
        tp=90,
        risk=0.0,
        no_loss=0,
        trailing=0,
        lot=0.10,
        open_stop=True,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        min_lot=0.01,
        max_lot=100.0,
        lot_precision=2,
        margin_per_lot=250.0,
        stop_level=0,
        last_day=0,
    )

    def __init__(self):
        """Initializes data feeds, states, trade statistics, and tracking parameters."""
        self.day_data = self.datas[1]

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.order = None
        self.pending_order = None
        self.pending_side = None
        self.pending_price = None
        self.pending_stop = None
        self.pending_take = None
        self.pending_day = None
        self.current_day = None
        self.stop_price = None
        self.take_profit_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _effective_lot(self):
        if float(self.p.risk) == 0:
            return float(self.p.lot)
        free_margin = self.broker.getcash()
        lot = free_margin * float(self.p.risk) / 100.0 / float(self.p.margin_per_lot)
        lot = max(float(self.p.min_lot), min(float(self.p.max_lot), lot))
        return round(lot, int(self.p.lot_precision))

    def _time_match(self):
        if self.p.time_set == '00:00':
            return True
        current_dt = bt.num2date(self.data.datetime[0])
        return current_dt.strftime('%H:%M') == str(self.p.time_set)

    def _new_day(self):
        current_dt = bt.num2date(self.data.datetime[0])
        day_key = current_dt.date()
        changed = self.current_day != day_key
        self.current_day = day_key
        return changed

    def _cancel_pending(self):
        if self.pending_order is not None:
            self.cancel(self.pending_order)
        self.pending_order = None
        self.pending_side = None
        self.pending_price = None
        self.pending_stop = None
        self.pending_take = None
        self.pending_day = None

    def _set_position_risk(self, side, entry_price):
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(entry_price - float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None
            self.take_profit_price = round(entry_price + float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None
        else:
            self.stop_price = round(entry_price + float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None
            self.take_profit_price = round(entry_price - float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None

    def _place_stop_orders(self):
        if len(self.day_data) <= int(self.p.last_day):
            return
        day_high = float(self.day_data.high[-int(self.p.last_day)])
        day_low = float(self.day_data.low[-int(self.p.last_day)])
        unit = self._unit()
        stop_level = max(float(self.p.stop_level), 0.0) * unit
        buy_price = round(max(day_high + float(self.p.delta) * unit, float(self.data.close[0]) + stop_level), int(self.p.price_digits))
        sell_price = round(min(day_low - float(self.p.delta) * unit, float(self.data.close[0]) - stop_level), int(self.p.price_digits))
        self.pending_day = bt.num2date(self.data.datetime[0]).date()
        self.pending_side = 'both'
        self.pending_price = {'buy': buy_price, 'sell': sell_price}
        self.pending_stop = {
            'buy': round(buy_price - float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None,
            'sell': round(sell_price + float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None,
        }
        self.pending_take = {
            'buy': round(buy_price + float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None,
            'sell': round(sell_price - float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None,
        }
        self.signal_count += 1

    def _trigger_pending(self):
        if not self.pending_price or self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        size = self._effective_lot()
        if high >= self.pending_price['buy']:
            self._set_position_risk('buy', self.pending_price['buy'])
            self.order = self.buy(size=size)
            self.pending_side = 'buy'
            return True
        if low <= self.pending_price['sell']:
            self._set_position_risk('sell', self.pending_price['sell'])
            self.order = self.sell(size=size)
            self.pending_side = 'sell'
            return True
        return False

    def _apply_no_loss(self):
        if not self.position or self.p.no_loss == 0:
            return
        unit = self._unit()
        if self.position.size > 0:
            new_stop = round(float(self.data.close[0]) - float(self.p.no_loss) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop > self.stop_price and new_stop > self.position.price):
                self.stop_price = new_stop
        else:
            new_stop = round(float(self.data.close[0]) + float(self.p.no_loss) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop < self.stop_price and new_stop < self.position.price):
                self.stop_price = new_stop

    def _apply_trailing(self):
        if not self.position or self.p.trailing == 0:
            return
        unit = self._unit()
        if self.position.size > 0:
            new_stop = round(float(self.data.close[0]) - float(self.p.trailing) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop > self.stop_price and new_stop > self.position.price):
                self.stop_price = new_stop
        else:
            new_stop = round(float(self.data.close[0]) + float(self.p.trailing) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop < self.stop_price and new_stop < self.position.price):
                self.stop_price = new_stop

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        self._apply_trailing()
        self._apply_no_loss()
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Updates date boundaries, adjusts trailing SL and break-even targets for active positions,
        and triggers virtual stop orders if a breakout level is breached.
        """
        self.bar_num += 1
        self._new_day()
        if self.order is not None:
            return
        if self.position:
            self._cancel_pending()
            self._manage_position()
            return
        self._trigger_pending()
        if self.pending_price:
            return
        if self._time_match():
            self._place_stop_orders()

    def notify_order(self, order):
        """Tracks order status and updates protective targets on completed fills.

        Args:
            order (bt.Order): Backtrader order status notification object.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                self.pending_price = None
                self.pending_stop = None
                self.pending_take = None
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Logs trade closure, resets order bookkeeping, and records trade win/loss statistics.

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


def load_backtest_frames(config):
    """Prepares and loads base and daily resampled historical data frames based on configuration parameters.

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
    base = load_mt5_csv(resolve_data_path(data_cfg['file']), fromdate=fromdate, todate=todate, bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if base.empty:
        raise ValueError('Loaded data frame is empty')
    daily = resample_daily(base)
    print(f'Loaded bars: base={len(base)}, daily={len(daily)}')
    return {'base': base, 'daily': daily, 'fromdate': fromdate, 'todate': todate}


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
    cerebro.broker.setcommission(commission=bt_cfg['commission'], margin=bt_cfg['margin'], mult=bt_cfg['multiplier'], commtype=comm_type, stocklike=bt_cfg.get('stocklike', False))
    base_feed = Mt5PandasFeed(dataname=frame['base'][['open', 'high', 'low', 'close', 'volume', 'openinterest']], timeframe=bt.TimeFrame.Minutes, compression=15)
    day_feed = Mt5PandasFeed(dataname=frame['daily'][['open', 'high', 'low', 'close', 'volume', 'openinterest']], timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.adddata(base_feed, name='XAUUSD_M15')
    cerebro.adddata(day_feed, name='Daily')
    params = dict(config.get('params', {}))
    params.setdefault('min_lot', bt_cfg.get('min_lot', 0.01))
    params.setdefault('max_lot', bt_cfg.get('max_lot', 100.0))
    params.setdefault('lot_precision', bt_cfg.get('lot_precision', 2))
    params.setdefault('margin_per_lot', bt_cfg.get('margin', 250.0))
    params.setdefault('stop_level', bt_cfg.get('stop_level', 0))
    cerebro.addstrategy(BreakdownLevelDayStrategy, **params)
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
        'bars_base': len(frame['base']),
        'bars_daily': len(frame['daily']),
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


def test_68_0068_0734_breakdown_level_day() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0068_0734_breakdown_level_day.
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

    assert metrics.get('bar_num') == 6044, f"bar_num: expected=6044, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 37, f"buy_count: expected=37, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 16, f"sell_count: expected=16, got={metrics.get('sell_count')!r}"
    assert metrics.get('total_trades') == 53, f"total_trades: expected=53, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 53, f"trade_count: expected=53, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 23, f"won: expected=23, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 30, f"lost: expected=30, got={metrics.get('lost')!r}"
    _close(metrics.get('bars_base'), 6129.0, tol=6.129000e-03, key='bars_base')
    _close(metrics.get('bars_daily'), 68.0, tol=6.800000e-05, key='bars_daily')
    _close(metrics.get('signal_count'), 54.0, tol=5.400000e-05, key='signal_count')
    _close(metrics.get('completed_orders'), 106.0, tol=1.060000e-04, key='completed_orders')
    _close(metrics.get('rejected_orders'), 0.0, tol=1.000000e-06, key='rejected_orders')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1000336.6000000003, tol=1.000337e+00, key='final_value')
    _close(metrics.get('net_pnl'), 336.60000000032596, tol=3.366000e-04, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.033660000000024226, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 43.39622641509434, tol=4.339623e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.1313099789342158, tol=1.131310e-06, key='profit_factor')
    _close(metrics.get('sharpe_ratio'), 2.654684437901722, tol=2.654684e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 2.0105702594654398, tol=2.010570e-06, key='annual_return_pct')
    _close(metrics.get('max_drawdown'), 0.07679511068464219, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sqn'), 0.34040443754063876, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
