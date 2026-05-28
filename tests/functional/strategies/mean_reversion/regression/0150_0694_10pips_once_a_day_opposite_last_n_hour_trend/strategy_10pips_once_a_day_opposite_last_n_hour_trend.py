from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines if line.strip())
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
        df['openinterest'] = 0
    df['volume'] = df['tick_volume']
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class OnceADayOppositeTrendStrategy(bt.Strategy):
    params = dict(
        fix_lot=0.1,
        min_lot=0.1,
        max_lot=5.0,
        maximum_risk=0.05,
        trading_hour=7,
        hours_to_check_trend=30,
        pos_max_age_seconds=75600,
        first_multiplicator=4,
        second_multiplicator=2,
        third_multiplicator=5,
        fourth_multiplicator=5,
        fifth_multiplicator=1,
        stop_loss_pips=50,
        trailing_stop_pips=0,
        take_profit_pips=10,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._entry_dt = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._last_trade_bar_dt = None
        self._last_hour_marker = None
        self._hourly_closes = []
        self._closed_trade_pnls = []

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _round_lot(self, value):
        return round(float(value), 1)

    def _round_price(self, value):
        return round(float(value), int(self.p.price_digits))

    def _sync_position_state(self):
        if not self.position:
            self._entry_price = None
            self._entry_dt = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._entry_dt = bt.num2date(self.data.datetime[0])
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = float(self.p.stop_loss_pips) * pip_size
        take_distance = float(self.p.take_profit_pips) * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price + take_distance if take_distance > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price - take_distance if take_distance > 0 else None

    def _update_hourly_close_history(self):
        dt = bt.num2date(self.data.datetime[0])
        marker = (dt.year, dt.month, dt.day, dt.hour)
        if dt.minute != 0:
            return
        if marker == self._last_hour_marker:
            return
        self._hourly_closes.append(float(self.data.close[0]))
        self._last_hour_marker = marker

    def _get_lot(self):
        if float(self.p.fix_lot) == 0:
            lot = self._round_lot(self.broker.getcash() * float(self.p.maximum_risk) / 1000.0)
        else:
            lot = float(self.p.fix_lot)
        multipliers = [
            float(self.p.first_multiplicator),
            float(self.p.second_multiplicator),
            float(self.p.third_multiplicator),
            float(self.p.fourth_multiplicator),
            float(self.p.fifth_multiplicator),
        ]
        for idx, pnl in enumerate(reversed(self._closed_trade_pnls[-5:])):
            if pnl > 0:
                break
            if pnl < 0:
                lot *= multipliers[idx]
        free_margin_cap = self._round_lot(self.broker.getcash() / 1000.0)
        lot = min(lot, free_margin_cap)
        lot = max(lot, float(self.p.min_lot))
        lot = min(lot, float(self.p.max_lot))
        return self._round_lot(lot)

    def _check_max_age_exit(self):
        if not self.position or self._entry_dt is None:
            return False
        dt = bt.num2date(self.data.datetime[0])
        age_seconds = (dt - self._entry_dt).total_seconds()
        if age_seconds > float(self.p.pos_max_age_seconds):
            self.log(f'close on max age age_seconds={age_seconds:.0f}')
            self.order = self.close()
            return True
        return False

    def _check_trailing_stop(self):
        if not self.position or float(self.p.trailing_stop_pips) <= 0:
            return
        pip_size = self._pip_size()
        trail = float(self.p.trailing_stop_pips) * pip_size
        close = float(self.data.close[0])
        if self.position.size > 0:
            if close - self._entry_price > trail:
                candidate = self._round_price(close - trail)
                if self._stop_price is None or candidate > self._stop_price:
                    self._stop_price = candidate
        else:
            if self._entry_price - close > trail:
                candidate = self._round_price(close + trail)
                if self._stop_price is None or candidate < self._stop_price:
                    self._stop_price = candidate

    def _check_protective_exit(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'long protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'long protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'short protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'short protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def _trade_allowed(self):
        dt = bt.num2date(self.data.datetime[0])
        if self._last_trade_bar_dt == dt:
            return False
        if dt.minute != 0:
            return False
        if self.position:
            return False
        if dt.hour != int(self.p.trading_hour):
            return False
        if len(self._hourly_closes) <= int(self.p.hours_to_check_trend):
            return False
        return True

    def _check_for_open_position(self):
        if self._hourly_closes[-int(self.p.hours_to_check_trend)] > self._hourly_closes[-1]:
            return 1
        return -1

    def next(self):
        self.bar_num += 1
        self._update_hourly_close_history()
        if len(self.data) < 8:
            return
        if self.order is not None:
            return
        self._sync_position_state()
        if self.position:
            if self._check_max_age_exit():
                return
            self._check_trailing_stop()
            if self._check_protective_exit():
                return
        if not self._trade_allowed():
            return
        signal = self._check_for_open_position()
        lot = self._get_lot()
        self.signal_count += 1
        self._last_trade_bar_dt = bt.num2date(self.data.datetime[0])
        if signal > 0:
            self.log(f'open long opposite last {self.p.hours_to_check_trend}h trend lot={lot:.1f}')
            self.order = self.buy(size=lot)
            return
        self.log(f'open short opposite last {self.p.hours_to_check_trend}h trend lot={lot:.1f}')
        self.order = self.sell(size=lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        self._closed_trade_pnls.append(float(trade.pnlcomm))
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
