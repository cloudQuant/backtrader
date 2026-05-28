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


def resample_daily(df):
    out = df.resample('1D', label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'openinterest': 'last',
    })
    out = out.dropna(subset=['open', 'high', 'low', 'close'])
    out['openinterest'] = out['openinterest'].fillna(0)
    return out


class Mt5PandasFeed(bt.feeds.PandasData):
    params = (
        ('datetime', None), ('open', 0), ('high', 1), ('low', 2), ('close', 3), ('volume', 4), ('openinterest', 5),
    )


class TenPipsEURUSDStrategy(bt.Strategy):
    params = dict(
        lot=0.01,
        stop_loss=50,
        take_profit=150,
        use_trailing=False,
        trailing_stop_loss=50,
        trailing_step=25,
        point=0.0001,
        digits_adjust=1,
        price_digits=5,
    )

    def __init__(self):
        self.base = self.datas[0]
        self.daily = self.datas[1]

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
        self.pending_buy_level = None
        self.pending_sell_level = None
        self.day_has_traded = False
        self.last_session_date = None

    def _unit(self):
        return float(self.p.point) * float(self.p.digits_adjust)

    def _reset_day(self):
        self.pending_buy_level = None
        self.pending_sell_level = None
        self.day_has_traded = False

    def _prepare_orders(self):
        if len(self.daily) < 2:
            return
        session_date = bt.num2date(self.base.datetime[0]).date()
        if self.last_session_date != session_date:
            self.last_session_date = session_date
            self._reset_day()
            prev_high = float(self.daily.high[-1])
            prev_low = float(self.daily.low[-1])
            open_now = float(self.base.open[0])
            if open_now >= prev_high or open_now <= prev_low:
                return
            spread_pad = self._unit() * 2.0
            self.pending_buy_level = round(prev_high + spread_pad, int(self.p.price_digits))
            self.pending_sell_level = round(prev_low - self._unit(), int(self.p.price_digits))

    def _apply_risk(self, side, entry):
        unit = self._unit()
        if side == 'buy':
            self.stop_price = round(entry - float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(entry + float(self.p.take_profit) * unit, int(self.p.price_digits)) if not self.p.use_trailing else None
        else:
            self.stop_price = round(entry + float(self.p.stop_loss) * unit, int(self.p.price_digits))
            self.take_profit_price = round(entry - float(self.p.take_profit) * unit, int(self.p.price_digits)) if not self.p.use_trailing else None

    def _manage_position(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        close = float(self.base.close[0])
        unit = self._unit()
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and low <= self.stop_price:
                self.order = self.close()
                return True
            if self.p.use_trailing and close - float(self.position.price) > float(self.p.trailing_stop_loss) * unit:
                candidate = round(close - float(self.p.trailing_stop_loss) * unit, int(self.p.price_digits))
                if self.stop_price is None or candidate > self.stop_price + float(self.p.trailing_step) * unit:
                    self.stop_price = candidate
        else:
            if self.take_profit_price is not None and low <= self.take_profit_price:
                self.order = self.close()
                return True
            if self.stop_price is not None and high >= self.stop_price:
                self.order = self.close()
                return True
            if self.p.use_trailing and float(self.position.price) - close > float(self.p.trailing_stop_loss) * unit:
                candidate = round(close + float(self.p.trailing_stop_loss) * unit, int(self.p.price_digits))
                if self.stop_price is None or candidate < self.stop_price - float(self.p.trailing_step) * unit:
                    self.stop_price = candidate
        return False

    def next(self):
        self.bar_num += 1
        self._prepare_orders()
        if self.order is not None:
            return
        if self.position:
            self._manage_position()
            return
        if self.day_has_traded:
            return
        high = float(self.base.high[0])
        low = float(self.base.low[0])
        if self.pending_buy_level is not None and high >= self.pending_buy_level:
            self.signal_count += 1
            self._apply_risk('buy', self.pending_buy_level)
            self.order = self.buy(size=self.p.lot)
            self.day_has_traded = True
            self.pending_sell_level = None
            return
        if self.pending_sell_level is not None and low <= self.pending_sell_level:
            self.signal_count += 1
            self._apply_risk('sell', self.pending_sell_level)
            self.order = self.sell(size=self.p.lot)
            self.day_has_traded = True
            self.pending_buy_level = None

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
