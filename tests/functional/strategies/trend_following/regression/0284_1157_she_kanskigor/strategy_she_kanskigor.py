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


class SheKanskigorStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        profit=350,
        stop=550,
        start_time_hour=0,
        start_time_minute=5,
        point=0.01,
    )

    def __init__(self):
        self.data_intraday = self.datas[0]
        self.data_daily = self.datas[1]

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
        self._traded_day = None

        self.addminperiod(3)

    def log(self, text):
        dt = bt.num2date(self.data_intraday.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _within_open_window(self):
        dt = bt.num2date(self.data_intraday.datetime[0])
        minutes = dt.hour * 60 + dt.minute
        start = int(self.p.start_time_hour) * 60 + int(self.p.start_time_minute)
        return start <= minutes <= start + 5

    def _daily_bias(self):
        if len(self.data_daily) < 2:
            return 0
        close_prev = float(self.data_daily.close[-1])
        open_prev = float(self.data_daily.open[-1])
        if close_prev > open_prev:
            return -1
        if close_prev < open_prev:
            return 1
        return 0

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data_intraday.high[0])
        low = float(self.data_intraday.low[0])
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
        if len(self.data_daily) < 2:
            return
        self.bar_num += 1
        if self.order is not None:
            return

        if self._check_exit_levels():
            return
        if self.position:
            return
        if not self._within_open_window():
            return

        dt = bt.num2date(self.data_intraday.datetime[0]).date()
        if self._traded_day == dt:
            return

        bias = self._daily_bias()
        lot = max(round(float(self.p.lots), 2), 0.01)

        if bias == 1:
            self.signal_count += 1
            ask = float(self.data_intraday.close[0])
            self.stop_price = ask - float(self.p.point) * float(self.p.stop) if int(self.p.stop) > 0 else None
            self.take_price = ask + float(self.p.point) * float(self.p.profit) if int(self.p.profit) > 0 else None
            self._traded_day = dt
            self.log(f'buy by opposite daily candle lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if bias == -1:
            self.signal_count += 1
            bid = float(self.data_intraday.close[0])
            self.stop_price = bid + float(self.p.point) * float(self.p.stop) if int(self.p.stop) > 0 else None
            self.take_price = bid - float(self.p.point) * float(self.p.profit) if int(self.p.profit) > 0 else None
            self._traded_day = dt
            self.log(f'sell by opposite daily candle lot={lot:.2f}')
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
