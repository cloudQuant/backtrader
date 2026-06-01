# Dev-Branch Regression Failures (3 Strategies) — RESOLVED

> **STATUS: FIXED** (2026-05-30). All 3 strategies now pass on `dev` and
> produce metrics identical to `master`. Full suite green:
> `pytest tests -n 8` → 2990 passed, 1 skipped.
>
> ## The fix (3 files, no construction-path changes)
>
> The root cause is that indicators which derive from a **secondary feed**
> (e.g. `SMA((h1.high + h1.low) / 2.0)` or `EMA(EMA(h4.close))` inside an
> M15 strategy) had their advance clock effectively tied to the strategy's
> primary (fast) feed in runonce mode, so they warmed up and emitted values
> on the wrong (fast) clock and drifted out of alignment with the slow feed.
>
> 1. `backtrader/strategy.py` — `Strategy._periodset()` gains a pre-pass that,
>    once the whole indicator tree and all feeds are finalized, resolves each
>    indicator's data dependency to the concrete feed it follows (walking
>    LinesOperation operands, indicator output lines via `_owner`/`_owner_ref`,
>    and `_clock`/`datas` chains). When that feed is a *secondary* feed it
>    pins `indicator._resolved_secondary_clock`. Crucially it does **not**
>    change `indicator._clock`, so the existing minperiod-to-feed attribution
>    (and thus strategy warmup / `bar_num`) is unchanged for every strategy.
>    Only runs when `len(self.datas) > 1`.
> 2. `backtrader/strategy.py` — the runonce post-phase advance loop in
>    `_oncepost()` and `backtrader/indicator.py` — `Indicator.advance()` both
>    honor `_resolved_secondary_clock` (falling back to `_clock`) so a
>    secondary-feed indicator advances in lockstep with its slow feed instead
>    of a clock that never ticks at the right cadence.
> 3. `backtrader/indicators/wma.py` — `WeightedMovingAverage.next()`/`once()`
>    now use `math.fsum` over the chronological (oldest-first) window with
>    `weights[0]=1.0` weighting the oldest value, matching the framework's
>    `WeightedAverage`. This removes a 1-ULP accumulation difference that
>    flipped a single strict comparison in `0208_universal_investor`
>    (`signal_count` 3861 vs 3860).
>
> Verified: the 3 target tests, the multi-feed strategies that the first
> (rejected) wrapping-based attempt regressed (`test_0060`, `test_0147`,
> `test_0148`, `test_0052`, `test_0071`, `test_31`), and the entire
> `tests/` suite all pass.

---

## Original diagnosis (kept for reference)

> Captured: 2026-05-29 · branch `dev` · baseline `master`
>
> Root cause confirmed via `scripts/run_strategy_branch_compare.py` log diff
> with `bt.observers.TradeLogger` enabled on both branches. The 3 tests
> below pass on `master` with the canonical metrics baked into commit
> `9524f562` ("test(strategies): align 3 regression baselines with master
> output"). They fail on `dev` because indicators built on top of a
> `LinesOperation` (e.g. `(h1.high + h1.low) / 2.0`) or on other indicators
> that follow a secondary feed end up advancing on the strategy's primary
> feed instead of the secondary feed the data actually derives from, so
> runonce emits indicator values too early, on misaligned bars.

---

## How to reproduce the divergence

```bash
# Build per-strategy TradeLogger wrappers under studies/branch_compare/
#   studies/branch_compare/0194_fx_chaos_scalp/run.py
#   studies/branch_compare/0113_blauergodicmdi_tm/run.py
#   studies/branch_compare/0208_universal_investor/run.py
# Each wrapper imports the inlined regression test, attaches TradeLogger,
# and dumps backtest_result.json for hash comparison.

# Diff dev vs master logs for each strategy (auto installs each branch,
# runs run.py, and writes a comparison report under logs/branch_strategy_compare/)
python scripts/run_strategy_branch_compare.py \
    studies/branch_compare/0194_fx_chaos_scalp/run.py \
    --branch current --branch master \
    --timeout 600 --install-timeout 600
```

The report lists which TradeLogger files diverge (`order.log`, `trade.log`,
`indicator.log`, `signal.log`, `position.log`, `value.log`). The
`first_diff` field for each log shows the first JSON record that differs
plus a per-field diff — that's where the real bug surfaces.

---

## Root cause (confirmed via TradeLogger log diff)

The following lines from `studies/branch_compare/0194_fx_chaos_scalp` (one
of the 3 failing strategies) make the bug concrete.

### Strategy code (excerpt)

```python
class FxChaosScalpStrategy(bt.Strategy):
    def __init__(self):
        self.base_feed = self.datas[0]   # M15 (6129 bars)
        self.h1_feed   = self.datas[1]   # H1  (1538 bars)
        self.d1_feed   = self.datas[2]   # D1  (68 bars)
        median_price = (self.h1_feed.high + self.h1_feed.low) / 2.0
        self.ao_fast = bt.indicators.SimpleMovingAverage(median_price, period=5)
        self.ao_slow = bt.indicators.SimpleMovingAverage(median_price, period=34)
        self.ao = self.ao_fast - self.ao_slow
```

### Master vs dev — `_clock` of the SMA on the LinesOperation

| | master | dev |
|---|---|---|
| `ao_fast.__class__` | `SimpleMovingAverage` | `MovingAverageSimple` (alias of same) |
| `ao_fast.data` | **`LineSeriesStub` wrapping LinesOperation** | **raw `LinesOperation`** |
| `ao_fast._clock` | **`LineSeriesStub`** (proxies LinesOperation's buflen) | **`Mt5PandasFeed` (the M15 base feed)** |
| `ao_fast._clock.buflen()` at strategy.start | 0 (gets populated alongside H1) | **6129 (M15 length, not H1)** |

Because dev's SMA `_clock` is the M15 feed (6129 bars), `_once()` calls:

```python
self.forward(size=self._clock.buflen())   # forwards 6129 slots
...
self.once(self._minperiod, self.buflen())  # once(5, 6129)
```

But the underlying `LinesOperation.array` only has 1538 valid H1
medians; positions 1538..6128 are NaN/uninitialized. Worse, even at
position `i < 1538`, `dst[i] = mean(src[i-4..i])` uses **H1-array indices
i-4..i**, which are not the H1 bars the M15 clock at `i` actually
belongs to. So the SMA at every M15 bar reads from misaligned H1 data.

On master, the SMA's `_clock` is a `LineSeriesStub` wrapping the
`LinesOperation`. `forward(buflen=0)` is a no-op until child
indicators populate the LinesOperation. Master's `_once()` flow then
binds `[0]`/`[-1]` lookups to the H1 timeline correctly, so any M15
bar reading `ao_fast[0]` gets the H1-bar-aligned SMA value.

### First diverging indicator value (logged via `bt.observers.TradeLogger`)

```text
indicator.log  line 5  (datetime 2025-12-03 02:15:00 — 5th M15 base bar)
  current__dev:  MovingAverageSimple_sma = 4215.991
  master:        MovingAverageSimple_sma = null   (correct — only 1 H1 bar exists)
```

`4215.991 = mean([4209.545, 4208.765, 4216.325, 4221.49, 4223.83])` —
the first 5 entries of the densely-packed H1 median array, computed
**before H1 has actually emitted 5 bars**.

### Where the wrap is dropped

Master applies `LineSeriesMaker(arg)` to every line-like positional
argument inside `LineIteratorMixin.donew`:

```python
# backtrader/lineiterator.py
@classmethod
def donew(cls, *args, **kwargs):
    ...
    for arg in args:
        ...
        if is_line_object:
            datas.append(LineSeriesMaker(arg))   # wraps LinesOperation in LineSeriesStub
    ...
```

Master's metaclass `MetaLineIterator(__call__)` always invoked `donew →
dopreinit → init`, so the wrap always ran.

Dev removed the metaclass and replaced it with `ParamsMixin.__init_subclass__`
+ `patched_init`. Inside `patched_init` (in `backtrader/metabase.py`),
when the indicator is constructed with positional line arguments, dev
sets `datas` directly from raw args:

```python
# backtrader/metabase.py — patched_init
if temp_datas:
    if not hasattr(self, "datas") or not self.datas:
        self.datas = temp_datas       # <-- raw, no LineSeriesMaker wrap!
        self.data = temp_datas[0]
```

So `LineIteratorMixin.donew` is never reached for indicators
constructed through `patched_init`, and the `LineSeriesMaker` wrap is
silently skipped. The downstream `_clock` resolution in `dopreinit`
then walks the raw `LinesOperation`, can't recognize it as a wrapped
proxy of a feed, and falls back to the strategy's primary feed
(`base_feed = M15`).

**Verification**: tracing every call to `LineSeriesMaker` during
`bt.indicators.SimpleMovingAverage((self.data.high + self.data.low)/2.0,
period=5)` shows it is never invoked on dev. Master invokes it once
(wrapping the `LinesOperation` into a `LineSeriesStub`).

---

## Recommended fix direction

The failing case is "indicator built on top of a `LineActions`
expression (LinesOperation, _LineDelay, bt.If/bt.And, etc.) where that
expression derives from a non-primary data feed".

Two fix paths, in order of preference:

1. **Restore the `LineSeriesMaker` wrap in `patched_init`.** The
   simplest equivalence with master: when `patched_init` extracts
   `temp_datas` from positional args, run them through
   `LineSeriesMaker(arg)` before assigning to `self.datas`. Validate
   that this also fixes the `_clock` resolution because the resulting
   `LineSeriesStub` exposes `buflen()` of the underlying line and
   `_clock` of its concrete data source.

2. **Or fix `_clock` resolution in `dopreinit` / `_register_indicator`** so
   that when `_obj.datas[0]` is a raw `LineActions` (LinesOperation
   etc.), `_line_like_source_clock` walks through it to the *concrete
   feed* underneath (e.g. `h1_feed`) instead of falling back to the
   strategy's primary feed. The current implementation already
   recognizes `LineActions` but it bottoms out at `LineBuffer` (e.g.
   `h1.high`) which doesn't have a feed-like `buflen()`, and a later
   guard reassigns `_clock` to `self.datas[0]` of the strategy.

Whichever direction is taken, add a runonce parity test that
specifically covers `bt.indicators.SMA(secondary_feed.high - secondary_feed.low, ...)`
to lock this scenario down. The existing
`tests/functional/runonce_parity` tests added in commit `575ec756` do
not cover this multi-feed-LinesOperation case — that's why the bug
slipped through.

---

## Per-strategy summary

### 1. `0194_0417_fx_chaos_scalp` (highest-signal failure)

Root cause: SMA on `(h1.high + h1.low) / 2.0` returns wrong values from
the very first bar of strategy.next(). Drives buy/sell counts from
21/18 to 2/2.

| | master (expected) | dev (actual) |
|---|---:|---:|
| `buy_count`     | 21              | 2            |
| `sell_count`    | 18              | 2            |
| `total_trades`  | 39              | 4            |
| `final_value`   | 999928.80       | 999983.10    |

**Path:** `tests/functional/strategies/trend_following/test_0194_0417_fx_chaos_scalp.py`
**Test fn:** `test_193_0194_0417_fx_chaos_scalp`

### 2. `0113_0353_exp_blauergodicmdi_tm`

Root cause: same shape — stack of `ExponentialMovingAverage` over an
H4 signal feed and over a `LinesOperation` (`dif = price - xprice`).
`indicator.log line 24` shows dev's `ExponentialMovingAverage_ema =
4208.69` where master logs `null` (correct warmup).

| | master (expected) | dev (actual) |
|---|---:|---:|
| `buy_count`     | 168             | 189          |
| `sell_count`    | 168             | 143          |
| `total_trades`  | 335             | 331          |
| `final_value`   | 1005824.20      | 999482.00    |
| `sharpe_ratio`  | 13.7881         | -1.1918      |
| `sqn`           | 1.7830          | -0.1649      |

**Path:** `tests/functional/strategies/mean_reversion/test_0113_0353_exp_blauergodicmdi_tm.py`
**Test fn:** `test_113_0113_0353_exp_blauergodicmdi_tm`

### 3. `0208_1161_universal_investor` (smallest delta)

Root cause: this one is **single-data** (M15 only) and only differs by
floating-point precision in `WeightedMovingAverage`'s last mantissa bit
(`4220.805434782608` on dev vs `4220.805434782609` on master). That
1-ULP difference flips a strict `lwma1 > ema1` comparison once and
generates one extra `signal_count` (3861 vs 3860). All trades and PnL
metrics match master exactly. Lowest priority of the three; should
become a non-issue once dev aligns its accumulation order with
master's, but is independent of the multi-data clock bug above.

| | master (expected) | dev (actual) |
|---|---:|---:|
| `signal_count` | 3860 | 3861 |
| every other metric | (matches) | (matches) |

**Path:** `tests/functional/strategies/mean_reversion/test_0208_1161_universal_investor.py`
**Test fn:** `test_209_0208_1161_universal_investor`

---

## Tools left in place for future debugging

The following helpers stay in the repo so the user can iterate on the
fix without rebuilding instrumentation:

- `studies/branch_compare/_common.py` — TradeLogger-attached cerebro
  runner, shared by the 3 wrapper `run.py` files.
- `studies/branch_compare/0194_fx_chaos_scalp/run.py`
- `studies/branch_compare/0113_blauergodicmdi_tm/run.py`
- `studies/branch_compare/0208_universal_investor/run.py`
- `scripts/run_strategy_branch_compare.py` (pre-existing) — small
  patch added to also sync `tests/datas/` into the master worktree
  and to expose `BT_BRANCH_COMPARE_DATA_ROOT` so the per-strategy
  `run.py` files can load the dev-tracked test fixtures from
  master's worktree.

After fixing the root cause, re-run:

```bash
python scripts/run_strategy_branch_compare.py \
    studies/branch_compare/0194_fx_chaos_scalp/run.py \
    --branch current --branch master --timeout 600 --install-timeout 600
```

and verify `RESULT_ALL_EQUAL True` and `DIFFERING_LOG_FILES 0`.
