from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class SSB5123Strategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        ma_period=45,
        macd_fast_period=47,
        macd_slow_period=95,
        macd_signal_period=74,
        sto_kperiod=25,
        sto_dperiod=12,
        sto_slowing=56,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.smma = bt.indicators.SmoothedMovingAverage(self.data0_feed.close, period=self.p.ma_period)
        self.macd = bt.indicators.MACD(
            self.data0_feed.close,
            period_me1=self.p.macd_fast_period,
            period_me2=self.p.macd_slow_period,
            period_signal=self.p.macd_signal_period,
        )
        self.stochastic = bt.indicators.Stochastic(
            self.data0_feed,
            period=self.p.sto_kperiod,
            period_dfast=self.p.sto_dperiod,
            period_dslow=self.p.sto_slowing,
            movav=bt.indicators.SimpleMovingAverage,
        )
        self.osma = self.macd.macd - self.macd.signal
        self.ao = bt.indicators.AwesomeOscillator(self.data0_feed)
        self.entry_order = None
        self.close_order = None
        self.pending_reverse = None
        self.active_side = None
        self.closing_side = None
        self.last_bar_dt = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    @staticmethod
    def _sign(value):
        if value > 0:
            return 1
        if value < 0:
            return -1
        return 0

    def _fcandle(self):
        return self._sign(float(self.data0_feed.open[-1]) - float(self.data0_feed.open[0]))

    def _fao(self):
        return self._sign(float(self.ao[0]))

    def _fao1(self):
        return self._sign(float(self.ao[-1]) - float(self.ao[0]))

    def _fmacd(self):
        return self._sign(float(self.macd.macd[0]))

    def _fmacd1(self):
        return self._sign(float(self.macd.macd[0]) - float(self.macd.macd[-1]))

    def _fosma1(self):
        return self._sign(float(self.osma[-1]) - float(self.osma[0]))

    def _fsmma(self):
        return self._sign(float(self.data0_feed.open[0]) - float(self.smma[0]))

    def _fstoch1(self):
        return self._sign(float(self.stochastic.percK[0]) - 50.0)

    def _fstoch2(self):
        return self._sign(float(self.stochastic.percD[0]) - 50.0)

    def _long_signal(self):
        checks = [self._fcandle(), self._fao(), self._fao1(), self._fmacd(), self._fmacd1(), self._fosma1(), self._fsmma(), self._fstoch1(), self._fstoch2()]
        return all(value >= 0 for value in checks)

    def _short_signal(self):
        checks = [self._fcandle(), self._fao(), self._fao1(), self._fmacd(), self._fmacd1(), self._fosma1(), self._fsmma(), self._fstoch1(), self._fstoch2()]
        return all(value <= 0 for value in checks)

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        if side == 'long':
            self.entry_order = self.buy(size=size)
        else:
            self.entry_order = self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.closing_side = self.active_side
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        min_bars = max(self.p.macd_slow_period + self.p.macd_signal_period + 5, self.p.sto_kperiod + self.p.sto_dperiod + self.p.sto_slowing + 5, self.p.ma_period + 5)
        if len(self.data0_feed) < min_bars:
            return
        if not self._new_bar():
            return
        longsignal = self._long_signal()
        shortsignal = self._short_signal()
        if self.position.size > 0 and shortsignal:
            self._submit_close('short signal', reverse='short')
            return
        if self.position.size < 0 and longsignal:
            self._submit_close('long signal', reverse='long')
            return
        if not self.position and self.pending_reverse and self.entry_order is None and self.close_order is None:
            side = self.pending_reverse
            self.pending_reverse = None
            self._submit_entry(side, 'reverse after close')
            return
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        if longsignal:
            self._submit_entry('long', 'all indicators positive')
        elif shortsignal:
            self._submit_entry('short', 'all indicators negative')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                reverse = self.pending_reverse
                self.pending_reverse = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_reverse = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.closing_side or self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.closing_side = None
