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


class GpfTcpivotlimitStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        max_risk=0.02,
        decrease_factor=3.0,
        target_profit=5,
        is_trade_day=False,
        mod_sl=False,
        spread_points=0.0,
        point=0.01,
    )

    def __init__(self):
        self.data_intraday = self.datas[0]
        self.data_daily = self.datas[1]

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
        self.first_target = None
        self._position_was_open = False
        self._closed_trade_pnls = []

        self.addminperiod(4)

    def log(self, text):
        dt = bt.num2date(self.data_intraday.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lot):
        return max(round(float(lot), 2), 0.01)

    def _loss_streak(self):
        losses = 0
        for pnl in reversed(self._closed_trade_pnls):
            if pnl > 0:
                break
            if pnl < 0:
                losses += 1
        return losses

    def _current_lot(self):
        if float(self.p.lots) == 0:
            lot = float(self.broker.getcash()) * float(self.p.max_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        if float(self.p.decrease_factor) > 0:
            losses = self._loss_streak()
            if losses > 1:
                lot = lot - lot * losses / float(self.p.decrease_factor)
        return self._normalize_lot(lot)

    def _levels(self):
        high = float(self.data_daily.high[-1])
        low = float(self.data_daily.low[-1])
        close = float(self.data_daily.close[-1])
        spread = float(self.p.spread_points) * float(self.p.point)

        pivot = (low + high + close) / 3.0
        resist1 = 2.0 * pivot - low
        support1 = 2.0 * pivot - high
        resist2 = pivot + (resist1 - support1)
        support2 = pivot - (resist1 - support1)
        resist3 = high + 2.0 * (pivot - low)
        support3 = low - 2.0 * (high - pivot)

        mapping = {
            1: dict(s_level=resist1, stop_sell=resist2, profit_sell=support1 + spread, b_level=support1, stop_buy=support2, profit_buy=resist1, target_sell=pivot, target_buy=pivot),
            2: dict(s_level=resist1, stop_sell=resist2, profit_sell=support2 + spread, b_level=support1, stop_buy=support2, profit_buy=resist2, target_sell=pivot, target_buy=pivot),
            3: dict(s_level=resist2, stop_sell=resist3, profit_sell=support1 + spread, b_level=support2, stop_buy=support3, profit_buy=resist1, target_sell=resist1, target_buy=support1),
            4: dict(s_level=resist2, stop_sell=resist3, profit_sell=support2 + spread, b_level=support2, stop_buy=support3, profit_buy=resist2, target_sell=resist1, target_buy=support1),
            5: dict(s_level=resist2, stop_sell=resist3, profit_sell=support3 + spread, b_level=support2, stop_buy=support3, profit_buy=resist3, target_sell=resist1, target_buy=support1),
        }
        idx = max(1, min(5, int(self.p.target_profit)))
        vals = mapping[idx]
        vals.update(dict(pivot=pivot, resist1=resist1, resist2=resist2, resist3=resist3, support1=support1, support2=support2, support3=support3, spread=spread))
        return vals

    def _intraday_close_signal(self):
        if not bool(self.p.is_trade_day):
            return False
        dt = bt.num2date(self.data_intraday.datetime[0])
        return dt.hour == 23

    def _maybe_move_stop_to_breakeven(self):
        if not bool(self.p.mod_sl) or not self.position or self.first_target is None:
            return
        spread = float(self.p.spread_points) * float(self.p.point)
        if self.position.size > 0:
            if float(self.data_intraday.close[0]) >= self.first_target:
                new_stop = float(self.position.price) + spread
                if self.stop_price is None or new_stop > self.stop_price:
                    self.stop_price = new_stop
        else:
            if float(self.data_intraday.close[0]) <= self.first_target:
                new_stop = float(self.position.price) - spread
                if self.stop_price is None or new_stop < self.stop_price:
                    self.stop_price = new_stop

    def _check_exit_levels(self):
        if not self.position or self.order is not None:
            return False
        high = float(self.data_intraday.high[0])
        low = float(self.data_intraday.low[0])
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
        if len(self.data_daily) < 2:
            return
        self.bar_num += 1
        if self.order is not None:
            return

        if self._intraday_close_signal() and self.position:
            self.log('close by intraday rule at 23:00')
            self.order = self.close()
            return

        self._maybe_move_stop_to_breakeven()
        if self._check_exit_levels():
            return

        vals = self._levels()
        cl1 = float(self.data_intraday.close[-1])
        cl2 = float(self.data_intraday.close[-2])
        hi2 = float(self.data_intraday.high[-2])
        lo2 = float(self.data_intraday.low[-2])
        op2 = float(self.data_intraday.open[-2])

        open_buy = ((lo2 < vals['b_level'] or cl2 <= vals['b_level']) and op2 > vals['b_level']) and cl1 >= vals['b_level']
        open_sell = ((hi2 > vals['s_level'] or cl2 >= vals['s_level']) and op2 < vals['s_level']) and cl1 <= vals['s_level']
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1

        if self.position:
            return

        lot = self._current_lot()
        if open_buy and not open_sell:
            self.stop_price = vals['stop_buy']
            self.take_price = vals['profit_buy']
            self.first_target = vals['target_buy']
            self.log(f"buy signal b_level={vals['b_level']:.5f} close_prev={cl1:.5f} lot={lot:.2f}")
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy:
            self.stop_price = vals['stop_sell']
            self.take_price = vals['profit_sell']
            self.first_target = vals['target_sell']
            self.log(f"sell signal s_level={vals['s_level']:.5f} close_prev={cl1:.5f} lot={lot:.2f}")
            self.order = self.sell(size=lot)
            return

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f'order failed status={order.getstatusname()}')
            if not self.position:
                self.stop_price = None
                self.take_price = None
                self.first_target = None
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
        self.stop_price = None
        self.take_price = None
        self.first_target = None
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
