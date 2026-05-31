"""Kijun-sen (Ichimoku) and EMA breakout trend-following strategy functional test.

Data Used:
    - **Symbol**: XAUUSD (Gold).
    - **Timeframe**: M15 (15-minute bars).
    - **Data Range**: 2025-12-03 01:15:00 to 2026-03-10 09:00:00.
    - **Data Source**: MT5 exported CSV parsed via `Mt5PandasFeed` with a 15-minute K-line shift.

Strategy Principle:
    - **Market Hypothesis**: Breakthroughs across the Kijun-sen (Base Line) of the Ichimoku Kinko Hyo system signify major trend reversals, which can be confirmed by an Exponential Moving Average (EMA) and Parabolic SAR to construct robust trend-following setups.
    - **Indicators Used**:
        - *Ichimoku Kijun-sen (12)*: Key support/resistance trend baseline.
        - *EMA (20)*: Filter representing secondary trend direction.
        - *Parabolic SAR*: Directional stop-and-reverse indicator used for confirmation.
    - **Trading Rules**:
        - *Bullish (Buy)*: Price crosses above Kijun-sen, the EMA is below Kijun-sen by more than `ma_filter_pips`, the EMA trend is upward, and Parabolic SAR is below the price.
        - *Bearish (Sell)*: Price crosses below Kijun-sen, the EMA is above Kijun-sen by more than `ma_filter_pips`, the EMA trend is downward, and Parabolic SAR is above the price.
        - *Exit/Take Profit*: Fixed stop loss (`stop_loss_pips`), take profit (`take_profit_pips`), break-even lock (`break_even_pips`), trailing stop (`trailing_stop_pips`), and exit on EMA trend reversals before break-even is achieved.

Strategy Logic:
    1. **Initialization**: Configures parameters for Ichimoku Kijun-sen, EMA, Parabolic SAR, SL/TP pips, break-even pips, and trading session hours (`day_start_hour` and `day_end_hour`).
    2. **Crossover Checks**:
        - Monitors price crosses relative to Kijun-sen within the designated session hours.
        - Validates the EMA direction filter (`ma_dir`) and spacing to confirm entry feasibility.
    3. **Position Management**:
        - Instantiates initial SL/TP price levels on trade fills.
        - Updates moving stop loss prices to break-even or trailing stops based on price actions.
        - Closes active position on protection targets or if the EMA direction reverses before break-even is activated.
    4. **Reporting**: Extracts Sharpe ratio, net returns, drawdowns, win rate, and total executed transactions.
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
        'name': 'kijun_sen_robot',
        'source_ea': 'ea/0696_Kijun_Sen_Robot/kijun_sen_robot.mq5',
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
        'symbol_hint': 'XAUUSD',
        'tenkan': 6,
        'kijun': 12,
        'senkou': 24,
        'ma_period': 20,
        'sar_step': 0.02,
        'sar_maximum': 0.2,
        'lot': 0.1,
        'point': 0.01,
        'price_digits': 2,
        'take_profit_pips': 120,
        'stop_loss_pips': 50,
        'break_even_pips': 9,
        'trailing_stop_pips': 10,
        'ma_filter_pips': 6,
        'use_optimized_values': False,
        'day_start_hour': 7,
        'day_end_hour': 19,
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





UP = 1
DOWN = -1
NEUTRAL = 0


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
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
        df['openinterest'] = 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'openinterest']]
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class KijunSenRobotStrategy(bt.Strategy):
    """Kijun-sen Breakout Trend-Following Robot Strategy.

    Integrates Ichimoku Kijun-sen crossings, EMA filters, and Parabolic SAR
    to initiate trades, protected by break-even, trailing stops, and reversal rules.
    """
    params = dict(
        symbol_hint='XAUUSD',
        tenkan=6,
        kijun=12,
        senkou=24,
        ma_period=20,
        sar_step=0.02,
        sar_maximum=0.2,
        lot=1.0,
        point=0.01,
        price_digits=2,
        take_profit_pips=120,
        stop_loss_pips=50,
        break_even_pips=9,
        trailing_stop_pips=10,
        ma_filter_pips=6,
        use_optimized_values=False,
        day_start_hour=7,
        day_end_hour=19,
    )

    def __init__(self):
        """Initializes Ichimoku, EMA, and Parabolic SAR indicators, states, and performance counters."""
        self.ichimoku = bt.indicators.Ichimoku(
            self.data,
            tenkan=self.p.tenkan,
            kijun=self.p.kijun,
            senkou=self.p.senkou,
            senkou_lead=self.p.kijun,
            chikou=self.p.kijun,
        )
        self.ema = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.sar_step, afmax=self.p.sar_maximum)
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._last_bid = None
        self._last_ask = None
        self.long_cross = 0.0
        self.short_cross = 0.0
        self.long_entry = 0.0
        self.short_entry = 0.0
        self.ma_dir = NEUTRAL
        self._pending_signal = 0
        self._effective = self._resolve_effective_params()

    def _resolve_effective_params(self):
        params = {
            'take_profit_pips': float(self.p.take_profit_pips),
            'stop_loss_pips': float(self.p.stop_loss_pips),
            'break_even_pips': float(self.p.break_even_pips),
            'trailing_stop_pips': float(self.p.trailing_stop_pips),
            'ma_filter_pips': float(self.p.ma_filter_pips),
        }
        if self.p.use_optimized_values:
            optimized = {
                'GBPUSD': dict(stop_loss_pips=50.0, break_even_pips=9.0, trailing_stop_pips=10.0, ma_filter_pips=6.0),
                'EURUSD': dict(stop_loss_pips=60.0, break_even_pips=9.0, trailing_stop_pips=6.0, ma_filter_pips=6.0),
            }
            params.update(optimized.get(str(self.p.symbol_hint).upper(), {}))
        return params

    def log(self, text):
        """Logs strategy events with current datetime.

        Args:
            text (str): Log message.
        """
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _round_price(self, value):
        return round(float(value), int(self.p.price_digits))

    def _within_entry_hours(self):
        dt = bt.num2date(self.data.datetime[0])
        return self.p.day_start_hour <= dt.hour <= self.p.day_end_hour - 1

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _sync_position_state(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self._effective['stop_loss_pips'] * pip_size
        take_distance = self._effective['take_profit_pips'] * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price + take_distance if take_distance > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price - take_distance if take_distance > 0 else None

    def _close_on_protection(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'long protective exit stop={self._stop_price:.2f} low={low:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'long protective exit tp={self._take_profit_price:.2f} high={high:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'short protective exit stop={self._stop_price:.2f} high={high:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'short protective exit tp={self._take_profit_price:.2f} low={low:.2f}')
                self.order = self.close()
                return True
        return False

    def _close_on_ema_reversal(self):
        if not self.position or len(self.data) < 3:
            return False
        ema_prev = float(self.ema[-1])
        ema_prev2 = float(self.ema[-2])
        if any(math.isnan(v) for v in (ema_prev, ema_prev2)):
            return False
        if self.position.size > 0 and ema_prev < ema_prev2 and (self._stop_price is None or self._stop_price < self._entry_price):
            self.log('close long on EMA reversal before break-even')
            self.order = self.close()
            return True
        if self.position.size < 0 and ema_prev > ema_prev2 and (self._stop_price is None or self._stop_price > self._entry_price):
            self.log('close short on EMA reversal before break-even')
            self.order = self.close()
            return True
        return False

    def _update_break_even(self):
        if not self.position or self._entry_price is None:
            return
        pip_size = self._pip_size()
        threshold = self._effective['break_even_pips'] * pip_size
        if threshold <= 0:
            return
        price = float(self.data.close[0])
        be_offset = pip_size
        if self.position.size > 0:
            if price - self._entry_price > threshold:
                candidate = self._entry_price + be_offset
                if self._stop_price is None or self._stop_price < candidate:
                    self._stop_price = self._round_price(candidate)
        else:
            if self._entry_price - price > threshold:
                candidate = self._entry_price - be_offset
                if self._stop_price is None or self._stop_price > candidate:
                    self._stop_price = self._round_price(candidate)

    def _update_trailing_stop(self):
        if not self.position or self._entry_price is None:
            return
        pip_size = self._pip_size()
        threshold = self._effective['trailing_stop_pips'] * pip_size
        if threshold <= 0:
            return
        price = float(self.data.close[0])
        if self.position.size > 0:
            if price - self._entry_price > threshold:
                candidate = self._round_price(price - threshold)
                if self._stop_price is None or self._stop_price < candidate:
                    self._stop_price = candidate
        else:
            if self._entry_price - price > threshold:
                candidate = self._round_price(price + threshold)
                if self._stop_price is None or self._stop_price > candidate:
                    self._stop_price = candidate

    def _compute_entry_signal(self):
        if not self._within_entry_hours() or len(self.data) < 3:
            return 0
        ks = float(self.ichimoku.kijun_sen[0])
        ks2 = float(self.ichimoku.kijun_sen[-2])
        ema_curr = float(self.ema[0])
        ema_prev = float(self.ema[-1])
        current_open = float(self.data.open[0])
        current_close = float(self.data.close[0])
        prev_close = float(self.data.close[-1])
        if any(math.isnan(v) for v in (ks, ks2, ema_curr, ema_prev, current_open, current_close, prev_close)):
            return 0
        pip_size = self._pip_size()
        ma_filter_distance = self._effective['ma_filter_pips'] * pip_size
        last_bid = prev_close if self._last_bid is None else self._last_bid
        last_ask = prev_close if self._last_ask is None else self._last_ask
        if current_open < ks and last_bid < ks and current_close > ks and self.long_cross == 0 and ks >= ks2:
            if ema_curr < ks - ma_filter_distance:
                self.long_cross = ks
                self.short_cross = 0.0
        if current_open > ks and last_ask > ks and current_close < ks and self.short_cross == 0 and ks <= ks2:
            if ema_curr > ks + ma_filter_distance:
                self.short_cross = ks
                self.long_cross = 0.0
        if ema_prev < ema_curr:
            self.ma_dir = UP
        elif ema_prev > ema_curr:
            self.ma_dir = DOWN
        if self.ma_dir == UP and self.long_cross != 0:
            self.long_entry = self._round_price(ks)
            return 1
        if self.ma_dir == DOWN and self.short_cross != 0:
            self.short_entry = self._round_price(ks)
            return -1
        self._last_bid = current_close
        self._last_ask = current_close
        return 0

    def next(self):
        """Executes core strategy logic on every K-line bar.

        Updates position state, applies protective target levels, and monitors
        Kijun-sen crossover signals and EMA filters to enter new trades.
        """
        self.bar_num += 1
        warmup = max(self.p.senkou, self.p.ma_period) + 3
        if len(self.data) < warmup:
            return
        if self.order:
            return
        self._sync_position_state()
        if self.position:
            if self._close_on_protection():
                return
            if self._close_on_ema_reversal():
                return
            self._update_break_even()
            self._update_trailing_stop()
            return
        action = self._compute_entry_signal()
        if action == 0:
            return
        self.signal_count += 1
        current_close = float(self.data.close[0])
        pip_size = self._pip_size()
        if action > 0:
            mode = 'market'
            if current_close > self.long_entry + 4 * pip_size:
                mode = 'buy_limit_approx'
            self.log(f'long signal entry={self.long_entry:.2f} close={current_close:.2f} mode={mode}')
            self._pending_signal = 1
            self.order = self.buy(size=self.p.lot)
            return
        mode = 'market'
        if current_close < self.short_entry - 4 * pip_size:
            mode = 'sell_limit_approx'
        self.log(f'short signal entry={self.short_entry:.2f} close={current_close:.2f} mode={mode}')
        self._pending_signal = -1
        self.order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        """Tracks order status and updates protective target levels on completed fills.

        Args:
            order (bt.Order): Backtrader order status notification object.
        """
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self._pending_signal > 0:
                self.long_cross = 0.0
                self.long_entry = 0.0
            elif self._pending_signal < 0:
                self.short_cross = 0.0
                self.short_entry = 0.0
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.rejected_order_count += 1
        if not self.position:
            self._clear_position_state()
        self._pending_signal = 0
        self.order = None

    def notify_trade(self, trade):
        """Logs trade closure, resets risk states, and records trade win/loss statistics.

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
    frame = load_mt5_csv(
        resolve_data_path(data_cfg['file']),
        fromdate=fromdate,
        todate=todate,
        bar_shift_minutes=data_cfg.get('bar_shift_minutes', 0),
    )
    if frame.empty:
        raise ValueError('Loaded data frame is empty')
    print(f'Loaded bars: {len(frame)}')
    return {'base': frame, 'fromdate': fromdate, 'todate': todate}


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
    cerebro.broker.setcommission(
        commission=bt_cfg['commission'],
        margin=bt_cfg['margin'],
        mult=bt_cfg['multiplier'],
        commtype=comm_type,
        stocklike=bt_cfg.get('stocklike', False),
    )
    base_df = frame['base'].copy()
    base_df['volume'] = base_df['tick_volume']
    feed = Mt5PandasFeed(
        dataname=base_df[['open', 'high', 'low', 'close', 'volume', 'openinterest']],
        timeframe=bt.TimeFrame.Minutes,
        compression=15,
    )
    cerebro.adddata(feed, name=f"{config['data']['symbol']}_{config['data']['timeframe']}")
    cerebro.addstrategy(KijunSenRobotStrategy, **config.get('params', {}))
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


def test_67_0067_0696_kijun_sen_robot() -> None:
    """Migrated regression test (runonce=True only).

    Originally located at tests/functional/strategies_regression/trend_following/0067_0696_kijun_sen_robot.
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

    assert metrics.get('bar_num') == 6094, f"bar_num: expected=6094, got={metrics.get('bar_num')!r}"
    assert metrics.get('buy_count') == 117, f"buy_count: expected=117, got={metrics.get('buy_count')!r}"
    assert metrics.get('sell_count') == 139, f"sell_count: expected=139, got={metrics.get('sell_count')!r}"
    assert metrics.get('total_trades') == 256, f"total_trades: expected=256, got={metrics.get('total_trades')!r}"
    assert metrics.get('trade_count') == 256, f"trade_count: expected=256, got={metrics.get('trade_count')!r}"
    assert metrics.get('won') == 128, f"won: expected=128, got={metrics.get('won')!r}"
    assert metrics.get('lost') == 128, f"lost: expected=128, got={metrics.get('lost')!r}"
    _close(metrics.get('bars_base'), 6129.0, tol=6.129000e-03, key='bars_base')
    _close(metrics.get('signal_count'), 256.0, tol=2.560000e-04, key='signal_count')
    _close(metrics.get('completed_orders'), 512.0, tol=5.120000e-04, key='completed_orders')
    _close(metrics.get('rejected_orders'), 0.0, tol=1.000000e-06, key='rejected_orders')
    _close(metrics.get('initial_cash'), 1000000.0, tol=1.000000e+00, key='initial_cash')
    _close(metrics.get('final_value'), 1004029.1999999995, tol=1.004029e+00, key='final_value')
    _close(metrics.get('net_pnl'), 4029.1999999994878, tol=4.029200e-03, key='net_pnl')
    _close(metrics.get('total_return_pct'), 0.4029199999999511, tol=1.000000e-06, key='total_return_pct')
    _close(metrics.get('win_rate'), 50.0, tol=5.000000e-05, key='win_rate')
    _close(metrics.get('profit_factor'), 1.4807712959538037, tol=1.480771e-06, key='profit_factor')
    _close(metrics.get('sharpe_ratio'), 10.727299966465877, tol=1.072730e-05, key='sharpe_ratio')
    _close(metrics.get('annual_return_pct'), 26.88078130357468, tol=2.688078e-05, key='annual_return_pct')
    _close(metrics.get('max_drawdown'), 0.16105345227830833, tol=1.000000e-06, key='max_drawdown')
    _close(metrics.get('sqn'), 1.3995100941151963, tol=1.399510e-06, key='sqn')
    _total_trades = metrics.get("total_trades") or metrics.get("trade_num") or metrics.get("trade_count") or 0
    _activity = (
        _total_trades
        or (metrics.get("buy_count") or 0)
        or (metrics.get("sell_count") or 0)
        or (metrics.get("rebalance_count") or 0)
    )
    assert _activity > 0, f"strategy must have non-zero activity, got metrics={metrics!r}"
