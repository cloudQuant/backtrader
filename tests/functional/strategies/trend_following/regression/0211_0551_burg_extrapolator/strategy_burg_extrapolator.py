from __future__ import absolute_import, division, print_function, unicode_literals

import io
import math

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


def burg_reflection_coeffs(series, order):
    if order <= 0 or len(series) <= order + 1:
        return []
    ef = list(series[1:])
    eb = list(series[:-1])
    refs = []
    for _ in range(order):
        if not ef or not eb:
            break
        num = -2.0 * sum(ef_i * eb_i for ef_i, eb_i in zip(ef, eb))
        den = sum(ef_i * ef_i + eb_i * eb_i for ef_i, eb_i in zip(ef, eb))
        k = num / den if den else 0.0
        refs.append(k)
        if len(ef) <= 1:
            break
        ef_next = []
        eb_next = []
        for i in range(len(ef) - 1):
            ef_next.append(ef[i + 1] + k * eb[i + 1])
            eb_next.append(eb[i] + k * ef[i])
        ef, eb = ef_next, eb_next
    return refs


def reflection_to_ar(refs):
    ar = []
    for k in refs:
        if not ar:
            ar = [k]
            continue
        prev = ar[:]
        ar = prev + [0.0]
        m = len(prev)
        for i in range(m):
            ar[i] = prev[i] + k * prev[m - 1 - i]
        ar[m] = k
    return ar


def burg_forecast(series, order, horizon):
    refs = burg_reflection_coeffs(series, order)
    ar = reflection_to_ar(refs)
    if not ar:
        return []
    history = list(series)
    preds = []
    for _ in range(horizon):
        lookback = history[-len(ar):]
        next_val = -sum(ar[i] * lookback[-1 - i] for i in range(len(ar)))
        preds.append(next_val)
        history.append(next_val)
    return preds


class BurgExtrapolatorStrategy(bt.Strategy):
    params = dict(
        risk=5.0,
        ntmax=5,
        min_profit=160,
        max_loss=130,
        take_profit=0,
        stop_loss=180,
        trailing_stop=10,
        past_bars=200,
        model_order=0.37,
        use_mom=True,
        use_roc=False,
        base_lot=0.1,
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
        self.stop_price = None
        self.take_profit_price = None

    def _point(self):
        return float(self.p.point)

    def _round(self, value):
        return round(float(value), int(self.p.price_digits))

    def _lot_size(self):
        return max(0.01, float(self.p.base_lot))

    def _build_transformed_series(self):
        bars = int(self.p.past_bars)
        opens = list(self.data.open.get(size=bars + 1))
        if len(opens) < bars + 1:
            return None
        use_mom = bool(self.p.use_mom)
        use_roc = bool(self.p.use_roc)
        if use_mom and use_roc:
            use_roc = False
        if use_mom:
            transformed = [math.log(float(opens[i + 1]) / float(opens[i])) for i in range(len(opens) - 1) if float(opens[i]) != 0]
            avg = None
        elif use_roc:
            transformed = [float(opens[i + 1]) / float(opens[i]) - 1.0 for i in range(len(opens) - 1) if float(opens[i]) != 0]
            avg = None
        else:
            base = [float(v) for v in opens[1:]]
            avg = sum(base) / len(base)
            transformed = [v - avg for v in base]
        return opens, transformed, avg, use_mom, use_roc

    def _forecast_prices(self):
        built = self._build_transformed_series()
        if built is None:
            return None
        opens, transformed, avg, use_mom, use_roc = built
        order = int(float(self.p.model_order) * int(self.p.past_bars))
        order = max(1, min(order, len(transformed) - 2))
        horizon = max(2, len(transformed) - order - 1)
        preds = burg_forecast(transformed, order, horizon)
        if not preds:
            return None
        current_open = float(opens[-1])
        prices = [current_open]
        if use_mom:
            for value in preds:
                prices.append(prices[-1] * math.exp(value))
        elif use_roc:
            for value in preds:
                prices.append(prices[-1] * (1.0 + value))
        else:
            for value in preds:
                prices.append(value + float(avg))
        return prices

    def _signal(self):
        prices = self._forecast_prices()
        if not prices or len(prices) < 2:
            return 0, 0
        ymax = prices[0]
        ymin = prices[0]
        imax = 0
        imin = 0
        open_signal = 0
        close_signal = 0
        min_profit = float(self.p.min_profit) * self._point()
        max_loss = float(self.p.max_loss) * self._point()
        for i in range(1, len(prices)):
            if prices[i] > ymax and open_signal == 0:
                ymax = prices[i]
                imax = i
                if imin == 0 and ymax - ymin >= max_loss:
                    close_signal = 1
                if imin == 0 and ymax - ymin >= min_profit:
                    open_signal = 1
            if prices[i] < ymin and open_signal == 0:
                ymin = prices[i]
                imin = i
                if imax == 0 and ymax - ymin >= max_loss:
                    close_signal = -1
                if imax == 0 and ymax - ymin >= min_profit:
                    open_signal = -1
        return open_signal, close_signal

    def _arm(self, direction, price):
        sl = float(self.p.stop_loss) * self._point()
        tp = float(self.p.take_profit) * self._point()
        if direction == 'buy':
            self.stop_price = self._round(price - sl) if sl > 0 else None
            self.take_profit_price = self._round(price + tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.buy(size=self._lot_size())
        else:
            self.stop_price = self._round(price + sl) if sl > 0 else None
            self.take_profit_price = self._round(price - tp) if tp > 0 else None
            self.signal_count += 1
            self.order = self.sell(size=self._lot_size())

    def _trail(self):
        if not self.position or self.order is not None or float(self.p.trailing_stop) <= 0 or float(self.p.stop_loss) <= 0:
            return
        ts = float(self.p.trailing_stop) * self._point()
        current = float(self.data.close[0])
        if self.position.size > 0:
            if current - float(self.position.price) > ts:
                new_sl = self._round(current - ts)
                if self.stop_price is None or new_sl > float(self.stop_price):
                    self.stop_price = new_sl
        else:
            if float(self.position.price) - current > ts:
                new_sl = self._round(current + ts)
                if self.stop_price is None or new_sl < float(self.stop_price):
                    self.stop_price = new_sl

    def _check_exit(self):
        if not self.position or self.order is not None:
            return
        high = float(self.data.high[0])
        low = float(self.data.low[0])
        if self.position.size > 0:
            if self.take_profit_price is not None and high >= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and low <= float(self.stop_price):
                self.order = self.close(); return
        else:
            if self.take_profit_price is not None and low <= float(self.take_profit_price):
                self.order = self.close(); return
            if self.stop_price is not None and high >= float(self.stop_price):
                self.order = self.close(); return

    def next(self):
        self.bar_num += 1
        if len(self) < int(self.p.past_bars) + 5 or self.order is not None:
            return
        open_signal, close_signal = self._signal()

        if self.position:
            if self.position.size > 0 and (close_signal == -1 or open_signal == -1):
                self.order = self.close()
                return
            if self.position.size < 0 and (close_signal == 1 or open_signal == 1):
                self.order = self.close()
                return
            self._trail()
            self._check_exit()
            return

        if open_signal == 1:
            self._arm('buy', float(self.data.close[0]))
            return
        if open_signal == -1:
            self._arm('sell', float(self.data.close[0]))

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
