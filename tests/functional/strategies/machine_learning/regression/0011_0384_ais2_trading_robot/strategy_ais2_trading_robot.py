import backtrader as bt


class Ais2TradingRobotStrategy(bt.Strategy):
    params = dict(
        account_reserve=0.20,
        order_reserve=0.04,
        symbol='EURUSD',
        take_factor=1.7,
        stop_factor=1.7,
        trail_factor=0.5,
        lot_min=0.01,
        lot_step=0.01,
        lot_max=5.0,
        margin_per_lot=1000.0,
        contract_size=100.0,
        point=0.0001,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.data2 = self.datas[2] if len(self.datas) > 2 else self.data0
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

    def _round_lot(self, size):
        lot_min = float(self.p.lot_min)
        lot_step = float(self.p.lot_step)
        lot_max = float(self.p.lot_max)
        if size < lot_min:
            return 0.0
        steps = int((size - lot_min) // lot_step)
        rounded = lot_min + steps * lot_step
        return max(lot_min, min(lot_max, rounded))

    def _compute_position_size(self, quote_risk):
        if quote_risk <= 0:
            return 0.0
        equity = float(self.broker.getvalue())
        var_limit = equity * float(self.p.order_reserve)
        point = max(float(self.p.point), 1e-6)
        contract_size = max(float(self.p.contract_size), 1e-6)
        risk_points = max(1.0, quote_risk / point)
        nominal_point_value = contract_size * point
        size_limit = var_limit / (risk_points * nominal_point_value)
        return self._round_lot(size_limit)

    def _manage_trailing(self, quote_trail, trail_step):
        if not self.position or self.order is not None:
            return
        if quote_trail <= 0:
            return
        if self.position.size > 0:
            if float(self.data0.close[0]) <= self.entry_price:
                return
            new_stop = float(self.data0.close[0]) - quote_trail
            if self.stop_price is None or new_stop - self.stop_price > trail_step:
                if new_stop < float(self.data0.close[0]):
                    self.stop_price = new_stop
                    self.log(f'TRAIL LONG stop={self.stop_price:.5f}')
        elif self.position.size < 0:
            if float(self.data0.close[0]) >= self.entry_price:
                return
            new_stop = float(self.data0.close[0]) + quote_trail
            if self.stop_price is None or self.stop_price - new_stop > trail_step:
                if new_stop > float(self.data0.close[0]):
                    self.stop_price = new_stop
                    self.log(f'TRAIL SHORT stop={self.stop_price:.5f}')

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data0.high[0])
        low = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG by stop={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE LONG by take={self.take_profit_price:.5f}')
                return
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT by stop={self.stop_price:.5f}')
                return
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.pending_action = 'close'
                self.order = self.close()
                self.log(f'CLOSE SHORT by take={self.take_profit_price:.5f}')
                return

    def next(self):
        if self.order is not None:
            return
        if len(self.data1) < 2 or len(self.data2) < 2:
            return

        low_1 = float(self.data1.low[-1])
        high_1 = float(self.data1.high[-1])
        close_1 = float(self.data1.close[-1])
        low_2 = float(self.data2.low[-1])
        high_2 = float(self.data2.high[-1])
        range_1 = high_1 - low_1
        range_2 = high_2 - low_2
        average_1 = (high_1 + low_1) / 2.0
        quote_take = range_1 * float(self.p.take_factor)
        quote_stop = range_1 * float(self.p.stop_factor)
        quote_trail = range_2 * float(self.p.trail_factor)
        trail_step = float(self.p.point) * 2.0

        self._manage_trailing(quote_trail, trail_step)
        self._check_exit_levels()
        if self.order is not None:
            return

        signal_dt = bt.num2date(self.data1.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        if self.position:
            return

        ask = float(self.data0.close[0])
        bid = float(self.data0.close[0])

        command = None
        price = None
        stop = None
        take = None

        if close_1 > average_1 and ask > high_1:
            price = ask
            stop = high_1 - quote_stop
            take = ask + quote_take
            if take > price and stop < price:
                command = 'buy'

        if close_1 < average_1 and bid < low_1:
            price = bid
            stop = low_1 + quote_stop
            take = bid - quote_take
            if take < price and stop > price:
                command = 'sell'

        if command is None:
            return

        size = self._compute_position_size(abs(price - stop))
        if size <= 0:
            return

        self.entry_price = price
        self.stop_price = stop
        self.take_profit_price = take

        if command == 'buy':
            self.pending_action = 'open_long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} price={price:.5f} stop={stop:.5f} take={take:.5f}')
        else:
            self.pending_action = 'open_short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} price={price:.5f} stop={stop:.5f} take={take:.5f}')

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
        print('========== AIS2 Trading Robot 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {self.trade_count}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('================================================')
