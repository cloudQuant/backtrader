# 016 Self-Similarity — Stability & Sample-Out Report (Iteration 35)

Date: 2026-09-20 · Data: XAUUSD_M1.csv (2021-08-12 ~ 2026-03-24, 1,628,865 bars)
Machine-readable evidence: `acceptance_summary.json` (same directory).
Verdict scope: **BAR_MODEL_ONLY** — bar touch fills, spread column unused,
costs via 0.02% commission. Nothing here demonstrates executable returns.

## 1. Structural findings (PASS-level facts)

- Default parameters (corr_threshold=0.6, per the original request) are
  structurally signal-starved on real data: sampling every 30 min over
  2021-09~10 (1,765 decision bars) the median best |corr| per bar is 0.259;
  ≥0.5 hits 0.1%, ≥0.6 hits 0%. Full-history default run: 31 trades in 4.6y.
- All timing/exiting paths work as specified (next-open fills, 15-bar
  horizon, OCO stop/take, single-position constraint) — see unit/functional
  tests (AC35-02~AC35-10).
- Performance budget met: full single backtest 251.6s (≤300s), 27-combo ×
  8-worker optimisation 643.3s (≤3600s).

## 2. Optimisation (training segment 2021-08-12 ~ 2023-12-31)

27 combinations (window 60/75/90 × corr 0.3/0.4/0.5 × prob 0.70/0.75/0.80);
pre-registered selection = max net profit among combos with ≥10 trades.

- **Every combination is net-negative** (best −5.49 at window=90,
  corr=0.5, prob=0.80 with 31 trades / 58.1% wins; worst −1945.02).
- Looser correlation gates (0.3) trade far more and lose far more —
  cost drag dominates: the "similarity" edge does not cover 2×0.02%
  commission under any tested gate.

## 3. Sensitivity (±1-step neighbourhood of selected params)

10 neighbour points, all net-negative (mean −36.83, stdev 67.37, min
−219.01, max −3.00). No hidden positive pocket adjacent to the optimum;
the loss surface direction is stable.

## 4. Three-way split (selected params, one evaluation each)

| Segment | Range | Trades | Win rate | Net |
|---|---|---|---|---|
| train | 2021-08-12 ~ 2023-12-31 | 31 | 58.1% | −5.49 |
| valid | 2024-01-01 ~ 2025-03-31 | 21 | 38.1% | −31.72 |
| **oos** | 2025-04-01 ~ 2026-03-24 | 3 | 33.3% | −4.78 |

The out-of-sample segment was evaluated once, after selection.

## 5. Verdict

**ECONOMIC FAIL / RESEARCH_REJECTED.** The self-similarity hypothesis
(intraday time-of-day return windows predict the next 15 minutes on XAUUSD
M1) does not survive costs in 2021-2026 data: the default threshold has no
signals, and every tradeable threshold variant loses money across train,
validation and untouched out-of-sample segments with a consistently negative
parameter neighbourhood. Structural correctness of the implementation is
independently verified by the iteration-35 acceptance suites; per G35-06
this economic FAIL is recorded, not iterated away. Re-opening this strategy
family requires a new pre-registered candidate (e.g. different cost model,
different signature or alignment) — not parameter fishing on this one.
