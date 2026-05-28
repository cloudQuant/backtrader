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


class ATRTrailingStrategy(bt.Strategy):
    """
    ATR Trailing Stop strategy.
    Uses ATR to build a channel around price.
    Upper trail = close + sell_factor * ATR
    Lower trail = close - buy_factor * ATR
    Buy: price crosses above upper trail (breakout up)
    Sell: price crosses below lower trail (breakout down)
    Trailing stops move with new bars.
    """
    params = dict(
        atr_period=14,
        buy_factor=2.0,
        sell_factor=2.0,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._trail_stop = None
        self._trail_dir = 0  # 1=long, -1=short

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.atr_period + 5:
            return

        close = float(self.data.close[0])
        atr_val = float(self.atr[0])
        upper = close + self.p.sell_factor * atr_val
        lower = close - self.p.buy_factor * atr_val

        if self.position:
            if self.position.size > 0:
                new_stop = close - self.p.buy_factor * atr_val
                if self._trail_stop is None or new_stop > self._trail_stop:
                    self._trail_stop = new_stop
                if close < self._trail_stop:
                    self.log(f'trail stop long hit close={close:.2f} stop={self._trail_stop:.2f}')
                    self.close()
                    self._trail_stop = None
                    self._trail_dir = 0
                    self.sell(size=self.p.lot)
                    self._trail_stop = close + self.p.sell_factor * atr_val
                    self._trail_dir = -1
                    return
            elif self.position.size < 0:
                new_stop = close + self.p.sell_factor * atr_val
                if self._trail_stop is None or new_stop < self._trail_stop:
                    self._trail_stop = new_stop
                if close > self._trail_stop:
                    self.log(f'trail stop short hit close={close:.2f} stop={self._trail_stop:.2f}')
                    self.close()
                    self._trail_stop = None
                    self._trail_dir = 0
                    self.buy(size=self.p.lot)
                    self._trail_stop = close - self.p.buy_factor * atr_val
                    self._trail_dir = 1
                    return
        else:
            prev_close = float(self.data.close[-1])
            prev_atr = float(self.atr[-1])
            prev_upper = prev_close + self.p.sell_factor * prev_atr
            prev_lower = prev_close - self.p.buy_factor * prev_atr
            if close > prev_upper:
                self.log(f'buy breakout close={close:.2f} atr={atr_val:.2f}')
                self.buy(size=self.p.lot)
                self._trail_stop = lower
                self._trail_dir = 1
                return
            if close < prev_lower:
                self.log(f'sell breakout close={close:.2f} atr={atr_val:.2f}')
                self.sell(size=self.p.lot)
                self._trail_stop = upper
                self._trail_dir = -1
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
