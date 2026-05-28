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


class GpfTcpivotstopStrategy(bt.Strategy):
    params = dict(
        lots=0.1,
        max_risk=0.02,
        decrease_factor=3.0,
        target_profit=3,
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

        self.addminperiod(3)

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

    def _pivot_levels(self):
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

        sell_levels = {
            1: (resist1 + spread, support1 + spread),
            2: (resist2 + spread, support2 + spread),
            3: (resist3 + spread, support3 + spread),
        }
        buy_levels = {
            1: (support1, resist1),
            2: (support2, resist2),
            3: (support3, resist3),
        }

        return {
            'pivot': pivot,
            'resist1': resist1,
            'resist2': resist2,
            'resist3': resist3,
            'support1': support1,
            'support2': support2,
            'support3': support3,
            'buy_levels': buy_levels,
            'sell_levels': sell_levels,
        }

    def _intraday_close_signal(self):
        if not bool(self.p.is_trade_day):
            return False
        dt = bt.num2date(self.data_intraday.datetime[0])
        return dt.hour == 23

    def _set_entry_levels(self, is_long, levels, first_target):
        self.first_target = first_target
        if is_long:
            self.stop_price, self.take_price = levels
        else:
            self.stop_price, self.take_price = levels

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

        levels = self._pivot_levels()
        pivot = levels['pivot']
        close_prev = float(self.data_intraday.close[-1])
        close_prev2 = float(self.data_intraday.close[-2])
        open_buy = close_prev > pivot and close_prev2 <= pivot
        open_sell = close_prev < pivot and close_prev2 >= pivot
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1

        if self.position:
            return

        lot = self._current_lot()
        target_idx = max(1, min(3, int(self.p.target_profit)))

        if open_buy and not open_sell:
            primary_levels = levels['buy_levels'][target_idx]
            fallback_levels = (levels['support2'], levels['resist3'])
            chosen_levels = primary_levels
            self._set_entry_levels(True, chosen_levels, levels['resist1'])
            self.log(f'buy signal pivot={pivot:.5f} close_prev={close_prev:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy:
            primary_levels = levels['sell_levels'][target_idx]
            fallback_levels = (levels['resist2'] + float(self.p.spread_points) * float(self.p.point), levels['support3'] + float(self.p.spread_points) * float(self.p.point))
            chosen_levels = primary_levels
            self._set_entry_levels(False, chosen_levels, levels['support1'])
            self.log(f'sell signal pivot={pivot:.5f} close_prev={close_prev:.5f} lot={lot:.2f}')
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
