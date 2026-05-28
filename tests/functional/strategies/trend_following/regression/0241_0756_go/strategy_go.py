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


class GOIndicator(bt.Indicator):
    lines = ('go',)
    params = dict(period=174, ma_method='SMA')

    def __init__(self):
        ma_cls = {
            'SMA': bt.indicators.SimpleMovingAverage,
            'EMA': bt.indicators.ExponentialMovingAverage,
            'SMMA': bt.indicators.SmoothedMovingAverage,
            'WMA': bt.indicators.WeightedMovingAverage,
        }.get(str(self.p.ma_method).upper(), bt.indicators.SimpleMovingAverage)
        self.ma_open = ma_cls(self.data.open, period=self.p.period)
        self.ma_high = ma_cls(self.data.high, period=self.p.period)
        self.ma_low = ma_cls(self.data.low, period=self.p.period)
        self.ma_close = ma_cls(self.data.close, period=self.p.period)
        self.addminperiod(int(self.p.period) + 1)

    def _calc_go(self, ma_open, ma_high, ma_low, ma_close, volume):
        values = (ma_open, ma_high, ma_low, ma_close, volume)
        if not all(math.isfinite(float(v)) for v in values):
            return 0.0
        return (
            (ma_close - ma_open)
            + (ma_high - ma_open)
            + (ma_low - ma_open)
            + (ma_close - ma_low)
            + (ma_close - ma_high)
        ) * volume

    def next(self):
        self.lines.go[0] = self._calc_go(
            float(self.ma_open[0]),
            float(self.ma_high[0]),
            float(self.ma_low[0]),
            float(self.ma_close[0]),
            float(self.data.volume[0]),
        )

    def once(self, start, end):
        ma_open = self.ma_open.array
        ma_high = self.ma_high.array
        ma_low = self.ma_low.array
        ma_close = self.ma_close.array
        volume = self.data.volume.array
        go = self.lines.go.array
        for i in range(start, end):
            go[i] = self._calc_go(
                float(ma_open[i]),
                float(ma_high[i]),
                float(ma_low[i]),
                float(ma_close[i]),
                float(volume[i]),
            )


class GOStrategy(bt.Strategy):
    params = dict(
        risk=30.0,
        max_positions=5,
        ma_method='SMA',
        ma_period=174,
        min_lot=0.01,
        volume_step=0.01,
    )

    def __init__(self):
        ma_cls = {
            'SMA': bt.indicators.SimpleMovingAverage,
            'EMA': bt.indicators.ExponentialMovingAverage,
            'SMMA': bt.indicators.SmoothedMovingAverage,
            'WMA': bt.indicators.WeightedMovingAverage,
        }.get(str(self.p.ma_method).upper(), bt.indicators.SimpleMovingAverage)
        period = max(1, int(self.p.ma_period))
        self.ma_open = ma_cls(self.data.open, period=period)
        self.ma_high = ma_cls(self.data.high, period=period)
        self.ma_low = ma_cls(self.data.low, period=period)
        self.ma_close = ma_cls(self.data.close, period=period)
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
        self.last_entry_dt = None
        self.layer_count = 0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _lot_check(self, lots):
        volume = round(float(lots), 2)
        step = float(self.p.volume_step)
        if step > 0.0:
            volume = step * int(volume / step)
        return max(volume, float(self.p.min_lot))

    def _lots_optimized(self):
        cash = float(self.broker.getcash())
        value = float(self.broker.getvalue())
        lots = round(value * float(self.p.risk) / 100000.0, 1)
        if cash < (1000.0 * lots):
            lots = round(cash * float(self.p.risk) / 100000.0, 1)
        return self._lot_check(lots)

    def _go_value(self):
        ma_open = float(self.ma_open[0])
        ma_high = float(self.ma_high[0])
        ma_low = float(self.ma_low[0])
        ma_close = float(self.ma_close[0])
        volume = float(self.data.volume[0])
        if not all(math.isfinite(v) for v in (ma_open, ma_high, ma_low, ma_close, volume)):
            return 0.0
        return (
            (ma_close - ma_open)
            + (ma_high - ma_open)
            + (ma_low - ma_open)
            + (ma_close - ma_low)
            + (ma_close - ma_high)
        ) * volume

    def _close_opposite_if_needed(self, go_value):
        if not self.position:
            return False
        if go_value < 0 and self.position.size > 0:
            self.signal_count += 1
            self.order = self.close()
            return True
        if go_value > 0 and self.position.size < 0:
            self.signal_count += 1
            self.order = self.close()
            return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        go_value = self._go_value()
        if self._close_opposite_if_needed(go_value):
            return
        if go_value == 0:
            return
        current_dt = bt.num2date(self.data.datetime[0])
        if self.last_entry_dt == current_dt:
            return
        if self.layer_count >= int(self.p.max_positions):
            return
        vol = self._lots_optimized()
        if vol <= 0:
            return
        if go_value > 0:
            self.signal_count += 1
            self.order = self.buy(size=vol)
            self.last_entry_dt = current_dt
            self.log(f'buy go={go_value:.4f} size={vol:.2f}')
            return
        if go_value < 0:
            self.signal_count += 1
            self.order = self.sell(size=vol)
            self.last_entry_dt = current_dt
            self.log(f'sell go={go_value:.4f} size={vol:.2f}')

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
                self.layer_count = max(1, self.layer_count + 1) if self.layer_count else 1
            else:
                self.layer_count = 0
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
