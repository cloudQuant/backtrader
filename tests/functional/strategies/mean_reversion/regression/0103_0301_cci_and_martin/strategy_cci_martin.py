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


class SafeCCI(bt.Indicator):
    lines = ('cci',)
    params = (
        ('period', 27),
        ('factor', 0.015),
    )

    def __init__(self):
        self.addminperiod(self.p.period)

    def next(self):
        period = self.p.period
        typical_prices = [
            (float(self.data.high[-i]) + float(self.data.low[-i]) + float(self.data.close[-i])) / 3.0
            for i in range(period)
        ]
        sma = sum(typical_prices) / period
        mean_dev = sum(abs(tp - sma) for tp in typical_prices) / period
        current_tp = typical_prices[0]
        denominator = self.p.factor * mean_dev
        self.lines.cci[0] = 0.0 if denominator == 0.0 else (current_tp - sma) / denominator


class CCIMartinStrategy(bt.Strategy):
    """
    0301 CCI and Martin EA — CCI indicator + candlestick pattern + optional martingale.

    BUY signal:
    - CCI[1] < 5, CCI[2] < CCI[3], CCI[1] < CCI[2], CCI[0] > CCI[1]
    - Bar#2 bearish, Bar#1 bearish, Bar#0 bullish
    - Bar#1 open < Bar#0 close

    SELL signal:
    - CCI[1] > -5, CCI[2] > CCI[3], CCI[1] > CCI[2], CCI[0] < CCI[1]
    - Bar#2 bullish, Bar#1 bullish, Bar#0 bearish
    - Bar#1 open > Bar#0 close

    Martingale: after a losing trade, multiply lot by coefficient (up to max multiplications).
    """
    params = dict(
        fixed_lot=0.1,
        point_size=0.01,
        stoploss_pips=20,
        takeprofit_pips=50,
        trailing_stop_pips=5,
        trailing_step_pips=15,
        cci_period=27,
        use_martin=True,
        martin_coeff=3.0,
        martin_ordinal_number=1,
        martin_max_multiplications=3,
    )

    def __init__(self):
        self.data0 = self.datas[0]
        self.cci = SafeCCI(self.data0, period=self.p.cci_period)
        self.entry_order = None
        self.close_order = None
        self.pending_side = None
        self.active_side = None
        self.entry_price = None
        self.stop_price = None
        self.limit_price = None
        # Martingale state
        self.current_lot = self.p.fixed_lot
        self.martin_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data0.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _reset_exit_levels(self):
        self.stop_price = None
        self.limit_price = None

    def _initialize_exit_levels(self):
        if not self.position or self.entry_price is None:
            return
        ps = self.p.point_size
        if self.position.size > 0:
            self.stop_price = self.entry_price - self.p.stoploss_pips * ps if self.p.stoploss_pips > 0 else None
            self.limit_price = self.entry_price + self.p.takeprofit_pips * ps if self.p.takeprofit_pips > 0 else None
        else:
            self.stop_price = self.entry_price + self.p.stoploss_pips * ps if self.p.stoploss_pips > 0 else None
            self.limit_price = self.entry_price - self.p.takeprofit_pips * ps if self.p.takeprofit_pips > 0 else None

    def _update_trailing_stop(self):
        if not self.position or self.entry_price is None:
            return
        if self.p.trailing_stop_pips == 0:
            return
        ps = self.p.point_size
        ts = self.p.trailing_stop_pips * ps
        step = self.p.trailing_step_pips * ps
        current = float(self.data0.close[0])
        if self.position.size > 0:
            if current - self.entry_price > ts + step:
                new_sl = current - ts
                if self.stop_price is None or new_sl > self.stop_price:
                    self.stop_price = new_sl
        else:
            if self.entry_price - current > ts + step:
                new_sl = current + ts
                if self.stop_price is None or new_sl < self.stop_price:
                    self.stop_price = new_sl

    def _submit_entry(self, side, reason):
        if self.entry_order is not None or self.close_order is not None:
            self.pending_side = side
            return
        if self.position.size > 0 and side == 'long':
            return
        if self.position.size < 0 and side == 'short':
            return
        if self.position:
            self.pending_side = side
            self._submit_close(f'reverse to {side}: {reason}')
            return
        size = max(0.01, float(self.current_lot))
        self.pending_side = None
        if side == 'long':
            self.entry_order = self.buy(size=size)
            self.log(f'OPEN LONG size={size} reason={reason}')
        else:
            self.entry_order = self.sell(size=size)
            self.log(f'OPEN SHORT size={size} reason={reason}')

    def _submit_close(self, reason):
        if not self.position or self.close_order is not None:
            return
        self.close_order = self.close()
        self.log(f'CLOSE side={self.active_side} reason={reason}')

    def _check_exit_thresholds(self):
        if not self.position or self.entry_price is None or self.close_order is not None:
            return False
        bar_high = float(self.data0.high[0])
        bar_low = float(self.data0.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and bar_low <= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_high >= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        else:
            if self.stop_price is not None and bar_high >= self.stop_price:
                self._submit_close(f'stop loss hit @{self.stop_price:.5f}')
                return True
            if self.limit_price is not None and bar_low <= self.limit_price:
                self._submit_close(f'take profit hit @{self.limit_price:.5f}')
                return True
        return False

    def _update_martin(self, pnl):
        if not self.p.use_martin:
            self.current_lot = self.p.fixed_lot
            return
        if pnl < 0:
            self.loss_count += 1
            if self.martin_count < self.p.martin_max_multiplications:
                if self.loss_count >= self.p.martin_ordinal_number:
                    new_lot = self.current_lot * self.p.martin_coeff
                    new_lot = round(new_lot, 2)
                    if new_lot > 0:
                        self.current_lot = new_lot
                    else:
                        self.current_lot = self.p.fixed_lot
                    self.martin_count += 1
                    return
        else:
            self.current_lot = self.p.fixed_lot
            self.martin_count = 0
            self.loss_count = 0

    def next(self):
        if len(self.data0) < self.p.cci_period + 5:
            return
        self._update_trailing_stop()
        if self._check_exit_thresholds():
            return
        if self.entry_order is not None or self.close_order is not None:
            return
        if self.position:
            return

        cci0 = float(self.cci[0])
        cci1 = float(self.cci[-1])
        cci2 = float(self.cci[-2])
        cci3 = float(self.cci[-3])

        o0 = float(self.data0.open[0])
        c0 = float(self.data0.close[0])
        o1 = float(self.data0.open[-1])
        c1 = float(self.data0.close[-1])
        o2 = float(self.data0.open[-2])
        c2 = float(self.data0.close[-2])

        # BUY signal
        if (cci1 < 5.0 and cci2 < cci3 and cci1 < cci2 and cci0 > cci1 and
                o2 > c2 and o1 > c1 and o0 < c0 and o1 < c0):
            self._submit_entry('long', 'CCI reversal up + bearish-to-bullish candle pattern')
            return

        # SELL signal
        if (cci1 > -5.0 and cci2 > cci3 and cci1 > cci2 and cci0 < cci1 and
                o2 < c2 and o1 < c1 and o0 > c0 and o1 > c0):
            self._submit_entry('short', 'CCI reversal down + bullish-to-bearish candle pattern')
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order == self.entry_order:
                self.active_side = 'long' if order.executed.size > 0 else 'short'
                self.entry_price = order.executed.price
                self.log(f'ENTRY FILLED side={self.active_side} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self._initialize_exit_levels()
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                self.active_side = None
                self.entry_price = None
                self._reset_exit_levels()
                if self.pending_side is not None:
                    next_side = self.pending_side
                    self.pending_side = None
                    self._submit_entry(next_side, 'post-close reversal')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.entry_order = None
            elif order == self.close_order:
                self.close_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.log(f'TRADE CLOSED side={self.active_side or ("long" if trade.long else "short")} pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
        self._update_martin(trade.pnlcomm)
        if not self.position:
            self.active_side = None
            self.entry_price = None
            self._reset_exit_levels()
