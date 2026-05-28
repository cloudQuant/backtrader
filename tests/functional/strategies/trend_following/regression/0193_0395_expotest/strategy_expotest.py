import math
import backtrader as bt


class ExpotestStrategy(bt.Strategy):
    params = dict(
        signal_timeframe='M15',
        sl_points=150,
        tp_points=200,
        volume=0.0,
        risk=0.13,
        magic=7505,
        slippage_points=30,
        sar_step=0.02,
        sar_maximum=0.2,
        point=0.01,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
        contract_size=100.0,
        margin_per_lot=1000.0,
        loss_multiplier=2.0,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.sar = bt.indicators.ParabolicSAR(
            self.signal_data,
            af=float(self.p.sar_step),
            afmax=float(self.p.sar_maximum),
        )
        self.order = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.last_trade_pnl = None
        self.last_trade_size = None
        self.current_size = None
        self.last_signal_dt = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, txt, dt=None):
        dt = dt or bt.num2date(self.data0.datetime[0])
        print(f'[{dt:%Y-%m-%d %H:%M}] {txt}')

    def _normalize_lot(self, lot):
        step = max(float(self.p.lot_step), 0.0001)
        min_lot = float(self.p.min_lot)
        max_lot = float(self.p.max_lot)
        lot = max(min_lot, min(max_lot, float(lot)))
        steps = math.floor(lot / step)
        return round(max(min_lot, min(max_lot, steps * step)), 8)

    def _calc_lot(self):
        if float(self.p.volume) > 0:
            lot = float(self.p.volume)
        else:
            margin_per_lot = max(float(self.p.margin_per_lot), 1.0)
            maximum_risk = float(self.p.risk) / 100.0
            free_margin = self.broker.getcash()
            lot = free_margin * maximum_risk / margin_per_lot
        lot = self._normalize_lot(lot)
        if self.last_trade_pnl is not None and self.last_trade_pnl < 0 and self.last_trade_size is not None:
            lot = self._normalize_lot(float(self.last_trade_size) * float(self.p.loss_multiplier))
        return lot

    def _prepare_levels(self, side, price):
        point = float(self.p.point)
        sl = int(self.p.sl_points)
        tp = int(self.p.tp_points)
        if side == 'long':
            self.stop_price = price - sl * point if sl > 0 else None
            self.take_profit_price = price + tp * point if tp > 0 else None
        else:
            self.stop_price = price + sl * point if sl > 0 else None
            self.take_profit_price = price - tp * point if tp > 0 else None
        self.entry_price = price

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                self.log(f'CLOSE LONG by SL stop={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                self.log(f'CLOSE LONG by TP target={self.take_profit_price:.5f}')
                return
        if self.position.size < 0:
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                self.log(f'CLOSE SHORT by SL stop={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                self.log(f'CLOSE SHORT by TP target={self.take_profit_price:.5f}')
                return

    def next(self):
        if len(self.signal_data) < 2:
            return
        self._check_exit()
        if self.order is not None or self.position:
            return

        signal_dt = bt.num2date(self.signal_data.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        sar_value = float(self.sar[0])
        ask_like = float(self.signal_data.close[0])
        signal = 0
        if sar_value <= ask_like:
            signal = 1
        elif sar_value >= ask_like:
            signal = -1
        if signal == 0:
            return

        size = self._calc_lot()
        self.current_size = size
        price = float(self.data0.close[0])
        if signal > 0:
            self._prepare_levels('long', price)
            self.order = self.buy(size=size)
            self.buy_count += 1
            self.log(f'OPEN LONG size={size:.2f} sar={sar_value:.5f} price={price:.5f}')
        else:
            self._prepare_levels('short', price)
            self.order = self.sell(size=size)
            self.sell_count += 1
            self.log(f'OPEN SHORT size={size:.2f} sar={sar_value:.5f} price={price:.5f}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            self.order = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.last_trade_pnl = trade.pnlcomm
        self.last_trade_size = abs(trade.size) if trade.size else self.current_size
        if trade.pnlcomm > 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.current_size = None
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} equity={self.broker.getvalue():.2f}')

    def stop(self):
        total = self.trade_count
        wr = (self.win_count / total * 100.0) if total else 0.0
        print('========== Expotest 策略结束 ==========' )
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {self.trade_count}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('=====================================')
