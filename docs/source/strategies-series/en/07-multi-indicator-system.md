# Multi-Indicator Systems: Voting, Scoring, and the MQL5 Wizard Way

> Strategy Compendium · No. 07 · Category `multi_indicator_system` (29 strategies) · 2026-09-02

A single indicator is a dictator: when MACD says buy, you buy, and nobody objects. Multi-indicator systems try to build a parliament instead — trend, momentum, and channels each get a seat. But parliaments need rules of order, and this category contains exactly two constitutions. **Voting** (AND logic): every indicator must agree before a position opens; one veto kills the motion, at the cost of very few signals. **Scoring** (weighted sum): each indicator casts ±100 points, the weighted total crossing a threshold triggers action — flexible, but it quietly introduces weights as a fresh set of tuning knobs.

The MQL5 community turned this methodology into an industry — MetaQuotes' official MQL5 Wizard assembles signal modules into expert advisors like Lego bricks, and this repository hosts a batch of those ports. This article walks through the 29 strategies in `tests/functional/strategies/multi_indicator_system/`. Most run on XAUUSD M15 (2025-12-03 to 2026-03-10); the Kaufman efficiency-ratio system uses daily bars.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Kaufman Efficiency Ratio | XAUUSD daily 2008-2025 | Require ER > 0.3 before trusting KAMA breakouts | `test_0001_0092_kaufman_efficiency_ratio.py` |
| Three Indicators | XAUUSD M15 | MACD slope + Stochastic zone + RSI state, three aligned votes | `test_0008_three_indicators.py` |
| Camel CCI MACD | XAUUSD M15 | CCI + MACD + EMA channel, triple confluence entry | `test_0014_steve_cartwright_trader_camel_cci_macd.py` |
| MACD Stochastic | XAUUSD M15 | MACD cross + Stochastic confirm + session filter | `test_0016_macd_stochastic.py` |
| MQL5 Wizard MACD PSAR | XAUUSD M15 | Scoring system fusing MACD momentum with PSAR trend | `test_0020_mql5_wizard_macd_parabolic_sar.py` |
| SAR + ADX + SMA100 | XAUUSD M15 | SAR for direction, ADX > 20 for strength, SMA for trend | `test_0027_sar_adx_sma.py` |
| ICT Concepts EA | XAUUSD M15 | Higher-timeframe bias + liquidity sweeps + MSS/FVG structure | `test_0006_ict_concepts_ea.py` |
| Universum 3.0 | XAUUSD M15 | DeMarker bias + martingale position sizing | `test_0022_universum_3_0.py` |
| Perceptron | XAUUSD M15 | Five indicators fed into a weighted perceptron score | `test_0028_perceptron.py` |
| Binary Wave | XAUUSD M15 | Seven indicators compressed into one smoothed wave | `test_0029_binary_wave.py` |

## Deep Dive 1: Camel CCI MACD — the Unanimous-Vote Template

Steve Cartwright's Camel system ([test_0014](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator_system/test_0014_steve_cartwright_trader_camel_cci_macd.py)) is the textbook AND-vote parliament. Three indicator families each govern one aspect: CCI(30) for momentum extremes, MACD(12, 26, 9) for momentum direction, and the EMA "camel" channel for price location. Long entry requires all four gates:

```python
self.camel_high = bt.indicators.ExponentialMovingAverage(
    self.data.high, period=self.p.ma_period_ma_high)     # EMA(40) of highs
self.camel_low = bt.indicators.ExponentialMovingAverage(
    self.data.low, period=self.p.ma_period_ma_low)       # EMA(5) of lows
self.macd = bt.indicators.MACD(self.data.close,
    period_me1=12, period_me2=26, period_signal=9)
self.cci = bt.indicators.CCI(self.data, period=self.p.ma_period_cci)  # 30

if cci_prev > 100 and macd_main_prev > 0 \
        and macd_main_prev > macd_signal_prev \
        and close_prev > camel_high_prev:                # all four green: go long
    self.order = self.buy(size=self.p.lot)

if cci_prev < -100 and macd_main_prev < 0 \
        and macd_main_prev < macd_signal_prev \
        and close_prev < camel_low_prev:                 # short is the exact mirror
    self.order = self.sell(size=self.p.lot)
```

Exits also demand "consensus breakdown": while long, MACD main falling back under its signal, or CCI retreating inside 100, or a 40-pip take-profit touch — any one closes the position. Two engineering details reward close reading: every comparison uses `[-1]` (the **previous** bar's values), eliminating same-bar self-reference look-ahead; and the camel bands are deliberately asymmetric (40 vs 5), so the upper band is slow and the lower fast — longs get more room than shorts. Over three months and 6,071 M15 bars the system traded 687 times, 352 wins against 335 losses, ending at 1,038,763.00 on a 1,000,000 account (+3.88%). High-frequency micro-profit trading: the edge is ground out by win rate, one small trade at a time.

## Deep Dive 2: MQL5 Wizard MACD + Parabolic SAR — a Scoring Lesson

The Wizard's standard play is module voting: each module outputs ±100 times its weight, and the total crossing a line opens a trade. This port ([test_0020](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/multi_indicator_system/test_0020_mql5_wizard_macd_parabolic_sar.py)) assigns MACD the momentum seat and PSAR the trend seat:

```python
def _macd_score(self):
    if self.macd.macd[0] > self.macd.signal[0]:
        return 100.0 * float(self.p.signal_macd_weight)   # weight 0.9
    if self.macd.macd[0] < self.macd.signal[0]:
        return -100.0 * float(self.p.signal_macd_weight)
    return 0.0

def _sar_score(self):
    if self.data.close[0] > self.sar[0]:
        return 100.0 * float(self.p.signal_sar_weight)    # weight 0.1
    if self.data.close[0] < self.sar[0]:
        return -100.0 * float(self.p.signal_sar_weight)
    return 0.0

def _signal_value(self):
    return self._macd_score() + self._sar_score()         # range [-100, +100]
```

With `signal_threshold_open=20`, a total of +20 or more goes long and −20 or less goes short; exits are any of fixed 50/115-point stop/target, or the score swinging to the full opposite 100 (`signal_threshold_close`) — both indicators in complete revolt. Now look harder at this "democracy": MACD's vote is worth 90 points, PSAR's only 10, and the threshold is 20 — **MACD alone can open the door; PSAR is a ceremonial voter.** Scoring looks like it smooths disagreement, but the weights decide who actually dictates. The backtest delivers a sharp verdict: 3,077 trades, 48.6% win rate, profit factor 0.915, final value 910,005.00 (−9.0%) — steady losses even on zero-commission M15 data. In high-frequency churn, a faint signal edge cannot survive even a sliver of friction. That losing baseline is asserted to the cent in the test file, which makes it a superb control group for studying how combination methodologies fail.

Put the two deep dives side by side and a third lesson appears: voting and scoring both add parameters as they add indicators — the Camel system carries four periods plus a take-profit distance, the Wizard system six weights and thresholds, and the bench below goes up to seven indicators (Binary Wave) or a five-input perceptron. Every extra knob buys more power to fit history and quietly spends out-of-sample reliability. That is precisely what a regression library is for: **pin every combination's raw score into a baseline first, and force any "optimization" to compete head-to-head on identical data.**

## The Rest of the Bench

- **Kaufman Efficiency Ratio** (`test_0001`): ER = net displacement over path length; above 0.3 the market is worth following, and only then does the KAMA adaptive-moving-average breakout get a hearing — filter "is there a trend" before asking "which way."
- **SAR + ADX + SMA100** (`test_0027`): direction (which side of SAR) × strength (ADX > 20) × trend (above/below SMA100) — the cleanest example of dividing labor among indicators.
- **Perceptron** (`test_0028`): MA cross, RSI, CCI, momentum, and Awesome Oscillator weighted into one perceptron emitting a directional bias — scoring reduced to its neural-network minimal form.
- **Binary Wave** (`test_0029`): MA/MACD/OSMA/CCI/momentum-ratio/RSI/ADX weighted into a single smoothed wave crossing zero — parliament compressed into one curve.
- **Universum 3.0** (`test_0022`): DeMarker above/below 0.5 for direction, then martingale doubling after losses until a circuit-breaker — a cautionary tale of money management substituting for a missing edge.

## Run It Yourself

```bash
# The whole category (29 strategies)
pytest tests/functional/strategies/multi_indicator_system/ -v

# Just Camel CCI MACD
pytest tests/functional/strategies/multi_indicator_system/test_0014_steve_cartwright_trader_camel_cci_macd.py -v
```

## Why Study Multi-Indicator Systems Here

No category has a higher parameter density — seven or eight knobs per strategy is routine, and combinatorial sweeps quickly reach tens of thousands of backtests. That demands **massive, reproducible** infrastructure, which is [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)'s sweet spot: 46% faster than the original in pure Python (all 1,152 strategy regression tests finish in minutes), a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) that turns "is the seventh indicator worth it?" from a hunch into a computable question, runonce/runnext dual-mode parity so vectorized and event-driven paths police each other, and asserted metric baselines so you optimize the strategy — not the engine's numerical drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/20-multi-indicator-system.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
