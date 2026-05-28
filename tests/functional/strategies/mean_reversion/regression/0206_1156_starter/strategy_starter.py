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


class LaguerreFilter(bt.Indicator):
    lines = ('value',)
    params = dict(gamma=0.7)

    def __init__(self):
        self.addminperiod(2)
        self._l0 = None
        self._l1 = None
        self._l2 = None
        self._l3 = None

    def next(self):
        price = float(self.data[0])
        gamma = float(self.p.gamma)
        if self._l0 is None:
            self._l0 = price
            self._l1 = price
            self._l2 = price
            self._l3 = price
            self.lines.value[0] = 0.5
            return
        l0_prev = self._l0
        l1_prev = self._l1
        l2_prev = self._l2
        l3_prev = self._l3
        self._l0 = (1.0 - gamma) * price + gamma * l0_prev
        self._l1 = -gamma * self._l0 + l0_prev + gamma * l1_prev
        self._l2 = -gamma * self._l1 + l1_prev + gamma * l2_prev
        self._l3 = -gamma * self._l2 + l2_prev + gamma * l3_prev
        cu = 0.0
        cd = 0.0
        pairs = ((self._l0, self._l1), (self._l1, self._l2), (self._l2, self._l3))
        for left, right in pairs:
            if left >= right:
                cu += left - right
            else:
                cd += right - left
        denom = cu + cd
        self.lines.value[0] = cu / denom if denom else self.lines.value[-1]


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


class StarterStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        maximum_risk=0.05,
        decrease_factor=0,
        stop_loss=100,
        take_profit=0,
        virtual_sltp=True,
        lag_gamma=0.7,
        cci_period=14,
        cci_price=0,
        cci_level=5,
        ma_period=5,
        ma_shift=0,
        ma_method='ema',
        ma_price=4,
        shift=0,
        point=0.01,
    )

    def __init__(self):
        self.price_cci = self._price_line(self.p.cci_price)
        self.price_ma = self._price_line(self.p.ma_price)
        self.laguerre = LaguerreFilter(self.data.close, gamma=self.p.lag_gamma)
        self.cci = AppliedPriceCCI(self.price_cci, period=self.p.cci_period)
        ma_cls = self._ma_class(self.p.ma_method)
        self.ma = ma_cls(self.price_ma, period=self.p.ma_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self.stop_price = None
        self.take_price = None
        self.stop_order = None
        self.limit_order = None
        self._position_was_open = False
        self._closed_trade_pnls = []

        self.addminperiod(max(self.p.cci_period, self.p.ma_period) + int(self.p.shift) + 5)

    def _price_line(self, price_code):
        code = int(price_code)
        if code == 0:
            return self.data.close
        if code == 1:
            return self.data.open
        if code == 2:
            return self.data.high
        if code == 3:
            return self.data.low
        if code == 4:
            return (self.data.high + self.data.low) / 2.0
        if code == 5:
            return (self.data.high + self.data.low + self.data.close) / 3.0
        if code == 6:
            return (self.data.high + self.data.low + self.data.close + self.data.close) / 4.0
        return self.data.close

    def _ma_class(self, method):
        name = str(method).lower()
        mapping = {
            'sma': bt.indicators.SimpleMovingAverage,
            'ema': bt.indicators.ExponentialMovingAverage,
            'smma': bt.indicators.SmoothedMovingAverage,
            'lwma': bt.indicators.WeightedMovingAverage,
            'wma': bt.indicators.WeightedMovingAverage,
        }
        return mapping.get(name, bt.indicators.ExponentialMovingAverage)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _loss_streak(self):
        losses = 0
        for pnl in reversed(self._closed_trade_pnls):
            if pnl > 0:
                break
            if pnl < 0:
                losses += 1
        return losses

    def _normalize_lot(self, lot):
        return max(round(float(lot), 2), 0.01)

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.maximum_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        if int(self.p.decrease_factor) > 0:
            losses = self._loss_streak()
            if losses > 1:
                lot = lot - lot * losses / float(self.p.decrease_factor)
        return self._normalize_lot(lot)

    def _idx(self):
        return -int(self.p.shift) if int(self.p.shift) > 0 else 0

    def _ma_idx(self):
        return self._idx() - int(self.p.ma_shift)

    def _cancel_exit_orders(self):
        if self.stop_order is not None:
            self.cancel(self.stop_order)
            self.stop_order = None
        if self.limit_order is not None:
            self.cancel(self.limit_order)
            self.limit_order = None

    def _check_exit_levels(self):
        if not bool(self.p.virtual_sltp) or not self.position or self.order is not None:
            return False
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_price is not None and high >= self.take_price:
                self.log(f'close long by take={self.take_price:.5f}')
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.log(f'close long by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
        else:
            if self.take_price is not None and low <= self.take_price:
                self.log(f'close short by take={self.take_price:.5f}')
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.log(f'close short by stop={self.stop_price:.5f}')
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        idx = self._idx()
        ma_idx = self._ma_idx()
        lag = float(self.laguerre[idx])
        cci = float(self.cci[idx])
        ma0 = float(self.ma[ma_idx])
        ma1 = float(self.ma[ma_idx - 1])

        open_buy = lag <= 0.000001 and ma0 > ma1 and cci < -float(self.p.cci_level)
        open_sell = lag >= 0.999999 and ma0 < ma1 and cci > float(self.p.cci_level)
        close_buy = lag > 0.9
        close_sell = lag < 0.1
        if (open_buy and not open_sell and not close_buy) or (open_sell and not open_buy and not close_sell):
            self.signal_count += 1

        if self.position:
            if self.position.size > 0 and close_buy:
                self._cancel_exit_orders()
                self.log(f'close buy by laguerre={lag:.5f}')
                self.order = self.close()
                return
            if self.position.size < 0 and close_sell:
                self._cancel_exit_orders()
                self.log(f'close sell by laguerre={lag:.5f}')
                self.order = self.close()
                return
            if self._check_exit_levels():
                return
            return

        lot = self._current_lot()
        px = float(self.data.close[0])

        if open_buy and not open_sell and not close_buy:
            self.stop_price = px - float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px + float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'buy signal lag={lag:.5f} cci={cci:.5f} ma0={ma0:.5f} ma1={ma1:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot, price=None, exectype=bt.Order.Market)
            return

        if open_sell and not open_buy and not close_sell:
            self.stop_price = px + float(self.p.point) * float(self.p.stop_loss) if int(self.p.stop_loss) > 0 else None
            self.take_price = px - float(self.p.point) * float(self.p.take_profit) if int(self.p.take_profit) > 0 else None
            self.log(f'sell signal lag={lag:.5f} cci={cci:.5f} ma0={ma0:.5f} ma1={ma1:.5f} lot={lot:.2f}')
            self.order = self.sell(size=lot, price=None, exectype=bt.Order.Market)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order == self.stop_order:
            if order.status == order.Completed:
                self.stop_order = None
                self.limit_order = None
            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.stop_order = None
            return
        if order == self.limit_order:
            if order.status == order.Completed:
                self.limit_order = None
                self.stop_order = None
            elif order.status in [order.Canceled, order.Margin, order.Rejected]:
                self.limit_order = None
            return
        if order.status == order.Completed:
            if not bool(self.p.virtual_sltp) and self.position:
                size = abs(order.executed.size)
                if order.isbuy():
                    if self.stop_price is not None:
                        self.stop_order = self.sell(size=size, exectype=bt.Order.Stop, price=self.stop_price)
                    if self.take_price is not None:
                        self.limit_order = self.sell(size=size, exectype=bt.Order.Limit, price=self.take_price, oco=self.stop_order)
                elif order.issell():
                    if self.stop_price is not None:
                        self.stop_order = self.buy(size=size, exectype=bt.Order.Stop, price=self.stop_price)
                    if self.take_price is not None:
                        self.limit_order = self.buy(size=size, exectype=bt.Order.Limit, price=self.take_price, oco=self.stop_order)
            self.order = None
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
        self._closed_trade_pnls.append(float(trade.pnlcomm))
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.stop_order = None
        self.limit_order = None
        self.stop_price = None
        self.take_price = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
