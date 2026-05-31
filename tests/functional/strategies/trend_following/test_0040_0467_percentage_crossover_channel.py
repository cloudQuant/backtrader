"""Percentage Crossover Channel strategy regression test.

Data Used:
    Symbol XAUUSD from ``tests/datas/XAUUSD_M15.csv`` with a bar shift of 15
    minutes applied to match close timestamps. The test window is
    ``2025-12-03 01:15:00`` to ``2026-03-10 09:00:00`` on M15 bars.

Strategy Principle:
    The indicator keeps a running percentage channel by adapting a middle line and
    upper/lower envelopes at ``percent`` distance. Signals are produced when price
    crosses the channel boundaries or the middle line and are optionally
    direction-reversed by strategy parameters.

Strategy Logic:
    The module loads and slices MT5 CSV data, builds a Backtrader feed and
    analyzers, then runs ``PercentageCrossoverChannelStrategy``. The strategy
    evaluates crossover conditions in ``next``, manages risk levels on filled
    orders, and counts order/trade events for regression metrics.
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
        'name': 'Percentage_Crossover_Channel_EA',
        'source_ea': 'ea/0467_Percentage_Crossover_Channel_EA/percentage_crossover_channel_ea.mq5',
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
        'percent': 50.0,
        'cross_middle': False,
        'reverse_trade': False,
        'volume': 0.1,
        'stop_loss_points': 0,
        'take_profit_points': 0,
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





def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load and normalize MT5 tab-separated price data into a Backtrader DataFrame.

    Args:
        filepath: Input MT5 export path.
        fromdate: Optional start datetime.
        todate: Optional end datetime.
        bar_shift_minutes: Minutes to shift timestamps to mark bar close.

    Returns:
        Pandas DataFrame indexed by datetime with OHLCV columns.
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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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
    """Pandas feed mapping MT5 OHLCV columns to Backtrader's data lines."""

    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class PercentageCrossoverChannel(bt.Indicator):
    """Percent-based dynamic channel indicator.

    The middle line is gradually adjusted toward current price with separate
    upper/lower bands derived from the configured percentage distance.
    """
    lines = ('upper', 'middle', 'lower')
    params = dict(percent=50.0)

    def __init__(self):
        """Initialize percent offsets and minimum warm-up settings."""
        self.addminperiod(2)
        percent = max(self.p.percent, 0.001) / 100.0
        self.plus_value = 1 + percent / 100.0
        self.minus_value = 1 - percent / 100.0

    def next(self):
        """Update middle, upper, and lower channel lines for the current bar."""
        price = float(self.data.close[0])
        if len(self.data) == 1 or self.lines.middle[-1] != self.lines.middle[-1]:
            middle = price
        else:
            prev_middle = float(self.lines.middle[-1])
            if price * self.minus_value > prev_middle:
                middle = price * self.minus_value
            elif price * self.plus_value < prev_middle:
                middle = price * self.plus_value
            else:
                middle = prev_middle
        self.lines.middle[0] = middle
        self.lines.upper[0] = middle * self.plus_value
        self.lines.lower[0] = middle * self.minus_value


class PercentageCrossoverChannelStrategy(bt.Strategy):
    """Channel-cross strategy with optional reverse and midpoint switching."""
    params = dict(
        percent=50.0,
        cross_middle=False,
        reverse_trade=False,
        volume=0.1,
        stop_loss_points=0,
        take_profit_points=0,
        point=0.01,
    )

    def __init__(self):
        """Create channel indicator and initialize counters, orders, and risk levels."""
        self.channel = PercentageCrossoverChannel(self.data, percent=self.p.percent)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_price = None
        self.take_profit_price = None

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _set_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _check_exit_levels(self):
        if not self.position:
            self._clear_risk()
            return False
        if self.position.size > 0:
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.high[0]) >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and float(self.data.low[0]) <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        """Apply exit checks first, then open/flip positions on channel crossings."""
        self.bar_num += 1
        if len(self.data) < 4:
            return
        if self.order:
            return
        if self._check_exit_levels():
            return

        line_up1 = float(self.channel.upper[-1])
        line_up2 = float(self.channel.upper[-2])
        line_md1 = float(self.channel.middle[-1])
        line_md2 = float(self.channel.middle[-2])
        line_dn1 = float(self.channel.lower[-1])
        line_dn2 = float(self.channel.lower[-2])

        open_long = False
        open_short = False
        if self.p.cross_middle:
            if float(self.data.close[-2]) > line_md2 and float(self.data.close[-1]) < line_md1:
                open_long = not self.p.reverse_trade
                open_short = self.p.reverse_trade
            if float(self.data.close[-2]) < line_md2 and float(self.data.close[-1]) > line_md1:
                open_short = not self.p.reverse_trade
                open_long = self.p.reverse_trade
        else:
            if float(self.data.low[-2]) > line_dn2 and float(self.data.low[-1]) <= line_dn1:
                open_long = not self.p.reverse_trade
                open_short = self.p.reverse_trade
            if float(self.data.high[-2]) < line_up2 and float(self.data.high[-1]) >= line_up1:
                open_short = not self.p.reverse_trade
                open_long = self.p.reverse_trade

        if open_long:
            if self.position.size < 0:
                self.order = self.close()
                return
            if self.position.size == 0:
                self.order = self.buy(size=self.p.volume)
                return
        if open_short:
            if self.position.size > 0:
                self.order = self.close()
                return
            if self.position.size == 0:
                self.order = self.sell(size=self.p.volume)

    def notify_order(self, order):
        """Track completed buys/sells and clear pending order bookkeeping."""
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
                if self.position.size > 0:
                    self._set_risk(order.executed.price, 1)
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
                if self.position.size < 0:
                    self._set_risk(order.executed.price, -1)
            elif self.position.size == 0:
                self._clear_risk()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        """Update trade result counters and risk state when a trade closes."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_risk()



BASE_DIR = Path(__file__).resolve().parent

REPO_BACKTRADER_DIR = BASE_DIR.parents[2] / 'backtrader'
if str(REPO_BACKTRADER_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_BACKTRADER_DIR))



MINUTES_PER_TRADING_YEAR = 24 * 60 * 252



def resolve_data_path(filename):
    """Resolve a data filename relative to this test module.

    Args:
        filename: Relative path to the target file.

    Returns:
        Absolute path to the resolved file.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Load dataset from config and trim to the configured test date range.

    Args:
        config: Strategy/backtest configuration.

    Returns:
        Dict with ``data``, ``fromdate`` and ``todate`` fields.
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
    """Build and return a configured ``bt.Cerebro`` instance.

    The method sets broker settings, mounts the MT5 feed, registers the strategy,
    and installs standard analyzers used by regression metrics.

    Args:
        config: Strategy and broker settings.
        frame: Loaded backtest payload including data frame.

    Returns:
        Ready-to-run ``bt.Cerebro`` object.
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
    cerebro.addstrategy(PercentageCrossoverChannelStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Collect strategy counters and analyzer outputs for regression assertions.

    Args:
        strat: Completed strategy instance.
        cerebro: Completed Cerebro engine after running.
        frame: Backtest frame used for this run.
        config: Execution config for initial cash context.

    Returns:
        Dictionary with trading and performance metrics.
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
    gross_win = trades.get('won', {}).get('pnl', {}).get('total', 0) or 0
    gross_loss = abs(trades.get('lost', {}).get('pnl', {}).get('total', 0) or 0)
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
        'profit_factor': (gross_win / gross_loss) if gross_loss else None,
        'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
        'sharpe_ratio': sharpe.get('sharperatio'),
        'annual_return_pct': (returns.get('rnorm') or 0) * 100,
        'sqn': sqn.get('sqn'),
    }



def run(plot=False):
    """Run backtest and return results, metrics, and engine for inspection.

    Args:
        plot: Render chart when set to True.

    Returns:
        Tuple ``(results, metrics, cerebro)``.
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


def test_40_0040_0467_percentage_crossover_channel() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0040_0467_percentage_crossover_channel.
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

    assert metrics.get('bar_num') == 6128, f"bar_num: expected=6128, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 123, f"buy_count: expected=123, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 124, f"sell_count: expected=124, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 70, f"win_count: expected=70, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 53, f"loss_count: expected=53, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 124, f"total_trades: expected=124, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 123, f"trade_count: expected=123, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 70, f"won: expected=70, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 53, f"lost: expected=53, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 994633.9999999955, tol=9.946340e-01, key='final_value')
    _close(metrics.get('net_pnl'), -5366.00000000454, tol=5.366000e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), -0.5366000000004534, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 56.451612903225815, tol=5.645161e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 0.8414800261951549, tol=1.000000e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.8830266419466639, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), -5.4800937779200085, tol=5.480094e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), -27.280490868161312, tol=2.728049e-05, key='annual_return_pct')
    _close(metrics.get('sqn'), -0.7199618615489642, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
