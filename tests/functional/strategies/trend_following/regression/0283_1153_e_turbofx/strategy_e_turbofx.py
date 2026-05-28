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


class ETurboFxStrategy(bt.Strategy):
    params = dict(
        n=3,
        lots=0.1,
        stop_loss=700,
        take_profit=1200,
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

        self.order = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False

        self.addminperiod(int(self.p.n) + 2)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_counts(self):
        n = int(self.p.n)
        bars = []
        for offset in range(n, 0, -1):
            bars.append((float(self.data.open[-offset]), float(self.data.close[-offset])))

        up_1 = 0
        dn_1 = 0
        for open_i, close_i in bars:
            if close_i < open_i:
                up_1 += 1
            if close_i > open_i:
                dn_1 += 1

        up_2 = 0
        dn_2 = 0
        for i in range(1, n):
            body_prev = abs(bars[i - 1][1] - bars[i - 1][0])
            body_curr = abs(bars[i][1] - bars[i][0])
            if body_curr > body_prev:
                up_2 += 1
                dn_2 += 1
        return up_1, dn_1, up_2, dn_2

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self._check_exit_levels():
            return
        if self.position:
            return

        up_1, dn_1, up_2, dn_2 = self._signal_counts()
        n = int(self.p.n)
        open_buy = up_1 == n and up_2 == n - 1
        open_sell = dn_1 == n and dn_2 == n - 1
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1
        lot = max(round(float(self.p.lots), 2), 0.01)
        px = float(self.data.close[0])

        if open_buy and not open_sell:
            self.stop_price = px - float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px + float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'buy signal up_1={up_1} up_2={up_2} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy:
            self.stop_price = px + float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px - float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'sell signal dn_1={dn_1} dn_2={dn_2} lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        self.order = None

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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
