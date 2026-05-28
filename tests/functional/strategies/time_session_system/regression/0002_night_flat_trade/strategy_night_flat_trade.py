import backtrader as bt


class NightFlatTradeStrategy(bt.Strategy):
    params = dict(
        take_profit_pips=50,
        trailing_stop_pips=15,
        trailing_step_pips=5,
        diff_min_pips=18,
        diff_max_pips=28,
        open_hour=0,
        lots=0.0,
        risk=5.0,
        margin_per_lot=1000.0,
        point=0.01,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.data1 = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.order = None
        self.pending_action = None
        self.entry_price = None
        self.stop_price = None
        self.take_profit_price = None
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_signal_dt = None

    def log(self, txt, dt=None):
        dt = dt or bt.num2date(self.data0.datetime[0])
        print(f'[{dt:%Y-%m-%d %H:%M}] {txt}')

    def _pip_value(self):
        return float(self.p.point)

    def _calc_size(self):
        if float(self.p.lots) > 0:
            return float(self.p.lots)
        risk_pct = max(0.0, float(self.p.risk)) / 100.0
        cash = float(self.broker.getcash())
        if risk_pct <= 0 or cash <= 0:
            return 0.0
        size = (cash * risk_pct) / float(self.p.margin_per_lot)
        return max(0.01, round(size, 2))

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
        elif self.position.size < 0:
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

    def _apply_trailing(self):
        if not self.position:
            return
        pip = self._pip_value()
        trailing_stop = float(self.p.trailing_stop_pips) * pip
        trailing_step = float(self.p.trailing_step_pips) * pip
        if trailing_stop <= 0:
            return
        current = float(self.data0.close[0])
        if self.position.size > 0:
            if current - self.entry_price > trailing_stop + trailing_step:
                new_stop = current - trailing_stop
                if self.stop_price is None or new_stop > self.stop_price + trailing_step:
                    self.stop_price = new_stop
                    self.log(f'TRAIL LONG stop={self.stop_price:.5f}')
        else:
            if self.entry_price - current > trailing_stop + trailing_step:
                new_stop = current + trailing_stop
                if self.stop_price is None or new_stop < self.stop_price - trailing_step:
                    self.stop_price = new_stop
                    self.log(f'TRAIL SHORT stop={self.stop_price:.5f}')

    def next(self):
        if self.order is not None:
            return
        if len(self.data1) < 4:
            return

        self._apply_trailing()
        self._check_exit_levels()
        if self.order is not None:
            return

        signal_dt = bt.num2date(self.data1.datetime[0])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt

        hour = signal_dt.hour
        if hour < int(self.p.open_hour) or hour > int(self.p.open_hour) + 1:
            return
        if self.position:
            return

        highs = [float(self.data1.high[-i]) for i in range(3)]
        lows = [float(self.data1.low[-i]) for i in range(3)]
        highest = max(highs)
        lowest = min(lows)
        diff = highest - lowest

        pip = self._pip_value()
        diff_min = float(self.p.diff_min_pips) * pip
        diff_max = float(self.p.diff_max_pips) * pip
        if not (diff > diff_min and diff < diff_max):
            return

        bid = float(self.data0.close[0])
        ask = float(self.data0.close[0])
        size = self._calc_size()
        if size <= 0:
            return

        if bid > lowest and bid <= lowest + diff / 4.0:
            sl = lowest - diff / 3.0
            tp = ask + float(self.p.take_profit_pips) * pip if int(self.p.take_profit_pips) > 0 else None
            self.entry_price = ask
            self.stop_price = sl
            self.take_profit_price = tp
            self.pending_action = 'open_long'
            self.order = self.buy(size=size)
            self.log(f'OPEN LONG size={size:.2f} diff={diff:.5f} sl={sl:.5f} tp={tp if tp is not None else 0.0:.5f}')
            return

        if bid < highest and bid >= highest - diff / 4.0:
            sl = highest + diff / 3.0
            tp = bid - float(self.p.take_profit_pips) * pip if int(self.p.take_profit_pips) > 0 else None
            self.entry_price = bid
            self.stop_price = sl
            self.take_profit_price = tp
            self.pending_action = 'open_short'
            self.order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size:.2f} diff={diff:.5f} sl={sl:.5f} tp={tp if tp is not None else 0.0:.5f}')
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
        print('========== Night Flat Trade 策略结束 ==========')
        print(f'  买入次数: {self.buy_count}')
        print(f'  卖出次数: {self.sell_count}')
        print(f'  总交易数: {self.trade_count}')
        print(f'  盈利次数: {self.win_count}')
        print(f'  亏损次数: {self.loss_count}')
        print(f'  胜率:     {wr:.1f}%')
        print(f'  最终权益: {self.broker.getvalue():.2f}')
        print('==============================================')
