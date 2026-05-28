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


class ArrowsCurvesIndicator(bt.Indicator):
    lines = ('sell', 'buy', 'sell_stop', 'buy_stop', 'smax', 'smin', 'smax2', 'smin2')
    params = dict(ssp=20, channel=0, ch_stop=30, relay=10)

    def __init__(self):
        self.addminperiod(self.p.ssp + self.p.relay + 2)
        self._uptrend = False
        self._old = False
        self._uptrend2 = False
        self._old2 = False

    def next(self):
        if len(self.data) <= self.p.ssp + self.p.relay:
            for line in self.lines:
                line[0] = 0.0
            return

        high_window = [float(self.data.high[-shift]) for shift in range(self.p.relay, self.p.relay + self.p.ssp)]
        low_window = [float(self.data.low[-shift]) for shift in range(self.p.relay, self.p.relay + self.p.ssp)]
        close0 = float(self.data.close[0])
        high_val = max(high_window)
        low_val = min(low_window)
        smax = high_val - (low_val - high_val) * self.p.channel / 100.0
        smin = low_val + (high_val - low_val) * self.p.channel / 100.0
        smax2 = high_val - (high_val - low_val) * (self.p.channel + self.p.ch_stop) / 100.0
        smin2 = low_val + (high_val - low_val) * (self.p.channel + self.p.ch_stop) / 100.0

        sell_signal = 0.0
        buy_signal = 0.0
        sell_stop = 0.0
        buy_stop = 0.0

        uptrend = self._uptrend
        uptrend2 = self._uptrend2
        old = self._old
        old2 = self._old2

        if close0 < smin and close0 < smax and uptrend2 is True:
            uptrend = False
        if close0 > smax and close0 > smin and uptrend2 is False:
            uptrend = True
        if (close0 > smax2 or close0 > smin2) and uptrend is False:
            uptrend2 = False
        if (close0 < smin2 or close0 < smax2) and uptrend is True:
            uptrend2 = True

        if close0 < smin and close0 < smax and uptrend2 is False:
            sell_signal = low_val
            uptrend2 = True
        if close0 > smax and close0 > smin and uptrend2 is True:
            buy_signal = high_val
            uptrend2 = False

        if uptrend != old and uptrend is False:
            sell_signal = low_val
        if uptrend != old and uptrend is True:
            buy_signal = high_val

        if uptrend2 != old2 and uptrend2 is True:
            buy_stop = smax2
        if uptrend2 != old2 and uptrend2 is False:
            sell_stop = smin2

        self.lines.sell[0] = sell_signal
        self.lines.buy[0] = buy_signal
        self.lines.sell_stop[0] = sell_stop
        self.lines.buy_stop[0] = buy_stop
        self.lines.smax[0] = smax
        self.lines.smin[0] = smin
        self.lines.smax2[0] = smax2
        self.lines.smin2[0] = smin2

        self._old = uptrend
        self._old2 = uptrend2
        self._uptrend = uptrend
        self._uptrend2 = uptrend2


class ArrowsAndCurvesEAStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        stop_loss_pips=50,
        take_profit_pips=50,
        trailing_stop_pips=0,
        trailing_step_pips=5,
        risk=5.0,
        ssp=20,
        channel=0,
        ch_stop=30,
        relay=10,
        point=0.01,
        price_digits=2,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.signal = ArrowsCurvesIndicator(
            self.data,
            ssp=self.p.ssp,
            channel=self.p.channel,
            ch_stop=self.p.ch_stop,
            relay=self.p.relay,
        )
        self.order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._position_was_open = False
        self._last_position_size = 0.0

    def _pip_size(self):
        digits_adjust = 10 if self.p.price_digits in (1, 3, 5) else 1
        return self.p.point * digits_adjust

    def _entry_size(self, stop_price):
        if self.p.lots > 0:
            return self.p.lots
        risk_cash = self.broker.get_cash() * (self.p.risk / 100.0)
        reference_price = float(self.data.close[0])
        stop_distance = abs(reference_price - stop_price)
        if stop_distance <= 0:
            return 0.01
        size = risk_cash / (stop_distance * self.p.contract_multiplier)
        return max(round(size, 2), 0.01)

    def _set_initial_protection(self):
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0
            return
        if self._entry_price is not None and self._last_position_size == self.position.size:
            return
        self._entry_price = float(self.position.price)
        self._last_position_size = float(self.position.size)
        pip_size = self._pip_size()
        stop_distance = self.p.stop_loss_pips * pip_size
        take_distance = self.p.take_profit_pips * pip_size
        if self.position.size > 0:
            self._stop_price = self._entry_price - stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price + take_distance if self.p.take_profit_pips > 0 else None
        else:
            self._stop_price = self._entry_price + stop_distance if self.p.stop_loss_pips > 0 else None
            self._take_profit_price = self._entry_price - take_distance if self.p.take_profit_pips > 0 else None

    def _apply_trailing(self):
        if not self.position or self.p.trailing_stop_pips <= 0:
            return
        trail = self.p.trailing_stop_pips * self._pip_size()
        step = self.p.trailing_step_pips * self._pip_size()
        close_price = float(self.data.close[0])
        if self.position.size > 0:
            if close_price - self._entry_price > trail + step:
                candidate = close_price - trail
                if self._stop_price is None or candidate - self._stop_price > step:
                    self._stop_price = candidate
        else:
            if self._entry_price - close_price > trail + step:
                candidate = close_price + trail
                if self._stop_price is None or self._stop_price - candidate > step:
                    self._stop_price = candidate

    def _maybe_hit_protection(self):
        if not self.position:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self._stop_price is not None and low <= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and high >= self._take_profit_price:
                self.order = self.close()
                return True
        else:
            if self._stop_price is not None and high >= self._stop_price:
                self.order = self.close()
                return True
            if self._take_profit_price is not None and low <= self._take_profit_price:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self.data) <= self.p.ssp + self.p.relay + 2:
            return
        if self.order:
            return

        self._set_initial_protection()
        if self.position:
            self._apply_trailing()
            if self._maybe_hit_protection():
                return

        need_open_buy = float(self.signal.sell[-1]) == 0.0 and float(self.signal.buy[-1]) != 0.0
        need_open_sell = float(self.signal.buy[-1]) == 0.0 and float(self.signal.sell[-1]) != 0.0

        if not self.position:
            if need_open_buy:
                stop_price = float(self.data.close[0]) - self.p.stop_loss_pips * self._pip_size() if self.p.stop_loss_pips > 0 else float(self.data.close[0])
                self.order = self.buy(size=self._entry_size(stop_price))
                return
            if need_open_sell:
                stop_price = float(self.data.close[0]) + self.p.stop_loss_pips * self._pip_size() if self.p.stop_loss_pips > 0 else float(self.data.close[0])
                self.order = self.sell(size=self._entry_size(stop_price))
                return
        else:
            if self.position.size < 0 and need_open_buy:
                self.order = self.close()
                return
            if self.position.size > 0 and need_open_sell:
                self.order = self.close()
                return

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == order.Completed and self.position:
            self._set_initial_protection()
        if order.status in [bt.Order.Completed, bt.Order.Canceled, bt.Order.Margin, bt.Order.Rejected]:
            self.order = None
        if not self.position:
            self._entry_price = None
            self._stop_price = None
            self._take_profit_price = None
            self._last_position_size = 0.0

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
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self._entry_price = None
        self._stop_price = None
        self._take_profit_price = None
        self._last_position_size = 0.0
