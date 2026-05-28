from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class VltTraderStrategy(bt.Strategy):
    params = dict(
        period=9,
        pending_level=100,
        lots=0.1,
        stop_loss=550,
        take_profit=550,
        spread_points=1.0,
        point=0.01,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.buy_entry_order = None
        self.sell_entry_order = None
        self.exit_order = None
        self.entry_type = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False

        self.addminperiod(int(self.p.period) + 5)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_prev_bar(self):
        current_range = float(self.data.high[-1]) - float(self.data.low[-1])
        prior_ranges = [float(self.data.high[-i]) - float(self.data.low[-i]) for i in range(2, int(self.p.period) + 2)]
        min_prior = min(prior_ranges)
        prev_prev_range = float(self.data.high[-2]) - float(self.data.low[-2])
        prev_prev_prior = [float(self.data.high[-i]) - float(self.data.low[-i]) for i in range(3, int(self.p.period) + 3)]
        prev_prev_min = min(prev_prev_prior)
        return current_range < min_prior and not (prev_prev_range < prev_prev_min)

    def _cancel_pending_entries(self):
        if self.buy_entry_order is not None:
            self.cancel(self.buy_entry_order)
            self.buy_entry_order = None
        if self.sell_entry_order is not None:
            self.cancel(self.sell_entry_order)
            self.sell_entry_order = None

    def _check_exit_levels(self):
        if not self.position or self.exit_order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.exit_order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.exit_order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.exit_order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.exit_order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1

        if self._check_exit_levels():
            return

        if self.position:
            if self.buy_entry_order is not None or self.sell_entry_order is not None:
                self._cancel_pending_entries()
            return

        if self.buy_entry_order is not None or self.sell_entry_order is not None:
            return

        if not self._signal_prev_bar():
            return

        self.signal_count += 1
        prev_high = float(self.data.high[-1])
        prev_low = float(self.data.low[-1])
        buy_stop = prev_high + float(self.p.point) * (float(self.p.pending_level) + float(self.p.spread_points))
        sell_stop = prev_low - float(self.p.point) * float(self.p.pending_level)
        lot = max(round(float(self.p.lots), 2), 0.01)

        self.log(f'place paired stops buy_stop={buy_stop:.5f} sell_stop={sell_stop:.5f} lot={lot:.2f}')
        self.buy_entry_order = self.buy(exectype=bt.Order.Stop, price=buy_stop, size=lot)
        self.sell_entry_order = self.sell(exectype=bt.Order.Stop, price=sell_stop, size=lot)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order is self.buy_entry_order:
                self.entry_type = 'buy'
                entry_price = float(order.executed.price)
                self.stop_price = entry_price - float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
                self.take_price = entry_price + float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
                self.log(f'buy stop filled price={entry_price:.5f}')
                if self.sell_entry_order is not None:
                    self.cancel(self.sell_entry_order)
                self.buy_entry_order = None
                return
            if order is self.sell_entry_order:
                self.entry_type = 'sell'
                entry_price = float(order.executed.price)
                self.stop_price = entry_price + float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
                self.take_price = entry_price - float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
                self.log(f'sell stop filled price={entry_price:.5f}')
                if self.buy_entry_order is not None:
                    self.cancel(self.buy_entry_order)
                self.sell_entry_order = None
                return
            if order is self.exit_order:
                self.exit_order = None
                return

        if order.status in [order.Canceled, order.Margin, order.Rejected, order.Expired]:
            if order is self.buy_entry_order:
                self.buy_entry_order = None
            elif order is self.sell_entry_order:
                self.sell_entry_order = None
            elif order is self.exit_order:
                self.exit_order = None
            self.log(f'order cleared status={order.getstatusname()}')

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
        self.stop_price = None
        self.take_price = None
        self.entry_type = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
