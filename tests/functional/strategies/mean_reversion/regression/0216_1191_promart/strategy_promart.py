from __future__ import absolute_import, division, print_function, unicode_literals

import io
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_SRC = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_SRC) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_SRC))

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


class ProMartStrategy(bt.Strategy):
    params = dict(
        dml=1000.0,
        doubling_count=1,
        stop_points=500,
        take_points=1500,
        macd1_fast=5,
        macd1_slow=20,
        macd2_fast=10,
        macd2_slow=15,
        macd_signal=3,
        base_lot_scale=0.001,
        volume_min=0.1,
        volume_step=0.1,
        volume_max=100.0,
        margin_per_lot=250.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.median_price = (self.data.high + self.data.low) / 2.0
        self.macd_entry = bt.indicators.MACD(
            self.median_price,
            period_me1=self.p.macd1_fast,
            period_me2=self.p.macd1_slow,
            period_signal=self.p.macd_signal,
        )
        self.macd_trend = bt.indicators.MACD(
            self.median_price,
            period_me1=self.p.macd2_fast,
            period_me2=self.p.macd2_slow,
            period_signal=self.p.macd_signal,
        )
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._position_was_open = False
        self.order = None
        self.entry_price = None
        self.stop_price = None
        self.take_price = None
        self.loss_streak = 0
        self.last_lot = 0.0
        self.current_trade_direction = 0
        self.last_trade_direction = 0
        self.last_trade_was_loss = False

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _round_volume_down(self, value):
        if value <= 0:
            return 0.0
        steps = int(value / self.p.volume_step)
        return round(steps * self.p.volume_step, 8)

    def _calc_base_lot(self):
        cash = float(self.broker.getcash())
        base_lot = cash / max(self.p.dml, 1.0) * self.p.base_lot_scale
        base_lot = self._round_volume_down(base_lot)
        if base_lot < self.p.volume_min:
            base_lot = self.p.volume_min
        base_lot = min(base_lot, self.p.volume_max)
        return round(base_lot, 8)

    def _calc_lot(self):
        cash = float(self.broker.getcash())
        base_lot = self._calc_base_lot()
        multiplier = 2 ** min(self.loss_streak, self.p.doubling_count)
        lot = self._round_volume_down(base_lot * multiplier)
        lot = min(lot, self.p.volume_max)
        while lot >= self.p.volume_min and cash < lot * self.p.margin_per_lot:
            lot = self._round_volume_down(lot - self.p.volume_step)
        if lot < self.p.volume_min:
            return 0.0
        return round(lot, 8)

    def _manage_position(self):
        if not self.position:
            return False
        if self.position.size > 0:
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self.log(f'close long stop={self.stop_price:.2f}')
                self.order = self.close()
                return True
            if self.take_price is not None and float(self.data.high[0]) >= self.take_price:
                self.log(f'close long take={self.take_price:.2f}')
                self.order = self.close()
                return True
            return False
        if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
            self.log(f'close short stop={self.stop_price:.2f}')
            self.order = self.close()
            return True
        if self.take_price is not None and float(self.data.low[0]) <= self.take_price:
            self.log(f'close short take={self.take_price:.2f}')
            self.order = self.close()
            return True
        return False

    def _signal_direction(self):
        entry0 = float(self.macd_entry.macd[0])
        entry1 = float(self.macd_entry.macd[-1])
        entry2 = float(self.macd_entry.macd[-2])
        trend0 = float(self.macd_trend.macd[0])
        trend1 = float(self.macd_trend.macd[-1])
        buy_sig = entry0 > entry1 and entry1 < entry2 and trend0 > trend1
        sell_sig = entry0 < entry1 and entry1 > entry2 and trend0 < trend1
        return buy_sig, sell_sig, entry2, entry1, entry0, trend1, trend0

    def next(self):
        self.bar_num += 1
        warmup = max(self.p.macd1_slow, self.p.macd2_slow) + self.p.macd_signal + 5
        if len(self.data) < warmup:
            return
        if self.order:
            return
        if self._manage_position():
            return
        if self.position:
            return

        buy_sig, sell_sig, entry2, entry1, entry0, trend1, trend0 = self._signal_direction()
        direction = 0
        reason = ''
        if self.last_trade_was_loss and self.last_trade_direction != 0:
            direction = -self.last_trade_direction
            reason = 'loss reversal'
        else:
            if buy_sig:
                direction = 1
                reason = 'macd buy'
            elif sell_sig:
                direction = -1
                reason = 'macd sell'

        if direction == 0:
            return

        lot = self._calc_lot()
        if lot < self.p.volume_min:
            return
        self.last_lot = lot
        if direction > 0:
            self.log(
                f'buy reason={reason} lot={lot:.2f} macd1=({entry2:.4f},{entry1:.4f},{entry0:.4f}) '
                f'macd2=({trend1:.4f},{trend0:.4f})'
            )
            self.order = self.buy(size=lot)
            return
        self.log(
            f'sell reason={reason} lot={lot:.2f} macd1=({entry2:.4f},{entry1:.4f},{entry0:.4f}) '
            f'macd2=({trend1:.4f},{trend0:.4f})'
        )
        self.order = self.sell(size=lot)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if self.position:
                self.entry_price = float(order.executed.price)
                if self.position.size > 0:
                    self.stop_price = round(self.entry_price - self.p.stop_points * self.p.point, self.p.price_digits)
                    self.take_price = round(self.entry_price + self.p.take_points * self.p.point, self.p.price_digits)
                    self.log(f'long filled price={self.entry_price:.2f} size={abs(self.position.size):.2f} stop={self.stop_price:.2f} take={self.take_price:.2f}')
                else:
                    self.stop_price = round(self.entry_price + self.p.stop_points * self.p.point, self.p.price_digits)
                    self.take_price = round(self.entry_price - self.p.take_points * self.p.point, self.p.price_digits)
                    self.log(f'short filled price={self.entry_price:.2f} size={abs(self.position.size):.2f} stop={self.stop_price:.2f} take={self.take_price:.2f}')
            else:
                self.entry_price = None
                self.stop_price = None
                self.take_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order {order.getstatusname()}')
            if not self.position:
                self.entry_price = None
                self.stop_price = None
                self.take_price = None
        self.order = None

    def notify_trade(self, trade):
        if trade.isopen and not self._position_was_open:
            if trade.size > 0:
                self.buy_count += 1
                self.current_trade_direction = 1
            elif trade.size < 0:
                self.sell_count += 1
                self.current_trade_direction = -1
            self._position_was_open = True
            return
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.last_trade_direction = self.current_trade_direction
        if trade.pnlcomm >= 0:
            self.win_count += 1
            self.loss_streak = 0
            self.last_trade_was_loss = False
        else:
            self.loss_count += 1
            self.loss_streak = min(self.loss_streak + 1, self.p.doubling_count)
            self.last_trade_was_loss = True
        self.current_trade_direction = 0
        self._position_was_open = False
        self.log(
            f'trade closed pnl={trade.pnlcomm:.2f} loss_streak={self.loss_streak} '
            f'last_trade_direction={self.last_trade_direction} last_trade_was_loss={self.last_trade_was_loss}'
        )
