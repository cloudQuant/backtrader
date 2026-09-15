# Risk Management Strategies: Vol Targeting, Tiered Drawdown Protection, and Crisis Hedges

> Strategy Compendium · No. 14 · Category `risk_management` (19 strategies) · 2026-09-02

There is an old joke in strategy research: retail asks "how much does it make," institutions ask "how much does it draw down." The two allocation techniques that spread fastest through institutional practice over the past twenty years predict nothing at all: **volatility targeting** — size positions so the portfolio's risk budget stays constant — and **drawdown protection** — the deeper the equity dip, the lower the leverage, a tiered response instead of a single hard stop. Add "crisis alpha" (the tendency of gold and CTA-style assets to rally in equity crashes) and you have this category's three themes.

`tests/functional/strategies/risk_management/` holds 19 strategies: ten genuine risk-management systems plus a batch of moving-average EA ports filed here during migration (disclosed honestly below). We deep-dive two: the multi-level drawdown protection system and the monthly MA tail-risk switch.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Probit risk modeling | XAUUSD daily 2008-2025 | Probit downside-risk probability as an on/off switch | `test_0001_probit_risk_modeling_gold.py` |
| Multi-market hedge | GLD/GDX/IDU/IVV daily | Conditional gold-long/miner-short hedge | `test_0002_gold_multi_market_hedge.py` |
| Tail-risk MA warning | XAUUSD daily 2008-2025 | Monthly close below 10-month MA halves exposure | `test_0003_tail_risk_ma_warning.py` |
| Drawdown protection | XAUUSD daily 2008-2025 | Vol-target sizing + 3%/6%/10% drawdown tiers | `test_0004_drawdown_protection.py` |
| Bond risk premium | Stock + bond ETFs | Stock/bond target weights, de-risk on drawdown | `test_0005_bond_risk_premium.py` |
| Managed futures hedge | XAUUSD daily | Fast/slow MA CTA switch sets notional exposure | `test_0006_managed_futures_hedge.py` |
| Crisis hedge | XAUUSD daily 2008-2025 | Buy gold when drawdown or volatility breaks | `test_0007_crisis_hedge.py` |
| Risk on / risk off | XAUUSD daily 2008-2025 | Hold long only when vol is low and price above MA | `test_0008_risk_on_risk_off.py` |
| Risk premium value | XAUUSD daily | Return/volatility score picks long or short | `test_0009_risk_premium_value.py` |
| Grid delta hedge | XAUUSD daily | Symmetric grid, target exposure steps per crossing | `test_0010_grid_trading_delta_hedge_strategy.py` |
| 0040 MA crossover | XAUUSD daily | EA port, MA family | `test_0011_0040_moving_average_crossover.py` |
| 0150 smoothing average | XAUUSD daily | EA port, MA family | `test_0012_0150_smoothing_average.py` |
| 0300 crossing MA | XAUUSD daily | EA port, MA family | `test_0013_0300_crossing_moving_average.py` |
| 0375 modified MAs | XAUUSD daily | EA port, MA family | `test_0014_0375_modified_moving_averages.py` |
| 0407 EA MA | XAUUSD daily | EA port, MA family | `test_0015_0407_ea_moving_average.py` |
| 0705 MA system | XAUUSD daily | EA port, MA family | `test_0016_0705_moving_average_trade_system.py` |
| 1120 MA | XAUUSD daily | EA port, MA family | `test_0017_1120_moving_average.py` |
| 1273 corrected average | XAUUSD daily | EA port, MA family | `test_0018_1273_corrected_average.py` |
| 1276 movingaverage fn | XAUUSD daily | EA port, MA family | `test_0019_1276_movingaverage_fn.py` |

## Deep Dive 1: Drawdown Protection — Vol Target × Drawdown Ladder × Smoothing

[test_0004_drawdown_protection.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/risk_management/test_0004_drawdown_protection.py) is institutional risk control in miniature. Layer one is volatility targeting — target 12% annualized, so the higher the realized vol, the smaller the position, clipped to [0.25, 1.0]:

```python
if current_vol > 0:
    vol_position = self.p.target_vol / current_vol   # target_vol = 0.12
    return max(0.25, min(1.0, vol_position))
```

Layer two is the drawdown ladder — peak-to-trough drawdown `(close - cummax) / cummax` crossing each threshold steps the multiplier down (documented intent: 3%/6%/10% → 1.0/0.75/0.5/0.25):

```python
if drawdown < -self.p.dd_threshold_1:      # 0.03
    return self.p.position_level_1         # 1.0
elif drawdown < -self.p.dd_threshold_2:    # 0.06
    return self.p.position_level_2         # 0.75
elif drawdown < -self.p.dd_threshold_3:    # 0.10
    return self.p.position_level_3         # 0.5
else:
    return self.p.position_level_4         # 0.25
```

The two layers combine via `min(dd_position, vol_position)`, then pass through an exponential smoother (factor 0.15) and a 5% rebalancing band — only act when the smoothed target moves more than 5%.

**The engineering note (read this twice).** Look at the branch order above: since `drawdown` is never positive, any drawdown beyond −3% returns 1.0 immediately — the 0.75 and 0.5 tiers are unreachable, and *shallow* drawdowns fall through to `else` and get 0.25. The migration baseline locks the code's **actual behavior**, not the documentation's intent: 2008-2025, 4,618 daily bars, 289 rebalances, final value 2,732,100.12 (+173.21%), Sharpe 0.616, max drawdown 31.43%. That is precisely what asserted baselines are for — fix the ladder ordering and the test goes red, forcing the change to be reviewed and re-recorded instead of drifting silently.

## Deep Dive 2: Tail-Risk MA Warning — the 10-Month Moving Average Switch

After 2008, "cut exposure when price loses the 10-month moving average" graduated from futures-floor folklore to a published tail-risk mitigation model (Meb Faber's classic study used exactly the 10-month MA). [test_0003_tail_risk_ma_warning.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/risk_management/test_0003_tail_risk_ma_warning.py) replicates the rule faithfully:

```python
monthly_close = out['close'].groupby(month_end_index).last()
monthly_ma = monthly_close.rolling(ma_period).mean()                # ma_period = 10 months
monthly_risk_state = (monthly_close < monthly_ma).astype(float)
active_risk_state = monthly_risk_state.shift(1).reindex(month_end_index).fillna(0.0)
out['target_pct'] = np.where(out['risk_state'] >= 0.5, risk_position, normal_position)  # 0.5 / 1.0
```

Three details show the craft: daily bars are grouped to month-end closes so the signal has monthly granularity; `shift(1)` delays the regime by one month — last month's close below the MA cuts *this* month's exposure, killing any lookahead; and a 2% rebalancing band stops the target from churning orders at the boundary. Over 2008-2025: 216 calendar months, 68 in the risk state (31.48%), 32 regime switches. Of 24 "large-loss months" (≤ −5%), 16 (66.67%) occurred below the MA — the switch really did keep most of the worst months out. Final value 3,806,875.01 (+280.69%), Sharpe 0.555, max drawdown 39.41% — against gold's 2011-2015 bear market, halving exposure could soften but not immunize.

## The Rest of the Bench

- **Risk on / risk off** (`test_0008`): the phrase compressed to one AND — annualized vol below 20% AND price above the 100-day MA. 81 trades, only 23 wins (28.40%) yet profit factor 3.75: classic regime filtering, mostly small stops plus a few large trends. Final value 3,881,633.30 (+288.16%), Sharpe 0.746, SQN 2.27, max drawdown 19.44% — the best drawdown control of the lot.
- **Probit risk modeling** (`test_0001`): a probit regression estimates the probability of a near-term crash; above threshold, go flat — a statistical model used as a circuit breaker.
- **Multi-market hedge / Crisis hedge** (`test_0002/0007`): a gold-long/miner-short relative-value book, and a system that buys gold specifically in crash regimes to harvest crisis alpha.
- **Bond risk premium / Managed futures hedge / Risk premium value** (`test_0005/0006/0009`): stock-bond de-risking, a CTA-style trend switch, and return-per-volatility scoring — three classic institutional recipes.
- **Grid delta hedge** (`test_0010`): a symmetric grid whose target exposure steps per crossing, with periodic re-centering.
- **The MA family (test_0011-0019)**: full disclosure — nine EA ports (0040/0150/0300/0375/0407/0705/1120/1273/1276) filed under this category by source; they carry no risk logic of their own. Browse them as neighbors, not members.

## Run It Yourself

```bash
# The whole category (19 strategies)
pytest tests/functional/strategies/risk_management/ -v

# Just Drawdown Protection
pytest tests/functional/strategies/risk_management/test_0004_drawdown_protection.py -v

# Just the tail-risk MA warning
pytest tests/functional/strategies/risk_management/test_0003_tail_risk_ma_warning.py -v
```

## Why Study Risk Management Here

Risk strategies live or die in long, multi-regime detail — exactly where engine numerical drift hurts most. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) fixes even subtle behaviors (a drawdown ladder's branch order) into reproducible facts with 1,152 strategy regression tests and per-strategy asserted baselines, while runonce/runnext dual-mode parity guarantees the vectorized and event-driven paths produce the same risk curve. The pure Python engine is 46% faster than the original; the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — enough to sweep 3%/6%/10% thresholds into a parameter plateau and see whether you are standing on a peak or a plain.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/27-risk-management.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
