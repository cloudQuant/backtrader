from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
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
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TwoEMATimeFilterStrategy(bt.Strategy):
    """
    Two EMA crossover with intraday time filter.
    Buy: Fast EMA crosses above Slow EMA during allowed trading hours
    Sell: Fast EMA crosses below Slow EMA during allowed trading hours
    Exit: via ATR-based stop loss and take profit
    """
    params = dict(
        fast_period=12,
        slow_period=26,
        atr_period=14,
        sl_atr_mult=3.0,
        tp_atr_mult=5.0,
        trade_start_hour=0,
        trade_end_hour=6,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.fast_ema = bt.indicators.EMA(self.data.close, period=self.p.fast_period)
        self.slow_ema = bt.indicators.EMA(self.data.close, period=self.p.slow_period)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._sl_price = None
        self._tp_price = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _in_trading_hours(self):
        dt = bt.num2date(self.data.datetime[0])
        h = dt.hour
        if self.p.trade_start_hour <= self.p.trade_end_hour:
            return self.p.trade_start_hour <= h < self.p.trade_end_hour
        else:
            return h >= self.p.trade_start_hour or h < self.p.trade_end_hour

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.slow_period + 5:
            return

        diff1 = float(self.fast_ema[-1]) - float(self.slow_ema[-1])
        diff2 = float(self.fast_ema[-2]) - float(self.slow_ema[-2])
        atr_val = float(self.atr[0])

        buy_cross = diff2 < 0 and diff1 > 0
        sell_cross = diff2 > 0 and diff1 < 0

        if self.position:
            price = float(self.data.close[0])
            if self.position.size > 0:
                if self._sl_price and price <= self._sl_price:
                    self.log(f'SL hit long price={price:.2f}')
                    self.close()
                    self._sl_price = None
                    self._tp_price = None
                    return
                if self._tp_price and price >= self._tp_price:
                    self.log(f'TP hit long price={price:.2f}')
                    self.close()
                    self._sl_price = None
                    self._tp_price = None
                    return
                if sell_cross:
                    self.log(f'cross exit long & sell price={price:.2f}')
                    self.close()
                    self._sl_price = None
                    self._tp_price = None
                    if self._in_trading_hours():
                        self.sell(size=self.p.lot)
                        self._sl_price = price + self.p.sl_atr_mult * atr_val
                        self._tp_price = price - self.p.tp_atr_mult * atr_val
                    return
            elif self.position.size < 0:
                if self._sl_price and price >= self._sl_price:
                    self.log(f'SL hit short price={price:.2f}')
                    self.close()
                    self._sl_price = None
                    self._tp_price = None
                    return
                if self._tp_price and price <= self._tp_price:
                    self.log(f'TP hit short price={price:.2f}')
                    self.close()
                    self._sl_price = None
                    self._tp_price = None
                    return
                if buy_cross:
                    self.log(f'cross exit short & buy price={price:.2f}')
                    self.close()
                    self._sl_price = None
                    self._tp_price = None
                    if self._in_trading_hours():
                        self.buy(size=self.p.lot)
                        self._sl_price = price - self.p.sl_atr_mult * atr_val
                        self._tp_price = price + self.p.tp_atr_mult * atr_val
                    return
        else:
            if not self._in_trading_hours():
                return
            price = float(self.data.close[0])
            if buy_cross:
                self.log(f'buy signal price={price:.2f} atr={atr_val:.2f}')
                self.buy(size=self.p.lot)
                self._sl_price = price - self.p.sl_atr_mult * atr_val
                self._tp_price = price + self.p.tp_atr_mult * atr_val
                return
            if sell_cross:
                self.log(f'sell signal price={price:.2f} atr={atr_val:.2f}')
                self.sell(size=self.p.lot)
                self._sl_price = price + self.p.sl_atr_mult * atr_val
                self._tp_price = price - self.p.tp_atr_mult * atr_val
                return

    def notify_trade(self, trade):
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
