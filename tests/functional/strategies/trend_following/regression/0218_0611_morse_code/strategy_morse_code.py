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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


def mask_to_pattern(mask_int):
    """Convert integer mask to binary pattern string like the MQL5 enum.

    The MQL5 EA maps enum values 0..61 to binary strings.
    E.g. 0->'0', 1->'1', 2->'00', 3->'01', 4->'10', 5->'11',
         6->'000', ... etc.
    We replicate this mapping.
    """
    mapping = {}
    idx = 0
    for length in range(1, 6):
        for val in range(2 ** length):
            mapping[idx] = format(val, f'0{length}b')
            idx += 1
    return mapping.get(mask_int, '0')


class MorseCodeStrategy(bt.Strategy):
    """Morse Code candle pattern strategy (EA 0611).

    Trades when the last N completed bars match a binary pattern.
    '1' = bullish (close > open), '0' = bearish (close < open).
    Direction (buy or sell) is fixed by parameter.
    Fixed SL and TP.
    """

    params = dict(
        pattern_mask=0,
        pos_type='buy',
        take_profit=50,
        stop_loss=50,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
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
        self.pattern = mask_to_pattern(int(self.p.pattern_mask))

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _pattern_match(self):
        n = len(self.pattern)
        if len(self) < n + 2:
            return False
        for i in range(n):
            bar_idx = -(n - i)
            o = float(self.data.open[bar_idx])
            c = float(self.data.close[bar_idx])
            if self.pattern[i] == '1':
                if o >= c:
                    return False
            else:
                if o <= c:
                    return False
        return True

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self.position:
            self._check_exit()
            return

        if self._pattern_match():
            self.signal_count += 1
            price = float(self.data.close[0])
            sl_dist = float(self.p.stop_loss) * self._point()
            tp_dist = float(self.p.take_profit) * self._point()
            if self.p.pos_type == 'buy':
                self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
                self.take_profit_price = self._round(price + tp_dist) if tp_dist > 0 else None
                self.order = self.buy(size=self.p.lots)
            else:
                self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
                self.take_profit_price = self._round(price - tp_dist) if tp_dist > 0 else None
                self.order = self.sell(size=self.p.lots)

    def _check_exit(self):
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        elif self.position.size < 0:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def notify_order(self, order):
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
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
