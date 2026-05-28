import backtrader as bt
import math


class KwanRdpIndicator(bt.Indicator):
    lines = ('kwan', 'direction',)

    params = dict(
        demarker_period=14,
        mfi_period=14,
        volume_type='TICK',
        momentum_period=14,
        momentum_price='CLOSE',
        xma_method='JJMA',
        x_length=7,
        x_phase=100,
    )

    def __init__(self):
        self.addminperiod(max(self.p.demarker_period, self.p.mfi_period, self.p.momentum_period) + self.p.x_length + 5)
        self._high_buf = []
        self._low_buf = []
        self._close_buf = []
        self._typical_buf = []
        self._money_flow_buf = []
        self._raw_buf = []
        self._smooth_prev = None
        self._smooth_buf = []

    def _select_price(self, mode):
        mode = str(mode).upper()
        if mode == 'OPEN':
            return float(self.data.open[0])
        if mode == 'HIGH':
            return float(self.data.high[0])
        if mode == 'LOW':
            return float(self.data.low[0])
        if mode == 'MEDIAN':
            return (float(self.data.high[0]) + float(self.data.low[0])) / 2.0
        if mode == 'TYPICAL':
            return (float(self.data.high[0]) + float(self.data.low[0]) + float(self.data.close[0])) / 3.0
        if mode == 'WEIGHTED':
            return (float(self.data.high[0]) + float(self.data.low[0]) + 2.0 * float(self.data.close[0])) / 4.0
        return float(self.data.close[0])

    def _calc_demarker(self):
        p = int(self.p.demarker_period)
        if len(self._high_buf) <= p or len(self._low_buf) <= p:
            return None
        demax = []
        demin = []
        for i in range(len(self._high_buf) - p, len(self._high_buf)):
            high_diff = self._high_buf[i] - self._high_buf[i - 1]
            low_diff = self._low_buf[i - 1] - self._low_buf[i]
            demax.append(max(high_diff, 0.0))
            demin.append(max(low_diff, 0.0))
        smax = sum(demax)
        smin = sum(demin)
        denom = smax + smin
        if denom == 0:
            return 0.5
        return smax / denom

    def _calc_mfi(self):
        p = int(self.p.mfi_period)
        if len(self._typical_buf) <= p or len(self._money_flow_buf) <= p:
            return None
        pos_flow = 0.0
        neg_flow = 0.0
        start = len(self._typical_buf) - p
        for i in range(start, len(self._typical_buf)):
            prev_tp = self._typical_buf[i - 1]
            curr_tp = self._typical_buf[i]
            curr_flow = self._money_flow_buf[i]
            if curr_tp > prev_tp:
                pos_flow += curr_flow
            elif curr_tp < prev_tp:
                neg_flow += curr_flow
        if neg_flow == 0:
            return 100.0
        money_ratio = pos_flow / neg_flow
        return 100.0 - (100.0 / (1.0 + money_ratio))

    def _calc_momentum(self):
        p = int(self.p.momentum_period)
        if len(self._close_buf) <= p:
            return None
        prev_price = self._close_buf[-(p + 1)]
        curr_price = self._select_price(self.p.momentum_price)
        if prev_price == 0:
            return None
        return 100.0 * curr_price / prev_price

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
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        close = float(self.data.close[0])
        volume = float(self.data.volume[0]) if math.isfinite(float(self.data.volume[0])) else 0.0

        self._high_buf.append(high)
        self._low_buf.append(low)
        self._close_buf.append(close)
        typical = (high + low + close) / 3.0
        self._typical_buf.append(typical)
        self._money_flow_buf.append(typical * volume)

        demarker = self._calc_demarker()
        mfi = self._calc_mfi()
        momentum = self._calc_momentum()
        if demarker is None or mfi is None or momentum is None:
            self.lines.kwan[0] = 0.0
            self.lines.direction[0] = 1.0
            return

        if momentum == 0 or not math.isfinite(momentum):
            raw_value = 100.0
        else:
            raw_value = 100.0 * demarker * mfi / momentum
        self._raw_buf.append(raw_value)

        smooth = self._smooth_value(raw_value)
        self._smooth_buf.append(smooth)
        self.lines.kwan[0] = smooth

        if len(self._smooth_buf) < 2:
            self.lines.direction[0] = 1.0
            return

        prev_smooth = self._smooth_buf[-2]
        if smooth > prev_smooth:
            self.lines.direction[0] = 0.0
        elif smooth < prev_smooth:
            self.lines.direction[0] = 2.0
        else:
            self.lines.direction[0] = 1.0


class ExpKwanRdpStrategy(bt.Strategy):
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
        demarker_period=14,
        mfi_period=14,
        volume_type='TICK',
        momentum_period=14,
        momentum_price='CLOSE',
        xma_method='JJMA',
        x_length=7,
        x_phase=100,
        signal_bar=1,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.kwan = KwanRdpIndicator(
            self.data1,
            demarker_period=self.p.demarker_period,
            mfi_period=self.p.mfi_period,
            volume_type=self.p.volume_type,
            momentum_period=self.p.momentum_period,
            momentum_price=self.p.momentum_price,
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

    @staticmethod
    def _finite(v):
        if v is None:
            return None
        try:
            if not math.isfinite(v):
                return None
        except (TypeError, ValueError):
            return None
        return v

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
        if not self.position:
            return
        price = float(self.data0.close[0])
        if self.position.size > 0:
            if self.stop_price is not None and price <= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG by SL  price={price:.5f} sl={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and price >= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG by TP  price={price:.5f} tp={self.take_profit_price:.5f}')
                return
        elif self.position.size < 0:
            if self.stop_price is not None and price >= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT by SL  price={price:.5f} sl={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and price <= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT by TP  price={price:.5f} tp={self.take_profit_price:.5f}')
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

        newer_dir = self._finite(self.kwan.direction[-sb])
        older_dir = self._finite(self.kwan.direction[-(sb + 1)])
        if newer_dir is None or older_dir is None:
            return

        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        if newer_dir == 0.0 and older_dir != 0.0:
            if self.p.buy_pos_open:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True

        if newer_dir == 2.0 and older_dir != 2.0:
            if self.p.sell_pos_open:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True

        if self.position.size > 0 and buy_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE LONG by KWAN reversal')
            return
        if self.position.size < 0 and sell_close:
            self.pending_action = 'close'
            self.order = self.close()
            self.log('CLOSE SHORT by KWAN reversal')
            return

        if self.position:
            return

        if buy_open:
            self.pending_action = 'open_long'
            self.order = self.buy(size=float(self.p.lot))
            self._prepare_entry_levels('long', float(self.data0.close[0]))
            self.log(f'OPEN LONG  dir_new={newer_dir} dir_old={older_dir}')
            return
        if sell_open:
            self.pending_action = 'open_short'
            self.order = self.sell(size=float(self.p.lot))
            self._prepare_entry_levels('short', float(self.data0.close[0]))
            self.log(f'OPEN SHORT dir_new={newer_dir} dir_old={older_dir}')
            return

    def notify_order(self, order):
        if order.status in [order.Completed]:
            action = self.pending_action or ''
            if 'open_long' in action:
                self.buy_count += 1
            elif 'open_short' in action:
                self.sell_count += 1
            self.pending_action = None
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.pending_action = None
            self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
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
        wr = (self.win_count / total * 100) if total > 0 else 0
        print('========== Exp_KWAN_RDP 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {total}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('=============================================')
