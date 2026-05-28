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


class TrendCatcherStrategy(bt.Strategy):
    params = dict(
        close_opposite_signal=True,
        reverse_sig_open=False,
        period_ma_slow=200,
        period_ma_fast=50,
        period_ma_fast2=25,
        step_sar=0.004,
        max_sar=0.2,
        auto_sl=True,
        auto_tp=True,
        min_sl=10,
        max_sl=200,
        sl_koef=1.0,
        tp_koef=1.0,
        sl=20,
        tp=200,
        risk=2.0,
        martin=True,
        koef=2.0,
        profit_level=500,
        sl_plus=1,
        profit_level2=500,
        trailing_stop2=10,
        candle_tf='current',
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
    )

    def __init__(self):
        self.ma_slow = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.period_ma_slow)
        self.ma_fast = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.period_ma_fast)
        self.ma_fast2 = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.period_ma_fast2)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.step_sar, afmax=self.p.max_sar)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.last_trade_pnl = 0.0
        self.last_entry_marker = None

        self.order = None
        self.stop_price = None
        self.take_profit_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _lot_size(self, sl_points):
        cash = self.broker.getvalue()
        risk_pct = float(self.p.risk)
        if self.p.martin and self.last_trade_pnl < 0:
            risk_pct *= float(self.p.koef)
        if sl_points <= 0:
            return 0.01
        risk_cash = cash * risk_pct / 100.0
        unit_value = 100000 * self._unit()
        size = risk_cash / max(sl_points * unit_value, 1e-9)
        return max(0.01, round(size, 2))

    def _signal(self):
        sig = 0
        close0 = float(self.data.close[0])
        close1 = float(self.data.close[-1])
        sar0 = float(self.sar[0])
        sar1 = float(self.sar[-1])
        ma_slow = float(self.ma_slow[0])
        ma_fast = float(self.ma_fast[0])
        ma_fast2 = float(self.ma_fast2[0])
        if close0 > sar0 and close1 < sar1 and ma_fast > ma_slow and close0 > ma_fast2:
            sig = 1
        elif close0 < sar0 and close1 > sar1 and ma_fast < ma_slow and close0 < ma_fast2:
            sig = -1
        if self.p.reverse_sig_open:
            sig *= -1
        return sig

    def _sl_tp_from_signal(self, side):
        unit = self._unit()
        price = float(self.data.close[0])
        sar0 = float(self.sar[0])
        if self.p.auto_sl:
            sl_points = abs(price - sar0) / unit * float(self.p.sl_koef)
        else:
            sl_points = float(self.p.sl)
        sl_points = min(max(sl_points, float(self.p.min_sl)), float(self.p.max_sl))
        tp_points = sl_points * float(self.p.tp_koef) if self.p.auto_tp else float(self.p.tp)
        if side == 'buy':
            sl = round(price - sl_points * unit, int(self.p.price_digits))
            tp = round(price + tp_points * unit, int(self.p.price_digits))
        else:
            sl = round(price + sl_points * unit, int(self.p.price_digits))
            tp = round(price - tp_points * unit, int(self.p.price_digits))
        return sl, tp, sl_points

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        signal = self._signal()
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        unit = self._unit()
        bez = float(self.p.profit_level) * unit
        sl_plus = float(self.p.sl_plus) * unit
        bez2 = float(self.p.profit_level2) * unit
        tr = float(self.p.trailing_stop2) * unit
        if self.position.size > 0:
            if self.p.close_opposite_signal and signal < 0:
                self.order = self.close()
                return True
            if high >= float(self.take_profit_price) or low <= float(self.stop_price):
                self.order = self.close()
                return True
            if close - float(self.position.price) > bez:
                self.stop_price = max(float(self.stop_price), round(float(self.position.price) + sl_plus, int(self.p.price_digits)))
            if close - float(self.position.price) > bez2:
                self.stop_price = max(float(self.stop_price), round(close - tr, int(self.p.price_digits)))
        else:
            if self.p.close_opposite_signal and signal > 0:
                self.order = self.close()
                return True
            if low <= float(self.take_profit_price) or high >= float(self.stop_price):
                self.order = self.close()
                return True
            if float(self.position.price) - close > bez:
                self.stop_price = min(float(self.stop_price), round(float(self.position.price) - sl_plus, int(self.p.price_digits)))
            if float(self.position.price) - close > bez2:
                self.stop_price = min(float(self.stop_price), round(close + tr, int(self.p.price_digits)))
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.period_ma_slow, 220):
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        signal = self._signal()
        if signal == 0:
            return
        marker = bt.num2date(self.data.datetime[0]).date() if self.p.candle_tf != 'current' else bt.num2date(self.data.datetime[0])
        if self.last_entry_marker == marker:
            return
        side = 'buy' if signal > 0 else 'sell'
        self.stop_price, self.take_profit_price, sl_points = self._sl_tp_from_signal(side)
        size = self._lot_size(sl_points)
        self.signal_count += 1
        self.last_entry_marker = marker
        if side == 'buy':
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
        self.last_trade_pnl = trade.pnlcomm
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
