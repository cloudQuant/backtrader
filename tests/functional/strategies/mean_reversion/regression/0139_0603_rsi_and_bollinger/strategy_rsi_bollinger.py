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


class RSIBollingerStrategy(bt.Strategy):
    """RSI + Bollinger Bands + Fractals + SAR strategy (EA 0603).

    Buy setup:
      1. RSI(prev bar) > BB upper band (applied on RSI).
      2. Price close(prev bar) < upper fractal level.
      3. Entry via BuyStop at fractal + indenting (simulated as market when price crosses).
      4. SAR trailing stop.

    Sell setup:
      1. RSI(prev bar) < BB lower band (applied on RSI).
      2. Price close(prev bar) > lower fractal level.
      3. Entry via SellStop at fractal - indenting (simulated as market when price crosses).
      4. SAR trailing stop.

    Simplified: Since Backtrader doesn't natively apply BB on RSI output,
    we compute RSI, then manually apply BB on the RSI values.
    """

    params = dict(
        rsi_period=8,
        bands_period=14,
        bands_deviation=1.0,
        sar_step=0.003,
        sar_max=0.2,
        lots=0.1,
        take_profit=50,
        stop_loss=135,
        indenting=15,
        rsi_up=70.0,
        rsi_down=30.0,
        sar_trailing_stop=10,
        point=0.01,
        price_digits=2,
    )

    def __init__(self):
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

        self.rsi = bt.indicators.RSI(self.data.close, period=int(self.p.rsi_period))
        self.bb_rsi = bt.indicators.BollingerBands(
            self.rsi, period=int(self.p.bands_period), devfactor=float(self.p.bands_deviation),
        )
        self.sar = bt.indicators.ParabolicSAR(
            self.data, period=2, af=float(self.p.sar_step), afmax=float(self.p.sar_max),
        )

        self.pending_buy_level = None
        self.pending_sell_level = None
        self.upper_fractal = None
        self.lower_fractal = None
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _update_fractals(self):
        if len(self) < 5:
            return
        h_m2 = float(self.data.high[-4])
        h_m1 = float(self.data.high[-3])
        h_0 = float(self.data.high[-2])
        h_p1 = float(self.data.high[-1])
        h_p2 = float(self.data.high[0])
        if h_0 > h_m1 and h_0 > h_m2 and h_0 > h_p1 and h_0 > h_p2:
            self.upper_fractal = h_0

        l_m2 = float(self.data.low[-4])
        l_m1 = float(self.data.low[-3])
        l_0 = float(self.data.low[-2])
        l_p1 = float(self.data.low[-1])
        l_p2 = float(self.data.low[0])
        if l_0 < l_m1 and l_0 < l_m2 and l_0 < l_p1 and l_0 < l_p2:
            self.lower_fractal = l_0

    def next(self):
        self.bar_num += 1
        warmup = max(int(self.p.rsi_period), int(self.p.bands_period)) + 5
        if len(self) < warmup:
            return
        if self.order is not None:
            return

        self._update_fractals()

        if self.position:
            self._check_exit()
            return

        rsi_val = float(self.rsi[-1]) if len(self.rsi) > 1 else 0
        bb_upper = float(self.bb_rsi.top[-1]) if len(self.bb_rsi.top) > 1 else 100
        bb_lower = float(self.bb_rsi.bot[-1]) if len(self.bb_rsi.bot) > 1 else 0
        prev_close = float(self.data.close[-1])

        if self.upper_fractal is not None and rsi_val > bb_upper and prev_close < self.upper_fractal:
            entry_price = self.upper_fractal + float(self.p.indenting) * self._point()
            if float(self.data.high[0]) >= entry_price:
                self.signal_count += 1
                sl_dist = float(self.p.stop_loss) * self._point()
                tp_dist = float(self.p.take_profit) * self._point()
                self.stop_price = self._round(entry_price - sl_dist) if sl_dist > 0 else None
                self.take_profit_price = self._round(entry_price + tp_dist) if tp_dist > 0 else None
                self.order = self.buy(size=self.p.lots)
                self.pending_buy_level = None
                return

        if rsi_val < float(self.p.rsi_down):
            self.pending_buy_level = None

        if self.lower_fractal is not None and rsi_val < bb_lower and prev_close > self.lower_fractal:
            entry_price = self.lower_fractal - float(self.p.indenting) * self._point()
            if float(self.data.low[0]) <= entry_price:
                self.signal_count += 1
                sl_dist = float(self.p.stop_loss) * self._point()
                tp_dist = float(self.p.take_profit) * self._point()
                self.stop_price = self._round(entry_price + sl_dist) if sl_dist > 0 else None
                self.take_profit_price = self._round(entry_price - tp_dist) if tp_dist > 0 else None
                self.order = self.sell(size=self.p.lots)
                self.pending_sell_level = None
                return

        if rsi_val > float(self.p.rsi_up):
            self.pending_sell_level = None

    def _check_exit(self):
        high = float(self.data.high[0])
        low = float(self.data.low[0])

        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close()
                return
            sar_val = float(self.sar[0])
            new_sl = self._round(sar_val - float(self.p.sar_trailing_stop) * self._point())
            if self.stop_price is None or new_sl > float(self.stop_price):
                self.stop_price = new_sl
        elif self.position.size < 0:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close()
                return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close()
                return
            sar_val = float(self.sar[0])
            new_sl = self._round(sar_val + float(self.p.sar_trailing_stop) * self._point())
            if self.stop_price is None or new_sl < float(self.stop_price):
                self.stop_price = new_sl

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
