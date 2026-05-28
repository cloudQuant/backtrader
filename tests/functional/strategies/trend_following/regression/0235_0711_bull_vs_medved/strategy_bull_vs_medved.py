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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


class BullVsMedvedStrategy(bt.Strategy):
    params = dict(
        lots=0.10,
        candle_size=75,
        stop_loss=60,
        take_profit=60,
        indent_up=16,
        indent_down=20,
        start_times=('00:05', '04:05', '08:05', '12:05', '16:05', '20:05'),
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
        pending_life_minutes=240,
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
        self.pending_side = None
        self.pending_price = None
        self.pending_expiry = None

        self.start_slots = set(self.p.start_times)

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _slot_match(self):
        dt = bt.num2date(self.data.datetime[0])
        return dt.strftime('%H:%M') in self.start_slots

    def _is_bull(self):
        return float(self.data.close[-3]) > float(self.data.open[-2]) and (float(self.data.close[-2]) - float(self.data.open[-2]) >= 10 * self._unit()) and (float(self.data.close[-1]) - float(self.data.open[-1]) >= float(self.p.candle_size) * self._unit())

    def _is_bad_bull(self):
        return (float(self.data.close[-3]) - float(self.data.open[-3]) >= 10 * self._unit()) and (float(self.data.close[-2]) - float(self.data.open[-2]) >= 10 * self._unit()) and (float(self.data.close[-1]) - float(self.data.open[-1]) >= 10 * self._unit())

    def _is_cool_bull(self):
        return (float(self.data.open[-2]) - float(self.data.close[-2]) >= 20 * self._unit()) and (float(self.data.close[-2]) <= float(self.data.open[-1])) and (float(self.data.close[-1]) - float(self.data.open[-1]) >= float(self.p.candle_size) * self._unit())

    def _is_bear(self):
        return float(self.data.open[-1]) - float(self.data.close[-1]) >= float(self.p.candle_size) * self._unit()

    def _place_pending(self, side):
        unit = self._unit()
        close = float(self.data.close[0])
        now = bt.num2date(self.data.datetime[0])
        if side == 'buy':
            self.pending_price = close
            self.stop_price = round(self.pending_price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(self.pending_price + float(self.p.take_profit) * unit, int(self.p.price_digits))
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots)
        else:
            self.pending_price = close
            self.stop_price = round(self.pending_price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(self.pending_price - float(self.p.take_profit) * unit, int(self.p.price_digits))
            self.signal_count += 1
            self.order = self.sell(size=self.p.lots)
        self.pending_expiry = now + pd.Timedelta(minutes=int(self.p.pending_life_minutes))
        self._clear_pending()

    def _clear_pending(self):
        self.pending_side = None
        self.pending_price = None
        self.pending_expiry = None

    def _manage_pending(self):
        if self.pending_side is None:
            return False
        now = bt.num2date(self.data.datetime[0])
        if self.pending_expiry is not None and now >= self.pending_expiry:
            self._clear_pending()
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.pending_side == 'buy' and low <= float(self.pending_price):
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots)
            self._clear_pending()
            return True
        if self.pending_side == 'sell' and high >= float(self.pending_price):
            self.signal_count += 1
            self.order = self.sell(size=self.p.lots)
            self._clear_pending()
            return True
        return False

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if high >= float(self.take_profit_price) or low <= float(self.stop_price):
                self.order = self.close()
                return True
        else:
            if low <= float(self.take_profit_price) or high >= float(self.stop_price):
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < 5:
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        if self._manage_pending():
            return
        if self.pending_side is not None:
            return
        if not self._slot_match():
            return
        if self._is_bull() and not self._is_bad_bull():
            self._place_pending('buy')
            return
        if self._is_cool_bull():
            self._place_pending('buy')
            return
        if self._is_bear():
            self._place_pending('sell')

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
