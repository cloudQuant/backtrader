# Breakout Strategies: From Turtle Rules to Dual Thrust and R-Breaker

> Strategy Compendium · No. 15 · Category `breakout` (6 strategies) · 2026-09-02

If you could study only one family of trading strategies, make it breakouts. The logic is disarmingly simple — "buy when price makes a new high" — yet it produced the most famous trading experiment in history: in the 1980s, Richard Dennis used a Donchian-channel breakout rule to turn 23 novices into the "Turtles," averaging ~80% annual returns, proving that trading can be taught as a system.

This article walks through the 6 breakout backtests in `tests/functional/strategies/breakout/`: two Donchian variants, the futures intraday duo Dual Thrust and R-Breaker, a volume-confirmed breakout, and a price-channel system. Each is a self-contained backtest you can reproduce with one command.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Donchian (classic) | ORCL daily, 2010-2014 | Enter on 20-day high, exit on 20-day low | `test_105_donchian_channel_strategy.py` |
| Donchian (backhacker) | ORCL daily | Same idea, alternate parameterization | `test_66_donchian_channel_strategy.py` |
| Dual Thrust | Glass futures FG889, minute bars | N-day range bands anchored at the open | `test_09_dual_thrust_strategy.py` |
| R-Breaker | Rebar futures RB889, minute bars | Six pivot levels; breakout + reversal logic | `test_10_r_breaker_strategy.py` |
| Volume breakout | ORCL daily | Breakout confirmed by volume spike + RSI | `test_115_volume_breakout_strategy.py` |
| Price channel | ORCL daily | N-day-high entry, M-day-low exit | `test_117_price_channel_strategy.py` |

## Deep Dive 1: Donchian Channel — Where the Turtles Began

The Turtle rule is one sentence: **buy when price breaks the N-day high; sell when it breaks the N-day low.** The Donchian channel turns that into two lines — the N-day high on top, the N-day low at the bottom.

The implementation ([test_105](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/breakout/test_105_donchian_channel_strategy.py)) is clean enough to read in 20 lines:

```python
class DonchianChannelStrategy(bt.Strategy):
    params = dict(stake=10, period=20)

    def __init__(self):
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.period)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.highest[-1]:   # break above upper band
                self.order = self.buy(size=self.p.stake)
        else:
            if self.data.close[0] < self.lowest[-1]:    # break below lower band
                self.order = self.close()
```

Note the `[-1]`: the comparison uses the channel value of the **previous** bar, avoiding the self-reference of "today's high breaking today's high" — a subtle look-ahead bias beginners often miss.

**An honest backtest.** With 0.1% commission, this bare-bones version ends at 99,965.62 on a 100,000 account over ORCL 2010-2014 — a small **loss**. The test pins that result with `abs(final_value - 99965.62) < 0.01`. That is the point of a regression library: strategies are here **to be compared, not performed**. A naked breakout bleeds in choppy markets; later articles in this series show how a single ADX filter or volume confirmation transforms the same idea.

## Deep Dive 2: Dual Thrust — the Futures Intraday Workhorse

Dual Thrust ([test_09](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/breakout/test_09_dual_thrust_strategy.py)) runs on glass-futures minute bars in three steps.

**Step 1 — build a range from the last N days (default 10):**

```python
hh = max(day_high_list[-look_back:])     # N-day high
lc = min(day_close_list[-look_back:])    # N-day lowest close
hc = max(day_close_list[-look_back:])    # N-day highest close
ll = min(day_low_list[-look_back:])      # N-day low
range_price = max(hh - lc, hc - ll)      # the more conservative of the two
```

**Step 2 — anchor two trigger lines at today's open:**

```python
upper_line = now_open + k1 * range_price    # k1 = 0.5
lower_line = now_open - k2 * range_price    # k2 = 0.5
```

**Step 3 — trade the touch, reverse on the opposite band, flatten at 14:55.**

The elegance: bands anchored at the open adapt to where each day starts, while the Range scales with volatility — wilder markets automatically get wider bands and fewer fake signals. The test also encodes the real rhythm of Chinese futures sessions (night session 21:00-23:00, day session 09:00-11:00).

## Deep Dive 3: R-Breaker — One Ladder of Levels, Two Playbooks

If Dual Thrust is a one-way pursuer, R-Breaker ([test_10](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/breakout/test_10_r_breaker_strategy.py)) is a double agent — **trend and reversal in one system**, a long-time resident of intraday strategy rankings.

From yesterday's high (H), low (L), and close (C):

```python
pivot = (pre_high + pre_low + pre_close) / 3
r1 = pivot + 0.5 * (pre_high - pre_low)   # observation resistance
r3 = pivot + 1.0 * (pre_high - pre_low)   # breakout resistance
s1 = pivot - 0.5 * (pre_high - pre_low)   # observation support
s3 = pivot - 1.0 * (pre_high - pre_low)   # breakout support
```

Two rule sets share the ladder:

- **Trend mode:** from flat, a close above R3 → go long; below S3 → go short (strong breakouts continue);
- **Reversal mode:** long positions that fall back through R1 are closed **and reversed** to short; shorts rising through S1 are reversed to long.

Flatten everything at 14:55. The trend mode harvests follow-through; the reversal mode punishes failed breakouts — whichever script the day follows, R-Breaker has a plan. On the engineering side, the test prices rebar with `ComminfoFuturesPercent` (10% margin, 10x multiplier) from 50,000 cash — a ready-made template for margin-aware futures backtests.

## The Rest of the Bench

- **Volume breakout** (`test_115`): a breakout must be *heard* — entry requires volume well above its moving average; exits on RSI overbought or a max holding period.
- **Price channel** (`test_117`): the minimal Turtle variant — enter at an N-day high, exit at an M-day low. Splitting entry/exit lookbacks (N vs M) is the first tuning knob of every channel system.
- **Donchian backhacker** (`test_66`): a second parameterization of the same idea, useful for comparing implementations of identical rules.

## Run It Yourself

```bash
# The whole category (runonce/runnext parity asserted automatically)
pytest tests/functional/strategies/breakout/ -v

# Just R-Breaker
pytest tests/functional/strategies/breakout/test_10_r_breaker_strategy.py -v
```

Every test runs twice — vectorized (`runonce=True`) and event-driven (`runonce=False`) — and asserts identical metrics, so engine regressions get caught immediately.

## Why Study Breakouts Here

Breakout strategies have sparse signals, long holding periods, and sensitive parameters — exactly what demands **massive, reproducible** backtesting infrastructure. That is [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)'s sweet spot: 46% faster than the original in pure Python (all 1,152 strategy regressions finish in minutes), a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) that turns parameter sweeps into coffee breaks, and asserted metric baselines so you optimize the strategy — not the engine's numerical drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map.

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
