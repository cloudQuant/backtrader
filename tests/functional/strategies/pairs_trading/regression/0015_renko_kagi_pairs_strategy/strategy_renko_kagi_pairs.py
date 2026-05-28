from __future__ import absolute_import, division, print_function, unicode_literals

import io

import backtrader as bt
import numpy as np
import pandas as pd


def load_mt5_csv(filepath, fromdate=None, todate=None):
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as handle:
        lines = [line.strip().strip('"') for line in handle.readlines() if line.strip()]
    cleaned = '\n'.join(lines)
    sep = '\t' if '\t' in lines[0] else ','
    df = pd.read_csv(io.StringIO(cleaned), sep=sep)
    if 'time' in df.columns:
        df['datetime'] = pd.to_datetime(df['time'], errors='coerce', utc=True).dt.tz_convert(None)
        if 'volume' not in df.columns:
            df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
        df['openinterest'] = 0
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
        df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
        if fromdate is not None:
            df = df[df.index >= fromdate]
        if todate is not None:
            df = df[df.index <= todate]
        return df
    dt_text = df['<DATE>'].astype(str) + ' ' + df['<TIME>'].astype(str)
    parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M', errors='coerce')
    if parsed.isna().any():
        parsed = pd.to_datetime(dt_text, format='%Y.%m.%d %H:%M:%S', errors='coerce')
    df['datetime'] = parsed
    df = df.rename(columns={
        '<OPEN>': 'open', '<HIGH>': 'high', '<LOW>': 'low', '<CLOSE>': 'close',
        '<TICKVOL>': 'tick_volume', '<VOL>': 'real_volume',
    })
    df['openinterest'] = 0
    df['volume'] = df['tick_volume'] if 'tick_volume' in df.columns else 0
    df = df[['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df = df.dropna(subset=['datetime']).set_index('datetime').sort_index()
    if fromdate is not None:
        df = df[df.index >= fromdate]
    if todate is not None:
        df = df[df.index <= todate]
    return df


def prepare_pairs_inputs(asset_map):
    aligned_index = None
    prepared = {}
    for symbol, frame in asset_map.items():
        aligned_index = frame.index if aligned_index is None else aligned_index.intersection(frame.index)
    aligned_index = aligned_index.sort_values()
    for symbol, frame in asset_map.items():
        prepared[symbol] = frame.loc[aligned_index][['open', 'high', 'low', 'close', 'volume', 'openinterest']].copy()
    close_df = pd.DataFrame({symbol: frame.loc[aligned_index, 'close'] for symbol, frame in asset_map.items()}, index=aligned_index)
    return prepared, close_df, aligned_index


def _build_renko_directions(prices, brick_size):
    renko_prices = [float(prices[0])]
    renko_directions = [1]
    for current_price in prices[1:]:
        last_renko = renko_prices[-1]
        direction = renko_directions[-1]
        change = float(current_price - last_renko)
        if direction == 1:
            if change >= brick_size:
                bricks = int(change / brick_size)
                for _ in range(bricks):
                    renko_prices.append(renko_prices[-1] + brick_size)
                    renko_directions.append(1)
            elif change <= -brick_size * 2:
                bricks = int(abs(change) / brick_size)
                for _ in range(bricks):
                    renko_prices.append(renko_prices[-1] - brick_size)
                    renko_directions.append(-1)
        else:
            if change <= -brick_size:
                bricks = int(abs(change) / brick_size)
                for _ in range(bricks):
                    renko_prices.append(renko_prices[-1] - brick_size)
                    renko_directions.append(-1)
            elif change >= brick_size * 2:
                bricks = int(change / brick_size)
                for _ in range(bricks):
                    renko_prices.append(renko_prices[-1] + brick_size)
                    renko_directions.append(1)
    return renko_prices, renko_directions


class RenkoKagiPairsStrategy(bt.Strategy):
    params = dict(
        atr_period=14,
        atr_multiplier=1.5,
        confirmation_bricks=2,
        deviation_threshold=1.0,
        hedge_ratio_lookback=96,
        position_size=0.5,
        commission_pct=0.0005,
    )

    def __init__(self):
        self.order_refs = set()
        self.bar_num = 0
        self.buy_count = 0
        self.sell_count = 0
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.broker_value_series = []
        self.turning_point_count = 0
        self.signal_count = 0

    def _submit(self, order):
        if order is not None:
            self.order_refs.add(order.ref)

    def _target_size(self, data, target_pct):
        broker_value = float(self.broker.getvalue())
        price = float(data.close[0])
        if broker_value <= 0 or price <= 0:
            return 0.0
        comminfo = self.broker.getcommissioninfo(data)
        multiplier = float(getattr(comminfo.p, 'mult', 1.0) or 1.0)
        if multiplier <= 0:
            return 0.0
        size = broker_value * abs(float(target_pct)) / (price * multiplier)
        size = max(0.01, round(size, 2))
        return size if target_pct >= 0 else -size

    def next(self):
        self.bar_num += 1
        gold = self.datas[0]
        silver = self.datas[1]
        self.broker_value_series.append((bt.num2date(gold.datetime[0]), float(self.broker.getvalue())))
        if self.order_refs:
            return
        lookback = max(int(self.p.hedge_ratio_lookback), int(self.p.atr_period) + 10)
        if len(gold) <= lookback or len(silver) <= lookback:
            return
        gold_prices = np.array([float(gold.close[-i]) for i in range(lookback - 1, -1, -1)], dtype=float)
        silver_prices = np.array([float(silver.close[-i]) for i in range(lookback - 1, -1, -1)], dtype=float)
        hedge_ratio = float(np.polyfit(silver_prices, gold_prices, 1)[0]) if np.std(silver_prices) > 0 else 1.0
        spread = pd.Series(gold_prices - hedge_ratio * silver_prices)
        tr = pd.concat([
            (spread - spread.shift(1)).abs(),
            (spread - spread.rolling(2).max().shift(1)).abs(),
            (spread - spread.rolling(2).min().shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr = float(tr.rolling(int(self.p.atr_period)).mean().iloc[-1])
        if not np.isfinite(atr) or atr <= 0:
            return
        brick_size = atr * float(self.p.atr_multiplier)
        renko_prices, renko_directions = _build_renko_directions(spread.tolist(), brick_size)
        if len(renko_directions) < int(self.p.confirmation_bricks) + 2:
            return
        turning_points = [i for i in range(1, len(renko_directions)) if renko_directions[i] != renko_directions[i - 1]]
        self.turning_point_count = len(turning_points)
        if not turning_points:
            return
        last_turn = turning_points[-1]
        confirmed = len(renko_directions) - last_turn >= int(self.p.confirmation_bricks)
        if not confirmed:
            return
        current_direction = renko_directions[-1]
        deviation = abs(float(spread.iloc[-1] - renko_prices[last_turn])) / brick_size
        if deviation < float(self.p.deviation_threshold):
            return
        self.signal_count += 1
        if current_direction == 1:
            target_gold_pct = -float(self.p.position_size)
            target_silver_pct = float(self.p.position_size)
        else:
            target_gold_pct = float(self.p.position_size)
            target_silver_pct = -float(self.p.position_size)
        gold_target_size = self._target_size(gold, target_gold_pct)
        silver_target_size = self._target_size(silver, target_silver_pct)
        gold_current = float(self.getposition(gold).size)
        silver_current = float(self.getposition(silver).size)
        if abs(gold_target_size - gold_current) >= 0.01:
            if gold_target_size > gold_current:
                self.buy_count += 1
            elif gold_target_size < gold_current:
                self.sell_count += 1
            self._submit(self.order_target_size(data=gold, target=gold_target_size))
        if abs(silver_target_size - silver_current) >= 0.01:
            if silver_target_size > silver_current:
                self.buy_count += 1
            elif silver_target_size < silver_current:
                self.sell_count += 1
            self._submit(self.order_target_size(data=silver, target=silver_target_size))

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.order_refs.discard(order.ref)

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.trade_count += 1
        if trade.pnlcomm >= 0:
            self.win_count += 1
        else:
            self.loss_count += 1
