# Volatility Channels: Keltner, SuperTrend, and the Chandelier Exit — ATR's Hundred Uses

> Strategy Compendium · No. 16 · Category `volatility` (9 strategies) · 2026-09-02

If technical indicators had an award for versatility, ATR (Average True Range) would win it. ATR asks nothing about direction — it only measures how wide the market swung today. The 9 strategies in `tests/functional/strategies/volatility/` are nearly all built on one idea: **give price a channel that breathes**. When volatility expands, the channel widens and false signals thin out; when it contracts, the bands hug price again. The upper band becomes dynamic resistance, the lower dynamic support, and price's position between them defines trend and exit.

The lineage is star-studded: Chester Keltner drew fixed-percentage channels in the 1960s; Linda Raschke swapped in ATR bands in the 1980s to create the modern Keltner channel; SuperTrend collapsed the channel into a single flipping line; and Chuck LeBeau's "chandelier exit" hangs a trailing stop N×ATR below the highest high — named for a light fixture dropping from the ceiling. This article dives into those three sources.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Keltner multi-contract | Rebar futures, multi-contract | Channel breakout both ways + auto rollover to the dominant contract | `test_08_kelter_strategy.py` |
| MACD + ATR | YHOO daily 2005-2014 | MACD cross entry, ATR trailing stop protection | `test_36_macd_atr_strategy.py` |
| Keltner (backhacker) | ORCL daily 2010-2014 | EMA mid ± 2×ATR, upper-band entry, mid-band exit | `test_70_keltner_channel_strategy.py` |
| SuperTrend | ORCL daily 2010-2014 | ATR(10)×3 dynamic line, trade the flip | `test_81_supertrend_strategy.py` |
| SuperTrend indicator | ORCL daily 2010-2014 | Same idea, alternate parameterization | `test_88_supertrend_indicator_strategy.py` |
| Adaptive SuperTrend | ORCL daily 2010-2014 | Multiplier self-adjusts with ATR | `test_89_adaptive_supertrend_strategy.py` |
| Keltner channel | ORCL daily 2010-2014 | Detailed companion implementation (same baseline as test_70) | `test_108_keltner_channel_strategy.py` |
| Chandelier exit | ORCL daily 2010-2014 | SMA8/15 cross + 22-day high − 3×ATR stop | `test_111_chandelier_exit_strategy.py` |
| SuperTrend + RSI | ORCL daily 2010-2014 | Enter only above the line AND with RSI confirmation | `test_114_supertrend_rsi_strategy.py` |

## Deep Dive 1: SuperTrend — A Channel That Flips

SuperTrend is the minimal form of a channel: draw no upper and lower bands, keep only **the one line on the trend side** — below price in an uptrend (support at ATR×multiplier), above it in a downtrend (resistance). When price crosses, the line jumps to the other side and the trend is declared reversed. The trading logic of [test_81_supertrend_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_81_supertrend_strategy.py) fits in one glance:

```python
params = dict(
    stake=10,
    period=10,          # ATR period
    multiplier=3.0,     # ATR multiple
)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    # Buy when trend turns up
    if not self.position:
        if self.supertrend.direction[0] == 1 and self.supertrend.direction[-1] == -1:
            self.order = self.buy(size=self.p.stake)
    else:
        # Sell when trend turns down
        if self.supertrend.direction[0] == -1:
            self.order = self.sell(size=self.p.stake)
```

Buy the bar where direction flips from −1 to +1; sell it all when it flips back. Entry and exit are the same event — naturally symmetric, no separate stop rule needed, because the stop *is* the SuperTrend line. The baseline is honest: ORCL 2010-2014, $100,000 initial, 0.1% commission, 1,247 bars, final value 99,999.23 — flat-to-slightly-negative, Sharpe −0.0038, max drawdown 11.22%. A naked SuperTrend gets whipsawed on a chop-heavy stock, which is exactly the gap `test_114`'s RSI filter fills later.

## Deep Dive 2: Keltner Channel — Bollinger Bands with ATR Inside

The one-sentence difference from Bollinger Bands in [test_108_keltner_channel_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_108_keltner_channel_strategy.py): **Bollinger uses the standard deviation of closes; Keltner uses ATR.** Standard deviation sees only the close-to-close distribution and can "pinch" misleadingly in quiet markets; ATR counts highs, lows, and gaps, so the band width tracks true volatility. The channel is an EMA midline with bands offset by 2×ATR:

```python
params = dict(
    stake=10,
    period=20,      # EMA period
    atr_mult=2.0,   # ATR multiplier
)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    if not self.position:
        # close breaks the upper band: bullish momentum confirmed
        if self.data.close[0] > self.kc.top[0]:
            self.order = self.buy(size=self.p.stake)
    else:
        # falls back to the mid line (EMA): trend fading, exit
        if self.data.close[0] < self.kc.mid[0]:
            self.order = self.close()
```

Note the asymmetry: entry demands a break of the *upper* band (only strong moves count), but exit only requires falling back to the *middle* — room for the trade to breathe without waiting for a full lower-band breach. Baseline: ORCL 2010-2014, 1,238 bars, final value 100,039.51, Sharpe 0.2796, max drawdown just 5.50% — one of the best drawdown profiles in the category. `test_70` implements the identical idea with a different parameterization and asserts the exact same numbers (100,039.51 / 0.2796), forming a tidy "same rules, two implementations, mutual confirmation" pair.

## Deep Dive 3: Chandelier Exit — the Stop That Hangs from the Ceiling

Chuck LeBeau's chandelier exit generates no entries; it answers one question: **when does a trend position go back to the market?** The answer: a trailing stop at the highest high since entry minus N×ATR, hanging from the ceiling like its namesake, never descending. [test_111_chandelier_exit_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility/test_111_chandelier_exit_strategy.py) welds it onto a moving-average cross:

```python
params = dict(
    stake=10,
    sma_fast=8,     # fast MA
    sma_slow=15,    # slow MA
    ce_period=22,   # chandelier lookback
    ce_mult=3,      # ATR multiplier
)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    if not self.position:
        # SMA golden cross AND price above Chandelier Short
        if self.sma_fast[0] > self.sma_slow[0] and self.data.close[0] > self.ce.short[0]:
            self.order = self.buy(size=self.p.stake)
    else:
        # SMA death cross AND price below Chandelier Long
        if self.sma_fast[0] < self.sma_slow[0] and self.data.close[0] < self.ce.long[0]:
            self.order = self.close()
```

Entry needs the golden cross AND price above the short chandelier line (healthy volatility structure); exit needs the death cross AND price below the long line — timing and volatility protection must deteriorate together. Baseline: 1,235 bars, final value 100,018.36, Sharpe 0.1430, max drawdown 8.41%. A 22-day lookback with 3×ATR is exactly the magnitude LeBeau recommended — the source code *is* the literature.

## The Rest of the Bench

- **SuperTrend + RSI** (`test_114`): one momentum filter transforms the naked SuperTrend — final value 100,085.04, Sharpe 0.8988, the category's best. One filter was worth that much.
- **SuperTrend indicator / Adaptive** (`test_88/89`): two variants of the same idea, final values 99,977.89 and 99,936.86 — a self-adjusting multiplier did not automatically help.
- **Keltner multi-contract** (`test_08`): channel breakout on Chinese rebar futures with automatic rollover to the dominant contract — channel thinking meets real contract-expiry plumbing.
- **MACD + ATR** (`test_36`): 46 trades on YHOO (17 wins, 28 losses); contrarian MACD entries protected by an `atr * atrdist` trailing stop — the stop engineering outshines the signal.

## Run It Yourself

```bash
# The whole category (9 strategies, each asserted in runonce AND runnext modes)
pytest tests/functional/strategies/volatility/ -v

# Just SuperTrend
pytest tests/functional/strategies/volatility/test_81_supertrend_strategy.py -v

# Just the Chandelier Exit
pytest tests/functional/strategies/volatility/test_111_chandelier_exit_strategy.py -v
```

All 9 tests here are parametrized with `@pytest.mark.parametrize("runonce", [True, False])` — vectorized and event-driven engines each replay every backtest and must agree digit-for-digit, so a single indexing slip in the ATR rolling window or the channel carry cannot hide.

## Why Study Volatility Channels Here

Channel strategies are the best touchstone for a backtesting engine: rolling ATR windows, recursive band carries, flip-point boundary logic — everywhere the vectorized and event-driven paths can disagree. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) bets heavily on exactly that: runonce/runnext dual-mode parity plus per-strategy asserted baselines across 1,152 strategy regression tests — change the multiplier from 3.0 to 2.5 and the curve's move is immediately visible against a pinned baseline. The pure Python engine is 46% faster than the original; with the C++ backend (`pip install back-trader-cpp`) and its median 128x speedup, a two-dimensional grid of ATR period × multiplier sweeps in minutes.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/29-volatility-channels.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
