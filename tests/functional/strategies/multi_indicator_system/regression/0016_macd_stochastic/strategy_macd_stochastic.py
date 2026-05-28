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


class MacdStochasticStrategy(bt.Strategy):
    params = dict(
        fast_ema_period=12,
        slow_ema_period=26,
        signal_period=9,
        use_stoch=True,
        bars_to_check_stoch=8,
        k_period=5,
        d_period=3,
        slowing=3,
        lots=0.1,
        stop_loss=100,
        take_profit=100,
        trailing_stop=0,
        trailing_step=5,
        max_positions=5,
        no_loss_stop=1,
        when_set_no_loss_stop=25,
        time_windows=((8, 15, 8, 35), (13, 45, 14, 42), (22, 15, 22, 45)),
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.macd = bt.ind.MACD(self.data.close, period_me1=int(self.p.fast_ema_period), period_me2=int(self.p.slow_ema_period), period_signal=int(self.p.signal_period))
        self.stoch = bt.ind.Stochastic(self.data, period=int(self.p.k_period), period_dfast=int(self.p.d_period), period_dslow=int(self.p.slowing))
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
        self.last_open_len = -1

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _is_good_time(self):
        dt = bt.num2date(self.data.datetime[0])
        hm = dt.hour * 60 + dt.minute
        for sh, sm, eh, em in self.p.time_windows:
            start = sh * 60 + sm
            end = eh * 60 + em
            if start <= hm <= end:
                return True
        return False

    def _check_stoch(self, direction):
        if not bool(self.p.use_stoch):
            return True
        main_current = float(self.stoch.percK[0])
        signal_current = float(self.stoch.percD[0])
        if direction == 'buy' and signal_current < main_current:
            for i in range(1, int(self.p.bars_to_check_stoch)):
                if len(self) <= i:
                    break
                if float(self.stoch.percD[-i]) > float(self.stoch.percK[-i]):
                    return True
        if direction == 'sell' and signal_current > main_current:
            for i in range(1, int(self.p.bars_to_check_stoch)):
                if len(self) <= i:
                    break
                if float(self.stoch.percD[-i]) < float(self.stoch.percK[-i]):
                    return True
        return False

    def _need_open_type(self):
        macd_main = float(self.macd.macd[0])
        macd_signal = float(self.macd.signal[0])
        macd_main_prev = float(self.macd.macd[-1])
        macd_signal_prev = float(self.macd.signal[-1])
        if macd_main > macd_signal and macd_main_prev <= macd_signal_prev and macd_main < 0 and macd_main_prev < 0:
            if self._check_stoch('buy'):
                return 'buy'
        if macd_main < macd_signal and macd_main_prev >= macd_signal_prev and macd_main > 0 and macd_main_prev > 0:
            if self._check_stoch('sell'):
                return 'sell'
        return None

    def _manage_positions(self):
        if not self.position or self.order is not None:
            return
        if float(self.p.trailing_stop) <= 0:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        current = float(self.data.close[0])
        when_set = float(self.p.when_set_no_loss_stop) * self._point()
        trail = float(self.p.trailing_stop) * self._point()
        step = float(self.p.trailing_step) * self._point()
        no_loss = float(self.p.no_loss_stop) * self._point()
        if self.position.size > 0:
            if current - float(self.position.price) > when_set:
                sl = float(self.stop_price or self.position.price)
                new_sl = sl + trail
                if current - step - trail > new_sl and new_sl > float(self.position.price) + no_loss:
                    self.stop_price = self._round(new_sl)
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if float(self.position.price) - current > when_set:
                sl = float(self.stop_price or self.position.price)
                new_sl = sl - trail
                if current + step + trail < new_sl and new_sl < float(self.position.price) - no_loss:
                    self.stop_price = self._round(new_sl)
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < 50 or self.order is not None:
            return
        if self.position:
            self._manage_positions()
        if len(self) == self.last_open_len:
            return
        position_slots = 1 if self.position else 0
        if position_slots >= int(self.p.max_positions):
            return
        if not self._is_good_time():
            return
        need = self._need_open_type()
        if need == 'buy':
            price = float(self.data.close[0])
            sl_dist = float(self.p.stop_loss) * self._point()
            tp_dist = float(self.p.take_profit) * self._point()
            self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price + tp_dist) if tp_dist > 0 else None
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lots))
            self.last_open_len = len(self)
            return
        if need == 'sell':
            price = float(self.data.close[0])
            sl_dist = float(self.p.stop_loss) * self._point()
            tp_dist = float(self.p.take_profit) * self._point()
            self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price - tp_dist) if tp_dist > 0 else None
            self.signal_count += 1
            self.order = self.sell(size=float(self.p.lots))
            self.last_open_len = len(self)

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
