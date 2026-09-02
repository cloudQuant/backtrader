# Pairs Trading: Gold/Silver Z-Scores, Kalman Betas, and Copulas

> Strategy Compendium · No. 11 · Category `pairs_trading` (22 strategies) · 2026-09-02

"The gold/silver ratio always comes back" is a trader's intuition centuries old. What turned it into a business was the statistical arbitrage desk at Morgan Stanley in the 1980s: Gerry Bamberger first discovered that pairing longs and shorts within an industry hedges away market risk; Nunzio Tartaglia's group then systematized "pairs trading" — with Nassim Taleb, the future author of *The Black Swan*, among its members. That desk proved one thing: **you can profit without predicting direction — you only bet that the spread comes home.**

The core concept is cointegration, not correlation. Correlation says "move together"; cointegration says "never drift too far apart" — two prices may each wander randomly, but as long as their spread is tethered to some mean, selling the rich leg and buying the cheap one has positive expectation. This article covers the 22 strategies in `tests/functional/strategies/pairs_trading/`: from the fixed-hedge gold/silver z-score, through Kalman-filter dynamic betas, to the copula version that models tail dependence.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Gold/silver pairs | XAUUSD/XAGUSD H1 2025 | Log spread + fixed hedge, rolling z-score thresholds | `test_0002_gold_silver_pairs_trading.py` |
| Kalman filter pairs | XAUUSD/XAGUSD H1 | Kalman-estimated dynamic beta, stability-gated entries | `test_0001_gold_kalman_filter_pairs_trading.py` |
| Copula pairs | XAUUSD/XAGUSD daily 2018-2025 | Clayton copula conditional probability flags mispricing | `test_0007_copula_pairs_trading.py` |
| Cointegration spread | Gold/silver daily | Cointegration-tested spread, z-score entries | `test_0003_gold_cointegration_spread.py` |
| Cointegrated (regression) | Gold/silver daily | Engle-Granger-style residual trading | `test_0006_cointegrated_gold_silver.py` |
| Distance pairs | XAUUSD daily | Gatev 1999: minimize normalized price distance | `test_0013_distance_pairs_trading.py` |
| Multi-pair basket | Gold/silver/platinum/palladium daily | Several pairs traded side by side | `test_0004_gold_multi_pair_trading.py` |
| Zero-crossing pairs | Gold/silver H1 | Bet on the spread crossing zero, not mean-reversion bands | `test_0005_zero_crossing_pairs.py` |
| CAD/crude pairs | USDCAD/BNO daily | A macro pair: Canada's economy rides oil | `test_0014_cad_crude_pairs_strategy.py` |
| Renko/Kagi pairs | Gold/silver H1 | Non-standard bars denoise pair signals | `test_0015_renko_kagi_pairs_strategy.py` |
| Copula (variant) | XAUUSD daily | A second copula parameterization | `test_0011_copula_pairs_trading.py` |
| MT5 EA ports | XAUUSD M15 | Single-leg EA ports (hedging/pending/TRIX/Laguerre/VLT) | `test_0017`-`test_0022` |

## Deep Dive 1: Gold/Silver — the Z-Score Three-Piece Kit

Every textbook element of pairs trading fits on one page of [test_0002](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pairs_trading/test_0002_gold_silver_pairs_trading.py). Step one, define the log spread with a fixed hedge ratio:

```python
def _spread(self):
    gold_price = max(float(self.gold.close[0]), 1e-6)
    silver_price = max(float(self.silver.close[0]), 1e-6)
    return math.log(gold_price) - float(self.p.hedge_ratio) * math.log(silver_price)
```

Step two, a rolling z-score over 192 bars. Step three, three thresholds managing the position:

```python
if not has_position:
    if zscore <= -float(self.p.entry_threshold):      # entry = 2.0, spread cheap: buy gold, sell silver
        self._open_long_spread()
    elif zscore >= float(self.p.entry_threshold):     # spread rich: sell gold, buy silver
        self._open_short_spread()
    return
if abs(zscore) <= float(self.p.exit_threshold) or abs(zscore) >= float(self.p.stop_threshold):
    self._close_all()     # exit = 0.5 on reversion; stop = 3.0 when the spread runs away
```

Each leg is sized at 5% notional (`max_notional_pct=0.05`). **The backtest:** gold/silver H1 bars from July to December 2025, 2,986 bars, 102 pair trades, 46 wins against 56 losses (45.1%), final value 990,238 (−0.98%), Sharpe −1.91, max drawdown a contained 1.67%. Small sizing caps the damage, but the fixed `hedge_ratio=1.0` is the visible weak point — the gold/silver ratio's center has drifted from around 60 to 120 over two decades, and a static ratio eats that drift as a loss. Hence the second deep dive.

## Deep Dive 2: the Kalman Filter — a Beta That Moves

If the relationship drifts, make the hedge ratio β a state variable and estimate it online. [test_0001](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pairs_trading/test_0001_gold_kalman_filter_pairs_trading.py) runs a one-dimensional Kalman filter, updating "how many ounces of silver per ounce of gold" bar by bar:

```python
def update(self, price_a, price_b):
    beta_pred = self.beta
    P_pred = self.P + self.Q                       # process noise Q = 0.0005
    denominator = P_pred * price_b * price_b + self.R   # observation noise R = 1.0
    K = (P_pred * price_b) / denominator           # Kalman gain
    innovation = price_a - beta_pred * price_b     # residual = new spread information
    self.beta = beta_pred + K * innovation         # beta adapts to new evidence
    self.P = (1.0 - K * price_b) * P_pred
    spread = price_a - self.beta * price_b
    return self.beta, spread
```

Seeded at `initial_beta=78.0` (roughly the historical ratio), it is data-driven thereafter. The masterstroke is the **beta stability gate**: entries are allowed only when the coefficient of variation of β over the last 96 bars stays under 0.03 — when the relationship is unstable, stand aside:

```python
if self.current_zscore <= -float(self.p.entry_threshold) and is_stable:
    self._submit_pair_orders(1, price_a, price_b)   # entry = 2.0, exit = 0.35, stop = 3.25
```

**The backtest:** the same H1 data, 103 closes (61 wins against 42 losses, 59.2%, including 9 stops), final value 997,507 (−0.25%). Against Deep Dive 1: win rate up from 45% to 59%, drawdown smaller — the value of a dynamic β is not earning more, but being wrong less.

## Deep Dive 3: the Copula — Not Just the Spread, but "Extreme Together?"

A z-score silently assumes the spread is elliptically distributed, but gold/silver coupling lives in the tails: in panics, gold up and silver down can be extreme simultaneously. The copula approach models the joint distribution directly ([test_0007](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pairs_trading/test_0007_copula_pairs_trading.py)): estimate a Clayton copula parameter from Kendall's tau over a 252-day rolling window (Clayton captures lower-tail dependence), then compute "the conditional probability of silver's move, given gold's":

```python
tau = stats.kendalltau(u, v).correlation
theta = 2.0 * tau / max(1e-6, 1.0 - tau)       # tau -> theta
def clayton_conditional(u, v, theta):
    term1 = u ** (-(theta + 1.0))
    term2 = (u ** (-theta) + v ** (-theta) - 1.0) ** (-(theta + 1.0) / theta)
    return term1 * term2                        # P(V<=v | U=u)
```

Read the conditional probability like this: `P(V<=v|U=u)` near zero means "gold barely moved, yet silver tanked" — silver is the mispriced leg; buy silver, sell gold, hedged by the rolling beta. The thresholds:

```python
if prob_v_given_u < entry_threshold:            # 0.05, silver distinctly cheap
    position = 1
elif prob_v_given_u > 1.0 - entry_threshold:    # silver distinctly rich
    position = -1
if abs(prob_v_given_u - 0.5) <= exit_band:      # 0.10, back in the neutral band: flatten
    position = 0
```

**The backtest:** gold/silver daily 2018-2025, 1,812 bars, 292 trades with 136 wins (46.6%), final value 986,607 (−1.34%), Sharpe −0.24. All three deep dives lost money — not by accident: in increasingly efficient markets, plain statistical arbitrage stopped printing money long ago. The regression library records them faithfully to give "is pairs trading easy?" an honest, asserted answer; the improvement paths (longer holds, cross-commodity baskets, cost modeling) each have worked examples elsewhere in the category.

## The Rest of the Bench

- **Distance pairs** (`test_0013`): Gatev's 1999 paper — pick the pair minimizing normalized price distance, exit on reversion; the archaeological edition.
- **Multi-pair basket** (`test_0004`): all pair combinations of gold/silver/platinum/palladium, diversifying single-spread risk.
- **CAD/crude** (`test_0014`): the macro pair — Canada's economy rides oil, so trade the USDCAD/BNO spread.
- **Renko/Kagi** (`test_0015`): non-standard bars as a noise filter for pair signals.
- **EA ports** (`test_0017`-`test_0022`): MT5 single-leg strategies (LBS, timed pending orders, TRIX, minimal hedging, Laguerre, VLT Trader) — handy material for M15 execution details.

## Run It Yourself

```bash
# The whole category (22 strategies)
pytest tests/functional/strategies/pairs_trading/ -v

# Just the gold/silver z-score pair
pytest tests/functional/strategies/pairs_trading/test_0002_gold_silver_pairs_trading.py -v
```

## Why Study Pairs Trading Here

Pairs trading is the harshest exam a backtest engine can take: multi-feed timestamp alignment, simultaneous two-leg ordering, margin math on net-short books, per-trade commissions — miss one link and the best spread signal is worthless. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) provides multi-asset infrastructure forged by 1,152 strategy regression tests: 46% faster than the original in pure Python, a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) so a sweep over z-score windows, thresholds, and hedge modes takes minutes, plus runonce/runnext dual-mode parity and asserted metric baselines — so every drift you measure comes from the market, not the engine.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/24-pairs-trading.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
