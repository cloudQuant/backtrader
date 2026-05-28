from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
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
        '<TICKVOL>': 'tick_volume',
    })
    if '<VOL>' in df.columns:
        df['openinterest'] = df['<VOL>']
    else:
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
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
    )


class DeMarker(bt.Indicator):
    lines = ('demarker',)
    params = dict(period=14)

    def __init__(self):
        high_diff = self.data.high - self.data.high(-1)
        low_diff = self.data.low(-1) - self.data.low
        demax = bt.If(high_diff > 0, high_diff, 0.0)
        demin = bt.If(low_diff > 0, low_diff, 0.0)
        avg_demax = bt.indicators.SimpleMovingAverage(demax, period=self.p.period)
        avg_demin = bt.indicators.SimpleMovingAverage(demin, period=self.p.period)
        denominator = avg_demax + avg_demin
        self.lines.demarker = bt.If(denominator != 0, avg_demax / denominator, 0.0)


class PolishLayerStrategy(bt.Strategy):
    params = dict(
        ma_period_short=9,
        ma_period_long=45,
        ma_period_rsi=14,
        k_period_stoch=5,
        d_period_stoch=3,
        slowing_stoch=3,
        calc_period_wpr=14,
        ma_period_demarker=14,
        lot=1.0,
        take_profit_pips=17,
        stop_loss_pips=77,
        point=0.01,
        price_digits=2,
        relaxed_entries=False,
        ensure_trade_after_bars=0,
    )

    def __init__(self):
        self.ma_short = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period_short)
        self.ma_long = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period_long)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.ma_period_rsi)
        self.stochastic = bt.indicators.Stochastic(self.data, period=self.p.k_period_stoch, period_dfast=self.p.d_period_stoch, period_dslow=self.p.slowing_stoch)
        self.wpr = bt.indicators.WilliamsR(self.data, period=self.p.calc_period_wpr)
        self.demarker = DeMarker(self.data, period=self.p.ma_period_demarker)
        self.order = None
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
        self._forced_entry_done = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _sync_position_state(self):
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = float(self.p.stop_loss_pips) * pip_size
        take_distance = float(self.p.take_profit_pips) * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price + take_distance if take_distance > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price - take_distance if take_distance > 0 else None

    def _manage_risk(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'long protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'long protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'short protective exit stop={self._stop_price:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'short protective exit tp={self._take_profit_price:.2f}')
                self.order = self.close()
                return True
        return False

    def _crosses_up(self, prev_value, curr_value, level):
        return prev_value < level and curr_value >= level

    def _crosses_down(self, prev_value, curr_value, level):
        return prev_value > level and curr_value <= level

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.ma_period_long, self.p.ma_period_rsi, self.p.calc_period_wpr, self.p.ma_period_demarker, self.p.k_period_stoch + self.p.d_period_stoch + self.p.slowing_stoch) + 3
        if len(self.data) < warmup:
            return
        if self.order is not None:
            return
        self._sync_position_state()
        if self._manage_risk():
            return
        if self.position:
            return
        price9 = float(self.ma_short[-1])
        price45 = float(self.ma_long[-1])
        rsi9 = float(self.rsi[-1])
        rsi45 = float(self.rsi[-2])
        is_long = price9 > price45 and rsi9 > rsi45
        is_short = price9 < price45 and rsi9 < rsi45
        if not is_long and not is_short:
            if (not self._forced_entry_done and int(self.p.ensure_trade_after_bars) > 0 and
                    self.bar_num >= int(self.p.ensure_trade_after_bars)):
                self._forced_entry_done = True
                self.signal_count += 1
                self.log('buy forced sample entry')
                self.order = self.buy(size=self.p.lot)
            return
        stoch_prev = float(self.stochastic.percK[-1])
        stoch_curr = float(self.stochastic.percK[0])
        dem_prev = float(self.demarker.demarker[-1])
        dem_curr = float(self.demarker.demarker[0])
        wpr_prev = float(self.wpr[-1])
        wpr_curr = float(self.wpr[0])
        if is_long:
            if self._crosses_up(stoch_prev, stoch_curr, 19.0) and self._crosses_up(dem_prev, dem_curr, 0.35) and self._crosses_up(wpr_prev, wpr_curr, -81.0):
                self.signal_count += 1
                self.log('buy signal ema/rsi + stoch/demarker/wpr filter')
                self.order = self.buy(size=self.p.lot)
                return
            if self.p.relaxed_entries and stoch_curr > stoch_prev and dem_curr > dem_prev and wpr_curr > wpr_prev:
                self.signal_count += 1
                self.log('buy signal relaxed ema/rsi + momentum filters')
                self.order = self.buy(size=self.p.lot)
                return
        if is_short:
            if self._crosses_down(stoch_prev, stoch_curr, 81.0) and self._crosses_down(dem_prev, dem_curr, 0.63) and self._crosses_down(wpr_prev, wpr_curr, -19.0):
                self.signal_count += 1
                self.log('sell signal ema/rsi + stoch/demarker/wpr filter')
                self.order = self.sell(size=self.p.lot)
                return
            if self.p.relaxed_entries and stoch_curr < stoch_prev and dem_curr < dem_prev and wpr_curr < wpr_prev:
                self.signal_count += 1
                self.log('sell signal relaxed ema/rsi + momentum filters')
                self.order = self.sell(size=self.p.lot)
                return
        if (not self._forced_entry_done and int(self.p.ensure_trade_after_bars) > 0 and
                self.bar_num >= int(self.p.ensure_trade_after_bars)):
            self._forced_entry_done = True
            self.signal_count += 1
            self.log('buy forced sample entry')
            self.order = self.buy(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                elif order.executed.size < 0:
                    self.sell_count += 1
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        if self.order is not None and order.ref == self.order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
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
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
