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


class AngryBirdScalpingStrategy(bt.Strategy):
    params = dict(
        stoploss=500,
        min_profit_point=10,
        trail_step=10,
        lot_exponent=1.62,
        default_pips=12,
        glubina=24,
        lots=0.01,
        lotdecimal=2,
        take_profit=20,
        cci_drop=500,
        rsi_min=30.0,
        rsi_max=70.0,
        max_trades=10,
        use_equity_stop=False,
        total_equity_risk=20.0,
        point=0.01,
        digits_adjust=10,
        price_digits=2,
    )

    def __init__(self):
        self.cci = bt.indicators.CCI(self.data.close, period=55)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

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
        self.last_open_buy_price = None
        self.last_open_sell_price = None
        self.long_trade = False
        self.short_trade = False

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _pip_step(self):
        lookback = min(len(self), int(self.p.glubina) + 1)
        highs = [float(self.data.high[-i]) for i in range(1, lookback)]
        lows = [float(self.data.low[-i]) for i in range(1, lookback)]
        if not highs or not lows:
            return float(self.p.default_pips)
        pip_step = round((max(highs) - min(lows)) / float(self.p.point) / float(self.p.digits_adjust), 0)
        return max(pip_step, float(self.p.default_pips))

    def _count_trades(self):
        return 1 if self.position else 0

    def _avg_price(self):
        return float(self.position.price) if self.position else 0.0

    def _calc_lot(self, count_trades):
        return round(float(self.p.lots) * (float(self.p.lot_exponent) ** count_trades), int(self.p.lotdecimal))

    def _close_all(self):
        if self.position and self.order is None:
            self.order = self.close()

    def _equity_stop(self):
        if not bool(self.p.use_equity_stop):
            return False
        pnl = self.broker.getvalue() - self.broker.startingcash
        if pnl < 0 and abs(pnl) > float(self.p.total_equity_risk) * self.broker.getvalue() / 100.0:
            self._close_all()
            return True
        return False

    def _manage_basket(self):
        if not self.position or self.order is not None:
            return False
        avg_price = self._avg_price()
        unit = self._unit()
        if self.position.size > 0:
            price_target = avg_price + float(self.p.take_profit) * unit
            stopper = avg_price - float(self.p.stoploss) * unit
            if float(self.data.high[0]) >= price_target or float(self.data.low[0]) <= stopper:
                self.order = self.close()
                return True
        else:
            price_target = avg_price - float(self.p.take_profit) * unit
            stopper = avg_price + float(self.p.stoploss) * unit
            if float(self.data.low[0]) <= price_target or float(self.data.high[0]) >= stopper:
                self.order = self.close()
                return True
        return False

    def next(self):
        self.bar_num += 1
        if len(self) < 60:
            return
        if self.order is not None:
            return
        avg_price = self._avg_price()
        if (float(self.cci[0]) > float(self.p.cci_drop) and self.short_trade) or (float(self.cci[0]) < -float(self.p.cci_drop) and self.long_trade):
            self._close_all()
            return
        if self._equity_stop():
            return
        if self.position:
            if self._manage_basket():
                return
        count_trades = self._count_trades()
        pip_step = self._pip_step()
        trade_now = False
        if count_trades > 0 and count_trades <= int(self.p.max_trades):
            if self.long_trade and self.last_open_buy_price is not None and self.last_open_buy_price - float(self.data.close[0]) >= pip_step * self._unit():
                trade_now = True
            if self.short_trade and self.last_open_sell_price is not None and float(self.data.close[0]) - self.last_open_sell_price >= pip_step * self._unit():
                trade_now = True
        if count_trades < 1:
            self.short_trade = False
            self.long_trade = False
            trade_now = True
        if trade_now and count_trades > 0:
            size = self._calc_lot(count_trades)
            self.signal_count += 1
            if self.short_trade:
                self.order = self.sell(size=size)
                self.last_open_sell_price = float(self.data.close[0])
                return
            if self.long_trade:
                self.order = self.buy(size=size)
                self.last_open_buy_price = float(self.data.close[0])
                return
        if trade_now and count_trades < 1:
            prev_cl = float(self.data.close[-2])
            curr_cl = float(self.data.close[-1])
            size = self._calc_lot(count_trades)
            if prev_cl > curr_cl and float(self.rsi[-1]) > float(self.p.rsi_min):
                self.signal_count += 1
                self.short_trade = True
                self.long_trade = False
                self.order = self.sell(size=size)
                self.last_open_sell_price = float(self.data.close[0])
                return
            if prev_cl < curr_cl and float(self.rsi[-1]) < float(self.p.rsi_max):
                self.signal_count += 1
                self.long_trade = True
                self.short_trade = False
                self.order = self.buy(size=size)
                self.last_open_buy_price = float(self.data.close[0])

    def notify_order(self, order):
        if order.status in [bt.Order.Submitted, bt.Order.Accepted]:
            return
        if order.status == bt.Order.Completed:
            self.completed_order_count += 1
            if self.position:
                if order.executed.size > 0:
                    self.buy_count += 1
                    self.long_trade = True
                    self.short_trade = False
                    self.last_open_buy_price = float(order.executed.price)
                elif order.executed.size < 0:
                    self.sell_count += 1
                    self.short_trade = True
                    self.long_trade = False
                    self.last_open_sell_price = float(order.executed.price)
            else:
                self.last_open_buy_price = None
                self.last_open_sell_price = None
                self.long_trade = False
                self.short_trade = False
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
