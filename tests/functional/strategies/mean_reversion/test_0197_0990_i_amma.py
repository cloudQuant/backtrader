"""Inlined regression test for tests/functional/strategies/mean_reversion/regression/0197_0990_i_amma.

Generated migration artifacts are consolidated here as a single deterministic
strategy test script.

Data Used:
    Uses ``{repo}/tests/datas/XAUUSD_M15.csv`` and constrains execution to
    2025-12-03 01:15:00 through 2026-03-10 09:00:00.
    Indicator timeframe is driven by configuration (H4 by default) while using
    XAUUSD price history.

Strategy Principle:
    Exp_i-AMMA tracks an adaptive moving-average envelope (i-AMMA) and trades
    reversals using crossover-like signals on shifted smoothed price values.
    Protective stop and take-profit rules gate each position lifecycle.

Strategy Logic:
    1. Load and clean raw bars, then prepare requested timeframe data.
    2. Compute i-AMMA line and derive open/close momentum signals.
    3. Execute entries/exits with pending direction, protective levels, and
       close/reverse behavior.
    4. Collect analyzer metrics and validate against migration baselines.
"""
from __future__ import annotations
import backtrader as bt
import math
from pathlib import Path
import datetime
import sys
import backtrader.analyzers as btanalyzers
from backtrader.utils.dateintern import num2date
from backtrader.strategy import Strategy
from backtrader.indicator import Indicator
import backtrader.feeds as btfeeds
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Exp_i-AMMA',
        'source_ea': 'ea/0990_Exp_i-AMMA',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'M15',
        'indicator_timeframe': 'H4',
        'base_timeframe': 'H4',
        'execution_compression_minutes': 240,
        'returns_compression_minutes': 15,
        'feature_cache_dir': 'features',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
    },
    'params': {
        'signal_bar': 1,
        'ma_period': 25,
        'price_shift': 0,
        'stop_loss_points': 1000,
        'take_profit_points': 2000,
        'lot': 0.1,
        'point': 0.01,
        'buy_pos_open': True,
        'sell_pos_open': True,
        'buy_pos_close': True,
        'sell_pos_close': True,
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


class Mt5PandasFeed(btfeeds.PandasData):
    """Feed mapping for normalized XAUUSD OHLCV bars."""
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class IAMMAStrategy(Strategy):
    """Adaptive moving-average strategy with reversal-based entry/exit logic."""
    params = dict(
        signal_bar=1,
        ma_period=25,
        price_shift=0,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
    )

    def __init__(self):
        """Create indicator stream and initialize tracking counters."""
        value = bt.indicators.SmoothedMovingAverage(self.data.close, period=max(1, int(self.p.ma_period)))
        if self.p.price_shift:
            value = value + float(self.p.price_shift) * float(self.p.point)
        self.indicator = type('IAMMALines', (), {})()
        self.indicator.value = value
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
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = max(int(self.p.signal_bar), 1) + 3

    def log(self, text):
        """Print timestamped strategy messages."""
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _get_signals(self):
        shift = max(int(self.p.signal_bar), 1)
        value_0 = float(self.indicator.value[-shift])
        value_1 = float(self.indicator.value[-(shift + 1)])
        value_2 = float(self.indicator.value[-(shift + 2)])
        buy_open = self.p.buy_pos_open and value_1 < value_2 and value_0 > value_1
        sell_open = self.p.sell_pos_open and value_1 > value_2 and value_0 < value_1
        buy_close = self.p.buy_pos_close and sell_open
        sell_close = self.p.sell_pos_close and buy_open
        return buy_open, sell_open, buy_close, sell_close

    def _open_long(self):
        self.pending_entry_direction = 1
        self.buy(size=self.p.lot)

    def _open_short(self):
        self.pending_entry_direction = -1
        self.sell(size=self.p.lot)

    def _close_long(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _close_short(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._close_long(f'close long stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_long(f'close long target={self.target_price:.2f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_short(f'close short stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_short(f'close short target={self.target_price:.2f}')
                return True
        return False

    def next(self):
        """Process signals, manage entries and exits per bar."""
        self.bar_num += 1
        if len(self.data) < self.warmup:
            return
        if self._manage_protective_levels():
            return
        buy_open, sell_open, buy_close, sell_close = self._get_signals()
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position:
            if self.position.size > 0:
                if buy_close:
                    self._close_long('close long on i-AMMA bearish reversal')
                    if sell_open:
                        self._open_short()
                    return
            else:
                if sell_close:
                    self._close_short('close short on i-AMMA bullish reversal')
                    if buy_open:
                        self._open_long()
                    return
        else:
            if buy_open:
                self.log('buy on i-AMMA bullish reversal')
                self._open_long()
                return
            if sell_open:
                self.log('sell on i-AMMA bearish reversal')
                self._open_short()
                return

    def notify_order(self, order):
        """Update order counters and stop/target levels on completion."""
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            self.log(f'order {order.getstatusname()}')
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy():
            self.buy_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return
        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return
        if not self.position:
            self._reset_levels()

    def notify_trade(self, trade):
        """Record trade outcome and emit closure details."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')


BASE_DIR = Path(__file__).resolve().parent

WORKSPACE_ROOT = BASE_DIR.parents[2]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if BACKTRADER_REPO.exists() and str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))


MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


def resolve_data_path(filename):
    """Resolve a relative fixture path and ensure it exists.

    Args:
        filename: Relative path to test data file.

    Returns:
        Absolute path object.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Load and validate the raw backtest DataFrame.

    Args:
        config: Migration config containing data source and window settings.

    Returns:
        Dictionary with backtest data and boundary dates.
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


def _timeframe_spec(label):
    mapping = {
        'M15': (bt.TimeFrame.Minutes, 15),
        'H1': (bt.TimeFrame.Minutes, 60),
        'H4': (bt.TimeFrame.Minutes, 240),
        'H8': (bt.TimeFrame.Minutes, 480),
        'H12': (bt.TimeFrame.Minutes, 720),
        'D1': (bt.TimeFrame.Days, 1),
    }
    if label not in mapping:
        raise ValueError(f'Unsupported timeframe: {label}')
    return mapping[label]


def build_cerebro(config, frame):
    """Configure cerebro instance, feed, strategy, and analyzers.

    Args:
        config: Strategy and backtest configuration.
        frame: Loaded historical frame and metadata.

    Returns:
        Ready-to-run cerebro engine.
    """
    bt_cfg = config['backtest']
    data_cfg = config['data']
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
    target_tf = data_cfg.get('indicator_timeframe', data_cfg['timeframe'])
    feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    if target_tf == data_cfg['timeframe']:
        cerebro.adddata(feed, name=f"{data_cfg['symbol']}_{target_tf}")
    else:
        timeframe, compression = _timeframe_spec(target_tf)
        cerebro.resampledata(feed, timeframe=timeframe, compression=compression, name=f"{data_cfg['symbol']}_{target_tf}")
    cerebro.addstrategy(IAMMAStrategy, **config.get('params', {}))
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(btanalyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(btanalyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Aggregate strategy, broker, and analyzer values for assertions.

    Args:
        strat: Strategy object after execution.
        cerebro: Completed cerebro engine.
        frame: Input frame metadata.
        config: Migration config.

    Returns:
        Metric dictionary used by regression assertions.
    """
    sharpe = strat.analyzers.sharpe.get_analysis()
    returns = strat.analyzers.returns.get_analysis()
    drawdown = strat.analyzers.drawdown.get_analysis()
    trades = strat.analyzers.trades.get_analysis()
    sqn = strat.analyzers.sqn.get_analysis()
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    total_trades = trades.get('total', {}).get('closed', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    return {
        'fromdate': frame['fromdate'],
        'todate': frame['todate'],
        'bars': len(frame['data']),
        'bar_num': strat.bar_num,
        'buy_signal_count': strat.buy_signal_count,
        'sell_signal_count': strat.sell_signal_count,
        'completed_order_count': strat.completed_order_count,
        'rejected_order_count': strat.rejected_order_count,
        'trade_count': strat.trade_count,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (returns.get('rtot') or 0) * 100,
        'total_trades': total_trades,
        'win_count': won,
        'loss_count': lost,
        'win_rate': (won / total_trades * 100) if total_trades else 0,
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sqn': sqn.get('sqn'),
    }


def _close(actual, expected, *, tol, key):
    """Assert ``actual`` is finite and within ``tol`` of ``expected``."""
    assert actual is not None, f"{key}: expected={expected}, got=None"
    a = float(actual)
    assert math.isfinite(a), f"{key}: expected={expected}, got non-finite {actual}"
    assert abs(a - float(expected)) <= tol, (
        f"{key}: expected={expected}, got={a} (tol={tol})"
    )


def _resolve_loader():
    """Locate the data-loading helper (varies by strategy)."""
    for name in ("load_inputs", "load_data", "load_backtest_frame", "prepare_inputs", "prepare_data"):
        fn = globals().get(name)
        if callable(fn):
            return fn
    raise RuntimeError("No inputs loader found in inlined module")


def _build_cerebro_compat(inputs, config):
    """Call build_cerebro with whichever signature the original used."""
    import inspect
    sig = inspect.signature(build_cerebro)
    params = list(sig.parameters.keys())
    if params and params[0].lower() in ("config", "cfg", "configuration"):
        return build_cerebro(config, inputs)
    try:
        return build_cerebro(inputs, config)
    except TypeError:
        return build_cerebro(config, inputs)


def _extract_metrics_compat(strat, cerebro, inputs, config):
    """Call extract_metrics with whichever signature the original used."""
    for args in (
        (strat, cerebro, inputs, config),
        (strat, cerebro, config, inputs),
        (strat, cerebro, inputs),
        (strat, cerebro),
    ):
        try:
            return extract_metrics(*args)
        except TypeError:
            continue
    raise RuntimeError("extract_metrics failed for all argument orderings")


def test_198_0197_0990_i_amma() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/mean_reversion/0197_0990_i_amma.
    """
    config = _bt_load_config(_CONFIG, repo=_REPO)
    inputs = _resolve_loader()(config)
    cerebro = _build_cerebro_compat(inputs, config)
    results = cerebro.run(runonce=True)
    metrics = _extract_metrics_compat(results[0], cerebro, inputs, config)

    assert metrics.get('bar_num') == 376, f"bar_num: expected=376, got={metrics.get('bar_num')!r}"
    assert metrics.get('win_count') == 7, f"win_count: expected=7, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 12, f"loss_count: expected=12, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 19, f"total_trades: expected=19, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 19, f"trade_count: expected=19, got={metrics.get('trade_count')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('buy_signal_count'), 11.0, tol=1.100000e-05, key='buy_signal_count')
    _close(metrics.get('sell_signal_count'), 9.0, tol=9.000000e-06, key='sell_signal_count')
    _close(metrics.get('completed_order_count'), 39.0, tol=3.900000e-05, key='completed_order_count')
    _close(metrics.get('rejected_order_count'), 0.0, tol=1.000000e-06, key='rejected_order_count')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1001579.1000000001, tol=1.001579e+00, key='final_value')
    _close(metrics.get('net_pnl'), 1579.1000000000931, tol=1.579100e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.15778545325677462, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 36.84210526315789, tol=3.684211e-05, key='win_rate')
    _close(metrics.get('sharpe_ratio'), 22.82890758853396, tol=2.282891e-05, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 318.46774661261514, tol=3.184677e-04, key='annual_return_pct')
    _close(metrics.get('max_drawdown'), 0.0814066022700896, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sqn'), 0.7824532951524911, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
