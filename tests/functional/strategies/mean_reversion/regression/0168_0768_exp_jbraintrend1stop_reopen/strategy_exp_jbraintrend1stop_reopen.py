from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume', 'real_volume', 'openinterest']]
    df = df.set_index('datetime')
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def resample_frame(df, rule):
    out = df.resample(rule, label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'tick_volume': 'sum',
        'real_volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


def smooth_series(series, period, method='MODE_SMA'):
    period = max(int(period), 1)
    if method == 'MODE_EMA':
        return series.ewm(span=period, adjust=False).mean()
    if method == 'MODE_SMMA':
        return series.ewm(alpha=1.0 / period, adjust=False).mean()
    if method == 'MODE_LWMA':
        weights = np.arange(1, period + 1, dtype=float)
        return series.rolling(period, min_periods=period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    return series.rolling(period, min_periods=period).mean()


def compute_jbraintrend1stop(frame, atr_period=7, sto_period=9, ma_method='MODE_SMA', stop_dperiod=3, length_=7, point=0.01):
    out = frame.copy()
    d = 2.3
    s = 1.5
    x1 = 53.0
    x2 = 47.0
    ma = ma_method or 'MODE_SMA'
    tr_components = pd.concat([
        out['high'] - out['low'],
        (out['high'] - out['close'].shift(1)).abs(),
        (out['low'] - out['close'].shift(1)).abs(),
    ], axis=1)
    true_range = tr_components.max(axis=1)
    atr = true_range.rolling(atr_period, min_periods=atr_period).mean()
    atr1 = true_range.rolling(atr_period + stop_dperiod, min_periods=atr_period + stop_dperiod).mean()
    highest = out['high'].rolling(sto_period, min_periods=sto_period).max()
    lowest = out['low'].rolling(sto_period, min_periods=sto_period).min()
    denom = highest - lowest
    stochastic = pd.Series(np.where(denom == 0, 50.0, 100.0 * (out['close'] - lowest) / denom), index=out.index)
    jh = smooth_series(out['high'], length_, ma)
    jl = smooth_series(out['low'], length_, ma)
    jc = smooth_series(out['close'], length_, ma)
    buy_stop = pd.Series(0.0, index=out.index)
    sell_stop = pd.Series(0.0, index=out.index)
    buy_stop_line = pd.Series(0.0, index=out.index)
    sell_stop_line = pd.Series(0.0, index=out.index)
    p_state = 0
    r_state = 0.0
    start = max(atr_period + stop_dperiod, sto_period, length_, 30) + 2
    for i in range(start, len(out)):
        range_value = atr.iloc[i] / d if pd.notna(atr.iloc[i]) else np.nan
        range1 = atr1.iloc[i] * s if pd.notna(atr1.iloc[i]) else np.nan
        if pd.isna(range_value) or pd.isna(range1) or pd.isna(stochastic.iloc[i]) or pd.isna(jh.iloc[i]) or pd.isna(jl.iloc[i]) or pd.isna(jc.iloc[i]) or pd.isna(jc.iloc[i - 2]):
            continue
        val1 = 0.0
        val2 = 0.0
        val3 = abs(round(float(jc.iloc[i]), 8) - round(float(jc.iloc[i - 2]), 8))
        if val3 > range_value:
            if stochastic.iloc[i] < x2 and p_state != 1:
                value3 = float(jh.iloc[i]) + range1 / 4.0
                val1 = value3
                p_state = 1
                r_state = val1
                sell_stop.iloc[i] = val1
                sell_stop_line.iloc[i] = val1
            if stochastic.iloc[i] > x1 and p_state != 2:
                value3 = float(jl.iloc[i]) - range1 / 4.0
                val2 = value3
                p_state = 2
                r_state = val2
                buy_stop.iloc[i] = val2
                buy_stop_line.iloc[i] = val2
        value4 = float(jh.iloc[i]) + range1
        value5 = float(jl.iloc[i]) - range1
        if val1 == 0.0 and val2 == 0.0:
            if p_state == 1:
                if value4 < r_state:
                    r_state = value4
                sell_stop.iloc[i] = r_state
                sell_stop_line.iloc[i] = r_state
            if p_state == 2:
                if value5 > r_state:
                    r_state = value5
                buy_stop.iloc[i] = r_state
                buy_stop_line.iloc[i] = r_state
    out['sell_stop'] = sell_stop
    out['buy_stop'] = buy_stop
    out['sell_stop_line'] = sell_stop_line
    out['buy_stop_line'] = buy_stop_line
    out = out[(out['sell_stop'] != 0.0) | (out['buy_stop'] != 0.0) | (out['sell_stop_line'] != 0.0) | (out['buy_stop_line'] != 0.0)]
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class JBrainTrend1StopFeed(bt.feeds.PandasData):
    lines = ('sell_stop', 'buy_stop', 'sell_stop_line', 'buy_stop_line')
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
        ('sell_stop', 6), ('buy_stop', 7), ('sell_stop_line', 8), ('buy_stop_line', 9),
    )


class ExpJBrainTrend1StopReopenStrategy(bt.Strategy):
    params = dict(
        signal_bar=1,
        size=0.1,
        stop_loss=1000,
        take_profit=2000,
        price_step=300,
        pos_total=10,
        buy_pos_open=True,
        sell_pos_open=True,
        buy_pos_close=True,
        sell_pos_close=True,
        atr_period=7,
        sto_period=9,
        ma_method='MODE_SMA',
        stop_dperiod=3,
        length_=7,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.signal = self.datas[1]
        self.buy_stop = self.signal.buy_stop
        self.sell_stop = self.signal.sell_stop

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0

        self.layers = []
        self.pending_order = None
        self.pending_action = None
        self.last_signal_dt = None

    def log(self, text):
        dt = bt.num2date(self.base.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _trade_unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _pyramid_threshold(self):
        return float(self.p.price_step) * self._trade_unit()

    def _layer_stop(self, side, entry_price):
        if float(self.p.stop_loss) <= 0:
            return None
        dist = float(self.p.stop_loss) * self._trade_unit()
        if side == 'buy':
            return round(entry_price - dist, int(self.p.price_digits))
        return round(entry_price + dist, int(self.p.price_digits))

    def _layer_take_profit(self, side, entry_price):
        if float(self.p.take_profit) <= 0:
            return None
        dist = float(self.p.take_profit) * self._trade_unit()
        if side == 'buy':
            return round(entry_price + dist, int(self.p.price_digits))
        return round(entry_price - dist, int(self.p.price_digits))

    def _position_side(self):
        if self.layers:
            return self.layers[-1]['side']
        if not self.position:
            return None
        return 'buy' if self.position.size > 0 else 'sell'

    def _submit_open(self, side, trigger):
        if self.pending_order is not None:
            return False
        size = float(self.p.size)
        if size <= 0:
            return False
        self.pending_action = {'type': 'open', 'side': side, 'trigger': trigger}
        self.pending_order = self.buy(size=size) if side == 'buy' else self.sell(size=size)
        self.log(f'submit {side} size={size:.2f} trigger={trigger}')
        return True

    def _submit_close(self, layer_indexes, reason, reopen_side=None):
        if self.pending_order is not None or not layer_indexes:
            return False
        close_size = sum(self.layers[idx]['size'] for idx in layer_indexes)
        if close_size <= 0:
            return False
        self.pending_action = {
            'type': 'close_layers',
            'indexes': sorted(layer_indexes),
            'reason': reason,
            'reopen_side': reopen_side,
        }
        if self._position_side() == 'buy':
            self.pending_order = self.sell(size=close_size)
        else:
            self.pending_order = self.buy(size=close_size)
        self.log(f'submit close size={close_size:.2f} reason={reason} layers={layer_indexes}')
        return True

    def _check_layer_risk(self):
        if not self.layers or self.pending_order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        to_close = []
        reason = None
        for idx, layer in enumerate(self.layers):
            if layer['side'] == 'buy':
                stop_hit = layer['stop_price'] is not None and low <= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and high >= layer['take_profit_price']
            else:
                stop_hit = layer['stop_price'] is not None and high >= layer['stop_price']
                take_hit = layer['take_profit_price'] is not None and low <= layer['take_profit_price']
            if stop_hit or take_hit:
                to_close.append(idx)
                if reason is None:
                    reason = 'take_profit' if take_hit and not stop_hit else 'stop_loss'
        if to_close:
            return self._submit_close(to_close, reason or 'risk_exit')
        return False

    def _enough_history(self):
        idx = max(int(self.p.signal_bar), 1)
        try:
            _ = float(self.buy_stop[-idx])
            _ = float(self.buy_stop[-(idx + 1)])
            _ = float(self.sell_stop[-idx])
            _ = float(self.sell_stop[-(idx + 1)])
            return True
        except (TypeError, ValueError, IndexError):
            return False

    def _evaluate_signals(self):
        idx = max(int(self.p.signal_bar), 1)
        up_curr = float(self.buy_stop[-idx])
        up_prev = float(self.buy_stop[-(idx + 1)])
        dn_curr = float(self.sell_stop[-idx])
        dn_prev = float(self.sell_stop[-(idx + 1)])
        buy_open = sell_open = buy_close = sell_close = False
        if up_curr != 0.0:
            if self.p.buy_pos_open and dn_prev != 0.0:
                buy_open = True
            if self.p.sell_pos_close:
                sell_close = True
        if dn_curr != 0.0:
            if self.p.sell_pos_open and up_prev != 0.0:
                sell_open = True
            if self.p.buy_pos_close:
                buy_close = True
        return buy_open, buy_close, sell_open, sell_close, up_curr, up_prev, dn_curr, dn_prev

    def _check_indicator_signal(self):
        if not self._enough_history():
            return False
        signal_idx = max(int(self.p.signal_bar), 1)
        signal_dt = bt.num2date(self.signal.datetime[-signal_idx])
        if self.last_signal_dt == signal_dt:
            return False
        self.last_signal_dt = signal_dt
        buy_open, buy_close, sell_open, sell_close, up_curr, up_prev, dn_curr, dn_prev = self._evaluate_signals()
        side = self._position_side()
        if buy_open or sell_open:
            self.signal_count += 1
        self.log(
            f'jbrain signal up_curr={up_curr:.5f} up_prev={up_prev:.5f} '
            f'dn_curr={dn_curr:.5f} dn_prev={dn_prev:.5f} buy_open={buy_open} sell_open={sell_open}'
        )
        if buy_open:
            if side == 'sell' and sell_close:
                reopen_side = 'buy' if self.p.buy_pos_open else None
                return self._submit_close(list(range(len(self.layers))), 'reverse_to_buy', reopen_side=reopen_side)
            if not self.layers and self.p.buy_pos_open:
                return self._submit_open('buy', 'signal')
            return False
        if sell_open:
            if side == 'buy' and buy_close:
                reopen_side = 'sell' if self.p.sell_pos_open else None
                return self._submit_close(list(range(len(self.layers))), 'reverse_to_sell', reopen_side=reopen_side)
            if not self.layers and self.p.sell_pos_open:
                return self._submit_open('sell', 'signal')
        return False

    def _check_pyramid(self):
        if not self.layers or self.pending_order is not None:
            return False
        addon_count = max(0, len(self.layers) - 1)
        if addon_count >= int(self.p.pos_total):
            return False
        last_layer = self.layers[-1]
        price = float(self.base.close[0])
        threshold = self._pyramid_threshold()
        if last_layer['side'] == 'buy' and price - last_layer['entry_price'] > threshold:
            return self._submit_open('buy', 'pyramid')
        if last_layer['side'] == 'sell' and last_layer['entry_price'] - price > threshold:
            return self._submit_open('sell', 'pyramid')
        return False

    def next(self):
        self.bar_num += 1
        if self.pending_order is not None:
            return
        if self._check_layer_risk():
            return
        if self._check_indicator_signal():
            return
        self._check_pyramid()

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        action = self.pending_action if self.pending_order is not None and order.ref == self.pending_order.ref else None
        reopen_side = None
        if order.status == bt.Order.Completed and action is not None:
            self.completed_order_count += 1
            if action['type'] == 'open':
                side = action['side']
                entry_price = float(order.executed.price)
                layer = {
                    'side': side,
                    'size': abs(float(order.executed.size)),
                    'entry_price': entry_price,
                    'stop_price': self._layer_stop(side, entry_price),
                    'take_profit_price': self._layer_take_profit(side, entry_price),
                }
                self.layers.append(layer)
                if side == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
                self.log(
                    f'{side} filled price={entry_price:.2f} size={layer["size"]:.2f} '
                    f'sl={layer["stop_price"]} tp={layer["take_profit_price"]} trigger={action["trigger"]}'
                )
            elif action['type'] == 'close_layers':
                remaining = []
                closed_pnl = 0.0
                reopen_side = action.get('reopen_side')
                exit_price = float(order.executed.price)
                for idx, layer in enumerate(self.layers):
                    if idx in action['indexes']:
                        if layer['side'] == 'buy':
                            closed_pnl += (exit_price - layer['entry_price']) * layer['size']
                        else:
                            closed_pnl += (layer['entry_price'] - exit_price) * layer['size']
                    else:
                        remaining.append(layer)
                self.layers = remaining
                self.log(
                    f'partial/complete close filled price={exit_price:.2f} '
                    f'reason={action["reason"]} remaining_layers={len(self.layers)} pnl={closed_pnl:.2f}'
                )
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1
            self.log(f'order failed status={order.getstatusname()}')

        if self.pending_order is not None and order.ref == self.pending_order.ref and order.status not in [bt.Order.Submitted, bt.Order.Accepted]:
            self.pending_order = None
            self.pending_action = None
            if reopen_side is not None and not self.layers:
                self._submit_open(reopen_side, 'signal_reopen')

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
