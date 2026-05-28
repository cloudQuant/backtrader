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


class Ccit3SignalFeed(btfeeds.PandasData):
    lines = ('ccit3',)
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
        ('ccit3', 6),
    )


def applied_price(df, price_type):
    if isinstance(price_type, (int, float)):
        price_code = int(price_type)
    else:
        mapping = {
            'close': 0,
            'open': 1,
            'high': 2,
            'low': 3,
            'median': 4,
            'typical': 5,
            'weighted': 6,
        }
        price_code = mapping.get(str(price_type).lower(), 5)
    open_ = df['open'].astype(float)
    high = df['high'].astype(float)
    low = df['low'].astype(float)
    close = df['close'].astype(float)
    if price_code == 0:
        return close
    if price_code == 1:
        return open_
    if price_code == 2:
        return high
    if price_code == 3:
        return low
    if price_code == 4:
        return (high + low) / 2.0
    if price_code == 6:
        return (high + low + 2.0 * close) / 4.0
    return (high + low + close) / 3.0


def cci_series(df, period, price_type):
    period = int(period)
    price = applied_price(df, price_type)
    sma = price.rolling(period).mean()
    mean_dev = price.rolling(period).apply(lambda values: (abs(values - values.mean())).mean(), raw=False)
    cci = (price - sma) / (0.015 * mean_dev)
    return cci.replace([math.inf, -math.inf], 0.0).fillna(0.0)


def ccit3_series(cci, t3_period, coeff_b, mode):
    b = float(coeff_b)
    b2 = b * b
    b3 = b2 * b
    c1 = -b3
    c2 = 3.0 * (b2 + b3)
    c3 = -3.0 * (2.0 * b2 + b + b3)
    c4 = 1.0 + 3.0 * b + b3 + 3.0 * b2
    n = int(t3_period)
    if n < 1:
        n = 1
    else:
        n = (n + 1) // 2
    w1 = 2.0 / (n + 1.0)
    w2 = 1.0 - w1
    values = []
    e1 = e2 = e3 = e4 = e5 = e6 = 0.0
    use_norecalc = str(mode).lower() == 'norecalc'
    for raw_value in cci.astype(float).tolist():
        if not math.isfinite(raw_value) or abs(raw_value) >= 1000:
            values.append(0.0)
            continue
        if use_norecalc:
            e1 = e2 = e3 = e4 = e5 = e6 = 0.0
        e1 = w1 * raw_value + w2 * e1
        e2 = w1 * e1 + w2 * e2
        e3 = w1 * e2 + w2 * e3
        e4 = w1 * e3 + w2 * e4
        e5 = w1 * e4 + w2 * e5
        e6 = w1 * e5 + w2 * e6
        values.append(c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3)
    return pd.Series(values, index=cci.index)


def build_signal_frame(
    df,
    use_simple_ccit3,
    use_norecalc_ccit3,
    cci_period_smpl,
    cci_price_type_smpl,
    t3_period_smpl,
    coeff_b_smpl,
    cci_period_otrng,
    cci_price_type_otrng,
    t3_period_otrng,
    coeff_b_otrng,
):
    if bool(use_simple_ccit3) == bool(use_norecalc_ccit3):
        raise ValueError('Choose exactly one of use_simple_ccit3/use_norecalc_ccit3')
    signal_df = df.copy()
    if use_simple_ccit3:
        cci = cci_series(signal_df, cci_period_smpl, cci_price_type_smpl)
        signal_df['ccit3'] = ccit3_series(cci, t3_period_smpl, coeff_b_smpl, mode='simple')
    else:
        cci = cci_series(signal_df, cci_period_otrng, cci_price_type_otrng)
        signal_df['ccit3'] = ccit3_series(cci, t3_period_otrng, coeff_b_otrng, mode='norecalc')
    return signal_df


class EaCcit3Strategy(bt.Strategy):
    params = dict(
        lots=1.0,
        tp=0.0,
        sl=0.0,
        trail=0.0,
        max_drawdown=0.0,
        trade_overturn=False,
        max_lot=None,
        point=0.01,
        use_simple_ccit3=True,
        use_norecalc_ccit3=False,
        cci_period_smpl=285,
        cci_price_type_smpl='typical',
        t3_period_smpl=60,
        coeff_b_smpl=0.618,
        cci_period_otrng=250,
        cci_price_type_otrng='typical',
        t3_period_otrng=170,
        coeff_b_otrng=0.618,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.ccit3 = self.signal.ccit3
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.order = None
        self.pending_entry_side = None
        self.stop_price = None
        self.take_price = None
        self.trail_stop = 0.0
        self._position_was_open = False

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _current_lot(self):
        lot = float(self.p.lots)
        if float(self.p.max_drawdown) > 0:
            lot = round(lot * float(self.broker.getcash()) / float(self.p.max_drawdown), 2)
        if self.p.max_lot is not None:
            lot = min(lot, float(self.p.max_lot))
        return max(round(lot, 2), 0.0)

    def _set_exit_levels(self, is_long, entry_price):
        point = float(self.p.point)
        self.trail_stop = 0.0
        self.stop_price = None
        self.take_price = None
        if float(self.p.sl) > 0:
            self.stop_price = entry_price - float(self.p.sl) * point if is_long else entry_price + float(self.p.sl) * point
        if float(self.p.tp) > 0:
            self.take_price = entry_price + float(self.p.tp) * point if is_long else entry_price - float(self.p.tp) * point

    def _clear_exit_levels(self):
        self.stop_price = None
        self.take_price = None
        self.trail_stop = 0.0

    def _update_trailing(self):
        if not self.position or float(self.p.trail) <= 0:
            return
        if self.position.size > 0 and float(self.base.close[0]) > float(self.position.price):
            candidate = float(self.base.close[0]) - float(self.p.trail) * float(self.p.point)
            if (self.trail_stop < candidate and self.trail_stop > 0) or self.trail_stop == 0:
                self.trail_stop = candidate
                if self.stop_price is None or candidate > self.stop_price:
                    self.stop_price = candidate
        elif self.position.size < 0 and float(self.base.close[0]) < float(self.position.price):
            candidate = float(self.base.close[0]) + float(self.p.trail) * float(self.p.point)
            if (self.trail_stop > candidate and self.trail_stop > 0) or self.trail_stop == 0:
                self.trail_stop = candidate
                if self.stop_price is None or candidate < self.stop_price:
                    self.stop_price = candidate

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.2f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.base) < 5 or len(self.signal) < 5:
            return
        if self.order is not None:
            return
        if not self.position and self.pending_entry_side is not None:
            lot = self._current_lot()
            if lot > 0:
                if self.pending_entry_side == 'long':
                    self.log(f'pending buy lot={lot:.2f}')
                    self.order = self.buy(size=lot)
                else:
                    self.log(f'pending sell lot={lot:.2f}')
                    self.order = self.sell(size=lot)
            self.pending_entry_side = None
            return
        self._update_trailing()
        if self._check_exit_levels():
            return
        ccit3_now = float(self.ccit3[-1])
        ccit3_prev = float(self.ccit3[-2])
        buy_signal = ccit3_now <= 0 and ccit3_prev > 0
        sell_signal = ccit3_now >= 0 and ccit3_prev < 0
        if buy_signal or sell_signal:
            self.signal_count += 1
        lot = self._current_lot()
        if not self.position:
            if buy_signal and lot > 0:
                self.log(f'buy signal ccit3_now={ccit3_now:.5f} ccit3_prev={ccit3_prev:.5f} lot={lot:.2f}')
                self.order = self.buy(size=lot)
                return
            if sell_signal and lot > 0:
                self.log(f'sell signal ccit3_now={ccit3_now:.5f} ccit3_prev={ccit3_prev:.5f} lot={lot:.2f}')
                self.order = self.sell(size=lot)
                return
            return
        if not bool(self.p.trade_overturn):
            return
        if self.position.size > 0 and sell_signal:
            self.log(f'reverse long->short ccit3_now={ccit3_now:.5f} ccit3_prev={ccit3_prev:.5f}')
            self.pending_entry_side = 'short'
            self.order = self.close()
            return
        if self.position.size < 0 and buy_signal:
            self.log(f'reverse short->long ccit3_now={ccit3_now:.5f} ccit3_prev={ccit3_prev:.5f}')
            self.pending_entry_side = 'long'
            self.order = self.close()

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position:
                self._set_exit_levels(self.position.size > 0, float(order.executed.price))
            else:
                self._clear_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.pending_entry_side = None
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
        self._clear_exit_levels()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
