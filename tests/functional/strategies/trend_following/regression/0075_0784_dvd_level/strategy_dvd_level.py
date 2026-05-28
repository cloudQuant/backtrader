from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class DvdLevelStrategy(bt.Strategy):
    params = dict(
        account_is_mini=True,
        money_management=True,
        relaxed_market_entry=False,
        min_score=50.0,
        use_trailing_stop=False,
        trade_size_percent=10.0,
        lots=0.01,
        max_lots=4.0,
        stop_loss=210,
        take_profit=18,
        margin_cutoff=300.0,
        slippage=40,
        point=0.01,
        point_multiplier=10.0,
        price_digits=2,
    )

    def __init__(self):
        self.m15 = self.datas[0]
        self.m30 = self.datas[1]
        self.h1 = self.datas[2]
        self.d1 = self.datas[3]

        self.h1_ema2 = bt.indicators.ExponentialMovingAverage(self.h1.close, period=2)
        self.h1_ema24 = bt.indicators.ExponentialMovingAverage(self.h1.close, period=24)
        self.d1_ema2 = bt.indicators.ExponentialMovingAverage(self.d1.close, period=2)
        self.d1_ema24 = bt.indicators.ExponentialMovingAverage(self.d1.close, period=24)

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.entry_order = None
        self.pending_setup = None
        self.stop_price = None
        self.take_profit_price = None
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.m15.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip(self):
        return self.p.point * self.p.point_multiplier

    def _ravi(self, fast, slow, idx=0):
        slow_value = float(slow[idx])
        if slow_value == 0:
            return 0.0
        return ((float(fast[idx]) - slow_value) / slow_value) * 100.0

    def _valid_time(self):
        dt = bt.num2date(self.m15.datetime[0])
        return not (dt.weekday() == 0 and dt.hour <= 6)

    def _enough_history(self):
        return len(self.m15) >= 40 and len(self.m30) >= 10 and len(self.h1) >= 20 and len(self.d1) >= 30

    def _get_lots(self):
        if self.p.money_management:
            lot = math.floor(self.broker.get_cash() * self.p.trade_size_percent / 1000.0) / 100.0
            if self.p.account_is_mini:
                lot = math.floor(lot * 100.0) / 100.0
                lot = max(lot, 0.1)
                lot = min(lot, self.p.max_lots)
            else:
                lot = max(lot, 1.0)
                lot = min(lot, self.p.max_lots)
            return round(lot, 2)
        lot = self.p.lots
        if self.p.account_is_mini:
            if lot > 1.0:
                lot = lot / 10.0
            if lot < 0.1:
                lot = 0.1
        return round(lot, 2)

    def _check_risk_exit(self):
        if not self.position:
            return False
        high_price = round(float(self.m15.high[0]), self.p.price_digits)
        low_price = round(float(self.m15.low[0]), self.p.price_digits)
        if self.position.size > 0:
            if self.stop_price is not None and low_price <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.2f}')
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and high_price >= self.take_profit_price:
                self.log(f'close long by take_profit={self.take_profit_price:.2f}')
                self.entry_order = self.close()
                return True
        else:
            if self.stop_price is not None and high_price >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.2f}')
                self.entry_order = self.close()
                return True
            if self.take_profit_price is not None and low_price <= self.take_profit_price:
                self.log(f'close short by take_profit={self.take_profit_price:.2f}')
                self.entry_order = self.close()
                return True
        return False

    def _handle_trailing(self):
        if not self.position or not self.p.use_trailing_stop:
            return
        pip = self._pip()
        if self.position.size > 0:
            is_go_hi = any(
                float(self.m15.high[-(x + 3)]) - float(self.m15.low[-x]) > 500 * self.p.point and
                float(self.m15.close[-x]) < float(self.m15.open[-(x + 3)])
                for x in range(31)
            )
            if self.position.price > float(self.m15.close[0]) and is_go_hi and self.take_profit_price is not None and self.take_profit_price > self.position.price + 50 * self.p.point:
                self.take_profit_price = round(self.position.price + 10 * self.p.point, self.p.price_digits)
        else:
            is_go_hi = any(
                float(self.m15.high[-x]) - float(self.m15.low[-(x + 3)]) > 500 * self.p.point and
                float(self.m15.close[-x]) > float(self.m15.open[-(x + 3)])
                for x in range(31)
            )
            if self.position.price < float(self.m15.close[0]) and is_go_hi and self.take_profit_price is not None and self.take_profit_price < self.position.price - 50 * self.p.point:
                self.take_profit_price = round(self.position.price - 10 * self.p.point, self.p.price_digits)

    def _buy_condition(self):
        bal = 0.0
        ravi_h1 = self._ravi(self.h1_ema2, self.h1_ema24)
        ravi_d1 = self._ravi(self.d1_ema2, self.d1_ema24)
        close_now = float(self.m15.close[0])
        if ravi_h1 < 0.0:
            bal += 10
        level100 = round(close_now + 50 * self.p.point, self.p.price_digits)
        if float(self.h1.high[-1]) > level100 + 700 * self.p.point or float(self.h1.high[-2]) > level100 + 700 * self.p.point:
            bal += 7
        if (
            close_now < level100 and
            float(self.m15.close[-1]) > level100 and
            float(self.h1.low[0]) > level100 - 50 * self.p.point + 30 * self.p.point and
            float(self.h1.low[-1]) > level100 - 50 * self.p.point + 30 * self.p.point and
            float(self.h1.low[-2]) > level100 - 50 * self.p.point
        ):
            bal += 45
        for x in range(12):
            if float(self.m15.high[-x]) > level100 + 600 * self.p.point:
                bal -= 50
        for x in range(31):
            if (
                float(self.m15.high[-(x + 3)]) - float(self.m15.low[-x]) > 300 * self.p.point and
                float(self.m15.open[-(x + 3)]) > float(self.m15.close[-x]) and
                ravi_d1 < -2
            ):
                bal -= 50
        is_cross = any(float(self.h1.high[-x]) > level100 + 450 * self.p.point for x in range(15))
        if not is_cross:
            bal -= 50
        if all(float(self.m30.high[-x]) < level100 + 250 * self.p.point for x in range(8)):
            bal -= 50
        return bal >= float(self.p.min_score), bal, level100

    def _sell_condition(self):
        bal = 0.0
        ravi_h1 = self._ravi(self.h1_ema2, self.h1_ema24)
        ravi_d1 = self._ravi(self.d1_ema2, self.d1_ema24)
        close_now = float(self.m15.close[0])
        if ravi_h1 > 0.0:
            bal += 10
        level100 = round(close_now - 50 * self.p.point, self.p.price_digits)
        if float(self.h1.low[-1]) < level100 - 700 * self.p.point or float(self.h1.low[-2]) < level100 - 700 * self.p.point:
            bal += 7
        if (
            close_now > level100 and
            float(self.m15.close[-1]) < level100 and
            float(self.h1.high[0]) < level100 + 50 * self.p.point - 30 * self.p.point and
            float(self.h1.high[-1]) < level100 + 50 * self.p.point - 30 * self.p.point and
            float(self.h1.high[-2]) < level100 + 50 * self.p.point
        ):
            bal += 45
        for x in range(12):
            if float(self.m15.low[-x]) < level100 - 600 * self.p.point:
                bal -= 50
        for x in range(31):
            if (
                float(self.m15.high[-x]) - float(self.m15.low[-(x + 3)]) > 300 * self.p.point and
                float(self.m15.close[-x]) > float(self.m15.open[-(x + 3)]) and
                ravi_d1 > 2
            ):
                bal -= 50
        is_cross = any(float(self.h1.low[-x]) < level100 - 450 * self.p.point for x in range(15))
        if not is_cross:
            bal -= 50
        if all(float(self.m30.low[-x]) > level100 - 250 * self.p.point for x in range(8)):
            bal -= 50
        return bal >= float(self.p.min_score), bal, level100

    def _place_buy_limit(self, bal):
        pip = self._pip()
        price = round(float(self.m15.close[0]) - 10 * pip, self.p.price_digits)
        tp = round(price + self.p.take_profit * pip, self.p.price_digits)
        ravi_d1 = self._ravi(self.d1_ema2, self.d1_ema24)
        if 1 < ravi_d1 < 5 and self._ravi(self.d1_ema2, self.d1_ema24, -1) < ravi_d1 and self._ravi(self.d1_ema2, self.d1_ema24, -2) < self._ravi(self.d1_ema2, self.d1_ema24, -1) and self._ravi(self.d1_ema2, self.d1_ema24, -3) < self._ravi(self.d1_ema2, self.d1_ema24, -2):
            tp = round(tp + 25 * pip, self.p.price_digits)
        sl = round(price - self.p.stop_loss * pip, self.p.price_digits)
        valid = bt.num2date(self.m15.datetime[0]) + pd.Timedelta(minutes=20)
        size = self._get_lots()
        self.pending_setup = dict(side='buy', stop=sl, take_profit=tp, score=bal)
        self.log(f'place buy limit price={price:.2f} sl={sl:.2f} tp={tp:.2f} score={bal:.2f} size={size:.2f}')
        if self.p.relaxed_market_entry:
            self.entry_order = self.buy(size=size)
            return
        self.entry_order = self.buy(size=size, exectype=bt.Order.Limit, price=price, valid=valid)

    def _place_sell_limit(self, bal):
        pip = self._pip()
        price = round(float(self.m15.close[0]) + 7 * pip, self.p.price_digits)
        tp = round(price - self.p.take_profit * pip, self.p.price_digits)
        ravi_d1 = self._ravi(self.d1_ema2, self.d1_ema24)
        if -5 < ravi_d1 < -1 and self._ravi(self.d1_ema2, self.d1_ema24, -1) > ravi_d1 and self._ravi(self.d1_ema2, self.d1_ema24, -2) > self._ravi(self.d1_ema2, self.d1_ema24, -1) and self._ravi(self.d1_ema2, self.d1_ema24, -3) > self._ravi(self.d1_ema2, self.d1_ema24, -2):
            tp = round(tp - 25 * pip, self.p.price_digits)
        sl = round(price + self.p.stop_loss * pip, self.p.price_digits)
        valid = bt.num2date(self.m15.datetime[0]) + pd.Timedelta(minutes=20)
        size = self._get_lots()
        self.pending_setup = dict(side='sell', stop=sl, take_profit=tp, score=bal)
        self.log(f'place sell limit price={price:.2f} sl={sl:.2f} tp={tp:.2f} score={bal:.2f} size={size:.2f}')
        if self.p.relaxed_market_entry:
            self.entry_order = self.sell(size=size)
            return
        self.entry_order = self.sell(size=size, exectype=bt.Order.Limit, price=price, valid=valid)

    def next(self):
        self.bar_num += 1
        if not self._enough_history():
            return
        if self.entry_order is not None:
            return

        if self.position:
            if self._check_risk_exit():
                return
            self._handle_trailing()
            return

        if not self._valid_time():
            return
        if self.broker.get_cash() < self.p.margin_cutoff:
            return

        buy_ok, buy_score, _ = self._buy_condition()
        sell_ok, sell_score, _ = self._sell_condition()
        if buy_ok:
            self._place_buy_limit(buy_score)
            return
        if sell_ok:
            self._place_sell_limit(sell_score)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
                if self.pending_setup:
                    self.stop_price = self.pending_setup['stop']
                    self.take_profit_price = self.pending_setup['take_profit']
                self.log(f'entry filled price={order.executed.price:.2f} size={order.executed.size:.2f}')
            else:
                self.log(f'position closed price={order.executed.price:.2f} size={order.executed.size:.2f}')
                self.stop_price = None
                self.take_profit_price = None
                self.pending_setup = None
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.log(f'order failed status={order.getstatusname()}')
            self.pending_setup = None
        if self.entry_order is not None and order.ref == self.entry_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.entry_order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
