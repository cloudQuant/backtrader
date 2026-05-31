"""Center of Gravity state-metric strategy regression test.

Data Used:
    - Source file: ``{repo}/tests/datas/XAUUSD_M15.csv`` resolved through ``load_config``.
    - Instrument and time window: XAUUSD, M15 bars from
      ``2025-12-03 01:15:00`` to ``2026-03-10 09:00:00``.
    - Feed layout: one base 15-minute Backtrader feed with an indicator-calculated
      center and signal line derived from selected price fields and moving average
      smoothing.

Strategy Principle:
    The strategy builds a Center of Gravity-style indicator from a moving average
    combination and classifies state as bullish or bearish using center/signal
    ordering. Trade direction switches when the state transitions.

Strategy Logic:
    After enough bars are available, the strategy checks prior and current state
    for crossover-like transitions at a configurable ``signal_bar`` delay.
    It opens/reverses positions accordingly and tracks entry/exit through
    ``notify_trade`` counters for regression metrics.
"""
from __future__ import annotations
import math
from pathlib import Path
import io
import sys
import argparse
import datetime
import backtrader as bt
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Center of Gravity',
        'source_ea': 'ea/1296_Exp_CenterOfGravity',
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
        'period': 10,
        'smooth_period': 3,
        'ma_method': 'sma',
        'applied_price': 'close',
        'signal_bar': 1,
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



REPO_ROOT = Path(__file__).resolve().parents[3] / 'backtrader'
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))



def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load MT5-style TSV data and normalize it for Backtrader.

    Args:
        filepath: Raw MT5 CSV filepath.
        fromdate: Optional start datetime filter.
        todate: Optional end datetime filter.
        bar_shift_minutes: Optional bar timestamp shift in minutes.

    Returns:
        Parsed DataFrame indexed by datetime with OHLCV columns.
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


class Mt5PandasFeed(bt.feeds.PandasData):
    """Standard OHLCV pandas data feed definition for MT5-converted input."""

    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class CenterOfGravityIndicator(bt.Indicator):
    """Center of Gravity indicator composed of price selection and smoothed center line."""

    lines = ('center', 'signal', 'state',)
    params = dict(
        period=10,
        smooth_period=3,
        ma_method='sma',
        applied_price='close',
        point=0.01,
    )

    def __init__(self):
        """Initialize base MAs and derived center/signal/state lines."""
        ma_cls = bt.indicators.SMA if str(self.p.ma_method).lower() == 'sma' else bt.indicators.EMA
        price = self._price_line()
        sma = bt.indicators.SMA(price, period=self.p.period)
        lwma = bt.indicators.WeightedMovingAverage(price, period=self.p.period)
        self.lines.center = (sma * lwma) / self.p.point
        self.lines.signal = ma_cls(self.lines.center, period=self.p.smooth_period)
        self.addminperiod(self.p.period + self.p.smooth_period + 5)

    def _price_line(self):
        mode = str(self.p.applied_price).lower()
        if mode == 'open':
            return self.data.open
        if mode == 'high':
            return self.data.high
        if mode == 'low':
            return self.data.low
        if mode == 'median':
            return (self.data.high + self.data.low) / 2.0
        if mode == 'typical':
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if mode == 'weighted':
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        if mode == 'simpl':
            return (self.data.open + self.data.close) / 2.0
        if mode == 'quarter':
            return (self.data.high + self.data.low + self.data.open + self.data.close) / 4.0
        return self.data.close

    def next(self):
        """Compute the state classification for the current bar."""
        self.lines.state[0] = 2.0 if float(self.lines.center[0]) < float(self.lines.signal[0]) else 1.0


class CenterOfGravityStrategy(bt.Strategy):
    """Center-of-gravity crossover strategy executing one lot size per state transition."""

    params = dict(
        period=10,
        smooth_period=3,
        ma_method='sma',
        applied_price='close',
        signal_bar=1,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initialize indicator and trade bookkeeping counters."""
        self.cog = CenterOfGravityIndicator(
            self.data,
            period=self.p.period,
            smooth_period=self.p.smooth_period,
            ma_method=self.p.ma_method,
            applied_price=self.p.applied_price,
            point=self.p.point,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        """Print timestamped text messages for signal/trade actions."""
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _state_values(self):
        base = -int(self.p.signal_bar)
        return float(self.cog.state[base - 1]), float(self.cog.state[base])

    def next(self):
        """Generate buy/sell or reversal signals from state transitions."""
        self.bar_num += 1
        if len(self.data) < self.p.period + self.p.smooth_period + self.p.signal_bar + 5:
            return

        prev_state, curr_state = self._state_values()
        buy_signal = curr_state == 1.0 and prev_state == 2.0
        sell_signal = curr_state == 2.0 and prev_state == 1.0

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell state={curr_state:.0f} center={float(self.cog.center[-self.p.signal_bar]):.2f} signal={float(self.cog.signal[-self.p.signal_bar]):.2f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy state={curr_state:.0f} center={float(self.cog.center[-self.p.signal_bar]):.2f} signal={float(self.cog.signal[-self.p.signal_bar]):.2f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_signal:
                self.log(f'buy state={curr_state:.0f} center={float(self.cog.center[-self.p.signal_bar]):.2f} signal={float(self.cog.signal[-self.p.signal_bar]):.2f}')
                self.buy(size=self.p.lot)
                return
            if sell_signal:
                self.log(f'sell state={curr_state:.0f} center={float(self.cog.center[-self.p.signal_bar]):.2f} signal={float(self.cog.signal[-self.p.signal_bar]):.2f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        """Update buy/sell and win/loss metrics from trade lifecycle events."""
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
    """Resolve a dataset filename under the current test directory.

    Args:
        filename: Relative path from this test module directory.

    Returns:
        Absolute path to the resolved dataset.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Load and cut dataset into the configured test period.

    Args:
        config: Strategy configuration with data section.

    Returns:
        Backtest payload with parsed data and date boundaries.
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
    """Build and configure Cerebro with feed, strategy, commission, and analyzers.

    Args:
        config: Full strategy/backtest config.
        frame: Backtest frame returned by :func:`load_backtest_frame`.

    Returns:
        Prepared ``bt.Cerebro`` engine.
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
    cerebro.addstrategy(CenterOfGravityStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Collect strategy and analyzer statistics used for regression assertions.

    Args:
        strat: Finished strategy instance.
        cerebro: Completed Cerebro instance.
        frame: Backtest input frame.
        config: Execution config for initial cash context.

    Returns:
        Dictionary of backtest metrics.
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
    """Execute the strategy backtest and return ``results``, ``metrics`` and engine.

    Args:
        plot: If true, display a Cerebro plot.

    Returns:
        ``(results, metrics, cerebro)`` tuple.
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


def test_321_0320_1296_center_of_gravity() -> None:
    """Migrated regression test (runonce=True only)."""
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

    assert metrics.get('bar_num') == 6101, f"bar_num: expected=6101, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 382, f"buy_count: expected=382, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 381, f"sell_count: expected=381, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 285, f"win_count: expected=285, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 477, f"loss_count: expected=477, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 763, f"total_trades: expected=763, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 762, f"trade_count: expected=762, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 285, f"won: expected=285, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 477, f"lost: expected=477, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1001382.5000000014, tol=1.001383e+00, key='final_value')
    _close(metrics.get('net_pnl'), 1382.500000001397, tol=1.382500e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.13825000000013965, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 37.352555701179554, tol=3.735256e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.023500946394775, tol=1.023501e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.6444568115449223, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), 1.2324268421398075, tol=1.232427e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 8.523571819334604, tol=8.523572e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), 0.17718224506516525, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
