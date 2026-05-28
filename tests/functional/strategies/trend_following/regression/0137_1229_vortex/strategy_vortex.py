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


class VortexIndicator(bt.Indicator):
    """
    Vortex Indicator (VI+ and VI-).
    VM+ = |High[0] - Low[-1]|
    VM- = |Low[0] - High[-1]|
    TR  = max(High-Low, |High-Close[-1]|, |Low-Close[-1]|)
    VI+ = sum(VM+, period) / sum(TR, period)
    VI- = sum(VM-, period) / sum(TR, period)
    """
    lines = ('vi_plus', 'vi_minus',)
    params = (('period', 14),)

    def __init__(self):
        pass

    def next(self):
        p = self.p.period
        if len(self.data) < p + 2:
            self.lines.vi_plus[0] = 0.0
            self.lines.vi_minus[0] = 0.0
            return

        vm_plus_sum = 0.0
        vm_minus_sum = 0.0
        tr_sum = 0.0
        for i in range(p):
            idx = -i
            idx_prev = idx - 1
            h = float(self.data.high[idx])
            l = float(self.data.low[idx])
            h_prev = float(self.data.high[idx_prev])
            l_prev = float(self.data.low[idx_prev])
            c_prev = float(self.data.close[idx_prev])

            vm_plus_sum += abs(h - l_prev)
            vm_minus_sum += abs(l - h_prev)
            tr_sum += max(h - l, abs(h - c_prev), abs(l - c_prev))

        if tr_sum > 0:
            self.lines.vi_plus[0] = vm_plus_sum / tr_sum
            self.lines.vi_minus[0] = vm_minus_sum / tr_sum
        else:
            self.lines.vi_plus[0] = 0.0
            self.lines.vi_minus[0] = 0.0


class VortexStrategy(bt.Strategy):
    """
    Vortex Indicator strategy.
    Buy: VI+ crosses above VI- (bullish cloud color change)
    Sell: VI- crosses above VI+ (bearish cloud color change)
    """
    params = dict(
        vortex_period=14,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.vortex = VortexIndicator(self.data, period=self.p.vortex_period)
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

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.vortex_period + 5:
            return

        vip0 = float(self.vortex.vi_plus[0])
        vim0 = float(self.vortex.vi_minus[0])
        vip1 = float(self.vortex.vi_plus[-1])
        vim1 = float(self.vortex.vi_minus[-1])

        bull_cross = vip1 < vim1 and vip0 > vim0
        bear_cross = vip1 > vim1 and vip0 < vim0

        if self.position:
            if self.position.size > 0 and bear_cross:
                self.log(f'close long & sell vi+={vip0:.3f} vi-={vim0:.3f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            elif self.position.size < 0 and bull_cross:
                self.log(f'close short & buy vi+={vip0:.3f} vi-={vim0:.3f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if bull_cross:
                self.log(f'buy vi+={vip0:.3f} vi-={vim0:.3f}')
                self.buy(size=self.p.lot)
                return
            if bear_cross:
                self.log(f'sell vi+={vip0:.3f} vi-={vim0:.3f}')
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
