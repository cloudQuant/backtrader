from __future__ import absolute_import, division, print_function, unicode_literals

import datetime as dt
import math

import backtrader as bt


class TheRSIEngineStrategy(bt.Strategy):
    params = dict(
        use_risk_management=False,
        risk_percent=1.0,
        lots=0.1,
        stop_loss_points=300,
        take_profit_points=300,
        magic_number=1901,
        use_trailing_stop=True,
        trailing_stop_trigger=3000,
        trailing_stop_step=50,
        rsi_period=14,
        rsi_overbought=70,
        rsi_oversold=30,
        rsi_centerline=50,
        use_divergence_signal=True,
        use_overbought_oversold_reversal=True,
        use_centerline_confirmation=True,
        use_rsi_level_exit=False,
        divergence_lookback_bars=60,
        enable_daily_limits=True,
        daily_profit_target=10000.0,
        daily_loss_limit=5000.0,
        use_news_filter=False,
        news_time_hour=15,
        news_time_minute=30,
        minutes_before_news=10,
        minutes_after_news=10,
        enable_time_filter=False,
        monday_hours='16:30-18:00;09:00-11:00',
        tuesday_hours='16:30-18:00;09:00-11:00',
        wednesday_hours='16:30-18:00;09:00-11:00',
        thursday_hours='16:30-18:00;09:00-11:00',
        friday_hours='16:30-18:00;09:00-11:00',
        saturday_hours='00:00-00:00',
        sunday_hours='00:00-00:00',
        close_at_end_time=False,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.current_order = None
        self.stop_order = None
        self.limit_order = None
        self.current_session_state = True
        self.current_day = None
        self.day_start_value = None
        self.daily_limit_reached = False
        self.pending_direction = None

    def log(self, text):
        d = bt.num2date(self.data.datetime[0])
        print(f'{d.isoformat()}, {text}')

    def next(self):
        self.bar_num += 1
        now = bt.num2date(self.data.datetime[0])
        self._reset_daily_state_if_needed(now)
        self._manage_session_end(now)
        self._manage_trailing_stop()

        if self.position:
            self._manage_open_trades()
        else:
            self._check_for_entry_signals(now)

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order == self.current_order:
                if order.isbuy():
                    self.buy_count += 1
                    self.log(f'long entry price={order.executed.price:.2f} volume={order.executed.size:.4f}')
                else:
                    self.sell_count += 1
                    self.log(f'short entry price={order.executed.price:.2f} volume={abs(order.executed.size):.4f}')
            elif order == self.stop_order:
                self.log(f'stop executed price={order.executed.price:.2f}')
            elif order == self.limit_order:
                self.log(f'target executed price={order.executed.price:.2f}')
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            if order == self.current_order:
                self.current_order = None
            if order == self.stop_order:
                self.stop_order = None
            if order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')

    def _reset_daily_state_if_needed(self, now):
        if self.current_day != now.date():
            self.current_day = now.date()
            self.day_start_value = self.broker.getvalue()
            self.daily_limit_reached = False

    def _normalize_volume(self, volume):
        volume = max(self.p.lot_min, min(self.p.lot_max, volume))
        if self.p.lot_step > 0:
            volume = round(volume / self.p.lot_step) * self.p.lot_step
        volume = max(self.p.lot_min, min(self.p.lot_max, volume))
        return round(volume, 4)

    def _calculate_lot_size(self):
        if not self.p.use_risk_management:
            return self._normalize_volume(self.p.lots)
        if self.p.stop_loss_points <= 0:
            return 0.0
        equity = self.broker.getvalue()
        risk_amount = equity * (self.p.risk_percent / 100.0)
        stop_distance = self.p.stop_loss_points * self.p.point_size
        stop_loss_money_per_lot = stop_distance * self.p.contract_multiplier
        if stop_loss_money_per_lot <= 0:
            return 0.0
        lots = risk_amount / stop_loss_money_per_lot
        return self._normalize_volume(lots)

    def _is_daily_limit_reached(self):
        if not self.p.enable_daily_limits:
            return False
        if self.daily_limit_reached:
            return True
        current_value = self.broker.getvalue()
        todays_profit = current_value - (self.day_start_value if self.day_start_value is not None else current_value)
        if todays_profit >= self.p.daily_profit_target:
            self.daily_limit_reached = True
            return True
        if todays_profit <= -self.p.daily_loss_limit:
            self.daily_limit_reached = True
            return True
        return False

    def _session_string_for_day(self, weekday):
        mapping = {
            0: self.p.monday_hours,
            1: self.p.tuesday_hours,
            2: self.p.wednesday_hours,
            3: self.p.thursday_hours,
            4: self.p.friday_hours,
            5: self.p.saturday_hours,
            6: self.p.sunday_hours,
        }
        return mapping[weekday]

    def _is_within_trading_hours(self, now):
        if not self.p.enable_time_filter:
            return True
        current_minute = now.hour * 60 + now.minute
        hours_string = self._session_string_for_day(now.weekday())
        for session in hours_string.split(';'):
            if not session:
                continue
            parts = session.split('-')
            if len(parts) != 2:
                continue
            sh, sm = map(int, parts[0].split(':'))
            eh, em = map(int, parts[1].split(':'))
            start_minute = sh * 60 + sm
            end_minute = eh * 60 + em
            if current_minute >= start_minute and current_minute < end_minute:
                return True
        return False

    def _is_news_time_restricted(self, now):
        if not self.p.use_news_filter:
            return False
        event_time = now.replace(hour=self.p.news_time_hour, minute=self.p.news_time_minute, second=0, microsecond=0)
        start = event_time - dt.timedelta(minutes=self.p.minutes_before_news)
        end = event_time + dt.timedelta(minutes=self.p.minutes_after_news)
        return start <= now < end

    def _manage_session_end(self, now):
        if not self.p.close_at_end_time:
            return
        in_session = self._is_within_trading_hours(now)
        if self.current_session_state and not in_session and self.position:
            self.close()
        self.current_session_state = in_session

    def _manage_trailing_stop(self):
        if not self.position or not self.p.use_trailing_stop:
            return
        if self.p.trailing_stop_trigger <= 0 or self.p.trailing_stop_step <= 0:
            return
        if not self.stop_order or self.current_order:
            return
        current_price = self.data.close[0]
        entry_price = self.position.price
        trigger_distance = self.p.trailing_stop_trigger * self.p.point_size
        trail_distance = self.p.trailing_stop_step * self.p.point_size
        if self.position.size > 0:
            profit_distance = current_price - entry_price
            if profit_distance >= trigger_distance:
                new_stop = current_price - trail_distance
                current_stop = self.stop_order.created.price if self.stop_order.alive() else None
                if new_stop > entry_price and (current_stop is None or new_stop > current_stop):
                    self.cancel(self.stop_order)
                    self.stop_order = self.sell(exectype=bt.Order.Stop, price=new_stop, size=self.position.size)
        else:
            profit_distance = entry_price - current_price
            if profit_distance >= trigger_distance:
                new_stop = current_price + trail_distance
                current_stop = self.stop_order.created.price if self.stop_order.alive() else None
                if new_stop < entry_price and (current_stop is None or new_stop < current_stop):
                    self.cancel(self.stop_order)
                    self.stop_order = self.buy(exectype=bt.Order.Stop, price=new_stop, size=abs(self.position.size))

    def _manage_open_trades(self):
        if not self.p.use_rsi_level_exit:
            return
        current_rsi = self.rsi[0]
        if self.position.size > 0 and current_rsi >= self.p.rsi_overbought:
            self.close()
        elif self.position.size < 0 and current_rsi <= self.p.rsi_oversold:
            self.close()

    def _check_bullish_divergence(self):
        lookback = self.p.divergence_lookback_bars
        lookback_half = lookback // 2
        if len(self.data) < lookback + 5 or lookback_half <= 0:
            return False
        recent_range = range(1, lookback_half + 1)
        previous_range = range(lookback_half + 1, lookback + 1)
        recent_low_index = min(recent_range, key=lambda i: self.data.low[-i])
        previous_low_index = min(previous_range, key=lambda i: self.data.low[-i])
        recent_low_price = self.data.low[-recent_low_index]
        previous_low_price = self.data.low[-previous_low_index]
        rsi_recent = self.rsi[-recent_low_index]
        rsi_previous = self.rsi[-previous_low_index]
        return recent_low_price < previous_low_price and rsi_recent > rsi_previous and rsi_previous < self.p.rsi_oversold + 5

    def _check_bearish_divergence(self):
        lookback = self.p.divergence_lookback_bars
        lookback_half = lookback // 2
        if len(self.data) < lookback + 5 or lookback_half <= 0:
            return False
        recent_range = range(1, lookback_half + 1)
        previous_range = range(lookback_half + 1, lookback + 1)
        recent_high_index = max(recent_range, key=lambda i: self.data.high[-i])
        previous_high_index = max(previous_range, key=lambda i: self.data.high[-i])
        recent_high_price = self.data.high[-recent_high_index]
        previous_high_price = self.data.high[-previous_high_index]
        rsi_recent = self.rsi[-recent_high_index]
        rsi_previous = self.rsi[-previous_high_index]
        return recent_high_price > previous_high_price and rsi_recent < rsi_previous and rsi_previous > self.p.rsi_overbought - 5

    def _check_for_entry_signals(self, now):
        if self.current_order:
            return
        if self._is_daily_limit_reached():
            return
        if not self._is_within_trading_hours(now):
            return
        if self._is_news_time_restricted(now):
            return
        if len(self.data) < max(3, self.p.divergence_lookback_bars + 5):
            return
        bullish_divergence = self._check_bullish_divergence() if self.p.use_divergence_signal else False
        bearish_divergence = self._check_bearish_divergence() if self.p.use_divergence_signal else False
        bullish_reversal = self.p.use_overbought_oversold_reversal and self.rsi[-2] < self.p.rsi_oversold and self.rsi[-1] > self.p.rsi_oversold
        bearish_reversal = self.p.use_overbought_oversold_reversal and self.rsi[-2] > self.p.rsi_overbought and self.rsi[-1] < self.p.rsi_overbought
        bullish_signal = False
        bearish_signal = False
        if bullish_divergence or bullish_reversal:
            if self.p.use_centerline_confirmation:
                bullish_signal = self.rsi[-2] < self.p.rsi_centerline and self.rsi[-1] > self.p.rsi_centerline
            else:
                bullish_signal = True
        if bearish_divergence or bearish_reversal:
            if self.p.use_centerline_confirmation:
                bearish_signal = self.rsi[-2] > self.p.rsi_centerline and self.rsi[-1] < self.p.rsi_centerline
            else:
                bearish_signal = True
        lots = self._calculate_lot_size()
        if lots <= 0:
            return
        if bullish_signal:
            self._open_bracket('long', lots)
        elif bearish_signal:
            self._open_bracket('short', lots)

    def _open_bracket(self, direction, lots):
        price = self.data.close[0]
        sl_distance = self.p.stop_loss_points * self.p.point_size
        tp_distance = self.p.take_profit_points * self.p.point_size
        if direction == 'long':
            stop_price = 0 if self.p.stop_loss_points == 0 else price - sl_distance
            limit_price = 0 if self.p.take_profit_points == 0 else price + tp_distance
            orders = self.buy_bracket(size=lots, stopprice=stop_price if stop_price else None, limitprice=limit_price if limit_price else None)
        else:
            stop_price = 0 if self.p.stop_loss_points == 0 else price + sl_distance
            limit_price = 0 if self.p.take_profit_points == 0 else price - tp_distance
            orders = self.sell_bracket(size=lots, stopprice=stop_price if stop_price else None, limitprice=limit_price if limit_price else None)
        self.current_order = orders[0]
        self.stop_order = orders[1]
        self.limit_order = orders[2]
