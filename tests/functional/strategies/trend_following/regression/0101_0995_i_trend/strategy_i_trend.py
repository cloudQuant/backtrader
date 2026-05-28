from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


def get_price_line(data, price_mode):
    mode = str(price_mode).lower()
    if mode in ('close', 'price_close', 'price_close_'):
        return data.close
    if mode in ('open', 'price_open', 'price_open_'):
        return data.open
    if mode in ('high', 'price_high', 'price_high_'):
        return data.high
    if mode in ('low', 'price_low', 'price_low_'):
        return data.low
    if mode in ('median', 'price_median', 'price_median_'):
        return (data.high + data.low) / 2.0
    if mode in ('typical', 'price_typical', 'price_typical_'):
        return (data.high + data.low + data.close) / 3.0
    if mode in ('weighted', 'price_weighted', 'price_weighted_'):
        return (data.high + data.low + data.close + data.close) / 4.0
    raise ValueError(f'Unsupported price mode: {price_mode}')


def build_ma(price_line, period, ma_type):
    mode = str(ma_type).upper()
    mapping = {
        'MODE_SMA': bt.indicators.SimpleMovingAverage,
        'SMA': bt.indicators.SimpleMovingAverage,
        'MODE_EMA': bt.indicators.ExponentialMovingAverage,
        'EMA': bt.indicators.ExponentialMovingAverage,
        'MODE_SMMA': bt.indicators.SmoothedMovingAverage,
        'SMMA': bt.indicators.SmoothedMovingAverage,
        'MODE_LWMA': bt.indicators.WeightedMovingAverage,
        'LWMA': bt.indicators.WeightedMovingAverage,
    }
    if mode not in mapping:
        raise ValueError(f'Unsupported ma_type: {ma_type}')
    return mapping[mode](price_line, period=period)


class ITrendIndicator(Indicator):
    lines = ('primary', 'signal')
    params = dict(
        price_type='close',
        ma_period=13,
        ma_type='EMA',
        ma_price='close',
        bb_period=20,
        deviation=2.0,
        bb_price='close',
        bb_mode=0,
    )

    def __init__(self):
        price_type_line = get_price_line(self.data, self.p.price_type)
        ma_price_line = get_price_line(self.data, self.p.ma_price)
        bb_price_line = get_price_line(self.data, self.p.bb_price)
        ma = build_ma(ma_price_line, int(self.p.ma_period), self.p.ma_type)
        bands = bt.indicators.BollingerBands(bb_price_line, period=int(self.p.bb_period), devfactor=float(self.p.deviation))
        mode = int(self.p.bb_mode)
        if mode == 0:
            band_line = bands.mid
        elif mode == 1:
            band_line = bands.top
        elif mode == 2:
            band_line = bands.bot
        else:
            raise ValueError(f'Unsupported bb_mode: {self.p.bb_mode}')
        self.l.primary = price_type_line - band_line
        self.l.signal = (ma * 2.0) - self.data.low - self.data.high
        self.addminperiod(max(int(self.p.ma_period), int(self.p.bb_period)) + 5)


class ITrendStrategy(Strategy):
    params = dict(
        signal_bar=1,
        price_type='close',
        ma_period=13,
        ma_type='EMA',
        ma_price='close',
        bb_period=20,
        deviation=2.0,
        bb_price='close',
        bb_mode=0,
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
        self.indicator = ITrendIndicator(
            self.data,
            price_type=self.p.price_type,
            ma_period=self.p.ma_period,
            ma_type=self.p.ma_type,
            ma_price=self.p.ma_price,
            bb_period=self.p.bb_period,
            deviation=self.p.deviation,
            bb_price=self.p.bb_price,
            bb_mode=self.p.bb_mode,
        )
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
        self.warmup = max(int(self.p.ma_period), int(self.p.bb_period)) + max(int(self.p.signal_bar), 1) + 5

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _get_signals(self):
        shift = max(int(self.p.signal_bar), 1)
        ind_now = float(self.indicator.primary[-shift])
        ind_prev = float(self.indicator.primary[-(shift + 1)])
        sig_now = float(self.indicator.signal[-shift])
        sig_prev = float(self.indicator.signal[-(shift + 1)])
        buy_open = self.p.buy_pos_open and ind_prev > sig_prev and ind_now <= sig_now
        sell_open = self.p.sell_pos_open and ind_prev < sig_prev and ind_now >= sig_now
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
                    self._close_long('close long on i_Trend bearish crossover')
                    if sell_open:
                        self._open_short()
                    return
            else:
                if sell_close:
                    self._close_short('close short on i_Trend bullish crossover')
                    if buy_open:
                        self._open_long()
                    return
        else:
            if buy_open:
                self.log('buy on i_Trend bullish crossover')
                self._open_long()
                return
            if sell_open:
                self.log('sell on i_Trend bearish crossover')
                self._open_short()
                return

    def notify_order(self, order):
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
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
