# Owning the Clock: Timers, Resampling, and Data Replay

> Strategy Compendium · No. 21 · Category `time_based` (7 strategies) · 2026-09-02

Most backtesting frameworks live by a single worldview: one bar, one world. The strategy sees a close, places an order, gets filled instantly, and jumps to the next bar. Real trading is nothing like that. You scan overnight news before the open, you watch a weekly bar that is still growing while the week unfolds, and you do specific things at specific moments — month-end, the lunch break, five minutes before the close. A framework that can schedule *time itself* as a first-class citizen is the only kind worth taking to production.

backtrader hands you three weapons here: `add_timer()` for scheduling, `resampledata()` for aggregation, and `replaydata()` for replay. This article walks through the 7 backtests in `tests/functional/strategies/time_based/`. Fair warning: the "strategies" are mostly plain dual-MA crossovers — because what is really being tested is the **framework**, not the signal. Writing feature verification as full strategy backtests with asserted metric baselines guards numerical drift far better than isolated unit tests.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Timer scheduling | Daily 2005-2006 (with sessions) | Dual MA cross + `SESSION_START` timer firing checks | `test_62_timers.py` |
| Pandas loading | Daily 2005-2006 | `PandasData` feeds a DataFrame straight into Cerebro | `test_52_data_pandas.py` |
| Resampling | Daily → weekly | `resampledata` aggregates weekly bars + dual MA cross | `test_53_data_resample.py` |
| Data replay | Daily → weekly | `replaydata` advances a "growing" weekly bar day by day | `test_58_data_replay.py` |
| Replay × Bollinger | Daily → weekly | Bollinger breakout on replayed weekly bars | `test_118_data_replay_bollinger.py` |
| Replay × EMA | Daily → weekly | EMA(12,26) crossover on replayed weekly bars | `test_119_data_replay_ema.py` |
| Replay × MACD | Daily → weekly | MACD(12,26,9) crossover on replayed weekly bars | `test_120_data_replay_macd.py` |

## Deep Dive 1: Timers — Writing "Do This at 9:00" into the Strategy

What live strategies need most is not a smarter indicator but **scheduling**: pull quotes at 9:25, rebalance before Friday's close, flatten overnight exposure at 14:55. backtrader's answer is registering timers inside the strategy and receiving callbacks in `notify_timer` ([test_62_timers.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_based/test_62_timers.py)):

```python
class TimerStrategy(bt.Strategy):
    params = dict(
        when=bt.timer.SESSION_START,
        timer=True,
        fast_period=10,
        slow_period=30,
    )

    def __init__(self):
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)
        self.crossover = bt.ind.CrossOver(self.fast_ma, self.slow_ma)

        if self.p.timer:
            self.add_timer(when=self.p.when)

    def notify_timer(self, timer, when, *args, **kwargs):
        self.timer_count += 1
```

The data feed declares a trading session (`sessionstart=9:00, sessionend=17:30`), so the timer knocks at the open of every trading day. The baseline the test pins is telling: `timer_count == 512` while `next()` was only called **482 times** — the difference is exactly the 30 warm-up bars of the slow MA. In other words, **timers fire from the very first bar, without waiting for indicators to be ready**. In production terms: risk checks and data sync during warm-up never miss a day. The same run also asserts a final value of 104,966.80, Sharpe 0.721, max drawdown 3.43%, and 9 completed trades.

## Deep Dive 2: Data Replay — Revisiting the Afternoon When the Bar Wasn't Finished

Resampling *compresses* history; replay *re-enacts* it. With the same daily file, `replaydata` runs the strategy on a weekly timeframe but **advances once per incoming daily bar**: you watch a weekly candle that grows through the week — half-formed on Monday's close, complete only on Friday's ([test_58_data_replay.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_based/test_58_data_replay.py)):

```python
# Use replay functionality to replay daily data as weekly data
cerebro.replaydata(
    data,
    timeframe=bt.TimeFrame.Weeks,
    compression=1
)

cerebro.addstrategy(ReplayMAStrategy, fast_period=5, slow_period=15)

print("Starting backtest...")
results = cerebro.run(runonce=runonce, preload=False)
```

Compare the same 5/15 parameters. Under resampling the strategy sees **89 weekly bars** and makes 3 trades (final value 100,765.01, Sharpe 1.079). Under replay the same strategy is advanced **439 times**, makes 13 trades, and finishes at 108,263.90 with Sharpe 1.179. Why? Replayed indicators recompute on every daily bar, so a crossover can trigger *mid-week*. That is precisely the point of replay: **testing how a strategy behaves with no future data and only a half-built bar**. It is also why replay must run with `preload=False`, feeding bars one at a time — a natural stress test of the engine's slow path.

## The Rest of the Bench

- **Pandas loading** (`test_52`): not all data lives in CSV files. `pd.read_csv` into a DataFrame, then `bt.feeds.PandasData(dataname=dataframe)` — the last mile from research notebook to backtest is often just this one line. Baseline: 482 bars, 9 trades, final value 100,496.68, matching the CSV-direct run.
- **Replay × Bollinger** (`test_118`): a Bollinger breakout replayed on weekly bars — 419 advances, 2 trades.
- **Replay × EMA** (`test_119`): EMA(12,26) crossover under replay — 384 advances, 9 trades.
- **Replay × MACD** (`test_120`): MACD(12,26,9) under replay — 344 advances, Sharpe 1.323, confirming a third indicator family doesn't drift on replayed data.

## Run It Yourself

```bash
# The whole category (7 strategies, runonce/runnext parity asserted automatically)
pytest tests/functional/strategies/time_based/ -v

# Just data replay
pytest tests/functional/strategies/time_based/test_58_data_replay.py -v
```

## Why Study Time and Data Flow Here

Timers, resampling, and replay all manipulate the engine's timeline — be off by a single bar anywhere and everything downstream is wrong. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) wraps these easiest-to-quietly-break features in 1,152 strategy regression tests with asserted metric baselines and runonce/runnext dual-mode parity: aggregate one row too many in resampling, or advance one step too few in replay, and a test screams. The pure-Python engine is 46% faster than the original, and the C++ backend (`pip install back-trader-cpp`) delivers a median 128x speedup — so you can keep event-driven replay in your daily regression loop instead of running it once and never again.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/34-time-based.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
