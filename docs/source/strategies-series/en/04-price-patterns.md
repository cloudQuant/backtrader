# Price Patterns: Engulfing Candles, NR7 Days, and Darvas Boxes

> Strategy Compendium · No. 04 · Category `price_patterns` (44 strategies) · 2026-09-02

Steve Nison's 1991 *Japanese Candlestick Charting Techniques* carried Tokugawa-era charting onto Wall Street, and ever since "hammer," "engulfing," and "morning star" have been the lingua franca of traders. The intuition is seductive: a long lower shadow means selling was absorbed; a bar that swallows its predecessor means control changed hands — **a visible snapshot of supply and demand**. But what happens when you translate those shapes literally into code and run them on real bars?

This digest tours the 44 backtests in `tests/functional/strategies/price_patterns/` — all MT5 expert-advisor ports, mostly on XAUUSD M15 (three months, 1,000,000 initial, fixed 0.1 lots, zero commission: the signal itself on trial). The directory has a rare gift for methodology: several patterns exist in *plain* and *oscillator-confirmed* pairs, so the value of the confirmator — not the pattern — becomes the measurable variable. Alongside the candles sit the structure family: NR7 narrow-range days, Darvas boxes, fractals, Renko.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Engulfing (plain) | XAUUSD M15 | Full-bar engulfment; opposite pattern reverses | `test_0010_0588_bullish_bearish_engulfing.py` |
| Engulfing + RSI | XAUUSD M15 | Engulfing + body-size + RSI(11) second vote | `test_0028_1339_engulfing_rsi.py` |
| Hammer/hanging man + RSI | XAUUSD M15 | Hammer below SMA with RSI<40 | `test_0023_1323_hammer_rsi.py` |
| Morning/evening star + CCI | XAUUSD M15 | Three-bar star + CCI confirmation | `test_0019_1318_morningstar_cci.py` |
| Three Inside + bracket | XAUUSD M15→H1 | Three-bar reversal via `buy_bracket` | `test_0001_0033_simple_three_inside_pattern_ea.py` |
| NR7 breakout | XAUUSD daily, 2008-2025 | Break beyond the narrowest-range day of the last 7 | `test_0037_nr7_pattern_breakout.py` |
| Darvas boxes | XAUUSD M15+H4 | Box color transitions; 1000/2000-pt bracket | `test_0044_0853_darvasboxes_system.py` |
| Heikin Ashi | XAUUSD M15 | Smoothed candles; color flip = reverse | `test_0015_1204_heiken_ashi.py` |
| Adaptive Renko | XAUUSD M15+H4 | ATR-sized bricks, trendline entries | `test_0036_1234_adaptive_renko.py` |
| Doji breakout | XAUUSD M15 | Trade the break of a doji's extremes | `test_0005_0495_doji_trader.py` |

## Deep Dive 1: Engulfing, With and Without a Second Vote

The plain version ([test_0010](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0010_0588_bullish_bearish_engulfing.py)) is stricter than the textbook — the current bar must engulf the previous one *entirely*, shadows included, with a `distance` margin:

```python
dist = float(self.p.distance) * self._point()
bullish = (
    c0_open < c0_close and          # current bar bullish
    c1_open > c1_close and          # previous bar bearish
    c0_high > c1_high + dist and    # highs engulfed too
    c0_close > c1_open + dist and
    c0_open < c1_close - dist and   # lows engulfed too
    c0_low < c1_low - dist
)
```

Its report card over three months of M15: exactly **1 trade, 0 wins**, final value 990,348.20 (-0.97%), Sharpe -8.34. The most famous reversal pattern in the world, implemented to textbook standard, is noise at this frequency in a trending market like gold.

Now add the second vote. [test_0028](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0028_1339_engulfing_rsi.py) keeps the engulfing but requires a *meaningful* bar and an oscillator opinion:

```python
def _bullish_engulfing(self):
    o2, c2 = float(self.data.open[-2]), float(self.data.close[-2])
    o1, c1 = float(self.data.open[-1]), float(self.data.close[-1])
    avg = self._avg_body()                       # rolling mean body (SMA 5)
    mid2 = (o2 + c2) / 2.0
    close_avg = float(self.sma[-2])
    return (
        o2 > c2 and                              # previous bar bearish
        (c1 - o1) > avg and                      # body beats the rolling average
        c1 > o2 and                              # closes past the prior open
        mid2 < close_avg and                     # pattern sits below the SMA
        o1 < c2
    )

# entry: pattern AND regime — previous RSI(11) below 40 for longs, above 60 for shorts
if bull_eng and rsi_1 < 40:
    self.buy(...)
```

Same data, same engine: 27 trades, 10 wins, **37.04% win rate**, final value 996,678.80. Still not profitable — but from 0% to 37% is what a confirmator buys. Push further with *location* (hammer hanging below its SMA) plus RSI(14) in `test_0023_1323_hammer_rsi.py` and the win rate reaches 52.38%. The A/B ladder — pattern, pattern+momentum, pattern+location+momentum — is the real teaching artifact here.

## Deep Dive 2: NR7 — Crabel's Volatility-Contraction Law

Toby Crabel's observation: the day with the narrowest range of the last seven tends to precede range expansion. [test_0037](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0037_nr7_pattern_breakout.py) implements it over 18 years of gold daily bars — detection is a one-liner, the discipline lives in the exits:

```python
out['daily_range'] = out['high'] - out['low']
out['min_range_prev6'] = out['daily_range'].shift(1).rolling(window=lookback - 1).min()
out['nr7'] = (out['daily_range'] < out['min_range_prev6']).astype(float)
out['breakout_up'] = ((out['nr7'].shift(1) > 0.5) &
                      (out['close'] > out['nr7_high'])).astype(float)

self.stop_loss = self.entry_price - self.p.stop_loss_atr * atr      # 2.5 × ATR
self.take_profit = self.entry_price + self.p.take_profit_atr * atr  # 4.0 × ATR
if bars_held >= self.p.time_exit:                                  # 5 bars, then out
    self.pending_order = self.close()
```

The 5-bar time stop is the strategy's soul: NR7 bets on *immediate* expansion, so a squeeze that hasn't delivered within a week is simply wrong. Baseline: 132 trades, 48.48% win rate, final value **1,310,862.61** (+31.09%), Sharpe 0.46 — bought at the price of a 49.46% max drawdown. A 1.6:1 payoff ratio near coin-flip odds is positive expectation; the drawdown column is the cardiologist's opinion. Sibling variants (`test_0038`, `test_0039`) add trend-mean filters and volatility-gated exits for contrast.

## Deep Dive 3: Darvas Boxes — the Dancer's Legacy, Engineered

In 1960, dancer Nicolas Darvas turned roughly $25,000 into $2 million trading boxes from telegraphed quotes while touring the world. [test_0044](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/price_patterns/test_0044_0853_darvasboxes_system.py) ports the MT5 version as a dual-timeframe system — M15 executes, H4 builds boxes — with the indicator publishing a color state and the strategy trading only *transitions*:

```python
if len(self.signal_data) == self._last_signal_len:
    return                                  # dedupe: one look per H4 bar
self._last_signal_len = len(self.signal_data)
c0 = float(self.ind.color[-sb]) if sb else float(self.ind.color[0])
c1 = float(self.ind.color[-(sb + 1)])
buy_open = c1 > 2.0 and c0 < 3.0 and self.p.buy_pos_open    # transition into green
sell_open = c1 < 2.0 and c0 > 1.0 and self.p.sell_pos_open  # transition into red
```

Exits are a fixed bracket — 1,000-point stop, 2,000-point target. On the three-month window the system took 11 trades, **every one of them a short** (buy_count=0), 3 wins against 8 losses, final value 999,221.40. Structure strategies can be picky eaters about regime — that bias is invisible until you backtest. The `_last_signal_len` dedupe is the port's quiet gem: without it, one H4 signal fires four times inside its M15 children.

## The Rest of the Bench

- **Heikin Ashi** (`test_0015`): six lines of recursion smooth candles into color — as a *trigger* it wins 34.14% and loses gently; the lesson is to use color runs as a filter, not a gun.
- **Three Inside + bracket** (`test_0001`): MT5's bracket-order habits (`buy_bracket`, 500/500 points) faithfully translated — entries by pattern, exits by order types, separable concerns.
- **Doji breakout** (`test_0005`): refuses to read the doji as reversal; treats it as a springboard and trades the break of its extremes.
- **Close-price fractals** (`test_0041`, `test_0043`): Williams fractals computed on closes (fewer shadow traps), with a minimum-distance gate that refuses whipsaw markets.
- **Adaptive Renko** (`test_0036`): brick size breathes with ATR — noise below one brick simply ceases to exist.

## Run It Yourself

```bash
# The whole category (44 strategies)
pytest tests/functional/strategies/price_patterns/ -v

# Just the RSI-confirmed engulfing
pytest tests/functional/strategies/price_patterns/test_0028_1339_engulfing_rsi.py -v
```

## Why Study Price Patterns Here

Pattern strategies live and die by details — an extra boolean in the engulfing definition, an RSI threshold moved from 40 to 35, a 1:1 versus 1:2 bracket. That demands reproducible A/B experiments, not impressions. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) gives you 1,152 strategy regression tests with asserted metric baselines: change one condition and the assertions tell you exactly which numbers moved. The pure-Python engine runs 46% faster than the original, the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup for ablation sweeps, and runonce/runnext dual-mode parity guards the engine underneath it all.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/15-patterns-candles.md) and [here](../zh/16-patterns-structure.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
