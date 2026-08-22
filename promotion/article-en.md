# 46% Faster Than Upstream, 128x With a C++ Backend: The Backtrader Fork Built for the AI Era

> Channels: Medium (primary), dev.to (cross-post), Hacker News (Show HN)
> Title options:
> - Backtrader, actively maintained: 1.86x faster core, 128x C++ backend, and an AI-native workflow
> - We forked Backtrader, made it 46% faster, and gave it an MCP server

---

## Why fork Backtrader?

[Backtrader](https://github.com/mementum/backtrader) is one of the most loved Python backtesting frameworks — elegant API, 50+ indicators, huge community. It has also been effectively unmaintained for years, and its architecture predates both modern performance expectations and AI coding assistants.

[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) is an **actively maintained, performance-oriented fork**. It keeps the public API compatible while removing metaclass metaprogramming overhead and rewriting hot paths — and it ships with an **AI-native strategy toolchain** around the core: author, review, and backtest strategies through Claude Code, Codex, or OpenCode.

## Performance: measured on three fronts

### 1. Pure-Python core: 46% faster

Full **1,271-strategy regression suite** on identical hardware (8 parallel workers):

| Metric | master (upstream-aligned) | dev | Improvement |
| --- | --- | --- | --- |
| Total execution time | 438.96s | 236.36s | **-46.2%** |
| Speedup | 1.00x | **1.86x** | ✓ |
| Pass rate | 100% | 100% | ✓ |

### 2. C++ / pybind11 backend: order-of-magnitude speedups

Via [back-trader-cpp](https://pypi.org/project/back-trader-cpp/) (one `pip install`, Python 3.8-3.14, macOS/Windows/Linux):

- 117 strategy benchmarks: **117/117 pass with zero metric mismatches**
- C++ median total-time speedup: **128.82x**; run-time: **235.78x**
- pybind11 median total-time speedup: **43.39x**; run-time: **57.60x**

### 3. Correctness: 3,200+ tests as a safety net

Speed never comes at the cost of correctness: the suite includes 1,271 strategy regression tests across 22 strategy categories, with the upstream-aligned `master` branch as the baselined reference.

## More than an engine: a six-repo ecosystem

| Repo | What it does |
| --- | --- |
| [backtrader](https://github.com/cloudQuant/backtrader) | The high-performance core: backtesting + live trading, tick to daily |
| [backtrader-skills](https://github.com/cloudQuant/backtrader-skills) | Offline author/review/test skills for AI coding agents: register local data, type-checked strategy specs, static review, isolated child-process backtests |
| [backtrader-mcp](https://github.com/cloudQuant/backtrader-mcp) | Local-first MCP server: 30 typed tools turning CSV files into immutable datasets, strategy intent into private drafts, and reviewed drafts into bounded subprocess runs with durable reports |
| [backtrader-agent](https://github.com/cloudQuant/backtrader-agent) | Offline-first strategy-authoring agent runtime with hash-bound approvals and recoverable session provenance |
| [backtrader_web](https://github.com/cloudQuant/backtrader_web) | "AI for Investor": Vue 3 + FastAPI platform for research, AI strategy generation, backtesting, paper trading, live execution, and data management |
| [fincore](https://github.com/cloudQuant/fincore) | Quantitative performance & risk analytics: 150+ metrics, portfolio optimization, Monte Carlo, attribution — the actively maintained successor to empyrical, pyfolio, and alphalens |

## The new workflow: let an AI agent write your strategy

The traditional loop is "read docs → hand-write strategy → debug the backtest". With `backtrader-mcp` in your Claude Code / Codex / OpenCode session, it becomes a prompt:

> "Inspect my offline CSV, register it as a dataset, scaffold a multi-timeframe momentum strategy, review it, and show me the backtest report."

The server handles: dataset validation → strategy draft rendering → static review (candidate code is never imported by the server) → human-gated approval → bounded subprocess backtest with runonce/runnext parity → 11 canonical metrics in JSON/Markdown. Offline, backtest-only, approval-separated — designed so "AI writes the strategy" stays inside safe boundaries.

## Start in 30 seconds

```bash
# Pure-Python core (from source)
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader && pip install -U .

# Or the pybind11-accelerated wheel
pip install back-trader-cpp
```

```python
import backtrader as bt

class SmaCross(bt.Strategy):
    params = (('fast', 10), ('slow', 30))

    def __init__(self):
        sma_fast = bt.indicators.SMA(period=self.p.fast)
        sma_slow = bt.indicators.SMA(period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(sma_fast, sma_slow)

    def next(self):
        if not self.position and self.crossover > 0:
            self.buy()
        elif self.position and self.crossover < 0:
            self.close()

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(SmaCross)
cerebro.broker.setcash(100000)
results = cerebro.run()
cerebro.plot(backend='plotly')  # interactive charts
```

## Get involved

- ⭐ Star the [six repos](https://github.com/cloudQuant) if this is useful
- 🐛 Found a discrepancy between `dev` and `master`? That's an indicator bug — open an issue, it's the highest-value contribution
- 📚 Bilingual docs: [English](https://backtrader.readthedocs.io/en/latest/) · [中文](https://backtrader-zh.readthedocs.io/zh-cn/latest/)

> Disclaimer: for education and research only. Algorithmic trading involves substantial risk; past performance does not guarantee future results.
