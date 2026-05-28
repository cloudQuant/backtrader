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


class MFI(bt.Indicator):
    """Money Flow Index indicator."""
    lines = ('mfi',)
    params = (('period', 14),)

    def __init__(self):
        self.addminperiod(self.p.period + 1)

    def next(self):
        period = self.p.period
        pos_flow = 0.0
        neg_flow = 0.0
        for i in range(-period, 0):
            tp_cur = (float(self.data.high[i]) + float(self.data.low[i]) + float(self.data.close[i])) / 3.0
            tp_prev = (float(self.data.high[i - 1]) + float(self.data.low[i - 1]) + float(self.data.close[i - 1])) / 3.0
            mf = tp_cur * float(self.data.volume[i])
            if tp_cur > tp_prev:
                pos_flow += mf
            elif tp_cur < tp_prev:
                neg_flow += mf
        if neg_flow == 0:
            self.lines.mfi[0] = 100.0
        else:
            ratio = pos_flow / neg_flow
            self.lines.mfi[0] = 100.0 - 100.0 / (1.0 + ratio)


class EngulfingMFIStrategy(bt.Strategy):
    """
    Bullish/Bearish Engulfing + MFI confirmation.
    Buy: Bullish engulfing pattern + MFI<40
    Sell: Bearish engulfing pattern + MFI>60
    Exit: MFI crosses critical levels (30/70)
    """
    params = dict(
        mfi_period=14,
        ma_period=5,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.mfi = MFI(self.data, period=self.p.mfi_period)
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _avg_body(self):
        total = 0.0
        for i in range(-5, 0):
            total += abs(float(self.data.close[i]) - float(self.data.open[i]))
        return total / 5.0

    def _bullish_engulfing(self):
        o2 = float(self.data.open[-2])
        c2 = float(self.data.close[-2])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (o2 + c2) / 2.0
        close_avg = float(self.sma[-2])
        return (o2 > c2 and
                (c1 - o1) > avg and
                c1 > o2 and
                mid2 < close_avg and
                o1 < c2)

    def _bearish_engulfing(self):
        o2 = float(self.data.open[-2])
        c2 = float(self.data.close[-2])
        o1 = float(self.data.open[-1])
        c1 = float(self.data.close[-1])
        avg = self._avg_body()
        mid2 = (o2 + c2) / 2.0
        close_avg = float(self.sma[-2])
        return (o2 < c2 and
                (o1 - c1) > avg and
                c1 < o2 and
                mid2 > close_avg and
                o1 > c2)

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.mfi_period + 5:
            return

        mfi1 = float(self.mfi.mfi[-1])
        mfi2 = float(self.mfi.mfi[-2]) if len(self.mfi.mfi) > 2 else mfi1

        bull_eng = self._bullish_engulfing()
        bear_eng = self._bearish_engulfing()

        if self.position:
            if self.position.size > 0:
                exit_long = ((mfi1 > 70 and mfi2 < 70) or (mfi1 < 30 and mfi2 > 30))
                if exit_long or (bear_eng and mfi1 > 60):
                    self.log(f'close long mfi={mfi1:.1f}')
                    self.close()
                    if bear_eng and mfi1 > 60:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                exit_short = ((mfi1 > 30 and mfi2 < 30) or (mfi1 > 70 and mfi2 < 70))
                if exit_short or (bull_eng and mfi1 < 40):
                    self.log(f'close short mfi={mfi1:.1f}')
                    self.close()
                    if bull_eng and mfi1 < 40:
                        self.buy(size=self.p.lot)
                    return
        else:
            if bull_eng and mfi1 < 40:
                self.log(f'buy engulfing mfi={mfi1:.1f}')
                self.buy(size=self.p.lot)
                return
            if bear_eng and mfi1 > 60:
                self.log(f'sell engulfing mfi={mfi1:.1f}')
                self.sell(size=self.p.lot)
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
