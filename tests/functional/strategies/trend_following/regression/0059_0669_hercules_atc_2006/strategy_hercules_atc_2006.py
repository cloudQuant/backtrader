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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class PercentEnvelope(bt.Indicator):
    lines = ('top', 'bot')
    params = dict(period=14, perc=1.0)

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data, period=int(self.p.period))
        self.addminperiod(int(self.p.period))

    def next(self):
        offset = float(self.p.perc) / 100.0
        ma = float(self.ma[0])
        self.lines.top[0] = ma * (1.0 + offset)
        self.lines.bot[0] = ma * (1.0 - offset)


class HerculesAtc2006Strategy(bt.Strategy):
    params = dict(
        lots=0.01,
        money_management=True,
        risk=2.5,
        trigger=38,
        trailing_stop=90,
        take_profit_1=210,
        take_profit_2=280,
        ma1_period=1,
        ma2_period=72,
        rsi_upper=55.0,
        rsi_lower=45.0,
        strict_breakout_filters=False,
        relaxed_trend_entry=True,
        blackout_period_hours=144,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
        base_compression=15,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.h1 = self.datas[1]
        self.h4 = self.datas[2]
        self.d1 = self.datas[3]

        self.ma_fast = bt.indicators.ExponentialMovingAverage(self.base.close, period=self.p.ma1_period)
        self.ma_slow = bt.indicators.SimpleMovingAverage(self.base.open, period=self.p.ma2_period)
        self.rsi_h1 = bt.indicators.RSI((self.h1.high + self.h1.low + self.h1.close) / 3.0, period=10)
        self.env_d1 = PercentEnvelope(self.d1.close, period=24, perc=0.99)
        self.env_h4 = PercentEnvelope(self.h4.close, period=96, perc=0.10)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.orders = []
        self.legs = []
        self.last_base_len = 0
        self.cross_price = None
        self.cross_dir = None
        self.cross_len = None
        self.blackout_until = None

    def _dt(self):
        return bt.num2date(self.base.datetime[0])

    def _point_value(self):
        return float(self.p.point)

    def _dynamic_lot(self):
        if not self.p.money_management:
            return float(self.p.lots)
        equity = float(self.broker.getvalue())
        lots = (equity * float(self.p.risk) / 100.0) / max(float(self.p.contract_multiplier), 1.0)
        return max(float(self.p.lots), round(lots, 2))

    def _bars_count_for_h10(self):
        return max(1, int(round(120 / float(self.p.base_compression))))

    def _high10h(self):
        count = min(self._bars_count_for_h10(), len(self.base) - 1)
        highs = [float(self.base.high[-i]) for i in range(1, count + 1)]
        return max(highs) if highs else float(self.base.high[-1])

    def _low10h(self):
        count = min(self._bars_count_for_h10(), len(self.base) - 1)
        lows = [float(self.base.low[-i]) for i in range(1, count + 1)]
        return min(lows) if lows else float(self.base.low[-1])

    def _detect_cross(self):
        if len(self.base) < 4:
            return
        fast1 = float(self.ma_fast[-1])
        fast2 = float(self.ma_fast[-2])
        fast3 = float(self.ma_fast[-3])
        slow1 = float(self.ma_slow[-1])
        slow2 = float(self.ma_slow[-2])
        slow3 = float(self.ma_slow[-3])
        if fast1 > slow1 and fast2 < slow2:
            self.cross_dir = 'long'
            self.cross_price = (fast1 + fast2 + slow1 + slow2) / 4.0
            self.cross_len = len(self.base) - 1
            return
        if fast2 > slow2 and fast3 < slow3:
            self.cross_dir = 'long'
            self.cross_price = (fast2 + fast3 + slow2 + slow3) / 4.0
            self.cross_len = len(self.base) - 2
            return
        if fast1 < slow1 and fast2 > slow2:
            self.cross_dir = 'short'
            self.cross_price = (fast1 + fast2 + slow1 + slow2) / 4.0
            self.cross_len = len(self.base) - 1
            return
        if fast2 < slow2 and fast3 > slow3:
            self.cross_dir = 'short'
            self.cross_price = (fast2 + fast3 + slow2 + slow3) / 4.0
            self.cross_len = len(self.base) - 2

    def _countdown_active(self):
        if self.cross_len is None:
            return False
        return (len(self.base) - self.cross_len) <= 2

    def _can_trade(self):
        return self.blackout_until is None or self._dt() >= self.blackout_until

    def _trigger_price(self):
        if self.cross_price is None or self.cross_dir is None:
            return None
        if self.cross_dir == 'long':
            return self.cross_price + float(self.p.trigger) * self._point_value()
        return self.cross_price - float(self.p.trigger) * self._point_value()

    def _clear_orders(self):
        self.orders = [o for o in self.orders if o.alive()]

    def _net_leg_size(self, side):
        return sum(leg['size'] for leg in self.legs if leg['side'] == side)

    def _open_two_legs(self, side):
        size = self._dynamic_lot()
        price = float(self.base.close[0])
        if side == 'long':
            stop = float(self.base.low[-4]) if len(self.base) > 4 else float(self.base.low[0])
            tp1 = round(price + float(self.p.take_profit_1) * self._point_value(), int(self.p.price_digits))
            tp2 = round(price + float(self.p.take_profit_2) * self._point_value(), int(self.p.price_digits))
            self.orders.append(self.buy(size=size))
            self.orders.append(self.buy(size=size))
        else:
            stop = float(self.base.high[-4]) if len(self.base) > 4 else float(self.base.high[0])
            tp1 = round(price - float(self.p.take_profit_1) * self._point_value(), int(self.p.price_digits))
            tp2 = round(price - float(self.p.take_profit_2) * self._point_value(), int(self.p.price_digits))
            self.orders.append(self.sell(size=size))
            self.orders.append(self.sell(size=size))
        self.signal_count += 1
        self.legs.extend([
            {'side': side, 'size': size, 'entry_hint': price, 'stop': round(stop, int(self.p.price_digits)), 'tp': tp1, 'opened': False},
            {'side': side, 'size': size, 'entry_hint': price, 'stop': round(stop, int(self.p.price_digits)), 'tp': tp2, 'opened': False},
        ])
        self.blackout_until = self._dt() + pd.Timedelta(hours=float(self.p.blackout_period_hours))

    def _apply_trailing(self):
        if not self.legs:
            return
        trail = float(self.p.trailing_stop) * self._point_value()
        if trail <= 0:
            return
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        for leg in self.legs:
            if not leg['opened'] or leg['size'] <= 0:
                continue
            if leg['side'] == 'long':
                stopcal = round(high - trail, int(self.p.price_digits))
                if leg['stop'] is None or stopcal > float(leg['stop']):
                    leg['stop'] = stopcal
            else:
                stopcal = round(low + trail, int(self.p.price_digits))
                if leg['stop'] is None or stopcal < float(leg['stop']):
                    leg['stop'] = stopcal

    def _manage_legs(self):
        if not self.legs:
            return
        self._apply_trailing()
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        new_legs = []
        close_orders = []
        for leg in self.legs:
            if not leg['opened'] or leg['size'] <= 0:
                new_legs.append(leg)
                continue
            exit_now = False
            if leg['side'] == 'long':
                if leg['tp'] is not None and high >= float(leg['tp']):
                    exit_now = True
                elif leg['stop'] is not None and low <= float(leg['stop']):
                    exit_now = True
                if exit_now:
                    close_orders.append(self.sell(size=leg['size']))
                else:
                    new_legs.append(leg)
            else:
                if leg['tp'] is not None and low <= float(leg['tp']):
                    exit_now = True
                elif leg['stop'] is not None and high >= float(leg['stop']):
                    exit_now = True
                if exit_now:
                    close_orders.append(self.buy(size=leg['size']))
                else:
                    new_legs.append(leg)
        if close_orders:
            self.orders.extend(close_orders)
        self.legs = new_legs

    def next(self):
        self.bar_num += 1
        self._clear_orders()
        self._manage_legs()
        if len(self.base) == self.last_base_len:
            return
        self.last_base_len = len(self.base)
        if len(self.base) < 100 or len(self.h1) < 12 or len(self.h4) < 100 or len(self.d1) < 30:
            return
        if self.legs or self.orders:
            return
        rsi = float(self.rsi_h1[0])
        if bool(self.p.relaxed_trend_entry):
            fast = float(self.ma_fast[0])
            slow = float(self.ma_slow[0])
            if fast >= slow:
                self._open_two_legs('long')
            else:
                self._open_two_legs('short')
            return
        self._detect_cross()
        if not self._can_trade():
            return
        if not self._countdown_active():
            if bool(self.p.relaxed_trend_entry):
                fast = float(self.ma_fast[0])
                slow = float(self.ma_slow[0])
                if fast > slow and rsi > float(self.p.rsi_upper):
                    self._open_two_legs('long')
                elif fast < slow and rsi < float(self.p.rsi_lower):
                    self._open_two_legs('short')
            return
        trigger_price = self._trigger_price()
        if trigger_price is None:
            return
        enu = float(self.env_d1.top[0])
        enl = float(self.env_d1.bot[0])
        enu2 = float(self.env_h4.top[0])
        enl2 = float(self.env_h4.bot[0])
        high10h = self._high10h()
        low10h = self._low10h()
        ask = float(self.base.close[0])
        bid = float(self.base.close[0])
        if self.cross_dir == 'long' and ask >= trigger_price:
            long_ok = rsi > float(self.p.rsi_upper)
            if bool(self.p.strict_breakout_filters):
                long_ok = long_ok and ask > high10h and ask > enu and ask > enu2
            if long_ok:
                self._open_two_legs('long')
        elif self.cross_dir == 'short' and bid <= trigger_price:
            short_ok = rsi < float(self.p.rsi_lower)
            if bool(self.p.strict_breakout_filters):
                short_ok = short_ok and bid < low10h and bid < enl and bid < enl2
            if short_ok:
                self._open_two_legs('short')

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if order.executed.size > 0:
                self.buy_count += 1
                for leg in self.legs:
                    if leg['side'] == 'long' and not leg['opened']:
                        leg['opened'] = True
                        leg['entry_hint'] = order.executed.price
                        break
            elif order.executed.size < 0:
                self.sell_count += 1
                for leg in self.legs:
                    if leg['side'] == 'short' and not leg['opened']:
                        leg['opened'] = True
                        leg['entry_hint'] = order.executed.price
                        break
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
