"""Price Crossover with Moving Average and ADX confirmation strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Price crossing over a long-term moving average suggests a potential trend change, but it requires confirmation of trend strength (ADX) and directional consistency (+DI and -DI) to avoid false breakouts.
    - **Indicators Used**:
        - *EMA (50)*: Smoothly represents the structural moving average. Rising EMA is bullish, falling is bearish.
        - *ADX (14)*: Average Directional Movement Index. Represents trend intensity. Filter requires ADX > 20.
        - *+DI and -DI*: Directional indicators confirming trend polarity.
    - **Crossover Rules**:
        - *Bullish (Buy)*: Close price crosses above the EMA, EMA is rising, ADX > 20, and +DI > -DI.
        - *Bearish (Sell)*: Close price crosses below the EMA, EMA is falling, ADX > 20, and -DI > +DI.

Strategy Logic:
    1. **Initialization**: Configures standard `bt.indicators.EMA` and directional movement indicators (ADX, PlusDI, MinusDI) via strategy parameters (`ma_period`, `adx_period`, `min_adx`).
    2. **Signal Filtering**:
        - Checks moving average trends (`ma0 > ma1 > ma2` for rising, and vice versa).
        - Confirms trend strength (`adx > min_adx`).
        - Validates positive or negative directional predominance (`di_plus > di_minus` for bullish, and vice versa).
    3. **Execution**:
        - *Entry*: Places a buy order of `lot` size on a bullish signal if no active position is open. Places a sell order of `lot` size on a bearish signal if no active position.
        - *SAR (Stop and Reverse)*: Reverses from long to short immediately upon a bearish signal, and vice versa.
    4. **Reporting**: Extracts backtesting performance stats (Sharpe ratio, returns, net cash value, drawdowns).
"""
from __future__ import annotations
import math
from pathlib import Path
import io
import argparse, datetime
import backtrader as bt
import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[4]

_CONFIG = {
    'strategy': {
        'name': 'Price Cross MA + ADX',
        'source_ea': 'ea/1329_MQL5_Wizard_-_Trading_Signals_Based_on_Price_Crossing_MA_and_Confirmed_by_ADX/expert_adx_ma.mq5',
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
        'ma_period': 50,
        'adx_period': 14,
        'min_adx': 20,
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


class Mt5PandasFeed(bt.feeds.PandasData):
    """Custom Pandas Data Feed for MT5 CSV format.

    Maps MT5 CSV columns (open, high, low, close, volume, openinterest) to Backtrader-compatible fields.
    """
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class PriceCrossMAAdxStrategy(bt.Strategy):
    """
    Price crossing MA + ADX confirmation.
    Buy: Close(1)>MA(1), MA rising, ADX>min_adx, DI+ > DI-
    Sell: Close(1)<MA(1), MA falling, ADX>min_adx, DI- > DI+
    """
    params = dict(
        ma_period=50,
        adx_period=14,
        min_adx=20,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        """Initializes EMA, ADX, PlusDI, and MinusDI indicators along with trade tracking variables."""
        self.ma = bt.indicators.EMA(self.data.close, period=self.p.ma_period)
        self.adx = bt.indicators.AverageDirectionalMovementIndex(self.data, period=self.p.adx_period)
        self.di_plus = bt.indicators.PlusDirectionalIndicator(self.data, period=self.p.adx_period)
        self.di_minus = bt.indicators.MinusDirectionalIndicator(self.data, period=self.p.adx_period)
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

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Calculates price crossovers against EMA and verifies trend strength using ADX/DI rules.
        Handles SAR execution logic for active and new positions.
        """
        self.bar_num += 1
        if len(self.data) < max(self.p.ma_period, self.p.adx_period) + 5:
            return

        c1 = float(self.data.close[-1])
        ma0 = float(self.ma[0])
        ma1 = float(self.ma[-1])
        ma2 = float(self.ma[-2])
        adx_val = float(self.adx.adx[0])
        di_plus = float(self.di_plus.plusDI[0])
        di_minus = float(self.di_minus.minusDI[0])

        ma_rising = ma0 > ma1 and ma1 > ma2
        ma_falling = ma0 < ma1 and ma1 < ma2
        trend_strong = adx_val > self.p.min_adx

        buy_sig = c1 > ma1 and ma_rising and trend_strong and di_plus > di_minus
        sell_sig = c1 < ma1 and ma_falling and trend_strong and di_minus > di_plus

        if self.position:
            if self.position.size > 0 and sell_sig:
                self.log(f'close long & sell price={self.data.close[0]:.2f} adx={adx_val:.1f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            if self.position.size < 0 and buy_sig:
                self.log(f'close short & buy price={self.data.close[0]:.2f} adx={adx_val:.1f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if buy_sig:
                self.log(f'buy signal price={self.data.close[0]:.2f} adx={adx_val:.1f}')
                self.buy(size=self.p.lot)
                return
            if sell_sig:
                self.log(f'sell signal price={self.data.close[0]:.2f} adx={adx_val:.1f}')
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
    cerebro.addstrategy(PriceCrossMAAdxStrategy, **config.get('params', {}))
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
    config=load_config(); frame=load_backtest_frame(config); cerebro=build_cerebro(config,frame)
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


def test_165_0165_1329_price_cross_ma_adx() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0165_1329_price_cross_ma_adx.
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

    assert metrics.get('bar_num') == 6080, f"bar_num: expected=6080, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 61, f"buy_count: expected=61, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 60, f"sell_count: expected=60, got={metrics.get('sell_count')!r}"
    assert metrics.get('win_count') == 46, f"win_count: expected=46, got={metrics.get('win_count')!r}"
    assert metrics.get('loss_count') == 74, f"loss_count: expected=74, got={metrics.get('loss_count')!r}"
    assert metrics.get('total_trades') == 121, f"total_trades: expected=121, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 120, f"trade_count: expected=120, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 46, f"won: expected=46, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 74, f"lost: expected=74, got={metrics.get('lost')!r}"
    _close(metrics.get('bars'), 6129.0, tol=6.129000e-03, key='bars')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1011723.7000000024, tol=1.011724e+00, key='final_value')
    _close(metrics.get('net_pnl'), 11723.700000002398, tol=1.172370e-02, key='net_pnl')
    _close(metrics.get('total_return_pct'), 1.1723700000002335, tol=1.172370e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 38.01652892561984, tol=3.801653e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.5785557986870902, tol=1.578556e-06, key='profit_factor')
    _close(metrics.get('max_drawdown'), 0.5015678792695231, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sharpe_ratio'), 10.254403189640282, tol=1.025440e-05, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 99.38916614702566, tol=9.938917e-05, key='annual_return_pct')
    _close(metrics.get('sqn'), 1.2741786111215545, tol=1.274179e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
