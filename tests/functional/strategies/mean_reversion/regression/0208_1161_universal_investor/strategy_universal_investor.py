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


class UniversalInvestorStrategy(bt.Strategy):
    params = dict(
        moving_period=23,
        maximum_risk=0.05,
        lots=0.1,
        decrease_factor=0.0,
    )

    def __init__(self):
        self.ema = bt.indicators.ExponentialMovingAverage(self.data.close, period=self.p.moving_period)
        self.lwma = bt.indicators.WeightedMovingAverage(self.data.close, period=self.p.moving_period)

        self.bar_num = 0
        self.signal_count = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

        self.order = None
        self._position_was_open = False
        self._closed_trade_pnls = []

        self.addminperiod(int(self.p.moving_period) + 3)

    def log(self, text):
        dt = bt.num2date(self.data.datetime[0])
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
            lot = float(self.broker.getcash()) * float(self.p.maximum_risk) / 1000.0
        else:
            lot = float(self.p.lots)
        if float(self.p.decrease_factor) > 0:
            losses = self._loss_streak()
            if losses > 1:
                lot = lot - lot * losses / float(self.p.decrease_factor)
        return self._normalize_lot(lot)

    def next(self):
        self.bar_num += 1
        if self.order is not None:
            return

        ema1 = float(self.ema[-1])
        ema2 = float(self.ema[-2])
        lwma1 = float(self.lwma[-1])
        lwma2 = float(self.lwma[-2])

        open_buy = lwma1 > ema1 and lwma1 > lwma2 and ema1 > ema2
        open_sell = lwma1 < ema1 and lwma1 < lwma2 and ema1 < ema2
        close_buy = lwma1 < ema1
        close_sell = lwma1 > ema1
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1

        if self.position.size > 0 and close_buy:
            self.log(f'close buy ema={ema1:.5f} lwma={lwma1:.5f}')
            self.order = self.close()
            return

        if self.position.size < 0 and close_sell:
            self.log(f'close sell ema={ema1:.5f} lwma={lwma1:.5f}')
            self.order = self.close()
            return

        if self.position:
            return

        lot = self._current_lot()
        if open_buy and not open_sell and not close_buy:
            self.log(f'buy signal ema={ema1:.5f} lwma={lwma1:.5f} lot={lot:.2f}')
            self.order = self.buy(size=lot)
            return

        if open_sell and not open_buy and not close_sell:
            self.log(f'sell signal ema={ema1:.5f} lwma={lwma1:.5f} lot={lot:.2f}')
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
        self._closed_trade_pnls.append(float(trade.pnlcomm))
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self._position_was_open = False
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
