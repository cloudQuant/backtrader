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


class MQL5WizardMacdParabolicSarStrategy(bt.Strategy):
    params = dict(
        signal_threshold_open=20,
        signal_threshold_close=100,
        signal_stop_level=50.0,
        signal_take_level=115.0,
        signal_macd_period_fast=12,
        signal_macd_period_slow=24,
        signal_macd_period_signal=9,
        signal_macd_weight=0.9,
        signal_sar_step=0.02,
        signal_sar_maximum=0.2,
        signal_sar_weight=0.1,
        money_fixlot_lots=1.0,
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
    )

    def __init__(self):
        self.macd = bt.indicators.MACD(self.data.close, period_me1=self.p.signal_macd_period_fast, period_me2=self.p.signal_macd_period_slow, period_signal=self.p.signal_macd_period_signal)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.signal_sar_step, afmax=self.p.signal_sar_maximum)

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

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _macd_score(self):
        macd_curr = float(self.macd.macd[0])
        signal_curr = float(self.macd.signal[0])
        if macd_curr > signal_curr:
            return 100.0 * float(self.p.signal_macd_weight)
        if macd_curr < signal_curr:
            return -100.0 * float(self.p.signal_macd_weight)
        return 0.0

    def _sar_score(self):
        close = float(self.data.close[0])
        sar = float(self.sar[0])
        if close > sar:
            return 100.0 * float(self.p.signal_sar_weight)
        if close < sar:
            return -100.0 * float(self.p.signal_sar_weight)
        return 0.0

    def _signal_value(self):
        return self._macd_score() + self._sar_score()

    def _set_risk(self, side, price):
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(price - float(self.p.signal_stop_level) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.signal_take_level) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.signal_stop_level) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.signal_take_level) * unit, int(self.p.price_digits))

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        signal_value = self._signal_value()
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if high >= float(self.take_profit_price) or low <= float(self.stop_price) or signal_value <= -float(self.p.signal_threshold_close):
                self.order = self.close()
                return True
        else:
            if low <= float(self.take_profit_price) or high >= float(self.stop_price) or signal_value >= float(self.p.signal_threshold_close):
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.signal_macd_period_slow, 30):
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        signal_value = self._signal_value()
        price = float(self.data.close[0])
        if signal_value >= float(self.p.signal_threshold_open):
            self.signal_count += 1
            self._set_risk('buy', price)
            self.order = self.buy(size=self.p.money_fixlot_lots)
            return
        if signal_value <= -float(self.p.signal_threshold_open):
            self.signal_count += 1
            self._set_risk('sell', price)
            self.order = self.sell(size=self.p.money_fixlot_lots)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if order.executed.size > 0:
                self.buy_count += 1
            elif order.executed.size < 0:
                self.sell_count += 1
            if not self.position:
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
