# Pivot Points and Fibonacci: The Numbers Every Intraday Trader Watches

> Strategy Compendium · No. 24 · Category `pivot_fibonacci_system` (6 strategies) · 2026-09-02

Before computers took over the trading floor, pit traders did the same arithmetic every morning with a pencil: yesterday's high plus low plus close, divided by three. That number is the pivot; from it radiate three rungs of resistance and three of support — a price map for the day, drawn in ten minutes and pinned to the desk. A century later the same formula is still being computed automatically; only the pencil has become Python.

Why does such a crude formula survive? One explanation is a **self-fulfilling prophecy**: because enough people watch the same numbers, price really does react there. Fibonacci retracements push the idea to its limit — 38.2%, 50%, 61.8% have no physical basis, but when every charting platform draws lines at the same ratios, expectation itself manufactures support and resistance. This article covers the 6 strategies in `tests/functional/strategies/pivot_fibonacci_system/`, all running on gold (XAUUSD) M15 data — psychological coordinates, quantified.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| MostasHaR15 pivot | XAUUSD M15 + H1 | 13 pivot levels from yesterday's OHLC; ADX/DI/OSMA multi-confirmation breakout | `test_0001_mostashar15_pivot.py` |
| SimplePivot | XAUUSD M15 → daily | Yesterday's mid-high/low sets direction; always in, flip on signal | `test_0002_simplepivot.py` |
| PivotHeiken 3 | XAUUSD M15 + D1 | Smoothed Heikin-Ashi momentum + daily pivot mean reversion | `test_0003_pivotheiken_3.py` |
| Fibo iSAR | XAUUSD M15 | 50% limit entry, 161% take profit + dual-speed Parabolic SAR | `test_0004_fibo_isar.py` |
| FiboCandles | XAUUSD M15 → H1 | Range × fibo ratios build color-flip candles; color change = signal | `test_0005_fibocandles.py` |
| Volatility pivot | XAUUSD M15 → H4 | ATR-driven moving pivot flip line; reversal flips position | `test_0006_volatility_pivot.py` |

## Deep Dive 1: MostasHaR15 — Thirteen Levels and Four Confirmations

[test_0001_mostashar15_pivot.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pivot_fibonacci_system/test_0001_mostashar15_pivot.py) first replicates the pit trader's pencil work in full — pivot plus every derived level, intermediate M0-M5 rungs included:

```python
p = (yh + yl + yc) / 3.0
r1 = (2.0 * p) - yl
s1 = (2.0 * p) - yh
r2 = p + (yh - yl)
s2 = p - (yh - yl)
r3 = (2.0 * p) + (yh - (2.0 * yl))
s3 = (2.0 * p) - ((2.0 * yh) - yl)
m5 = (r2 + r3) / 2.0
m4 = (r1 + r2) / 2.0
...
```

Thirteen levels slice the price axis into twelve segments. The strategy first locates which segment price occupies, then demands **more than 14 points of room below the next resistance** before considering entry — it refuses to buy right under a ceiling. What separates it from a textbook pivot system is the four-way confirmation on the H1 timeframe:

```python
if dif2 > 14 and self.adx[0] > 20 and self.plus_di[0] > self.plus_di[-1] and self.plus_di[0] > self.minus_di[0] and (self.ma_close[0] - self.ma_open[0]) >= ext_step and self.ma_close[-1] > self.ma_open[-1] and self.osma[0] > self.osma[-1]:
```

ADX above 20 (a trend exists), +DI rising and above -DI (direction is up), dual EMAs on close/open spreading for two bars (momentum confirms), OSMA histogram climbing (MACD pushes). The pivot answers "*where*"; four indicators jointly answer "*may I*." The baseline is sobering: 6,001 M15 bars produce 387 trades (200 wins, 187 losses) and a final value of 999,163.7 — a million in capital, three months of combat, 387 round trips, net standing still. No number states the cost-sensitivity of intraday breakout trading more plainly.

## Deep Dive 2: Fibo iSAR — A Limit Order Waiting at the 50% Retrace

[test_0004_fibo_isar.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/pivot_fibonacci_system/test_0004_fibo_isar.py) is the complete engineering specimen of Fibonacci trading. Direction comes from a dual-speed Parabolic SAR (fast 0.02/0.2, slow 0.01/0.1); entry waits at the 50% retracement of the swing, take profit sits at the 161.8% extension:

```python
def _get_fibo(self, high, low, level):
    return round(low + (high - low) * level, self.p.price_digits)

...
op = self._get_fibo(max_price, min_price, self.p.fibo_entrance_level / 100.0)   # 50.0
tp = self._get_fibo(max_price, min_price, self.p.fibo_profit_level / 100.0)     # 161.0
sl = round(min_price - self.p.indent_stop_loss * self._trade_unit(), self.p.price_digits)

if self.pending_buy is None and not self._has_position_side(True):
    valid = bt.num2date(self.data0.datetime[0]) + pd.Timedelta(minutes=15 * self.p.order_valid_bars)
    self.pending_buy = self.buy(size=self.p.size, exectype=bt.Order.Limit, price=op, valid=valid)
```

Three engineering details to steal. First, `exectype=bt.Order.Limit` *waits* for the pullback instead of chasing at market — a retracement strategy lives or dies on that one parameter. Second, `valid` gives the order a 45-minute lifetime (3 M15 bars): if price never pulls back, the order expires and levels are recomputed, so no stale "good price" lurks in the book. Third, the stop sits 30 trade-units beyond the swing extreme and then trails in 10/5 steps as profit accrues — entry, expiry, and trailing each have an explicit clock and ruler. Baseline: 6,128 bars, 335 trades, 194 wins / 141 losses, final value 1,005,690.9 — one of the few on the profitable side of this category.

## The Rest of the Bench

- **SimplePivot** (`test_0002`): the fruit knife to the first two strategies' heavy machinery. Pivot is just the midpoint of yesterday's high/low; direction is wherever the open lands — below yesterday's high but above the midpoint means short, otherwise long — always in the market, flipping via `notify_order`'s close-first-then-reopen choreography. ~3 months of daily data (resampled from M15), 25 trades, 15 wins / 10 losses.
- **PivotHeiken 3** (`test_0003`): LWMA double-smoothed Heikin-Ashi momentum as a mean-reversion trigger below the daily pivot — 6,038 bars, a category-high 1,584 trades.
- **FiboCandles** (`test_0005`): multiplies the range by fibo ratios (0.236/0.382/0.5/0.618/0.762, five selectable) as color-flip thresholds — 6,093 bars, 95 trades, 56 wins / 39 losses.
- **Volatility Pivot** (`test_0006`): the pivot becomes a moving flip line that breathes with ATR(100)×3 — 4,446 bars, just 9 trades. The most patient of the six.

## Run It Yourself

```bash
# The whole category (6 strategies)
pytest tests/functional/strategies/pivot_fibonacci_system/ -v

# Just Fibo iSAR
pytest tests/functional/strategies/pivot_fibonacci_system/test_0004_fibo_isar.py -v
```

## Why Study Pivots and Fibonacci Here

All six strategies run on M15 data with multi-timeframe feeds, limit orders, order lifetimes, and bar-by-bar trailing stops — each feature is a stress test of the engine's event-driven path, and being one bar off anywhere rewrites MostasHaR15's 387-trade win/loss distribution. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) pins every count, win/loss tally, and final value into asserted baselines across 1,152 strategy regression tests, with runonce/runnext dual-mode parity ensuring both engine paths emit the identical trade list. The pure-Python engine runs 46% faster than the original; the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — so "3 months of M15 × 6 strategies" regresses faster than you can watch the chart.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/37-pivot-fibonacci.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
