from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader.feeds as btfeeds
import backtrader.indicators as btind
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class Cs2011Strategy(Strategy):
    params = dict(
        risk=3.0,
        deposit_base=5000.0,
        tp_points=2200,
        sl_points=6000,
        fast=14,
        slow=500,
        signal=36,
        point=0.01,
        min_volume=0.1,
        max_volume=100.0,
        volume_step=0.1,
    )

    def __init__(self):
        self.macd = btind.MACD(
            self.data.close,
            period_me1=int(self.p.fast),
            period_me2=int(self.p.slow),
            period_signal=int(self.p.signal),
        )
        self.order = None
        self.pending_target = None
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

        self.bar_num = 0
        self.signal_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.rejected_order_count = 0
        self.completed_order_count = 0

        self.addminperiod(max(int(self.p.slow), 100) + 5)

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_volume(self, volume):
        step = float(self.p.volume_step)
        if step <= 0:
            return volume
        steps = math.floor(volume / step + 1e-9)
        return round(steps * step, 1)

    def _money_m(self):
        money = float(self.broker.getvalue())
        lots = float(self.p.risk) * money / float(self.p.deposit_base)
        lots = min(float(self.p.max_volume), max(float(self.p.min_volume), lots))
        return self._normalize_volume(lots)

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None or self.order is not None:
            return False
        low = float(self.data.low[0])
        high = float(self.data.high[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.target_price is not None and high >= self.target_price:
                self.log(f'close long target={self.target_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.target_price is not None and low <= self.target_price:
                self.log(f'close short target={self.target_price:.2f}')
                self.order = self.close()
                return True
        return False

    def _signals(self):
        macd_now = float(self.macd.macd[0])
        macd_prev = float(self.macd.macd[-1])
        signal_now = float(self.macd.signal[0])
        signal_prev = float(self.macd.signal[-1])
        signal_older = float(self.macd.signal[-2])

        dn_signal = False
        up_signal = False
        if macd_now > 0 and macd_prev < 0:
            dn_signal = True
        if macd_now < 0 and macd_prev > 0:
            up_signal = True
        if macd_prev < 0 and signal_now < signal_prev and signal_prev > signal_older:
            dn_signal = True
        if macd_prev > 0 and signal_now > signal_prev and signal_prev < signal_older:
            up_signal = True
        return up_signal, dn_signal

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._manage_protective_levels():
            return

        up_signal, dn_signal = self._signals()
        target_lots = self._money_m()

        if up_signal:
            self.signal_count += 1
            self.buy_signal_count += 1
            self.pending_target = target_lots
            self.log(f'buy signal target={target_lots:.1f}')
            self.order = self.order_target_size(target=target_lots)
            return

        if dn_signal:
            self.signal_count += 1
            self.sell_signal_count += 1
            self.pending_target = -target_lots
            self.log(f'sell signal target={target_lots:.1f}')
            self.order = self.order_target_size(target=-target_lots)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.log(f'order {order.getstatusname()}')
            self.pending_target = None
            self.order = None
            return
        if order.status == order.Completed:
            self.completed_order_count += 1
            if self.pending_target is not None:
                if self.pending_target > 0 and order.isbuy():
                    self.buy_count += 1
                if self.pending_target < 0 and order.issell():
                    self.sell_count += 1
            if self.position:
                self.entry_price = float(self.position.price)
                if self.position.size > 0:
                    self.stop_price = self.entry_price - float(self.p.sl_points) * float(self.p.point) if self.p.sl_points > 0 else None
                    self.target_price = self.entry_price + float(self.p.tp_points) * float(self.p.point) if self.p.tp_points > 0 else None
                else:
                    self.stop_price = self.entry_price + float(self.p.sl_points) * float(self.p.point) if self.p.sl_points > 0 else None
                    self.target_price = self.entry_price - float(self.p.tp_points) * float(self.p.point) if self.p.tp_points > 0 else None
            else:
                self._reset_levels()
            self.pending_target = None
        self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
        if not self.position:
            self._reset_levels()
