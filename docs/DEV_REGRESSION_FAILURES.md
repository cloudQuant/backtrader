# Dev-Branch Regression Failures (3 Strategies)

> Captured: 2026-05-29 · branch `dev` · baseline `master`
>
> All three tests below pass on `master` with the canonical metrics baked
> into commit `9524f562` ("test(strategies): align 3 regression baselines
> with master output"). They fail on `dev` because dev's runonce calculation
> path produces different numbers than master.
>
> Quick repro:
> ```bash
> # baseline check (must pass)
> git checkout master && pip install -U . && \
>   pytest tests/functional/strategies -n 6 --use-installed-backtrader
>
> # back to dev (the 3 tests below must currently fail)
> git checkout dev && \
>   pytest tests/functional/strategies/trend_following/test_0194_0417_fx_chaos_scalp.py \
>          tests/functional/strategies/mean_reversion/test_0113_0353_exp_blauergodicmdi_tm.py \
>          tests/functional/strategies/mean_reversion/test_0208_1161_universal_investor.py -v
> ```

---

## TL;DR — Where to dig

The shared symptom is **"runonce on a multi-data setup produces different
indicator values than master"**. The strongest single suspect is dev's
rewritten `once()` in `backtrader/indicators/sma.py` (and the analogous
direct-indexing code in `Average.once()` in `backtrader/indicators/basicops.py`):
both iterate `range(start, end)` against `self.data.array` directly, which is
broken when `self.data` is a `LinesOperation` whose underlying length is
shorter than the primary feed's length. Master's `MovingAverageSimple`
delegates to `Average(self.data, period=...)` and inherits the canonical
`PeriodN.once()` machinery — so it never falls into this trap.

```python
# master (correct, 3 lines):
class MovingAverageSimple(MovingAverageBase):
    alias = ('SMA', 'SimpleMovingAverage',)
    lines = ('sma',)
    def __init__(self):
        self.lines[0] = Average(self.data, period=self.p.period)
        super().__init__()
```

```python
# dev (broken once() — see the loop indexing self.data.array directly):
class MovingAverageSimple(MovingAverageBase):
    ...
    def once(self, start, end):
        dst = self.lines[0].array
        src = self.data.array
        period = self.p.period
        actual_end = min(end, len(src))
        ...
        for i in range(calc_start, actual_end):
            window = src[i - period + 1 : i + 1]
            dst[i] = math.fsum(window) / period
```

The loop walks the primary timeline (length 6129 for these tests, M15 bars)
but `src` only has 1538 valid entries (H1 bars) followed by trailing NaN,
so `dst[i]` at `i` past 1538 is computed from misaligned (or NaN) windows
— and even before that, the H1-bar at H1-array-index `i` is *not* the H1
bar that the M15 clock at base-bar `i` belongs to.

**Recommended fix direction (match master):** restore master's
`MovingAverageSimple.__init__` delegation to `Average(...)`, drop dev's
`next()` and `once()` overrides, and audit `Average.once()` /
`PeriodN.once()` to ensure they honor multi-data clock binding. A first
attempt at this fix was reverted at the editor level — re-do it cleanly,
verify with the repro below, and audit other base-ops indicators
(`SumN`, `AverageN`, `WeightedMovingAverage`, etc.) for the same bug
shape.

---

## 1. `0194_0417_fx_chaos_scalp` (highest-signal failure)

| | master (expected) | dev (actual) | delta |
|---|---:|---:|---:|
| `buy_count`     | 21              | 2            | -19 |
| `sell_count`    | 18              | 2            | -16 |
| `win_count`     | 16              | 1            | -15 |
| `loss_count`    | 23              | 3            | -20 |
| `total_trades`  | 39              | 4            | -35 |
| `final_value`   | 999928.80       | 999983.10    | +54.30 |
| `max_drawdown`  | 0.04279         | 0.00572      | -0.0371 |
| `sharpe_ratio`  | -0.8220         | -1.5103      |  |
| `sqn`           | -0.10608        | -0.19693     |  |

**Path:** `tests/functional/strategies/trend_following/test_0194_0417_fx_chaos_scalp.py`
**Test fn:** `test_193_0194_0417_fx_chaos_scalp`

**Strategy shape (relevant excerpt):**

```python
class FxChaosScalpStrategy(bt.Strategy):
    def __init__(self):
        self.base_feed = self.datas[0]   # M15  (6129 bars)
        self.h1_feed   = self.datas[1]   # H1   (1538 bars)
        self.d1_feed   = self.datas[2]   # D1   (68 bars)
        median_price = (self.h1_feed.high + self.h1_feed.low) / 2.0   # LinesOperation on H1
        self.ao_fast = bt.indicators.SimpleMovingAverage(median_price, period=5)
        self.ao_slow = bt.indicators.SimpleMovingAverage(median_price, period=34)
        self.ao = self.ao_fast - self.ao_slow
```

### Diagnosis already collected

- `h1.high[0]` and `h1.low[0]` are **identical** between master and dev
  (data feed is fine).
- `median_price` (the `LinesOperation`) values are **identical** between
  master and dev when accessed via `[0]`/`[-N]`.
- `SimpleMovingAverage(median_price, period=5)` is **wrong on dev**:
  e.g. at one debug point dev returns `fast=4832.21` where master returns
  `fast=4332.76` (real H1 median around 4334).
- Inserting a debug print in `backtrader/indicators/sma.py once()` showed
  `len(src) = 6129` (M15 length) but `src[1538:]` is all NaN — the SMA's
  `for i in range(calc_start, end)` loop is computing `dst[i]` from
  H1-array index `i`, which is the wrong H1 bar for the M15 clock at
  base-bar position `i`.
- Master avoids this entirely because `MovingAverageSimple.__init__`
  delegates to `Average(self.data, period=...)`, which uses the
  framework's data-binding machinery rather than raw array indexing.

### Likely fix

1. Replace `backtrader/indicators/sma.py` with master's 3-line delegation
   form.
2. Verify (and fix if needed) `Average.once()` /
   `PeriodN.once()` in `backtrader/indicators/basicops.py` so they advance
   along `self.data`'s clock-bound iterator instead of indexing
   `self.data.array` directly.
3. Re-run `tests/functional/runonce_parity` (added via
   `575ec756 Add runonce parity strategy tests`) to catch regressions.

---

## 2. `0113_0353_exp_blauergodicmdi_tm`

| | master (expected) | dev (actual) | delta |
|---|---:|---:|---:|
| `buy_count`     | 168             | 189          | +21 |
| `sell_count`    | 168             | 143          | -25 |
| `win_count`     | 145             | 124          | -21 |
| `loss_count`    | 190             | 207          | +17 |
| `total_trades`  | 335             | 331          | -4 |
| `final_value`   | 1005824.20      | 999482.00    | -6342 |
| `max_drawdown`  | 0.29228         | 0.31346      | +0.0212 |
| `annual_return` | 2.7112          | -0.1104      | (sign flip) |
| `sharpe_ratio`  | 13.7881         | -1.1918      | (sign flip) |
| `sqn`           | 1.7830          | -0.1649      | (sign flip) |

**Path:** `tests/functional/strategies/mean_reversion/test_0113_0353_exp_blauergodicmdi_tm.py`
**Test fn:** `test_113_0113_0353_exp_blauergodicmdi_tm`

**Strategy shape (relevant excerpt):**

```python
class ExpBlauErgodicMDITmStrategy(bt.Strategy):
    def __init__(self):
        self.exec_feed   = self.datas[0]   # M15  (6129 bars)
        self.signal_feed = self.datas[1]   # H4   (signal timeframe)
        # 4 stacked EMAs over signal_feed.close, signal lines built at H4 resolution.
        price   = bt.indicators.ExponentialMovingAverage(self.signal_feed.close, period=20)
        xprice  = bt.indicators.ExponentialMovingAverage(price,   period=5)
        dif     = price - xprice                                  # LinesOperation
        xdif    = bt.indicators.ExponentialMovingAverage(dif,    period=5)
        xxdif   = bt.indicators.ExponentialMovingAverage(xdif,   period=5)
        xxxdif  = bt.indicators.ExponentialMovingAverage(xxdif,  period=5)
```

### Diagnosis hypothesis

Same family as 0194: a stack of `ExponentialMovingAverage` indicators is
applied to the H4 signal feed (and to a `LinesOperation` `dif = price -
xprice`) inside a strategy whose primary feed is M15. If
`ExponentialSmoothing.once()` (in `backtrader/indicators/basicops.py`)
indexes `self.data.array` directly using the M15 timeline, the same
multi-data clock-misalignment bug applies and the EMA stack drifts.

The sign-flip on `annual_return`, `sharpe_ratio` and `sqn` plus the asymmetric
buy/sell counts (168/168 → 189/143) point at signals being generated at
different bars, not just being slightly noisy.

### Suggested next steps

1. After fixing `SMA`, re-run; if 0113 still fails, instrument
   `ExponentialSmoothing.once()` with a small print at e.g.
   `len(self.data) == warmup` to compare the EMA value emitted on a known
   H4 bar between master and dev.
2. Cross-check with the new `runonce_parity` tests — the EMA stack may
   already have a parity test that's silently passing because it doesn't
   cover multi-data wiring.

---

## 3. `0208_1161_universal_investor` (smallest delta)

| | master (expected) | dev (actual) | delta |
|---|---:|---:|---:|
| `signal_count`        | 3860            | 3861         | +1 |
| `buy_count`           | 68              | 68           | 0 |
| `sell_count`          | 68              | 68           | 0 |
| `total_trades`        | 136             | 136          | 0 |
| `trade_count`         | 135             | 135          | 0 |
| `win_count`           | 46              | 46           | 0 |
| `loss_count`          | 89              | 89           | 0 |
| `final_value`         | 1004551.90      | 1004551.90   | 0 |
| every other metric    | (matches)       | (matches)    | 0 |

**Path:** `tests/functional/strategies/mean_reversion/test_0208_1161_universal_investor.py`
**Test fn:** `test_209_0208_1161_universal_investor`

**Strategy shape (relevant excerpt):**

```python
class UniversalInvestorStrategy(bt.Strategy):
    def __init__(self):
        self.ema  = bt.indicators.ExponentialMovingAverage(self.data.close, period=23)
        self.lwma = bt.indicators.WeightedMovingAverage(self.data.close, period=23)

    def next(self):
        self.bar_num += 1
        ema1, ema2 = float(self.ema[-1]), float(self.ema[-2])
        lwma1, lwma2 = float(self.lwma[-1]), float(self.lwma[-2])
        open_buy  = lwma1 > ema1 and lwma1 > lwma2 and ema1 > ema2
        open_sell = lwma1 < ema1 and lwma1 < lwma2 and ema1 < ema2
        if (open_buy and not open_sell) or (open_sell and not open_buy):
            self.signal_count += 1
        ...
```

### Diagnosis hypothesis

This one is **single-data** (only M15) and has **a single bar of drift in
`signal_count` only** — every trade and PnL metric matches master. That's
consistent with a one-bar-off boundary in either `ExponentialMovingAverage`
or `WeightedMovingAverage` warmup / `nextstart` handling on dev. Worth
checking:

- Does dev's `EMA`/`WMA` `once()` emit a value one bar earlier than
  master at the very first valid bar after `addminperiod`?
- Or does the strategy itself trigger one extra `signal_count` because
  some warmup-skip condition was relaxed?

The fact that no actual trade fires off this extra signal (because the
position is held when the extra signal occurs) is why all downstream
metrics still match. Lowest priority of the three; fixable independently
once the SMA/EMA `once()` family is healthy.

---

## Reference: known-good (master) metrics live in the test files themselves

The current expected values are baked directly into each test file's
assertion block (see commit `9524f562`). When the dev fix lands, those
assertions should pass on `dev` as well — no expected-value updates
required.

## Reference: artifacts deleted as part of this rewrite

- `OFFICIAL_BACKTRADER_REGRESSION_ANALYSIS.md` (deleted)
- `OFFICIAL_BACKTRADER_REGRESSION_FAILURES.md` (deleted)
- `scripts/capture_master_metrics.py` (deleted — was a one-shot baseline tool)
