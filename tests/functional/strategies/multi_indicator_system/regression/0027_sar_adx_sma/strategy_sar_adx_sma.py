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


class SarAdxSmaStrategy(bt.Strategy):
    """
    Triple indicator strategy: SAR + ADX + SMA(100).
    Buy: price > SMA100 AND SAR below price AND ADX > threshold (trending up).
    Sell: price < SMA100 AND SAR above price AND ADX > threshold (trending down).
    Exit: SAR flips or ADX drops below threshold.
    """
    params = dict(
        sma_period=100,
        adx_period=14,
        adx_threshold=20,
        sar_af=0.02,
        sar_afmax=0.2,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.sma_period)
        self.adx = bt.indicators.AverageDirectionalMovementIndex(
            self.data, period=self.p.adx_period)
        self.sar = bt.indicators.ParabolicSAR(
            self.data, af=self.p.sar_af, afmax=self.p.sar_afmax)
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
        if len(self.data) < self.p.sma_period + 5:
            return

        close = float(self.data.close[0])
        sma_val = float(self.sma[0])
        adx_val = float(self.adx[0])
        sar_val = float(self.sar[0])

        above_sma = close > sma_val
        below_sma = close < sma_val
        sar_below = sar_val < close
        sar_above = sar_val > close
        adx_strong = adx_val > self.p.adx_threshold

        if self.position:
            if self.position.size > 0:
                if sar_above or not adx_strong:
                    self.log(f'close long sar={sar_val:.2f} adx={adx_val:.1f}')
                    self.close()
                    if below_sma and sar_above and adx_strong:
                        self.sell(size=self.p.lot)
                    return
            elif self.position.size < 0:
                if sar_below or not adx_strong:
                    self.log(f'close short sar={sar_val:.2f} adx={adx_val:.1f}')
                    self.close()
                    if above_sma and sar_below and adx_strong:
                        self.buy(size=self.p.lot)
                    return
        else:
            if above_sma and sar_below and adx_strong:
                self.log(f'buy sma={sma_val:.2f} sar={sar_val:.2f} adx={adx_val:.1f}')
                self.buy(size=self.p.lot)
                return
            if below_sma and sar_above and adx_strong:
                self.log(f'sell sma={sma_val:.2f} sar={sar_val:.2f} adx={adx_val:.1f}')
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
