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
        '<TICKVOL>': 'tick_volume',
        '<VOL>': 'real_volume',
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


class MacdPatternTraderAllStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        perema1=7,
        perema2=21,
        persma3=98,
        perema4=365,
        patterns=(
            dict(name='Pattern1', enable=True, stoplossbars=22, takeprofitbars=32, otstup=40, fast=24, slow=13),
            dict(name='Pattern2', enable=True, stoplossbars=2, takeprofitbars=2, otstup=50, fast=17, slow=7),
            dict(name='Pattern3', enable=True, stoplossbars=8, takeprofitbars=12, otstup=2, fast=32, slow=2),
            dict(name='Pattern4', enable=True, stoplossbars=10, takeprofitbars=32, otstup=45, fast=4, slow=9),
            dict(name='Pattern5', enable=True, stoplossbars=8, takeprofitbars=47, otstup=45, fast=6, slow=2),
            dict(name='Pattern6', enable=True, stoplossbars=26, takeprofitbars=42, otstup=20, fast=4, slow=8),
        ),
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.macds = []
        for pattern in self.p.patterns:
            self.macds.append((pattern, bt.indicators.MACD(self.data.close, period_me1=pattern['fast'], period_me2=pattern['slow'], period_signal=1)))
        self.ema1 = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.perema1)
        self.ema2 = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.perema2)
        self.sma1 = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.persma3)
        self.ema3 = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.perema4)

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
        self.active_pattern = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _stop_loss(self, side, bars, otstup):
        lookback = max(2, int(bars))
        unit = self._unit()
        if side == 'sell':
            value = max(float(self.data.high[-i]) for i in range(1, min(len(self), lookback + 1))) + float(otstup) * unit
        else:
            value = min(float(self.data.low[-i]) for i in range(1, min(len(self), lookback + 1))) - float(otstup) * unit
        return round(value, int(self.p.price_digits))

    def _take_profit(self, side, bars):
        lookback = max(2, int(bars))
        if side == 'sell':
            value = min(float(self.data.low[-i]) for i in range(1, min(len(self), lookback + 1)))
        else:
            value = max(float(self.data.high[-i]) for i in range(1, min(len(self), lookback + 1)))
        return round(value, int(self.p.price_digits))

    def _pattern_signal(self, indicator):
        macd_curr = float(indicator.macd[-1])
        macd_last = float(indicator.macd[-2]) if len(indicator) > 2 else 0.0
        macd_last3 = float(indicator.macd[-3]) if len(indicator) > 3 else 0.0
        if abs(macd_last) < 1e-12:
            return None
        if (macd_last3 > 0.0 or macd_curr < 0.0) and abs(macd_last3 / macd_last) >= 5.0 and abs(macd_curr / macd_last) >= 5.0:
            return 'sell'
        if (macd_last3 < 0.0 or macd_curr > 0.0) and abs(macd_last3 / macd_last) >= 5.0 and abs(macd_curr / macd_last) >= 5.0:
            return 'buy'
        return None

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        if self.position.size > 0:
            if self.take_profit_price is not None and float(self.data.high[0]) >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and float(self.data.low[0]) <= self.stop_price:
                self.order = self.close()
                return True
            if self.position.size > 0 and self.position.price < float(self.data.close[0]):
                if float(self.data.close[-1]) > float(self.ema2[0]) or float(self.data.high[-1]) > (float(self.sma1[0]) + float(self.ema3[0])) / 2.0:
                    self.order = self.close()
                    return True
        else:
            if self.take_profit_price is not None and float(self.data.low[0]) <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and float(self.data.high[0]) >= self.stop_price:
                self.order = self.close()
                return True
            if self.position.price > float(self.data.close[0]):
                if float(self.data.close[-1]) < float(self.ema2[0]) or float(self.data.low[-1]) < (float(self.sma1[0]) + float(self.ema3[0])) / 2.0:
                    self.order = self.close()
                    return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < max(self.p.perema4, 50):
            return
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        for pattern, indicator in reversed(self.macds):
            if not pattern['enable']:
                continue
            signal = self._pattern_signal(indicator)
            if signal is None:
                continue
            self.signal_count += 1
            self.active_pattern = pattern['name']
            if signal == 'sell':
                self.stop_price = self._stop_loss('sell', pattern['stoplossbars'], pattern['otstup'])
                self.take_profit_price = self._take_profit('sell', pattern['takeprofitbars'])
                self.order = self.sell(size=self.p.lots)
                return
            self.stop_price = self._stop_loss('buy', pattern['stoplossbars'], pattern['otstup'])
            self.take_profit_price = self._take_profit('buy', pattern['takeprofitbars'])
            self.order = self.buy(size=self.p.lots)
            return

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
                self.active_pattern = None
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
