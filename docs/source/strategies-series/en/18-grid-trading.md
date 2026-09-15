# Grids and Martingale: The Mathematics and Discipline of Averaging

> Strategy Compendium · No. 18 · Category `grid_trading` (9 strategies) · 2026-09-02

The most widely circulated strategy family in the MT5 ecosystem is not trend following — it is grids and martingale: high win rates, equity curves that glide upward most of the time, backtest charts too pretty to refuse. Quantitative finance has long frowned on them, because hidden in the tail of that pretty curve is a geometric series.

Put the math on the table first. An averaging grid adds to losing positions — the deeper price falls, the bigger the adds — dragging the basket's average cost toward the current price, then waits for one bounce to unwind everything. Positive expectancy has two strict preconditions: **the market mean-reverts, and your margin survives the maximum adverse excursion**. Once a one-sided move walks through N layers with lots doubling per layer, margin grows as `base × (1 + 2 + 4 + … + 2^N)` — by layer 10 a single layer is 512× the first. Institutional risk limits forbid such structures; retail platforms' high leverage feeds on them. That is the whole story of why this family fares so differently in the two worlds.

The 9 strategies in `tests/functional/strategies/grid_trading/` are all ports of real MT5 EAs on the same XAUUSD M15 data (2025-12-03 to 2026-03-10, ~6,129 bars, $1,000,000 initial, zero commission, 100x multiplier) — a rare same-data, same-rules grid laboratory. We deep-dive three: the textbook averaging grid, a martingale with brakes, and a coin-flip control group.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| MoneyRain | XAUUSD H1 (resampled from M15) | DeMarker >0.5 long, ≤0.5 short, fixed lots and stops | `test_0001_moneyrain.py` |
| Very Blonde System | XAUUSD M15 | Enter toward recent 10-bar extremes, doubling-limit grid, fixed-$ basket TP | `test_0002_very_blonde_system.py` |
| Frank_UD | XAUUSD M15 | Dual long/short hedging grid, martingale averaging | `test_0003_frank_ud.py` |
| VR-SETKA-3 | XAUUSD M15 | Averaging grid: pullback entry, widening layers, weighted-average basket TP | `test_0004_vr_setka_3.py` |
| Exp_Loco | XAUUSD M15 exec / H8 signal | Reverse on Loco color-line flip | `test_0005_loco.py` |
| RndTrade | XAUUSD M15 | Coin-flip direction every 60 minutes (random baseline) | `test_0006_0463_rndtrade.py` |
| New_Random | XAUUSD M15 | Random/alternating entries, symmetric 50-point SL/TP | `test_0007_0555_new_random.py` |
| Truly Random Robot | XAUUSD M15 | Coin-flip direction, 3,000-pt stop + 1,000-pt target | `test_0008_1196_random_robot.py` |
| MartGreg | XAUUSD M15 | Dual-MACD reversal entry, lot doubles after a loss (capped once) | `test_0009_1198_martgreg.py` |

## Deep Dive 1: VR-SETKA-3 — the Textbook Averaging Grid

[test_0004_vr_setka_3.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/grid_trading/test_0004_vr_setka_3.py), ported from EA #0767, puts all three core components of an averaging grid on the table. The **first-entry signal** reads the percentage pullback from intraday extremes, confirmed by the previous bar's color:

```python
def _compute_signal(self):
    if len(self) < 2 or not bool(self.p.proc):
        return 0, 0
    close_now = float(self.data.close[0])
    day_high = float(self.data.day_high[0])
    day_low = float(self.data.day_low[0])
    prev_bull = float(self.data.close[-1]) > float(self.data.open[-1])
    prev_bear = float(self.data.close[-1]) < float(self.data.open[-1])
    x = 0.0
    y = 0.0
    if close_now > day_low:
        x = round(close_now * 100.0 / day_low - 100.0, 2)
    if close_now < day_high:
        y = round(close_now * 100.0 / day_high - 100.0, 2)
    sigup = 1 if (-float(self.p.procent) <= y and prev_bull) else 0
    sigdw = 1 if (float(self.p.procent) >= x and prev_bear) else 0
    return sigup, sigdw
```

**Layer distance widens with depth** — after the n-th layer, the next add waits longer (`dis = (distance_points + step_distance_points * n) * unit`): the deeper the adverse move, the sparser the adds. **Lots scale linearly with the layer count** (the martin factor):

```python
def _next_lot(self):
    base = self._base_lot()
    if not bool(self.p.martin):
        return base
    factor = max(len(self.layers), 1)
    return self._round_lot(base * factor)
```

And the **exit watches one thing only**: the basket's weighted-average entry plus `plus_points` (a single layer takes a fixed 30-point profit instead); one touch closes the whole basket, where `avg = Σ(entry_price × size) / Σ(size)`. Average down, wait for reversion, exit in one piece. Over the window: 1,591 trades, 67.94% win rate, profit factor 2.57, final value 1,077,029.70 (+7.70%) — but an 18.70% max drawdown, in barely three months without an extreme one-sided trend.

## Deep Dive 2: MartGreg — Martingale with Brakes

An unbounded grid has no risk ceiling; the smart move is to **cap the doubling**. The signal side of [test_0009_1198_martgreg.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/grid_trading/test_0009_1198_martgreg.py) is not grid-like at all: two MACDs on the median price `(high+low)/2` (fast 5/20, slow 10/15, signal 3) require the fast line to turn from a local trough with slow-line confirmation; every trade carries a 500-point stop and a 1,500-point target. The martingale lives only in position sizing:

```python
def _calc_lot(self):
    cash = float(self.broker.getcash())
    base_lot = self._calc_base_lot()
    multiplier = 2 ** min(self.loss_streak, self.p.doubling_count)
    lot = self._round_volume_down(base_lot * multiplier)
    lot = min(lot, self.p.volume_max)
    while lot >= self.p.volume_min and cash < lot * self.p.margin_per_lot:
        lot = self._round_volume_down(lot - self.p.volume_step)
    if lot < self.p.volume_min:
        return 0.0
    return round(lot, 8)
```

`2 ** min(loss_streak, doubling_count)` with `doubling_count=1` — double at most once, then back to base; the trailing `while` loop steps the lot down when margin runs short. Two small brakes that rewrite "blow-up math" into "bounded escalation." The result: 687 trades, only a 35.66% win rate, but the 1,500-to-500 payoff ratio (plus the capped doubling) delivers final value 1,032,971.20 (+3.30%) with a 5.14% max drawdown — low win rate, high payoff, the opposite end of the martingale spectrum from VR-SETKA-3.

## Deep Dive 3: Truly Random Robot — Why a Coin Flip Also Doesn't Lose

The category's most heterodox asset is its random trio, led by [test_0008_1196_random_robot.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/grid_trading/test_0008_1196_random_robot.py): no indicator whatsoever; when flat, flip a coin (fixed `seed=1`) for direction, then place a 3,000-point stop and a 1,000-point target:

```python
self.last_coin_toss = self.rng.randint(0, 1)
if self.last_coin_toss == 0:
    self.order = self.buy(size=self.p.lot)
    return
self.order = self.sell(size=self.p.lot)
```

909 trades, 66.23% win rate, final value 1,005,472.40 (+0.55%), max drawdown 0.56%. Why does a random strategy belong in a regression library? Because it is the **control group**. Any sophisticated strategy on this data must first beat "coin flip plus asymmetric exits" — if an indicator system can't, its intelligence is suspect. RndTrade (`test_0006`, direction re-randomized every 60 minutes, expected return near zero) and New_Random (`test_0007`, symmetric 50-point stop and target) complete the family as internal controls — random direction, asymmetric payoff, fixed cadence, each perturbation isolated. Experimental design thinking, not just strategy writing.

## The Rest of the Bench

- **MoneyRain** (`test_0001`): a single-indicator DeMarker system whose martingale lots were simplified to fixed 0.01 during migration — another "keep the signal, strip the leverage" cleanup specimen.
- **Very Blonde System** (`test_0002`): first entry after price strays 240 points from the 10-bar extreme, doubling limit orders every 35 points, the whole basket cashed at $40 of floating profit, plus a break-even lock.
- **Frank_UD** (`test_0003`): a dual-leg hedging grid that adds on both sides and manages overall risk on a virtual equity curve — the complete hedging-grid implementation.
- **Exp_Loco** (`test_0005`): reverses on an H8 color-line flip — strictly a trend strategy that wandered into the grid classroom, which makes it a useful non-grid control.

## Run It Yourself

```bash
# The whole category (9 strategies, runonce=True, asserting migration-time baselines)
pytest tests/functional/strategies/grid_trading/ -v

# Just VR-SETKA-3
pytest tests/functional/strategies/grid_trading/test_0004_vr_setka_3.py -v
```

Each MT5 port pins twenty-plus metrics — win rate, profit factor, drawdown, SQN — as baselines. Martingale tail risk is precisely the family that needs "every change stays comparable" guardrails.

## Why Study Grids and Martingale Here

Grid strategies have many parameters, strong path dependence, and acute sensitivity to margin assumptions — the family most prone to "tuning yourself into a hallucination," and therefore the one that most needs large-scale, reproducible backtesting infrastructure. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) provides it: the pure Python engine is 46% faster than the original and finishes all 1,152 strategy regression tests in minutes; the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup, turning sensitivity sweeps over layer counts, martingale factors, and spacing into a coffee break; runonce/runnext dual-mode parity and asserted baselines keep you optimizing the grid, not being misled by engine drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/31-grid-trading.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
