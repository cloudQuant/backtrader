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


class PivotStopFeed(btfeeds.PandasData):
    lines = ('pivot', 'resist1', 'resist2', 'resist3', 'support1', 'support2', 'support3')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3),
        ('volume', 4), ('openinterest', 5),
        ('pivot', 6), ('resist1', 7), ('resist2', 8), ('resist3', 9),
        ('support1', 10), ('support2', 11), ('support3', 12),
    )


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


def build_pivot_frame(df):
    daily = df.resample('1D').agg({'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    prev = daily.shift(1)
    levels = pd.DataFrame(index=daily.index)
    levels['pivot'] = (prev['low'] + prev['high'] + prev['close']) / 3.0
    levels['resist1'] = 2.0 * levels['pivot'] - prev['low']
    levels['support1'] = 2.0 * levels['pivot'] - prev['high']
    levels['resist2'] = levels['pivot'] + (levels['resist1'] - levels['support1'])
    levels['support2'] = levels['pivot'] - (levels['resist1'] - levels['support1'])
    levels['resist3'] = prev['high'] + 2.0 * (levels['pivot'] - prev['low'])
    levels['support3'] = prev['low'] - 2.0 * (prev['high'] - levels['pivot'])
    signal_df = df.copy()
    signal_df['session_date'] = signal_df.index.normalize()
    signal_df = signal_df.join(levels, on='session_date')
    signal_df = signal_df.drop(columns=['session_date'])
    return signal_df


class GpfTcpivotStopStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        max_risk=0.02,
        decrease_factor=3.0,
        tgt_profit=3,
        is_trade_day=False,
        mod_sl=False,
        point=0.01,
    )

    def __init__(self):
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.order = None
        self.stop_price = None
        self.take_price = None
        self.first_target = None
        self._position_was_open = False
        self._closed_trade_pnls = []

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        return max(round(float(lot), 2), 0.01)

    def _loss_streak(self):
        losses = 0
        for pnl in reversed(self._closed_trade_pnls):
            if pnl > 0:
                break
            if pnl < 0:
                losses += 1
        return losses

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.max_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        if float(self.p.decrease_factor) > 0:
            losses = self._loss_streak()
            if losses > 1:
                lot = lot - lot * losses / float(self.p.decrease_factor)
        return self._normalize_lot(lot)

    def _current_levels(self):
        pivot = float(self.data.pivot[0])
        levels = {
            'pivot': pivot,
            'resist1': float(self.data.resist1[0]),
            'resist2': float(self.data.resist2[0]),
            'resist3': float(self.data.resist3[0]),
            'support1': float(self.data.support1[0]),
            'support2': float(self.data.support2[0]),
            'support3': float(self.data.support3[0]),
        }
        return levels

    def _resolve_buy_levels(self, levels):
        if int(self.p.tgt_profit) == 1:
            return levels['support1'], levels['resist1']
        if int(self.p.tgt_profit) == 2:
            return levels['support2'], levels['resist2']
        return levels['support3'], levels['resist3']

    def _resolve_sell_levels(self, levels):
        if int(self.p.tgt_profit) == 1:
            return levels['resist1'], levels['support1']
        if int(self.p.tgt_profit) == 2:
            return levels['resist2'], levels['support2']
        return levels['resist3'], levels['support3']

    def _clear_targets(self):
        self.stop_price = None
        self.take_price = None
        self.first_target = None

    def _apply_mod_sl(self):
        if not bool(self.p.mod_sl) or not self.position or self.first_target is None:
            return
        entry = float(self.position.price)
        if self.position.size > 0 and float(self.data.high[0]) >= self.first_target:
            new_stop = entry
            if self.stop_price is None or new_stop > self.stop_price:
                self.stop_price = new_stop
        elif self.position.size < 0 and float(self.data.low[0]) <= self.first_target:
            new_stop = entry
            if self.stop_price is None or new_stop < self.stop_price:
                self.stop_price = new_stop

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) < 3:
            return
        levels = self._current_levels()
        if not all(math.isfinite(v) for v in levels.values()):
            return
        if self.order is not None:
            return
        if bool(self.p.is_trade_day) and self.position:
            current_dt = bt.num2date(self.data.datetime[0])
            if current_dt.hour == 23:
                self.log('close position by trade-day cutoff')
                self.order = self.close()
                return
        self._apply_mod_sl()
        if self._check_exit_levels():
            return
        close1 = float(self.data.close[-1])
        close2 = float(self.data.close[-2])
        pivot = levels['pivot']
        open_buy = close1 > pivot and close2 <= pivot
        open_sell = close1 < pivot and close2 >= pivot
        if self.position:
            return
        lot = self._current_lot()
        if open_buy and not open_sell:
            self.stop_price, self.take_price = self._resolve_buy_levels(levels)
            self.first_target = levels['resist1']
            self.log(f'buy signal pivot={pivot:.5f} close1={close1:.5f} close2={close2:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return
        if open_sell and not open_buy:
            self.stop_price, self.take_price = self._resolve_sell_levels(levels)
            self.first_target = levels['support1']
            self.log(f'sell signal pivot={pivot:.5f} close1={close1:.5f} close2={close2:.5f} lot={lot:.2f}')
            self.order = self.sell(size=lot)

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self._clear_targets()
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
        self._closed_trade_pnls.append(float(trade.pnlcomm))
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self._clear_targets()
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
