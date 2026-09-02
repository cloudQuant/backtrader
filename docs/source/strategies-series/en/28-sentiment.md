# Sentiment Strategies: Fear & Greed, Put/Call, and VIX — Buffett's Maxim, Quantified

> Strategy Compendium · No. 28 · Category `sentiment` (4 strategies) · 2026-09-02

"Be fearful when others are greedy, and greedy when others are fearful." Everyone can recite Buffett's maxim — but how do you *quantify* fear? CNN's Fear & Greed index compresses it into a single 0-100 number; the options market votes with real money and produces the Put/Call Ratio; VIX prices panic outright. Three indicators, three fear meters.

The interesting part: they do not measure the same emotion. The Fear & Greed index is a composite of seven sub-indicators (momentum, breadth, volatility...) — a *state* measure; PCR records which way option buyers are betting right now — a *behavior* measure; VIX is the implied quote for 30-day volatility — an *expectation* measure. Sentiment strategies use these **slow variables** as timing filters — extreme readings appear only a few times a year, so the strategies trade only a few times a year. Spoiler: the most active strategy in this category places just 6 orders in 11 years.

This article walks through the 4 backtests in `tests/functional/strategies/sentiment/`. They share one data file (a CSV of SPY plus three sentiment indicators) yet demonstrate several distinct ways to open the contrarian trade.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Fear & Greed | SPY + sentiment, 2011-2021 | Buy below 10 (extreme fear), sell above 94 (extreme greed) | `test_22_fear_greed_strategy.py` |
| Put/Call Ratio | SPY + sentiment, 2011-2021 | Buy above 1.0 (panic crowding), sell below 0.45 (euphoria) | `test_23_put_call_strategy.py` |
| VIX | SPY + sentiment, 2011-2021 | Buy SPY above 35, exit below 10 | `test_24_vix_strategy.py` |
| BTC Google Trends | BTC weekly + Trends, 2018-2020 | Search-heat breakouts of Bollinger bands; exit at the midline | `test_33_btc_sentiment_strategy.py` |

## Deep Dive 1: Fear & Greed — Act Only at the Extremes

[test_22_fear_greed_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/sentiment/test_22_fear_greed_strategy.py) fits its entire trading logic in a dozen lines:

```python
def next(self):
    self.bar_num += 1
    size = int(self.broker.getcash() / self.close[0])

    # Buy when extremely fearful
    if self.fear_greed[0] < self.p.fear_threshold and not self.position:
        if size > 0:
            self.buy(size=size)
            self.buy_count += 1

    # Sell when extremely greedy
    if self.fear_greed[0] > self.p.greed_threshold and self.position.size > 0:
        self.sell(size=self.position.size)
        self.sell_count += 1
```

The thresholds — `fear_threshold=10`, `greed_threshold=94` — sit deliberately at the far ends of the 0-100 scale: act only in the most extreme 10% of readings. The engineering lesson is the data plumbing: sentiment indicators are not OHLC bars, so the test extends `GenericCSVData` and mounts Put/Call, F&G, and VIX as three extra lines on the price stream:

```python
class SPYFearGreedData(bt.feeds.GenericCSVData):
    lines = ('put_call', 'fear_greed', 'vix')
    params = (('dtformat', '%Y-%m-%d'), ('datetime', 0), ('open', 1), ('high', 2),
              ('low', 3), ('close', 4), ('volume', 6), ('openinterest', -1),
              ('put_call', 7), ('fear_greed', 8), ('vix', 9))
```

The backtest (SPY, 2011-2021): 2,445 daily bars, only **6 buys and 2 sells**, both closed trades winners, final value 280,859.60 (11.2% annualized, Sharpe 0.89), max drawdown 24.3%. Note the last buy never closes — if greed is late to arrive, the position stays exposed to the market, and that 24.3% drawdown is the price of waiting. Six buys in 11 years also exposes the statistical embarrassment of this family: a 100% win rate on two closed trades proves nothing. 2011-2021 was a historic US bull run — "extreme fear always rebounds" may be a property of bull markets, not of sentiment. Run the same 10/94 thresholds over 2000-2010 and the answer may differ entirely.

## Deep Dive 2: Put/Call Ratio — the Options Market's Ballot

PCR = put volume / call volume. A spiking ratio means everyone is buying insurance; a bottoming ratio means everyone is chasing calls naked. [test_23_put_call_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/sentiment/test_23_put_call_strategy.py) keeps the same skeleton and swaps the signal line: `PCR > 1.0` reads as peak fear — buy; `PCR < 0.45` reads as euphoria — liquidate. On the same SPY data: 6 buys, 3 sells, all 3 closed trades winners, final value 240,069.35 (Sharpe 0.83).

The comparison with Fear & Greed is instructive: the two indicators are highly correlated (both fear-derived), the entry counts are identical (6), yet different exit timing produces a 40,000-dollar gap in final value — **the alpha of sentiment strategies hides in the exit rules**. The other implication of slow variables is tiny samples: 3-6 trades in 11 years cannot pass any significance test. A backtest can prove the logic *runs*; it cannot prove the pattern *exists*.

## The Rest of the Bench

- **VIX** (`test_24`): the bluntest version — buy above 35, exit below 10. In 11 years it triggers only 3 buys (readings above 35 are rare), ending at 261,273.50 with Sharpe 0.92 — the laziest and sharpest of the trio. VIX above 35 happens almost exclusively mid-crash: this is knife-catching, with the worst drawdown of the three (33.7%) and the fattest returns.
- **BTC Google Trends** (`test_33`): retail sentiment, crypto edition — Bollinger bands (period 10, devfactor 1) on Google Trends search heat; a break above the upper band goes long, below the lower band goes short, return to the midline flattens. Engineering-wise it demonstrates dual feeds: BTC price is `datas[0]`, search heat rides in as `datas[1]`'s close, and the indicator sits directly on the sentiment line. On weekly bars: 16 buys, 16 sells, roughly 50/50 (final value 15,301.43 from 10,000) — far higher turnover than the SPY trio. Crypto sentiment is a fast variable, and here it is used *with* the trend — the exact opposite of the contrarian SPY family.

## Run It Yourself

```bash
# The whole category (4 strategies, runonce/runnext parity asserted automatically)
pytest tests/functional/strategies/sentiment/ -v

# Just Fear & Greed
pytest tests/functional/strategies/sentiment/test_22_fear_greed_strategy.py -v
```

Every test runs twice — vectorized (`runonce=True`) and event-driven (`runonce=False`) — and asserts identical metrics, so engine regressions get caught immediately.

## Why Study Sentiment Here

Sentiment strategies trade sparsely and are path-sensitive — a single fill at a different price reshapes the whole equity curve, which makes matching fidelity and reproducibility in the backtest engine critical. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) pins every strategy's trade counts, final values, and Sharpe ratios into asserted metric baselines across its 1,152 strategy regression tests, while runonce/runnext dual-mode parity ensures both engines walk away with the same trades. The pure-Python engine is 46% faster than the original and the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — so scanning alternative thresholds (what if 10/94 became 15/90?) takes minutes, not weekends.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/41-sentiment.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
