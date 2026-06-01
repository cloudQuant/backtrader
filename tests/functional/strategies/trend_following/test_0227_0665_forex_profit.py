"""Forex Profit triple EMA and Parabolic SAR trend-following strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: H1 (1-hour compressed from M15 data).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift and resampled to 1 hour.

Strategy Principle:
    - **Market Hypothesis**: Combining short-term, medium-term, and long-term moving averages with Parabolic SAR allows for strong trend-following setups and strict protection against trend exhaustion.
    - **Indicators Used**:
        - *EMA (10)*: Short-term trend baseline applied on K-line median price.
        - *EMA (25)*: Medium-term trend baseline applied on K-line median price.
        - *EMA (50)*: Long-term trend baseline applied on K-line median price.
        - *Parabolic SAR*: Trend direction confirmation.
    - **Trading Rules**:
        - *Buy Signal (Bullish)*: EMA 10 is greater than EMA 25 and EMA 50, EMA 10 on the prior bar is less than or equal to EMA 50 on the prior bar, and Parabolic SAR on the prior bar is below close price.
        - *Sell Signal (Bearish)*: EMA 10 is less than EMA 25 and EMA 50, EMA 10 on the prior bar is greater than or equal to EMA 50 on the prior bar, and Parabolic SAR on the prior bar is above close price.
        - *Exit/Take Profit*: Fixed take profit pips, trailing stop loss, or early exit if EMA 10 reverses and floating profit exceeds `min_profit_to_exit`.

Strategy Logic:
    1. **Initialization**: Configures parameters for triple EMAs (`ema10_period`, `ema25_period`, `ema50_period`), SAR (`sar_af`, `sar_afmax`), and pip levels (`stop_loss_buy`, `take_profit_buy`, etc.).
    2. **Signal Detection**:
        - Scans for crossovers of EMA 10 relative to EMA 25 and 50.
        - Checks Parabolic SAR position relative to close price.
    3. **Position Tracking**:
        - Updates risk management stop prices via trailing stops.
        - Monitors EMA 10 directional changes for early-take-profit closures when floating profit exceeds threshold.
    4. **Reporting**: Extracts Sharpe ratio, net PnL, win/loss trade ratios, drawdowns, and system performance.
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
        'name': 'Forex_Profit',
        'source_ea': 'ea/0665_Forex_Profit/forex_profit.mq5',
    },
    'data': {
        'symbol': 'XAUUSD',
        'timeframe': 'H1',
        'file': '{repo}/tests/datas/XAUUSD_M15.csv',
        'fromdate': '2025-12-03 01:15:00',
        'todate': '2026-03-10 09:00:00',
        'bar_shift_minutes': 15,
        'compression': 60,
    },
    'params': {
        'take_profit_buy': 55,
        'take_profit_sell': 65,
        'stop_loss_buy': 60,
        'stop_loss_sell': 85,
        'trailing_stop_buy': 20,
        'trailing_step': 5,
        'trailing_stop_sell': 74,
        'lots': 1.0,
        'ema10_period': 10,
        'ema25_period': 25,
        'ema50_period': 50,
        'sar_af': 0.02,
        'sar_afmax': 0.2,
        'point': 0.01,
        'price_digits': 2,
        'contract_multiplier': 100.0,
        'min_profit_to_exit': 10.0,
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
    """Custom Pandas Data Feed for MT5 CSV format.

    Maps MT5 CSV columns (open, high, low, close, volume, openinterest) to Backtrader-compatible fields.
    """
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ForexProfitStrategy(bt.Strategy):
    """Forex Profit Strategy utilizing Triple EMAs and Parabolic SAR.

    Coordinates three EMAs (10, 25, 50) and Parabolic SAR to trigger buy/sell orders,
    supporting trailing stops and early exits on moving average reversals.
    """
    params = dict(
        take_profit_buy=55,
        take_profit_sell=65,
        stop_loss_buy=60,
        stop_loss_sell=85,
        trailing_stop_buy=20,
        trailing_step=5,
        trailing_stop_sell=74,
        lots=1.0,
        ema10_period=10,
        ema25_period=25,
        ema50_period=50,
        sar_af=0.02,
        sar_afmax=0.2,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
        min_profit_to_exit=10.0,
    )

    def __init__(self):
        """Initializes EMA indicators, Parabolic SAR, and tracking counters."""
        median = (self.data.high + self.data.low) / 2.0
        self.ema10 = bt.indicators.ExponentialMovingAverage(median, period=self.p.ema10_period)
        self.ema25 = bt.indicators.ExponentialMovingAverage(median, period=self.p.ema25_period)
        self.ema50 = bt.indicators.ExponentialMovingAverage(median, period=self.p.ema50_period)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.sar_af, afmax=self.p.sar_afmax)

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
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _floating_pnl(self):
        if not self.position:
            return 0.0
        return (float(self.data.close[0]) - float(self.position.price)) * float(self.position.size) * float(self.p.contract_multiplier)

    def _set_risk(self, side, price):
        if side == 'buy':
            self.stop_price = self._round(price - float(self.p.stop_loss_buy) * self._point())
            self.take_profit_price = self._round(price + float(self.p.take_profit_buy) * self._point())
        else:
            self.stop_price = self._round(price + float(self.p.stop_loss_sell) * self._point())
            self.take_profit_price = self._round(price - float(self.p.take_profit_sell) * self._point())

    def _buy_signal(self):
        return float(self.ema10[0]) > float(self.ema25[0]) and float(self.ema10[0]) > float(self.ema50[0]) and float(self.ema10[-1]) <= float(self.ema50[-1]) and float(self.sar[-1]) < float(self.data.close[-1])

    def _sell_signal(self):
        return float(self.ema10[0]) < float(self.ema25[0]) and float(self.ema10[0]) < float(self.ema50[0]) and float(self.ema10[-1]) >= float(self.ema50[-1]) and float(self.sar[-1]) > float(self.data.close[-1])

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        ema10_now = float(self.ema10[0])
        ema10_prev = float(self.ema10[-1])
        pnl = self._floating_pnl()
        if self.position.size > 0:
            if ema10_now < ema10_prev and pnl > float(self.p.min_profit_to_exit):
                self.order = self.close()
                return
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
            if float(self.p.trailing_stop_buy) > 0:
                move_trigger = float(self.p.trailing_stop_buy) * self._point()
                if float(self.data.close[0]) - float(self.position.price) > move_trigger:
                    candidate = self._round(float(self.data.close[0]) - move_trigger)
                    threshold = self._round(float(self.data.close[0]) - (float(self.p.trailing_stop_buy) + float(self.p.trailing_step)) * self._point())
                    if self.stop_price is None or float(self.stop_price) < threshold:
                        self.stop_price = candidate
        else:
            if ema10_now > ema10_prev and pnl > float(self.p.min_profit_to_exit):
                self.order = self.close()
                return
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return
            if float(self.p.trailing_stop_sell) > 0:
                move_trigger = float(self.p.trailing_stop_sell) * self._point()
                if float(self.position.price) - float(self.data.close[0]) > move_trigger:
                    candidate = self._round(float(self.data.close[0]) + move_trigger)
                    threshold = self._round(float(self.data.close[0]) + (float(self.p.trailing_stop_sell) + float(self.p.trailing_step)) * self._point())
                    if self.stop_price is None or float(self.stop_price) > threshold:
                        self.stop_price = candidate

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Evaluates active positions for protection rules or trailing stops,
        and scans for new entries based on Triple EMA crossovers and Parabolic SAR filters.
        """
        self.bar_num += 1
        if len(self) < self.p.ema50_period + 2:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        signal = 0
        if self._buy_signal():
            signal = 1
        elif self._sell_signal():
            signal = -1
        if signal == 0:
            return
        self.signal_count += 1
        price = float(self.data.close[0])
        if signal > 0:
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.lots)
        else:
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        """Tracks order status and coordinates protection levels for completed transactions.

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
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        """Logs trade closure, resets risk state, and records trade win/loss statistics.

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
    print(f'Loaded {len(df)} bars: {df.index[0]} -> {df.index[-1]}')
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
    feed = Mt5PandasFeed(
        dataname=frame['data'][['open', 'high', 'low', 'close', 'volume', 'openinterest']],
        timeframe=bt.TimeFrame.Minutes,
        compression=data_cfg.get('compression', 60),
    )
    cerebro.adddata(feed, name=f"{data_cfg['symbol']}_{data_cfg['timeframe']}")
    cerebro.addstrategy(ForexProfitStrategy, **config.get('params', {}))
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Minutes, factor=MINUTES_PER_TRADING_YEAR, annualize=True, riskfreerate=0)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns', timeframe=bt.TimeFrame.Minutes, compression=data_cfg.get('compression', 60), tann=MINUTES_PER_TRADING_YEAR)
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
        'bars': len(frame['data']),
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


def test_226_0227_0665_forex_profit() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0227_0665_forex_profit.
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

    assert metrics.get('bar_num') == 6080, f"bar_num: expected=6080, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 61, f"buy_count: expected=61, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 56, f"sell_count: expected=56, got={metrics.get('sell_count')!r}"
    assert metrics.get('total_trades') == 117, f"total_trades: expected=117, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 117, f"trade_count: expected=117, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 55, f"won: expected=55, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 62, f"lost: expected=62, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('signal_count'), 117.0, tol=1.170000e-04, key='signal_count')
    _close(metrics.get('completed_orders'), 234.0, tol=2.340000e-04, key='completed_orders')
    _close(metrics.get('rejected_orders'), 0.0, tol=1.000000e-06, key='rejected_orders')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1014652.0000000005, tol=1.014652e+00, key='final_value')
    _close(metrics.get('net_pnl'), 14652.000000000466, tol=1.465200e-02, key='net_pnl')
    _close(metrics.get('total_return_pct'), 1.4652000000000553, tol=1.465200e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 47.008547008547005, tol=4.700855e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.3496647018113297, tol=1.349665e-06, key='profit_factor')
    _close(metrics.get('sharpe_ratio'), 5.078768079983184, tol=5.078768e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 2602.881220156706, tol=2.602881e-03, key='annual_return_pct')
    _close(metrics.get('max_drawdown'), 1.1291195588446652, tol=1.129120e-06, key='max_drawdown')
    _close(metrics.get('sqn'), 0.6543329715825276, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
