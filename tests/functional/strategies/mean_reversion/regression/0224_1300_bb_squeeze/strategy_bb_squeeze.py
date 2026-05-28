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


class BBSqueezeIndicator(bt.Indicator):
    """
    Bollinger Band Squeeze: measures BB width relative to Keltner Channel.
    Histogram = close - midline of (BB + KC) / 2, colored by whether
    BB is inside KC (squeeze on) or outside (squeeze off).
    Simplified: histogram = momentum (close - SMA), signal direction by
    BB bandwidth vs KC bandwidth.
    """
    lines = ('squeeze', 'momentum',)
    params = (
        ('bb_period', 20),
        ('bb_dev', 2.0),
        ('kc_period', 20),
        ('kc_mult', 1.5),
        ('mom_period', 12),
    )

    def __init__(self):
        self.bb = bt.indicators.BollingerBands(self.data.close, period=self.p.bb_period, devfactor=self.p.bb_dev)
        self.atr = bt.indicators.ATR(self.data, period=self.p.kc_period)
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.kc_period)
        self.mom = bt.indicators.Momentum(self.data.close, period=self.p.mom_period)

    def next(self):
        bb_upper = float(self.bb.top[0])
        bb_lower = float(self.bb.bot[0])
        bb_width = bb_upper - bb_lower

        kc_upper = float(self.sma[0]) + self.p.kc_mult * float(self.atr[0])
        kc_lower = float(self.sma[0]) - self.p.kc_mult * float(self.atr[0])
        kc_width = kc_upper - kc_lower

        self.lines.squeeze[0] = 1.0 if bb_width < kc_width else -1.0
        self.lines.momentum[0] = float(self.mom[0])


class BBSqueezeStrategy(bt.Strategy):
    """
    Bollinger Band Squeeze strategy.
    Buy: Squeeze releases (BB expands outside KC) with positive momentum
    Sell: Squeeze releases with negative momentum
    Exit: When squeeze fires again (BB contracts inside KC) or momentum reverses
    """
    params = dict(
        bb_period=20,
        bb_dev=2.0,
        kc_period=20,
        kc_mult=1.5,
        mom_period=12,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.squeeze = BBSqueezeIndicator(
            self.data,
            bb_period=self.p.bb_period,
            bb_dev=self.p.bb_dev,
            kc_period=self.p.kc_period,
            kc_mult=self.p.kc_mult,
            mom_period=self.p.mom_period,
        )
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
        if len(self.data) < max(self.p.bb_period, self.p.kc_period, self.p.mom_period) + 5:
            return

        sq0 = float(self.squeeze.squeeze[0])
        sq1 = float(self.squeeze.squeeze[-1])
        mom0 = float(self.squeeze.momentum[0])
        mom1 = float(self.squeeze.momentum[-1])

        squeeze_released = sq1 > 0 and sq0 < 0
        squeeze_fired = sq1 < 0 and sq0 > 0
        mom_reversed_from_pos = mom1 > 0 and mom0 < 0
        mom_reversed_from_neg = mom1 < 0 and mom0 > 0

        if self.position:
            if self.position.size > 0:
                if squeeze_fired or mom_reversed_from_pos:
                    self.log(f'close long squeeze={sq0:.0f} mom={mom0:.2f}')
                    self.close()
                    if squeeze_released and mom0 < 0:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                if squeeze_fired or mom_reversed_from_neg:
                    self.log(f'close short squeeze={sq0:.0f} mom={mom0:.2f}')
                    self.close()
                    if squeeze_released and mom0 > 0:
                        self.buy(size=self.p.lot)
                    return
        else:
            if squeeze_released and mom0 > 0:
                self.log(f'buy squeeze release mom={mom0:.2f}')
                self.buy(size=self.p.lot)
                return
            if squeeze_released and mom0 < 0:
                self.log(f'sell squeeze release mom={mom0:.2f}')
                self.sell(size=self.p.lot)
                return
            if mom1 < 0 and mom0 > 0 and sq0 < 0:
                self.log(f'buy momentum flip mom={mom0:.2f}')
                self.buy(size=self.p.lot)
                return
            if mom1 > 0 and mom0 < 0 and sq0 < 0:
                self.log(f'sell momentum flip mom={mom0:.2f}')
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
