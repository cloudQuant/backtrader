from __future__ import absolute_import, division, print_function, unicode_literals

import io
import json
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


class OppositeLastNHourTrendStrategy(bt.Strategy):
    params = dict(
        max_positions=9,
        lots=0.1,
        take_profit=20,
        max_lot=5.0,
        trading_hour=7,
        hours_to_check_trend=24,
        multiplier_1=2,
        multiplier_2=4,
        multiplier_3=8,
        multiplier_4=16,
        multiplier_5=32,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.h1 = self.datas[1]
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.open_orders = {}
        self.active_tranches = []
        self.sequence = 0
        self.last_hour_signal = None
        self.closed_trade_pnls = []
        self._semantic_file = None
        trade_log_root = os.environ.get('BT_TRADE_LOG_DIR', '').strip()
        if trade_log_root:
            log_dir = Path(trade_log_root) / 'python'
            log_dir.mkdir(parents=True, exist_ok=True)
            self._semantic_file = open(log_dir / 'semantic.log', 'w', encoding='utf-8')

    def stop(self):
        if self._semantic_file is not None:
            self._semantic_file.close()
            self._semantic_file = None

    def _semantic_tranches(self):
        return [
            {
                'id': int(t['id']),
                'direction': t['direction'],
                'size': float(t.get('size', 0.0)),
                'take_profit': None if t.get('take_profit') is None else float(t['take_profit']),
            }
            for t in self.active_tranches
        ]

    def _semantic_write(self, event, action=None, reason=None, **fields):
        if self._semantic_file is None:
            return
        bars = int(self.p.hours_to_check_trend)
        h1_len = len(self.h1)
        current_dt = bt.num2date(self.data.datetime[0])
        payload = {
            'event': event,
            'bar_num': int(self.bar_num),
            'datetime': current_dt.isoformat(sep=' '),
            'data_len': len(self.data),
            'h1_len': h1_len,
            'h1_prev_close': float(self.h1.close[-1]) if h1_len > 0 else None,
            'h1_back_close': float(self.h1.close[-bars]) if h1_len > bars else None,
            'trend_signal': self._trend_signal(),
            'position_size': float(self.position.size),
            'open_order_count': len(self.open_orders),
            'active_count': len(self.active_tranches),
            'active_tranches': self._semantic_tranches(),
            'closed_trade_count': len(self.closed_trade_pnls),
            'current_multiplier': self._current_multiplier(),
        }
        if action is not None:
            payload['action'] = action
        if reason is not None:
            payload['reason'] = reason
        payload.update(fields)
        self._semantic_file.write(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\n')
        self._semantic_file.flush()

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _submit_close_all(self):
        if self.open_orders or not self.active_tranches:
            return
        total_size = sum(float(t['size']) for t in self.active_tranches)
        order = self.close(data=self.data, size=total_size)
        self.open_orders[order.ref] = {'kind': 'exit_all'}
        self._semantic_write('submit', action='exit_all', order_ref=order.ref, size=total_size)

    def _manage_tp(self):
        if not self.active_tranches or self.open_orders:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        hit_ids = []
        for tranche in self.active_tranches:
            if tranche['direction'] == 'buy' and tranche['take_profit'] is not None and high >= float(tranche['take_profit']):
                hit_ids.append(tranche['id'])
            elif tranche['direction'] == 'sell' and tranche['take_profit'] is not None and low <= float(tranche['take_profit']):
                hit_ids.append(tranche['id'])
        if hit_ids:
            total_size = sum(float(t['size']) for t in self.active_tranches if t['id'] in hit_ids)
            order = self.close(data=self.data, size=total_size)
            self.open_orders[order.ref] = {'kind': 'exit', 'ids': hit_ids}
            self._semantic_write('submit', action='exit_tp', order_ref=order.ref, ids=hit_ids, size=total_size)

    def _current_multiplier(self):
        consecutive_losses = 0
        for pnl in reversed(self.closed_trade_pnls):
            if pnl < 0:
                consecutive_losses += 1
            else:
                break
        mapping = {
            1: float(self.p.multiplier_1),
            2: float(self.p.multiplier_2),
            3: float(self.p.multiplier_3),
            4: float(self.p.multiplier_4),
            5: float(self.p.multiplier_5),
        }
        return mapping.get(min(consecutive_losses, 5), 1.0)

    def _trend_signal(self):
        bars = int(self.p.hours_to_check_trend)
        if len(self.h1) <= bars:
            return 0
        if float(self.h1.close[-bars]) < float(self.h1.close[-1]):
            return -1
        return 1

    def next(self):
        self.bar_num += 1
        self._semantic_write('bar', action='start')
        self._manage_tp()
        if self.open_orders:
            self._semantic_write('bar', action='return', reason='open_orders')
            return
        current_dt = bt.num2date(self.data.datetime[0])
        if current_dt.hour != int(self.p.trading_hour):
            if self.active_tranches:
                self._submit_close_all()
            else:
                self._semantic_write('bar', action='return', reason='outside_trading_hour')
            return
        hour_key = (current_dt.date(), current_dt.hour)
        if self.last_hour_signal == hour_key:
            self._semantic_write('bar', action='return', reason='already_signaled_hour')
            return
        self.last_hour_signal = hour_key
        if len(self.active_tranches) >= int(self.p.max_positions):
            self._semantic_write('bar', action='return', reason='max_positions')
            return
        direction_signal = self._trend_signal()
        if direction_signal == 0:
            self._semantic_write('bar', action='return', reason='no_trend_signal')
            return
        base_lot = float(self.p.lots)
        lot = min(float(self.p.max_lot), base_lot * self._current_multiplier())
        if lot <= 0:
            self._semantic_write('bar', action='return', reason='non_positive_lot', lot=lot, direction_signal=direction_signal)
            return
        price = float(self.data.close[0])
        tp_dist = float(self.p.take_profit) * self._point()
        if direction_signal == 1:
            order = self.buy(data=self.data, size=lot)
            self.open_orders[order.ref] = {'kind': 'entry', 'tranche': {'id': self.sequence, 'direction': 'buy', 'size': lot, 'take_profit': self._round(price + tp_dist) if tp_dist > 0 else None}}
            self._semantic_write('submit', action='entry_buy', order_ref=order.ref, tranche_id=self.sequence, size=lot, price=price, take_profit=self._round(price + tp_dist) if tp_dist > 0 else None)
        else:
            order = self.sell(data=self.data, size=lot)
            self.open_orders[order.ref] = {'kind': 'entry', 'tranche': {'id': self.sequence, 'direction': 'sell', 'size': lot, 'take_profit': self._round(price - tp_dist) if tp_dist > 0 else None}}
            self._semantic_write('submit', action='entry_sell', order_ref=order.ref, tranche_id=self.sequence, size=lot, price=price, take_profit=self._round(price - tp_dist) if tp_dist > 0 else None)
        self.sequence += 1
        self.signal_count += 1

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            self._semantic_write('order', action=order.getstatusname(), order_ref=order.ref, size=float(order.created.size), price=float(order.created.price or 0.0))
            return
        meta = self.open_orders.pop(order.ref, None)
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if meta and meta.get('kind') == 'entry':
                tranche = meta['tranche']
                tranche['size'] = abs(float(order.executed.size))
                tranche['entry_price'] = float(order.executed.price)
                self.active_tranches.append(tranche)
                if tranche['direction'] == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
            elif meta and meta.get('kind') == 'exit':
                exit_ids = set(meta.get('ids', []))
                self.active_tranches = [t for t in self.active_tranches if t['id'] not in exit_ids]
            elif meta and meta.get('kind') == 'exit_all':
                self.active_tranches = []
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
        self._semantic_write(
            'order',
            action=order.getstatusname(),
            order_ref=order.ref,
            meta_kind=None if meta is None else meta.get('kind'),
            executed_size=float(order.executed.size),
            executed_price=float(order.executed.price),
            executed_value=float(order.executed.value),
            executed_comm=float(order.executed.comm),
        )

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        self.closed_trade_pnls.append(float(trade.pnlcomm))
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._semantic_write('trade', action='closed', pnl=float(trade.pnl), pnlcomm=float(trade.pnlcomm), trade_count=self.trade_count)
