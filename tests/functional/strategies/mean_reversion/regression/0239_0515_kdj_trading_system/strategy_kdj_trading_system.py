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


class KDJIndicator(bt.Indicator):
    lines = ('kdc', 'rsv', 'k', 'd')
    params = dict(m1=3, m2=6, kdj_period=30)

    def __init__(self):
        self.addminperiod(int(self.p.kdj_period) + int(self.p.m2) + 2)

    def next(self):
        kdj_period = int(self.p.kdj_period)
        m1 = int(self.p.m1)
        m2 = int(self.p.m2)
        highs = [float(self.data.high[-i]) for i in range(kdj_period)]
        lows = [float(self.data.low[-i]) for i in range(kdj_period)]
        max_high = max(highs)
        min_low = min(lows)
        if max_high - min_low != 0.0:
            self.lines.rsv[0] = (float(self.data.close[0]) - min_low) / (max_high - min_low) * 100.0
        else:
            self.lines.rsv[0] = 1.0
        rsv_values = []
        for i in range(m1):
            value = float(self.lines.rsv[-i]) if len(self) > i else 50.0
            rsv_values.append(value)
        self.lines.k[0] = sum(rsv_values) / float(m1)
        k_values = []
        for i in range(m2):
            value = float(self.lines.k[-i]) if len(self) > i else 50.0
            k_values.append(value)
        self.lines.d[0] = sum(k_values) / float(m2)
        self.lines.kdc[0] = float(self.lines.k[0]) - float(self.lines.d[0])


class KDJTradingSystemStrategy(bt.Strategy):
    params = dict(
        m1=3,
        m2=6,
        kdj_period=30,
        lots=0.1,
        stop_loss=25,
        take_profit=45,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_h1 = self.datas[1]
        self.kdj = KDJIndicator(self.data_h1, m1=int(self.p.m1), m2=int(self.p.m2), kdj_period=int(self.p.kdj_period))
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
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _manage(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(data=self.data); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(data=self.data); return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(data=self.data); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(data=self.data); return

    def next(self):
        self.bar_num += 1
        self._manage()
        if self.order is not None or self.position:
            return
        if len(self.data_h1) < int(self.p.kdj_period) + int(self.p.m2) + 3:
            return
        signal_dt = self.data_h1.datetime.datetime(0)
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        val_kdc_current = float(self.kdj.kdc[0])
        val_kdc_prev = float(self.kdj.kdc[-1])
        val_k_current = float(self.kdj.k[0])
        val_k_prev = float(self.kdj.k[-1])
        price = float(self.data.close[0])
        sl_dist = float(self.p.stop_loss) * self._point()
        tp_dist = float(self.p.take_profit) * self._point()
        if (val_kdc_prev < 0.0 and val_kdc_current > 0.0) or (val_kdc_current > 0.0 and (val_k_prev - val_k_current) < 0.0):
            self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price + tp_dist) if tp_dist > 0 else None
            self.signal_count += 1
            self.order = self.buy(data=self.data, size=float(self.p.lots))
            return
        if (val_kdc_prev > 0.0 and val_kdc_current < 0.0) or (val_kdc_current < 0.0 and (val_k_prev - val_k_current) > 0.0):
            self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price - tp_dist) if tp_dist > 0 else None
            self.signal_count += 1
            self.order = self.sell(data=self.data, size=float(self.p.lots))

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
