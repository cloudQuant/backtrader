from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class NevalyashkaBreakdownLevelStrategy(bt.Strategy):
    params = dict(
        time_start='07:26',
        time_end='09:13',
        use_time_close=False,
        time_close='23:30',
        lot=0.1,
        k_martin=2.0,
        no_loss=False,
        point=0.0001,
        price_digits=5,
    )

    def __init__(self):
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.order = None
        self.stop_price = None
        self.take_profit_price = None
        self.trade_day = None
        self.pending_reversal = None
        self.active_lot = float(self.p.lot)
        self.last_exit_reason = None
        self.last_loss_distance = None
        self.entry_direction = None

    def _hhmm_to_minutes(self, value):
        hour, minute = [int(x) for x in str(value).split(':')]
        return hour * 60 + minute

    def _now_minutes(self):
        dt = self.data.datetime.datetime(0)
        return dt.hour * 60 + dt.minute

    def _today_key(self):
        return self.data.datetime.date(0).isoformat()

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _today_range(self):
        current_date = self.data.datetime.date(0)
        start_minutes = self._hhmm_to_minutes(self.p.time_start)
        end_minutes = self._hhmm_to_minutes(self.p.time_end)
        highs = []
        lows = []
        for i in range(len(self.data)):
            idx = -i
            dt = self.data.datetime.datetime(idx)
            if dt.date() != current_date:
                break
            mins = dt.hour * 60 + dt.minute
            if start_minutes <= mins <= end_minutes:
                highs.append(float(self.data.high[idx]))
                lows.append(float(self.data.low[idx]))
        if not highs:
            return None, None
        return max(highs), min(lows)

    def _arm(self, direction, entry_price, stop_price, take_profit_price, lot):
        self.entry_direction = direction
        self.active_lot = float(lot)
        self.stop_price = self._round(stop_price) if stop_price is not None else None
        self.take_profit_price = self._round(take_profit_price) if take_profit_price is not None else None
        self.signal_count += 1
        if direction == 'buy':
            self.order = self.buy(size=float(lot))
        else:
            self.order = self.sell(size=float(lot))
        self.last_loss_distance = abs(float(entry_price) - float(stop_price)) if stop_price is not None else None

    def _maybe_breakeven(self):
        if not self.position or not self.p.no_loss or self.stop_price is None or self.take_profit_price is None:
            return
        entry = float(self.position.price)
        current = float(self.data.close[0])
        if self.position.size > 0:
            halfway = entry + (float(self.take_profit_price) - entry) / 2.0
            if current >= halfway and float(self.stop_price) < entry:
                self.stop_price = self._round(entry)
        else:
            halfway = entry - (entry - float(self.take_profit_price)) / 2.0
            if current <= halfway and float(self.stop_price) > entry:
                self.stop_price = self._round(entry)

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.last_exit_reason = 'tp'
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.last_exit_reason = 'sl'
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.last_exit_reason = 'tp'
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.last_exit_reason = 'sl'
                self.order = self.close()
                return

    def next(self):
        self.bar_num += 1
        if len(self) < 10:
            return
        if self.order is not None:
            return

        now_minutes = self._now_minutes()
        close_minutes = self._hhmm_to_minutes(self.p.time_close)
        end_minutes = self._hhmm_to_minutes(self.p.time_end)

        if self.p.use_time_close and now_minutes >= close_minutes:
            if self.position:
                self.last_exit_reason = 'time_close'
                self.order = self.close()
            return

        if self.position:
            self._maybe_breakeven()
            self._check_exit()
            return

        if self.pending_reversal is not None:
            direction = self.pending_reversal['direction']
            lot = self.pending_reversal['lot']
            distance = self.pending_reversal['distance']
            price = float(self.data.close[0])
            if direction == 'buy':
                self._arm(direction, price, price - distance, price + distance, lot)
            else:
                self._arm(direction, price, price + distance, price - distance, lot)
            self.pending_reversal = None
            return

        if now_minutes <= end_minutes or now_minutes >= close_minutes:
            return
        if self.trade_day == self._today_key():
            return

        max_price, min_price = self._today_range()
        if max_price is None or min_price is None or max_price <= min_price:
            return

        close_price = float(self.data.close[0])
        width = max_price - min_price
        if close_price > max_price:
            self._arm('buy', close_price, min_price, close_price + width, float(self.p.lot))
            return
        if close_price < min_price:
            self._arm('sell', close_price, max_price, close_price - width, float(self.p.lot))

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
            else:
                self.stop_price = None
                self.take_profit_price = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.trade_day = self._today_key()
        else:
            self.loss_count += 1
            if self.last_exit_reason == 'sl' and self.last_loss_distance is not None:
                next_direction = 'sell' if self.entry_direction == 'buy' else 'buy'
                self.pending_reversal = {
                    'direction': next_direction,
                    'lot': float(self.active_lot) * float(self.p.k_martin),
                    'distance': float(self.last_loss_distance),
                }
        self.last_exit_reason = None
