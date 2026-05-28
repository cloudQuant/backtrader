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


class GoStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        maximum_risk=0.05,
        shift=1,
        ma_period=174,
        ma_shift=0,
        ma_method='ema',
        vol_volume='tick',
        open_level=0.0,
        close_level_dif=0.0,
        point=0.01,
    )

    def __init__(self):
        ma_cls = self._ma_class(self.p.ma_method)
        self.ma_high = ma_cls(self.data.high, period=self.p.ma_period)
        self.ma_low = ma_cls(self.data.low, period=self.p.ma_period)
        self.ma_close = ma_cls(self.data.close, period=self.p.ma_period)
        self.ma_open = ma_cls(self.data.open, period=self.p.ma_period)
        self.vol_line = self.data.volume if str(self.p.vol_volume).lower() == 'tick' else self.data.openinterest

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

        self.addminperiod(self.p.ma_period + int(self.p.shift) + 3)

    def _ma_class(self, method):
        name = str(method).lower()
        mapping = {
            'sma': bt.indicators.SimpleMovingAverage,
            'ema': bt.indicators.ExponentialMovingAverage,
            'smma': bt.indicators.SmoothedMovingAverage,
            'lwma': bt.indicators.WeightedMovingAverage,
            'wma': bt.indicators.WeightedMovingAverage,
        }
        return mapping.get(name, bt.indicators.ExponentialMovingAverage)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.maximum_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        return max(round(lot, 2), 0.01)

    def _go_value(self):
        idx = -int(self.p.shift) if int(self.p.shift) > 0 else 0
        ma_idx = idx - int(self.p.ma_shift)
        o = float(self.ma_open[ma_idx])
        h = float(self.ma_high[ma_idx])
        l = float(self.ma_low[ma_idx])
        c = float(self.ma_close[ma_idx])
        v = float(self.vol_line[idx])
        return ((c - o) + (h - o) + (l - o) + (c - l) + (c - h)) * v

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        go = self._go_value()
        open_buy = go > float(self.p.open_level)
        open_sell = go < -float(self.p.open_level)
        close_buy = go < (float(self.p.open_level) - float(self.p.close_level_dif))
        close_sell = go > -(float(self.p.open_level) - float(self.p.close_level_dif))
        if (open_buy and not open_sell and not close_buy) or (open_sell and not open_buy and not close_sell):
            self.signal_count += 1

        if self.position:
            if self.position.size > 0 and close_buy:
                self.log(f'close buy go={go:.5f}')
                self.order = self.close()
                return
            if self.position.size < 0 and close_sell:
                self.log(f'close sell go={go:.5f}')
                self.order = self.close()
                return
            return

        lot = self._current_lot()
        if open_buy and not open_sell and not close_buy:
            self.log(f'buy signal go={go:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy and not close_sell:
            self.log(f'sell signal go={go:.5f} lot={lot:.2f}')
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
