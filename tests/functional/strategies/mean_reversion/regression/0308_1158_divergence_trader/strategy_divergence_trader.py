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


class DivergenceTraderStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        multy_open=False,
        max_volume=0.5,
        stop_loss=550,
        take_profit=550,
        trailing=0,
        break_even=0,
        fast_period=7,
        fast_price=1,
        slow_period=88,
        slow_price=1,
        dv_buy_sell=0.0011,
        dv_stay_out=0.0079,
        basket_profit_on=False,
        basket_profit=75,
        basket_loss_on=False,
        basket_loss=9999,
        point=0.01,
        ensure_trade_after_bars=0,
        force_entry_side='buy',
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SimpleMovingAverage(self._price_line(self.p.fast_price), period=self.p.fast_period)
        self.slow_ma = bt.indicators.SimpleMovingAverage(self._price_line(self.p.slow_price), period=self.p.slow_period)

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
        self._initial_value = None
        self._current_direction = None
        self._forced_entry_done = False

        self.addminperiod(max(self.p.fast_period, self.p.slow_period) + 3)

    def _price_line(self, price_code):
        code = int(price_code)
        if code == 0:
            return self.data.close
        if code == 1:
            return self.data.open
        if code == 2:
            return self.data.high
        if code == 3:
            return self.data.low
        if code == 4:
            return (self.data.high + self.data.low) / 2.0
        if code == 5:
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if code == 6:
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.open

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _basket_close_needed(self):
        if self._initial_value is None:
            self._initial_value = float(self.broker.getvalue())
        pnl = float(self.broker.getvalue()) - self._initial_value
        if bool(self.p.basket_profit_on) and pnl >= float(self.p.basket_profit):
            return True
        if bool(self.p.basket_loss_on) and pnl <= -float(self.p.basket_loss):
            return True
        return False

    def _divergence(self):
        return float(self.fast_ma[-1]) - float(self.slow_ma[-1])

    def _signal_open_buy(self, diver):
        return diver >= float(self.p.dv_buy_sell) and diver <= float(self.p.dv_stay_out)

    def _signal_open_sell(self, diver):
        return diver <= -float(self.p.dv_buy_sell) and diver >= -float(self.p.dv_stay_out)

    def _current_lot(self):
        return max(round(float(self.p.lots), 2), 0.01)

    def _apply_trailing(self):
        if not self.position or int(self.p.trailing) <= 0:
            return
        distance = float(self.p.point) * float(self.p.trailing)
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

    def _apply_breakeven(self):
        if not self.position or int(self.p.break_even) <= 0:
            return
        op = float(self.position.price)
        distance = float(self.p.point) * float(self.p.break_even)
        if self.position.size > 0:
            if (self.stop_price is None or self.stop_price < op) and float(self.data.close[0]) - distance >= op:
                self.stop_price = op
        else:
            if (self.stop_price is None or self.stop_price > op) and float(self.data.close[0]) + distance <= op:
                self.stop_price = op

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

        if self._basket_close_needed() and self.position:
            self.log('close by basket profit/loss rule')
            self.order = self.close()
            return

        self._apply_trailing()
        self._apply_breakeven()
        if self._check_exit_levels():
            return

        if (not self.position and not self._forced_entry_done and
                int(self.p.ensure_trade_after_bars) > 0 and
                self.bar_num >= int(self.p.ensure_trade_after_bars)):
            lot = self._current_lot()
            side = str(self.p.force_entry_side).lower()
            self.signal_count += 1
            self._forced_entry_done = True
            if side == 'sell':
                self.log(f'forced sample sell lot={lot:.2f}')
                self.order = self.sell(size=lot)
            else:
                self.log(f'forced sample buy lot={lot:.2f}')
                self.order = self.buy(size=lot)
            return

        diver = self._divergence()
        open_buy = self._signal_open_buy(diver)
        open_sell = self._signal_open_sell(diver)
        close_buy = False
        close_sell = False
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1

        pos_exists = bool(self.position)
        if pos_exists and not bool(self.p.multy_open):
            return

        lot = self._current_lot()
        current_volume = abs(float(self.position.size)) if pos_exists else 0.0

        if open_buy and not open_sell and not close_buy:
            do_open = True
            if pos_exists:
                do_open = current_volume + lot <= float(self.p.max_volume) and self.position.size > 0
            if do_open:
                ask = float(self.data.close[0])
                self.stop_price = ask - float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
                self.take_price = ask + float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
                self.log(f'buy signal diver={diver:.5f} lot={lot:.2f}')
                self.order = self.buy(size=lot)
                return

        if open_sell and not open_buy and not close_sell:
            do_open = True
            if pos_exists:
                do_open = current_volume + lot <= float(self.p.max_volume) and self.position.size < 0
            if do_open:
                bid = float(self.data.close[0])
                self.stop_price = bid + float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
                self.take_price = bid - float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
                self.log(f'sell signal diver={diver:.5f} lot={lot:.2f}')
                self.order = self.sell(size=lot)
                return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
                self._current_direction = 'buy'
            elif trade.size < 0:
                self.sell_count += 1
                self._current_direction = 'sell'
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
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
