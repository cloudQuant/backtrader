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


class EnvelopesJpAlonso(bt.Indicator):
    lines = ('mid', 'upper', 'lower')
    params = dict(period=200, deviation=0.35)

    def __init__(self):
        self.lines.mid = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.period)
        ratio = float(self.p.deviation) / 100.0
        self.lines.upper = self.lines.mid * (1.0 + ratio)
        self.lines.lower = self.lines.mid * (1.0 - ratio)


class JpAlonsoModokiStrategy(bt.Strategy):
    params = dict(
        signal_threshold_open=10,
        signal_threshold_close=10,
        signal_stop_level=77.0,
        signal_take_level=127.0,
        envelopes_period=200,
        envelopes_deviation=0.35,
        lots=5.0,
        point=0.01,
        start_after='2012-10-08 10:55:00',
    )

    def __init__(self):
        self.envs = EnvelopesJpAlonso(self.data, period=self.p.envelopes_period, deviation=self.p.envelopes_deviation)
        self.order = None
        self.stop_price = None
        self.take_price = None
        self.start_after = pd.Timestamp(self.p.start_after)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

        self.addminperiod(self.p.envelopes_period + 5)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _long_vote(self):
        close = float(self.data.close[0])
        upper = float(self.envs.upper[0])
        lower = float(self.envs.lower[0])
        mid = lower + (upper - lower) / 2.0
        return 100 if (close <= lower or (close < upper and close > mid)) else 0

    def _short_vote(self):
        close = float(self.data.close[0])
        upper = float(self.envs.upper[0])
        lower = float(self.envs.lower[0])
        mid = lower + (upper - lower) / 2.0
        return 100 if (close >= upper or (close > lower and close < mid)) else 0

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

        now = pd.Timestamp(bt.num2date(self.data.datetime[0]))
        if now < self.start_after:
            return

        long_vote = self._long_vote()
        short_vote = self._short_vote()
        lot = max(round(float(self.p.lots), 2), 0.01)
        px = float(self.data.close[0])

        if long_vote >= int(self.p.signal_threshold_open) and short_vote < int(self.p.signal_threshold_open):
            self.signal_count += 1
            self.stop_price = px - float(self.p.signal_stop_level) * float(self.p.point) if float(self.p.signal_stop_level) > 0 else None
            self.take_price = px + float(self.p.signal_take_level) * float(self.p.point) if float(self.p.signal_take_level) > 0 else None
            self.log(f'buy long_vote={long_vote} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return
        if short_vote >= int(self.p.signal_threshold_open) and long_vote < int(self.p.signal_threshold_open):
            self.signal_count += 1
            self.stop_price = px + float(self.p.signal_stop_level) * float(self.p.point) if float(self.p.signal_stop_level) > 0 else None
            self.take_price = px - float(self.p.signal_take_level) * float(self.p.point) if float(self.p.signal_take_level) > 0 else None
            self.log(f'sell short_vote={short_vote} lot={lot:.2f}')
            self.order = self.sell(size=lot)

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
