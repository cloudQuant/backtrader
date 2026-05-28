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


def smooth_series(series, period=5):
    return series.ewm(span=period, adjust=False).mean()


def compute_weight_oscillator(frame, rsi_weight=1.0, rsi_period=14, mfi_weight=1.0, mfi_period=14, wpr_weight=1.0, wpr_period=14, demarker_weight=1.0, demarker_period=14, b_length=5):
    work = frame.copy()
    close = work['close']
    high = work['high']
    low = work['low']
    volume = work['volume']

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(rsi_period, min_periods=rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period, min_periods=rsi_period).mean()
    rs = gain / loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))

    typical = (high + low + close) / 3.0
    money_flow = typical * volume
    pos_flow = money_flow.where(typical > typical.shift(1), 0.0).rolling(mfi_period, min_periods=mfi_period).sum()
    neg_flow = money_flow.where(typical < typical.shift(1), 0.0).rolling(mfi_period, min_periods=mfi_period).sum()
    mfr = pos_flow / neg_flow.replace(0, pd.NA)
    mfi = 100 - (100 / (1 + mfr))

    highest = high.rolling(wpr_period, min_periods=wpr_period).max()
    lowest = low.rolling(wpr_period, min_periods=wpr_period).min()
    wpr = -100 * (highest - close) / (highest - lowest).replace(0, pd.NA)
    wpr_adj = wpr + 100.0

    demax = (high - high.shift(1)).clip(lower=0)
    demin = (low.shift(1) - low).clip(lower=0)
    demarker = demax.rolling(demarker_period, min_periods=demarker_period).mean() / (
        demax.rolling(demarker_period, min_periods=demarker_period).mean() + demin.rolling(demarker_period, min_periods=demarker_period).mean()
    ).replace(0, pd.NA)
    demarker_adj = demarker * 100.0

    sum_weight = rsi_weight + mfi_weight + wpr_weight + demarker_weight
    weight_osc = (rsi_weight * rsi + mfi_weight * mfi + wpr_weight * wpr_adj + demarker_weight * demarker_adj) / sum_weight
    work['weight_osc'] = smooth_series(weight_osc, b_length)
    return work.dropna(subset=['weight_osc'])


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class WeightOscillatorFeed(bt.feeds.PandasData):
    lines = ('weight_osc',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5), ('weight_osc', 6),
    )


class ExpWeightOscillatorStrategy(bt.Strategy):
    params = dict(
        stop_loss=1000,
        take_profit=2000,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        trend='direct',
        high_level=70.0,
        low_level=30.0,
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

    def _signal(self):
        prev_val = float(self.ind.weight_osc[-1])
        curr_val = float(self.ind.weight_osc[0])
        buy_open = sell_open = buy_close = sell_close = False
        if str(self.p.trend).lower() == 'direct':
            if curr_val > float(self.p.low_level) and prev_val <= float(self.p.low_level):
                buy_open = bool(self.p.buy_pos_open)
                sell_close = bool(self.p.sell_pos_close)
            if curr_val < float(self.p.high_level) and prev_val >= float(self.p.high_level):
                sell_open = bool(self.p.sell_pos_open)
                buy_close = bool(self.p.buy_pos_close)
        else:
            if curr_val > float(self.p.low_level) and prev_val <= float(self.p.low_level):
                sell_open = bool(self.p.sell_pos_open)
                buy_close = bool(self.p.buy_pos_close)
            if curr_val < float(self.p.high_level) and prev_val >= float(self.p.high_level):
                buy_open = bool(self.p.buy_pos_open)
                sell_close = bool(self.p.sell_pos_close)
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

    def next(self):
        self.bar_num += 1
        if len(self.ind) < 2:
            return
        if self.order is not None:
            return
        signal_dt = bt.num2date(self.ind.datetime[0])
        buy_open, sell_open, buy_close, sell_close = self._signal()
        if self.position:
            self._manage_position(buy_close, sell_close)
            return
        if self.last_signal_dt == signal_dt:
            return
        if buy_open:
            self.signal_count += 1
            self._set_risk('buy')
            self.order = self.buy(size=self.p.lot)
            self.last_signal_dt = signal_dt
            return
        if sell_open:
            self.signal_count += 1
            self._set_risk('sell')
            self.order = self.sell(size=self.p.lot)
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
