# Classic Single-Indicator Strategies: Williams %R, Stochastic KD, TRIX, and the Ultimate Oscillator

> Strategy Compendium · No. 17 · Category `multi_indicator` (9 strategies) · 2026-09-02

Open any technical analysis textbook and you meet the same cast: Williams %R, stochastic KD, CCI, TRIX, parabolic SAR… Most were born in the 1970s-80s — no backtesting software, no Python — their authors compressing market observations into one formula on graph paper and a calculator. The most legendary is Larry Williams: in the 1987 Robbins World Cup Trading Championship he turned $10,000 into over a million dollars, an 11,000%+ year; his daughter (later the actress Michelle Williams) won the same contest at 16. Williams %R and this article's Ultimate Oscillator both come from his hand.

"Textbook indicators" get sneered at as outdated, but that is precisely why they are the best place to learn quantitative trading: transparent formulas, minimal parameters, logic you can say in one sentence — and when something breaks, you know exactly what to suspect. The 9 backtests in `tests/functional/strategies/multi_indicator/` run 7 of them on the same ORCL daily data (2010-2014, $100,000 cash, 0.1% commission, 10 shares per trade) — a natural controlled experiment: same data, same cash, different indicators.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Williams %R | ORCL daily | Buy %R turning up from below −80, exit above −20 | `test_102_williams_r_strategy.py` |
| Stochastic KD | ORCL daily | K crosses above D with K<20 to buy; K crosses below D with K>80 to exit | `test_103_stochastic_strategy.py` |
| CCI | ORCL daily | Enter on CCI crossing up through −100, exit falling back below +100 | `test_104_cci_strategy.py` |
| Parabolic SAR | ORCL daily | Buy price crossing above SAR, exit crossing below | `test_106_parabolic_sar_strategy.py` |
| TRIX | ORCL daily | Triple-EMA rate of change crossing zero | `test_107_trix_strategy.py` |
| Ultimate Oscillator | ORCL daily | 7/14/28 blended momentum; buy <30, exit >70 | `test_109_ultimate_oscillator_strategy.py` |
| Aberration (futures) | Rebar RB889 minute bars | 200-period Bollinger breakout, exit at mid band | `test_12_abberation_strategy.py` |
| Aberration (stock) | SPDB daily 2000-2022 | Same Bollinger-breakout idea on an A-share | `test_25_abbration_strategy.py` |
| UDVD | ORCL daily | Sign of the 3-bar SMA of candle bodies | `test_95_udvd_strategy.py` |

## Deep Dive 1: Ultimate Oscillator — Larry Williams' Surgery on "Divergence"

Single-period oscillators share one disease: 7 bars react fast but noisily, 28 bars reliably but late. Williams' 1985 answer in *Technical Analysis of Stocks & Commodities* was surgical — **blend three periods into one indicator**, weighting the shortest most heavily:

```python
params = dict(
    stake=10,
    p1=7,
    p2=14,
    p3=28,
    oversold=30,
    overbought=70,
)

def __init__(self):
    self.uo = bt.indicators.UltimateOscillator(
        self.data, p1=self.p.p1, p2=self.p.p2, p3=self.p.p3
    )

def next(self):
    self.bar_num += 1
    if self.order:
        return

    if not self.position:
        # Entry: UO in oversold territory
        if self.uo[0] < self.p.oversold:
            self.order = self.buy(size=self.p.stake)
    else:
        # Exit: UO in overbought territory
        if self.uo[0] > self.p.overbought:
            self.order = self.close()
```

That is the entirety of [test_109_ultimate_oscillator_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator/test_109_ultimate_oscillator_strategy.py) — under 20 lines. Note the `bar_num` assertion of **1,229**, some 20-26 bars fewer than its siblings: the UO needs full history for 28-period buying pressure and true range, so a longer warm-up is the inherent tax of multi-period blending.

It posts the brightest report card of the textbook group: final value 100,199.75, Sharpe 2.2256, max drawdown just 6.37%. Against SAR's Sharpe 0.158 and 14.47% drawdown, the multi-period weighting genuinely earns its noise reduction — though the 0.04% annualized return also reminds you that an overbought/oversold system without a trend filter wins only "respectably."

## Deep Dive 2: Stochastic KD — Adding a Location Gate to Crossovers

George Lane's 1950s stochastic observes where the close sits inside its recent range: closing at the highs is strength, at the lows weakness. But raw K/D crossovers fire far too often, and the textbook patch is to **buy only in the oversold zone, sell only in the overbought zone**. [test_103_stochastic_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator/test_103_stochastic_strategy.py) implements the rule faithfully:

```python
def __init__(self):
    self.stoch = bt.indicators.Stochastic(
        self.data,
        period=self.p.period,
        period_dfast=self.p.period_dfast,
    )
    self.crossover = bt.indicators.CrossOver(self.stoch.percK, self.stoch.percD)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    if not self.position:
        # K crosses above D and in oversold zone
        if self.crossover[0] > 0 and self.stoch.percK[0] < self.p.oversold:
            self.order = self.buy(size=self.p.stake)
    else:
        # K crosses below D and in overbought zone
        if self.crossover[0] < 0 and self.stoch.percK[0] > self.p.overbought:
            self.order = self.close()
```

Parameters are the classic 14/3 with 20/80 thresholds. The double gate — crossover AND location — compresses 1,239 bars of trading into a handful of high-quality windows: final value 100,219.02, Sharpe 0.692, max drawdown 8.50%. The engineering lesson is `CrossOver`: it pushes the boundary arithmetic (yesterday ≤, today >) down into the indicator layer, so the strategy reads a single sign — better readability, fewer bugs than hand-rolled comparisons.

## Deep Dive 3: Parabolic SAR — Wilder's One-Book Legacy

J. Welles Wilder Jr.'s 1978 *New Concepts in Technical Trading Systems* is probably the single most productive book in technical analysis history: RSI, ATR, ADX, and parabolic SAR all came from it. SAR's twist is the **acceleration factor** — each new trend extreme ratchets the stop tighter, faster, like a parabola, until profit is squeezed out. [test_106_parabolic_sar_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator/test_106_parabolic_sar_strategy.py):

```python
params = dict(
    stake=10,
    af=0.02,
    afmax=0.2,
)

def __init__(self):
    self.sar = bt.indicators.ParabolicSAR(
        self.data, af=self.p.af, afmax=self.p.afmax
    )
    self.crossover = bt.indicators.CrossOver(self.data.close, self.sar)

def next(self):
    self.bar_num += 1
    if self.order:
        return

    if not self.position:
        if self.crossover[0] > 0:
            self.order = self.buy(size=self.p.stake)
    else:
        if self.crossover[0] < 0:
            self.order = self.close()
```

af starting at 0.02 and capped at 0.2 are Wilder's original numbers. SAR is elegant — the stop is the signal — but its weakness is equally famous: getting slapped back and forth in range-bound markets. The backtest is honest about it: final value 100,044.47, Sharpe 0.158, max drawdown 14.47% over 1,255 bars — a whole lot of work for nothing. The module's own docstring says it plainly: SAR is strongest in trending markets; add a filter for chop.

## The Rest of the Bench

- **Williams %R** (`test_102`): Larry Williams, 1973 — same "where does the close sit in the range" idea as KD, traded as a one-sided swing: final value 100,102.86, Sharpe 0.479.
- **CCI** (`test_104`): Donald Lambert's 1980 commodity-cycle oscillator — price deviation from its typical price over mean absolute deviation, traded at ±100 crossings.
- **TRIX** (`test_107`): Jack Hutson's triple-EMA rate of change — three low-pass filters deep, zero-line crossings; the bluntest and most noise-resistant momentum indicator in the batch.
- **The Aberration twins** (`test_12` / `test_25`): blue-blooded long-term channel systems — 200-period Bollinger bands, 2 standard deviations, long the upper break, short the lower, exit at the midline. The futures version on rebar minute bars: 94 trades, Sharpe 0.55, final value 1,079,820 from 1,000,000. The stock version on 22 years of SPDB: 423,916.71 from 100,000 — with a 46.5% max drawdown. Same idea transplanted across markets, wildly different risk portraits.
- **UDVD** (`test_95`): the simplest seat — long when the 3-bar SMA of candle bodies is positive, flat when negative. Final value 99,939.44, the group's only loser: "simpler" does not mean "better."

## Run It Yourself

```bash
# The whole category (9 strategies, runonce/runnext parity asserted automatically)
pytest tests/functional/strategies/multi_indicator/ -v

# Just the Ultimate Oscillator
pytest tests/functional/strategies/multi_indicator/test_109_ultimate_oscillator_strategy.py -v
```

## Why Study Classic Indicators Here

Classic indicators, with few parameters and transparent formulas, are perfect for **reproducible controlled experiments**: same data, same cash settings, nine indicators, one leaderboard. That is [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)'s home turf — the pure Python engine runs 46% faster than the original, finishing all 1,152 strategy regression tests in minutes; the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup, turning parameter sweeps from overnight jobs into coffee breaks. Every strategy's Sharpe, drawdown, and final value is pinned by assertions, and runonce/runnext dual-mode parity ensures you are comparing indicators — not the engine's numerical drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/30-classic-indicators.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
