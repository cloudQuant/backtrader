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
        tp = (self.data.high + self.data.low + self.data.close) / 3.0
        self.tp = tp
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


class ThreeCrowsSoldiersMFIStrategy(bt.Strategy):
    """
    3 Black Crows / 3 White Soldiers + MFI confirmation.

    Open long: 3 White Soldiers AND MFI < 40
    Close long: MFI crosses up through 30 or up through 70
    Open short: 3 Black Crows AND MFI > 60
    Close short: MFI crosses down through 70 or down through 30
    """
    params = dict(
        mfi_period=37,
        ma_period=13,
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
        count = min(self.p.ma_period, len(self.data) - 1)
        if count <= 0:
            return 0.0
        for i in range(-count, 0):
            total += abs(float(self.data.close[i]) - float(self.data.open[i]))
        return total / count

    def _mid_point(self, idx):
        return (float(self.data.high[idx]) + float(self.data.low[idx])) / 2.0

    def _three_white_soldiers(self):
        if len(self.data) < 4:
            return False
        avg = self._avg_body()
        if avg <= 0:
            return False
        return (
            (float(self.data.close[-3]) - float(self.data.open[-3]) > avg) and
            (float(self.data.close[-2]) - float(self.data.open[-2]) > avg) and
            (float(self.data.close[-1]) - float(self.data.open[-1]) > avg) and
            (self._mid_point(-2) > self._mid_point(-3)) and
            (self._mid_point(-1) > self._mid_point(-2))
        )

    def _three_black_crows(self):
        if len(self.data) < 4:
            return False
        avg = self._avg_body()
        if avg <= 0:
            return False
        return (
            (float(self.data.open[-3]) - float(self.data.close[-3]) > avg) and
            (float(self.data.open[-2]) - float(self.data.close[-2]) > avg) and
            (float(self.data.open[-1]) - float(self.data.close[-1]) > avg) and
            (self._mid_point(-2) < self._mid_point(-3)) and
            (self._mid_point(-1) < self._mid_point(-2))
        )

    def next(self):
        self.bar_num += 1
        if len(self.data) < max(self.p.mfi_period, self.p.ma_period) + 5:
            return

        mfi_1 = float(self.mfi.mfi[-1])
        mfi_2 = float(self.mfi.mfi[-2]) if len(self.mfi.mfi) > 2 else mfi_1

        if self.position:
            if self.position.size > 0:
                if ((mfi_1 > 30 and mfi_2 < 30) or (mfi_1 > 70 and mfi_2 < 70)):
                    self.log(f'close long mfi={mfi_1:.2f}')
                    self.close()
                    return
            elif self.position.size < 0:
                if ((mfi_1 > 70 and mfi_2 < 70) or (mfi_1 < 30 and mfi_2 > 30)):
                    self.log(f'close short mfi={mfi_1:.2f}')
                    self.close()
                    return
        else:
            if self._three_white_soldiers() and mfi_1 < 40:
                self.log(f'buy signal price={self.data.close[0]:.2f} mfi={mfi_1:.2f}')
                self.buy(size=self.p.lot)
                return
            if self._three_black_crows() and mfi_1 > 60:
                self.log(f'sell signal price={self.data.close[0]:.2f} mfi={mfi_1:.2f}')
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
