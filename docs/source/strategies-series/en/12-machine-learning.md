# Machine Learning Strategies: Scores, Clusters, and Pseudo-Q Values

> Strategy Compendium · No. 12 · Category `machine_learning` (21 strategies) · 2026-09-02

Mention "machine learning trading" and most people picture a bottomless black-box neural network. Open the 21 strategies in `tests/functional/strategies/machine_learning/` and you find a different landscape: the ML that actually earns a place in a regression library almost always compresses the model into **one assertable rule** — a composite score, a cluster label, a pseudo Q-value.

That is not laziness; it is engineering choice. A black box whose outputs drift a hair can flip an entire backtest, while a rule like "go long when the score exceeds 0.6" can be pinned into a test assertion and re-verified forever. This article reads three representatives of the genre: the composite score, KMeans state classification, and "reinforcement learning in name."

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| KMeans candle classification | XAUUSD daily 2022-2025 | Rolling KMeans on ATR-normalized bars; follow the "active cluster" | `test_0001_candlestick_kmeans_classification_gold.py` |
| Extreme short-term gain | XAUUSD daily 2008-2025 | Enter after multi-day surges, fixed holding period | `test_0002_extreme_short_term_gain.py` |
| Gold ML Prediction | XAUUSD daily 2008-2025 | RSI/MA-trend/volatility-rank scores averaged; long above 0.6 | `test_0003_gold_ml_prediction.py` |
| Reinforcement Learning | XAUUSD daily 2008-2025 | RSI deviation + MA distance averaged into a q_score, ±0.2 triggers | `test_0004_reinforcement_learning.py` |
| Random forest ratios | IVV/IWM/IWD/PDP/DBMF daily | RandomForest classifies synthetic fundamental ratios | `test_0005_random_forest_financial_ratios_strategy.py` |
| Sentiment signal | XAUUSD daily 2008-2025 | Return z x volume z as a sentiment proxy | `test_0006_sentiment_signal_strategy.py` |
| Heads or Tails | XAUUSD M5 | Coin-flip entries driven by randomness (EA port) | `test_0007_0007_heads_or_tails.py` |
| 0187 RNN | XAUUSD M15 2025-2026 | RSI state + hand-tuned probabilities, symmetric stops | `test_0008_0187_rnn.py` |
| SkyscraperFix + ColorAML | XAUUSD M15 exec / H4 signal | Dual subsystems + de-risking after loss streaks | `test_0009_0238_exp_skyscraper_fix_coloraml_mmrec.py` |
| 0688 Fuzzy Logic | XAUUSD M15 2025-2026 | Five indicators fuzzified into one score | `test_0014_0688_fuzzy_logic.py` |
| 0715 MTC Neural Net + MACD | XAUUSD H1 | Neural-net indicator stacked on MACD (EA port) | `test_0015_0715_mtc_neural_network_plus_macd.py` |
| 1225 AML | XAUUSD M15 | Adaptive moving average EA port | `test_0020_1225_aml.py` |
| JBrainSig1 + Ultra RSI | XAUUSD M15 | Trend signal engine fused with smoothed RSI momentum | `test_0021_1293_jbrainsig1_ultra_rsi.py` |

## Deep Dive 1: Gold ML Prediction — Three Scores, One Signal

ML enters strategies in two typical postures: the **signal synthesizer** and the **state classifier**. The former compresses several features into one score and sets a threshold; the latter (next section) discretizes market regimes. [test_0003](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/machine_learning/test_0003_gold_ml_prediction.py) is the synthesizer's textbook exhibit — an RSI score, an MA trend score, and a volatility-rank score, averaged:

```python
# RSI score (0-1, oversold=1)
rsi = 100 - (100 / (1 + rs))
out['rsi_score'] = 1.0 - rsi / 100.0

# MA score (fast > slow = 1)
fast_ma = out['close'].rolling(ma_fast).mean()      # ma_fast = 20
slow_ma = out['close'].rolling(ma_slow).mean()      # ma_slow = 60
out['ma_score'] = (fast_ma > slow_ma).astype(float)

# Vol score (low vol = high score)
vol = ret.rolling(vol_period).std()                 # vol_period = 20
out['vol_score'] = 1.0 - vol.rolling(min(252, len(vol))).rank(pct=True)

# Composite
out['composite_score'] = (out['rsi_score'] + out['ma_score'] + out['vol_score']) / 3.0
```

The trading rule is two comparisons: `score > threshold (0.6)` buys in full; `score < 1.0 - threshold (0.4)` flattens. No model files, no random seeds — everything reproduces. On XAUUSD 2008-2025 from 1,000,000 with 0.02% commission, the asserted baseline reads: 39 trades, 20 wins against 18 losses (51.28% win rate), final value 3,334,048.03 (+233.40%), profit factor 2.451, Sharpe 0.636, max drawdown 34.93%. Notice that all three scores derive from price alone — the "ML" here is really hand-crafted feature engineering. That is precisely the regression library's taste: **interpretable, assertable, replayable.**

## Deep Dive 2: KMeans Clustering — a 0-for-70 Lesson in Out-of-Sample

[test_0001](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/machine_learning/test_0001_candlestick_kmeans_classification_gold.py) takes the classifier posture — and delivers the category's most honest lesson. It feeds KMeans three ratio features per bar (upper shadow, lower shadow, body, each normalized by ATR), fits on a 756-day training window, refits every 20 days, and promotes the "active cluster" whose next-day mean return beats the benchmark:

```python
fitted_model = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)  # n_clusters = 4
train_labels = fitted_model.fit_predict(train_x)
cluster_stats = train.groupby("cluster")["next_intraday_return"].agg(["mean", "count"])
benchmark = float(train["next_intraday_return"].mean())
eligible = cluster_stats[cluster_stats["count"] >= min_cluster_size]      # min_cluster_size = 20
if not eligible.empty and float(eligible.iloc[0]["mean"]) > benchmark:
    active_cluster = float(eligible.index[0])
```

When today's bar is predicted into the active cluster, the strategy buys at the next open and force-closes before the session ends. Signals are shifted with `shift(1)` to kill look-ahead. The result? On XAUUSD 2022-2025, 262 trading days, 70 trades — **zero wins, seventy losses.** The test asserts `win_count == 0` and `loss_count == 70`, nailing the shutout into the baseline. A cluster's in-sample statistical edge evaporates the moment it leaves the training window — the canonical overfitting specimen on low-signal-to-noise financial data, more vivid than any textbook lecture. (The file also demonstrates graceful degradation: without scikit-learn, the whole module skips rather than errors.)

## Deep Dive 3: Reinforcement Learning — a q_score Is Not a Q Value

[test_0004](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/machine_learning/test_0004_reinforcement_learning.py) has the scariest name and the tiniest core. It computes a "q_score" — the average of RSI's normalized distance from 50 and price's percentage distance from its 50-day moving average:

```python
ma = out['close'].rolling(ma_period).mean()         # ma_period = 50
rsi_norm = (out['rsi'] - 50) / 50.0                 # rsi_period = 14
trend = (out['close'] - ma) / ma
out['q_score'] = (rsi_norm + trend) / 2.0
```

Trading rules: flat and `q > 0.2` buys; long and `q < -0.2` flattens. No environment, no reward updates, no Bellman equation — it is an RL-*shaped* state-to-action mapping, not the real thing. The engineering commentary writes itself: a genuine RL backtest can hardly be made a deterministic regression (training's own randomness drifts every run), so this "frozen decision function" keeps RL's form while discarding its unreproducible soul. Its baseline is equally frank: 56 trades, 41.07% win rate, final value 1,956,006.56 (+95.60%), max drawdown 44.85%, Sharpe 0.348 — it earns a lot and shakes hard doing it.

## The Rest of the Bench

- **Extreme short-term gain** (`test_0002`): detect multi-day surges as "extreme events," enter on the next pullback, exit on a fixed holding period — event-driven feature engineering.
- **Random forest ratios** (`test_0005`): a real sklearn random forest classifying synthetic fundamental ratios across five ETFs; the module skips gracefully when sklearn is missing.
- **Sentiment signal** (`test_0006`): no news feed? Multiply a return z-score by a volume z-score and you have a backtestable sentiment proxy.
- **0187 RNN / 0688 fuzzy / 0715 neural+MACD / 0797 & 1154 perceptrons** (`test_0008/0014/0015/0017/0019`): a batch of MT5 EA ports — "neural network" on the label, fixed-weight indicator math inside; prime material for studying ML marketing versus ML substance.
- **1225 AML / ZeroLagEA / JBrainSig1+UltraRSI** (`test_0020/0016/0021`): adaptive-MA and trend-engine EA families, all deterministic and assertable.

## Run It Yourself

```bash
# The whole category (21 strategies, runonce=True single mode)
pytest tests/functional/strategies/machine_learning/ -v

# Just Gold ML Prediction
pytest tests/functional/strategies/machine_learning/test_0003_gold_ml_prediction.py -v

# The KMeans case (needs scikit-learn; auto-skips if absent)
pytest tests/functional/strategies/machine_learning/test_0001_candlestick_kmeans_classification_gold.py -v
```

Most tests in this category are single-file regressions asserting metric baselines under `runonce=True`; the KMeans and random-forest files depend on sklearn and skip the whole module when it is missing.

## Why Study Machine Learning Here

ML strategies fear two things above all: irreproducibility, and overfitting that goes unnoticed. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) builds the countermeasures into the infrastructure: 1,152 strategy regression tests and per-strategy asserted metric baselines record out-of-sample failures like "0 wins in 70 trades" permanently instead of letting them vanish into quiet re-tuning; the pure-Python engine runs 46% faster than the original, so feature experiments and parameter sweeps never need an overnight window; and the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup on top, with runonce/runnext dual-mode parity keeping both execution paths honest. Want real models in your strategies? First make the engine and the baselines worthy of your experiment volume.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/25-machine-learning.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
