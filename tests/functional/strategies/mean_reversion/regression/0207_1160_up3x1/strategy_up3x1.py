from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class Up3x1Strategy(bt.Strategy):
    params = dict(
        maximum_risk=0.05,
        lots=0.1,
        decrease_factor=0.0,
        take_profit=150,
        stop_loss=100,
        trailing_stop=100,
        fast_period=24,
        fast_shift=6,
        middle_period=60,
        middle_shift=6,
        slow_period=120,
        slow_shift=6,
        point=0.01,
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.fast_period)
        self.middle_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.middle_period)
        self.slow_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.slow_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.stop_price = None
        self.take_price = None
        self._position_was_open = False
        self._closed_trade_pnls = []

        self.addminperiod(max(self.p.fast_period + self.p.fast_shift, self.p.middle_period + self.p.middle_shift, self.p.slow_period + self.p.slow_shift) + 3)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        return max(round(float(lot), 2), 0.01)

    def _loss_streak(self):
        losses = 0
        for pnl in reversed(self._closed_trade_pnls):
            if pnl > 0:
                break
            if pnl < 0:
                losses += 1
        return losses

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.maximum_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        if float(self.p.decrease_factor) > 0:
            losses = self._loss_streak()
            if losses > 1:
                lot = lot - lot * losses / float(self.p.decrease_factor)
        return self._normalize_lot(lot)

    def _ma_values(self):
        fi0 = -(int(self.p.fast_shift))
        fi1 = -(int(self.p.fast_shift) + 1)
        mi0 = -(int(self.p.middle_shift))
        mi1 = -(int(self.p.middle_shift) + 1)
        si0 = -(int(self.p.slow_shift))
        si1 = -(int(self.p.slow_shift) + 1)
        return (
            float(self.fast_ma[fi0]), float(self.fast_ma[fi1]),
            float(self.middle_ma[mi0]), float(self.middle_ma[mi1]),
            float(self.slow_ma[si0]), float(self.slow_ma[si1]),
        )

    def _apply_trailing(self):
        if not self.position or int(self.p.trailing_stop) <= 0:
            return
        distance = float(self.p.point) * float(self.p.trailing_stop)
        if self.position.size > 0:
            new_stop = float(self.data.close[0]) - distance
            if new_stop >= float(self.position.price):
                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop
        else:
            new_stop = float(self.data.close[0]) + distance
            if new_stop <= float(self.position.price):
                if self.stop_price is None or new_stop < self.stop_price:
                    self.stop_price = new_stop

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        self._apply_trailing()
        if self._check_exit_levels():
            return

        f0, f1, m0, m1, s0, s1 = self._ma_values()
        open_buy = f1 < m1 and m0 < f0 and m1 < s1 and f0 < s0
        open_sell = f1 > m1 and m0 > f0 and m1 > s1 and f0 > s0
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1

        if self.position:
            return

        lot = self._current_lot()
        if open_buy and not open_sell:
            ask = float(self.data.close[0])
            self.stop_price = ask - float(self.p.point) * float(self.p.stop_loss)
            self.take_price = ask + float(self.p.point) * float(self.p.take_profit)
            self.log(f'buy signal fast={f0:.5f} middle={m0:.5f} slow={s0:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy:
            bid = float(self.data.close[0])
            self.stop_price = bid + float(self.p.point) * float(self.p.stop_loss)
            self.take_price = bid - float(self.p.point) * float(self.p.take_profit)
            self.log(f'sell signal fast={f0:.5f} middle={m0:.5f} slow={s0:.5f} lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.stop_price = None
                self.take_price = None
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
            elif trade.size < 0:
                self.sell_count += 1
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
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
