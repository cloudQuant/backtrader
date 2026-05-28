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


def compute_silvertrend_signal(frame, ssp=9, risk=3):
    work = frame.copy()
    k = int(risk)
    start_bars = ssp + 1
    old = False
    uptrend = False
    buy_arrow = []
    sell_arrow = []
    for idx in range(len(work)):
        if idx < start_bars:
            buy_arrow.append(0.0)
            sell_arrow.append(0.0)
            continue
        window = work.iloc[max(0, idx - ssp + 1): idx + 1]
        high_max = window['high'].max()
        low_min = window['low'].min()
        avg_range = (window['high'] - window['low']).mean()
        rng = avg_range
        smin = low_min + (high_max - low_min) * k / 100.0
        smax = high_max - (high_max - low_min) * k / 100.0
        close = float(work['close'].iloc[idx])
        if close < smin:
            uptrend = False
        if close > smax:
            uptrend = True
        buy_val = 0.0
        sell_val = 0.0
        low = float(work['low'].iloc[idx])
        high = float(work['high'].iloc[idx])
        if uptrend != old and uptrend:
            buy_val = low - rng * 0.5
        if uptrend != old and not uptrend:
            sell_val = high + rng * 0.5
        buy_arrow.append(buy_val)
        sell_arrow.append(sell_val)
        old = uptrend
    work['buy_arrow'] = buy_arrow
    work['sell_arrow'] = sell_arrow
    return work


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class SilverTrendFeed(bt.feeds.PandasData):
    lines = ('buy_arrow', 'sell_arrow')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('buy_arrow', 6), ('sell_arrow', 7),
    )


class ExpSilverTrendSignalReOpenStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        price_step=300,
        pos_total=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        lot=0.1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.ind = self.datas[1]

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
        self.last_signal_dt = None
        self.add_count = 0
        self.last_add_price = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side, price=None):
        unit = self._unit()
        if price is None:
            price = float(self.base.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _indicator_signal(self):
        buy_open = bool(float(self.ind.buy_arrow[0]))
        sell_open = bool(float(self.ind.sell_arrow[0]))
        buy_close = sell_open and self.p.buy_pos_close
        sell_close = buy_open and self.p.sell_pos_close
        return buy_open, sell_open, buy_close, sell_close

    def _manage_position(self, buy_close, sell_close):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if buy_close:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
        else:
            if sell_close:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
        return False

    def _reopen_condition(self):
        if not self.position or self.order is not None:
            return None
        if self.add_count >= int(self.p.pos_total):
            return None
        base_price = self.last_add_price if self.last_add_price is not None else self.position.price
        unit = self._unit()
        if self.position.size > 0:
            distance = float(self.base.close[0]) - float(base_price)
            if distance > float(self.p.price_step) * unit:
                return 'buy'
        if self.position.size < 0:
            distance = float(base_price) - float(self.base.close[0])
            if distance > float(self.p.price_step) * unit:
                return 'sell'
        return None

    def next(self):
        self.bar_num += 1
        if len(self.ind) < 1:
            return
        if self.order is not None:
            return
        signal_dt = bt.num2date(self.ind.datetime[0])
        buy_open, sell_open, buy_close, sell_close = self._indicator_signal()
        if self.position:
            if self._manage_position(buy_close, sell_close):
                return
            reopen_side = self._reopen_condition()
            if reopen_side == 'buy':
                self.signal_count += 1
                self._set_risk('buy')
                self.order = self.buy(size=self.p.lot)
                self.last_add_price = float(self.base.close[0])
                self.add_count += 1
                return
            if reopen_side == 'sell':
                self.signal_count += 1
                self._set_risk('sell')
                self.order = self.sell(size=self.p.lot)
                self.last_add_price = float(self.base.close[0])
                self.add_count += 1
                return
            return
        if self.last_signal_dt == signal_dt:
            return
        if buy_open and self.p.buy_pos_open:
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lot)
            self.last_signal_dt = signal_dt
            self.add_count = 0
            self.last_add_price = float(self.base.close[0])
            return
        if sell_open and self.p.sell_pos_open:
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lot)
            self.last_signal_dt = signal_dt
            self.add_count = 0
            self.last_add_price = float(self.base.close[0])

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
                self.last_add_price = float(order.executed.price)
            else:
                self.stop_price = None
                self.take_profit_price = None
                self.last_add_price = None
                self.add_count = 0
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
