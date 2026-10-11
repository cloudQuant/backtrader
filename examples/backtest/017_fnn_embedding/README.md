# 017 — FNN Embedding Retrieval Strategy (Iteration 35-1)

Feed-forward autoencoder (FNN-AE) feature encoding with cosine-similarity
pattern matching on XAUUSD 1-minute bars. Each 75-bar window is summarised
into a 12-dim feature vector (segment returns, realised vol, RSI, momentum,
range position, candle anatomy, tick-volume), compressed to a 4-dim
embedding, and matched against a **full-history sliding library** (no
time-of-day restriction — iteration 35's structural fix). The decorrelated
Top-N neighbours' forward returns drive a Wilson-lower-bound directional
gate plus a cost-adjusted expectation gate; positions hold 15 bars with an
ATR/spread-floored OCO bracket.

Full design: `docs/_internal/opts/requirements/迭代35-1-自相似性策略改进/`

## Files

| File | Purpose |
|---|---|
| `config.yaml` | run configuration (params, training, logging, budgeted grid) |
| `run.py` | composition root: backtest / optimize / diagnose modes |
| `fnn_embedding_strategy.py` | feature engine, library, retrieval, decision chain, `FnnEmbeddingStrategy` |
| `fnn_autoencoder.py` | PyTorch AE, deterministic trainer, rolling walk-forward retraining, model cache |

## Usage

```bash
# freeze the similarity-threshold default first (design D351-06.3):
python run.py --mode diagnose --fromdate 2021-09-01 --todate 2021-10-31

# single backtest with TradeLogger detail logs
python run.py --fromdate 2021-09-01 --todate 2021-10-31

# budgeted parameter sweep (trading-layer params only; cached models)
python run.py --mode optimize

# force retraining (ignore models/ cache)
python run.py --retrain --fromdate 2021-09-01 --todate 2021-10-31
```

Outputs: `backtest_result.json` (standard metrics + encoder diagnostics),
`signals.jsonl` (per-bar retrieval diagnostics with rejection reasons),
`logs/` (TradeLogger), `reports/train_report.jsonl` (per-retrain loss,
neighbourhood retention, Procrustes drift), `reports/sim_distribution.json`
(diagnose mode), `models/` (cached rolling weights).

## No-lookahead guarantees (G351-02, three defences)

1. **Training cutoff** — each retrain uses only library samples whose
   forward label is fully realised before the retrain instant;
2. **Lazy labels** — samples enter the retrievable library only after
   their label realisation instant (`label_ready`);
3. **Rolling normalisation** — z-score statistics use only the previous
   `norm_window` samples.

## Parameters (key ones)

| Param | Default | Meaning |
|---|---|---|
| `window_bars` | 75 | feature window (bars) |
| `horizon_bars` | 15 | holding period / label horizon |
| `top_n` | 30 | decorrelated Top-N neighbours |
| `sim_threshold` | 0.8 | cosine gate (calibrate with `--mode diagnose`) |
| `prob_threshold` | 0.75 | Wilson lower-bound directional gate |
| `k_cost` | 1.5 | expectation gate = k_cost × round-trip cost |
| `embed_dim` | 4 | latent dimension (not in grid) |
| `retrain_freq` | 20 | walk-forward retraining cadence (trading days) |

## Environment (locked, NFR351-02 determinism scope)

Anaconda base (`/Users/yunjinqi/opt/anaconda3`): torch 2.13.0,
scipy 1.17.1, sklearn 1.6.1, numpy 1.26.4, pandas 3.0.3.
Backtests replay from cached model weights; a different environment needs
a fresh determinism pass (design D351-15.4).

## Known limitations (design D351-15)

- `BAR_MODEL_ONLY`: spread column is not part of fills; costs enter via
  `commission_pct` + `spread_cost_pct` in the expectation gate and the
  stop floor.
- The AE is unsupervised; encoding usefulness is judged by neighbourhood
  retention (>=0.15 engineering gate) and noise controls, not guaranteed.
- Economic conclusions may FAIL honestly; a cost gate that blocks all
  trades is recorded as "cost-infeasible", never loosened to revive signals.
