from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class TerminatorV20Strategy(bt.Strategy):
    params = dict(
        trade_on=True,
        lots=0.1,
        maximum_risk=0.05,
        stop_loss=2500,
        take_profit=500,
        take_profit2=100,
        max_count=10,
        double_count=5,
        pips=500,
        trailing=0,
        shift=1,
        reverse_condition=False,
        signal_mode='macd',
        macd_fast_period=14,
        macd_slow_period=26,
        macd_signal_period=1,
        macd_price='close',
        point=0.01,
    )

    def __init__(self):
        price_line = self._price_line(self.p.macd_price)
        self.macd = bt.indicators.MACD(
            price_line,
            period_me1=int(self.p.macd_fast_period),
            period_me2=int(self.p.macd_slow_period),
            period_signal=int(self.p.macd_signal_period),
        )

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.order_meta = {}
        self.current_exit_stop = None
        self.current_exit_take = None
        self.entry_index = 0
        self.start_lot = None
        self.last_entry_price = None
        self._position_was_open = False

        self.addminperiod(max(int(self.p.macd_slow_period), int(self.p.macd_signal_period)) + int(self.p.shift) + 3)

    def _price_line(self, price_code):
        name = str(price_code).lower()
        if name in ('close', 'price_close', '0'):
            return self.data.close
        if name in ('open', 'price_open', '1'):
            return self.data.open
        if name in ('high', 'price_high', '2'):
            return self.data.high
        if name in ('low', 'price_low', '3'):
            return self.data.low
        if name in ('median', 'price_median', '4'):
            return (self.data.high + self.data.low) / 2.0
        if name in ('typical', 'price_typical', '5'):
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if name in ('weighted', 'price_weighted', '6'):
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        return max(round(float(lot), 2), 0.01)

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.maximum_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        return self._normalize_lot(lot)

    def _signal_state(self):
        if str(self.p.signal_mode).lower() != 'macd':
            return False, False, 0.0, 0.0
        idx = -int(self.p.shift) if int(self.p.shift) > 0 else 0
        macd0 = float(self.macd.macd[idx])
        macd1 = float(self.macd.macd[idx - 1])
        buy_sig = macd0 > macd1
        sell_sig = macd0 < macd1
        if bool(self.p.reverse_condition):
            buy_sig, sell_sig = sell_sig, buy_sig
        return buy_sig, sell_sig, macd0, macd1

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.current_exit_stop is not None and low <= self.current_exit_stop:
                self.log(f'close long by stop={self.current_exit_stop:.5f}')
                self.order = self.close()
                self.order_meta[self.order.ref] = {'role': 'close'}
                return True
            if self.current_exit_take is not None and high >= self.current_exit_take:
                self.log(f'close long by take={self.current_exit_take:.5f}')
                self.order = self.close()
                self.order_meta[self.order.ref] = {'role': 'close'}
                return True
        else:
            if self.current_exit_stop is not None and high >= self.current_exit_stop:
                self.log(f'close short by stop={self.current_exit_stop:.5f}')
                self.order = self.close()
                self.order_meta[self.order.ref] = {'role': 'close'}
                return True
            if self.current_exit_take is not None and low <= self.current_exit_take:
                self.log(f'close short by take={self.current_exit_take:.5f}')
                self.order = self.close()
                self.order_meta[self.order.ref] = {'role': 'close'}
                return True
        return False

    def _apply_trailing(self):
        if int(self.p.trailing) <= 0 or not self.position:
            return
        trail_distance = float(self.p.point) * float(self.p.trailing)
        price = float(self.data.close[0])
        if self.position.size > 0:
            new_stop = price - trail_distance
            if new_stop >= float(self.position.price):
                if self.current_exit_stop is None or new_stop > self.current_exit_stop:
                    self.current_exit_stop = new_stop
        else:
            new_stop = price + trail_distance
            if new_stop <= float(self.position.price):
                if self.current_exit_stop is None or new_stop < self.current_exit_stop:
                    self.current_exit_stop = new_stop

    def _place_initial_order(self, side, lot, signal_value):
        point = float(self.p.point)
        tp_distance = int(self.p.take_profit)
        if side == 'buy':
            self.log(f'buy signal macd={signal_value:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
        else:
            self.log(f'sell signal macd={signal_value:.5f} lot={lot:.2f}')
            self.order = self.sell(size=lot)
        self.order_meta[self.order.ref] = {
            'role': 'entry',
            'kind': 'initial',
            'side': side,
            'index': 1,
            'stop_loss': int(self.p.stop_loss) if int(self.p.max_count) == 1 else 0,
            'take_profit': tp_distance,
            'point': point,
        }

    def _next_add_lot(self):
        base = self.start_lot if self.start_lot is not None else self._current_lot()
        index = self.entry_index
        k = int(self.p.double_count)
        lot = base * (2 ** min(index, max(k - 1, 0)))
        if index > k - 1:
            lot = lot * (1.5 ** (index - k + 1))
        return self._normalize_lot(lot)

    def _place_add_order(self, side, signal_value):
        lot = self._next_add_lot()
        next_index = self.entry_index + 1
        point = float(self.p.point)
        stop_loss = int(self.p.stop_loss) if int(self.p.max_count) != -1 and next_index == int(self.p.max_count) else 0
        take_profit = int(self.p.take_profit2)
        if side == 'buy':
            self.log(f'add buy signal macd={signal_value:.5f} index={next_index} lot={lot:.2f}')
            self.order = self.buy(size=lot)
        else:
            self.log(f'add sell signal macd={signal_value:.5f} index={next_index} lot={lot:.2f}')
            self.order = self.sell(size=lot)
        self.order_meta[self.order.ref] = {
            'role': 'entry',
            'kind': 'add',
            'side': side,
            'index': next_index,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'point': point,
        }

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self._check_exit_levels():
            return

        buy_sig, sell_sig, macd0, macd1 = self._signal_state()

        if self.position:
            if bool(self.p.trade_on) and self.entry_index > 0:
                current_price = float(self.data.close[0])
                threshold = float(self.p.point) * float(self.p.pips)
                limit_ok = int(self.p.max_count) == -1 or self.entry_index < int(self.p.max_count)
                if self.position.size > 0 and buy_sig and limit_ok and self.last_entry_price is not None:
                    if self.last_entry_price - current_price >= threshold:
                        self._place_add_order('buy', macd0)
                        return
                if self.position.size < 0 and sell_sig and limit_ok and self.last_entry_price is not None:
                    if current_price - self.last_entry_price >= threshold:
                        self._place_add_order('sell', macd0)
                        return
            self._apply_trailing()
            return

        if not bool(self.p.trade_on):
            return

        lot = self._current_lot()
        if buy_sig and not sell_sig:
            self._place_initial_order('buy', lot, macd0)
            return
        if sell_sig and not buy_sig:
            self._place_initial_order('sell', lot, macd0)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        meta = self.order_meta.pop(order.ref, {})

        if order.status == order.Completed:
            if meta.get('role') == 'entry':
                side = meta.get('side')
                if side == 'buy':
                    self.buy_count += 1
                elif side == 'sell':
                    self.sell_count += 1

                self.entry_index = int(meta.get('index', 1))
                self.last_entry_price = float(order.executed.price)
                if meta.get('kind') == 'initial':
                    self.start_lot = abs(float(order.executed.size))
                point = float(meta.get('point', self.p.point))
                stop_loss = int(meta.get('stop_loss', 0))
                take_profit = int(meta.get('take_profit', 0))

                if side == 'buy':
                    self.current_exit_stop = float(order.executed.price) - point * stop_loss if stop_loss > 0 else None
                    if meta.get('kind') == 'add' and take_profit > 0:
                        self.current_exit_take = float(self.position.price) + point * take_profit
                    else:
                        self.current_exit_take = float(order.executed.price) + point * take_profit if take_profit > 0 else None
                else:
                    self.current_exit_stop = float(order.executed.price) + point * stop_loss if stop_loss > 0 else None
                    if meta.get('kind') == 'add' and take_profit > 0:
                        self.current_exit_take = float(self.position.price) - point * take_profit
                    else:
                        self.current_exit_take = float(order.executed.price) - point * take_profit if take_profit > 0 else None
            self.order = None
            return

        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            self.order = None

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
        self.current_exit_stop = None
        self.current_exit_take = None
        self.entry_index = 0
        self.start_lot = None
        self.last_entry_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
