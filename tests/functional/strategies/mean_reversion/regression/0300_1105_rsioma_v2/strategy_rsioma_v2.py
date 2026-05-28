from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader.feeds as btfeeds
import backtrader.indicators as btind
from backtrader.indicator import Indicator
from backtrader.strategy import Strategy
from backtrader.utils.dateintern import num2date
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low',
        '<CLOSE>': 'close', '<TICKVOL>': 'volume', '<VOL>': 'openinterest',
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


class RsiomaV2(Indicator):
    lines = ('rsioma', 'signal')
    params = dict(
        rsioma_period=14,
        ma_rsioma_period=21,
        mom_period=1,
    )

    def __init__(self):
        base = btind.EMA(self.data.close, period=max(int(self.p.rsioma_period), 1))
        if int(self.p.mom_period) > 1:
            base = btind.Momentum(base, period=int(self.p.mom_period))
        self.l.rsioma = btind.RSI(base, period=max(int(self.p.rsioma_period), 1), safediv=True)
        self.l.signal = btind.EMA(self.l.rsioma, period=max(int(self.p.ma_rsioma_period), 1))


class RsiomaV2Strategy(Strategy):
    params = dict(
        mode='breakdown',
        signal_bar=1,
        rsioma_period=14,
        ma_rsioma_period=21,
        mom_period=1,
        main_trend_long=60,
        main_trend_short=40,
        stop_loss_points=1000,
        take_profit_points=2000,
        lot=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.indicator = RsiomaV2(
            self.data,
            rsioma_period=self.p.rsioma_period,
            ma_rsioma_period=self.p.ma_rsioma_period,
            mom_period=self.p.mom_period,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.buy_signal_count = 0
        self.sell_signal_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self.pending_entry_direction = 0
        self.warmup = max(int(self.p.ma_rsioma_period) * 5, int(self.p.rsioma_period) * 5, 50)

    def log(self, text):
        dt = num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _signal_indexes(self):
        current = -max(int(self.p.signal_bar), 1)
        previous = current - 1
        older = current - 2
        return current, previous, older

    def _breakdown_signals(self):
        current, previous, _ = self._signal_indexes()
        rsi_now = float(self.indicator.rsioma[current])
        rsi_prev = float(self.indicator.rsioma[previous])
        buy_signal = rsi_prev <= float(self.p.main_trend_long) and rsi_now > float(self.p.main_trend_long)
        sell_signal = rsi_prev >= float(self.p.main_trend_short) and rsi_now < float(self.p.main_trend_short)
        return buy_signal, sell_signal

    def _twist_signals(self):
        current, previous, older = self._signal_indexes()
        rsi_now = float(self.indicator.rsioma[current])
        rsi_prev = float(self.indicator.rsioma[previous])
        rsi_older = float(self.indicator.rsioma[older])
        return rsi_prev < rsi_older and rsi_now > rsi_prev, rsi_prev > rsi_older and rsi_now < rsi_prev

    def _cloudtwist_signals(self):
        current, previous, _ = self._signal_indexes()
        rsi_now = float(self.indicator.rsioma[current])
        rsi_prev = float(self.indicator.rsioma[previous])

        def zone(value):
            if value > float(self.p.main_trend_long):
                return 1
            if value < float(self.p.main_trend_short):
                return -1
            return 0

        current_zone = zone(rsi_now)
        previous_zone = zone(rsi_prev)
        return previous_zone != 1 and current_zone == 1, previous_zone != -1 and current_zone == -1

    def _get_signals(self):
        mode = str(self.p.mode).lower()
        if mode == 'twist':
            return self._twist_signals()
        if mode == 'cloudtwist':
            return self._cloudtwist_signals()
        return self._breakdown_signals()

    def _reset_levels(self):
        self.entry_price = None
        self.stop_price = None
        self.target_price = None

    def _open_long(self):
        self.pending_entry_direction = 1
        self.buy(size=self.p.lot)

    def _open_short(self):
        self.pending_entry_direction = -1
        self.sell(size=self.p.lot)

    def _close_position(self, reason):
        self.log(reason)
        self.close()
        self._reset_levels()

    def _manage_protective_levels(self):
        if not self.position or self.entry_price is None:
            return False

        low = float(self.data.low[0])
        high = float(self.data.high[0])

        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._close_position(f'close long stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and high >= self.target_price:
                self._close_position(f'close long target={self.target_price:.2f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._close_position(f'close short stop={self.stop_price:.2f}')
                return True
            if self.target_price is not None and low <= self.target_price:
                self._close_position(f'close short target={self.target_price:.2f}')
                return True

        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < self.warmup + max(int(self.p.signal_bar), 1) + 2:
            return

        if self._manage_protective_levels():
            return

        buy_signal, sell_signal = self._get_signals()
        rsi_now = float(self.indicator.rsioma[0])
        signal_now = float(self.indicator.signal[0])

        if buy_signal:
            self.buy_signal_count += 1
        if sell_signal:
            self.sell_signal_count += 1

        if self.position:
            if self.position.size > 0 and sell_signal:
                self.log(f'close long & sell rsioma={rsi_now:.4f} signal={signal_now:.4f}')
                self.close()
                self._reset_levels()
                self._open_short()
                return
            if self.position.size < 0 and buy_signal:
                self.log(f'close short & buy rsioma={rsi_now:.4f} signal={signal_now:.4f}')
                self.close()
                self._reset_levels()
                self._open_long()
                return
        else:
            if buy_signal:
                self.log(f'buy rsioma={rsi_now:.4f} signal={signal_now:.4f}')
                self._open_long()
                return
            if sell_signal:
                self.log(f'sell rsioma={rsi_now:.4f} signal={signal_now:.4f}')
                self._open_short()
                return

    def notify_order(self, order):
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.rejected_order_count += 1
            self.pending_entry_direction = 0
            self.log(f'order {order.getstatusname()}')
            return

        if order.status != order.Completed:
            return

        self.completed_order_count += 1

        if self.pending_entry_direction == 1 and order.isbuy():
            self.buy_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price - self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price + self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return

        if self.pending_entry_direction == -1 and order.issell():
            self.sell_count += 1
            self.entry_price = order.executed.price
            self.stop_price = self.entry_price + self.p.stop_loss_points * self.p.point if self.p.stop_loss_points > 0 else None
            self.target_price = self.entry_price - self.p.take_profit_points * self.p.point if self.p.take_profit_points > 0 else None
            self.pending_entry_direction = 0
            return

        if not self.position:
            self._reset_levels()

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
