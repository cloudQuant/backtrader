# Momentum: One Switch, One Ranking, One Anchor

> Strategy Compendium · No. 03 · Category `momentum` (45 strategies) · 2026-09-02

Momentum may be the most academically durable anomaly in finance: Jegadeesh and Titman showed in 1993 that assets that outperformed over the past 6-12 months tend to keep outperforming for another 3-12. What brought momentum into mainstream asset allocation was Gary Antonacci's Dual Momentum framework, which splits the idea into two orthogonal questions: **absolute momentum asks "should I be in the market at all?" — relative momentum asks "given that I am, what should I hold?"** A parallel line, Moskowitz, Ooi and Pedersen's 2012 *Time Series Momentum*, ignores everyone else entirely: if an asset's own 12-month return is positive, own it.

The 45 backtests in `tests/functional/strategies/momentum/` exercise both questions on gold's 2008-2025 daily bars — a window containing the 2011-2015 bear, the 2019-2025 bull, and everything in between. This digest follows the two levers of dual momentum plus a behavioral third act: the 52-week-high effect.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Dual momentum (switch) | XAUUSD daily, 2008-2025 | Monthly check of 252-day momentum; hold or go to cash | `test_0001_dual_momentum.py` |
| Gold dual momentum (4 assets) | XAUUSD/IVV/IEF/GLD | 12-month relative pick; cash if the best is still losing | `test_0002_gold_dual_momentum.py` |
| TS momentum (vol-targeted) | XAUUSD daily | 12-month direction, 15% vol target, 8% stop | `test_0005_gold_time_series_momentum.py` |
| Antonacci classic | XAUUSD vs GSPY | Gold-vs-equities head-to-head dual momentum | `test_0015_dual_momentum_strategy.py` |
| 52-week high effect | XAUUSD daily | Close within 75-98% of the rolling high, above 200-SMA | `test_0014_52week_high_effect.py` |
| ESG momentum | XAUUSD daily | 120-day momentum + low-volatility rank | `test_0025_esg_momentum.py` |
| Precious-metals ROC rotation | Au/Ag/Pt/Pd daily | 21/63/252-day composite ROC, monthly switch | `test_0010_momentum_rotation_roc.py` |
| Alpha momentum | GLD/GDX/XAGUSD/IEF | Rolling alpha vs IVV; long high, short low | `test_0017_alpha_momentum.py` |
| Dual momentum + Vortex | XAUUSD daily | 252-day momentum + 14-day Vortex timing | `test_0022_dual_momentum_vortex.py` |
| Two-period RSI | ORCL daily, 2010-2014 | RSI(14)>50 and RSI(5)>65 | `test_101_rsi_long_short_strategy.py` |

## Deep Dive 1: Absolute Momentum as a Switch

[test_0001](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0001_dual_momentum.py) is dual momentum in its minimal form. Features are one line of pandas; the strategy checks them once a month:

```python
lookback = int(params.get('lookback_period', 252))
risk_free = float(params.get('risk_free_threshold', 0.0))
out['momentum'] = out['close'] / out['close'].shift(lookback) - 1
out['abs_momentum'] = (out['momentum'] > risk_free).astype(float)

def next(self):
    month_key = bt.num2date(self.data.datetime[0]).month
    if month_key == self.current_month:
        return                                  # one decision per month
    self.current_month = month_key
    abs_momentum = float(self.data.abs_momentum[0])
    if abs_momentum > 0.5:                      # 252-day momentum positive
        if not self.position:
            self.pending_order = self.buy(size=self._get_position_size(...))
    else:                                       # momentum gone → cash
        if self.position:
            self.pending_order = self.close()
```

Eighteen years produce just 14 trades (5 wins, 8 losses, one flat) — a 35.7% win rate — yet profit factor 2.36, final value **3,789,720** (+278.97%), max drawdown 33.71%. The canonical trend-following profile: many small losses exchanged for a few large wins. Note two quiet guardrails: position sizing divides by the contract multiplier (100), so futures margin is not silently 100x-leveraged; and a `pending_order` gate stops `next()` from re-firing while an order is alive — the kind of detail that makes cent-level assertion parity possible.

## Deep Dive 2: Relative Momentum as a Ranking

A single asset can only answer "in or out." [test_0002](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0002_gold_dual_momentum.py) widens the universe to four assets — spot gold, IVV (S&P 500), IEF (Treasuries), GLD — aligned to month-end, completing Antonacci's puzzle:

```python
momentum = close_table / close_table.shift(formation_period) - 1.0    # 12 months
best_asset.loc[valid_mask] = momentum.loc[valid_mask].idxmax(axis=1)  # relative: pick the strongest
best_return.loc[valid_mask] = momentum.loc[valid_mask].max(axis=1)
selected_asset = best_asset.where(best_return > 0, 'CASH')            # absolute: or hold cash
```

The position ledger tells the story better than the equity curve: of 204 months, equities held 96, spot gold 76, bonds 16, GLD 5 — and 11 months in cash — with 52 switches, final value **2,078,226** (+107.82%). The headline number, though, is the max drawdown: **12.08%**, versus 33.71% for the single-asset switch. No line of "market timing" code exists anywhere — the two momentum conditions migrate the portfolio to risk assets in bulls and to cash when even the strongest asset is falling. That is why dual momentum earned its place in allocation circles.

## Deep Dive 3: The 52-Week High — Anchored, Not Broken

George and Hwang (2004) found that *proximity to the 52-week high* predicts returns better than conventional momentum — the behavioral read is anchoring: investors fixate on the high, so price near it is "expensive" and under-reacts. [test_0014](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/momentum/test_0014_52week_high_effect.py) turns the finding into rules — notably, it does **not** buy breakouts; it buys proximity:

```python
rolling_high = out['high'].rolling(lookback_days).max().shift(1)   # lookback_weeks = 26
ratio = out['close'] / rolling_high
trend_ma = out['close'].rolling(trend_ma_days).mean()              # 200-SMA
near_high = ((ratio >= lower_threshold) & (ratio <= upper_threshold)).astype(float)  # 0.75~0.98
trend_filter = (out['close'] > trend_ma).astype(float)
entry_signal = ((near_high > 0.5) & (trend_filter > 0.5)).astype(float)
```

Exits are three-way: ratio losing 0.7, close back under the 200-SMA, or 63 days held. Result: final value **2,992,579** (+199.26%) on a 32.65% win rate, profit factor 2.13, Sharpe 0.57, max drawdown 30.61% — a long-tail payoff profile again. One implementation wrinkle worth internalizing: the config says `lookback_weeks=26`, so the rolling window is 26 weeks (130 trading days), *not* the 52 weeks in the strategy's name. Strategy names and parameters are different things — always read the params; the assertions freeze them precisely so you must.

## The Rest of the Bench

- **ESG momentum** (`test_0025`): momentum for direction, low-volatility rank for quality, rebalanced every 63 days — final 3,857,492 (+285.75%), 81.25% win rate, 19.19% drawdown: factor stacking at its most instructive.
- **Vol-targeted TSM** (`test_0005`): 12-month direction with a 15% volatility throttle (0.5x-1.5x scaling) and an 8% stop — final 2,758,111, drawdown 23.30%, Sharpe 0.70; slightly less return than the raw switch, visibly better risk.
- **Precious-metals ROC rotation** (`test_0010`): an honest -10.55% with 46.41% drawdown — four highly correlated metals give cross-sectional momentum nothing to rotate *between*. Losing baselines are pinned here on purpose.
- **The combination builders** (`test_0026`, `test_0017`): five momentum flavors inverse-vol weighted, and rolling-alpha longs/shorts — the category's heaviest engineering.

## Run It Yourself

```bash
# The whole category (45 strategies)
pytest tests/functional/strategies/momentum/ -v

# Just the dual-momentum switch
pytest tests/functional/strategies/momentum/test_0001_dual_momentum.py -v
```

## Why Study Momentum Here

Momentum strategies have long lookbacks, sparse rebalances, and many branching code paths — the worst place for "the engine changed and the numbers quietly moved." [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) keeps 1,152 strategy regression tests on asserted metric baselines, pinning every strategy's final value, win rate, and drawdown; runonce/runnext dual-mode parity keeps the vectorized and event-driven paths numerically identical. The engine itself is 46% faster than the original in pure Python, and the C++ backend (`pip install back-trader-cpp`) delivers a median 128x speedup — sensitivity checks across 126/188/252-day lookbacks stop being overnight jobs.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/13-momentum-dual-ts.md) and [here](../zh/14-momentum-factor-rotation.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
