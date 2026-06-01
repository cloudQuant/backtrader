"""Hammer and Hanging Man pattern with Stochastic confirmation strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Candlestick patterns with extreme shadows (like Hammer and Hanging Man) signify potential local trend exhaustion and reversal, which are highly effective when confirmed by Slow Stochastic overbought/oversold levels.
    - **Hammer Pattern (Bullish Reversal)**:
        - Midpoint of the bar is below the prior bt.indicators.SMA.
        - The real body is small and situated in the upper 1/3 of the bar range.
        - Current close and open prices are lower than prior close and open prices.
        - Trigger long if oversold (Stochastic %D < 30).
    - **Hanging Man Pattern (Bearish Reversal)**:
        - Midpoint of the bar is above the prior bt.indicators.SMA.
        - The real body is small and situated in the upper 1/3 of the bar range.
        - Current close and open prices are higher than prior close and open prices.
        - Trigger short if overbought (Stochastic %D > 70).

Strategy Logic:
    1. **Initialization**: Instantiates Slow Stochastic (`period=stoch_k`, `period_dfast=stoch_d`, `period_dslow=stoch_slow`) and a Simple Moving Average (SMA) of close prices over `ma_period` as trend baseline. Sets metrics tracking variables.
    2. **Pattern Verification**:
        - `_hammer()` checks for small bodies in the top 1/3, falling closes/opens, and midpoint below bt.indicators.SMA.
        - `_hanging_man()` checks for small bodies in the top 1/3, rising closes/opens, and midpoint above bt.indicators.SMA.
    3. **Execution**:
        - *Entry*: Enters long on a Hammer signal with oversold Stochastic (%D < 30). Enters short on a Hanging Man signal with overbought Stochastic (%D > 70).
        - *Exit*: Closes long position if Stochastic %D crosses 20 or 80 upwards, or a Hanging Man signal occurs. Closes short position if Stochastic %D crosses 80 or 20 downwards, or a Hammer signal occurs.
    4. **Reporting**: Extracts portfolio performance stats (Sharpe ratio, returns, net cash value, drawdowns).
"""
from __future__ import annotations
import backtrader as bt
import math
from pathlib import Path
import argparse, datetime
import pytest
from backtrader.utils.load_data import load_config as _bt_load_config, load_mt5_csv

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Hammer / Hanging Man + Stochastic',
        'source_ea': 'ea/1334_MQL5_Wizard_-_Trading_Signals_Based_on_Hammer_Hanging_Man_Pattern_+_Stochastic',
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
        'stoch_k': 14,
        'stoch_d': 3,
        'stoch_slow': 3,
        'ma_period': 5,
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


class Mt5PandasFeed(bt.feeds.PandasData):
    """Custom Pandas Data Feed for MT5 CSV format.

    Maps MT5 CSV columns (open, high, low, close, volume, openinterest) to Backtrader-compatible fields.
    """
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class HammerStochStrategy(bt.Strategy):
    """
    Hammer / Hanging Man + Stochastic confirmation.
    Buy: Hammer pattern (downtrend, small body top 1/3, long lower shadow) + Stoch %D < 30
    Sell: Hanging Man pattern (uptrend, small body top 1/3, long lower shadow) + Stoch %D > 70
    Exit: Stochastic %D crosses critical levels (20/80)
    """
    params = dict(
        stoch_k=14,
        stoch_d=3,
        stoch_slow=3,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initializes Slow Stochastic, trend SMA, and metrics tracking variables."""
        self.stoch = bt.indicators.StochasticSlow(
            self.data, period=self.p.stoch_k, period_dfast=self.p.stoch_d,
            period_dslow=self.p.stoch_slow)
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.bar_num = 0
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
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _hammer(self):
        h1 = float(self.data.high[-1])
        l1 = float(self.data.low[-1])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        rng = h1 - l1
        if rng == 0:
            return False
        mid1 = (h1 + l1) / 2.0
        close_avg = float(self.sma[-2])
        body_min = min(o1, c1)
        return (mid1 < close_avg and
                body_min > (h1 - rng / 3.0) and
                c1 < float(self.data.close[-2]) and
                o1 < float(self.data.open[-2]))

    def _hanging_man(self):
        h1 = float(self.data.high[-1])
        l1 = float(self.data.low[-1])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        rng = h1 - l1
        if rng == 0:
            return False
        mid1 = (h1 + l1) / 2.0
        close_avg = float(self.sma[-2])
        body_min = min(o1, c1)
        return (mid1 > close_avg and
                body_min > (h1 - rng / 3.0) and
                c1 > float(self.data.close[-2]) and
                o1 > float(self.data.open[-2]))

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Evaluates active positions for exits and Stop-and-Reverse triggers.
        Scans for new Hammer and Hanging Man candlestick setups with Stochastic %D confirmation.
        """
        self.bar_num += 1
        if len(self.data) < max(self.p.stoch_k, self.p.ma_period) + 5:
            return

        stoch_d1 = float(self.stoch.percD[-1])
        stoch_d2 = float(self.stoch.percD[-2]) if len(self.stoch.percD) > 2 else stoch_d1

        hammer = self._hammer()
        hanging = self._hanging_man()

        if self.position:
            if self.position.size > 0:
                exit_long = ((stoch_d1 > 20 and stoch_d2 < 20) or (stoch_d1 > 80 and stoch_d2 < 80))
                if exit_long or (hanging and stoch_d1 > 70):
                    self.log(f'close long stoch={stoch_d1:.1f}')
                    self.close()
                    if hanging and stoch_d1 > 70:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                exit_short = ((stoch_d1 < 80 and stoch_d2 > 80) or (stoch_d1 < 20 and stoch_d2 > 20))
                if exit_short or (hammer and stoch_d1 < 30):
                    self.log(f'close short stoch={stoch_d1:.1f}')
                    self.close()
                    if hammer and stoch_d1 < 30:
                        self.buy(size=self.p.lot)
                    return
        else:
            if hammer and stoch_d1 < 30:
                self.log(f'buy hammer stoch={stoch_d1:.1f}')
                self.buy(size=self.p.lot)
                return
            if hanging and stoch_d1 > 70:
                self.log(f'sell hanging_man stoch={stoch_d1:.1f}')
                self.sell(size=self.p.lot)
                return

    def notify_trade(self, trade):
        """Logs and records trade closure and profit statistics.

        Tracks trade performance including win/loss counts, net PnL, and total transactions.

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
    if not path.exists(): raise FileNotFoundError(f'Data file not found: {path}')
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
    df = load_mt5_csv(resolve_data_path(data_cfg['file']), fromdate=fromdate, todate=todate,
                      bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0))
    if df.empty: raise ValueError('Loaded data frame is empty')
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
    cerebro = bt.Cerebro(stdstats=True)
    cerebro.broker.setcash(bt_cfg['initial_cash'])
    comm_type = bt.CommInfoBase.COMM_FIXED if bt_cfg.get('commission_type','fixed')=='fixed' else bt.CommInfoBase.COMM_PERC
    cerebro.broker.setcommission(commission=bt_cfg['commission'], margin=bt_cfg['margin'],
        mult=bt_cfg['multiplier'], commtype=comm_type, stocklike=bt_cfg.get('stocklike',False))
    feed = Mt5PandasFeed(dataname=frame['data'], timeframe=bt.TimeFrame.Minutes, compression=15)
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(HammerStochStrategy, **config.get('params', {}))
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
    ic = config['backtest']['initial_cash']; fv = cerebro.broker.getvalue()
    tt = trades.get('total',{}).get('total',0); w = trades.get('won',{}).get('total',0)
    l = trades.get('lost',{}).get('total',0)
    gw = trades.get('won',{}).get('pnl',{}).get('total',0) or 0
    gl = abs(trades.get('lost',{}).get('pnl',{}).get('total',0) or 0)
    return {'fromdate':frame['fromdate'],'todate':frame['todate'],'bars':len(frame['data']),
        'bar_num':strat.bar_num,'buy_count':strat.buy_count,'sell_count':strat.sell_count,
        'trade_count':strat.trade_count,'win_count':strat.win_count,'loss_count':strat.loss_count,
        'initial_cash':ic,'final_value':fv,'net_pnl':fv-ic,'total_return_pct':(fv/ic-1)*100,
        'total_trades':tt,'won':w,'lost':l,'win_rate':(w/tt*100) if tt else 0,
        'profit_factor':(gw/gl) if gl else None,'max_drawdown':drawdown.get('max',{}).get('drawdown',0),
        'sharpe_ratio':sharpe.get('sharperatio'),'annual_return_pct':(returns.get('rnorm') or 0)*100,
        'sqn':sqn.get('sqn')}

def run(plot=False):
    """Orchestrates strategy loading, execution, evaluation, and optional plotting.

    Args:
        plot (bool, optional): Whether to plot backtest chart. Defaults to False.

    Returns:
        tuple: (results, metrics, cerebro) containing strategy results, metrics dict, and engine.
    """
    config=_bt_load_config(_CONFIG, repo=_REPO); frame=load_backtest_frame(config); cerebro=build_cerebro(config,frame)
    print('\nStarting backtest...'); results=cerebro.run(); strat=results[0]
    metrics=extract_metrics(strat,cerebro,frame,config); print_report(metrics)
    if plot: cerebro.plot()
    return results,metrics,cerebro


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--plot',action='store_true'); a=p.parse_args()
    run(plot=a.plot)


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


def test_167_0167_1334_hammer_stoch() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0167_1334_hammer_stoch.
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

    assert metrics.get('bar_num') == 6112, f"bar_num: expected=6112, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 24, f"buy_count: expected=24, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 24, f"sell_count: expected=24, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 33, f"win_count: expected=33, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 15, f"loss_count: expected=15, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 48, f"total_trades: expected=48, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 48, f"trade_count: expected=48, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 33, f"won: expected=33, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 15, f"lost: expected=15, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1000287.8000000003, tol=1.000288e+00, key='final_value')
    _close(metrics.get('net_pnl'), 287.8000000002794, tol=2.878000e-04, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.028780000000017125, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 68.75, tol=6.875000e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.0676412522327696, tol=1.067641e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.1743076150258954, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), 1.1015251459677435, tol=1.101525e-06, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 1.7183300180026309, tol=1.718330e-06, key='annual_return_pct')
    _close(metrics.get('sqn'), 0.15958367948873808, tol=1.000000e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
