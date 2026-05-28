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
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'openinterest']]
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
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    out['volume'] = out['tick_volume']
    return out


def compute_adx_cloud(frame, period=14):
    high = frame['high']
    low = frame['low']
    close = frame['close']
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / float(period), adjust=False).mean()
    di_plus = 100.0 * plus_dm.ewm(alpha=1.0 / float(period), adjust=False).mean() / atr.replace(0, pd.NA)
    di_minus = 100.0 * minus_dm.ewm(alpha=1.0 / float(period), adjust=False).mean() / atr.replace(0, pd.NA)
    out = frame.copy()
    out['di_plus'] = di_plus
    out['di_minus'] = di_minus
    return out.dropna(subset=['di_plus', 'di_minus'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class AdxCloudFeed(bt.feeds.PandasData):
    lines = ('di_plus', 'di_minus')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('di_plus', 6), ('di_minus', 7),
    )


class ExpFractalAdxCloudStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        signal_bar=1,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
        size=0.1,
        e_period=30,
        normal_speed=30,
        applied_price='PRICE_CLOSE_',
    )

    def __init__(self):
        self.base = self.datas[0]
        self.ind = self.datas[1]
        self.di_plus = self.ind.di_plus
        self.di_minus = self.ind.di_minus

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
            self.stop_price = round(price - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price + float(self.p.take_profit) * unit, int(self.p.price_digits))
        else:
            self.stop_price = round(price + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(price - float(self.p.take_profit) * unit, int(self.p.price_digits))

    def _manage_risk(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if low <= self.stop_price or high >= self.take_profit_price:
                self.order = self.close()
                return True
        else:
            if high >= self.stop_price or low <= self.take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return
        if self._manage_risk():
            return
        idx = max(int(self.p.signal_bar), 1)
        try:
            prev_plus = float(self.di_plus[-idx - 1])
            prev_minus = float(self.di_minus[-idx - 1])
            curr_plus = float(self.di_plus[-idx])
            curr_minus = float(self.di_minus[-idx])
        except (IndexError, TypeError, ValueError):
            return
        signal_dt = bt.num2date(self.ind.datetime[-idx])
        if self.last_signal_dt == signal_dt:
            return
        self.last_signal_dt = signal_dt
        buy_open = sell_open = buy_close = sell_close = False
        if prev_plus > prev_minus:
            if self.p.buy_pos_open and curr_plus <= curr_minus:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if prev_plus < prev_minus:
            if self.p.sell_pos_open and curr_plus >= curr_minus:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        if buy_close and self.position and self.position.size > 0:
            self.order = self.close()
            return
        if sell_close and self.position and self.position.size < 0:
            self.order = self.close()
            return
        if buy_open and (not self.position or self.position.size <= 0):
            if self.position and self.position.size < 0:
                self.order = self.close()
                return
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.size)
            return
        if sell_open and (not self.position or self.position.size >= 0):
            if self.position and self.position.size > 0:
                self.order = self.close()
                return
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.size)

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
