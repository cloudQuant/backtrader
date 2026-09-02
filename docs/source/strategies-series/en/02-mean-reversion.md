# Mean Reversion: Connors RSI2, Double 7s, and 331 Ways to Buy Fear

> Strategy Compendium · No. 02 · Category `mean_reversion` (331 strategies) · 2026-09-02

When Wells Wilder invented the RSI in 1978, the prescribed usage was: 14 periods, above 70 is overbought — consider selling, below 30 is oversold — consider buying. Thirty years later Larry Connors turned that doctrine upside down: cut the period to 2, cut the threshold to 5, and **only ever buy oversold in an uptrend**.

That is a complete reinterpretation of the word "oversold." In Wilder's frame, an RSI of 20 means falling momentum — stay away. In Connors' frame, an extremely oversold reading inside a long-term uptrend is precisely the golden dip-buy, because the "mean" you are reverting to is itself rising. This digest walks the 331 backtests in `tests/functional/strategies/mean_reversion/` through three of them: the classic RSI2, the smoothed-oscillator school of KDJ and DiNapoli, and Connors' one-line classic Double 7s. A bonus: 256 of these tests are annotated `source_ea` ports from the MQL ecosystem, each keeping its original pips-and-lots semantics.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Connors RSI2 (classic) | XAUUSD daily, 2008-2025 | RSI(2)<5 above the 100-SMA; exit when RSI recrosses 30 | `test_0004_rsi2_mean_reversion.py` |
| ConnorsRSI (composite) | XAUUSD daily | RSI(3)+streak RSI(2)+percent rank, limit orders | `test_0020_connorsrsi_mean_reversion.py` |
| Double 7s | XAUUSD daily | Buy a 7-day low above the 200-SMA; sell a 7-day high | `test_0002_double_7s_mean_reversion.py` |
| Consecutive down days | XAUUSD daily | Buy after 3-5 down days, hold one day | `test_0008_consecutive_down_days.py` |
| Efficiency-ratio MR | XAUUSD daily | Choppy market (ER<50) + RSI(2)<10 | `test_0041_efficiency_ratio_mean_reversion.py` |
| KDJ trading system | XAUUSD M15→H1 | KDJ(30,3,6) crosses + midline direction | `test_0239_0515_kdj_trading_system.py` |
| DiNapoli Stochastic | XAUUSD M15→H6 | 8/3/3 double-smoothed stochastic, reversed | `test_0275_1013_dinapoli_stochastic.py` |
| BB Squeeze (TTM-style) | XAUUSD M15 | Bollinger inside Keltner; trade the release | `test_0224_1300_bb_squeeze.py` |
| Three crows/soldiers × 4 | XAUUSD M15 | Same pattern detector, RSI/MFI/CCI/Stoch swapped | `test_0225_1343_three_crows_soldiers_rsi.py` |
| Cointegration z-score | XAUUSD daily | z < -2 buys; exit inside \|z\| < 0.5 | `test_0009_cointegration_mean_reversion_gold.py` |
| Pairs trading (V/MA) | Visa/Mastercard daily | Rolling OLS z-score at ±2.5 | `test_63_pairs_trading_strategy.py` |

## Deep Dive 1: Connors RSI2 — Buying Oversold Inside the Trend

The whole rule compresses to one sentence: **when the long-term trend is up, short-term panic is a gift.** The implementation ([test_0004](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0004_rsi2_mean_reversion.py)) runs 17 years of gold daily bars with four parameters:

```python
params = dict(
    rsi_period=2,           # ultra-short: exhaustion within two bars
    rsi_buy_threshold=5,    # not 30 — extreme oversold
    rsi_sell_threshold=30,  # exit on recovery, no greed
    sma_period=100,         # the safety line: only long above it
)

out['buy_signal'] = ((out['rsi'] < rsi_buy) &
                     (out['close'] > out['sma'])).astype(float)
out['sell_signal'] = (out['rsi'] > rsi_sell).astype(float)
```

Two design choices deserve chewing. `rsi_period=2` makes the RSI a panic meter — two down days drive it under 5. And `sma_period=100` is the seatbelt: in 2008, 2013, or 2021-style crashes the RSI(2) hugs the floor for weeks, but with price below the mean, not one signal fires.

The asserted baseline: 4,538 daily bars, 311 trades, **67.85% win rate**, final value **1,703,436.24** (+70.34%), max drawdown 17.37%, SQN 2.06. Not a fortune machine — but a four-parameter rule system holding two-thirds winners over 17 years is exactly why this is the textbook of short-term reversion. Its composite sibling ([test_0020](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0020_connorsrsi_mean_reversion.py)) averages price momentum, *streak* RSI (RSI of the win/loss streak itself), and percent rank into one score, then enters via limit orders 0.3% below yesterday's close: just 38 fills in 17 years (14 limit orders expired unfilled), 78.95% win rate, profit factor 3.38, max drawdown 6.42%. Pickier entry, cheaper fills, shallower drawdowns — "less is more" with receipts.

## Deep Dive 2: KDJ and DiNapoli — Taming a Twitchy Oscillator

Raw oscillators jitter; the interesting engineering question is how to make them tradeable. The KDJ system ([test_0239](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0239_0515_kdj_trading_system.py)) — the stochastic's Chinese-market evolution — computes KDJ(30, 3, 6) on an H1 resampled feed and executes on M15:

```python
self.kdj = bt.indicators.KDJIndicator(self.data_h1, m1=3, m2=6, kdj_period=30)

# long: the KDC midline flips positive (cross), or K is positive and still rising
if (val_kdc_prev < 0.0 and val_kdc_current > 0.0) or \
   (val_kdc_current > 0.0 and (val_k_prev - val_k_current) < 0.0):
    self.stop_price = self._round(price - sl_dist)        # 25-point stop
    self.take_profit_price = self._round(price + tp_dist) # 45-point target
    self.order = self.buy(data=self.data, size=float(self.p.lots))
```

Three months of M15: 1,149 trades, 50.22% win rate, profit factor 1.16, final value 1,006,404 — thin-edge, high-volume reversion earning discipline and spread control.

DiNapoli goes the opposite way: slow the oscillator down. [test_0275](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0275_1013_dinapoli_stochastic.py) takes an 8-period raw %K, then applies recursive exponential smoothing twice:

```python
res = 100.0 * (frame['close'] - lowest) / raw_range     # 8-period raw %K

for value in res.tolist():
    prev_sto = prev_sto + (float(value) - prev_sto) / max(1, int(slow_k))  # 3-period main
    prev_sig = prev_sig + (prev_sto - prev_sig) / max(1, int(slow_d))      # 3-period signal

buy_signal = (sto.shift(1) > sig.shift(1)) & (sto <= sig)   # main crosses BELOW signal = buy
```

Read that last line twice: the main line crossing *below* the signal line is the buy — pure contrarian, betting price follows the oscillator's first step down from a high. Signals evaluate on a 6-hour frame; the result is 24 trades in three months (14 wins, 9 losses, 58.33%), final value 1,000,797.20. Two smoothings turn an aggressive reversal rule into a low-frequency, holdable system.

## Deep Dive 3: Double 7s — A Classic Rule, Frozen in Assertions

Blog folklore mutates: parameters drift, conditions get added, samples get cherry-picked. The cure is freezing the rule in code and pinning the result. Connors' Double 7s — originally for the S&P 500 — is rendered verbatim in [test_0002](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/mean_reversion/test_0002_double_7s_mean_reversion.py):

```python
out['sma'] = out['close'].rolling(sma_period).mean()      # 200-day trend filter
out['n_day_low'] = out['close'].rolling(n_low).min()      # 7-day low
out['n_day_high'] = out['close'].rolling(n_high).max()    # 7-day high

out['buy_signal'] = ((out['close'] > out['sma']) &
                     (out['close'] <= out['n_day_low'])).astype(float)
out['sell_signal'] = (out['close'] >= out['n_day_high']).astype(float)
```

On gold daily 2008-2025 with 0.02% commission: 148 trades, **66.89% win rate**, final value **2,138,567.90**, Sharpe 0.566 — with a 30.35% max drawdown as the bill for Connors' signature *no-stop* philosophy (time-based exit instead of price stops, so you are never shaken out at maximum fear). The neighboring `test_0010_double_n_gold.py` re-implements the same idea with N instead of 7 and asserts identical numbers — two independent implementations proving the rule didn't warp in translation. Related frozen classics: consecutive-down-days (203 trades, 56.65%, final 1,167,207.74 — note the -0.1% daily threshold and the 5-day cap that refuses falling knives) and the efficiency-ratio gate (548 trades, final 2,700,065.50) that only buys oversold when Kaufman's ER says the market is choppy.

## The Rest of the Bench

- **BB Squeeze** (`test_0224`): the category's traitor — after a Bollinger-inside-Keltner compression, it trades *momentum* on the release: 309 trades, 40.78% win rate, PF 1.27.
- **The 3σ touch-reversion** (`test_0140_0616_bollinger.py`): an 80-period, 3σ band requiring the *whole bar* outside the band — 4 trades in 6,050 bars, all winners, final value 999,218.55. Signal quality versus signal quantity, quantified.
- **A four-way confirmator experiment** (`test_0225`–`test_0228`): identical three-crows/soldiers detector, only the confirming oscillator swapped (RSI/MFI/CCI/Stoch) — the cleanest design for studying "which confirmator."
- **Statistical tail** (`test_0009`, `test_63`): gold z-score reversion wins 63.46% to a final 1,289,841.82; the Visa/Mastercard pairs trade finishes flat with a 1.157% max drawdown — and doubles as a runonce/runnext parity exemplar.

## Run It Yourself

```bash
# The whole category (331 strategies, runonce/runnext parity asserted automatically)
pytest tests/functional/strategies/mean_reversion/ -v

# Just the classic Connors RSI2
pytest tests/functional/strategies/mean_reversion/test_0004_rsi2_mean_reversion.py -v
```

## Why Study Mean Reversion Here

The RSI family is among the most parameter-sensitive in existence — period 2 or 3, threshold 5 or 10, mean 100 or 200; every knob reshapes the trade distribution, and without mass reproduction you cannot tell edge from luck. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) is built for exactly this: 46% faster than the original in pure Python (all 1,152 strategy regressions finish in minutes), a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) that shrinks a period-by-threshold grid scan to a coffee break, runonce/runnext dual-mode parity, and asserted metric baselines — so the differences you measure are the strategy's, not the engine's.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/07-mr-rsi.md), [here](../zh/08-mr-oscillators.md), and [here](../zh/11-mr-classic-rules.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
