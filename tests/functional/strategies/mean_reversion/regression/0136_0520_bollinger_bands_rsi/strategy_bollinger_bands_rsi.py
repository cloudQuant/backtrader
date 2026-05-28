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


class BollingerBandsRSIStrategy(bt.Strategy):
    params = dict(
        enter=0,
        bands_period=140,
        deviation_teeth=2.0,
        rsi_filter=False,
        rsi_ma_period=8,
        rsi_lower_level=70,
        stochastic_filter=True,
        sto_kperiod=20,
        sto_lower_level=95,
        closure=2,
        bar_shift=1,
        only_one_position=True,
        lots=0.1,
        stop_loss=200,
        take_profit=200,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
        self.bb_teeth = bt.ind.BollingerBands(self.data.close, period=int(self.p.bands_period), devfactor=float(self.p.deviation_teeth))
        self.bb_jaws = bt.ind.BollingerBands(self.data.close, period=int(self.p.bands_period), devfactor=float(self.p.deviation_teeth) / 2.0)
        self.bb_lips = bt.ind.BollingerBands(self.data.close, period=int(self.p.bands_period), devfactor=float(self.p.deviation_teeth) * 2.0)
        self.rsi = bt.ind.RSI(self.data.close, period=int(self.p.rsi_ma_period))
        self.stochastic = bt.ind.Stochastic(self.data, period=int(self.p.sto_kperiod), period_dfast=3, period_dslow=3)
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
        self.okbuy = False
        self.oksell = False

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _band_value(self, line):
        shift = -int(self.p.bar_shift)
        return float(line[shift])

    def _levels(self):
        upper_teeth = self._band_value(self.bb_teeth.top)
        base_teeth = self._band_value(self.bb_teeth.mid)
        lower_teeth = self._band_value(self.bb_teeth.bot)
        upper_jaws = self._band_value(self.bb_jaws.top)
        lower_jaws = self._band_value(self.bb_jaws.bot)
        upper_lips = self._band_value(self.bb_lips.top)
        lower_lips = self._band_value(self.bb_lips.bot)
        if int(self.p.enter) == 0:
            enter_buy = upper_teeth + ((upper_jaws - upper_teeth) / 2.0)
            enter_sell = lower_teeth - ((lower_teeth - lower_jaws) / 2.0)
        elif int(self.p.enter) == 1:
            enter_buy = upper_jaws + ((upper_lips - upper_jaws) / 2.0)
            enter_sell = lower_jaws - ((lower_jaws - lower_lips) / 2.0)
        elif int(self.p.enter) == 2:
            enter_buy = upper_teeth
            enter_sell = lower_teeth
        elif int(self.p.enter) == 3:
            enter_buy = upper_jaws
            enter_sell = lower_jaws
        else:
            enter_buy = upper_lips
            enter_sell = lower_lips
        if (int(self.p.closure) == 1 and int(self.p.enter) == 0) or (int(self.p.closure) == 2 and int(self.p.enter) == 1):
            close_buy = enter_sell
            close_sell = enter_buy
        elif int(self.p.closure) == 0:
            close_buy = base_teeth
            close_sell = base_teeth
        elif int(self.p.closure) == 3:
            close_buy = lower_teeth
            close_sell = upper_teeth
        elif int(self.p.closure) == 4:
            close_buy = lower_jaws
            close_sell = upper_jaws
        elif int(self.p.closure) == 5:
            close_buy = lower_lips
            close_sell = upper_lips
        else:
            close_buy = lower_jaws - ((lower_jaws - lower_lips) / 2.0)
            close_sell = upper_jaws + ((upper_lips - upper_jaws) / 2.0)
        return base_teeth, enter_buy, enter_sell, close_buy, close_sell

    def _filters(self):
        shift = -int(self.p.bar_shift)
        rsi_val = float(self.rsi[shift]) if bool(self.p.rsi_filter) else None
        sto_val = float(self.stochastic.percK[shift]) if bool(self.p.stochastic_filter) else None
        buy_ok = True
        sell_ok = True
        if bool(self.p.rsi_filter):
            buy_ok = buy_ok and rsi_val <= (100.0 - float(self.p.rsi_lower_level))
            sell_ok = sell_ok and rsi_val >= float(self.p.rsi_lower_level)
        if bool(self.p.stochastic_filter):
            buy_ok = buy_ok and sto_val < (100.0 - float(self.p.sto_lower_level))
            sell_ok = sell_ok and sto_val > float(self.p.sto_lower_level)
        return buy_ok, sell_ok

    def _check_exit(self, close_buy, close_sell):
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
            if float(self.data.close[0]) >= float(close_sell):
                self.order = self.close(); return
        elif self.position.size < 0:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return
            if float(self.data.close[0]) <= float(close_buy):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.bands_period), int(self.p.rsi_ma_period), int(self.p.sto_kperiod)) + int(self.p.bar_shift) + 5
        if len(self) < warmup or self.order is not None:
            return
        base_teeth, enter_buy, enter_sell, close_buy, close_sell = self._levels()
        if self.position:
            self._check_exit(close_buy, close_sell)
            return
        buy_ok, sell_ok = self._filters()
        price = float(self.data.close[0])
        if not bool(self.p.only_one_position):
            if price >= base_teeth:
                self.okbuy = False
            if price <= base_teeth:
                self.oksell = False
        if price >= enter_buy and sell_ok and (bool(self.p.only_one_position) or not self.oksell):
            sl_dist = float(self.p.stop_loss) * self._point()
            tp_dist = float(self.p.take_profit) * self._point()
            self.stop_price = self._round(price + sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price - tp_dist) if tp_dist > 0 else None
            self.signal_count += 1
            self.oksell = True
            self.order = self.sell(size=float(self.p.lots))
            return
        if price <= enter_sell and buy_ok and (bool(self.p.only_one_position) or not self.okbuy):
            sl_dist = float(self.p.stop_loss) * self._point()
            tp_dist = float(self.p.take_profit) * self._point()
            self.stop_price = self._round(price - sl_dist) if sl_dist > 0 else None
            self.take_profit_price = self._round(price + tp_dist) if tp_dist > 0 else None
            self.signal_count += 1
            self.okbuy = True
            self.order = self.buy(size=float(self.p.lots))

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
