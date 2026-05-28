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


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class Ichimok2005Strategy(bt.Strategy):
    params = dict(
        tenkan=9,
        kijun=26,
        senkou=52,
        lot=0.1,
        point=0.01,
        price_digits=2,
        stop_loss_pips=30,
        take_profit_pips=60,
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
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (3, 5) else 1
        return self.p.point * digits_adjust

    def _clear_position_state(self):
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0

    def _sync_position_state(self):
        if not self.position:
            self._clear_position_state()
            return
        if self._entry_price is not None and self._last_position_size == self.position.size:
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        take_distance = self.p.take_profit_pips * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price + take_distance if self.p.take_profit_pips > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price - take_distance if self.p.take_profit_pips > 0 else None

    def next(self):
        self.bar_num += 1
        warmup = self.p.senkou + self.p.kijun + 5
        if len(self.data) < warmup:
            return

        self._sync_position_state()

        if self.position:
            high = float(self.data.high[0])
            low = float(self.data.low[0])
            if self.position.size > 0:
                if self._stop_price is not None and low <= self._stop_price:
                    self.log(f'long stop hit stop={self._stop_price:.2f} low={low:.2f}')
                    self.close()
                    return
                if self._take_profit_price is not None and high >= self._take_profit_price:
                    self.log(f'long take profit hit tp={self._take_profit_price:.2f} high={high:.2f}')
                    self.close()
                    return
            else:
                if self._stop_price is not None and high >= self._stop_price:
                    self.log(f'short stop hit stop={self._stop_price:.2f} high={high:.2f}')
                    self.close()
                    return
                if self._take_profit_price is not None and low <= self._take_profit_price:
                    self.log(f'short take profit hit tp={self._take_profit_price:.2f} low={low:.2f}')
                    self.close()
                    return

        senkou_a_prev = float(self.ichimoku.senkou_span_a[-1])
        senkou_b_prev = float(self.ichimoku.senkou_span_b[-1])
        open_prev = float(self.data.open[-1])
        close_prev = float(self.data.close[-1])

        if any(math.isnan(v) for v in (senkou_a_prev, senkou_b_prev)):
            return

        buy_sig = (
            senkou_a_prev > senkou_b_prev
            and close_prev > open_prev
            and senkou_b_prev < close_prev < senkou_a_prev
        )
        sell_sig = (
            senkou_b_prev > senkou_a_prev
            and open_prev > close_prev
            and senkou_b_prev > close_prev > senkou_a_prev
        )

        if buy_sig:
            if self.position.size < 0:
                self.log(
                    f'close short on buy signal close={close_prev:.2f} cloud=({senkou_b_prev:.2f},{senkou_a_prev:.2f})'
                )
                self.close()
            self.log(
                f'buy signal close={close_prev:.2f} open={open_prev:.2f} cloud=({senkou_b_prev:.2f},{senkou_a_prev:.2f})'
            )
            self.buy(size=self.p.lot)
            return

        if sell_sig:
            if self.position.size > 0:
                self.log(
                    f'close long on sell signal close={close_prev:.2f} cloud=({senkou_a_prev:.2f},{senkou_b_prev:.2f})'
                )
                self.close()
            self.log(
                f'sell signal close={close_prev:.2f} open={open_prev:.2f} cloud=({senkou_a_prev:.2f},{senkou_b_prev:.2f})'
            )
            self.sell(size=self.p.lot)
            return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if not self.position:
            self._clear_position_state()

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
