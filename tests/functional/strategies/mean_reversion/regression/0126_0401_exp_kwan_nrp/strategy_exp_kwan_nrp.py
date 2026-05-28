"""
Backtrader 策略：Exp_KWAN_NRP
来源 EA：ea/0401_Exp_KWAN_NRP/Exp_KWAN_NRP.mq5
指标源码：ea/0401_Exp_KWAN_NRP/KWAN_NRP.mq5

核心逻辑
--------
1. 在信号时间框架 (默认 H1) 上计算复合指标 KWAN_NRP：
   kwan = Stochastic_Signal(%D) * RSI / MomentumOsc
   然后用 SMA(XLength) 平滑。
2. 判断平滑后指标方向：
   - 0 = 上升 (当前值 > 前值)
   - 2 = 下降 (当前值 < 前值)
   - 1 = 持平
3. 交易信号 (在 SignalBar 偏移处)：
   - 方向从 非0 变为 0 → BUY_Open  + SELL_Close
   - 方向从 非2 变为 2 → SELL_Open + BUY_Close
4. 单仓切换模型：先平反向仓再开新仓。
5. 固定 lot 近似原版 TradeAlgorithms.mqh 的账户级手数。
"""
import backtrader as bt
import math


class KwanNrpIndicator(bt.Indicator):
    """复合指标 KWAN_NRP = SMA( Stoch_%D * RSI / MomentumOsc, XLength )"""

    lines = ('kwan', 'direction',)

    params = dict(
        k_period=5,
        d_period=3,
        slowing=3,
        rsi_period=14,
        momentum_period=14,
        x_length=3,
    )

    def __init__(self):
        # --- Stochastic %D (signal line) ---
        stoch = bt.indicators.Stochastic(
            self.data,
            period=self.p.k_period,
            period_dfast=self.p.slowing,
            period_dslow=self.p.d_period,
        )
        self.stoch_d = stoch.percD

        # --- RSI ---
        self.rsi = bt.indicators.RSI(
            self.data.close,
            period=self.p.rsi_period,
        )

        # --- Momentum Oscillator  = 100 * close / close[-period] ---
        self.mom_osc = bt.indicators.MomentumOscillator(
            self.data.close,
            period=self.p.momentum_period,
        )

        # --- 原始 kwan ---
        # kwan_raw = stoch_d * rsi / mom_osc
        # 为防止 mom_osc 为 0 导致除零，后面在 next 中处理
        # 先占位一个 SMA 需要的 lines
        self.addminperiod(
            max(self.p.k_period + self.p.slowing + self.p.d_period,
                self.p.rsi_period,
                self.p.momentum_period)
            + self.p.x_length + 2
        )

        # 内部缓冲
        self._raw_buf = []

    def next(self):
        mom = self.mom_osc[0]
        if mom == 0 or not math.isfinite(mom):
            kwan_raw = 100.0
        else:
            kwan_raw = self.stoch_d[0] * self.rsi[0] / mom

        self._raw_buf.append(kwan_raw)

        # SMA 平滑
        xl = self.p.x_length
        if len(self._raw_buf) >= xl:
            smoothed = sum(self._raw_buf[-xl:]) / xl
        else:
            smoothed = kwan_raw

        self.lines.kwan[0] = smoothed

        # 方向判断
        if len(self._raw_buf) < xl + 1:
            self.lines.direction[0] = 1.0
            return

        prev_smoothed_vals = self._raw_buf[-(xl + 1):-1]
        if len(prev_smoothed_vals) >= xl:
            prev_smoothed = sum(prev_smoothed_vals[-xl:]) / xl
        else:
            prev_smoothed = smoothed

        if smoothed > prev_smoothed:
            self.lines.direction[0] = 0.0  # rising
        elif smoothed < prev_smoothed:
            self.lines.direction[0] = 2.0  # falling
        else:
            self.lines.direction[0] = 1.0  # flat


class ExpKwanNrpStrategy(bt.Strategy):
    """
    Backtrader 策略复现 Exp_KWAN_NRP。
    data0 = 执行时间框架 (如 M15)
    data1 = 信号时间框架 (如 H1)，可通过 resample 生成
    """

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
        # KWAN_NRP indicator params
        k_period=5,
        d_period=3,
        slowing=3,
        rsi_period=14,
        momentum_period=14,
        x_length=3,
        signal_bar=1,
        lot=0.10,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]

        self.kwan = KwanNrpIndicator(
            self.data1,
            k_period=self.p.k_period,
            d_period=self.p.d_period,
            slowing=self.p.slowing,
            rsi_period=self.p.rsi_period,
            momentum_period=self.p.momentum_period,
            x_length=self.p.x_length,
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

    # -----------------------------------------------------------------
    def log(self, txt, dt=None):
        dt = dt or bt.num2date(self.data0.datetime[0])
        print(f'[{dt:%Y-%m-%d %H:%M}] {txt}')

    # -----------------------------------------------------------------
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

    # -----------------------------------------------------------------
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

    # -----------------------------------------------------------------
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

    # -----------------------------------------------------------------
    def next(self):
        if self.order is not None:
            return

        # 信号时间框架数据长度检查
        sb = int(self.p.signal_bar)
        if len(self.data1) <= sb + 1:
            return

        # SL / TP 检查
        self._check_exit_levels()
        if self.order is not None:
            return

        # 每根信号 K 线只处理一次
        signal_dt = bt.num2date(self.data1.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        # 取 direction 值
        newer_dir = self._finite(self.kwan.direction[-sb])
        older_dir = self._finite(self.kwan.direction[-(sb + 1)])
        if newer_dir is None or older_dir is None:
            return

        buy_open = False
        sell_open = False
        buy_close = False
        sell_close = False

        # 方向从非0变为0 → BUY 信号
        if newer_dir == 0.0 and older_dir != 0.0:
            if self.p.buy_pos_open:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True

        # 方向从非2变为2 → SELL 信号
        if newer_dir == 2.0 and older_dir != 2.0:
            if self.p.sell_pos_open:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True

        # 先平仓
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

        # 无仓才开新仓
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

    # -----------------------------------------------------------------
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
        print('========== Exp_KWAN_NRP 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {total}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('=============================================')
