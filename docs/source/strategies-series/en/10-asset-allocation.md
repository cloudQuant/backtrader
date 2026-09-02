# Asset Allocation: 60/40, the Permanent Portfolio, and CPPI Insurance

> Strategy Compendium · No. 10 · Category `asset_allocation` (23 strategies) · 2026-09-02

Timing strategies ask "when to buy." Allocation strategies ask "how much, and of what" — one word apart, a worldview away. Timers believe direction can be predicted; allocators concede that prediction is hard, lean on low correlations between assets instead, and collect the market's own money (beta). Stock-bond portfolio theory dates to 1926, and "60/40" ruled institutional portfolios for the better part of a century — until 2008 exposed its soft spot: in a crisis, correlations spike, and 60/40 sinks as one. Risk parity rose from that wreck — Bridgewater's All Weather turned "equalize risk, not dollars" into a trillion-dollar business.

This article walks through the 23 allocation strategies in `tests/functional/strategies/asset_allocation/`: from the trend-enhanced 60/40, through Harry Browne's Permanent Portfolio and CPPI portfolio insurance, to Lopez de Prado's Hierarchical Risk Parity. All are multi-asset, fully reproducible backtests.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| 60/40 trend-enhanced | XAUUSD daily 2008-2025 | SMA200 filter: 60% above, 30% below; 63-day rebalance | `test_0011_sixty_forty_portfolio.py` |
| Permanent Portfolio | GLD/IVV/IEF daily | 25% each stocks/bonds/gold/cash; annual + threshold rebalance | `test_0007_permanent_portfolio.py` |
| CPPI insurance | XAUUSD daily | Floor at 80% of peak; cushion x 3 sets exposure | `test_0017_cppi_portfolio_insurance.py` |
| Hierarchical Risk Parity | XAUUSD daily | Hierarchical clustering + bisection, no covariance inverse | `test_0012_hierarchical_risk_parity.py` |
| TAA risk parity trend | DBC/GLD/IEF/IVV daily | Risk-parity weights with a trend overlay | `test_0008_taa_risk_parity_trend.py` |
| HERC | XAUUSD daily | HRP's hierarchical equal-risk-contribution variant | `test_0015_herc_portfolio.py` |
| Gold 60/40 enhancement | XAUUSD/IVV/IEF daily | Classic 60/40 plus a gold leg | `test_0002_gold_60_40_enhancement.py` |
| Trinity portfolio | XAUUSD daily | The 4%-rule withdrawal portfolio | `test_0005_trinity_portfolio_gold.py` |
| Anti-fragile portfolio | XAUUSD daily | Convexity-first barbell structure | `test_0014_anti_fragile_portfolio.py` |
| Volatility-managed | XAUUSD daily | Exposure inverse to realized volatility | `test_0004_volatility_managed_portfolio_gold.py` |
| Optimal gold allocation | DBC/GLD/IEF/IVV daily | Weight search for gold in multi-asset mixes | `test_0018_optimal_gold_allocation_strategy.py` |
| Crypto optimal allocation | GLD/IBIT/IEF/IVV daily | A Bitcoin ETF enters the portfolio | `test_0019_crypto_optimal_allocation_strategy.py` |
| Adaptive Asset Allocation | DBC/GLD/IEF/IVV daily | Momentum + volatility dual-factor weights | `test_0022_adaptive_asset_allocation_strategy.py` |
| Composite allocation | BIL/EFA/GTIP/IEF/IVV daily | Five assets, multiple signals blended | `test_0010_composite_asset_allocation.py` |

## Deep Dive 1: 60/40 Trend-Enhanced — a Classic, Fitted with a Brake

[test_0011](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/asset_allocation/test_0011_sixty_forty_portfolio.py) is the trend-filtered edition of the classic. It approximates the equity leg with a single asset (gold) and the bond leg with de-risking: above SMA200 the target exposure is 60%; below it, 30% — "half off below the line" is a soft stop-loss for the whole portfolio. Signal side:

```python
out["ma"] = out["close"].rolling(ma_period).mean()          # ma_period = 200
out["trend_up"] = (out["close"] > out["ma"]).astype(float)
# a rebalance flag is raised every rebalance_days = 63 days
```

On rebalance days the strategy adjusts to the trend target, and only acts when the drift exceeds 10%:

```python
target_weight = self.p.equity_weight if trend_up else 0.30   # 0.60 / 0.30
if abs(current_size - target_size) > target_size * 0.1:
    self.pending_order = self.close()                        # flatten first, then resize
```

**The backtest:** XAUUSD daily 2008-2025 from 1,000,000 — only 19 adjustments in 17 years, 13 wins against 6 losses (68.4%), final value 2,542,114 (+154.2%), profit factor 5.24, max drawdown a modest 11.9%, Sharpe 0.770. Low frequency plus a trend filter is a drawdown-control combination that buy-and-hold cannot offer on the same series. For the unfiltered versions in a multi-asset setting, `test_0002` and `test_0003` provide the contrast.

## Deep Dive 2: the Permanent Portfolio — 25% x 4 Philosophy

Harry Browne proposed the Permanent Portfolio in 1981: stocks, bonds, gold, and cash at 25% each, betting that the future is always in one of four states — prosperity, recession, inflation, or deflation — and that in each state some asset thrives. The implementation ([test_0007](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/asset_allocation/test_0007_permanent_portfolio.py)) uses three daily ETF feeds (GLD/IVV/IEF) plus a cash leg:

```python
params = dict(
    target_weights={'GLD': 0.25, 'IVV': 0.25, 'IEF': 0.25},
    cash_weight=0.25,
    rebalance_threshold=0.05,          # drift band for ordinary assets: 5%
    gold_rebalance_threshold=0.02,     # gold is volatile; give it a tighter 2%
)
```

Rebalancing runs on dual tracks — annual plus threshold — which is standard practice for live portfolios:

```python
if current_year != self.last_rebalance_year:
    self._rebalance()                          # forced on the first trading day of each year
    return
if self._needs_threshold_rebalance():          # drifted past the band: correct early
    self.threshold_rebalance_count += 1
    self._rebalance()
```

**The backtest:** 2008-2025, 4,518 trading days, 50 rebalances fired — 32 of them by threshold, the gold leg's tight 2% band staying busy as designed — final value 4,268,547 (+326.9%), 8.43% annualized, max drawdown 32.3%, Sharpe 0.659. Caveat printed honestly: both gold and US equities enjoyed a mighty bull run in this window, so the headline numbers flatter the design. But details like "a tighter drift band for the gold leg" are what textbooks omit and backtests teach.

## Deep Dive 3: CPPI — Capital Preservation by Formula

CPPI (Constant Proportion Portfolio Insurance) is 1980s technology invented for "guaranteed funds": set a floor the portfolio must not breach, call the excess of portfolio value above the floor the cushion, and set risky exposure = cushion × multiplier. Rallies thicken the cushion and enlarge exposure; declines shrink it and de-risk automatically — in theory the floor is never pierced. The implementation ([test_0017](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/asset_allocation/test_0017_cppi_portfolio_insurance.py)):

```python
running_max = out['close'].cummax()
floor_value = running_max * floor_pct                  # floor_pct = 0.8, i.e. 80% of peak
out['cushion_pct'] = (out['close'] - floor_value) / out['close']
out['exposure'] = (out['cushion_pct'] * cppi_mult).clip(0.0, 1.0)   # multiplier = 3.0
```

Rebalancing every 21 days, entries only when exposure exceeds 10%, full liquidation below 5%. **The backtest:** 35 trades, 14 wins against 20 losses — a 40% win rate — yet the account finishes at 1,533,999 (+53.4%) with Sharpe 0.447. Winning less than half the time while banking profit is CPPI's personality: with a 3x multiplier, upside cushions expand exposure quickly while downside compresses the balance sheet fast. Its enemy is gap risk — one jump straight through the floor. Whether a daily-bar 20% cushion survives a 2008-style crash is an excellent experiment to run yourself by editing the parameters.

## The Rest of the Bench

- **HRP / HERC** (`test_0012` / `test_0015`): Lopez de Prado's answer to covariance inversion, from *Advances in Financial Machine Learning* — hierarchical clustering plus recursive bisection; stable, interpretable weights, the modern face of risk parity.
- **Dual-asset leveraged portfolio** (`test_0009`): the minimum viable allocation — one risky asset plus cash.
- **Volatility-based family** (`test_0020` / `test_0021`): switch between stocks and bonds against a volatility target.
- **Random-data portfolio optimization** (`test_0006`): the portfolio-optimization pipeline demonstrated on GDX/XAGUSD/XAUUSD.
- **Open-to-open TAA** (`test_0016`): rebalance at the open instead of the close — execution-timing sensitivity, tested.

## Run It Yourself

```bash
# The whole category (23 strategies)
pytest tests/functional/strategies/asset_allocation/ -v

# Just the Permanent Portfolio
pytest tests/functional/strategies/asset_allocation/test_0007_permanent_portfolio.py -v
```

## Why Study Asset Allocation Here

Allocation backtests are bottlenecked by multi-asset alignment and rebalance scheduling: decades of daily bars, several data feeds, hundreds of rebalance events, each involving cash arithmetic and multi-leg ordering. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) ships all of it as infrastructure proven by 1,152 strategy regression tests: 46% faster than the original in pure Python, a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) — sweeps over rebalance frequency and drift-band width stop being overnight jobs — plus runonce/runnext dual-mode parity and asserted metric baselines, so what you compare is allocation philosophy, not engine drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/23-asset-allocation.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
