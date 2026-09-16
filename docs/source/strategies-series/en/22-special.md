# The Misfits: ETF Rotation, Calendar-Spread Arbitrage, and Strategies No School Claims

> Strategy Compendium · No. 22 · Category `special` (7 strategies) · 2026-09-02

Strategy textbooks like chapters: trend, mean reversion, momentum... But plenty of real-world trading refuses to be filed. A binary choice between the SSE 50 ETF and the ChiNext ETF. The spread between near and far treasury-futures contracts. A "double-low" scorecard across dozens of convertible bonds. What these share is not a signal formula but an engineering capability: **feed multiple data series into one backtest, align them, and make relative-value judgments between them**.

This article covers the 7 unclassifiable strategies in `tests/functional/strategies/special/`. The attraction is not indicators but data plumbing: how do you align two ETFs with different listing dates? How do you score dozens of bonds by day? How do you roll positions onto the new dominant contract when expiry arrives? Each file is an answer you can lift and adapt.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| ETF rotation | SSE 50 ETF + ChiNext ETF, daily | Price/MA momentum ratio picks the stronger; flat when both weak | `test_18_etf_rotation_strategy.py` |
| Treasury calendar spread | CFFEX T-contract daily | Spread band entries, reversion exits, auto rollover | `test_20_arbitrage_strategy.py` |
| Convertible double-low | Multi-bond daily (extended fields) | Price + premium rank scoring, monthly rebalance | `test_02_multi_extend_data.py` |
| Premium-rate crossover | Bond 113013 daily | SMA(10/60) crossover on an extended data line | `test_01_premium_rate_strategy.py` |
| Multi-source MA | 30 convertible bonds, daily | Per-bond 60-day MA long/flat, equal weight | `test_04_simple_ma_multi_data.py` |
| Fei A'li (4-price) | Rebar RB889, minute bars | Bollinger(200,2) + prior-day high/low intraday breakout | `test_13_fei_strategy.py` |
| Hans123 (MA filter) | Rebar RB889, minute bars | First-2-bar range breakout with a 200-MA filter | `test_14_hanse123_strategy.py` |

## Deep Dive 1: ETF Rotation — China's Large-vs-Small Cap Coin Flip

A persistent style pattern in A-shares: large-cap blue chips and small-cap growth rarely lead at the same time, yet the style switch is nearly impossible to call in advance. Rather than predict, follow — [test_18_etf_rotation_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/special/test_18_etf_rotation_strategy.py) turns "relative strength" into one comparable number via a 20-day moving average:

```python
# If both ETFs are below moving averages, close all positions
if sz_close < self.sz_ma[0] and cy_close < self.cy_ma[0]:
    if self.sz_pos > 0:
        self.close(sz_data)
    if self.cy_pos > 0:
        self.close(cy_data)

# If at least one ETF is above its moving average
if sz_close > self.sz_ma[0] or cy_close > self.cy_ma[0]:
    # If SSE 50 momentum indicator is larger
    if sz_close / self.sz_ma[0] > cy_close / self.cy_ma[0]:
        if self.sz_pos == 0 and self.cy_pos == 0:
            total_value = self.broker.get_value()
            lots = int(0.95 * total_value / sz_close)
            self.buy(sz_data, size=lots)
```

Three design details worth stealing. First, the comparison uses `close/MA` ratios, not raw prices — momentum is normalized so two ETFs at different price scales become comparable. Second, "both below the MA → close everything" gives the strategy the right to *decline to play*; rotation strategies die when forced to pick a side in a downtrend. Third, sizing with `int(0.95 * total_value / price)` instead of a fixed lot lets the equity curve compound. Baseline (from 2011-09-20, 0.02% commission, 50,000 initial): 2,600 bars, 266 buys, 265 trades, 16.19% annualized, 32.03% max drawdown, final value 235,146.29. Handsome returns — and a one-third drawdown to remind you style rotation is never gentle.

## Deep Dive 2: Treasury Calendar Spread — A Lesson in Ideal vs Reality

The textbook calendar arbitrage reads like a physics problem: when the near/far spread exceeds carry cost, sell near, buy far, wait for convergence. [test_20_arbitrage_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/special/test_20_arbitrage_strategy.py) builds the full engineering version — including the hardest part, rollover:

```python
# Open position
if self.market_position == 0:
    # Open long
    if near_data.close[0] - far_data.close[0] < self.p.spread_low:
        self.buy(near_data, size=1)
        self.sell(far_data, size=1)
        self.market_position = 1
        self.holding_contract_name = [near_data, far_data]
    # Open short
    if near_data.close[0] - far_data.close[0] > self.p.spread_high:
        self.sell(near_data, size=1)
        self.buy(far_data, size=1)
        self.market_position = -1
        self.holding_contract_name = [near_data, far_data]
```

The band `spread_low=0.06 / spread_high=0.52` defines the channel: break out to enter, revert to exit. The genuinely valuable engineering is `get_near_far_data()`: on every bar it ranks contracts by open interest to find the two most active, and once the dominant contract rolls, it closes old legs and re-opens them on the new pair in the original direction. A calendar-spread position *must* outlive the roll date — any arbitrage backtest without rollover logic is a toy. Then the honest part: 1,990 bars and 86 trades of T-contract data end at Sharpe **-2.24** and a final value of 918,003.89 from 1,000,000. These fixed thresholds lose money in-sample. Spreads do not revert unconditionally — and this asserted baseline teaches more than any profit curve.

## The Rest of the Bench

- **Convertible double-low** (`test_02`): registers bond value, conversion value, and premium rates as data lines; ranks price and premium cross-sectionally (`rank()`, not raw values — different scales demand ranks), blends 50/50 into a score, buys the top 20, rebalances on each month's last trading day. Baseline: 1,300 bars, 89 trades, Sharpe -2.97, max drawdown 4.03% — low drawdown, negative return: hiding in bond floors while missing the trend.
- **Premium-rate crossover** (`test_01`): the same extended fields on a single bond — 1,384 bars, 21 trades, final value 104,275.87.
- **Multi-source MA** (`test_04`): 30 bonds, each with its own 60-day MA — 4,434 bars, 460 trades, final value 14,535,803.03. Together the three files form a complete "custom data fields, from declaration to use" tutorial.
- **Fei A'li** (`test_13`): Bollinger(200,2) breakout plus prior-day levels, flattened at 14:55 — 19,801 minute bars, Sharpe -2.42, final 805,620.92. The price tag of naked breakouts on choppy instruments.
- **Hans123** (`test_14`): same data, a 200-MA direction filter on the opening-range breakout — 235 trades, final 958,610.35; less than a quarter of Fei's loss from the same 1M start. One filter's value, quantified.

## Run It Yourself

```bash
# The whole category (7 strategies, runonce/runnext dual-mode parity)
pytest tests/functional/strategies/special/ -v

# Just ETF rotation
pytest tests/functional/strategies/special/test_18_etf_rotation_strategy.py -v
```

## Why Study Multi-Data Strategies Here

Multi-feed strategies are where data-alignment bugs breed: two feeds a day apart, an indicator warm-up one bar short, positions across instruments stepping on each other — all silently change results. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) freezes all 7 multi-data scenarios inside 1,152 strategy regression tests with asserted metric baselines and runonce/runnext dual-mode parity, so any engine change that bends multi-data timing trips an alarm immediately. The pure-Python engine runs 46% faster than the original, and the C++ backend (`pip install back-trader-cpp`) brings a median 128x speedup — making "20 bonds × 5 years × both modes" comparisons a minutes-long job.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/35-special.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
