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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


class AltariusRsiStochasticStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        maximum_risk=0.1,
        decrease_factor=3.0,
        period_rsi=4,
        point=0.01,
        contract_multiplier=100.0,
        min_lot=0.1,
    )

    def __init__(self):
        self.sto_15_8_8 = bt.indicators.Stochastic(self.data, period=15, period_dfast=8, period_dslow=8)
        self.sto_10_3_3 = bt.indicators.Stochastic(self.data, period=10, period_dfast=3, period_dslow=3)
        median = (self.data.high + self.data.low) / 2.0
        self.rsi = bt.indicators.RSI(median, period=3)

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
        self.closed_trade_pnls = []

    def _lot_optimized(self):
        lot = float(self.p.lots)
        lot = round(float(self.broker.get_cash()) * float(self.p.maximum_risk) / 1000.0, 2)
        if float(self.p.decrease_factor) > 0:
            losses = 0
            for pnl in reversed(self.closed_trade_pnls):
                if pnl > 0:
                    break
                if pnl < 0:
                    losses += 1
            if losses > 1:
                lot = round(lot - lot * losses / float(self.p.decrease_factor), 1)
        return max(float(self.p.min_lot), lot)

    def _open_signal(self):
        slow_main = float(self.sto_15_8_8.percK[0])
        slow_signal = float(self.sto_15_8_8.percD[0])
        fast_main = float(self.sto_10_3_3.percK[0])
        fast_signal = float(self.sto_10_3_3.percD[0])
        if slow_main > slow_signal and slow_main < 50 and abs(fast_main - fast_signal) > 5:
            return 1
        if slow_main < slow_signal and slow_main > 55 and abs(fast_main - fast_signal) > 5:
            return -1
        return 0

    def _close_signal(self):
        rsi_0 = float(self.rsi[0])
        sto_signal_0 = float(self.sto_15_8_8.percD[0])
        sto_signal_1 = float(self.sto_15_8_8.percD[-1])
        if self.position.size > 0:
            return rsi_0 > 60 and sto_signal_0 < sto_signal_1 and sto_signal_0 > 70
        if self.position.size < 0:
            return rsi_0 < 40 and sto_signal_0 > sto_signal_1 and sto_signal_0 < 30
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < 100:
            return
        if self.order is not None:
            return
        if self.position:
            if self._close_signal():
                self.order = self.close()
            return
        signal = self._open_signal()
        if signal == 0:
            return
        self.signal_count += 1
        size = self._lot_optimized()
        if signal > 0:
            self.order = self.buy(size=size)
        else:
            self.order = self.sell(size=size)

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
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.closed_trade_pnls.append(trade.pnlcomm)
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
