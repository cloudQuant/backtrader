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
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume']
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class BollingerStrategy(bt.Strategy):
    """Bollinger Bands mean-reversion strategy (EA 0616).

    Entry:
      - Buy  when Low < LowerBand AND High < MiddleBand
      - Sell when High > UpperBand AND Low > MiddleBand

    Position management:
      - No SL / TP.
      - Reversal only allowed when existing position is in profit.
      - If no position, open on signal directly.
    """

    params = dict(
        bands_period=80,
        deviation=3.0,
        lots=0.01,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.pending_reentry = None

        self.bbands = bt.indicators.BollingerBands(
            self.data.close,
            period=int(self.p.bands_period),
            devfactor=float(self.p.deviation),
        )

    def next(self):
        self.bar_num += 1
        warmup = int(self.p.bands_period) + 2
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        high = float(self.data.high[0])
        low = float(self.data.low[0])
        upper = float(self.bbands.top[0])
        middle = float(self.bbands.mid[0])
        lower = float(self.bbands.bot[0])

        buy_sig = low < lower and high < middle
        sell_sig = high > upper and low > middle

        if self.position:
            pnl = float(self.position.size) * (float(self.data.close[0]) - float(self.position.price))
            if self.position.size > 0 and sell_sig and pnl > 0:
                self.pending_reentry = 'sell'
                self.order = self.close()
                return
            if self.position.size < 0 and buy_sig and pnl > 0:
                self.pending_reentry = 'buy'
                self.order = self.close()
                return
            return

        if buy_sig:
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots)
        elif sell_sig:
            self.signal_count += 1
            self.order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                pending = self.pending_reentry
                self.pending_reentry = None
                if pending and self.order is None:
                    self.signal_count += 1
                    if pending == 'buy':
                        self.order = self.buy(size=self.p.lots)
                    else:
                        self.order = self.sell(size=self.p.lots)
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.pending_reentry = None
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
