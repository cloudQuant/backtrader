from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


class OhlcStochasticStrategy(bt.Strategy):
    params = dict(
        trailing_stop_pips=5.0,
        trailing_step_pips=2.0,
        sto_level_up=70.0,
        sto_level_down=30.0,
        sto_k_period=5,
        sto_d_period=3,
        sto_slowing=3,
        lots=0.0,
        risk_percent=15.0,
        pip_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
        allow_long=True,
        allow_short=True,
    )

    def __init__(self):
        self.exec_data = self.datas[0]
        self.signal_data = self.datas[1] if len(self.datas) > 1 else self.datas[0]
        self.stochastic = bt.indicators.StochasticFull(
            self.signal_data,
            period=self.p.sto_k_period,
            period_dfast=self.p.sto_d_period,
            period_dslow=self.p.sto_slowing,
            movav=bt.indicators.SimpleMovingAverage,
            safediv=True,
        )
        self.sto_main = self.stochastic.percK
        self.sto_signal = self.stochastic.percD

        self.entry_order = None
        self.close_order = None
        self.stop_order = None
        self.pending_reverse = None
        self.current_stop_price = None

        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def prenext(self):
        self.next()

    def log(self, text):
        dt = bt.num2date(self.exec_data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        lot = min(max(lot, self.p.lot_min), self.p.lot_max)
        lot = int(lot / self.p.lot_step) * self.p.lot_step
        return round(max(lot, self.p.lot_min), 4)

    def _position_size(self, price):
        if self.p.lots and self.p.lots > 0:
            return self._normalize_lot(self.p.lots)
        if self.p.risk_percent <= 0:
            return 0.0
        notional = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        unit_cost = max(price * self.p.contract_multiplier, self.p.pip_size)
        raw_size = notional / unit_cost
        return self._normalize_lot(raw_size)

    def _signal_ready(self):
        return len(self.signal_data) > max(self.p.sto_k_period, self.p.sto_d_period + self.p.sto_slowing)

    def _buy_signal(self):
        if not self._signal_ready():
            return False
        main = self.sto_main[0]
        signal = self.sto_signal[0]
        if not math.isfinite(main) or not math.isfinite(signal):
            return False
        return main > signal and (main < self.p.sto_level_down or signal < self.p.sto_level_down)

    def _sell_signal(self):
        if not self._signal_ready():
            return False
        main = self.sto_main[0]
        signal = self.sto_signal[0]
        if not math.isfinite(main) or not math.isfinite(signal):
            return False
        return main < signal and (main > self.p.sto_level_up or signal > self.p.sto_level_up)

    def _cancel_stop_order(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None

    def _replace_stop_order(self, stop_price):
        self._cancel_stop_order()
        size = abs(self.position.size)
        if size <= 0:
            return
        if self.position.size > 0:
            self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=stop_price)
        else:
            self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=stop_price)

    def _submit_entry(self, direction, reason):
        if self.entry_order is not None or self.close_order is not None or self.position:
            return
        price = self.exec_data.close[0]
        size = self._position_size(price)
        if size <= 0:
            self.log(f'SKIP {direction.upper()} size={size}')
            return
        if direction == 'long':
            self.entry_order = self.buy(size=size)
        else:
            self.entry_order = self.sell(size=size)
        self.log(f'OPEN {direction.upper()} size={size} reason={reason}')

    def _submit_close(self, reason, reverse=None):
        if not self.position or self.close_order is not None:
            return
        self.pending_reverse = reverse
        self.current_stop_price = None
        self._cancel_stop_order()
        self.close_order = self.close()
        self.log(f'CLOSE size={self.position.size} reason={reason} reverse={reverse}')

    def _update_trailing(self):
        if not self.position or self.entry_order is not None or self.close_order is not None:
            return
        trailing_stop = self.p.trailing_stop_pips * self.p.pip_size
        trailing_step = self.p.trailing_step_pips * self.p.pip_size
        trigger = trailing_stop + trailing_step
        close = self.exec_data.close[0]

        if self.position.size > 0:
            move = close - self.position.price
            if move <= trigger:
                return
            candidate = close - trailing_stop
            if self.current_stop_price is None or candidate - self.current_stop_price >= trailing_step:
                self.current_stop_price = candidate
                self._replace_stop_order(candidate)
                self.log(f'TRAIL LONG stop={candidate:.5f}')
            return

        move = self.position.price - close
        if move <= trigger:
            return
        candidate = close + trailing_stop
        if self.current_stop_price is None or self.current_stop_price - candidate >= trailing_step:
            self.current_stop_price = candidate
            self._replace_stop_order(candidate)
            self.log(f'TRAIL SHORT stop={candidate:.5f}')

    def next(self):
        self._update_trailing()

        if self.entry_order is not None or self.close_order is not None:
            return

        buy_signal = self._buy_signal()
        sell_signal = self._sell_signal()

        if self.position:
            if self.position.size > 0 and sell_signal:
                self._submit_close('sell signal', reverse='short' if self.p.allow_short else None)
            elif self.position.size < 0 and buy_signal:
                self._submit_close('buy signal', reverse='long' if self.p.allow_long else None)
            return

        if buy_signal and self.p.allow_long:
            self._submit_entry('long', 'buy signal')
        elif sell_signal and self.p.allow_short:
            self._submit_entry('short', 'sell signal')

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order == self.entry_order:
                self.log(f'ENTRY FILLED side={"BUY" if order.isbuy() else "SELL"} price={order.executed.price:.5f} size={order.executed.size}')
                self.entry_order = None
                self.current_stop_price = None
            elif order == self.close_order:
                self.log(f'CLOSE FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.close_order = None
                next_side = self.pending_reverse
                self.pending_reverse = None
                self.current_stop_price = None
                if next_side is not None and not self.position:
                    self._submit_entry(next_side, 'reverse after close')
            elif order == self.stop_order:
                self.log(f'STOP FILLED price={order.executed.price:.5f} size={order.executed.size}')
                self.stop_order = None
                self.current_stop_price = None
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if order == self.entry_order:
                self.log(f'ENTRY FAILED status={order.getstatusname()}')
                self.entry_order = None
            elif order == self.close_order:
                self.log(f'CLOSE FAILED status={order.getstatusname()}')
                self.close_order = None
                self.pending_reverse = None
            elif order == self.stop_order:
                self.stop_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm > 0:
            self.win_count += 1
        elif trade.pnlcomm < 0:
            self.loss_count += 1
        self.log(f'TRADE CLOSED pnl={trade.pnlcomm:.2f} net={self.broker.getvalue():.2f}')
