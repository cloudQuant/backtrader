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
        '<OPEN>': 'open',
        '<HIGH>': 'high',
        '<LOW>': 'low',
        '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


def resample_daily(df):
    out = df.resample('1D', label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class BreakdownLevelDayStrategy(bt.Strategy):
    params = dict(
        time_set='07:32',
        delta=6,
        sl=120,
        tp=90,
        risk=0.0,
        no_loss=0,
        trailing=0,
        lot=0.10,
        open_stop=True,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        min_lot=0.01,
        max_lot=100.0,
        lot_precision=2,
        margin_per_lot=250.0,
        stop_level=0,
        last_day=0,
    )

    def __init__(self):
        self.day_data = self.datas[1]

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
        self.pending_order = None
        self.pending_side = None
        self.pending_price = None
        self.pending_stop = None
        self.pending_take = None
        self.pending_day = None
        self.current_day = None
        self.stop_price = None
        self.take_profit_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _effective_lot(self):
        if float(self.p.risk) == 0:
            return float(self.p.lot)
        free_margin = self.broker.getcash()
        lot = free_margin * float(self.p.risk) / 100.0 / float(self.p.margin_per_lot)
        lot = max(float(self.p.min_lot), min(float(self.p.max_lot), lot))
        return round(lot, int(self.p.lot_precision))

    def _time_match(self):
        if self.p.time_set == '00:00':
            return True
        current_dt = bt.num2date(self.data.datetime[0])
        return current_dt.strftime('%H:%M') == str(self.p.time_set)

    def _new_day(self):
        current_dt = bt.num2date(self.data.datetime[0])
        day_key = current_dt.date()
        changed = self.current_day != day_key
        self.current_day = day_key
        return changed

    def _cancel_pending(self):
        if self.pending_order is not None:
            self.cancel(self.pending_order)
        self.pending_order = None
        self.pending_side = None
        self.pending_price = None
        self.pending_stop = None
        self.pending_take = None
        self.pending_day = None

    def _set_position_risk(self, side, entry_price):
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(entry_price - float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None
            self.take_profit_price = round(entry_price + float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None
        else:
            self.stop_price = round(entry_price + float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None
            self.take_profit_price = round(entry_price - float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None

    def _place_stop_orders(self):
        if len(self.day_data) <= int(self.p.last_day):
            return
        day_high = float(self.day_data.high[-int(self.p.last_day)])
        day_low = float(self.day_data.low[-int(self.p.last_day)])
        unit = self._unit()
        stop_level = max(float(self.p.stop_level), 0.0) * unit
        buy_price = round(max(day_high + float(self.p.delta) * unit, float(self.data.close[0]) + stop_level), int(self.p.price_digits))
        sell_price = round(min(day_low - float(self.p.delta) * unit, float(self.data.close[0]) - stop_level), int(self.p.price_digits))
        self.pending_day = bt.num2date(self.data.datetime[0]).date()
        self.pending_side = 'both'
        self.pending_price = {'buy': buy_price, 'sell': sell_price}
        self.pending_stop = {
            'buy': round(buy_price - float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None,
            'sell': round(sell_price + float(self.p.sl) * unit, int(self.p.price_digits)) if self.p.sl > 0 else None,
        }
        self.pending_take = {
            'buy': round(buy_price + float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None,
            'sell': round(sell_price - float(self.p.tp) * unit, int(self.p.price_digits)) if self.p.tp > 0 else None,
        }
        self.signal_count += 1

    def _trigger_pending(self):
        if not self.pending_price or self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        size = self._effective_lot()
        if high >= self.pending_price['buy']:
            self._set_position_risk('buy', self.pending_price['buy'])
            self.order = self.buy(size=size)
            self.pending_side = 'buy'
            return True
        if low <= self.pending_price['sell']:
            self._set_position_risk('sell', self.pending_price['sell'])
            self.order = self.sell(size=size)
            self.pending_side = 'sell'
            return True
        return False

    def _apply_no_loss(self):
        if not self.position or self.p.no_loss == 0:
            return
        unit = self._unit()
        if self.position.size > 0:
            new_stop = round(float(self.data.close[0]) - float(self.p.no_loss) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop > self.stop_price and new_stop > self.position.price):
                self.stop_price = new_stop
        else:
            new_stop = round(float(self.data.close[0]) + float(self.p.no_loss) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop < self.stop_price and new_stop < self.position.price):
                self.stop_price = new_stop

    def _apply_trailing(self):
        if not self.position or self.p.trailing == 0:
            return
        unit = self._unit()
        if self.position.size > 0:
            new_stop = round(float(self.data.close[0]) - float(self.p.trailing) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop > self.stop_price and new_stop > self.position.price):
                self.stop_price = new_stop
        else:
            new_stop = round(float(self.data.close[0]) + float(self.p.trailing) * unit, int(self.p.price_digits))
            if self.stop_price is None or (new_stop < self.stop_price and new_stop < self.position.price):
                self.stop_price = new_stop

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        self._apply_trailing()
        self._apply_no_loss()
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        self._new_day()
        if self.order is not None:
            return
        if self.position:
            self._cancel_pending()
            self._manage_position()
            return
        self._trigger_pending()
        if self.pending_price:
            return
        if self._time_match():
            self._place_stop_orders()

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
                self.pending_price = None
                self.pending_stop = None
                self.pending_take = None
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
        else:
            self.loss_count += 1
