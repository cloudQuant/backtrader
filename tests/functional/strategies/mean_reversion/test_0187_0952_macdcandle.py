"""Inlined regression test for tests/functional/strategies/mean_reversion/regression/0187_0952_macdcandle.

This module is derived from generated migration artifacts and remains a self-
contained backtest test for deterministic regression verification.

Data Used:
    Uses ``{repo}/tests/datas/XAUUSD_M15.csv`` as the base source.
    The backtest window spans 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    Data is processed at execution timeframe M15 and indicator timeframe H4 to
    produce a secondary signal feed.

Strategy Principle:
    The Exp_MACDCandle strategy builds MACD-like candle proxies on OHLC paths and
    derives a three-state color signal (bullish/neutral/bearish). Position
    entries/exits are driven by color flips and configurable close flags across a
    multi-timeframe setup.

Strategy Logic:
    1. Load and normalize market data, then resample when required for H4
       indicator evaluation.
    2. Compute MACDCandle values for open/high/low/close and expose direction
       color transitions.
    3. On each signal bar, open or reverse positions with risk guardrails.
    4. Track lifecycle counters and assert full regression metrics from analyzers.
"""
from __future__ import annotations
import backtrader as bt
import math
from pathlib import Path
import datetime
import sys
import backtrader.analyzers as btanalyzers
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, augment_mt5_csv_columns as _augment_mt5_csv_columns, load_mt5_csv as _load_mt5_csv


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    """Load MT5 data and preserve fixture-specific raw columns."""
    frame = _load_mt5_csv(
        filepath,
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=bar_shift_minutes,
    )
    return _augment_mt5_csv_columns(
        frame,
        filepath,
        ("spread",),
        bar_shift_minutes=bar_shift_minutes,
    )

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Exp_MACDCandle',
        'source_ea': 'ea/0952_Exp_MACDCandle',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'M15',
        'base_timeframe': 'M15',
        'indicator_timeframe': 'H4',
        'execution_compression_minutes': 15,
        'returns_compression_minutes': 15,
        'feature_cache_dir': 'features',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
    },
    'params': {
        'signal_bar': 1,
        'fast_ema_period': 12,
        'slow_ema_period': 26,
        'signal_period': 9,
        'mode': 'signal',
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


class Mt5PandasFeed(bt.feeds.PandasData):
    """Backtest feed with a dedicated spread line for base XAUUSD bars."""
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class MacdCandleStrategy(bt.Strategy):
    """MACDCandle strategy with directional color-flip entries and exits."""
    params = dict(
        fixed_lot=0.1,
        risk_percent=0.0,
        point=0.01,
        stop_loss_points=1000,
        take_profit_points=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        fast_ema_period=12,
        slow_ema_period=26,
        signal_period=9,
        mode='signal',
        signal_bar=1,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=100.0,
        contract_multiplier=100.0,
    )

    def __init__(self):
        """Instantiate indicator stack and initialize trade/order tracking fields."""
        self.data0_feed = self.datas[0]
        self.signal_feed = self.datas[-1]
        self.indicator = bt.indicators.MacdCandleIndicator(
            self.signal_feed,
            fast_ema_period=self.p.fast_ema_period,
            slow_ema_period=self.p.slow_ema_period,
            signal_period=self.p.signal_period,
            mode=self.p.mode,
        )
        self.bar_num = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.pending_entry_direction = 0
        self.pending_reverse_direction = 0
        self.entry_side = None
        self.last_signal_dt = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.warmup = max(int(self.p.fast_ema_period), int(self.p.slow_ema_period)) + int(self.p.signal_period) + int(self.p.signal_bar) + 8

    def log(self, text):
        """Log strategy events with the execution feed timestamp."""
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_size(self, size):
        bounded = min(max(size, self.p.lot_min), self.p.lot_max)
        steps = round(bounded / self.p.lot_step)
        return min(max(steps * self.p.lot_step, self.p.lot_min), self.p.lot_max)

    def _position_size(self):
        if self.p.fixed_lot > 0:
            return self._round_size(self.p.fixed_lot)
        stop_distance = self.p.stop_loss_points * self.p.point
        if stop_distance <= 0 or self.p.risk_percent <= 0:
            return self._round_size(self.p.lot_min)
        risk_money = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        raw_size = risk_money / (stop_distance * self.p.contract_multiplier)
        return self._round_size(raw_size)

    def _color_at(self, shift):
        idx = max(int(shift) - 1, 0)
        if len(self.indicator.color.array) <= idx:
            return None
        return int(float(self.indicator.color[-idx] if idx else self.indicator.color[0]))

    def _set_entry_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _clear_risk(self):
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def _submit_entry(self, direction, reason):
        size = self._position_size()
        if size <= 0:
            return False
        self.pending_entry_direction = direction
        if direction > 0:
            self.entry_side = 'long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} reason={reason}')
        else:
            self.entry_side = 'short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} reason={reason}')
        return True

    def _check_exit_levels(self):
        if not self.position:
            return False
        low = float(self.data0_feed.low[0])
        high = float(self.data0_feed.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long protective stop={self.stop_price:.5f}')
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_reverse_direction = 0
                self.order = self.close()
                self.log(f'CLOSE long take_profit={self.take_profit_price:.5f}')
                return True
            return False
        if self.stop_price is not None and high >= self.stop_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short protective stop={self.stop_price:.5f}')
            return True
        if self.take_profit_price is not None and low <= self.take_profit_price:
            self.pending_reverse_direction = 0
            self.order = self.close()
            self.log(f'CLOSE short take_profit={self.take_profit_price:.5f}')
            return True
        return False

    def next(self):
        """Evaluate signal colors each bar and manage entry/exit flows."""
        self.bar_num += 1
        signal_dt = bt.num2date(self.signal_feed.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        if len(self.signal_feed) < self.warmup:
            return
        if self.order is not None:
            return
        if self.position and self._check_exit_levels():
            return
        current_color = self._color_at(int(self.p.signal_bar))
        previous_color = self._color_at(int(self.p.signal_bar) + 1)
        if current_color is None or previous_color is None:
            return
        buy_open = self.p.buy_pos_open and current_color == 2 and previous_color < 2
        sell_open = self.p.sell_pos_open and current_color == 0 and previous_color > 0
        sell_close = self.p.sell_pos_close and current_color == 2
        buy_close = self.p.buy_pos_close and current_color == 0
        if buy_open:
            self.buy_signal_count += 1
        if sell_open:
            self.sell_signal_count += 1
        if self.position.size > 0:
            if buy_close:
                self.pending_reverse_direction = -1 if sell_open else 0
                self.order = self.close()
                self.log('CLOSE long MACDCandle signal')
            return
        if self.position.size < 0:
            if sell_close:
                self.pending_reverse_direction = 1 if buy_open else 0
                self.order = self.close()
                self.log('CLOSE short MACDCandle signal')
            return
        if buy_open:
            self._submit_entry(1, 'MACDCandle bullish color flip')
            return
        if sell_open:
            self._submit_entry(-1, 'MACDCandle bearish color flip')
            return

    def notify_order(self, order):
        """Update counters and retry reverse entries when exits are completed."""
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.log(f'ORDER FAILED status={order.getstatusname()}')
            self.order = None
            self.pending_entry_direction = 0
            self.pending_reverse_direction = 0
            if not self.position:
                self.entry_side = None
            return
        if order.status != order.Completed:
            return
        self.completed_order_count += 1
        if self.pending_entry_direction == 1 and order.isbuy() and self.position.size > 0:
            self.buy_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, 1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED LONG price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if self.pending_entry_direction == -1 and order.issell() and self.position.size < 0:
            self.sell_count += 1
            self.entry_price = order.executed.price
            self._set_entry_risk(self.entry_price, -1)
            self.pending_entry_direction = 0
            self.log(f'ENTRY FILLED SHORT price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            return
        if not self.position:
            self._clear_risk()
            self.log(f'EXIT FILLED price={order.executed.price:.5f} size={order.executed.size:.2f}')
            self.order = None
            self.entry_side = None
            reverse_direction = self.pending_reverse_direction
            self.pending_reverse_direction = 0
            if reverse_direction != 0:
                self._submit_entry(reverse_direction, 'reverse after MACDCandle signal')
            return
        self.order = None

    def notify_trade(self, trade):
        """Count closed trades and reset risk state on position exit."""
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self._clear_risk()
            self.entry_side = None


BASE_DIR = Path(__file__).resolve().parent

WORKSPACE_ROOT = BASE_DIR.parents[2]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if BACKTRADER_REPO.exists() and str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))


MINUTES_PER_TRADING_YEAR = 24 * 60 * 252


def resolve_data_path(filename):
    """Resolve and validate a fixture path.

    Args:
        filename: Relative path to a required CSV fixture.

    Returns:
        Absolute file path as ``Path``.
    """
    path = (BASE_DIR / filename).resolve()
    if not path.exists():
        raise FileNotFoundError(f'Data file not found: {path}')
    return path


def load_backtest_frame(config):
    """Load and time-filter the main source frame from migration config.

    Args:
        config: Migration config containing data block and date range.

    Returns:
        Dict containing the prepared frame and backtest bounds.
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
    """Build the Backtrader engine, data feeds, strategy and analyzers.

    Args:
        config: Combined strategy/backtest settings.
        frame: Preloaded input frame with date boundaries.

    Returns:
        Configured `bt.Cerebro` instance.
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
    execution_feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    cerebro.adddata(execution_feed, name=f"{data_cfg['symbol']}_{data_cfg['timeframe']}")
    if target_tf != data_cfg['timeframe']:
        signal_source_feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
        timeframe, compression = _timeframe_spec(target_tf)
        cerebro.resampledata(signal_source_feed, timeframe=timeframe, compression=compression, name=f"{data_cfg['symbol']}_{target_tf}")
    params = dict(config.get('params', {}))
    params.setdefault('contract_multiplier', bt_cfg['multiplier'])
    cerebro.addstrategy(MacdCandleStrategy, **params)
    cerebro.addanalyzer(btanalyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(btanalyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=15, tann=MINUTES_PER_TRADING_YEAR)
    cerebro.addanalyzer(btanalyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(btanalyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(btanalyzers.SQN, _name='sqn')
    return cerebro


def extract_metrics(strat, cerebro, frame, config):
    """Aggregate analyzer output and strategy counters for regression checks.

    Args:
        strat: Executed strategy object.
        cerebro: Finished cerebro engine.
        frame: Input frame metadata used during run.
        config: Migration config.

    Returns:
        Dictionary of metrics asserted by this test.
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
        'win_count': won,
        'loss_count': lost,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'net_pnl': final_value - initial_cash,
        'total_return_pct': (returns.get('rtot') or 0) * 100,
        'total_trades': total_trades,
        'won': won,
        'lost': lost,
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


def test_188_0187_0952_macdcandle() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/mean_reversion/0187_0952_macdcandle.
    """
    config = _bt_load_config(_CONFIG, repo=_REPO)
    inputs = _resolve_loader()(config)
    cerebro = _build_cerebro_compat(inputs, config)
    results = cerebro.run(runonce=True)
    metrics = _extract_metrics_compat(results[0], cerebro, inputs, config)

    assert metrics.get('bar_num') == 5551, f"bar_num: expected=5551, got={metrics.get('bar_num')!r}"
    assert metrics.get('win_count') == 10, f"win_count: expected=10, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 11, f"loss_count: expected=11, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 21, f"total_trades: expected=21, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 21, f"trade_count: expected=21, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 10, f"won: expected=10, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 11, f"lost: expected=11, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('buy_signal_count'), 10.0, tol=1.000000e-05, key='buy_signal_count')
    _close(metrics.get('sell_signal_count'), 11.0, tol=1.100000e-05, key='sell_signal_count')
    _close(metrics.get('completed_order_count'), 42.0, tol=4.200000e-05, key='completed_order_count')
    _close(metrics.get('rejected_order_count'), 0.0, tol=1.000000e-06, key='rejected_order_count')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1001658.000000001, tol=1.001658e+00, key='final_value')
    _close(metrics.get('net_pnl'), 1658.0000000010477, tol=1.658000e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.1656627035375118, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 47.61904761904761, tol=4.761905e-05, key='win_rate')
    _close(metrics.get('sharpe_ratio'), 4.861287085558189, tol=4.861287e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 10.303778527671367, tol=1.030378e-05, key='annual_return_pct')
    _close(metrics.get('max_drawdown'), 0.13984000022333518, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sqn'), 0.7604570464890034, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
