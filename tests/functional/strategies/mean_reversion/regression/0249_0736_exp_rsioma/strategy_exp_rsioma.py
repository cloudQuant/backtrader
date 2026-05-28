from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


PRICE_MAP = {
    'close': lambda row: row['close'],
    'open': lambda row: row['open'],
    'high': lambda row: row['high'],
    'low': lambda row: row['low'],
    'median': lambda row: (row['high'] + row['low']) / 2.0,
    'typical': lambda row: (row['high'] + row['low'] + row['close']) / 3.0,
    'weighted': lambda row: (row['high'] + row['low'] + 2.0 * row['close']) / 4.0,
    'simple': lambda row: (row['open'] + row['close']) / 2.0,
    'quarter': lambda row: (row['high'] + row['low'] + row['open'] + row['close']) / 4.0,
}


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
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'real_volume', 'openinterest']]
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
        'tick_volume': 'sum',
        'real_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    out['volume'] = out['tick_volume']
    return out


def _sma(values):
    return float(np.mean(values))


def _ema(values):
    period = len(values)
    smooth = 2.0 / (1.0 + period)
    ema = values[0]
    for value in values[1:]:
        ema = value * smooth + ema * (1.0 - smooth)
    return float(ema)


def _smma(values):
    period = len(values)
    smma = values[0]
    for value in values[1:]:
        smma = (smma * (period - 1) + value) / period
    return float(smma)


def _lwma(values):
    weights = np.arange(1, len(values) + 1, dtype=float)
    values = np.asarray(values, dtype=float)
    return float(np.dot(values, weights) / weights.sum())


def smooth(values, period, method='ema'):
    if period <= 1:
        return float(values[-1])
    window = values[-period:]
    method = str(method).lower()
    if method == 'sma':
        return _sma(window)
    if method == 'smma':
        return _smma(window)
    if method == 'lwma':
        return _lwma(window)
    return _ema(window)


def compute_rsioma(frame, rsioma_method='ema', rsioma=14, marsioma_method='ema', marsioma=21, mom_period=1, price_type='close'):
    work = frame.copy()
    price_getter = PRICE_MAP.get(price_type, PRICE_MAP['close'])
    prices = work.apply(price_getter, axis=1).to_numpy(dtype=float)
    x1xma = []
    rels = []
    positives = []
    negatives = []
    rsi_values = []
    trigger_values = []
    prev_positive = 0.0
    prev_negative = 0.0
    for i in range(len(work)):
        price_history = prices[: i + 1]
        xma = smooth(price_history, min(rsioma, len(price_history)), rsioma_method)
        x1xma.append(xma)
        if i < mom_period:
            rel = 0.0
        else:
            rel = x1xma[i] - x1xma[i - mom_period]
        rels.append(rel)
        pos_hist = [max(x, 0.0) for x in rels]
        neg_hist = [-min(x, 0.0) for x in rels]
        sump = rsioma * smooth(pos_hist, min(rsioma, len(pos_hist)), 'sma')
        sumn = rsioma * smooth(neg_hist, min(rsioma, len(neg_hist)), 'sma')
        positive = (prev_positive * (rsioma - 1) + sump) / rsioma
        negative = (prev_negative * (rsioma - 1) + sumn) / rsioma
        prev_positive = positive
        prev_negative = negative
        if negative != 0:
            res = 1.0 + positive / negative
        else:
            res = 2.0
        rsi = 50.0 - 100.0 / res if res != 0 else 0.0
        positives.append(positive)
        negatives.append(negative)
        rsi_values.append(rsi)
        trigger = smooth(rsi_values, min(marsioma, len(rsi_values)), marsioma_method)
        trigger_values.append(trigger)
    work['rsioma'] = rsi_values
    work['trigger'] = trigger_values
    return work.dropna(subset=['rsioma', 'trigger'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class RSIOMAFeed(bt.feeds.PandasData):
    lines = ('rsioma', 'trigger')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('rsioma', 6), ('trigger', 7),
    )


class ExpRSIOMAStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        lots=0.1,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        mode='histdisposition',
        high_level=20.0,
        middle_level=0.0,
        low_level=-20.0,
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

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _set_risk(self, side):
        unit = self._unit()
        price = float(self.base.close[0])
        if side == 'buy':
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits)) if self.p.stop_loss > 0 else None
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits)) if self.p.take_profit > 0 else None

    def _mode_signal(self):
        mode = str(self.p.mode).lower()
        macd0 = float(self.ind.rsioma[-1])
        macd1 = float(self.ind.rsioma[0])
        signal0 = float(self.ind.trigger[-1])
        signal1 = float(self.ind.trigger[0])
        macd2 = float(self.ind.rsioma[-2]) if len(self.ind) > 2 else macd0
        signal2 = float(self.ind.trigger[-2]) if len(self.ind) > 2 else signal0
        buy_open = sell_open = buy_close = sell_close = False
        if mode == 'breakdown':
            if macd1 > float(self.p.high_level):
                if self.p.buy_pos_open and macd0 <= float(self.p.high_level):
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if macd1 < float(self.p.low_level):
                if self.p.sell_pos_open and macd0 >= float(self.p.low_level):
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        elif mode == 'histtwist':
            if macd1 > macd2:
                if self.p.buy_pos_open and macd0 <= macd1:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if macd1 < macd2:
                if self.p.sell_pos_open and macd0 >= macd1:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        elif mode == 'signaltwist':
            if signal1 > signal2:
                if self.p.buy_pos_open and signal0 <= signal1:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if signal1 < signal2:
                if self.p.sell_pos_open and signal0 >= signal1:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        else:
            if macd1 > signal1:
                if self.p.buy_pos_open and macd0 <= signal0:
                    buy_open = True
                if self.p.sell_pos_close:
                    sell_close = True
            if macd1 < signal1:
                if self.p.sell_pos_open and macd0 >= signal0:
                    sell_open = True
                if self.p.buy_pos_close:
                    buy_close = True
        return buy_open, sell_open, buy_close, sell_close

    def _manage_position(self, buy_close, sell_close):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if buy_close and self.p.buy_pos_close:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if sell_close and self.p.sell_pos_close:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.ind) < 3:
            return
        if self.order is not None:
            return
        signal_dt = bt.num2date(self.ind.datetime[0])
        buy_open, sell_open, buy_close, sell_close = self._mode_signal()
        if self.position:
            self._manage_position(buy_close, sell_close)
            return
        if self.last_signal_dt == signal_dt:
            return
        if buy_open:
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lots)
            self.last_signal_dt = signal_dt
            return
        if sell_open:
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lots)
            self.last_signal_dt = signal_dt

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
        else:
            self.loss_count += 1
