from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
BACKTRADER_REPO = WORKSPACE_ROOT / 'backtrader'
if str(BACKTRADER_REPO) not in sys.path:
    sys.path.insert(0, str(BACKTRADER_REPO))

import backtrader as bt
import pandas as pd

RFTL_WEIGHTS = [
    -0.0025097319,
    0.0513007762,
    0.1142800493,
    0.1699342860,
    0.2025269304,
    0.2025269304,
    0.1699342860,
    0.1142800493,
    0.0513007762,
    -0.0025097319,
]


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
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5), ('spread', 6),
    )


class RFTLIndicator(bt.Indicator):
    lines = ('rftl',)
    params = dict(weights=tuple(RFTL_WEIGHTS))

    def __init__(self):
        total = 0.0
        for idx, weight in enumerate(self.p.weights):
            total += float(weight) * self.data.close(-idx)
        self.lines.rftl = total
        self.addminperiod(len(self.p.weights) + 1)


class RsiRftlEaStrategy(bt.Strategy):
    params = dict(
        fixed_lot=1.0,
        point_size=0.01,
        stoploss_pips=50,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=5,
        rsi_period=30,
        lookback_bars=500,
    )

    def __init__(self):
        self.data0_feed = self.datas[0]
        self.rsi = bt.indicators.RSI(self.data0_feed.close, period=self.p.rsi_period)
        self.rftl = RFTLIndicator(self.data0_feed)
        self.entry_order = None
        self.stop_order = None
        self.limit_order = None
        self.close_order = None
        self.active_side = None
        self.active_stop_price = None
        self.pending_side = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_bar_dt = None

    def log(self, text):
        dt = bt.num2date(self.data0_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _new_bar(self):
        current = bt.num2date(self.data0_feed.datetime[0])
        if self.last_bar_dt == current:
            return False
        self.last_bar_dt = current
        return True

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _place_exit_orders(self):
        if not self.position:
            return
        size = abs(self.position.size)
        stop_distance = self.p.stoploss_pips * self.p.point_size
        take_distance = self.p.takeprofit_pips * self.p.point_size
        if self.position.size > 0:
            stop_price = self.position.price - stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price + take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)
        else:
            stop_price = self.position.price + stop_distance if self.p.stoploss_pips > 0 else None
            take_price = self.position.price - take_distance if self.p.takeprofit_pips > 0 else None
            if stop_price is not None:
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)
                self.active_stop_price = stop_price
            if take_price is not None:
                self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=take_price, oco=self.stop_order)

    def _apply_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0 or self.p.trailing_step_pips <= 0 or self.entry_order is not None:
            return
        trail_stop = self.p.trailing_stop_pips * self.p.point_size
        trail_step = self.p.trailing_step_pips * self.p.point_size
        price = float(self.data0_feed.close[0])
        size = abs(self.position.size)
        if self.position.size > 0:
            if price - self.position.price <= trail_stop + trail_step:
                return
            candidate = price - trail_stop
            if self.active_stop_price is None or candidate > self.active_stop_price + trail_step:
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate
        else:
            if self.position.price - price <= trail_stop + trail_step:
                return
            candidate = price + trail_stop
            if self.active_stop_price is None or candidate < self.active_stop_price - trail_step:
                if self.stop_order is not None:
                    self.cancel(self.stop_order)
                self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=candidate, oco=self.limit_order)
                self.active_stop_price = candidate

    def _collect_rsi_series(self, count):
        values = []
        max_count = min(count, len(self.data0_feed) - 1)
        for idx in range(max_count):
            try:
                val = float(self.rsi[-idx]) if idx else float(self.rsi[0])
            except Exception:
                break
            if math.isnan(val):
                break
            values.append(val)
        return values

    def _scan_signals(self):
        rsi_values = self._collect_rsi_series(self.p.lookback_bars)
        if len(rsi_values) < 10:
            return False, False, rsi_values
        buffer_up = [0.0] * len(rsi_values)
        buffer_dw = [0.0] * len(rsi_values)
        for i in range(len(rsi_values) - 3):
            if rsi_values[i + 1] < rsi_values[i + 2] and rsi_values[i + 2] >= rsi_values[i + 3]:
                buffer_up[i + 2] = rsi_values[i + 2]
            if rsi_values[i + 1] > rsi_values[i + 2] and rsi_values[i + 2] <= rsi_values[i + 3]:
                buffer_dw[i + 2] = rsi_values[i + 2]

        vol1 = vol2 = vol3 = vol4 = 0.0
        pos1 = pos2 = pos3 = pos4 = -1
        k = 0
        for i, value in enumerate(buffer_up):
            if value > 40 and k == 0:
                vol1 = value
                pos1 = i
                k += 1
            elif value > 60 and value > vol1 and k != 0:
                vol2 = value
                pos2 = i
                k += 1
        if pos2 > 0:
            for i in range(pos2):
                if buffer_dw[i] != 0.0 and buffer_dw[i] < 40:
                    vol1 = 0.0
                    vol2 = 0.0
                    pos1 = pos2 = -1
                    break

        k = 0
        for i, value in enumerate(buffer_dw):
            if value != 0.0 and value < 60 and k == 0:
                vol3 = value
                pos3 = i
                k += 1
            elif value != 0.0 and value < 40 and value < vol3 and k != 0:
                vol4 = value
                pos4 = i
                k += 1
        if pos4 > 0:
            for i in range(pos4):
                if buffer_up[i] != 0.0 and buffer_up[i] > 60:
                    vol3 = 0.0
                    vol4 = 0.0
                    pos3 = pos4 = -1
                    break

        sell_signal = False
        buy_signal = False
        rftl_prev = float(self.rftl[-1])
        close_prev = float(self.data0_feed.close[-1])
        if vol3 != 0.0 and vol4 != 0.0 and pos4 > pos3 >= 0:
            vol_dw = vol3 + (pos3 * (vol3 - vol4) / float(pos4 - pos3))
            vol_dw1 = vol3 + ((pos3 - 1) * (vol3 - vol4) / float(pos4 - pos3))
            sell_signal = (
                rsi_values[1] < vol_dw
                and rsi_values[2] > vol_dw1
                and rftl_prev > close_prev
                and rsi_values[2] > 50
                and rsi_values[0] > 47
                and pos2 > pos4
            )
        if vol1 != 0.0 and vol2 != 0.0 and pos2 > pos1 >= 0:
            vol_up = vol1 + (pos1 * (vol1 - vol2) / float(pos2 - pos1))
            vol_up1 = vol1 + ((pos1 - 1) * (vol1 - vol2) / float(pos2 - pos1))
            buy_signal = (
                rsi_values[1] > vol_up
                and rsi_values[2] < vol_up1
                and rftl_prev < close_prev
                and rsi_values[2] < 50
                and rsi_values[0] < 55
                and pos4 > pos2
            )
        if not buy_signal and not sell_signal and math.isfinite(rftl_prev):
            rsi_now = rsi_values[0]
            rsi_prev = rsi_values[1]
            buy_signal = rsi_prev <= 50.0 < rsi_now and close_prev > rftl_prev
            sell_signal = rsi_prev >= 50.0 > rsi_now and close_prev < rftl_prev
        return buy_signal, sell_signal, rsi_values

    def _submit_entry(self, side, reason):
        if self.position or self.entry_order is not None:
            return
        size = max(0.01, float(self.p.fixed_lot))
        self.entry_order = self.buy(size=size) if side == 'long' else self.sell(size=size)
        self.log(f'OPEN {side.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_side = reverse
        self._cancel_exit_orders()
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason} reverse={reverse}')

    def next(self):
        self.bar_num += 1
        self._apply_trailing()
        if len(self.data0_feed) < max(self.p.rsi_period + 20, 60):
            return
        if not self._new_bar():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        buy_signal, sell_signal, rsi_values = self._scan_signals()
        if len(rsi_values) < 3:
            return
        if self.position.size > 0 and rsi_values[0] > 70:
            self._submit_close('rsi above 70 close long')
            return
        if self.position.size < 0 and rsi_values[0] < 30:
            self._submit_close('rsi below 30 close short')
            return
        if self.position.size < 0 and buy_signal:
            self._submit_close('buy signal while short', reverse='long')
            return
        if self.position.size > 0 and sell_signal:
            self._submit_close('sell signal while long', reverse='short')
            return
        if not self.position:
            if buy_signal:
                self._submit_entry('long', 'RSI bottom divergence with RFTL filter')
            elif sell_signal:
                self._submit_entry('short', 'RSI top divergence with RFTL filter')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                if order.executed.size > 0:
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.entry_order = None
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self._place_exit_orders()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                reverse = self.pending_side
                self.pending_side = None
                self.active_stop_price = None
                if reverse is not None and not self.position:
                    self._submit_entry(reverse, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.limit_order = None
                self.active_side = None
                self.active_stop_price = None
            elif order == self.limit_order:
                self.log(f'TAKE PROFIT FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.limit_order = None
                self.stop_order = None
                self.active_side = None
                self.active_stop_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None
                self.pending_side = None
            elif order == self.stop_order:
                self.stop_order = None
            elif order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
