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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class ArttraderV15Strategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        point_size=0.01,
        ema_speed=11,
        big_jump_pips=30,
        double_jump_pips=55,
        stop_loss_pips=20,
        emergency_loss_pips=50,
        take_profit_pips=25,
        slope_small_pips=5,
        slope_large_pips=8,
        minutes_begin=25,
        minutes_end=25,
        slip_begin_pips=0,
        slip_end_pips=0,
        min_volume=0,
        adjust_pips=1,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.h1_feed = self.datas[1]
        self.order = None
        self.close_order = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        self.open_price_ref = None
        self.h1_ema = bt.indicators.EMA(self.h1_feed.open, period=self.p.ema_speed)

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None
        self.open_price_ref = None

    def _initialize_exit_levels(self, side, current_open):
        adjust = self.p.adjust_pips * self.p.point_size
        spread_adjust = float(self.data0_feed.spread[0]) * self.p.point_size if hasattr(self.data0_feed, 'spread') else 0.0
        if side == 'long':
            self.open_price_ref = current_open - adjust - spread_adjust
            self.stop_price = self.entry_price - self.p.emergency_loss_pips * self.p.point_size if self.p.emergency_loss_pips > 0 else None
            self.limit_price = self.entry_price + self.p.take_profit_pips * self.p.point_size if self.p.take_profit_pips > 0 else None
        else:
            self.open_price_ref = current_open + adjust + spread_adjust
            self.stop_price = self.entry_price + self.p.emergency_loss_pips * self.p.point_size if self.p.emergency_loss_pips > 0 else None
            self.limit_price = self.entry_price - self.p.take_profit_pips * self.p.point_size if self.p.take_profit_pips > 0 else None

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _check_emergency_exit(self):
        if not self.position or self.close_order is not None:
            return False
        high = float(self.data0_feed.high[0])
        low = float(self.data0_feed.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self._submit_close(f'emergency stop hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and high >= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self._submit_close(f'emergency stop hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and low <= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        return False

    def _bar_minute(self):
        return bt.num2date(self.data0_feed.datetime[0]).minute

    def _jump_filters_pass(self):
        if len(self.data0_feed) < 6:
            return False
        big_jump = self.p.big_jump_pips * self.p.point_size
        double_jump = self.p.double_jump_pips * self.p.point_size
        opens = [float(self.data0_feed.open[-i]) for i in range(0, 6)]
        for i in range(5):
            if abs(opens[i] - opens[i + 1]) >= big_jump:
                return False
        if abs(opens[0] - opens[2]) >= double_jump:
            return False
        if abs(opens[1] - opens[3]) >= double_jump:
            return False
        if abs(opens[2] - opens[4]) >= double_jump:
            return False
        if abs(opens[3] - opens[5]) >= double_jump:
            return False
        return True

    def _entry_signals(self):
        if len(self.h1_feed) < 2 or len(self.data0_feed) < 6:
            return False, False
        ema_slope = float(self.h1_ema[0] - self.h1_ema[-1])
        slope_small = self.p.slope_small_pips * self.p.point_size
        slope_large = self.p.slope_large_pips * self.p.point_size
        minute = self._bar_minute()
        open_ = float(self.data0_feed.open[0])
        high = float(self.data0_feed.high[0])
        low = float(self.data0_feed.low[0])
        close = float(self.data0_feed.close[0])
        slip_begin = self.p.slip_begin_pips * self.p.point_size
        begin_buy = False
        begin_sell = False
        if slope_small <= ema_slope <= slope_large:
            if minute > self.p.minutes_begin and close <= open_ and close <= low + slip_begin:
                begin_buy = True
        if -slope_large <= ema_slope <= -slope_small:
            if minute > self.p.minutes_begin and close >= open_ and close >= high - slip_begin:
                begin_sell = True
        if not self._jump_filters_pass():
            return False, False
        return begin_buy, begin_sell

    def _smart_exit_signals(self):
        if not self.position or self.open_price_ref is None:
            return False, False
        minute = self._bar_minute()
        open_ = float(self.data0_feed.open[0])
        high = float(self.data0_feed.high[0])
        low = float(self.data0_feed.low[0])
        close = float(self.data0_feed.close[0])
        slip_end = self.p.slip_end_pips * self.p.point_size
        end_buy = False
        end_sell = False
        if self.position.size > 0:
            if close - self.open_price_ref <= -(self.p.stop_loss_pips * self.p.point_size):
                if minute > self.p.minutes_end and close >= open_ and close >= high - slip_end:
                    end_buy = True
        else:
            if self.open_price_ref - close <= -(self.p.stop_loss_pips * self.p.point_size):
                if minute > self.p.minutes_end and close <= open_ and close <= low + slip_end:
                    end_sell = True
        prev_volume = float(self.data0_feed.volume[-1]) if len(self.data0_feed) > 1 else 0.0
        if prev_volume <= self.p.min_volume:
            if self.position.size > 0:
                end_buy = True
            else:
                end_sell = True
        return end_buy, end_sell

    def next(self):
        if len(self.h1_feed) < 2 or len(self.data0_feed) < 6:
            return
        if self._check_emergency_exit():
            return
        if self.position and self.close_order is None:
            end_buy, end_sell = self._smart_exit_signals()
            if end_buy:
                self._submit_close('smart stop/volume exit')
                return
            if end_sell:
                self._submit_close('smart stop/volume exit')
                return
        if self.position or self.order is not None:
            return
        begin_buy, begin_sell = self._entry_signals()
        current_open = float(self.data0_feed.open[0])
        size = max(0.01, float(self.p.fixed_lot))
        if begin_buy:
            self.active_side = 'long'
            self.order = self.buy(size=size)
            self.entry_price = float(self.data0_feed.close[0])
            self._initialize_exit_levels('long', current_open)
            self.log(f'OPEN LONG signal price={self.entry_price:.5f}')
            return
        if begin_sell:
            self.active_side = 'short'
            self.order = self.sell(size=size)
            self.entry_price = float(self.data0_feed.close[0])
            self._initialize_exit_levels('short', current_open)
            self.log(f'OPEN SHORT signal price={self.entry_price:.5f}')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.order:
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.order = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.order:
                self.order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        side = self.active_side or ('long' if trade.long else 'short')
        self.log(f'TRADE CLOSED side={side} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()
