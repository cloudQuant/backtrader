# Trend Following: From the Golden Cross to Hidden Markov Models

> Strategy Compendium · No. 01 · Category `trend_following` (340 strategies) · 2026-09-02

If quantitative strategies have a family tree, its first page belongs to the moving-average crossover. It is the first "technical analysis" most traders ever meet: fast line crosses above slow line, buy; crosses below, sell. And because it is so simple, it is also the most underestimated family in the shop — within this repository's `trend_following` category (340 strategies), crossovers and their close relatives alone occupy roughly 69 seats.

Here is a counterintuitive fact to set the tone: on gold's 2008-2025 bull run, a bare 50/200 golden-cross system traded only **13 times in 18 years**, won fewer than a third of those trades, and still turned 1,000,000 into 3,571,828. Win rate and profit are different variables — that is lesson one of trend following.

This digest tours the category through three of its highlights: the patient Golden Cross, the full Original Turtle Rules (position engineering, not just signals), and a Hidden Markov Model that turns "what regime are we in" into a computable quantity. Each is a self-contained backtest you can reproduce with one command.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Golden Cross | XAUUSD daily, 2008-2025 | 50 SMA crosses above 200 SMA to enter; death cross exits | `test_0175_golden_cross.py` |
| SMA trend following | XAUUSD daily | Hold while price closes above the 200 SMA | `test_0001_sma_trend_following.py` |
| Original Turtle Rules | XAUUSD M15 | 20/55-channel entries + ATR unit sizing + pyramiding | `test_0074_0776_original_turtle_rules_trader.py` |
| Donchian color system | XAUUSD M15→H4 | Dual-timeframe channel "color" state machine | `test_0078_0855_donchian_channels_system.py` |
| MACD Sample (MT5 official) | XAUUSD M15 | Golden cross below zero + EMA26 slope confirmation | `test_0116_1107_macd_sample.py` |
| ADX + MA | XAUUSD M15 | ADX threshold gates every MA-cross signal | `test_0064_0687_adx_ma.py` |
| SuperTrend (Kolier) | XAUUSD M15 | ATR band flip = stop and reverse | `test_0139_1232_supertrend.py` |
| Woodies CCI | XAUUSD M15→H4 | Fast/slow CCI cloud transition | `test_0082_0887_cci_woodies.py` |
| Gold HMM trend following | XAUUSD daily, 2024-2025 | Gaussian HMM regimes with confidence gating | `test_0002_gold_hmm_trend_following.py` |
| Risk parity + trend gate | Gold/silver/JPY/CHF/IEF daily | Inverse-volatility weights, 200-day MA gate | `test_0003_risk_parity_trend.py` |

## Deep Dive 1: Golden Cross — 13 Trades in 18 Years

Statistically, a golden cross is a crossing test between two sample means: the 50-day average is a proxy for recent momentum, the 200-day for the long-run baseline. The signal is sparse, lagging, and very quiet.

The implementation ([test_0175](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0175_golden_cross.py)) precomputes signals in pandas and keeps the strategy side dumb:

```python
out['ma_fast'] = out['close'].rolling(window=fast_period).mean()   # fast = 50
out['ma_slow'] = out['close'].rolling(window=slow_period).mean()   # slow = 200

out['golden_cross'] = ((out['ma_fast'].shift(1) <= out['ma_slow'].shift(1)) &
                       (out['ma_fast'] > out['ma_slow'])).astype(float)
out['death_cross'] = ((out['ma_fast'].shift(1) >= out['ma_slow'].shift(1)) &
                      (out['ma_fast'] < out['ma_slow'])).astype(float)

def next(self):
    golden_cross = float(self.data.golden_cross[0]) > 0.5
    death_cross = float(self.data.death_cross[0]) > 0.5
    if not self.position:
        if golden_cross:
            self.pending_order = self.buy(size=self._get_position_size(
                target_notional_pct=float(self.p.lot_size)))
        return
    if death_cross:
        self.pending_order = self.close()
```

Note the `shift(1)`: the cross must compare the *previous* bar's averages, so a signal cannot retro-fit itself on the current bar.

**The pinned baseline.** XAUUSD daily 2008-2025, 1,000,000 initial, 0.02% commission: 13 trades, 4 wins and 8 losses (one open), a 30.77% win rate, final value **3,571,828.03** (+257.18%), profit factor 2.04, max drawdown 37.54%. The test pins every number with tolerances like `abs(final_value - 3571828.03) < 3.6`. A 31% win rate making 2.5x on the back of a 2:1 payoff profile is trend following in one sentence: cut losses, let winners run.

The neighboring control group sharpens the point. The price-crossing variant ([test_0001](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0001_sma_trend_following.py)) trades 65 times (16.92% win rate) for a similar 3,686,124.79 — five times the turnover for the same money. And the death-cross-reverse strategy ([test_0174](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0174_death_cross_reverse.py)) bets on the *opposite* side of the same signal: 12 trades, 75% win rate, +28.41%. Same indicator, three coherent uses.

## Deep Dive 2: Original Turtle Rules — the Signal Is 10% of the System

The minimal Turtle rule fits in one line (see [No. 15](15-breakout.md) for the Donchian minimal version). The full rulebook Richard Dennis handed his students is mostly *position engineering*: ATR-sized units, pyramiding every 1×ATR of favorable movement, a 4-unit cap. [test_0074](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0074_0776_original_turtle_rules_trader.py) ports all of it — `n_st=20` (system-one channel), `n_lt=55` (backup channel after a failed breakout), `n_exit=10`, `atr_period=20`, `max_risk=0.01`.

The soul of the system is the unit size — **each unit risks only 1% of equity, converted to lots through ATR**:

```python
def _unit_size(self):
    atr = float(self.atr[-1]) if len(self) > 1 else float(self.atr[0])
    if atr <= 0:
        return self.p.volume_min
    equity = self.broker.getvalue()
    risk_budget = equity * self.p.max_risk            # 1% of equity per unit
    unit = risk_budget / max(atr * self.p.stop_loss * self.p.multiplier, 1e-9)
    return self._round_volume(unit)
```

Entries fire on a 20-day channel break (a 55-day backup re-confirmation follows a failed breakout); stops sit 1×ATR from entry; and each new unit of profit adds another unit:

```python
st_upper = self._channel_max(self.p.n_st)
st_breakout = self._breakout(close, st_upper, st_lower)
if st_breakout == 0:
    return
unit = self._unit_size()
self._set_risk_prices(st_breakout, close)             # stop = entry ∓ 1×ATR
self.entry_order = self.buy(size=unit) if st_breakout > 0 else self.sell(size=unit)

# inside the position manager: add a unit every adding_interval × ATR of profit
if (close - self.last_entry_price) * current_direction > self.p.adding_interval * atr:
    self.entry_order = self.buy(size=unit) if current_direction > 0 else self.sell(size=unit)
```

Baseline on three months of XAUUSD M15: 6,109 bars, 345 trades, 173 wins vs 172 losses (50.14% win rate), final value **1,190,431.17** (+19.04%), profit factor 1.23, max drawdown just 8.08%. A coin-flip win rate that still compounds — the profit lives entirely in the position structure: add into trends, stop at the start of them.

## Deep Dive 3: Gold HMM — Making "Regime" Computable

"Is this a bull market?" Humans answer with feel; a hidden Markov model answers with posterior probabilities. [test_0002](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/trend_following/test_0002_gold_hmm_trend_following.py) is a hand-written 431-line test that rolls a 3-state `GaussianHMM(covariance_type="full")` over gold daily bars — retrained every 21 days on a 252-day window, using just two features: log returns and 20-day annualized volatility. Raw states are then *labeled* BULL/BEAR/NEUTRAL by their mean return on the training set.

A state alone is not enough; the model must also be confident:

```python
vol_factor = min(target_volatility / max(float(current_row["volatility_20"].iloc[0]), 1e-6),
                 max_target_percent / max(base_target_percent, 1e-6))
dynamic_target = min(max_target_percent, base_target_percent * current_confidence * vol_factor)
if current_confidence < state_persistence_min or persistence < state_persistence_min or consistent < 0.5:
    dynamic_target = 0.0
```

Target exposure is `min(0.10, 0.03 × confidence × volatility factor)`, and any of three trust checks — state posterior, transition-matrix stickiness, three consecutive same-state days — falling below 0.7 zeroes the position. Once unrealized profit reaches 8%, the stop ratchets from −3% to break-even. Result over 2024-2025: 245 daily bars, just 6 trades (3 wins, 3 losses), final value 1,001,059.99 — roughly flat after commissions. Two engineering habits worth stealing: `pytest.importorskip("hmmlearn")` degrades gracefully when the ML dependency is absent, and HMM features are precomputed in pandas, keeping the backtest engine itself pure.

## The Rest of the Bench

- **MACD, three fates** (`test_0116`/`test_0163`/`test_30`): the MT5 official template with a zero-axis filter loses gently (-0.19%, PF 0.60); the naked stop-and-reverse crossover bleeds slower (-0.72% over 474 trades); and the MACD+KDJ combo with all-in sizing turns 100,000 into 5,870.49 — a 98.63% drawdown preserved forever as a lesson: sizing *is* the strategy.
- **ADX gates and trailing stops** (`test_0064`, `test_0140`): the ADX+MA gate wins 45.5% and loses money; the ATR chandelier wins only 35.5% yet profits (PF 1.117, Sharpe 4.40). Two baselines, one verdict on win rate vs payoff.
- **Woodies CCI** (`test_0082`): the community-evolved CCI cloud is the risk-adjusted standout of the confirmation family — PF 1.274, Sharpe 5.34, max drawdown 0.077%.
- **Risk parity + 200-day gate** (`test_0003`): five safe-haven assets, monthly inverse-volatility weights, trend-gated to cash — 18 years, 206 rebalances, a 26% win rate, +23.6%.
- **Dual-timeframe architecture** (`test_0078`): signals on a resampled H4 stream, orders on M15 — the standard skeleton for half the category's MT5 ports.

## Run It Yourself

```bash
# The whole category (300+ strategies, runonce/runnext parity asserted automatically)
pytest tests/functional/strategies/trend_following/ -v

# Just the Golden Cross
pytest tests/functional/strategies/trend_following/test_0175_golden_cross.py -v
```

## Why Study Trend Following Here

Trend systems live on parameter sweeps — MA periods, channel lengths, ATR multipliers, pyramid intervals — and every knob changes the trade distribution. That is exactly what [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) is built for: 46% faster than the original in pure Python (all 1,152 strategy regressions finish in minutes), a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) that turns a Turtle-parameter grid into a coffee break, runonce/runnext dual-mode parity so vectorized and event-driven engines must agree, and asserted metric baselines so you optimize the strategy — not chase the engine's numerical drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/01-trend-ma-crossover.md), [here](../zh/02-trend-channel-breakout.md), and [here](../zh/06-trend-statistical-thematic.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
