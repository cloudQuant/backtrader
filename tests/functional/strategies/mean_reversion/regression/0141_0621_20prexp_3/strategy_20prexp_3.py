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


class PRExp3Strategy(bt.Strategy):
    params = dict(
        take_profit=20,
        trailing_stop=10,
        trailing_step=10,
        gap=50,
        volume_ratio_threshold=1.5,
        start_hour=7,
        sar_af=0.005,
        sar_afmax=0.01,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_base = self.datas[0]
        self.data_vol = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.sar = bt.indicators.ParabolicSAR(self.data_base, af=self.p.sar_af, afmax=self.p.sar_afmax)

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

        self.session_date = None
        self.session_high = None
        self.session_low = None
        self.prev_session_high = None
        self.prev_session_low = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _update_session_levels(self):
        current_dt = bt.num2date(self.data_base.datetime[0])
        current_date = current_dt.date()
        high = float(self.data_base.high[0])
        low = float(self.data_base.low[0])

        if self.session_date != current_date:
            self.session_date = current_date
            self.session_high = high
            self.session_low = low
            self.prev_session_high = None
            self.prev_session_low = None
            return

        self.prev_session_high = float(self.session_high)
        self.prev_session_low = float(self.session_low)
        self.session_high = max(float(self.session_high), high)
        self.session_low = min(float(self.session_low), low)

    def _volume_ratio(self):
        if len(self.data_vol) < 2:
            return 0.0
        prev_volume = float(self.data_vol.volume[-1])
        if prev_volume <= 0:
            return 0.0
        return float(self.data_vol.volume[0]) / prev_volume

    def _manage_position(self):
        if not self.position or self.order is not None:
            return

        prev_close = float(self.data_base.close[-1])
        price = float(self.data_base.close[0])
        high = float(self.data_base.high[0])
        low = float(self.data_base.low[0])
        trailing_stop = float(self.p.trailing_stop) * self._point()
        trailing_step = float(self.p.trailing_step) * self._point()
        take_dist = float(self.p.take_profit) * self._point()

        if self.position.size > 0:
            if float(self.sar[0]) > prev_close:
                self.order = self.close()
                return
            if trailing_stop > 0 and price - float(self.position.price) > trailing_stop:
                candidate_stop = self._round(price - trailing_stop)
                threshold = price - (trailing_stop + trailing_step)
                if self.stop_price is None or float(self.stop_price) < threshold:
                    self.stop_price = candidate_stop
                    self.take_profit_price = self._round(price + trailing_stop) if take_dist > 0 else None
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if float(self.sar[0]) < prev_close:
                self.order = self.close()
                return
            if trailing_stop > 0 and float(self.position.price) - price > trailing_stop:
                candidate_stop = self._round(price + trailing_stop)
                threshold = price + (trailing_stop + trailing_step)
                if self.stop_price is None or float(self.stop_price) > threshold:
                    self.stop_price = candidate_stop
                    self.take_profit_price = self._round(price - trailing_stop) if take_dist > 0 else None
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def _get_trade_signal(self):
        if self.prev_session_high is None or self.prev_session_low is None:
            return 0

        current_dt = bt.num2date(self.data_base.datetime[0])
        if current_dt.hour < int(self.p.start_hour):
            return 0

        ratio = self._volume_ratio()
        canal = float(self.prev_session_high) - float(self.prev_session_low)
        gap_dist = float(self.p.gap) * self._point()
        if ratio <= float(self.p.volume_ratio_threshold) or canal <= gap_dist:
            return 0

        if float(self.data_base.low[0]) < float(self.prev_session_low):
            return -1
        if float(self.data_base.high[0]) > float(self.prev_session_high):
            return 1
        return 0

    def next(self):
        self.bar_num += 1
        self._update_session_levels()

        if len(self.data_base) < 5 or len(self.data_vol) < 2:
            return
        if self.order is not None:
            return

        if self.position:
            self._manage_position()
            return

        signal = self._get_trade_signal()
        if signal == 0:
            return

        price = float(self.data_base.close[0])
        take_dist = float(self.p.take_profit) * self._point()
        if signal > 0:
            self.signal_count += 1
            self.stop_price = self._round(self.session_low) if self.session_low is not None else None
            self.take_profit_price = self._round(price + take_dist) if take_dist > 0 else None
            self.order = self.buy(size=self.p.lots)
        elif signal < 0:
            self.signal_count += 1
            self.stop_price = self._round(self.session_high) if self.session_high is not None else None
            self.take_profit_price = self._round(price - take_dist) if take_dist > 0 else None
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
