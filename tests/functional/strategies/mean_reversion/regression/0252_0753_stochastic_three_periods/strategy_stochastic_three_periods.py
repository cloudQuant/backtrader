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


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class ThreePeriodStochStrategy(bt.Strategy):
    params = dict(
        tp=30,
        sl=10,
        lots=0.1,
        shift_entrance=3,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.m5 = self.datas[1]
        self.m15 = self.datas[2]
        self.m30 = self.datas[3]
        self.exit_tf = self.datas[4]

        self.stoch_m5 = bt.indicators.Stochastic(self.m5, period=5, period_dfast=3, period_dslow=3)
        self.stoch_m15 = bt.indicators.Stochastic(self.m15, period=5, period_dfast=3, period_dslow=3)
        self.stoch_m30 = bt.indicators.Stochastic(self.m30, period=5, period_dfast=3, period_dslow=3)
        self.stoch_exit = bt.indicators.Stochastic(self.exit_tf, period=5, period_dfast=3, period_dslow=3)

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
        self.lastorder = 0
        self.stop_price = None
        self.take_profit_price = None
        self.last_entry_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _entry_signal(self):
        k0 = float(self.stoch_m5.percK[0])
        d0 = float(self.stoch_m5.percD[0])
        idx = max(int(self.p.shift_entrance), 1)
        k_shift = float(self.stoch_m5.percK[-idx])
        d_shift = float(self.stoch_m5.percD[-idx])
        k15 = float(self.stoch_m15.percK[0])
        d15 = float(self.stoch_m15.percD[0])
        k30 = float(self.stoch_m30.percK[0])
        d30 = float(self.stoch_m30.percD[0])
        close_0 = float(self.base.close[0])
        close_1 = float(self.base.close[-1])
        if k0 > d0 and k_shift < d_shift and k15 > d15 and k30 > d30 and close_0 > close_1:
            return 1
        if k0 < d0 and k_shift > d_shift and k15 < d15 and k30 < d30 and close_0 < close_1:
            return 2
        return 0

    def _exit_signal(self):
        k1 = float(self.stoch_exit.percK[-1])
        d1 = float(self.stoch_exit.percD[-1])
        if k1 > d1:
            return 1
        if k1 < d1:
            return 2
        return 0

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.base.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.sl) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.tp) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.sl) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.tp) * unit, int(self.p.price_digits))

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if low <= self.stop_price or high >= self.take_profit_price or self._exit_signal() == 2:
                self.order = self.close()
                return True
        else:
            if high >= self.stop_price or low <= self.take_profit_price or self._exit_signal() == 1:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < max(5, int(self.p.shift_entrance) + 2):
            return
        if self.order is not None:
            return
        if self.position:
            if self._manage_position():
                return
        signal_dt = bt.num2date(self.m5.datetime[0])
        if self.last_entry_signal_dt == signal_dt:
            return
        if self.position:
            return
        signal = self._entry_signal()
        if signal == 1 and self.lastorder != 1:
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lots)
            self.lastorder = 1
            self.last_entry_signal_dt = signal_dt
            return
        if signal == 2 and self.lastorder != 2:
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lots)
            self.lastorder = 2
            self.last_entry_signal_dt = signal_dt

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
                self.stop_price = None
                self.take_profit_price = None
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
