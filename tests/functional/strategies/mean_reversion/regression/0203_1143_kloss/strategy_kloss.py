from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import backtrader.feeds as btfeeds
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


class Mt5PandasFeed(btfeeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2),
        ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class AppliedPriceCCI(bt.Indicator):
    lines = ('cci',)
    params = dict(period=14, factor=0.015)

    def __init__(self):
        self.addminperiod(int(self.p.period) + 1)

    def next(self):
        period = int(self.p.period)
        prices = [float(self.data[-i]) for i in range(period)]
        mean_price = sum(prices) / period
        mean_dev = sum(abs(price - mean_price) for price in prices) / period
        denom = float(self.p.factor) * mean_dev
        if denom == 0:
            self.lines.cci[0] = 0.0
            return
        self.lines.cci[0] = (float(self.data[0]) - mean_price) / denom


class KlossStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        maximum_risk=0.05,
        stop_loss=550,
        take_profit=550,
        rev_close=True,
        ma_period=1,
        ma_method='lwma',
        ma_price='typical',
        ma_shift=5,
        p_shift=1,
        cci_period=10,
        cci_price='weighted',
        cci_differ=120,
        cci_shift=0,
        st_k_period=5,
        st_d_period=3,
        st_s_period=3,
        st_method='sma',
        st_price='lowhigh',
        st_shift=0,
        st_differ=20,
        common_shift=1,
        mw_mode=True,
        point=0.01,
    )

    def __init__(self):
        self.ma_index = int(self.p.ma_shift) + int(self.p.common_shift)
        self.price_index = int(self.p.p_shift) + int(self.p.common_shift)
        self.cci_index = int(self.p.cci_shift) + int(self.p.common_shift)
        self.st_index = int(self.p.st_shift) + int(self.p.common_shift)

        ma_input = self._price_line(self.p.ma_price)
        ma_cls = self._ma_class(self.p.ma_method)
        self.ma = ma_cls(ma_input, period=int(self.p.ma_period))
        self.cci = AppliedPriceCCI(self._price_line(self.p.cci_price), period=int(self.p.cci_period))
        self.stochastic = bt.indicators.Stochastic(
            self.data,
            period=int(self.p.st_k_period),
            period_dfast=int(self.p.st_d_period),
            period_dslow=int(self.p.st_s_period),
            movav=self._ma_class(self.p.st_method),
        )

        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.signal_count = 0

        self.order = None
        self.stop_price = None
        self.take_price = None
        self.pending_stop_price = None
        self.pending_take_price = None
        self._position_was_open = False

        self.addminperiod(max(self.ma_period_safe(), self.ma_index, self.price_index, self.cci_index, self.st_index) + 10)

    def ma_period_safe(self):
        return max(int(self.p.ma_period), int(self.p.cci_period), int(self.p.st_k_period) + int(self.p.st_d_period) + int(self.p.st_s_period))

    def _ma_class(self, method):
        name = str(method).lower()
        mapping = {
            'sma': bt.indicators.SimpleMovingAverage,
            'ema': bt.indicators.ExponentialMovingAverage,
            'smma': bt.indicators.SmoothedMovingAverage,
            'lwma': bt.indicators.WeightedMovingAverage,
            'wma': bt.indicators.WeightedMovingAverage,
        }
        return mapping.get(name, bt.indicators.WeightedMovingAverage)

    def _price_line(self, price_name):
        name = str(price_name).lower()
        if name == 'open':
            return self.data.open
        if name == 'high':
            return self.data.high
        if name == 'low':
            return self.data.low
        if name == 'median':
            return (self.data.high + self.data.low) / 2.0
        if name == 'typical':
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if name == 'weighted':
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _solve_lots(self):
        if float(self.p.lots) == 0:
            lot = self.broker.getcash() * float(self.p.maximum_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        return max(round(lot, 2), 0.01)

    def _buy_signal(self):
        cci = float(self.cci[-self.cci_index])
        st_main = float(self.stochastic.percK[-self.st_index])
        cl = float(self.data.close[-self.price_index])
        ma = float(self.ma[-self.ma_index])
        return cci < -float(self.p.cci_differ) and st_main < 50.0 - float(self.p.st_differ) and cl > ma

    def _sell_signal(self):
        cci = float(self.cci[-self.cci_index])
        st_main = float(self.stochastic.percK[-self.st_index])
        cl = float(self.data.close[-self.price_index])
        ma = float(self.ma[-self.ma_index])
        return cci > float(self.p.cci_differ) and st_main > 50.0 + float(self.p.st_differ) and cl < ma

    def _activate_mw_mode(self):
        if not bool(self.p.mw_mode) or not self.position:
            return
        if self.stop_price is None and self.take_price is None and (self.pending_stop_price is not None or self.pending_take_price is not None):
            self.stop_price = self.pending_stop_price
            self.take_price = self.pending_take_price
            self.pending_stop_price = None
            self.pending_take_price = None

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        self._activate_mw_mode()
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        if self._check_exit_levels():
            return

        open_buy = self._buy_signal()
        open_sell = self._sell_signal()
        close_buy = open_sell if bool(self.p.rev_close) else False
        close_sell = open_buy if bool(self.p.rev_close) else False

        if self.position:
            if self.position.size > 0 and close_buy:
                self.log('close long by reverse signal')
                self.order = self.close()
                return
            if self.position.size < 0 and close_sell:
                self.log('close short by reverse signal')
                self.order = self.close()
                return
            return

        lot = self._solve_lots()
        px = float(self.data.close[0])
        self.signal_count += int(open_buy or open_sell)

        if open_buy and not open_sell and not close_buy:
            stop_price = px - float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            take_price = px + float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            if bool(self.p.mw_mode):
                self.pending_stop_price = stop_price
                self.pending_take_price = take_price
                self.stop_price = None
                self.take_price = None
            else:
                self.stop_price = stop_price
                self.take_price = take_price
            self.log(f'buy signal lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy and not close_sell:
            stop_price = px + float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            take_price = px - float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            if bool(self.p.mw_mode):
                self.pending_stop_price = stop_price
                self.pending_take_price = take_price
                self.stop_price = None
                self.take_price = None
            else:
                self.stop_price = stop_price
                self.take_price = take_price
            self.log(f'sell signal lot={lot:.2f}')
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
        self.order = None

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
        self.stop_price = None
        self.take_price = None
        self.pending_stop_price = None
        self.pending_take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
