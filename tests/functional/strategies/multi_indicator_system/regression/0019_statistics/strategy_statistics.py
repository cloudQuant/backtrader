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


class StatisticsStrategy(bt.Strategy):
    """Historical bar statistics strategy (EA 0605).

    On each new bar:
      1. Close any existing position.
      2. Look back N days of history for bars with the same hour:minute.
      3. Sum bull candle sizes vs bear candle sizes.
      4. If bull > bear -> buy; if bear > bull -> sell.
      5. Fixed SL, no TP.
      6. After a losing trade, increase lot by martin ratio.
    """

    params = dict(
        candle_height=10,
        lots=0.1,
        stop_loss=15,
        days_of_history=10,
        martin=1.618,
        point=0.01,
        price_digits=2,
        timeframe_minutes=15,
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
        self.current_lots = float(self.p.lots)
        self.stop_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self.position:
            self.order = self.close()
            return

        current_dt = self.data.datetime.datetime(0)
        target_hour = current_dt.hour
        target_minute = current_dt.minute

        bull_size = 0.0
        bear_size = 0.0
        bars_per_day = int(24 * 60 / max(int(self.p.timeframe_minutes), 1))
        lookback = int(self.p.days_of_history) * bars_per_day

        for i in range(1, min(lookback + 1, len(self))):
            bar_dt = self.data.datetime.datetime(-i)
            if bar_dt.hour == target_hour and bar_dt.minute == target_minute:
                o = float(self.data.open[-i])
                c = float(self.data.close[-i])
                size = c - o
                if size == 0:
                    continue
                abs_size = abs(size)
                if int(self.p.candle_height) > 0 and abs_size / self._point() < int(self.p.candle_height):
                    continue
                if size > 0:
                    bull_size += abs_size
                else:
                    bear_size += abs_size

        if bull_size == 0 and bear_size == 0:
            return

        sl_dist = float(self.p.stop_loss) * self._point()

        if bull_size > bear_size:
            self.signal_count += 1
            price = float(self.data.close[0])
            self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
            self.order = self.buy(size=self.current_lots)
        elif bear_size > bull_size:
            self.signal_count += 1
            price = float(self.data.close[0])
            self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
            self.order = self.sell(size=self.current_lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if order.executed.size > 0:
                self.buy_count += 1
            elif order.executed.size < 0:
                self.sell_count += 1
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
            self.current_lots = float(self.p.lots)
        else:
            self.loss_count += 1
            self.current_lots = float(self.p.lots) * float(self.p.martin)
