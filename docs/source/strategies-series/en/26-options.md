# Options Strategies: Expiration-Week Drift and the Art of Collecting Premium

> Strategy Compendium · No. 26 · Category `options` (5 strategies) · 2026-09-02

The options market has a famous asymmetry: most buyers lose money, yet the market cannot exist without them — insurance buyers pay the premium, insurance sellers collect it. Quant trading grew two very different playbooks on top of that structure. One bets on **calendar regularities** (price drift during options expiration week, the "pinning" effect); the other simply **stands on the sell side** and collects premium (put writes, covered calls).

Pinning is not mysterious: as expiration approaches, market makers' gamma exposure piles up around strikes — hedging flows buy above the strike and sell below it, and the price gets "pinned" back. Expiration week therefore behaves differently in volatility, volume, and price — prime hunting ground for calendar strategies. Seller strategies, meanwhile, have a lottery-ticket payoff by construction: many small wins, occasional disasters. The left tail is the real product being sold.

This article walks through the 5 options backtests in `tests/functional/strategies/options/`. Since the framework does not embed an option pricing engine, these tests demonstrate a different engineering route: approximating option behavior on pure stock/ETF data streams with realized volatility, synthetic NAV, and simplified pricing formulas.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Expiration week (XAUUSD) | Gold daily, 2008-2025 | Long-only in bullish months (3/4/10/12), Monday-to-Friday, month-weighted | `test_0001_options_expiration_week_strategy.py` |
| Expiration week (GLD) | GLD daily, 2008-2025 | Monthly bull/bear bias sets direction: long bulls, short bears, Monday in, Friday out | `test_0002_options_expiration_week.py` |
| Low-volatility options combo | JEPI/PBP/IVV daily | Three-sleeve combo of low-vol equity, covered call, synthetic put-write with vol targeting | `test_0003_low_volatility_options.py` |
| Options valuation | Gold daily, 2008-2025 | Realized-vol percentile as an IV-rank proxy: long below 0.2, exit above 0.8 | `test_0004_options_valuation.py` |
| GLD put write | GLD daily, 2010-2025 | Cash-secured 30-day put selling with volatility-based approximate pricing | `test_0005_gld_put_write_strategy.py` |

## Deep Dive 1: Options Expiration Week — the Hidden Script in the Calendar

US equity and index options expire on the third Friday of each month. Around that week, hedging flows (gamma hedging, rolling) are believed to suppress or push the spot price. This strategy does not try to predict *where* pinning happens — it bets on a coarser claim: **certain months exhibit systematic drift during expiration week**.

[test_0002_options_expiration_week.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/options/test_0002_options_expiration_week.py) first locates the expiration week with a calendar algorithm, assigns each month a bull/bear bias, then enters Monday and exits Friday:

```python
def _third_friday(year, month):
    month_calendar = calendar.monthcalendar(year, month)
    friday_count = 0
    for week in month_calendar:
        if week[calendar.FRIDAY] != 0:
            friday_count += 1
            if friday_count == 3:
                return week[calendar.FRIDAY]          # third Friday of the month

monday_day = third_friday - 4                          # Monday = Friday minus 4 days
in_week = monday_day <= idx.day <= third_friday and idx.weekday() <= 4
bias = 1.0 if idx.month in bullish_months else (-1.0 if idx.month in bearish_months else 0.0)
entry_signal.append(1.0 if in_week and idx.weekday() == 0 and bias != 0.0 else 0.0)
exit_signal.append(1.0 if in_week and idx.weekday() == 4 else 0.0)
```

Parameters declare months 1-5 and 9-12 bullish, 6-8 bearish, with 95% position size, a 2% stop-loss, and a 1.5% take-profit. The honest verdict is written into the assertions: on GLD 2008-2025 — 4,519 bars, 199 trades, 49.2% win rate, final value 947,033.84, a **5.3% loss**, Sharpe -0.02, max drawdown 32.89%. Hard-coded monthly biases do not even survive in-sample — a textbook example of the most common trap in seasonality research.

The engineering is worth studying: **features and strategy are layered**. Expiration-week flags, monthly bias, and entry/exit signals are all computed offline in pandas and attached as extra columns on a custom `PandasData` feed; `next()` reads just three lines (`entry_signal`, `exit_signal`, `direction`). Calendar logic and trading logic are fully decoupled — change one without touching the other, and the engine never needs to understand calendars.

## Deep Dive 2: GLD Put Write — What Premium Sellers Actually Earn

A cash-secured put write is the strategy of "I am willing to buy at this price, and you pay me a deposit first." The payoff is inherently twisted: **high probability of small wins (premium), small probability of large losses (catching a falling knife)** — high win rate, poisonous tail.

[test_0005_gld_put_write_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/options/test_0005_gld_put_write_strategy.py) prices the option with an approximation that skips full Black-Scholes:

```python
def _estimate_option_mark(self, spot, strike, days_to_expiry, realized_vol):
    vol = max(float(realized_vol or 0.0), 0.05)
    time_value = vol * math.sqrt(max(days_to_expiry, 1) / 365.0) * float(spot) * float(self.p.premium_factor)
    intrinsic = max(0.0, float(strike) - float(spot))
    return intrinsic + time_value

def _round_strike(self, price):
    strike = price * float(self.p.moneyness)           # 0.95 → 5% out-of-the-money
    return round(strike / 0.5) * 0.5                   # rounded to $0.50
```

The entry filter requires price above the 200-day average **and** RSI at or above 30 — no knife-catching mid-crash. While holding, the mark is re-priced daily at the new volatility; if the premium doubles (a 50% rise, the stop line), the put is bought back; otherwise it is held to the 30-day expiry. This open—mark-to-market—stop-or-expire loop is precisely the daily rhythm of a real option seller.

The backtest (2010-2025): 92 opens, 82 natural expiries, 9 stops, **win rate 81/91 ≈ 89%**, final value 1,156,219.97 (+15.6%). But remember what the 9 stops represent — the tail risk made visible. In a 2008-style market that number grows exponentially. Split the win rate from the payoff ratio: the flip side of 89% wins is how much those 9 stops must average to drag expectancy back to zero. The "comfort" of a put write is exactly where its danger lives.

## The Rest of the Bench

- **Expiration week, XAUUSD version** (`test_0001`): the same idea on spot gold, long-only in months 3/4/10/12 with October and December weighted 1.2x — month-weighting is one of the less arbitrary variants in calendar trading.
- **Low-volatility options combo** (`test_0003`): 0.5 parts JEPI + 0.25 parts PBP + 0.25 parts synthetic put-write, rebalanced every 63 days, 12% volatility target, risk halved when drawdown exceeds 20% — an institutional-style "options income all-weather" portfolio.
- **Options valuation** (`test_0004`): does not trade options at all — it treats "volatility is cheap/expensive" as a timing signal, going long when the 252-day percentile of realized volatility falls below 0.2 and exiting above 0.8.

## Run It Yourself

```bash
# The whole category (5 strategies)
pytest tests/functional/strategies/options/ -v

# Just the GLD put write
pytest tests/functional/strategies/options/test_0005_gld_put_write_strategy.py -v
```

## Why Study Options Here

Approximate option modeling is terrified of "the engine's numbers quietly changed": tiny drift in the `sqrt(days/365)` pricing term or the daily mark-to-market cash flows distorts every win-rate statistic. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) pins those numbers down with asserted metric baselines across its 1,152 strategy regression tests, and its runonce/runnext dual-mode parity guarantees the vectorized and event-driven engines produce the same premiums. The pure-Python engine is 46% faster than the original; the C++ backend (`pip install back-trader-cpp`) delivers a median 128x speedup — enough to sweep all 5 strategies across volatility parameters in minutes and see exactly how sensitive "approximate pricing" really is.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/39-options.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
