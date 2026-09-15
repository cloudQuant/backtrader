# Carry Trading: The Science of Picking Up Yield — and the 2008 Steamroller

> Strategy Compendium · No. 29 · Category `carry_trading` (4 strategies) · 2026-09-02

Borrow yen at 0.1%, convert to Australian dollars yielding 5%, do nothing, and pocket roughly 5% — the carry trade was once called "the only free lunch in finance." The 2008 crisis tore up the menu: panic sent the yen soaring, carry positions worldwide unwound simultaneously, and AUD/JPY collapsed within months — the rent-collectors gave back years of rent in weeks. **Carry is not a free lunch; it is a premium for bearing tail risk** — academia gave it a blunt name: carry crash.

Why does the spread exist at all? One explanation: it is compensation for depreciation risk. High-yield currencies usually pay high rates because inflation is high and the central bank is tight — and over the long run their exchange rates tend to weaken, while low-yield safe-haven currencies appreciate in crises. So a carry book earns small positive returns most days and enormous negative ones on crisis days — picking up coins in front of a steamroller. Understanding that structure explains the common orientation of all four strategies here: **use hedging, neutralization, and stops to push the steamroller a little further away.**

This article walks through the 4 backtests in `tests/functional/strategies/carry_trading/`. They all face the same engineering problem — MT5-exported history contains no interest rates and no futures term structure — and their answers are worth studying: **reconstruct carry from proxy variables.**

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Gold-rate carry | XAUUSD + IEF daily, 2008-2025 | Rolling beta maps a fair gold price; bet on residual z-score convergence | `test_0001_0031_gold_rate_carry.py` |
| Gold relative value | Gold/silver/platinum daily, 2010-2025 | Two precious-metal spread z-scores, mean-reversion trades | `test_0002_0050_gold_relative_value.py` |
| FX carry | AUD/NZD/GBP/EUR daily, 2008-2025 | Baseline carry score + long trend − recent volatility as a proxy; long high, short low | `test_0003_0393_carry_trading_strategy.py` |
| Commodity carry | DBC/GLD/metals daily | Short-minus-long window returns approximate carry; cross-sectional ranking | `test_0004_0394_commodity_carry_strategy.py` |

## Deep Dive 1: FX Carry — No Interest-Rate Data? Build One

The heart of [test_0003_0393_carry_trading_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/carry_trading/test_0003_0393_carry_trading_strategy.py) is this proxy construction:

```python
trend = px['close'].pct_change(trend_window)      # 126-day long-horizon trend
vol = px['close'].pct_change().rolling(vol_window).std()  # 21-day volatility
baseline = float(baseline_scores.get(symbol, 0.0))
carry_proxy = baseline + trend - vol
```

Each ingredient has a job: `baseline_carry_scores` encodes the prior interest-differential ranking (AUDUSD 0.03, NZDUSD 0.025, GBPUSD 0.01, EURUSD -0.002); the long-window trend captures the exchange-rate drift of high-yield currencies; subtracting recent volatility penalizes turbulent ones. **High yield + trend + calm = good carry** — precisely the behavioral profile of the carry factor in the academic literature.

Every 21 days the four pairs are ranked by proxy score: long the top 2, short the bottom 2 (each leg capped at 25% notional), leaving the book roughly **dollar-neutral** after netting. The 2008-2025 backtest — 4,549 bars, 217 rebalances, 200 trades — delivers a brutally honest result: final value 912,208.05 (**-8.8%**), Sharpe -0.27, win rate 41%. The proxy did not reproduce the interest-rate spread — the trend term hijacked the signal. That is itself the engineering lesson: **bias introduced by a proxy variable can quietly turn a factor strategy into a different strategy.**

## Deep Dive 2: Gold-Rate Carry — Turning Carry into a Cointegration Pair

The other route skips rankings and builds a pair. [test_0001_0031_gold_rate_carry.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/carry_trading/test_0001_0031_gold_rate_carry.py) treats gold and a rate-proxy ETF (IEF) as a cointegrated pair: a rolling regression derives gold's "fair anchor" from rates, then bets on the residual:

```python
gold_log = np.log(out['close'])
rate_log = np.log(out['rate_proxy_close'])
cov = gold_log.rolling(relationship_window).cov(rate_log)      # 126-day
var = rate_log.rolling(relationship_window).var().replace(0, np.nan)
out['beta'] = cov / var
out['fair_value'] = out['beta'] * rate_log
out['spread'] = gold_log - out['fair_value']                   # the residual
out['spread_z'] = rolling_zscore(out['spread'], relationship_window)

long_mask = (out['rate_z'] > entry_z) & (out['spread_z'] < -spread_entry_z)   # rates stretched, gold cheap
short_mask = (out['rate_z'] < -entry_z) & (out['spread_z'] > spread_entry_z)
```

Entry demands **two extremes at once**: the rate side stretched beyond 1 standard deviation, and gold deviating 0.5 standard deviations *against* its fair anchor — a bet on mispricing and reversion. Exits trigger when the residual converges inside ±0.2, with a hard 3x ATR stop as backstop (25% position, shorts allowed). The dual z-score design is one notch more rigorous than "trade when the spread moves": it requires both the driver (rates) and the driven (gold) to flash extreme readings, filtering out reams of one-sided noise.

The result: 4,258 bars, 117 trades, a 41% win rate carried by the payoff ratio to a profit factor of 1.13, final value 1,032,287.54 (+3.2%). Low win rate living off payoff asymmetry — the signature temperament of the mean-reversion family.

## The Rest of the Bench

- **Gold relative value** (`test_0002`): gold/silver and gold/platinum spread z-scores, mean-reverting with weights aggregated per asset and total exposure capped, rebalanced via `order_target_percent`. 125 trades, profit factor 0.97 — precisely unprofitable.
- **Commodity carry** (`test_0004`): approximates term-structure carry as "short-window return minus a scaled long-window return," ranks six commodities cross-sectionally, longs the top two and shorts the bottom two. After 118 rebalances: final value 1,306,885.25 (+30.7%, Sharpe 0.52) — the same proxy carry, a different basket, a wildly different outcome. Carry is a risk premium, not a law of physics.

## Run It Yourself

```bash
# The whole category (4 strategies)
pytest tests/functional/strategies/carry_trading/ -v

# Just the FX carry ranking
pytest tests/functional/strategies/carry_trading/test_0003_0393_carry_trading_strategy.py -v
```

## Why Study Carry Here

Multi-asset alignment, daily rebalancing, simultaneous long and short legs — carry backtests load a framework's concurrent data streams and order book to the max. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)'s runonce/runnext dual-mode parity keeps multi-data alignment identical across its vectorized and event-driven engines, and its 1,152 strategy regression tests pin every rebalance's trade counts and final values into asserted metric baselines. The pure-Python engine is 46% faster than the original; the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — enough to change the 21-day cadence to 5, swap four pairs for eight, and map the parameter sensitivity of proxy carry systematically.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/42-carry-trading.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
