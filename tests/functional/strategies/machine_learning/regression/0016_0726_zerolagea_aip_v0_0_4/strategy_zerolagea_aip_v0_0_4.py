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


class ZeroLagMacd(bt.Indicator):
    lines = ('macd', 'signal')
    params = dict(fast=12, slow=26)

    def __init__(self):
        ema_fast = bt.indicators.ExponentialMovingAverage(self.data, period=self.p.fast)
        ema_fast2 = bt.indicators.ExponentialMovingAverage(ema_fast, period=self.p.fast)
        zlema_fast = 2.0 * ema_fast - ema_fast2
        ema_slow = bt.indicators.ExponentialMovingAverage(self.data, period=self.p.slow)
        ema_slow2 = bt.indicators.ExponentialMovingAverage(ema_slow, period=self.p.slow)
        zlema_slow = 2.0 * ema_slow - ema_slow2
        self.lines.macd = zlema_fast - zlema_slow
        self.lines.signal = bt.indicators.ExponentialMovingAverage(self.lines.macd, period=9)


class ZeroLagEAAIPStrategy(bt.Strategy):
    params = dict(
        fast_ema=2,
        slow_ema=34,
        use_fresh_macd_sig=1,
        lots=2.0,
        start_hour=9,
        end_hour=15,
        kill_day=5,
        kill_hour=21,
    )

    def __init__(self):
        self.zlmacd = ZeroLagMacd(self.data.close, fast=self.p.fast_ema, slow=self.p.slow_ema)

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

    def _in_session(self):
        dt = bt.num2date(self.data.datetime[0])
        if dt.hour < int(self.p.start_hour) or dt.hour >= int(self.p.end_hour):
            return False
        if dt.weekday() == int(self.p.kill_day) and dt.hour == int(self.p.kill_hour):
            return False
        return True

    def _kill_time(self):
        dt = bt.num2date(self.data.datetime[0])
        return dt.weekday() == int(self.p.kill_day) and dt.hour == int(self.p.kill_hour)

    def _fresh_signal(self):
        main_prev = float(self.zlmacd.macd[-1])
        signal_prev = float(self.zlmacd.signal[-1])
        main_curr = float(self.zlmacd.macd[0])
        signal_curr = float(self.zlmacd.signal[0])
        return (signal_prev > main_prev and signal_curr < main_curr) or (signal_prev < main_prev and signal_curr > main_curr)

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.fast_ema, self.p.slow_ema) + 5:
            return
        if self.order is not None:
            return
        if not self._in_session():
            if self.position:
                self.order = self.close()
            return
        if self._kill_time() and self.position:
            self.order = self.close()
            return
        if int(self.p.use_fresh_macd_sig) == 1 and not self._fresh_signal():
            return
        main_now = float(self.zlmacd.macd[0])
        signal_now = float(self.zlmacd.signal[0])
        buy_sig = signal_now < main_now
        sell_sig = signal_now > main_now
        if self.position:
            if self.position.size > 0 and sell_sig:
                self.order = self.close()
                return
            if self.position.size < 0 and buy_sig:
                self.order = self.close()
                return
            return
        if buy_sig:
            self.signal_count += 1
            self.order = self.buy(size=self.p.lots)
            return
        if sell_sig:
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
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
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
