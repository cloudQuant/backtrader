from __future__ import absolute_import, division, print_function, unicode_literals

import io
import os
from pathlib import Path

import backtrader as bt
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None, bar_shift_minutes=0):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.read().strip().split('\n')
    cleaned = '\n'.join(line.strip().strip('"') for line in lines)
    df = pd.read_csv(io.StringIO(cleaned), sep='\t')
    df['datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'], format='%Y.%m.%d %H:%M:%S')
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
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


class CGOscillator(bt.Indicator):
    lines = ('main', 'signal')
    params = (('length', 10),)

    def __init__(self):
        self.addminperiod(int(self.p.length) + 1)
        self.cgshift = (float(self.p.length) + 1.0) / 2.0

    def next(self):
        num = 0.0
        denom = 0.0
        length = int(self.p.length)
        for count in range(length):
            price = (float(self.data.high[-count]) + float(self.data.low[-count])) / 2.0
            num += (1.0 + count) * price
            denom += price
        self.lines.main[0] = (-num / denom + self.cgshift) if denom else 0.0
        self.lines.signal[0] = self.lines.main[-1] if len(self) > 1 else 0.0


class ExpCGOscillatorX2Strategy(bt.Strategy):
    """EA 0639: dual CG Oscillator trend-following strategy.

    Slow timeframe determines the market bias via CG main/signal position.
    Fast timeframe generates entries on CG/main trigger crossovers aligned with
    the slow bias. Fixed SL/TP are preserved; lot sizing is simplified to a
    fixed quantity.
    """

    params = dict(
        length_slow=10,
        length_fast=10,
        signal_bar=1,
        signal_bar_fast=1,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        buy_pos_close_fast=False,
        sell_pos_close_fast=False,
        stop_loss=1000,
        take_profit=2000,
        lots=0.1,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.data_fast = self.datas[0]
        self.data_slow = self.datas[1]

        self.cg_slow = CGOscillator(self.data_slow, length=self.p.length_slow)
        self.cg_fast = CGOscillator(self.data_fast, length=self.p.length_fast)

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
        self.pending_reentry_side = None
        self.last_fast_dt = None
        self._semantic_log = None
        log_root = os.environ.get('BT_TRADE_LOG_DIR')
        if log_root:
            log_dir = Path(log_root) / 'python'
            log_dir.mkdir(parents=True, exist_ok=True)
            self._semantic_log = open(log_dir / 'semantic.log', 'w', encoding='utf-8')

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _set_risk(self, side, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if side == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None

    def _enter_side(self, side, price):
        self.signal_count += 1
        self._set_risk(side, price)
        if side == 'buy':
            self.order = self.buy(size=self.p.lots)
        else:
            self.order = self.sell(size=self.p.lots)

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data_fast.high[0])
        low = float(self.data_fast.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def _slow_trend(self):
        signal_bar = int(self.p.signal_bar)
        main = float(self.cg_slow.main[-signal_bar])
        signal = float(self.cg_slow.signal[-signal_bar])
        if main > signal:
            return 1
        if main < signal:
            return -1
        return 0

    def _fast_signals(self, trend):
        signal_bar = int(self.p.signal_bar_fast)
        older_main = float(self.cg_fast.main[-signal_bar - 1])
        older_signal = float(self.cg_fast.signal[-signal_bar - 1])
        latest_main = float(self.cg_fast.main[-signal_bar])
        latest_signal = float(self.cg_fast.signal[-signal_bar])

        buy_close = bool(self.p.buy_pos_close_fast and latest_main < latest_signal)
        sell_close = bool(self.p.sell_pos_close_fast and latest_main > latest_signal)
        buy_open = False
        sell_open = False

        if trend < 0:
            if self.p.buy_pos_close:
                buy_close = True
            if self.p.sell_pos_open and older_main >= older_signal and latest_main < latest_signal:
                sell_open = True
        elif trend > 0:
            if self.p.sell_pos_close:
                sell_close = True
            if self.p.buy_pos_open and older_main <= older_signal and latest_main > latest_signal:
                buy_open = True

        return buy_open, sell_open, buy_close, sell_close

    def _log_semantic(self, fast_dt, trend, buy_open, sell_open, buy_close, sell_close):
        if self._semantic_log is None:
            return
        sb = int(self.p.signal_bar)
        sfb = int(self.p.signal_bar_fast)
        fields = {
            'dt': fast_dt.isoformat(),
            'dt_num': float(self.data_fast.datetime[0]),
            'bar_num': self.bar_num,
            'fast_len': len(self.data_fast),
            'slow_len': len(self.data_slow),
            'position': float(self.position.size) if self.position else 0.0,
            'trend': trend,
            'slow_main': float(self.cg_slow.main[-sb]),
            'slow_signal': float(self.cg_slow.signal[-sb]),
            'older_main': float(self.cg_fast.main[-sfb - 1]),
            'older_signal': float(self.cg_fast.signal[-sfb - 1]),
            'latest_main': float(self.cg_fast.main[-sfb]),
            'latest_signal': float(self.cg_fast.signal[-sfb]),
            'buy_open': int(buy_open),
            'sell_open': int(sell_open),
            'buy_close': int(buy_close),
            'sell_close': int(sell_close),
            'pending_reentry': self.pending_reentry_side or '',
        }
        self._semantic_log.write(','.join(f'{key}={value}' for key, value in fields.items()) + '\n')
        self._semantic_log.flush()

    def next(self):
        if len(self.data_fast) < int(self.p.length_fast) + int(self.p.signal_bar_fast) + 2:
            return
        if len(self.data_slow) < int(self.p.length_slow) + int(self.p.signal_bar) + 1:
            return

        fast_dt = self.data_fast.datetime.datetime(0)
        if self.last_fast_dt == fast_dt:
            return
        self.last_fast_dt = fast_dt

        self.bar_num += 1
        if self.order is not None:
            return

        trend = self._slow_trend()
        buy_open, sell_open, buy_close, sell_close = self._fast_signals(trend)
        price = float(self.data_fast.close[0])
        self._log_semantic(fast_dt, trend, buy_open, sell_open, buy_close, sell_close)

        if self.position:
            if self.position.size > 0 and (buy_close or sell_open):
                self.pending_reentry_side = 'sell' if sell_open else None
                self.order = self.close()
                return
            if self.position.size < 0 and (sell_close or buy_open):
                self.pending_reentry_side = 'buy' if buy_open else None
                self.order = self.close()
                return
            self._manage_position()
            return

        if self.pending_reentry_side == 'buy':
            self.pending_reentry_side = None
            self._enter_side('buy', price)
            return
        if self.pending_reentry_side == 'sell':
            self.pending_reentry_side = None
            self._enter_side('sell', price)
            return

        if buy_open:
            self._enter_side('buy', price)
        elif sell_open:
            self._enter_side('sell', price)

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
