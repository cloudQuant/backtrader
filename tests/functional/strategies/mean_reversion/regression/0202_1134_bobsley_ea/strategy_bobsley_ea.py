from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


class RawCloseCloseStochastic(bt.Indicator):
    lines = ('raw',)
    params = dict(period=5)

    def __init__(self):
        self.addminperiod(int(self.p.period))

    def next(self):
        period = int(self.p.period)
        closes = [float(self.data.close[-i]) for i in range(period)]
        highest = max(closes)
        lowest = min(closes)
        denom = highest - lowest
        if denom == 0:
            self.lines.raw[0] = 0.0
            return
        self.lines.raw[0] = 100.0 * (float(self.data.close[0]) - lowest) / denom

    def once(self, start, end):
        period = int(self.p.period)
        closes = self.data.close.array
        raw = self.lines.raw.array
        for i in range(start, end):
            window_start = max(0, i - period + 1)
            window = closes[window_start:i + 1]
            highest = max(window)
            lowest = min(window)
            denom = highest - lowest
            raw[i] = 0.0 if denom == 0 else 100.0 * (closes[i] - lowest) / denom


class CloseCloseEmaStochastic(bt.Indicator):
    lines = ('percK', 'percD')
    params = dict(period=5, slowing=3, dperiod=3)

    def __init__(self):
        raw = RawCloseCloseStochastic(self.data, period=int(self.p.period))
        self.lines.percK = bt.indicators.ExponentialMovingAverage(raw, period=int(self.p.slowing))
        self.lines.percD = bt.indicators.ExponentialMovingAverage(self.lines.percK, period=int(self.p.dperiod))


class BobsleyEaStrategy(bt.Strategy):
    params = dict(
        take_profit=0.007,
        stop_loss=0.0035,
        ma_period=76,
        stoch_oversold=30,
        stoch_overbought=70,
        lot=5.0,
    )

    def __init__(self):
        self.ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.ma_period)
        self.order = None
        self.stop_price = None
        self.take_price = None
        self._stoch_k = None
        self._stoch_history = []

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False

        self.addminperiod(self.p.ma_period + 5)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _money_m(self):
        cash = float(self.broker.getcash())
        lots = cash / 100000.0 * 50.0
        lots = min(15.0, max(0.1, lots))
        if lots < 1.0:
            return round(lots, 1 if lots >= 0.1 else 2)
        return round(lots, 0)

    def _update_stoch_k(self):
        period = 5
        closes = [float(self.data.close[-i]) for i in range(period)]
        highest = max(closes)
        lowest = min(closes)
        denom = highest - lowest
        raw = 0.0 if denom == 0 else 100.0 * (float(self.data.close[0]) - lowest) / denom
        alpha = 2.0 / (3.0 + 1.0)
        self._stoch_k = raw if self._stoch_k is None else alpha * raw + (1.0 - alpha) * self._stoch_k
        self._stoch_history.append(self._stoch_k)
        if len(self._stoch_history) > 3:
            self._stoch_history.pop(0)
        return self._stoch_k

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
        if self._check_exit_levels():
            return
        if self.position:
            return

        ask = float(self.data.close[0])
        bid = float(self.data.close[0])
        close1 = float(self.data.close[-1])
        ma0 = float(self.ma[0])
        ma1 = float(self.ma[-1])
        ma2 = float(self.ma[-2])
        st0 = self._update_stoch_k()
        st1 = self._stoch_history[-2] if len(self._stoch_history) > 1 else st0
        st2 = self._stoch_history[-3] if len(self._stoch_history) > 2 else st1
        if not all(math.isfinite(value) for value in (ma0, ma1, ma2, st0, st1, st2)):
            return

        buy_condition = (ma0 < ma1 < ma2 and ask > ma0 and st1 > st2 and st0 < float(self.p.stoch_oversold))
        sell_condition = (ma0 > ma1 > ma2 and bid < ma0 and st1 < st2 and st0 > float(self.p.stoch_overbought))
        if not buy_condition and not sell_condition:
            buy_condition = close1 <= ma1 and ask > ma0 and st0 >= 50.0
            sell_condition = close1 >= ma1 and bid < ma0 and st0 <= 50.0
        lot = min(float(self.p.lot), self._money_m())

        if buy_condition and self.broker.getcash() > 5000:
            self.signal_count += 1
            self.stop_price = ask - float(self.p.stop_loss)
            self.take_price = ask + float(self.p.take_profit)
            self.log(f'buy lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return
        if sell_condition and self.broker.getcash() > 5000:
            self.signal_count += 1
            self.stop_price = bid + float(self.p.stop_loss)
            self.take_price = bid - float(self.p.take_profit)
            self.log(f'sell lot={lot:.2f}')
            self.order = self.sell(size=lot)

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
            elif trade.size < 0:
                self.sell_count += 1
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
