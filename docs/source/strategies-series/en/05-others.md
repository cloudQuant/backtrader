# Gaps, Calendars, and Kelly: Where the "Miscellaneous" Drawer Keeps the Good Stuff

> Strategy Compendium · No. 05 · Category `others` (69 strategies) · 2026-09-02

Erase every bar from a price chart and keep only the calendar — Monday to Friday, start of month, end of quarter, January — and a surprising share of "market behavior" turns out to be calendar-shaped. Academia has cataloged these anomalies since the 1970s: weekend effects, turn-of-month, the January effect. Others hide in the cracks between bars: the nearly invisible gap between yesterday's close and today's open. Folk wisdom says "gaps always get filled," but real gaps have three fates — continuation, reversal, and neglect — and each fate has a testable strategy.

A second strand asks a stranger question: what if *position size itself* is the strategy? In 1956 Bell Labs' John Kelly published an information-theory answer to "how much should a gambler with an edge bet?"; Ed Thorp carried it from blackjack to the first quantitative hedge fund. Meanwhile hydrologist Harold Hurst, studying 800 years of Nile levels, found the river had memory — a yardstick Mandelbrot later moved to markets. The 69 backtests in `tests/functional/strategies/others/` hold all of it. Single-asset tests run on XAUUSD daily bars, 2008-2025.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Gap N Go Fade | XAUUSD daily, 2008-2025 | Fade the strong gap-up after a 50-day low; hold 2 days | `test_0001_gap_n_go_fade_from_50_day_low.py` |
| Gap Down | XAUUSD daily | Buy gaps down beyond -1%; hold 5 days | `test_0040_gap_down.py` |
| Unfilled gap | XAUUSD daily | Cluster of open gap-ups + fresh 30-day high | `test_0030_unfilled_gap.py` |
| Overnight/Intraday | XAUUSD daily | Hold when the 20-day mean overnight return > 0 | `test_0037_overnight_intraday.py` |
| Monday drop bounce | XAUUSD daily | Buy a >2% Monday drop after 3 down days | `test_0002_monday_drop_bounce.py` |
| Day-of-month timing | XAUUSD + BIL daily | Month-end MA200 vote with seasonal multipliers | `test_0026_day_of_month_timing.py` |
| January effect | IWM/IVV/IWD daily | Hold last year's loser through January | `test_0049_january_effect_strategy.py` |
| Kelly / Optimal F | GLD daily, 2008-2025 | Rolling Kelly fraction, halved and capped | `test_0052_kelly_optimal_f_strategy.py` |
| Hurst exponent | GLD daily | H>0.55 → trend rules; H<0.45 → RSI reversal | `test_0056_hurst_exponent_strategy.py` |
| Markowitz (Sharpe proxy) | XAUUSD daily | Rolling 120-day annualized Sharpe as gate | `test_0046_markowitz_optimization.py` |
| Turbulence index | 5-asset daily | Mahalanobis distance → three fixed allocations | `test_0060_turbulence_index_strategy.py` |

## Deep Dive 1: Gap N Go Fade — Fading the Relief Rally

Intuition says that after a 50-day low, a strong gap-up is the textbook bottom reversal. [test_0001](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0001_gap_n_go_fade_from_50_day_low.py) bets the opposite: a gap at the end of a decline is more likely a one-time emotional release — and then the decline continues. The setup is four AND-ed conditions:

```python
out['prior_day_new_low'] = out['new_50d_low'].shift(1).fillna(0.0)   # yesterday: 50-day low
out['gap_up_abs'] = out['open'] - out['prev_close']
pct_gap_trigger = out['gap_up_abs'] > (out['prev_close'] * gap_threshold_pct)  # 0.3%
atr_gap_trigger = out['gap_up_abs'] > (out['atr'] * gap_atr_multiple)          # 0.5 × ATR(14)
out['significant_gap_up'] = (pct_gap_trigger | atr_gap_trigger).astype(float)
out['gap_unfilled'] = (out['close'] > out['prev_close']).astype(float)   # gap never filled
out['close_above_open'] = (out['close'] > out['open']).astype(float)     # bullish confirmation

out['setup_signal'] = ((out['prior_day_new_low'] > 0.5) & (out['significant_gap_up'] > 0.5)
                       & (out['gap_unfilled'] > 0.5) & (out['close_above_open'] > 0.5)).astype(float)
```

Two details travel well: "significant" gap is a dual trigger — percent *or* ATR-scaled — so volatile months automatically raise the bar; and the exit is purely temporal (2 days), no stop, no target — removing every human temptation to "hold until it comes back." The baseline is honesty itself: in 4,588 daily bars, the setup fired **6 times** — 3 wins, 3 losses, final value 1,030,141.98 (+3.01%), profit factor 1.56, max drawdown 3.27%. Not a money printer; a clean frozen reference for "same idea, different filter" experiments. Its mirror image (`test_0040_gap_down.py`) buys gaps down beyond 1% — same phenomenon, opposite hypothesis, both preserved.

## Deep Dive 2: Kelly / Optimal F — Sizing as the Signal

[test_0052](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0052_kelly_optimal_f_strategy.py) recomputes the target fraction every bar from a rolling 126-day return window, with two selectable engines:

```python
def _kelly_fraction(self, returns):
    mean_return = float(np.mean(returns))
    variance = float(np.var(returns))
    if variance <= 0:
        return 0.0
    fraction = mean_return / variance                     # f* = μ / σ²
    fraction = max(0.0, fraction) * float(self.p.kelly_adjustment)   # half-Kelly
    return min(fraction, float(self.p.max_fraction))      # hard cap 0.2

def _optimal_f(self, returns):
    best_f, best_score = 0.0, -1e18
    for f_value in np.arange(0.0, 1.0 + float(self.p.optimal_f_step), float(self.p.optimal_f_step)):
        wealth_path = 1.0 + f_value * returns
        if np.any(wealth_path <= 0):
            continue
        score = float(np.prod(wealth_path))               # maximize terminal wealth
        if score > best_score:
            best_score, best_f = score, float(f_value)
    return min(best_f * float(self.p.optimal_f_adjustment), float(self.p.max_fraction))
```

Full Kelly is the theoretical optimum *and* a bankruptcy machine the moment your return estimates are off — so the implementation is all brakes: half-Kelly, a 20% cap, and a 63-day trend gate that zeroes exposure when the trend is non-positive. Over 18 years of GLD: average exposure just 10.1%, final value **1,250,223.05** (+25.0%), max drawdown 5.16%, Sharpe 0.53. And a metrics lesson baked in: 1,042 buys and 1,292 sells of continuous resizing, yet the TradeAnalyzer records exactly **1** closed trade — read the *conventions* before you read the numbers.

## Deep Dive 3: Hurst — One Market, Two Personalities

If prices have long memory, the Hurst exponent drifts off 0.5: toward 1, trend self-reinforces; toward 0, up-down alternation (mean reversion) dominates. [test_0056](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/others/test_0056_hurst_exponent_strategy.py) estimates H on a rolling 150-day window and lets it choose the playbook:

```python
def _hurst_from_prices(values, min_lag, max_lag):        # lags 2..20
    log_prices = np.log(prices)
    tau, lags = [], list(range(min_lag, max_lag + 1))
    for lag in lags:
        diffs = log_prices[lag:] - log_prices[:-lag]
        tau.append(np.std(diffs))
    slope, _ = np.polyfit(np.log(lags), np.log(tau), 1)
    return float(np.clip(slope, 0.0, 1.0))               # the log-log slope is H

if hurst_value > float(self.p.trend_threshold):           # H > 0.55: trending
    target_pct = 1.0 if close > sma50 else -1.0
elif hurst_value < float(self.p.mean_reversion_threshold):  # H < 0.45: reverting
    if rsi < 30:  target_pct = 0.75                       # oversold → long
    elif rsi > 70: target_pct = -0.75                     # overbought → short
```

The result is an honest losing baseline: 108 trades, 59 wins, 49 losses, final value **669,247.06** (-33.1%). The diagnosis is more interesting than the number: gold has spent these 18 years being a famously *trending* market, and the mean-reversion leg kept getting run over by one-way moves. The strategy isn't broken — the market's personality and the window disagree. Losing baselines get pinned here for the same reason as winning ones: they mark the factory settings of every signal engine.

## The Rest of the Bench

- **Overnight/Intraday** (`test_0037`): hold whenever the 20-day mean overnight return is positive — +323.5% final, until you notice `margin=0.01, multiplier=100`: 10x futures leverage and a 30.27% drawdown. Read the broker config before the return.
- **Markowitz, shrunk** (`test_0046`): mean-variance collapsed to a rolling Sharpe proxy, rebalanced quarterly — 9 buys and 8 sells in 18 years, final 5,203,300 (same leverage caveat applies).
- **Day-of-month timing** (`test_0026`): month-end MA200 vote with seasonal multipliers (1.1x for Jan/Sep-Dec, 0.75x for Jun-Aug) — final 3,050,417 on a 4-win-16-loss trade record; rotation returns live in the path, not the trades.
- **The stat stack** (`test_0017`, `test_0060`): Omega-ratio gating and a Mahalanobis-distance turbulence thermometer mapping to three fixed allocations.

## Run It Yourself

```bash
# The whole category (69 strategies)
pytest tests/functional/strategies/others/ -v

# Just Gap N Go Fade
pytest tests/functional/strategies/others/test_0001_gap_n_go_fade_from_50_day_low.py -v
```

## Why Study Calendars and Sizing Here

These strategies share a dangerous trait: sparse signals and tiny samples (six trades in 18 years is a real row in this table), where a single backtest is indistinguishable from luck — and sizing rules with dozens of interacting knobs. That is precisely what [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) is for: 46% faster than the original in pure Python, so all 1,152 strategy regression tests finish in minutes; a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) that turns "try a different signal day" from an overnight job into a coffee break; runonce/runnext dual-mode parity; and asserted metric baselines on every strategy, so what you optimize is the strategy — never the engine's drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/17-others-calendar-events.md) and [here](../zh/18-others-statistical-portfolio.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
