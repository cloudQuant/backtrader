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


class Expert20200AntSStrategy(bt.Strategy):
    params = dict(
        t1=6,
        t2=2,
        delta_l=6,
        delta_s=21,
        take_profit_l=390,
        stop_loss_l=1470,
        take_profit_s=320,
        stop_loss_s=2670,
        lots=0.1,
        auto_lot=True,
        big_lot_size=6.0,
        one_mult=True,
        trade_time=14,
        max_open_time=504,
        point=0.01,
    )

    def __init__(self):
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
        self._position_was_open = False
        self.last_balance = None
        self.pre_lots = None
        self.entry_datetime = None

        self.addminperiod(max(int(self.p.t1), int(self.p.t2)) + 5)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _base_lot(self):
        lot = float(self.p.lots)
        if bool(self.p.auto_lot):
            lot = max(self.broker.getvalue() / 100000.0, 0.01)
        return max(round(lot, 2), 0.01)

    def _solve_lots(self):
        lots = self._base_lot()
        lots2 = lots
        if self.last_balance is not None and self.last_balance > self.broker.getvalue():
            if bool(self.p.auto_lot) and self.pre_lots is not None:
                lots = self.pre_lots
            lots = max(round(lots * float(self.p.big_lot_size), 2), 0.01)
        return lots, lots2

    def _check_max_open_time(self):
        if not self.position or self.order is not None or int(self.p.max_open_time) <= 0 or self.entry_datetime is None:
            return False
        dt_now = bt.num2date(self.data.datetime[0])
        held_hours = (dt_now - self.entry_datetime).total_seconds() / 3600.0
        if held_hours >= float(self.p.max_open_time):
            self.log(f'close by max_open_time held_hours={held_hours:.2f}')
            self.order = self.close()
            return True
        return False

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
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

        if self._check_max_open_time():
            return
        if self._check_exit_levels():
            return
        if self.position:
            return

        dt = bt.num2date(self.data.datetime[0])
        if dt.hour != int(self.p.trade_time):
            return

        op1 = float(self.data.open[-int(self.p.t1)])
        op2 = float(self.data.open[-int(self.p.t2)])
        open_buy = op2 - op1 > float(self.p.point) * float(self.p.delta_l)
        open_sell = op1 - op2 > float(self.p.point) * float(self.p.delta_s)
        if not open_buy and not open_sell:
            return

        lots, lots2 = self._solve_lots()
        px = float(self.data.close[0])
        self.signal_count += 1

        if open_buy and not open_sell:
            self.stop_price = px - float(self.p.point) * float(self.p.stop_loss_l) if int(self.p.stop_loss_l) > 0 else None
            self.take_price = px + float(self.p.point) * float(self.p.take_profit_l) if int(self.p.take_profit_l) > 0 else None
            self.log(f'buy signal op2-op1={op2 - op1:.5f} lot={lots:.2f}')
            self.order = self.buy(size=lots)
            self.last_balance = self.broker.getvalue()
            self.pre_lots = lots2 if bool(self.p.one_mult) else lots
            return

        if open_sell and not open_buy:
            self.stop_price = px + float(self.p.point) * float(self.p.stop_loss_s) if int(self.p.stop_loss_s) > 0 else None
            self.take_price = px - float(self.p.point) * float(self.p.take_profit_s) if int(self.p.take_profit_s) > 0 else None
            self.log(f'sell signal op1-op2={op1 - op2:.5f} lot={lots:.2f}')
            self.order = self.sell(size=lots)
            self.last_balance = self.broker.getvalue()
            self.pre_lots = lots2 if bool(self.p.one_mult) else lots
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
            self.entry_datetime = bt.num2date(self.data.datetime[0])
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
        self.entry_datetime = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
