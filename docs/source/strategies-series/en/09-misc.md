# The Misc Drawer: TD Sequential, the Pinkfish Challenge, and the Foundation Tests

> Strategy Compendium · No. 09 · Category `misc` (28 strategies) · 2026-09-02

Every strategy library has a junk drawer. This one has taste: here lives Tom DeMark's TD Sequential — the indicator that makes traders count candles all the way to 13 — alongside BTFD (the Wall Street meme, quantified), Bill Williams' Alligator, and a "buy the 20-day high, sell two bars later" challenge of disarming simplicity.

The category also plays a second, quieter role: **framework verification**. Slippage models, commission schemes, the data writer, and numeric baselines for a shelf of analyzers all live here. They are not "strategies," yet they are the foundation beneath the other 1,000-plus strategy backtests — if the slippage model is wrong, every high-frequency backtest in the repository is self-deception. Strategies and foundations share a room; this article tours both.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| TD Sequential | ORCL daily 2010-2014 | 9-bar Setup vs close 4 back, then a Countdown to 13 | `test_65_td_sequential_strategy.py` |
| Pinkfish challenge | YHOO daily 2005-2006 | Buy 20-day highs, unconditionally sell after 2 bars | `test_46_pinkfish_strategy.py` |
| Buy The Dip family | ORCL daily | Several parameterizations of buying dips | `test_110_buy_the_dip_strategy.py` / `test_79_buy_dip_strategy.py` |
| BTFD | Standard daily 2005-2006 | The meme, quantified: pullbacks are opportunities | `test_39_btfd_strategy.py` |
| Heikin Ashi | ORCL daily | Averaged candles smooth noise for trend-following | `test_76_heikin_ashi_strategy.py` |
| Alligator | ORCL daily | Bill Williams' three-line balance detects trend | `test_82_alligator_strategy.py` |
| Stochastic S/R | SSE sh600000 daily | Stochastic locates support/resistance levels | `test_32_stochastic_sr_strategy.py` |
| Slope | ORCL daily | Linear-regression slope of price sets direction | `test_77_slope_strategy.py` |
| Renko + EMA | ORCL daily | Brick bars filter noise, layered with an MA | `test_92_renko_ema_strategy.py` |
| Sky Garden | Shanghai zinc ZN889 minute bars | Intraday opening-pattern breakout | `test_11_sky_garden_strategy.py` |
| The Strategy | 5-minute + daily, 2006 | Multi-timeframe resonance sample | `test_21_the_strategy.py` |
| Convertible bonds | CB / stock daily | Convertibles traded against their underlying | `test_16_cb_strategy.py` / `test_17_cb_monday_strategy.py` |
| Double Sevens | ORCL daily | Fade seven consecutive same-direction bars | `test_71_double_sevens_strategy.py` |
| **Framework: slippage** | Standard daily 2005-2006 | SMA cross validates the slippage model | `test_47_slippage_strategy.py` |
| **Framework: analyzers** | YHOO / standard daily | Calmar/VWR/Sharpe numeric baselines | `test_49_calmar_analyzer.py` / `test_50_vwr_analyzer.py` / `test_57_sharpe_timereturn.py` |

## Deep Dive 1: TD Sequential — Exhaustion, Counted

TD Sequential is rare in technical analysis: an indicator with a complete algorithmic specification, used to catch trend exhaustion. Prices cannot fall forever — but after nine consecutive down-closes and a further countdown of thirteen, the sellers should be tired. The repository's implementation ([test_65](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/misc/test_65_td_sequential_strategy.py)) faithfully reproduces the two-stage structure. The Setup phase: nine consecutive closes below the close four bars earlier (`candles_past_to_compare=4`):

```python
if len(self.dataclose) > self.p.candles_past_to_compare:
    # buy trigger: this close < close 4 back, and the previous bar did not qualify
    if (self.dataclose[0] < self.dataclose[-self.p.candles_past_to_compare] and
            self.dataclose[-1] > self.dataclose[-(self.p.candles_past_to_compare + 1)]):
        self.buyTrig = True
        self.sellTrig = False
    # Setup count: each further qualifying bar increments
    if self.dataclose[0] < self.dataclose[-self.p.candles_past_to_compare] and self.buyTrig:
        self.tdsl += 1
```

The Countdown phase starts once Setup reaches nine, and only at bar 13 — with price breaking the low recorded at countdown bar 8 — is the "ideal buy point" confirmed:

```python
if self.buyCountdown == 8:
    self.buyVal = countdown_compare            # record bar-8 price
elif self.buyCountdown == 13:
    if self.dataprimary.low[0] <= self.buyVal:
        self.idealBuySig = True
        if not self.position:
            self.buy(size=10)                  # ideal buy point, go long
        self.buySetup = False
        self.buyCountdown = 0
```

The parameters — `cancel_1/2/3`, `recycle_12`, `aggressive_countdown` — are the full vocabulary of DeMark's cancellation and recycling clauses. **The backtest:** ORCL 2010-2014, 100,000 initial, 0.1% commission; after 1,257 bars the account stands at 100,002.91 — dead flat, with Sharpe locked to six decimals (0.022949...). The test is parametrized over `runonce=True/False` and asserts identical numbers both ways. Exhaustion counting does not make money on a single stock — but as an engineering blueprint for a complex state machine under regression discipline, it is priceless.

## Deep Dive 2: Pinkfish — the Honesty of Two Bars

If TD Sequential is maximalism, the Pinkfish challenge ([test_46](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/misc/test_46_pinkfish_strategy.py)) is minimalism perfected: buy a 20-day high, hold exactly two bars, sell unconditionally. The entire trading logic:

```python
def next(self):
    self.bar_num += 1
    if not self.position:
        if self.data.high[0] >= self.highest[0]:       # current high touches the 20-day highest
            self.buy()
            self.inmarket = len(self)
    else:
        if (len(self) - self.inmarket) >= self.p.sellafter:   # held 2 bars
            self.sell()
```

Note the difference from Turtle-style breakouts: no exit channel, no stop — the exit reads the calendar, and "time's up" means go. **The backtest:** YHOO 2005-2006, 50,000 initial, fixed 100-share lots; after 484 bars the account is worth 49,739.00 — Sharpe −2.5197, roughly −0.26% annualized. Those ugly numbers are welded into the assertions. Why read it at all? Because it is the best hypothesis-testing teaching aid in the drawer: momentum entry plus a random holding period is a grinding machine in a choppy market. Would `sellafter=20` change the picture? What about a trailing stop? Change one line, and the assertions instantly quote you the price of the experiment — that is how a regression library teaches research.

## Deep Dive 3: The Slippage Test — the Foundation Under the Drawer

The third deep dive belongs to no trading idea, yet decides how much every other backtest can be trusted. [test_47](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/misc/test_47_slippage_strategy.py) carries a standard SMA(10/30) crossover strategy, but its reason for existence is to host the broker's slippage API:

```python
cerebro = bt.Cerebro(stdstats=True)
cerebro.broker.setcash(50000.0)
cerebro.broker.set_slippage_perc(0.01)  # 1% slippage on all trades
...
assert strat.bar_num == 482
assert abs(final_value - 52702.98) < 0.01
assert abs(sharpe_ratio - (7.146238384824227)) < 1e-6
```

The same strategy's fills and equity under zero versus fixed/percentage slippage are asserted one by one, in both `runonce` modes. Its siblings in arms: the commission-scheme matrix (`test_54`), the data writer (`test_60`), numeric analyzer baselines for Calmar/VWR/Sharpe (`test_49/50/57`), the PSAR indicator (`test_55`), and sizer mechanics (`test_56`). They share the exact Cerebro pipeline with the strategies, so any engine change that touches fills, fees, or indicator math trips these tests before the strategy tests notice — **the misc category is not a junk drawer; it is a load-bearing wall.**

## The Rest of the Bench

- **BTFD trio** (`test_39` / `test_79` / `test_110`): one "buy the dip" idea in three parameterizations — dip depth, confirmation, and entry cadence — made for horizontal comparison.
- **Sky Garden** (`test_11`): an opening-pattern intraday system on Shanghai zinc minute bars; the Chinese futures session handling is ready to copy.
- **The Strategy** (`test_21`): the reference sample for 5-minute + daily dual-timeframe backtests via `resampledata`.
- **Double Sevens & up/down candles** (`test_71` / `test_85`): candle-pattern statistics, quantified.
- **cheat-on-open** (`test_40`): demonstrates the boundaries of the open-price cheat mode — know it before you use it.

## Run It Yourself

```bash
# The whole category (28 tests: strategies + framework verification)
pytest tests/functional/strategies/misc/ -v

# Just TD Sequential (runonce/runnext dual-mode asserted automatically)
pytest tests/functional/strategies/misc/test_65_td_sequential_strategy.py -v
```

## Why Study Misc Strategies Here

The misc category stresses an engine's corners hardest: Renko and Heikin Ashi non-standard bars, multi-timeframe alignment, slippage and commission minutiae — precisely where numerical divergence is born. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) nails every corner into a baseline with 1,152 strategy regression tests: 46% faster than the original in pure Python, a median 128x speedup with the C++ backend (`pip install back-trader-cpp`), and runonce/runnext dual-mode parity so the vectorized and event-driven code paths referee each other. Want to sweep hundreds of TD-Sequential cancellation-clause combinations? This repository lets you afford it.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/22-misc.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
