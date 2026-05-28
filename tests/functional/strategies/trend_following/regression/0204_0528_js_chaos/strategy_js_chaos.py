from __future__ import absolute_import, division, print_function, unicode_literals

import io

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


class JSChaosStrategy(bt.Strategy):
    params = dict(
        use_time=True,
        open_hour=7,
        close_hour=18,
        lots=0.1,
        indenting=0,
        fibo_1=1.618,
        fibo_2=4.618,
        use_close_positions=True,
        use_trailing=True,
        use_breakeven=True,
        breakeven_plus=1,
        fractal_lookback=10,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        median = (self.data.high + self.data.low) / 2.0
        self.jaw = bt.ind.SmoothedMovingAverage(median, period=13)
        self.teeth = bt.ind.SmoothedMovingAverage(median, period=8)
        self.lips = bt.ind.SmoothedMovingAverage(median, period=5)
        self.ma_21 = bt.ind.SmoothedMovingAverage(self.data.close, period=21)
        self.ao = bt.ind.SimpleMovingAverage(median, period=5) - bt.ind.SimpleMovingAverage(median, period=34)
        self.ac = self.ao - bt.ind.SimpleMovingAverage(self.ao, period=5)
        self.stddev = bt.ind.StandardDeviation(self.data.close, period=10)
        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.completed_order_count = 0
        self.rejected_order_count = 0
        self.pending_orders = []
        self.active_tranches = []
        self.open_orders = {}
        self.sequence = 0

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _is_trade_time(self):
        if not bool(self.p.use_time):
            return True
        dt = bt.num2date(self.data.datetime[0])
        hour = dt.hour
        start = int(self.p.open_hour)
        end = int(self.p.close_hour)
        if start > end:
            return hour <= end or hour >= start
        if start < end:
            return start <= hour <= end
        return hour == start

    def _signal(self):
        if len(self) < 40:
            return 0
        ao_0 = float(self.ao[0])
        ao_1 = float(self.ao[-1])
        lips = float(self.lips[0])
        teeth = float(self.teeth[0])
        jaw = float(self.jaw[0])
        if ao_0 > ao_1 and ao_1 > 0.0 and lips > teeth and teeth > jaw:
            return 1
        if ao_0 < ao_1 and ao_1 < 0.0 and lips < teeth and teeth < jaw:
            return 2
        return 0

    def _fractal_up(self, bars):
        if len(self) < bars + 5:
            return 0.0
        for shift in range(2, bars + 2):
            center = float(self.data.high[-shift])
            if center > float(self.data.high[-shift - 1]) and center > float(self.data.high[-shift - 2]) and center > float(self.data.high[-shift + 1]) and center > float(self.data.high[-shift + 2]):
                return self._round(center + float(self.p.indenting) * self._point())
        return 0.0

    def _fractal_down(self, bars):
        if len(self) < bars + 5:
            return 0.0
        for shift in range(2, bars + 2):
            center = float(self.data.low[-shift])
            if center < float(self.data.low[-shift - 1]) and center < float(self.data.low[-shift - 2]) and center < float(self.data.low[-shift + 1]) and center < float(self.data.low[-shift + 2]):
                return self._round(center - float(self.p.indenting) * self._point())
        return 0.0

    def _pending_exists(self, tag):
        return any(p['tag'] == tag for p in self.pending_orders)

    def _pending_count(self, direction):
        return sum(1 for p in self.pending_orders if p['direction'] == direction)

    def _active_tags(self):
        return {t['tag'] for t in self.active_tranches}

    def _active_direction_count(self, direction):
        return sum(1 for t in self.active_tranches if t['direction'] == direction)

    def _delete_pending(self, direction):
        self.pending_orders = [p for p in self.pending_orders if p['direction'] != direction]

    def _queue_pending(self, direction, entry, sl, tp, size, tag):
        self.pending_orders.append({
            'direction': direction,
            'entry': self._round(entry),
            'sl': self._round(sl),
            'tp': self._round(tp),
            'size': float(size),
            'tag': tag,
        })
        self.signal_count += 1

    def _place_pending_orders(self, signal, fractal_up, fractal_down):
        if not self._is_trade_time():
            return
        lips = float(self.lips[0])
        price = float(self.data.close[0])
        pt = self._point()
        if signal == 1:
            self._delete_pending('sell')
            if self._active_direction_count('buy') == 0 and fractal_up and fractal_up > lips:
                if self._pending_count('buy') == 0:
                    tp = lips + (fractal_up - lips) * float(self.p.fibo_1)
                    if tp > 0 and tp - fractal_up > pt and fractal_up - lips > pt and price + pt < fractal_up:
                        self._queue_pending('buy', fractal_up, lips, tp, float(self.p.lots) * 2.0, 'buy_1')
                elif self._pending_count('buy') == 1 and self._pending_exists('buy_1') and not self._pending_exists('buy_2'):
                    tp = lips + (fractal_up - lips) * float(self.p.fibo_2)
                    if tp > 0 and tp - fractal_up > pt and fractal_up - lips > pt and price + pt < fractal_up:
                        self._queue_pending('buy', fractal_up, lips, tp, float(self.p.lots), 'buy_2')
        elif signal == 2:
            self._delete_pending('buy')
            if self._active_direction_count('sell') == 0 and fractal_down and fractal_down < lips:
                if self._pending_count('sell') == 0:
                    tp = lips - (lips - fractal_down) * float(self.p.fibo_1)
                    if tp > 0 and fractal_down - tp > pt and lips - fractal_down > pt and price - pt > fractal_down:
                        self._queue_pending('sell', fractal_down, lips, tp, float(self.p.lots) * 2.0, 'sell_1')
                elif self._pending_count('sell') == 1 and self._pending_exists('sell_1') and not self._pending_exists('sell_2'):
                    tp = lips - (lips - fractal_down) * float(self.p.fibo_2)
                    if tp > 0 and fractal_down - tp > pt and lips - fractal_down > pt and price - pt > fractal_down:
                        self._queue_pending('sell', fractal_down, lips, tp, float(self.p.lots), 'sell_2')

    def _trigger_pending_orders(self):
        if self.open_orders:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        triggered = []
        for pending in list(self.pending_orders):
            if pending['direction'] == 'buy' and high >= float(pending['entry']):
                order = self.buy(size=float(pending['size']))
                self.open_orders[order.ref] = {'kind': 'entry', 'pending': pending}
                triggered.append(pending)
            elif pending['direction'] == 'sell' and low <= float(pending['entry']):
                order = self.sell(size=float(pending['size']))
                self.open_orders[order.ref] = {'kind': 'entry', 'pending': pending}
                triggered.append(pending)
        if triggered:
            self.pending_orders = [p for p in self.pending_orders if p not in triggered]

    def _submit_close_for_tags(self, tags):
        if self.open_orders or not tags:
            return
        tranches = [t for t in self.active_tranches if t['tag'] in tags]
        if not tranches:
            return
        total_size = sum(float(t['size']) for t in tranches)
        order = self.close(size=total_size)
        self.open_orders[order.ref] = {'kind': 'exit', 'tags': list(tags)}

    def _manage_tp_sl(self):
        if not self.active_tranches or self.open_orders:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        hit_tags = []
        for tranche in self.active_tranches:
            if tranche['direction'] == 'buy':
                if tranche['take_profit'] is not None and high >= float(tranche['take_profit']):
                    hit_tags.append(tranche['tag'])
                elif tranche['stop_loss'] is not None and low <= float(tranche['stop_loss']):
                    hit_tags.append(tranche['tag'])
            else:
                if tranche['take_profit'] is not None and low <= float(tranche['take_profit']):
                    hit_tags.append(tranche['tag'])
                elif tranche['stop_loss'] is not None and high >= float(tranche['stop_loss']):
                    hit_tags.append(tranche['tag'])
        self._submit_close_for_tags(hit_tags)

    def _manage_breakeven(self):
        if not bool(self.p.use_breakeven):
            return
        tags = self._active_tags()
        plus = float(self.p.breakeven_plus) * self._point()
        bid = float(self.data.close[0])
        ask = float(self.data.close[0])
        for tranche in self.active_tranches:
            if tranche['tag'] == 'buy_2' and 'buy_1' not in tags:
                if float(tranche['stop_loss']) < float(tranche['entry_price']) and float(tranche['entry_price']) + plus <= bid:
                    tranche['stop_loss'] = self._round(float(tranche['entry_price']) + plus)
            elif tranche['tag'] == 'sell_2' and 'sell_1' not in tags:
                if float(tranche['stop_loss']) > float(tranche['entry_price']) and float(tranche['entry_price']) - plus >= ask:
                    tranche['stop_loss'] = self._round(float(tranche['entry_price']) - plus)

    def _manage_trailing(self):
        if not bool(self.p.use_trailing) or len(self) < 3:
            return
        ma_21 = float(self.ma_21[0])
        ao_0 = float(self.ao[0])
        ao_1 = float(self.ao[-1])
        ac_0 = float(self.ac[0])
        ac_1 = float(self.ac[-1])
        std_0 = float(self.stddev[0])
        std_1 = float(self.stddev[-1])
        bid = float(self.data.close[0])
        ask = float(self.data.close[0])
        pt = self._point()
        for tranche in self.active_tranches:
            if tranche['direction'] == 'buy':
                if tranche['stop_loss'] is None or ((not self._compare(tranche['stop_loss'], ma_21)) and float(tranche['stop_loss']) < ma_21 and std_0 > std_1 and ao_0 > ao_1 and ac_0 > ac_1):
                    if ma_21 + pt <= bid:
                        tranche['stop_loss'] = self._round(ma_21)
            else:
                if tranche['stop_loss'] is None or ((not self._compare(tranche['stop_loss'], ma_21)) and float(tranche['stop_loss']) > ma_21 and std_0 > std_1 and ao_0 < ao_1 and ac_0 < ac_1):
                    if ma_21 - pt >= ask:
                        tranche['stop_loss'] = self._round(ma_21)

    def _manage_signal_close(self):
        if not bool(self.p.use_close_positions) or self.open_orders or len(self) < 2:
            return
        prev_open = float(self.data.open[-1])
        lips = float(self.lips[0])
        if lips > prev_open:
            self._submit_close_for_tags([t['tag'] for t in self.active_tranches if t['direction'] == 'buy'])
        elif lips < prev_open:
            self._submit_close_for_tags([t['tag'] for t in self.active_tranches if t['direction'] == 'sell'])

    def _compare(self, value1, value2, eps=1e-7):
        return abs(float(value1) - float(value2)) <= eps

    def next(self):
        self.bar_num += 1
        if len(self) < 60:
            return
        self._trigger_pending_orders()
        self._manage_breakeven()
        self._manage_trailing()
        self._manage_tp_sl()
        self._manage_signal_close()
        if self.open_orders:
            return
        signal = self._signal()
        fractal_up = self._fractal_up(int(self.p.fractal_lookback))
        fractal_down = self._fractal_down(int(self.p.fractal_lookback))
        self._place_pending_orders(signal, fractal_up, fractal_down)

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        meta = self.open_orders.pop(order.ref, None)
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if meta and meta.get('kind') == 'entry':
                pending = meta['pending']
                tranche = {
                    'id': self.sequence,
                    'tag': pending['tag'],
                    'direction': pending['direction'],
                    'size': abs(float(order.executed.size)),
                    'entry_price': float(order.executed.price),
                    'stop_loss': pending['sl'],
                    'take_profit': pending['tp'],
                }
                self.sequence += 1
                self.active_tranches.append(tranche)
                if pending['direction'] == 'buy':
                    self.buy_count += 1
                else:
                    self.sell_count += 1
            elif meta and meta.get('kind') == 'exit':
                exit_tags = set(meta.get('tags', []))
                self.active_tranches = [t for t in self.active_tranches if t['tag'] not in exit_tags]
        elif order.status in [bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected, bt.Order.Expired]:
            self.rejected_order_count += 1

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
