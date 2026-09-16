# Advanced Framework Patterns: Optimization, Signals, and Multi-Data — From Writing Strategies to Wielding One

> Strategy Compendium · No. 27 · Category `advanced` (5 strategies) · 2026-09-02

Writing a strategy is easy; writing strategies that can be **managed at scale** is hard. When you have 50 ideas, each with 3 parameters, and each parameter set needs 10 years of data, you no longer need smarter signals — you need framework-grade weapons: parameter grid optimization, declarative signals, multi-data alignment, runtime strategy selection.

That is also the dividing line between novice and veteran. The novice treats a backtest as a script that "runs once"; the veteran treats it as a reproducible experimental system — every strategy a pluggable unit, every parameter an enumerable dimension, every data feed a composable input. This article walks through the 5 tests in `tests/functional/strategies/advanced/`. They do not demonstrate one trading idea but five framework capabilities of backtrader — strategies and framework features in one breath.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Signal strategy | Daily bars, 2005-2006 | Declarative `add_signal`: long when price minus SMA(30) is positive | `test_44_signals_strategy.py` |
| Multiple trades | Daily bars, 2006 | Trade ids rotate through [0, 1, 2]; concurrent trade management | `test_45_multitrades_strategy.py` |
| Strategy selection | Daily bars, 2005-2006 | Runtime choice between a dual-MA and a price-vs-MA strategy | `test_48_strategy_selection.py` |
| Optimization | Daily bars, 2006 | MACD(12,26,9) crossover + SMA-period grid; best Sharpe selected and rerun | `test_51_optimization.py` |
| Multi-data | YHOO dual feeds | data1 generates signals, data0 receives orders — a lead-lag skeleton | `test_59_multidata_strategy.py` |

## Deep Dive 1: Optimization — Grid Search and Its Traps

`cerebro.optstrategy` turns one backtest into a parameter sweep: pass in ranges, and the framework runs every combination. [test_51_optimization.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/advanced/test_51_optimization.py) compresses the standard workflow into three moves:

```python
cerebro.optstrategy(
    OptimizeStrategy,
    smaperiod=range(10, 13),   # 3 values: 10, 11, 12
    macdperiod1=[12], macdperiod2=[26], macdperiod3=[9],
)
...
best_result = max(all_results, key=lambda x: x['sharpe_ratio'] or -999)
best_params = {'smaperiod': best_result['smaperiod']}
best_metrics = run_best_strategy(best_params, runonce=runonce)   # full rerun with the winner
```

**Sweep → select by Sharpe → rerun and verify.** The assertions lock the outcome down: of the 3 parameter sets the best is `smaperiod=10`; the rerun covers 221 bars and 10 trades, ending at 100,150.06 with Sharpe 0.4979. Note the plumbing detail: optimization results arrive as a nested list (`for stratrun in results: for strat in stratrun`) — one strategy instance per parameter set, each with its own analyzers. The framework does the grouped-collection dirty work for you.

But this 3-cell grid is itself an overfitting lesson. Picking parameters on a single year (2006) means any "best" is likely noise; the serious approach is in-sample/out-of-sample splitting — tune on the first half, validate on the second, and if out-of-sample performance collapses, you optimized a historical coincidence, not a pattern. A subtler trap is **the selection metric itself**: choosing by Sharpe favors low-volatility, low-trade combinations that may rest on one or two lucky trades; switching to Calmar or adding a minimum-trade constraint often crowns a completely different "best." Also note `bt.Cerebro(maxcpus=1)`: single-threaded for reproducibility — in production, unleash the cores.

## Deep Dive 2: Signal Strategies — Trading Without a Strategy Class

The same "go long when price stands above its average" can be declared as a signal line handed to the framework — no `next()`, no order management ([test_44_signals_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/advanced/test_44_signals_strategy.py)):

```python
cerebro.add_signal(bt.SIGNAL_LONG, bt.indicators.SMACloseSignal, period=30)
```

That is the entire strategy — one line. `SMACloseSignal` outputs `price - SMA(30)`: positive opens a long, negative closes it, and **position size is proportional to the signal value** — the further price runs from the average, the larger the position. Four signal types exist (`SIGNAL_LONG`, `SIGNAL_SHORT`, `SIGNAL_LONGSHORT`, `SIGNAL_LONGEXIT`), and multiple lines can be stacked so entry uses signal A while exit uses signal B — more powerful than it looks.

The cost is in the numbers: 21 trades, final value 50,607.58, Sharpe -12.58, max drawdown 64%. "Size scales linearly with distance" means the position is heaviest at trend tops. Declarative signals are perfect for quickly validating indicator combinations; complex risk logic still belongs in a Strategy class. Two dialects, one engine — use each where it fits.

## The Rest of the Bench

- **Multiple trades** (`test_45`): with `mtrade=True`, each new entry rotates the trade id (0→1→2) so several trades book P&L and close independently inside one strategy — the underlying machinery for pyramiding and scaled exits.
- **Strategy selection** (`test_48`): `StrategyA` (dual-MA crossover) and `StrategyB` (price vs single MA) share one interface and are injected at runtime — turning the *strategy itself* into a configurable parameter.
- **Multi-data** (`test_59`): `bt.ind.SMA(self.data1, period=15)` computes the signal on data 1 while orders execute on data 0 (0.5% commission); backtrader aligns the two streams by timestamp automatically — the generic skeleton for lead-lag and pairs trading.

## Run It Yourself

```bash
# The whole category (5 strategies, runonce/runnext parity asserted automatically)
pytest tests/functional/strategies/advanced/ -v

# Just the optimizer
pytest tests/functional/strategies/advanced/test_51_optimization.py -v
```

Every test runs twice — vectorized (`runonce=True`) and event-driven (`runonce=False`) — and asserts identical metrics, so engine regressions get caught immediately.

## Why Study the Framework Here

Parameter optimization is a bottomless pit of compute: a 3-cell grid is trivial, a 300-cell grid is another story. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)'s pure-Python engine is 46% faster than the original, and the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — turning sweeps from overnight jobs into coffee breaks. The 1,152 strategy regression tests and runonce/runnext dual-mode parity guarantee the speed was not bought with matching-semantics drift: you are optimizing your parameters, not chasing engine bugs. Asserted metric baselines make every grid rerun precisely comparable to the last.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/40-advanced.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
