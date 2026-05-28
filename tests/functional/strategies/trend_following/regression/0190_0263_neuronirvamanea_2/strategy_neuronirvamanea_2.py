from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class LaguerrePlusDiProxy(bt.Indicator):
    lines = ('value',)
    params = dict(period=14)

    def __init__(self):
        self.addminperiod(self.p.period + 3)

    def next(self):
        pdm_vals = []
        mdm_vals = []
        tr_vals = []
        for idx in range(self.p.period):
            high0 = float(self.data.high[-idx])
            high1 = float(self.data.high[-idx - 1])
            low0 = float(self.data.low[-idx])
            low1 = float(self.data.low[-idx - 1])
            close1 = float(self.data.close[-idx - 1])
            up_move = high0 - high1
            down_move = low1 - low0
            pdm = up_move if up_move > down_move and up_move > 0 else 0.0
            mdm = down_move if down_move > up_move and down_move > 0 else 0.0
            tr = max(high0 - low0, abs(high0 - close1), abs(low0 - close1))
            pdm_vals.append(pdm)
            mdm_vals.append(mdm)
            tr_vals.append(tr)
        tr_sum = sum(tr_vals)
        if tr_sum <= 1e-12:
            self.lines.value[0] = 0.5
            return
        pdi = 100.0 * sum(pdm_vals) / tr_sum
        mdi = 100.0 * sum(mdm_vals) / tr_sum
        denom = pdi + mdi
        ratio = 0.5 if denom <= 1e-12 else pdi / denom
        self.lines.value[0] = max(0.0, min(1.0, ratio))


class SilverTrendSignalProxy(bt.Indicator):
    lines = ('buy', 'sell')
    params = dict(risk=3)

    def __init__(self):
        self.period = max(3, int(self.p.risk) * 2 + 1)
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.period)
        self.addminperiod(self.period + 3)

    def next(self):
        buy = 0.0
        sell = 0.0
        close0 = float(self.data.close[0])
        close1 = float(self.data.close[-1])
        ma0 = float(self.ma[0])
        ma1 = float(self.ma[-1])
        if close1 <= ma1 and close0 > ma0:
            buy = close0
        elif close1 >= ma1 and close0 < ma0:
            sell = close0
        self.lines.buy[0] = buy
        self.lines.sell[0] = sell


class NeuroNirvamanEA2Strategy(bt.Strategy):
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        start_hour=9,
        start_min=0,
        end_hour=17,
        end_min=3,
        risk_1=3,
        laguerre_1_period=14,
        laguerre_1_distance=0.0,
        x11=100.0,
        x12=100.0,
        tp1=100,
        sl1=50,
        risk_2=9,
        laguerre_2_period=14,
        laguerre_2_distance=0.0,
        x21=100.0,
        x22=100.0,
        tp2=100,
        sl2=50,
        laguerre_3_period=14,
        laguerre_3_distance=0.0,
        laguerre_4_period=14,
        laguerre_4_distance=0.0,
        x31=100.0,
        x32=100.0,
        pass_mode=3,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.laguerre_1 = LaguerrePlusDiProxy(self.data0_feed, period=self.p.laguerre_1_period)
        self.laguerre_2 = LaguerrePlusDiProxy(self.data0_feed, period=self.p.laguerre_2_period)
        self.laguerre_3 = LaguerrePlusDiProxy(self.data0_feed, period=self.p.laguerre_3_period)
        self.laguerre_4 = LaguerrePlusDiProxy(self.data0_feed, period=self.p.laguerre_4_period)
        self.silver_1 = SilverTrendSignalProxy(self.data0_feed, risk=self.p.risk_1)
        self.silver_2 = SilverTrendSignalProxy(self.data0_feed, risk=self.p.risk_2)
        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.limit_order = None
        self.active_side = None
        self.last_bar_dt = None
        self.close_all_pending = False

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def prenext(self):
        self.next()

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _in_trade_window(self):
        current_dt = bt.num2date(self.data0_feed.datetime[0])
        current = current_dt.hour * 3600 + current_dt.minute * 60
        start = self.p.start_hour * 3600 + self.p.start_min * 60
        end = self.p.end_hour * 3600 + self.p.end_min * 60
        return start <= current <= end

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _signal_from_laguerre(self, value, distance):
        upper = 0.5 + distance / 100.0
        lower = 0.5 - distance / 100.0
        if value > upper:
            return -1
        if value < lower:
            return 1
        return 0

    def _silver_value(self, proxy):
        if float(proxy.buy[0]) != 0.0:
            return 1
        if float(proxy.sell[0]) != 0.0:
            return -1
        return 0

    def _perceptron1(self):
        w2 = self.p.x11 - 100.0
        w4 = self.p.x12 - 100.0
        a2 = self._signal_from_laguerre(float(self.laguerre_1.value[0]), self.p.laguerre_1_distance)
        a4 = self._silver_value(self.silver_1)
        return w2 * a2 + w4 * a4

    def _perceptron2(self):
        w2 = self.p.x21 - 100.0
        w4 = self.p.x22 - 100.0
        a2 = self._signal_from_laguerre(float(self.laguerre_2.value[0]), self.p.laguerre_2_distance)
        a4 = self._silver_value(self.silver_2)
        return w2 * a2 + w4 * a4

    def _perceptron3(self):
        w1 = self.p.x31 - 100.0
        w2 = self.p.x32 - 100.0
        a1 = self._signal_from_laguerre(float(self.laguerre_3.value[0]), self.p.laguerre_3_distance)
        a2 = self._signal_from_laguerre(float(self.laguerre_4.value[0]), self.p.laguerre_4_distance)
        return w1 * a1 + w2 * a2

    def _supervisor(self):
        tp = 100.0
        sl = 50.0
        if self.p.pass_mode == 3:
            if self._perceptron3() > 0:
                if self._perceptron2() > 0:
                    return 1, float(self.p.tp2), float(self.p.sl2)
            else:
                if self._perceptron1() < 0:
                    return -1, float(self.p.tp1), float(self.p.sl1)
            return 0, tp, sl
        if self.p.pass_mode == 2:
            if self._perceptron2() > 0:
                return 1, float(self.p.tp2), float(self.p.sl2)
            return -1, tp, sl
        if self.p.pass_mode == 1:
            if self._perceptron1() < 0:
                return -1, float(self.p.tp1), float(self.p.sl1)
            return 1, tp, sl
        return 0, tp, sl

    def _submit_entry(self, direction, tp_points, sl_points):
        if self.position or self.entry_order is not None or self.close_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        price = float(self.data0_feed.close[0])
        sl_distance = sl_points * self.p.point_size
        tp_distance = tp_points * self.p.point_size
        if direction > 0:
            sl = price - sl_distance
            tp = price + tp_distance
            orders = self.buy_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.log(f'OPEN LONG size={size} tp={tp_points} sl={sl_points} reason=supervisor>0')
        else:
            sl = price + sl_distance
            tp = price - tp_distance
            orders = self.sell_bracket(size=size, exectype=bt.Order.Market, stopprice=sl, limitprice=tp)
            self.log(f'OPEN SHORT size={size} tp={tp_points} sl={sl_points} reason=supervisor<0')
        self.entry_order, self.stop_order, self.limit_order = orders

    def next(self):
        if len(self.data0_feed) < max(self.p.laguerre_1_period, self.p.laguerre_2_period, self.p.laguerre_3_period, self.p.laguerre_4_period, 20) + 5:
            return
        if not self._new_bar():
            return
        if not self._in_trade_window():
            if self.position and self.close_order is None:
                self.close_all_pending = True
                self._cancel_exit_orders()
                self.close_order = self.close()
                self.log('CLOSE side=all reason=outside trade window')
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        if self.position:
            return
        direction, tp_points, sl_points = self._supervisor()
        if direction != 0:
            self._submit_entry(direction, tp_points, sl_points)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.close_all_pending = False
                self.active_side = None
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.close_all_pending = False
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
