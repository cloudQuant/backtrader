import math
import backtrader as bt


class AverageChangeCandle(bt.Indicator):
    lines = ('open_line', 'high_line', 'low_line', 'close_line', 'color',)

    params = dict(
        ma_method1='LWMA',
        length1=12,
        phase1=15,
        ipc1='PRICE_MEDIAN_',
        ma_method2='JJMA',
        length2=5,
        phase2=100,
        pow_value=5.0,
    )

    def __init__(self):
        self.addminperiod(max(int(self.p.length1), int(self.p.length2)) + 10)
        self._base_buf = []
        self._o_buf = []
        self._h_buf = []
        self._l_buf = []
        self._c_buf = []
        self._base_prev = None
        self._o_prev = None
        self._h_prev = None
        self._l_prev = None
        self._c_prev = None

    def _price_series(self):
        mode = str(self.p.ipc1).upper()
        o = float(self.data.open[0])
        h = float(self.data.high[0])
        l = float(self.data.low[0])
        c = float(self.data.close[0])
        if mode == 'PRICE_OPEN_':
            return o
        if mode == 'PRICE_HIGH_':
            return h
        if mode == 'PRICE_LOW_':
            return l
        if mode == 'PRICE_TYPICAL_':
            return (h + l + c) / 3.0
        if mode == 'PRICE_WEIGHTED_':
            return (h + l + c + c) / 4.0
        if mode == 'PRICE_SIMPL_':
            return (o + c) / 2.0
        if mode == 'PRICE_QUARTER_':
            return (h + l + o + c) / 4.0
        if mode == 'PRICE_DEMARK_':
            return (h + l + 2.0 * c) / 4.0
        return (h + l) / 2.0

    def _smooth(self, raw_value, method, length, phase, buf, prev_value_attr):
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
            denom = float(sum(weights))
            return sum(v * w for v, w in zip(values, weights)) / denom

        prev = getattr(self, prev_value_attr)
        phase = max(-100, min(100, int(phase)))
        alpha = 2.0 / (length + 1.0)
        alpha *= 1.0 + 0.35 * (phase / 100.0)
        alpha = max(0.01, min(0.99, alpha))
        if prev is None or not math.isfinite(prev):
            smooth = raw_value
        else:
            smooth = prev + alpha * (raw_value - prev)
        setattr(self, prev_value_attr, smooth)
        return smooth

    def next(self):
        base_price = self._price_series()
        self._base_buf.append(base_price)
        xma = self._smooth(
            base_price,
            self.p.ma_method1,
            self.p.length1,
            self.p.phase1,
            self._base_buf,
            '_base_prev',
        )
        xma = xma if xma != 0 else 1e-12

        power = float(self.p.pow_value)
        o_raw = math.pow(float(self.data.open[0]) / xma, power)
        h_raw = math.pow(float(self.data.high[0]) / xma, power)
        l_raw = math.pow(float(self.data.low[0]) / xma, power)
        c_raw = math.pow(float(self.data.close[0]) / xma, power)

        self._o_buf.append(o_raw)
        self._h_buf.append(h_raw)
        self._l_buf.append(l_raw)
        self._c_buf.append(c_raw)

        o_val = self._smooth(o_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._o_buf, '_o_prev')
        h_val = self._smooth(h_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._h_buf, '_h_prev')
        l_val = self._smooth(l_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._l_buf, '_l_prev')
        c_val = self._smooth(c_raw, self.p.ma_method2, self.p.length2, self.p.phase2, self._c_buf, '_c_prev')

        max_body = max(o_val, c_val)
        min_body = min(o_val, c_val)
        h_val = max(max_body, h_val)
        l_val = min(min_body, l_val)

        if o_val < c_val:
            color = 2.0
        elif o_val > c_val:
            color = 0.0
        else:
            color = 1.0

        self.lines.open_line[0] = o_val
        self.lines.high_line[0] = h_val
        self.lines.low_line[0] = l_val
        self.lines.close_line[0] = c_val
        self.lines.color[0] = color


class ExpAverageChangeCandleStrategy(bt.Strategy):
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
        ma_method1='LWMA',
        length1=12,
        phase1=15,
        ipc1='PRICE_MEDIAN_',
        ma_method2='JJMA',
        length2=5,
        phase2=100,
        pow_value=5.0,
        signal_bar=1,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.ind = AverageChangeCandle(
            self.data1,
            ma_method1=self.p.ma_method1,
            length1=self.p.length1,
            phase1=self.p.phase1,
            ipc1=self.p.ipc1,
            ma_method2=self.p.ma_method2,
            length2=self.p.length2,
            phase2=self.p.phase2,
            pow_value=self.p.pow_value,
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

        current_color = float(self.ind.color[-sb])
        prev_color = float(self.ind.color[-(sb + 1)])

        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        if prev_color == 2.0:
            if self.p.buy_pos_open and current_color != 2.0:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True

        if prev_color == 0.0:
            if self.p.sell_pos_open and current_color != 0.0:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True

        if self.position.size > 0 and buy_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE LONG by candle reversal')
            return
        if self.position.size < 0 and sell_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE SHORT by candle reversal')
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
        print('========== Exp_AverageChangeCandle 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {self.trade_count}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('=====================================================')
