# Volume Systems: VWMA Slopes and Ergodic Tick Volume — Price-Volume Experiments

> Strategy Compendium · No. 19 · Category `volume_system` (7 strategies) · 2026-09-02

"Volume precedes price" — the old Wall Street saw is the starting point of all volume analysis: price can lie, volume is harder to fake, and the direction of expanding volume often leads the direction of price. But in spot FX and gold the aphorism needs a patch: there is **no central exchange**, hence no unified traded volume. What MT5 offers instead is tick volume — the number of quote updates inside each bar. Empirical research has long supported an interesting conclusion: tick volume correlates strongly enough with real volume to play the role. So the question becomes — what happens when you feed tick volume into classic indicators?

The 7 strategies in `tests/functional/strategies/volume_system/` answer it. All are ports of real MT5 EAs sharing one precise dual-timeframe architecture: **M15 bars execute orders, resampled H4/H6/H8 bars compute signals**, on XAUUSD from 2025-12-03 to 2026-03-10 (~6,129 M15 bars, $1,000,000 initial, zero commission, 100x multiplier).

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Exp_Volume_Weighted_MACandle | XAUUSD M15 exec / H4 signal | Synthetic volume-weighted candles; trade the color flip | `test_0001_volume_weighted_macandle.py` |
| Exp_Volume_Weighted_MA_Digit_System | XAUUSD M15 / H4 | Rounded VWMA high/low channel with color-code breaks | `test_0002_volume_weighted_ma_digit_system.py` |
| Exp_Volume_Weighted_MA_StDev | XAUUSD M15 / H4 | VWMA change over its own std dev, 1.5σ/2.5σ tiered signals | `test_0003_volume_weighted_ma_stdev.py` |
| Exp_Volume_Weighted_MA | XAUUSD M15 / H4 | VWMA slope turn with fixed-point SL/TP | `test_0004_volume_weighted_ma.py` |
| Exp_Ergodic_Ticks_Volume_OSMA | XAUUSD M15 / H8 | Double-smoothed TVI read through OSMA-histogram turns | `test_0005_ergodic_ticks_volume_osma.py` |
| Exp_Ergodic_Ticks_Volume_Indicator | XAUUSD M15 / H6 | Ergodic TVI crossed with its signal line | `test_0006_ergodic_ticks_volume_indicator.py` |
| Exp_XPVT | XAUUSD M15 / H4 | Price-Volume Trend cumulative line vs its EMA | `test_0007_xpvt.py` |

## Deep Dive 1: VWMA Slope — Giving Volume a Vote

A plain moving average treats every bar equally; a VWMA lets **high-volume bars speak louder**: `Σ(price × volume) / Σ(volume)`. A high-volume breakout leaves a deep mark on the VWMA; low-volume chop barely moves it. That is exactly the mechanism [test_0004_volume_weighted_ma.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volume_system/test_0004_volume_weighted_ma.py) uses to catch turning points — and the signal is a **slope flip**, not a price crossover:

```python
self.indicator = bt.indicators.VolumeWeightedMAIndicator(self.signal_data, length=self.p.length, ipc=self.p.ipc, use_tick_volume=self.p.use_tick_volume)
```

```python
v0 = self._val(self.indicator.vwma, signal_bar)
v1 = self._val(self.indicator.vwma, signal_bar + 1)
v2 = self._val(self.indicator.vwma, signal_bar + 2)
if v1 < v2:
    if self.p.buy_pos_open and v0 > v1:
        buy_open = True
    if self.p.sell_pos_close:
        sell_close = True
if v1 > v2:
    if self.p.sell_pos_open and v0 < v1:
        sell_open = True
    if self.p.buy_pos_close:
        buy_close = True
```

Three H4 VWMA values (`length=12`, tick-volume weighted) must trace a V — falling, then rising — to open long; an inverted V opens short. Positions carry a 1,000-point stop and a 2,000-point target enforced on the M15 execution feed. Note the `use_tick_volume=True` switch: MT5 exports carry both tick and real volume columns, and spot gold's real volume is perennially zero — this whole family defaults to the tick column, and mixing up the two is the most common migration bug. The backtest produced 54 trades at a 42.59% win rate, profit factor 1.154, final value 1,000,646.80 — another low-win-rate, payoff-ratio specimen: slope-turn signals lag by construction, so entries are not cheap; the edge is that once an H4 trend does form, the 2,000-point target dwarfs the 1,000-point stop. Engineering note: the `_last_signal_len` latch evaluates each signal bar exactly once — without it in a dual-timeframe setup, one H4 bar gets consumed 16 times by M15 bars and the signals degenerate into noise.

## Deep Dive 2: Ergodic TVI — Blau's Multiple-Smoothing Philosophy

In the 1990s William Blau (*Momentum, Direction, and Divergence*) systematized the "Ergodic" family: pass any raw quantity through **double exponential smoothing** before building an oscillator. The TVI (Tick Volume Index) is his recipe applied to tick volume, and [test_0006_ergodic_ticks_volume_indicator.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volume_system/test_0006_ergodic_ticks_volume_indicator.py) lays out the whole pipeline:

```python
up_ticks = (vol + (frame['close'].astype(float) - frame['open'].astype(float)) / point) / 2.0
down_ticks = vol - up_ticks

ema_up = apply_ma(up_ticks, xlength1, xma_method)
ema_down = apply_ma(down_ticks, xlength1, xma_method)
dema_up = apply_ma(ema_up, xlength2, xma_method)
dema_down = apply_ma(ema_down, xlength2, xma_method)

denom = (dema_up + dema_down).replace(0.0, np.nan)
tvi_calculate = 100.0 * (dema_up - dema_down) / denom
tvi = apply_ma(tvi_calculate, xlength3, xma_method)
ema_tvi = apply_ma(tvi, xlength4, xma_method)
ergodic_tvi = apply_ma(ema_tvi, xlength5, xma_method)
ergodic_signal = apply_ma(ergodic_tvi, xlength6, xma_method)
```

The first step is the elegant one: a bullish bar's (close>open) ticks are all credited to the bulls, bearish bars to the bears, the count split in two and each side double-smoothed (`xlength1=xlength2=12`) — **tick volume is promoted into a bull-vs-bear force ratio**. TVI = 100×(up−down)/(up+down), then four more smoothing passes produce the ergodic line and its signal; crossovers trade. The six `xlength` knobs map to the six pipeline stages, with `xlength3=1` meaning TVI itself gets no extra smoothing — Blau's own trade-off point on the "deeper smoothing, duller signal" curve. Signal sparsity is the price: the whole H6 window holds only 236 bars and produced 14 trades (8 wins, 6 losses), profit factor 2.04, final value 1,005,203.90, max drawdown 0.34%. Few signals, clean curve.

## The Rest of the Bench

- **VWMA Candle** (`test_0001`): uses VWMA values as synthetic open/close to paint candles; flip the color, reverse the position — the pattern-reading version of the same idea.
- **VWMA Digit System** (`test_0002`): rounds VWMA highs/lows into a channel; closes beyond the rails light up color codes processed as breakout signals.
- **VWMA StDev** (`test_0003`): VWMA's bar-to-bar change divided by its rolling standard deviation — momentum as a volatility-normalized z-score with 1.5σ/2.5σ tiers.
- **Ergodic OSMA** (`test_0005`): the same TVI pipeline as Deep Dive 2 but signals on OSMA-histogram turns on H8 — a controlled comparison of "crossover" vs "inflection" signal extractors.
- **XPVT** (`test_0007`): the Price-Volume Trend ledger — each bar adds `volume × price change rate`, so a 1% rise on heavy volume moves the line more than a 5% rise on thin volume; the signal line is a 5-bar EMA of PVT. The category's best report card: 49 trades, 48.98% win rate, profit factor 3.26, final value 1,015,722.30 (+1.57%), max drawdown 0.19%. Three months of gold on zero costs is a baseline, not gospel — but the potential of a price-volume composite line as a direction filter is on full display.

## Run It Yourself

```bash
# The whole category (7 strategies, runonce=True, asserting migration-time baselines)
pytest tests/functional/strategies/volume_system/ -v

# Just XPVT
pytest tests/functional/strategies/volume_system/test_0007_xpvt.py -v
```

## Why Study Volume Systems Here

Price-volume strategies depend inherently on dual data streams (price + tick volume) and multi-timeframe architectures (M15 execution, H4+ signals), which demand extreme **data-pipeline precision** from a backtesting engine — resampling boundaries, bar-timestamp offsets, signal alignment off by one bar and everything distorts. That is precisely [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)'s strength: the pure Python engine runs 46% faster than the original, and all 1,152 strategy regression tests pin every pipeline's win rate, profit factor, drawdown, and SQN as asserted baselines. The C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup, shrinking multi-timeframe parameter scans from overnight jobs to coffee breaks, while runonce/runnext dual-mode parity guarantees both code paths compute the same VWMA.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/32-volume-systems.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
