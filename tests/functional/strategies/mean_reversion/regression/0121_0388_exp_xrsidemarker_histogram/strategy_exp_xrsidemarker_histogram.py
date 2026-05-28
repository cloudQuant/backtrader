import math
import backtrader as bt


class DeMarker(bt.Indicator):
    lines = ('demarker',)
    params = dict(period=14)

    def __init__(self):
        self.addminperiod(self.p.period + 1)
        up_move = bt.If(self.data.high(0) - self.data.high(-1) > 0, self.data.high(0) - self.data.high(-1), 0.0)
        down_move = bt.If(self.data.low(-1) - self.data.low(0) > 0, self.data.low(-1) - self.data.low(0), 0.0)
        up_sum = bt.ind.SumN(up_move, period=self.p.period)
        down_sum = bt.ind.SumN(down_move, period=self.p.period)
        total = up_sum + down_sum
        self.lines.demarker = bt.If(total != 0, up_sum / total, 0.5)


class XrsiDeMarkerHistogram(bt.Indicator):
    lines = ('value',)
    params = dict(
        ind_period=14,
        rsi_price='close',
        high_level=60.0,
        low_level=40.0,
        xma_method='SMA',
        x_length=5,
        x_phase=15,
    )

    def __init__(self):
        self.rsi = bt.ind.RSI(self.data.close, period=self.p.ind_period)
        self.demarker = DeMarker(self.data, period=self.p.ind_period)
        self._raw_buf = []
        self._smooth_prev = None
        self.addminperiod(self.p.ind_period + self.p.x_length + 5)

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
        raw_value = (float(self.rsi[0]) + 100.0 * float(self.demarker.demarker[0])) / 2.0
        self._raw_buf.append(raw_value)
        self.lines.value[0] = self._smooth_value(raw_value)


class ExpXrsiDeMarkerHistogramStrategy(bt.Strategy):
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
        ind_period=14,
        rsi_price='close',
        high_level=60.0,
        low_level=40.0,
        xma_method='SMA',
        x_length=5,
        x_phase=15,
        signal_bar=1,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.hist = XrsiDeMarkerHistogram(
            self.data1,
            ind_period=self.p.ind_period,
            rsi_price=self.p.rsi_price,
            high_level=self.p.high_level,
            low_level=self.p.low_level,
            xma_method=self.p.xma_method,
            x_length=self.p.x_length,
            x_phase=self.p.x_phase,
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
        if len(self.data1) <= sb + 2:
            return

        self._check_exit_levels()
        if self.order is not None:
            return

        signal_dt = bt.num2date(self.data1.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        v0 = float(self.hist[-sb])
        v1 = float(self.hist[-(sb + 1)])
        v2 = float(self.hist[-(sb + 2)])

        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        if v1 < v2:
            if self.p.buy_pos_open and v0 >= v1:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True

        if v1 > v2:
            if self.p.sell_pos_open and v0 <= v1:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True

        if self.position.size > 0 and buy_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE LONG by histogram reversal')
            return
        if self.position.size < 0 and sell_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE SHORT by histogram reversal')
            return

        if self.position:
            return

        price = float(self.data0.close[0])
        if buy_open:
            self.pending_action = 'open_long'
            self._prepare_entry_levels('long', price)
            self.order = self.buy(size=float(self.p.lot))
            self.log(f'OPEN LONG hist0={v0:.2f} hist1={v1:.2f} hist2={v2:.2f}')
            return
        if sell_open:
            self.pending_action = 'open_short'
            self._prepare_entry_levels('short', price)
            self.order = self.sell(size=float(self.p.lot))
            self.log(f'OPEN SHORT hist0={v0:.2f} hist1={v1:.2f} hist2={v2:.2f}')
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
        print('========== Exp_XRSIDeMarker_Histogram 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {self.trade_count}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('=========================================================')
