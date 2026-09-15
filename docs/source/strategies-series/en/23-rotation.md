# Rotation: Monthly Rankings Turn Momentum into a Portfolio Game

> Strategy Compendium · No. 23 · Category `rotation` (6 strategies) · 2026-09-02

A single-asset momentum strategy asks "did it go up?" A rotation strategy asks "**what went up the most?**" That one-word difference turns momentum from a time-series question into a cross-sectional one: Moskowitz, Ooi, and Pedersen documented inertia across 58 instruments in their famous 2012 time-series momentum study, and Gary Antonacci's dual momentum framework combined "relative momentum selects the asset, absolute momentum acts as the switch" into a plan individual investors can actually execute. Rotation is relative momentum applied to a portfolio.

This article covers the 6 strategies in `tests/functional/strategies/rotation/`. They share one skeleton: align multiple assets → rank periodically → hold the strongest → keep a "if you can't beat them, retreat" defensive asset on standby. The gold/bonds/cash safe-haven ladder gets reinterpreted in six different ways.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Gold asset rotation | XAUUSD/IVV/IEF/DBC monthly, 2006-2025 | 3-month momentum rank, top two at 70/30; absolute-momentum gate else flee to IEF | `test_0001_gold_asset_rotation.py` |
| Safe haven rotation | Gold/silver/JPY/CHF/IEF daily, 2008-2025 | Blended multi-period momentum rank + 63-day MA trend confirm; bonds as fallback | `test_0002_safe_haven_rotation.py` |
| Timing bond rotation | IVV + 4 bond ETFs daily, 2008-2025 | Above the 200-day MA hold equity; below it switch to the strongest-momentum bond | `test_0003_timing_bond_rotation.py` |
| Monthly rotation ranking | XAUUSD daily, 2008-2025 | Percentile-rank the return, buy the upper half, exit below 0.3 | `test_0004_monthly_rotation_ranking.py` |
| Three-factor ETF rotation | IVV/IWM/IEF/GLD/EEM daily, 2021-2025 | 3-month + 20-day momentum + 20-day volatility scoring, top 3 equal weight | `test_0005_three_factor_etf_rotation_strategy.py` |
| Cross-asset rotation | IVV/IEF/GLD/DBC daily, 2008-2025 | 126-day return rank, top two, 50% cap per asset | `test_0006_rotational_trading_strategy.py` |

## Deep Dive 1: Monthly Rotation Ranking — a Single Asset Can Rotate Against Itself

Who says rotation needs multiple assets? [test_0004_monthly_rotation_ranking.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/rotation/test_0004_monthly_rotation_ranking.py) pits an asset against its own history: percentile-rank today's 63-day return within the trailing year — literally asking "is it stronger right now than at most times in the past?"

```python
out['return_rank'] = out['close'].pct_change(lookback).rolling(min(252, len(out))).rank(pct=True)

# ...a rebalance_flag is set every 21 bars...
rank = float(self.data.return_rank[0])
if not self.position:
    if rank > 0.5:
        self.buy_count += 1
        self.pending_order = self.buy(size=self._get_position_size())
else:
    if rank < 0.3:
        self.sell_count += 1
        self.pending_order = self.close()
```

Entry threshold 0.5, exit threshold 0.3 — and between them a **holding buffer** where nothing happens, preventing churn as the rank oscillates around a single line. That asymmetric buffer is the most practical small design in all ranked strategies. The rank itself arrives as a custom data line (`return_rank` via an extended `PandasData` feed), a clean pattern for shipping precomputed signals into backtrader. Eighteen years of gold: 4,324 bars, 20 trades, 12 wins against 7 losses (60% win rate, profit factor 3.50, final value 2,631,363.63 on 1,000,000) under futures-style commission — a low-frequency rhythm, plain to see.

## Deep Dive 2: Safe Haven Rotation — When the Defensive Assets Hold a Tournament

[test_0002_safe_haven_rotation.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/rotation/test_0002_safe_haven_rotation.py) asks a question most portfolios never formalize: *when risk-off actually arrives, which safe haven is strongest?* Five candidates — gold, silver, yen, franc, and a bond ETF as fallback. Note the neat trick for FX: USDJPY and USDCHF are inverted into yen- and franc-*strength* series, so all five assets point the same conceptual direction:

```python
returns = {period: close_df / close_df.shift(period) - 1.0 for period in momentum_periods}
rank_scores = pd.DataFrame(0.0, index=close_df.index, columns=close_df.columns)
for period in momentum_periods:
    period_rank = returns[period].rank(axis=1, ascending=False, method='min')
    rank_scores = rank_scores.add(period_rank, fill_value=0.0)

trend_ma = close_df.rolling(trend_ma_period).mean()
trend_ok = close_df > trend_ma

# at month end: take the top-ranked asset that also confirms its trend
for asset in candidate_assets:
    if bool(trend_ok.loc[dt, asset]):
        chosen = asset
        break
if chosen is None:
    chosen = backup_asset      # nobody confirms: retreat to the bond ETF
```

Blended 63/126-day momentum ranks pick the leader — but the crown only transfers if the leader also trades above its 63-day MA; otherwise capital falls back to bonds. Rank decides who deserves it, the trend filter decides if it's safe to take it. Over 2008-2025 (4,287 bars) this produced 123 rebalances but only **3 completed round-trip trades — 3 wins, 0 losses**. Safe-haven rotation is a patient, almost meditative discipline.

## The Rest of the Bench

- **Gold asset rotation** (`test_0001`): the textbook dual-momentum build — 4 assets resampled to month-end, 3-month momentum ranked, top two at 70/30, and an absolute-momentum gate (`threshold=0.0`): if even the winner's momentum is negative, everything goes to IEF. Twenty years of monthly bars (236 bars): 59 trades, 158 rebalances, 36 wins / 22 losses. Momentum's low turnover, visible.
- **Timing bond rotation** (`test_0003`): one 200-day MA as the risk switch; below it, bonds are scored with front-weighted 12/4/2/1 momentum across 21/63/126/252-day lookbacks; a 5% drift threshold respects transaction costs. 3,212 bars, 16 trades, 8 wins / 7 losses across two equity bear markets.
- **Three-factor ETF rotation** (`test_0005`): adds 20-day volatility (lower is better) to momentum at 0.4/0.4/0.2 weights, top 3 equal-weighted — template code for multi-factor ranking. 1,245 bars, 56 rebalances, 2021-2025.
- **Cross-asset rotation** (`test_0006`): the plain vanilla — 126-day returns, top two, 50% cap, every 21 days; 4,518 bars, 216 rebalances. Keep it as the control group to see exactly what seasoning the other five added.

## Run It Yourself

```bash
# The whole category (6 strategies)
pytest tests/functional/strategies/rotation/ -v

# Just monthly rotation ranking
pytest tests/functional/strategies/rotation/test_0004_monthly_rotation_ranking.py -v
```

## Why Study Rotation Here

Rotation is inherently multi-data, multi-timeframe: resampling, alignment, ranking, and rebalancing can each inject numerical drift — and "rank one position lower" means a completely different portfolio. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) nails all of it down with 1,152 strategy regression tests and asserted metric baselines, while runonce/runnext dual-mode parity guarantees the vectorized and event-driven paths produce the same ranking. The pure-Python engine is 46% faster than the original, and the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — turning "18 years × 4 assets of monthly resampling" from a coffee break into a whim.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/36-rotation.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
