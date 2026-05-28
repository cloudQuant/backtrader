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


class MAParabolicStrategy(bt.Strategy):
    """
    Smoothed Parabolic SAR using X2MA (double-smoothed moving average) as input.
    Simplified: EMA-smoothed Parabolic SAR.
    Buy: SAR flips below price (dots appear below candles)
    Sell: SAR flips above price (dots appear above candles)
    """
    params = dict(
        ema_period=14,
        sar_af=0.02,
        sar_afmax=0.2,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.ema = bt.indicators.EMA(self.data.close, period=self.p.ema_period)
        self.sar = bt.indicators.ParabolicSAR(
            self.data, af=self.p.sar_af, afmax=self.p.sar_afmax)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._prev_sar_above = None

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.p.ema_period + 5:
            return

        ema_val = float(self.ema[0])
        sar_val = float(self.sar[0])
        sar_above = sar_val > ema_val

        if self._prev_sar_above is None:
            self._prev_sar_above = sar_above
            return

        sar_flipped_below = self._prev_sar_above and not sar_above
        sar_flipped_above = not self._prev_sar_above and sar_above
        self._prev_sar_above = sar_above

        if self.position:
            if self.position.size > 0 and sar_flipped_above:
                self.log(f'close long & sell sar={sar_val:.2f} ema={ema_val:.2f}')
                self.close()
                self.sell(size=self.p.lot)
                return
            elif self.position.size < 0 and sar_flipped_below:
                self.log(f'close short & buy sar={sar_val:.2f} ema={ema_val:.2f}')
                self.close()
                self.buy(size=self.p.lot)
                return
        else:
            if sar_flipped_below:
                self.log(f'buy sar={sar_val:.2f} ema={ema_val:.2f}')
                self.buy(size=self.p.lot)
                return
            if sar_flipped_above:
                self.log(f'sell sar={sar_val:.2f} ema={ema_val:.2f}')
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
