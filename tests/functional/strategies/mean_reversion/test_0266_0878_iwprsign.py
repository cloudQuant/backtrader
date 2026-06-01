"""Inlined regression test for tests/functional/strategies/mean_reversion/regression/0266_0878_iwprsign.

This module is inlined from migration artifacts and contains the full regression
scenario in one executable test file.

Data Used:
    Uses ``{repo}/tests/datas/XAUUSD_M15.csv`` with period
    2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    A H1-derived indicator feed is built from the same base data using a
    configurable resample interval.

Strategy Principle:
    Exp_iWPRSign combines WPR trigger lines with ATR-aware offset levels to
    generate buy/sell points and optional close conditions.

Strategy Logic:
    1. Load base bars and build a separate signal frame by resampling.
    2. Run ``IWPRSignIndicator`` for buy/sell signal levels.
    3. On each signal bar, open or close positions accordingly.
    4. Aggregate analyzers and trade counters for deterministic regression checks.
"""
from __future__ import annotations
import backtrader as bt
import math
from pathlib import Path
import sys
import datetime
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Exp_iWPRSign',
        'source_ea': 'ea/0878_Exp_iWPRSign',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'M15',
        'indicator_timeframe': 'H1',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
    },
    'params': {
        'indicator_minutes': 60,
        'atr_period': 14,
        'wpr_period': 14,
        'up_level': -30,
        'dn_level': -70,
        'signal_bar': 1,
        'stop_loss_points': 1000,
        'take_profit_points': 2000,
        'fixed_lot': 0.1,
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


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))


class Mt5PandasFeed(bt.feeds.PandasData):
    """Base OHLCV feed for iWPRSign backtest execution."""
    params = (('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5))


class ExpIWPRSignStrategy(bt.Strategy):
    """Execution strategy for iWPRSign-based trigger entries and exits."""
    params = dict(
        atr_period=14,
        wpr_period=14,
        up_level=-30,
        dn_level=-70,
        signal_bar=1,
        stop_loss_points=1000,
        take_profit_points=2000,
        fixed_lot=0.1,
        point=0.01,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        indicator_minutes=60,
    )

    def __init__(self):
        """Initialize feed bindings, indicator, and runtime counters."""
        self.base = self.datas[0]
        self.signal_data = self.datas[1]
        self.indicator = bt.indicators.IWPRSignIndicator(self.signal_data, atr_period=self.p.atr_period, wpr_period=self.p.wpr_period, up_level=self.p.up_level, dn_level=self.p.dn_level)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._last_signal_len = 0

    def log(self, text):
        """Print timestamped strategy logs."""
        print(f'{bt.num2date(self.base.datetime[0]).isoformat()}, {text}')

    def _check_exit_levels(self):
        if not self.position:
            return False
        cp = float(self.base.close[0])
        pv = float(self.p.point)
        sd = self.p.stop_loss_points * pv if self.p.stop_loss_points > 0 else None
        td = self.p.take_profit_points * pv if self.p.take_profit_points > 0 else None
        ep = float(self.position.price)
        if self.position.size > 0:
            if sd and cp <= ep - sd:
                self.log(f'close long SL {cp:.2f}')
                self.close()
                return True
            if td and cp >= ep + td:
                self.log(f'close long TP {cp:.2f}')
                self.close()
                return True
        else:
            if sd and cp >= ep + sd:
                self.log(f'close short SL {cp:.2f}')
                self.close()
                return True
            if td and cp <= ep - td:
                self.log(f'close short TP {cp:.2f}')
                self.close()
                return True
        return False

    def _line_value(self, line, offset):
        val = float(line[-offset]) if offset else float(line[0])
        return None if math.isnan(val) else val

    def next(self):
        """Run per-bar signal evaluation and order actions."""
        self.bar_num += 1
        if len(self.base) < 2:
            return
        if self._check_exit_levels():
            return
        signal_bar = max(int(self.p.signal_bar) - 1, 0)
        min_needed = max(int(self.p.atr_period), int(self.p.wpr_period)) + signal_bar + 4
        if len(self.signal_data) < min_needed:
            return
        csl = len(self.signal_data)
        if csl == self._last_signal_len:
            return
        self._last_signal_len = csl

        up_signal = self._line_value(self.indicator.buy, signal_bar)
        dn_signal = self._line_value(self.indicator.sell, signal_bar)
        close_long = False
        close_short = False
        for bar in range(signal_bar + 1, len(self.signal_data)):
            if self.p.sell_pos_close and self._line_value(self.indicator.buy, bar) is not None:
                close_short = True
                break
        for bar in range(signal_bar + 1, len(self.signal_data)):
            if self.p.buy_pos_close and self._line_value(self.indicator.sell, bar) is not None:
                close_long = True
                break
        if up_signal is not None and self.p.sell_pos_close:
            close_short = True
        if dn_signal is not None and self.p.buy_pos_close:
            close_long = True
        buy_open = up_signal is not None and self.p.buy_pos_open
        sell_open = dn_signal is not None and self.p.sell_pos_open
        cp = float(self.base.close[0])
        sz = float(self.p.fixed_lot)
        if sz <= 0:
            return
        if close_short and self.position.size < 0:
            self.log(f'close short signal {cp:.2f}')
            self.close()
        if close_long and self.position.size > 0:
            self.log(f'close long signal {cp:.2f}')
            self.close()
        if buy_open:
            self.signal_count += 1
            self.log(f'buy signal {cp:.2f}')
            if self.position.size <= 0:
                self.buy(size=sz)
        if sell_open:
            self.signal_count += 1
            self.log(f'sell signal {cp:.2f}')
            if self.position.size >= 0:
                self.sell(size=sz)

    def notify_trade(self, trade):
        """Track trade lifecycle statistics when positions are opened or closed."""
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
    """Resolve fixture path and verify it exists.

    Args:
        filename: Relative fixture path.

    Returns:
        Absolute ``Path`` for the fixture.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Load primary backtest frame for the given date window.

    Args:
        config: Migration configuration with data constraints.

    Returns:
        Dictionary containing DataFrame and from/to bounds.
    """
    data_cfg = config['data']
    fromdate = datetime.datetime.fromisoformat(data_cfg['fromdate'])
    todate = datetime.datetime.fromisoformat(data_cfg['todate'])
    df = load_mt5_csv(resolve_data_path(data_cfg['file']), fromdate=fromdate, todate=todate, bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if df.empty:
        raise ValueError('Loaded empty dataframe for backtest window')
    print(f'Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}')
    return {'data': df, 'fromdate': fromdate, 'todate': todate}


def build_signal_frame(df, indicator_minutes):
    """Resample base frame into the configured signal interval.

    Args:
        df: Base OHLCV frame.
        indicator_minutes: Minute interval for indicator feed.

    Returns:
        Resampled signal DataFrame.
    """
    rule = f'{int(indicator_minutes)}min'
    signal_df = df.resample(rule, label='right', closed='right').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'openinterest': 'last'})
    signal_df = signal_df.dropna(subset=['open', 'high', 'low', 'close'])
    signal_df['openinterest'] = signal_df['openinterest'].fillna(0)
    return signal_df


def build_cerebro(config, frame):
    """Build configured Backtrader engine and load data, strategy, and analyzers.

    Args:
        config: Full strategy/backtest configuration.
        frame: Loaded historical frame data.

    Returns:
        Prepared `bt.Cerebro` object.
    """
    backtest_cfg = config['backtest']
    params = config.get('params', {})
    indicator_minutes = params.get('indicator_minutes', 60)
    signal_df = build_signal_frame(frame['data'], indicator_minutes)
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(backtest_cfg['initial_cash'])
    commtype = bt.CommInfoBase.COMM_FIXED if backtest_cfg.get('commission_type', 'fixed') == 'fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(commission=backtest_cfg['commission'], margin=backtest_cfg['margin'], mult=backtest_cfg['multiplier'], commtype=commtype, stocklike=backtest_cfg.get('stocklike', False))
    data_cfg = config['data']
    cerebro.adddata(Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15), name=f"{data_cfg['symbol']}_{data_cfg['timeframe']}")
    cerebro.adddata(Mt5PandasFeed(dataname=signal_df, timeframe=bt.TimeFrame.Minutes, compression=indicator_minutes), name=f"{data_cfg['symbol']}_{data_cfg['indicator_timeframe']}")
    strategy_params = dict(params)
    strategy_params.pop('indicator_minutes', None)
    cerebro.addstrategy(ExpIWPRSignStrategy, **strategy_params)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0.0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strategy, cerebro, frame, config):
    """Collect analyzer outputs and strategy counters for assertions.

    Args:
        strategy: Completed strategy object.
        cerebro: Engine instance after execution.
        frame: Input frame metadata.
        config: Migration configuration.

    Returns:
        Structured metrics dictionary.
    """
    sharpe = strategy.analyzers.sharpe.get_analysis()
    returns = strategy.analyzers.returns.get_analysis()
    drawdown = strategy.analyzers.drawdown.get_analysis()
    trades = strategy.analyzers.trades.get_analysis()
    sqn = strategy.analyzers.sqn.get_analysis()
    initial_cash = config['backtest']['initial_cash']
    final_value = cerebro.broker.getvalue()
    total_trades = trades.get('total', {}).get('total', 0)
    won = trades.get('won', {}).get('total', 0)
    lost = trades.get('lost', {}).get('total', 0)
    gross_won = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_lost = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
    return {'fromdate': frame['fromdate'], 'todate': frame['todate'], 'bars': len(frame['data']), 'bar_num': strategy.bar_num, 'signal_count': strategy.signal_count, 'buy_count': strategy.buy_count, 'sell_count': strategy.sell_count, 'trade_count': strategy.trade_count, 'win_count': strategy.win_count, 'loss_count': strategy.loss_count, 'initial_cash': initial_cash, 'final_value': final_value, 'net_pnl': final_value - initial_cash, 'total_return_pct': (final_value / initial_cash - 1.0) * 100.0, 'total_trades': total_trades, 'won': won, 'lost': lost, 'win_rate': (won / total_trades * 100.0) if total_trades else 0.0, 'profit_factor': (gross_won / gross_lost) if gross_lost else None, 'max_drawdown': drawdown.get('max', {}).get('drawdown', 0), 'sharpe_ratio': sharpe.get('sharperatio'), 'annual_return_pct': (returns.get('rnorm') or 0) * 100.0, 'sqn': sqn.get('sqn')}


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


def test_267_0266_0878_iwprsign() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/mean_reversion/0266_0878_iwprsign.
    """
    config = _bt_load_config(_CONFIG, repo=_REPO)
    inputs = _resolve_loader()(config)
    cerebro = _build_cerebro_compat(inputs, config)
    results = cerebro.run(runonce=True)
    metrics = _extract_metrics_compat(results[0], cerebro, inputs, config)

    assert metrics.get('bar_num') == 6073, f"bar_num: expected=6073, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 97, f"buy_count: expected=97, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 115, f"sell_count: expected=115, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 93, f"win_count: expected=93, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 119, f"loss_count: expected=119, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 212, f"total_trades: expected=212, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 212, f"trade_count: expected=212, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 93, f"won: expected=93, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 119, f"lost: expected=119, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('signal_count'), 213.0, tol=2.130000e-04, key='signal_count')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 997852.0000000003, tol=9.978520e-01, key='final_value')
    _close(metrics.get('net_pnl'), -2147.9999999996508, tol=2.148000e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), -0.21479999999997057, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 43.86792452830189, tol=4.386792e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 0.8519825245662186, tol=1.000000e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.3801808133150604, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), -6.001275512417382, tol=6.001276e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), -11.941452786534951, tol=1.194145e-05, key='annual_return_pct')
    _close(metrics.get('sqn'), -0.7874148138729968, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
