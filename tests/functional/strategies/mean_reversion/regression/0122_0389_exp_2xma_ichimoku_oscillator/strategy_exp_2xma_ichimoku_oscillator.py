import math
import backtrader as bt


class XmaIchimoku(bt.Indicator):
    lines = ('value',)

    params = dict(
        up_period=6,
        dn_period=6,
        up_mode='HIGH',
        dn_mode='LOW',
        xma_method='SMA',
        x_length=25,
        x_phase=15,
        price_shift=0.0,
    )

    def __init__(self):
        self.addminperiod(max(int(self.p.up_period), int(self.p.dn_period)) + int(self.p.x_length) + 5)
        self._raw_buf = []
        self._smooth_prev = None

    def _series_value(self, mode, ago):
        mode = str(mode).upper()
        if mode == 'OPEN':
            return float(self.data.open[ago])
        if mode == 'LOW':
            return float(self.data.low[ago])
        if mode == 'HIGH':
            return float(self.data.high[ago])
        return float(self.data.close[ago])

    def _smooth_value(self, raw_value):
        method = str(self.p.xma_method).upper()
        if method in ('MODE_SMA_', 'SMA'):
            period = max(1, int(self.p.x_length))
            if len(self._raw_buf) < period:
                return raw_value
            return sum(self._raw_buf[-period:]) / float(period)

        length = max(1, int(self.p.x_length))
        phase = max(-100, min(100, int(self.p.x_phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if self._smooth_prev is None or not math.isfinite(self._smooth_prev):
            smooth = raw_value
        else:
            smooth = self._smooth_prev + alpha * (raw_value - self._smooth_prev)
        self._smooth_prev = smooth
        return smooth

    def next(self):
        up_period = int(self.p.up_period)
        dn_period = int(self.p.dn_period)
        if len(self.data) < max(up_period, dn_period):
            self.lines.value[0] = 0.0
            return

        highs = [self._series_value(self.p.up_mode, -i) for i in range(up_period)]
        lows = [self._series_value(self.p.dn_mode, -i) for i in range(dn_period)]
        ish_up = max(highs)
        ish_dn = min(lows)
        raw_value = (ish_up + ish_dn) / 2.0
        self._raw_buf.append(raw_value)
        smooth = self._smooth_value(raw_value) + float(self.p.price_shift)
        self.lines.value[0] = smooth


class TwoXmaIchimokuOscillator(bt.Indicator):
    lines = ('line', 'color',)

    params = dict(
        up_period1=6,
        dn_period1=6,
        up_period2=9,
        dn_period2=9,
        up_mode1='HIGH',
        dn_mode1='LOW',
        up_mode2='HIGH',
        dn_mode2='LOW',
        xma1_method='SMA',
        xma2_method='SMA',
        x_length1=25,
        x_length2=80,
        x_phase=15,
        point=0.01,
    )

    def __init__(self):
        self.xma1 = XmaIchimoku(
            self.data,
            up_period=self.p.up_period1,
            dn_period=self.p.dn_period1,
            up_mode=self.p.up_mode1,
            dn_mode=self.p.dn_mode1,
            xma_method=self.p.xma1_method,
            x_length=self.p.x_length1,
            x_phase=self.p.x_phase,
        )
        self.xma2 = XmaIchimoku(
            self.data,
            up_period=self.p.up_period2,
            dn_period=self.p.dn_period2,
            up_mode=self.p.up_mode2,
            dn_mode=self.p.dn_mode2,
            xma_method=self.p.xma2_method,
            x_length=self.p.x_length2,
            x_phase=self.p.x_phase,
        )
        self._prev_color = 2.0

    def next(self):
        point = float(self.p.point) if float(self.p.point) != 0 else 1.0
        line_value = (float(self.xma1[0]) - float(self.xma2[0])) / point
        self.lines.line[0] = line_value

        if len(self) < 2:
            self.lines.color[0] = 2.0
            self._prev_color = 2.0
            return

        prev_line = float(self.lines.line[-1])
        color = self._prev_color
        if line_value >= 0:
            if line_value > prev_line:
                color = 0.0
            elif line_value < prev_line:
                color = 1.0
        else:
            if line_value < prev_line:
                color = 4.0
            elif line_value > prev_line:
                color = 3.0
        self.lines.color[0] = color
        self._prev_color = color


class Exp2XmaIchimokuOscillatorStrategy(bt.Strategy):
    params = dict(
        mm=0.1,
        mm_mode='LOT',
        stop_loss_points=1000,
        take_profit_points=2000,
        deviation_points=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        up_period1=6,
        dn_period1=6,
        up_period2=9,
        dn_period2=9,
        up_mode1='HIGH',
        dn_mode1='LOW',
        up_mode2='HIGH',
        dn_mode2='LOW',
        xma1_method='SMA',
        xma2_method='SMA',
        x_length1=25,
        x_length2=80,
        x_phase=15,
        signal_bar=1,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.osc = TwoXmaIchimokuOscillator(
            self.data1,
            up_period1=self.p.up_period1,
            dn_period1=self.p.dn_period1,
            up_period2=self.p.up_period2,
            dn_period2=self.p.dn_period2,
            up_mode1=self.p.up_mode1,
            dn_mode1=self.p.dn_mode1,
            up_mode2=self.p.up_mode2,
            dn_mode2=self.p.dn_mode2,
            xma1_method=self.p.xma1_method,
            xma2_method=self.p.xma2_method,
            x_length1=self.p.x_length1,
            x_length2=self.p.x_length2,
            x_phase=self.p.x_phase,
            point=self.p.point,
        )
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_signal_dt = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, txt, dt=None):
        dt = dt or bt.num2date(self.data0.datetime[0])
        print(f'[{dt:%Y-%m-%d %H:%M}] {txt}')

    def _prepare_entry_levels(self, side, price):
        pt = float(self.p.point)
        sl_pts = int(self.p.stop_loss_points)
        tp_pts = int(self.p.take_profit_points)
        if side == 'long':
            self.stop_price = price - sl_pts * pt if sl_pts > 0 else None
            self.take_profit_price = price + tp_pts * pt if tp_pts > 0 else None
        else:
            self.stop_price = price + sl_pts * pt if sl_pts > 0 else None
            self.take_profit_price = price - tp_pts * pt if tp_pts > 0 else None
        self.entry_price = price

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG by SL stop={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG by TP target={self.take_profit_price:.5f}')
                return
        elif self.position.size < 0:
            if self.stop_price is not None and high >= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT by SL stop={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT by TP target={self.take_profit_price:.5f}')
                return

    def next(self):
        if self.order is not None:
            return
        sb = int(self.p.signal_bar)
        if len(self.data1) <= sb + 1:
            return

        self._check_exit_levels()
        if self.order is not None:
            return

        signal_dt = bt.num2date(self.data1.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        newer = float(self.osc.color[-sb])
        older = float(self.osc.color[-(sb + 1)])

        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        if older in (3.0, 0.0):
            if self.p.buy_pos_open and newer in (4.0, 1.0):
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True

        if older in (1.0, 4.0):
            if self.p.sell_pos_open and newer in (0.0, 3.0):
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True

        if self.position.size > 0 and buy_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE LONG by oscillator reversal')
            return
        if self.position.size < 0 and sell_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE SHORT by oscillator reversal')
            return

        if self.position:
            return

        price = float(self.data0.close[0])
        if buy_open:
            self.pending_action = 'open_long'
            self._prepare_entry_levels('long', price)
            self.order = self.buy(size=float(self.p.lot))
            self.log(f'OPEN LONG color_new={newer} color_old={older}')
            return
        if sell_open:
            self.pending_action = 'open_short'
            self._prepare_entry_levels('short', price)
            self.order = self.sell(size=float(self.p.lot))
            self.log(f'OPEN SHORT color_new={newer} color_old={older}')
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            action = self.pending_action or ''
            if action == 'open_long':
                self.buy_count += 1
            elif action == 'open_short':
                self.sell_count += 1
            self.pending_action = None
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.pending_action = None
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None

    def stop(self):
        total = self.trade_count
        wr = (self.win_count / total * 100.0) if total else 0.0
        print('========== Exp_2XMA_Ichimoku_Oscillator 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {self.trade_count}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('===========================================================')
