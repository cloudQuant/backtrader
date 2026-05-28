from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math
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


class DiffTfMaStrategy(bt.Strategy):
    params = dict(
        period_ma=10,
        higher_tf_compression=240,
        current_tf_compression=15,
        reverse_trade=False,
        volume=0.1,
        stop_loss_points=0,
        take_profit_points=0,
        point=0.01,
    )

    def __init__(self):
        self.data_current = self.datas[0]
        self.data_senior = self.datas[1]
        ratio = max(int(self.p.higher_tf_compression / self.p.current_tf_compression), 1)
        self.period_ma_current = max(int(self.p.period_ma * ratio), 1)
        self.ma_current = bt.ind.SMA(self.data_current.close, period=self.period_ma_current)
        self.ma_senior = bt.ind.SMA(self.data_senior.close, period=self.p.period_ma)
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.stop_price = None
        self.take_profit_price = None
        self._semantic_log = None
        trade_log_root = os.environ.get('BT_TRADE_LOG_DIR', '').strip()
        if trade_log_root:
            log_dir = Path(trade_log_root) / 'python'
            log_dir.mkdir(parents=True, exist_ok=True)
            self._semantic_log = open(log_dir / 'semantic.log', 'w', encoding='utf-8')

    @staticmethod
    def _fmt_log_value(value):
        if isinstance(value, float):
            if not math.isfinite(value):
                return 'nan'
            return f'{value:.10f}'
        return str(value)

    def _semantic_write(self, event, **fields):
        if self._semantic_log is None:
            return
        parts = [f'event={event}']
        for key, value in fields.items():
            parts.append(f'{key}={self._fmt_log_value(value)}')
        self._semantic_log.write('|'.join(parts) + '\n')

    def _semantic_common(self):
        return dict(
            bar_num=self.bar_num,
            base_len=len(self.data_current),
            signal_len=len(self.data_senior),
            dt0=self.data_current.datetime.datetime(0),
            dt1=self.data_senior.datetime.datetime(0),
            pos=float(self.position.size),
            order_active=int(self.order is not None),
        )

    def _semantic_bar(self, reason, action='none', **values):
        fields = self._semantic_common()
        fields.update(values)
        fields['reason'] = reason
        fields['action'] = action
        self._semantic_write('bar', **fields)

    def stop(self):
        if self._semantic_log is not None:
            self._semantic_log.flush()
            self._semantic_log.close()
            self._semantic_log = None

    def _clear_risk(self):
        self.stop_price = None
        self.take_profit_price = None

    def _set_risk(self, price, direction):
        stop_distance = self.p.stop_loss_points * self.p.point
        take_distance = self.p.take_profit_points * self.p.point
        if direction > 0:
            self.stop_price = price - stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price + take_distance if self.p.take_profit_points > 0 else None
        else:
            self.stop_price = price + stop_distance if self.p.stop_loss_points > 0 else None
            self.take_profit_price = price - take_distance if self.p.take_profit_points > 0 else None

    def _check_exit_levels(self):
        if not self.position:
            self._clear_risk()
            return False
        if self.position.size > 0:
            if self.stop_price is not None and float(self.data_current.low[0]) <= self.stop_price:
                self.order = self.close(data=self.data_current)
                self._semantic_bar('risk_exit', action='close_long_stop')
                return True
            if self.take_profit_price is not None and float(self.data_current.high[0]) >= self.take_profit_price:
                self.order = self.close(data=self.data_current)
                self._semantic_bar('risk_exit', action='close_long_take_profit')
                return True
        else:
            if self.stop_price is not None and float(self.data_current.high[0]) >= self.stop_price:
                self.order = self.close(data=self.data_current)
                self._semantic_bar('risk_exit', action='close_short_stop')
                return True
            if self.take_profit_price is not None and float(self.data_current.low[0]) <= self.take_profit_price:
                self.order = self.close(data=self.data_current)
                self._semantic_bar('risk_exit', action='close_short_take_profit')
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data_current) < self.period_ma_current + 3 or len(self.data_senior) < self.p.period_ma + 3:
            self._semantic_bar('warmup')
            return
        if self.order:
            self._semantic_bar('pending_order')
            return
        if self._check_exit_levels():
            return

        ma_tf1 = float(self.ma_senior[-1])
        ma_tf2 = float(self.ma_senior[-2])
        ma1 = float(self.ma_current[-1])
        ma2 = float(self.ma_current[-2])
        if not all(v == v for v in [ma_tf1, ma_tf2, ma1, ma2]):
            self._semantic_bar('nan', ma_tf1=ma_tf1, ma_tf2=ma_tf2, ma1=ma1, ma2=ma2)
            return

        open_long = False
        open_short = False
        if ma_tf2 < ma2 and ma_tf1 > ma1:
            open_long = not self.p.reverse_trade
            open_short = self.p.reverse_trade
        if ma_tf2 > ma2 and ma_tf1 < ma1:
            open_short = not self.p.reverse_trade
            open_long = self.p.reverse_trade

        signal_values = dict(
            ma_tf1=ma_tf1,
            ma_tf2=ma_tf2,
            ma1=ma1,
            ma2=ma2,
            open_long=int(open_long),
            open_short=int(open_short),
        )

        if open_long:
            if self.position.size < 0:
                self._semantic_bar('signal', action='close_short', **signal_values)
                self.order = self.close(data=self.data_current)
                return
            if self.position.size == 0:
                self._semantic_bar('signal', action='open_long', **signal_values)
                self.order = self.buy(data=self.data_current, size=self.p.volume)
                return
        if open_short:
            if self.position.size > 0:
                self._semantic_bar('signal', action='close_long', **signal_values)
                self.order = self.close(data=self.data_current)
                return
            if self.position.size == 0:
                self._semantic_bar('signal', action='open_short', **signal_values)
                self.order = self.sell(data=self.data_current, size=self.p.volume)
                return
        self._semantic_bar('signal', **signal_values)

    def notify_order(self, order):
        self._semantic_write(
            'order',
            bar_num=self.bar_num,
            status=order.getstatusname(),
            ref=order.ref,
            side='BUY' if order.isbuy() else 'SELL',
            created_size=float(getattr(order.created, 'size', 0.0)),
            executed_size=float(order.executed.size),
            executed_price=float(order.executed.price),
            executed_comm=float(order.executed.comm),
            pos=float(self.position.size),
        )
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy() and order.executed.size > 0:
                self.buy_count += 1
                if self.position.size > 0:
                    self._set_risk(order.executed.price, 1)
            elif order.issell() and order.executed.size < 0:
                self.sell_count += 1
                if self.position.size < 0:
                    self._set_risk(order.executed.price, -1)
            elif self.position.size == 0:
                self._clear_risk()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self._semantic_write(
            'trade',
            bar_num=self.bar_num,
            status='closed',
            ref=getattr(trade, 'ref', ''),
            size=float(trade.size),
            price=float(trade.price),
            pnl=float(trade.pnl),
            pnlcomm=float(trade.pnlcomm),
            pos=float(self.position.size),
        )
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        if not self.position:
            self._clear_risk()
