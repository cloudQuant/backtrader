from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

import backtrader as bt
import pandas as pd


UP = 1
DOWN = -1
NEUTRAL = 0


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
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'openinterest']]
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


class KijunSenRobotStrategy(bt.Strategy):
    params = dict(
        symbol_hint='XAUUSD',
        tenkan=6,
        kijun=12,
        senkou=24,
        ma_period=20,
        sar_step=0.02,
        sar_maximum=0.2,
        lot=1.0,
        point=0.01,
        price_digits=2,
        take_profit_pips=120,
        stop_loss_pips=50,
        break_even_pips=9,
        trailing_stop_pips=10,
        ma_filter_pips=6,
        use_optimized_values=False,
        day_start_hour=7,
        day_end_hour=19,
    )

    def __init__(self):
        self.ichimoku = bt.indicators.Ichimoku(
            self.data,
            tenkan=self.p.tenkan,
            kijun=self.p.kijun,
            senkou=self.p.senkou,
            senkou_lead=self.p.kijun,
            chikou=self.p.kijun,
        )
        self.ema = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.ma_period)
        self.sar = bt.indicators.ParabolicSAR(self.data, af=self.p.sar_step, afmax=self.p.sar_maximum)
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
        self._last_bid = None
        self._last_ask = None
        self.long_cross = 0.0
        self.short_cross = 0.0
        self.long_entry = 0.0
        self.short_entry = 0.0
        self.ma_dir = NEUTRAL
        self._pending_signal = 0
        self._effective = self._resolve_effective_params()

    def _resolve_effective_params(self):
        params = {
            'take_profit_pips': float(self.p.take_profit_pips),
            'stop_loss_pips': float(self.p.stop_loss_pips),
            'break_even_pips': float(self.p.break_even_pips),
            'trailing_stop_pips': float(self.p.trailing_stop_pips),
            'ma_filter_pips': float(self.p.ma_filter_pips),
        }
        if self.p.use_optimized_values:
            optimized = {
                'GBPUSD': dict(stop_loss_pips=50.0, break_even_pips=9.0, trailing_stop_pips=10.0, ma_filter_pips=6.0),
                'EURUSD': dict(stop_loss_pips=60.0, break_even_pips=9.0, trailing_stop_pips=6.0, ma_filter_pips=6.0),
            }
            params.update(optimized.get(str(self.p.symbol_hint).upper(), {}))
        return params

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if int(self.p.price_digits) in (3, 5) else 1
        return float(self.p.point) * digits_adjust

    def _round_price(self, value):
        return round(float(value), int(self.p.price_digits))

    def _within_entry_hours(self):
        dt = bt.num2date(self.data.datetime[0])
        return self.p.day_start_hour <= dt.hour <= self.p.day_end_hour - 1

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _sync_position_state(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == float(self.position.size):
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self._effective['stop_loss_pips'] * pip_size
        take_distance = self._effective['take_profit_pips'] * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price + take_distance if take_distance > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if stop_distance > 0 else None
            self._take_profit_price = self._entry_price - take_distance if take_distance > 0 else None

    def _close_on_protection(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.log(f'long protective exit stop={self._stop_price:.2f} low={low:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.log(f'long protective exit tp={self._take_profit_price:.2f} high={high:.2f}')
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.log(f'short protective exit stop={self._stop_price:.2f} high={high:.2f}')
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.log(f'short protective exit tp={self._take_profit_price:.2f} low={low:.2f}')
                self.order = self.close()
                return True
        return False

    def _close_on_ema_reversal(self):
        if not self.position or len(self.data) < 3:
            return False
        ema_prev = float(self.ema[-1])
        ema_prev2 = float(self.ema[-2])
        if any(math.isnan(v) for v in (ema_prev, ema_prev2)):
            return False
        if self.position.size > 0 and ema_prev < ema_prev2 and (self._stop_price is None or self._stop_price < self._entry_price):
            self.log('close long on EMA reversal before break-even')
            self.order = self.close()
            return True
        if self.position.size < 0 and ema_prev > ema_prev2 and (self._stop_price is None or self._stop_price > self._entry_price):
            self.log('close short on EMA reversal before break-even')
            self.order = self.close()
            return True
        return False

    def _update_break_even(self):
        if not self.position or self._entry_price is None:
            return
        pip_size = self._pip_size()
        threshold = self._effective['break_even_pips'] * pip_size
        if threshold <= 0:
            return
        price = float(self.data.close[0])
        be_offset = pip_size
        if self.position.size > 0:
            if price - self._entry_price > threshold:
                candidate = self._entry_price + be_offset
                if self._stop_price is None or self._stop_price < candidate:
                    self._stop_price = self._round_price(candidate)
        else:
            if self._entry_price - price > threshold:
                candidate = self._entry_price - be_offset
                if self._stop_price is None or self._stop_price > candidate:
                    self._stop_price = self._round_price(candidate)

    def _update_trailing_stop(self):
        if not self.position or self._entry_price is None:
            return
        pip_size = self._pip_size()
        threshold = self._effective['trailing_stop_pips'] * pip_size
        if threshold <= 0:
            return
        price = float(self.data.close[0])
        if self.position.size > 0:
            if price - self._entry_price > threshold:
                candidate = self._round_price(price - threshold)
                if self._stop_price is None or self._stop_price < candidate:
                    self._stop_price = candidate
        else:
            if self._entry_price - price > threshold:
                candidate = self._round_price(price + threshold)
                if self._stop_price is None or self._stop_price > candidate:
                    self._stop_price = candidate

    def _compute_entry_signal(self):
        if not self._within_entry_hours() or len(self.data) < 3:
            return 0
        ks = float(self.ichimoku.kijun_sen[0])
        ks2 = float(self.ichimoku.kijun_sen[-2])
        ema_curr = float(self.ema[0])
        ema_prev = float(self.ema[-1])
        current_open = float(self.data.open[0])
        current_close = float(self.data.close[0])
        prev_close = float(self.data.close[-1])
        if any(math.isnan(v) for v in (ks, ks2, ema_curr, ema_prev, current_open, current_close, prev_close)):
            return 0
        pip_size = self._pip_size()
        ma_filter_distance = self._effective['ma_filter_pips'] * pip_size
        last_bid = prev_close if self._last_bid is None else self._last_bid
        last_ask = prev_close if self._last_ask is None else self._last_ask
        if current_open < ks and last_bid < ks and current_close > ks and self.long_cross == 0 and ks >= ks2:
            if ema_curr < ks - ma_filter_distance:
                self.long_cross = ks
                self.short_cross = 0.0
        if current_open > ks and last_ask > ks and current_close < ks and self.short_cross == 0 and ks <= ks2:
            if ema_curr > ks + ma_filter_distance:
                self.short_cross = ks
                self.long_cross = 0.0
        if ema_prev < ema_curr:
            self.ma_dir = UP
        elif ema_prev > ema_curr:
            self.ma_dir = DOWN
        if self.ma_dir == UP and self.long_cross != 0:
            self.long_entry = self._round_price(ks)
            return 1
        if self.ma_dir == DOWN and self.short_cross != 0:
            self.short_entry = self._round_price(ks)
            return -1
        self._last_bid = current_close
        self._last_ask = current_close
        return 0

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.senkou, self.p.ma_period) + 3
        if len(self.data) < warmup:
            return
        if self.order:
            return
        self._sync_position_state()
        if self.position:
            if self._close_on_protection():
                return
            if self._close_on_ema_reversal():
                return
            self._update_break_even()
            self._update_trailing_stop()
            return
        action = self._compute_entry_signal()
        if action == 0:
            return
        self.signal_count += 1
        current_close = float(self.data.close[0])
        pip_size = self._pip_size()
        if action > 0:
            mode = 'market'
            if current_close > self.long_entry + 4 * pip_size:
                mode = 'buy_limit_approx'
            self.log(f'long signal entry={self.long_entry:.2f} close={current_close:.2f} mode={mode}')
            self._pending_signal = 1
            self.order = self.buy(size=self.p.lot)
            return
        mode = 'market'
        if current_close < self.short_entry - 4 * pip_size:
            mode = 'sell_limit_approx'
        self.log(f'short signal entry={self.short_entry:.2f} close={current_close:.2f} mode={mode}')
        self._pending_signal = -1
        self.order = self.sell(size=self.p.lot)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            self._sync_position_state()
            if self._pending_signal > 0:
                self.long_cross = 0.0
                self.long_entry = 0.0
            elif self._pending_signal < 0:
                self.short_cross = 0.0
                self.short_entry = 0.0
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.rejected_order_count += 1
        if not self.position:
            self._clear_position_state()
        self._pending_signal = 0
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
