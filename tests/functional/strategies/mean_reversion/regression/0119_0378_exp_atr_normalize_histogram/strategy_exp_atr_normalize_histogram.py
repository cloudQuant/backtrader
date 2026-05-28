import math
import backtrader as bt


class AtrNormalizeHistogram(bt.Indicator):
    lines = ('value', 'color')
    params = dict(
        ma_method1='SMA',
        length1=14,
        phase1=15,
        ma_method2='SMA',
        length2=14,
        phase2=15,
        high_level=60,
        middle_level=50,
        low_level=40,
        point=0.01,
    )

    def __init__(self):
        self._diff_buf = []
        self._range_buf = []
        self._diff_prev = None
        self._range_prev = None
        self.addminperiod(max(int(self.p.length1), int(self.p.length2)) + 5)

    def _smooth(self, raw_value, method, length, phase, buf, prev_attr):
        method = str(method).upper()
        length = max(1, int(length))
        if method in ('MODE_SMA_', 'SMA'):
            if len(buf) < length:
                return raw_value
            return sum(buf[-length:]) / float(length)
        if method in ('MODE_LWMA_', 'LWMA'):
            if len(buf) < length:
                return raw_value
            weights = list(range(1, length + 1))
            values = buf[-length:]
            return sum(v * w for v, w in zip(values, weights)) / float(sum(weights))

        prev = getattr(self, prev_attr)
        phase = max(-100, min(100, int(phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if prev is None or not math.isfinite(prev):
            smooth = raw_value
        else:
            smooth = prev + alpha * (raw_value - prev)
        setattr(self, prev_attr, smooth)
        return smooth

    def next(self):
        prev_close = float(self.data.close[-1]) if len(self.data) > 1 else float(self.data.close[0])
        diff = float(self.data.close[0]) - float(self.data.low[0])
        range_value = max(float(self.data.high[0]), prev_close) - min(float(self.data.low[0]), prev_close)
        self._diff_buf.append(diff)
        self._range_buf.append(range_value)
        xdiff = self._smooth(diff, self.p.ma_method1, self.p.length1, self.p.phase1, self._diff_buf, '_diff_prev')
        xrange = self._smooth(range_value, self.p.ma_method2, self.p.length2, self.p.phase2, self._range_buf, '_range_prev')
        xrange = max(xrange, float(self.p.point))
        value = 100.0 * xdiff / xrange
        if value > float(self.p.high_level):
            color = 0.0
        elif value > float(self.p.middle_level):
            color = 1.0
        elif value < float(self.p.low_level):
            color = 4.0
        elif value < float(self.p.middle_level):
            color = 3.0
        else:
            color = 2.0
        self.lines.value[0] = value
        self.lines.color[0] = color


class ExpAtrNormalizeHistogramStrategy(bt.Strategy):
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
        ma_method1='SMA',
        length1=14,
        phase1=15,
        ma_method2='SMA',
        length2=14,
        phase2=15,
        high_level=60,
        middle_level=50,
        low_level=40,
        signal_bar=1,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.hist = AtrNormalizeHistogram(
            self.data1,
            ma_method1=self.p.ma_method1,
            length1=self.p.length1,
            phase1=self.p.phase1,
            ma_method2=self.p.ma_method2,
            length2=self.p.length2,
            phase2=self.p.phase2,
            high_level=self.p.high_level,
            middle_level=self.p.middle_level,
            low_level=self.p.low_level,
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
        else:
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

        current_color = float(self.hist.color[-sb])
        prev_color = float(self.hist.color[-(sb + 1)])

        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        if prev_color == 0.0:
            if self.p.buy_pos_open and current_color != 0.0:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True

        if prev_color == 4.0:
            if self.p.sell_pos_open and current_color != 4.0:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True

        if self.position.size > 0 and buy_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE LONG by histogram color reversal')
            return
        if self.position.size < 0 and sell_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE SHORT by histogram color reversal')
            return

        if self.position:
            return

        price = float(self.data0.close[0])
        if buy_open:
            self.pending_action = 'open_long'
            self._prepare_entry_levels('long', price)
            self.order = self.buy(size=float(self.p.lot))
            self.log(f'OPEN LONG prev_color={prev_color} current_color={current_color}')
            return
        if sell_open:
            self.pending_action = 'open_short'
            self._prepare_entry_levels('short', price)
            self.order = self.sell(size=float(self.p.lot))
            self.log(f'OPEN SHORT prev_color={prev_color} current_color={current_color}')
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
        print('========== Exp_ATR_Normalize_Histogram 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {self.trade_count}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('=========================================================')
