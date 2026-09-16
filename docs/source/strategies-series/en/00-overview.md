# The Strategy Compendium: 1,152 Backtested Strategies, Explained

> Series: Overview · Updated: 2026-09-02

The **Strategy Compendium** is a serialized deep-dive into the **1,152 strategy backtests** living in [tests/functional/strategies](https://github.com/cloudQuant/backtrader/tree/main/tests/functional/strategies) of this repository. They span **30 categories** — from the classic Turtle Trader and Dual Thrust breakouts, through HMM regime switching and Kalman-filtered pairs trading, to grid/martingale systems and options expiration-week effects. Every one of them is a **complete, runnable backtest with precise assertions** — not pseudocode, not a toy example.

Why this matters:

1. **Real data** — XAUUSD (gold) M15/D1 bars, rebar & glass futures minute data, ORCL daily prices;
2. **Asserted metrics** — final portfolio value, Sharpe ratio, and max drawdown are compared against baselines (e.g., the Donchian test asserts `final_value` within 0.01);
3. **Dual-mode parity** — each strategy runs in both vectorized (`runonce=True`) and event-driven (`runonce=False`) engine modes and must produce identical results, guarding engine correctness.

All of this rides on the [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) high-performance engine: 46% faster than the original in pure Python, 128x median speedup with the C++/pybind11 backend, and 3,200+ tests protecting correctness.

## Series Index

> All 30 digests published (completed 2026-09-02). The [Chinese edition](../zh/00-overview.md) splits large categories further (43 articles).

| # | Category | Strategies | Focus | Status |
|---|----------|-----------|-------|--------|
| 01 | trend_following | 340 | MA crossovers, channel breakouts, MACD, ADX/Supertrend, HMM & DSP trends | ✅ |
| 02 | mean_reversion | 331 | Connors RSI2, oscillator reversals, Bollinger, Double 7s, MT5 EA ports | ✅ |
| 03 | momentum | 45 | Dual momentum, time-series momentum, factor & rotation variants | ✅ |
| 04 | price_patterns | 44 | Engulfing/hammer/stars, NR7, fractals, Darvas boxes, Renko | ✅ |
| 05 | others | 69 | Gap & overnight effects, Kelly, Hurst, Markowitz, breadth thrust | ✅ |
| 06 | volatility_systems | 32 | HMM regime detection, VIX divergence, cyber cycles | ✅ |
| 07 | multi_indicator_system | 29 | Multi-indicator resonance systems | ✅ |
| 08 | calendar_effects | 28 | Sell in May, turn-of-month, FOMC, opex seasonality | ✅ |
| 09 | misc | 28 | TD Sequential, buy-the-dip, analyzer validations | ✅ |
| 10 | asset_allocation | 23 | 60/40, risk parity, HRP, CPPI, permanent portfolio | ✅ |
| 11 | pairs_trading | 22 | Gold/silver cointegration, Kalman, Copula pairs | ✅ |
| 12 | machine_learning | 21 | KMeans, RNN, reinforcement learning, fuzzy logic | ✅ |
| 13 | commodity_currency | 21 | Macro factors, COT positioning, real rates | ✅ |
| 14 | risk_management | 19 | Drawdown protection, tail-risk hedging, risk budgeting | ✅ |
| 15 | breakout | 6 | Donchian, Dual Thrust, R-Breaker, volume breakout | ✅ |
| 16 | volatility | 9 | Keltner channels, SuperTrend, chandelier exits | ✅ |
| 17 | multi_indicator | 9 | Williams %R, Stochastic, TRIX, Ultimate Oscillator | ✅ |
| 18 | grid_trading | 9 | Grid & martingale systems (VR-SETKA et al.) | ✅ |
| 19 | volume_system | 7 | Volume-weighted MAs, Ergodic Tick Volume | ✅ |
| 20 | time_session_system | 7 | Night-session channels, timed open/close | ✅ |
| 21 | time_based | 7 | Timers, data replay & resampling | ✅ |
| 22 | special | 7 | ETF rotation, arbitrage, multi-data strategies | ✅ |
| 23 | rotation | 6 | Monthly ranking, safe-haven switching | ✅ |
| 24 | pivot_fibonacci_system | 6 | Pivot points & Fibonacci retracement systems | ✅ |
| 25 | order_types | 6 | Bracket, OCO, stop-trail orders in practice | ✅ |
| 26 | options | 5 | Expiration-week effects, put-write | ✅ |
| 27 | advanced | 5 | Optimization, multi-data, signal strategies | ✅ |
| 28 | sentiment | 4 | Fear & Greed, put/call ratio, VIX, BTC sentiment | ✅ |
| 29 | carry_trading | 4 | Cross-sectional carry harvesting | ✅ |
| 30 | forecasting | 3 | ARIMA, Forecast Oscillator | ✅ |

## Article Structure

Each article follows the same layout: a **category inventory** (all strategies at a glance), the **idea behind the edge**, **deep dives** into 2-3 representative strategies with runnable code, and a **one-line pytest** to reproduce the backtest.

## Quick Start

```bash
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader && pip install -U .

# Run every breakout backtest in the category
pytest tests/functional/strategies/breakout/ -v

# A single strategy (runonce/runnext parity is asserted automatically)
pytest tests/functional/strategies/breakout/test_10_r_breaker_strategy.py -v
```

## Related Resources

- Chinese edition: [量化策略图鉴](../zh/00-overview.md)
- Main repo: [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)
- Ecosystem: [backtrader-mcp](https://github.com/cloudQuant/backtrader-mcp) · [backtrader_web](https://github.com/cloudQuant/backtrader_web) · [fincore](https://github.com/cloudQuant/fincore)
- Docs: [English](https://backtrader.readthedocs.io/en/latest/) · [中文](https://backtrader-zh.readthedocs.io/zh-cn/latest/)

> Risk disclaimer: for education and research only. Algorithmic trading carries substantial risk of loss; past performance does not guarantee future results.
