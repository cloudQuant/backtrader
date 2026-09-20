# 016 — Self-Similarity Strategy (Iteration 35)

Intraday time-of-day pattern matching on XAUUSD 1-minute bars: the current
75-minute log-return window is correlated against the same time-of-day
windows of the most recent 60 historical trading days. When the sign-adjusted
forward returns of the `|corr| ≥ threshold` matches agree on direction with
probability ≥ 75% and positive expectation, the strategy trades in the
predicted direction, holds 15 bars, and brackets the position with an OCO
stop/take at `3 × expected_return`.

Full design: `docs/_internal/opts/requirements/迭代35-自相似性策略实现/`

## Files

| File | Purpose |
|---|---|
| `config.yaml` | run configuration (data window, params, logging, grid) |
| `run.py` | composition root: backtest / optimise modes |
| `self_similarity_strategy.py` | `SelfSimilarityStrategy` + `SimilarityEngine` |

## Usage

```bash
# single backtest with TradeLogger detail logs (from this directory)
python run.py --fromdate 2021-09-01 --todate 2021-10-31

# note: default params (corr_threshold=0.6) have ~zero hits on real XAUUSD
# (measured max|corr| median 0.259); use the optimiser to explore 0.3-0.5
python run.py --mode optimize
```

Outputs: `backtest_result.json` (standard metrics), `signals.jsonl`
(per-bar signal diagnostics with rejection reasons), `logs/` (TradeLogger),
`optimize_results.csv|json` (grid sweep, no per-trade logs).

## Parameters

| Param | Default | Meaning |
|---|---|---|
| `window_bars` | 75 | intraday return window (bars, yields window-1 returns) |
| `horizon_bars` | 15 | holding period in bars (= minutes) |
| `lookback_days` | 60 | most recent valid candidate trading days |
| `corr_threshold` | 0.6 | abs Pearson selection gate |
| `prob_threshold` | 0.75 | directional probability gate |
| `exit_multiple` | 3.0 | stop/take distance in multiples of expected log return |
| `min_matches` | 5 | minimum selected candidates required to trade |

## Limitations (BAR_MODEL_ONLY)

- Stop/take fills use bar high/low touch; no spread/queue modelling
  (the CSV `SPREAD` column is not used; costs enter via `commission_pct`).
- Forward-return statistics exclude early stop/take exits.
- Time-of-day alignment uses MT5 server time as-is (no DST remapping).
- Results do not demonstrate executable profitability; out-of-sample
  conclusions may legitimately FAIL.
