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


class HarvesterStrategy(bt.Strategy):
    params = dict(
        fast_ema=12,
        slow_ema=24,
        signal_ema=9,
        number_bars_macd=6,
        sma1=50,
        sma2=100,
        min_indentation=10,
        number_bars_sl=6,
        adx_enable=False,
        buy_level_adx=50,
        sell_level_adx=50,
        period_adx=14,
        half_ratio=2,
        lots=1.0,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.macd = bt.ind.MACD(self.data.close, period_me1=int(self.p.fast_ema), period_me2=int(self.p.slow_ema), period_signal=int(self.p.signal_ema))
        self.sma_fast = bt.ind.SMA(self.data.close, period=int(self.p.sma1))
        self.sma_slow = bt.ind.SMA(self.data.close, period=int(self.p.sma2))
        self.adx = bt.ind.ADX(self.data, period=int(self.p.period_adx))
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
        self.partial_taken = False

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _adx_ok(self, direction):
        if bool(self.p.adx_enable):
            current_adx = float(self.adx[0])
        else:
            current_adx = 60.0
        if direction == 'buy':
            return current_adx > float(self.p.buy_level_adx)
        return current_adx > float(self.p.sell_level_adx)

    def _macd_window_has_opposite(self, direction):
        window = [float(self.macd.macd[-i]) for i in range(1, int(self.p.number_bars_macd) + 1) if len(self) > i]
        if not window:
            return False
        if direction == 'buy':
            return min(window) < 0.0
        return max(window) > 0.0

    def _entry_buy(self):
        close_1 = float(self.data.close[-1])
        sma1_1 = float(self.sma_fast[-1])
        sma2_1 = float(self.sma_slow[-1])
        macd_1 = float(self.macd.macd[-1])
        indent = float(self.p.min_indentation) * self._point()
        okbuy = close_1 < sma2_1
        return close_1 + indent > sma1_1 and close_1 + indent > sma2_1 and macd_1 > 0 and okbuy and self._adx_ok('buy') and self._macd_window_has_opposite('buy')

    def _entry_sell(self):
        close_1 = float(self.data.close[-1])
        sma1_1 = float(self.sma_fast[-1])
        sma2_1 = float(self.sma_slow[-1])
        macd_1 = float(self.macd.macd[-1])
        indent = float(self.p.min_indentation) * self._point()
        oksell = close_1 > sma2_1
        return close_1 - indent < sma1_1 and close_1 - indent < sma2_1 and macd_1 < 0 and oksell and self._adx_ok('sell') and self._macd_window_has_opposite('sell')

    def _manage_position(self):
        if not self.position or self.order is not None:
            return
        close_1 = float(self.data.close[-1])
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            target = float(self.position.price) + abs(float(self.position.price) - float(self.stop_price)) * float(self.p.half_ratio)
            if not self.partial_taken and close_1 > target and abs(self.position.size) >= 2.0:
                self.partial_taken = True
                self.order = self.close(size=abs(self.position.size) / 2.0)
                self.stop_price = self._round(float(self.position.price))
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
        else:
            target = float(self.position.price) - abs(float(self.position.price) - float(self.stop_price)) * float(self.p.half_ratio)
            if not self.partial_taken and close_1 < target and abs(self.position.size) >= 2.0:
                self.partial_taken = True
                self.order = self.close(size=abs(self.position.size) / 2.0)
                self.stop_price = self._round(float(self.position.price))
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.sma2) + 5, int(self.p.number_bars_macd) + 5, int(self.p.period_adx) + 5)
        if len(self) < warmup or self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        if self._entry_buy():
            stoploss = min(float(self.data.low[-i]) for i in range(1, int(self.p.number_bars_sl) + 1) if len(self) > i)
            self.stop_price = self._round(stoploss)
            self.take_profit_price = None
            self.partial_taken = False
            self.signal_count += 1
            self.order = self.buy(size=float(self.p.lots))
            return
        if self._entry_sell():
            stoploss = max(float(self.data.high[-i]) for i in range(1, int(self.p.number_bars_sl) + 1) if len(self) > i)
            self.stop_price = self._round(stoploss)
            self.take_profit_price = None
            self.partial_taken = False
            self.signal_count += 1
            self.order = self.sell(size=float(self.p.lots))

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
                self.partial_taken = False
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
