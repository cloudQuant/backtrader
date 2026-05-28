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
        '<TICKVOL>': 'volume',
        '<VOL>': 'openinterest',
        '<SPREAD>': 'spread',
    })
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest', 'spread']]
    df = df.set_index('datetime').sort_index()
    if bar_shift_minutes:
        df.index = df.index + pd.Timedelta(minutes=bar_shift_minutes)
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


class Mt5PandasFeed(bt.feeds.PandasData):
    lines = ('spread',)
    params = (
        ('datetime', None),
        ('open', 0),
        ('high', 1),
        ('low', 2),
        ('close', 3),
        ('volume', 4),
        ('openinterest', 5),
        ('spread', 6),
    )


class MultiDivergenceEaStrategy(bt.Strategy):
    params = dict(
        lot_size=0.1,
        stop_loss=100,
        take_profit=200,
        max_spread=30,
        use_money_management=False,
        risk_percent=2.0,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        stoch_k=5,
        stoch_d=3,
        stoch_slowing=3,
        bars_to_check=50,
        min_bars_distance=5,
        min_divergence_strength=0.7,
        min_confirmations=3,
        use_volume_filter=True,
        use_trend_filter=True,
        allow_buy=True,
        allow_sell=True,
        max_trades=1,
        magic_number=123456,
        trend_ema_period=50,
        volume_lookback=10,
        volume_multiplier=1.2,
        point_size=0.01,
        lot_min=0.01,
        lot_max=100.0,
        lot_step=0.01,
        contract_multiplier=100.0,
    )

    def __init__(self):
        self.data_feed = self.datas[0]
        self.rsi = bt.indicators.RSI(self.data_feed.close, period=self.p.rsi_period)
        self.macd = bt.indicators.MACD(
            self.data_feed.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )
        self.stoch = bt.indicators.Stochastic(
            self.data_feed,
            period=self.p.stoch_k,
            period_dfast=self.p.stoch_slowing,
            period_dslow=self.p.stoch_d,
        )
        self.trend_ema = bt.indicators.EMA(self.data_feed.close, period=self.p.trend_ema_period)
        self.current_order = None
        self.stop_order = None
        self.limit_order = None
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0

    def log(self, text):
        dt = bt.num2date(self.data_feed.datetime[0])
        print(f'{dt.isoformat()}, {text}')

    def _normalize_lot(self, lots):
        lots = min(max(lots, self.p.lot_min), self.p.lot_max)
        lots = int(lots / self.p.lot_step) * self.p.lot_step
        return round(max(lots, self.p.lot_min), 4)

    def _calculate_lot_size(self):
        if not self.p.use_money_management:
            return self._normalize_lot(self.p.lot_size)
        if self.p.stop_loss <= 0 or self.p.point_size <= 0 or self.p.contract_multiplier <= 0:
            return self._normalize_lot(self.p.lot_size)
        risk_amount = self.broker.getvalue() * (self.p.risk_percent / 100.0)
        risk_per_lot = self.p.stop_loss * self.p.point_size * self.p.contract_multiplier
        if risk_per_lot <= 0:
            return self._normalize_lot(self.p.lot_size)
        return self._normalize_lot(risk_amount / risk_per_lot)

    def _spread_ok(self):
        spread = float(self.data_feed.spread[0]) if len(self.data_feed) else 0.0
        return spread <= self.p.max_spread

    def _count_trades(self):
        return 1 if self.position else 0

    def _safe_abs_max(self, value1, value2):
        return max(abs(value1), abs(value2), 1e-12)

    def _calculate_divergence_strength(self, price1, price2, ind1, ind2):
        price_change = abs(price1 - price2) / self._safe_abs_max(price1, price2)
        ind_change = abs(ind1 - ind2) / self._safe_abs_max(ind1, ind2)
        return min(price_change + ind_change, 1.0)

    def _find_peaks_and_troughs(self, indicator_line):
        price_highs = []
        price_lows = []
        ind_highs = []
        ind_lows = []
        high_bars = []
        low_bars = []
        for i in range(self.p.min_bars_distance, self.p.bars_to_check - self.p.min_bars_distance):
            is_peak = True
            is_trough = True
            current_high = float(self.data_feed.high[-i])
            current_low = float(self.data_feed.low[-i])
            current_ind = float(indicator_line[-i])
            for j in range(1, self.p.min_bars_distance + 1):
                if i - j < 0 or i + j >= self.p.bars_to_check:
                    continue
                if current_high <= float(self.data_feed.high[-(i - j)]) or current_high <= float(self.data_feed.high[-(i + j)]):
                    is_peak = False
                    break
            if is_peak:
                avg_high = 0.0
                count = 0
                for k in range(i - self.p.min_bars_distance * 2, i + self.p.min_bars_distance * 2 + 1):
                    if k < 0 or k >= self.p.bars_to_check or k == i:
                        continue
                    avg_high += float(self.data_feed.high[-k])
                    count += 1
                if count > 0 and current_high <= avg_high / count * 1.001:
                    is_peak = False
            for j in range(1, self.p.min_bars_distance + 1):
                if i - j < 0 or i + j >= self.p.bars_to_check:
                    continue
                if current_low >= float(self.data_feed.low[-(i - j)]) or current_low >= float(self.data_feed.low[-(i + j)]):
                    is_trough = False
                    break
            if is_trough:
                avg_low = 0.0
                count = 0
                for k in range(i - self.p.min_bars_distance * 2, i + self.p.min_bars_distance * 2 + 1):
                    if k < 0 or k >= self.p.bars_to_check or k == i:
                        continue
                    avg_low += float(self.data_feed.low[-k])
                    count += 1
                if count > 0 and current_low >= avg_low / count * 0.999:
                    is_trough = False
            if is_peak:
                price_highs.append(current_high)
                ind_highs.append(current_ind)
                high_bars.append(i)
            if is_trough:
                price_lows.append(current_low)
                ind_lows.append(current_ind)
                low_bars.append(i)
        return price_highs, price_lows, ind_highs, ind_lows, high_bars, low_bars

    def _check_divergence(self, indicator_line):
        price_highs, price_lows, ind_highs, ind_lows, _, _ = self._find_peaks_and_troughs(indicator_line)
        if len(price_lows) >= 2 and len(ind_lows) >= 2:
            if price_lows[0] < price_lows[1] and ind_lows[0] > ind_lows[1]:
                strength = self._calculate_divergence_strength(price_lows[0], price_lows[1], ind_lows[0], ind_lows[1])
                if strength >= self.p.min_divergence_strength:
                    return 1
        if len(price_highs) >= 2 and len(ind_highs) >= 2:
            if price_highs[0] > price_highs[1] and ind_highs[0] < ind_highs[1]:
                strength = self._calculate_divergence_strength(price_highs[0], price_highs[1], ind_highs[0], ind_highs[1])
                if strength >= self.p.min_divergence_strength:
                    return -1
        return 0

    def _analyze_divergences(self):
        bullish_count = 0
        bearish_count = 0
        signals = [
            self._check_divergence(self.rsi),
            self._check_divergence(self.macd.macd),
            self._check_divergence(self.stoch.percK),
        ]
        for signal in signals:
            if signal == 1:
                bullish_count += 1
            elif signal == -1:
                bearish_count += 1
        if bullish_count >= self.p.min_confirmations:
            return 1
        if bearish_count >= self.p.min_confirmations:
            return -1
        return 0

    def _confirm_trend_direction(self, signal):
        current_price = float(self.data_feed.close[0])
        ma_value = float(self.trend_ema[0])
        if signal == 1:
            return current_price > ma_value
        if signal == -1:
            return current_price < ma_value
        return False

    def _confirm_volume_pattern(self):
        if len(self.data_feed) < self.p.volume_lookback + 1:
            return False
        avg_volume = 0.0
        for i in range(self.p.volume_lookback):
            avg_volume += float(self.data_feed.volume[-i])
        avg_volume /= self.p.volume_lookback
        recent_volume = float(self.data_feed.volume[0])
        return recent_volume > avg_volume * self.p.volume_multiplier

    def _open_bracket(self, direction):
        lots = self._calculate_lot_size()
        price = float(self.data_feed.close[0])
        stop_distance = self.p.stop_loss * self.p.point_size
        target_distance = self.p.take_profit * self.p.point_size
        if self.p.stop_loss <= 0 and self.p.take_profit <= 0:
            self.current_order = self.buy(size=lots) if direction == 'long' else self.sell(size=lots)
            self.stop_order = None
            self.limit_order = None
            return
        if direction == 'long':
            stop_price = price - stop_distance if self.p.stop_loss > 0 else None
            limit_price = price + target_distance if self.p.take_profit > 0 else None
            orders = self.buy_bracket(size=lots, stopprice=stop_price, limitprice=limit_price)
        else:
            stop_price = price + stop_distance if self.p.stop_loss > 0 else None
            limit_price = price - target_distance if self.p.take_profit > 0 else None
            orders = self.sell_bracket(size=lots, stopprice=stop_price, limitprice=limit_price)
        self.current_order = orders[0]
        self.stop_order = orders[1]
        self.limit_order = orders[2]

    def next(self):
        self.bar_num += 1
        min_bars = max(
            self.p.bars_to_check + self.p.min_bars_distance * 2 + 5,
            self.p.trend_ema_period + 2,
            self.p.volume_lookback + 2,
            self.p.macd_slow + self.p.macd_signal + 2,
            self.p.rsi_period + 2,
            self.p.stoch_k + self.p.stoch_slowing + self.p.stoch_d + 2,
        )
        if len(self.data_feed) < min_bars:
            return
        if self.current_order:
            return
        if self._count_trades() >= self.p.max_trades:
            return
        if not self._spread_ok():
            return
        divergence_signal = self._analyze_divergences()
        if divergence_signal != 0:
            if self.p.use_trend_filter and not self._confirm_trend_direction(divergence_signal):
                divergence_signal = 0
            if self.p.use_volume_filter and not self._confirm_volume_pattern():
                divergence_signal = 0
        if divergence_signal == 1 and self.p.allow_buy:
            self._open_bracket('long')
        elif divergence_signal == -1 and self.p.allow_sell:
            self._open_bracket('short')

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        if order.status == order.Completed:
            if order == self.current_order:
                if order.isbuy():
                    self.buy_count += 1
                    self.log(f'long entry price={order.executed.price:.2f} volume={order.executed.size:.4f}')
                else:
                    self.sell_count += 1
                    self.log(f'short entry price={order.executed.price:.2f} volume={abs(order.executed.size):.4f}')
            elif order == self.stop_order:
                self.log(f'stop executed price={order.executed.price:.2f}')
                if self.limit_order and self.limit_order.alive():
                    self.cancel(self.limit_order)
            elif order == self.limit_order:
                self.log(f'target executed price={order.executed.price:.2f}')
                if self.stop_order and self.stop_order.alive():
                    self.cancel(self.stop_order)
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            if order == self.current_order:
                self.current_order = None
            if order == self.stop_order:
                self.stop_order = None
            if order == self.limit_order:
                self.limit_order = None

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
        self.log(f'trade closed pnl={trade.pnlcomm:.2f}')
