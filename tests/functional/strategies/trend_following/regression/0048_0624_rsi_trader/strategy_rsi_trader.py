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


class RSITraderStrategy(bt.Strategy):
    """EA 0624: RSI averaged with SMA/LWMA + dual MA crossover on price.
    RSI Short SMA = SimpleMA of RSI array over Short_RSI_MA_periods.
    RSI Long SMA  = SimpleMA of RSI array over Long_RSI_MA_periods.
    Price MA Short = SMA(9), Price MA Long = LWMA(45).
    Long:  RSI_Short > RSI_Long AND Price_MA_Short > Price_MA_Long.
    Short: RSI_Short < RSI_Long AND Price_MA_Short < Price_MA_Long.
    Reverse option flips direction. No SL/TP in original.
    """

    params = dict(
        rsi_period=14,
        short_rsi_ma=9,
        long_rsi_ma=45,
        ma_short_period=9,
        ma_long_period=45,
        reverse=False,
        lots=1.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.rsi_sma_short = bt.indicators.SMA(self.rsi, period=self.p.short_rsi_ma)
        self.rsi_sma_long = bt.indicators.SMA(self.rsi, period=self.p.long_rsi_ma)
        self.ma_short = bt.indicators.SMA(self.data.close, period=self.p.ma_short_period)
        self.ma_long = bt.indicators.WMA(self.data.close, period=self.p.ma_long_period)

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

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.rsi_period + self.p.long_rsi_ma, self.p.ma_long_period) + 2
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        rsi_s = float(self.rsi_sma_short[-1])
        rsi_l = float(self.rsi_sma_long[-1])
        ma_s = float(self.ma_short[-1])
        ma_l = float(self.ma_long[-1])

        long_sig = rsi_s > rsi_l and ma_s > ma_l
        short_sig = rsi_s < rsi_l and ma_s < ma_l
        sideways_sig = ((ma_s > ma_l and rsi_s < rsi_l) or
                        (ma_s < ma_l and rsi_s > rsi_l))

        if self.p.reverse:
            long_sig, short_sig = short_sig, long_sig

        if self.position:
            if sideways_sig:
                self.order = self.close()
            return

        if long_sig:
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots)
        elif short_sig:
            self.signal_count += 1
            self.order = self.sell(size=self.p.lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0: self.buy_count += 1
                elif order.executed.size < 0: self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0: self.win_count += 1
        else: self.loss_count += 1
