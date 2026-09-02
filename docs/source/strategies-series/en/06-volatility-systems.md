# Volatility Systems: HMM Regimes, Asymmetric Sigma, and Ehlers' Signal Processing

> Strategy Compendium · No. 06 · Category `volatility_systems` (32 strategies) · 2026-09-02

In 1963 Mandelbrot made an observation still cited sixty years later: large price changes tend to follow large changes, small ones follow small — **volatility clustering**. It means the market is not a machine with constant parameters; it switches between personalities, calm and violent. Quantitative finance built two languages on top of that insight. One *models* the switching directly — hidden Markov machines inferring an unobservable regime from returns, volatility, and momentum. The other *measures* the fever — VIX-style proxies standing in for a fear thermometer. And then there is the third, cult strand: aerospace engineer John Ehlers, who imported radar signal processing into technical analysis and tries to *demodulate* cycles out of price.

All three strands live in the 32 backtests under `tests/functional/strategies/volatility_systems/`. Single-asset tests mostly run on XAUUSD daily bars (2008-2025) or M15 (three months from 2025-12).

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| HMM regime detection | XAUUSD daily, 2024-2025 | 3-state Gaussian HMM + confidence gates | `test_0007_0125_hmm_regime_detection.py` |
| Bollinger breakout (asymmetric σ) | XAUUSD daily, 2008-2025 | Enter above +3σ, exit below -1σ | `test_0021_bollinger_band_breakout.py` |
| Fisher Cyber Cycle | XAUUSD M15 + H8 signal | Fisher-sharpened Cyber Cycle turns | `test_0019_fisher_cyber_cycle.py` |
| Adaptive Cyber Cycle | XAUUSD M15 + H4 signal | Dominant-cycle adaptive oscillator | `test_0020_adaptive_cyber_cycle.py` |
| Cycle period | XAUUSD M15 + H6 signal | Hilbert-transform period estimate | `test_0018_cycle_period.py` |
| VIX-SPX divergence | XAUUSD daily | New high with rising volatility → short fragility | `test_0011_0285_vix_spx_divergence.py` |
| Adaptive VIX MA | XAUUSD daily | Volatility percentile sets the EMA alpha | `test_0012_0302_adaptive_vix_ma.py` |
| VIX futures basis | XAUUSD daily | 10-day vs 60-day volatility spread switch | `test_0013_0320_vix_futures_basis.py` |
| Gold volatility position | XAUUSD daily | Volatility-tercile sizing 100/75/50% | `test_0005_0053_gold_volatility_position.py` |
| Correlation regime | IVV/IEF/GLD/DBC daily | Stock-bond correlation sign → risk on/off | `test_0015_0374_correlation_regime_strategy.py` |
| Volatility long memory | XAUUSD daily | Hurst exponent *of volatility itself* | `test_0010_0206_volatility_long_memory.py` |

## Deep Dive 1: HMM Regime Detection — Teaching the Model to Name Bulls and Bears

The category's highest machine-learning density ([test_0007](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility_systems/test_0007_0125_hmm_regime_detection.py)). It assumes three hidden states and infers them from three observables — log return, 20-day annualized volatility, 60-day momentum — refitting a `GaussianHMM` on the trailing 252 bars, retraining every 63 days:

```python
model = GaussianHMM(n_components=n_states, covariance_type='full',
                    n_iter=300, random_state=42)      # n_states = 3
model.fit(train_std)
labels = _label_states(model, train_std)   # relabel states BULL/BEAR/NEUTRAL by mean return

current_state = int(state_seq[-1])
current_confidence = float(proba[-1, current_state])
consistent = len(recent_states) >= smoothing_window and \
    all(s == current_state for s in recent_states[-smoothing_window:])   # 5 straight days

signed_target = 0.0
if current_confidence >= confidence_threshold and consistent:   # confidence ≥ 0.55
    if current_label == 'BULL':
        signed_target = min(1.0, 1.0 * current_confidence)      # long, scaled by confidence
    elif current_label == 'BEAR':
        signed_target = max(-0.5, -0.5 * current_confidence)    # small short
```

Both defenses matter. HMM state *numbers* are meaningless — state 0 can be a bull this month and a bear after the next retrain — so states are relabeled by their mean standardized return every time. And regime signals are noisy, so exposure requires confidence above 0.55 **and** five consecutive days of agreement: better late than wrong. Over the 2024-2025 window (205 bars, 4 retrains): 27 signal changes, but the gates admitted only **2 trades — both winners** — final value 1,014,553.76 (+1.46%), SQN 4.76, max drawdown 4.22%. One more habit worth copying: the module opens with `pytest.importorskip("hmmlearn")`, so a missing optional ML dependency skips gracefully instead of painting CI red.

## Deep Dive 2: The Asymmetric Bollinger — a 3σ Door In, a 1σ Door Out

Anyone can write a Bollinger breakout. The soul of [test_0021](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility_systems/test_0021_bollinger_band_breakout.py) is that entry and exit live at *different* sigmas:

```python
out['bb_middle'] = out['close'].rolling(bb_period).mean()          # bb_period = 100
out['bb_std'] = out['close'].rolling(bb_period).std()
out['bb_upper_entry'] = out['bb_middle'] + entry_dev * out['bb_std']   # +3.0σ to enter
out['bb_lower_exit'] = out['bb_middle'] - exit_dev * out['bb_std']     # -1.0σ to exit
out['entry_signal'] = (out['close'] > out['bb_upper_entry']).astype(float)
out['exit_signal'] = (out['close'] < out['bb_lower_exit']).astype(float)
```

Requiring a close above three standard deviations filters 18 years of daily bars down to **7 entries**; exiting at just one sigma below the mean gives trends a wide runway. The result is a textbook low-frequency trend profile: 7 trades, 3 wins and 3 losses closed (42.9% win rate), profit factor **2.97**, final value **3,076,810.25** (+207.7%), max drawdown 23.1%. Low win rate × high payoff — the exact mirror image of the HMM's two-trade precision, and both are trend strategies. Same goal, two architectures, assertions holding each to its word.

## Deep Dive 3: Fisher Cyber Cycle — Ehlers' Filter Philosophy

Most indicators are statistics; Ehlers' indicators are filters. [test_0019](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/volatility_systems/test_0019_fisher_cyber_cycle.py) smooths the median price, extracts the cycle with a second-order super-smoother, normalizes it, then applies the Fisher transform — which stretches any distribution toward Gaussian and makes turning points knife-sharp:

```python
k0 = (1.0 - 0.5 * alpha) ** 2                               # alpha = 0.07
k2 = 2.0 * (1.0 - alpha)
k3 = (1.0 - alpha) ** 2
smooth[bar] = (price[bar] + 2.0*price[bar-1] + 2.0*price[bar-2] + price[bar-3]) / 6.0
cycle[bar] = k0*(smooth[bar] - 2.0*smooth[bar-1] + smooth[bar-2]) \
             + k2*cycle[bar-1] - k3*cycle[bar-2]            # Cyber Cycle
value1[bar] = (cycle[bar] - ll) / (hh - ll)                 # normalize in a length-8 window
weighted = (4.0*vals[-1] + 3.0*vals[-2] + 2.0*vals[-3] + vals[-4]) / 10.0
scaled = 1.98 * (weighted - 0.5)
scaled = min(max(scaled, -0.999999), 0.999999)              # clamp: Fisher diverges at ±1
fish[bar] = 0.5 * math.log((1.0 + scaled) / (1.0 - scaled)) # Fisher transform
trigger[bar] = fish[bar - 1]                                # trigger lags one bar
```

Fish crossing its trigger line trades the turn; signals compute on an H8 (480-minute) resampled stream, orders execute on M15, with a 1,000/2,000-point stop/target bracket. Three months: 18 trades, 7 wins, 11 losses, final value 996,022.30 (-0.40%) — a losing baseline pinned by assertion. It proves not "Ehlers doesn't work" but "these parameters had no positive expectation on this window," and it leaves you a controlled starting point. Note the clamp line, a small monument of numerical engineering: the Fisher transform diverges at ±1, and one `min(max(...))` prevents a NaN cascade.

## The Rest of the Bench

- **VIX-SPX divergence** (`test_0011`): no VIX data? Use realized volatility — short when price prints a new high while volatility rises and the price-vol correlation breaks.
- **Adaptive VIX MA** (`test_0012`): the volatility percentile over 500 days sets the EMA's alpha (constant 4.6) — the more extreme the regime, the tighter the average hugs price.
- **Gold volatility position** (`test_0005`): tercile sizing — full position below the 20th percentile, half above the 80th, 75% in between. "Be greedy when others are fearful," as three if-statements.
- **Volatility long memory** (`test_0010`): runs Hurst on the *volatility series* — trending vol follows a moving average, anti-persistent vol trades reversal.
- **Correlation regime** (`test_0015`): the stock-bond correlation is a free risk barometer — negative means risk-on (equities), positive means risk-off (bonds), ambiguous means stay balanced.

## Run It Yourself

```bash
# The whole category (32 strategies)
pytest tests/functional/strategies/volatility_systems/ -v

# Just HMM regime detection (requires hmmlearn)
pytest tests/functional/strategies/volatility_systems/test_0007_0125_hmm_regime_detection.py -v
```

## Why Study Volatility and Regimes Here

Regime-switching strategies are the ceiling of backtest complexity: HMMs refit on a rolling window, Ehlers systems align dual feeds across timeframes — one run is slow enough, let alone a parameter sweep. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) exists for this workload: 46% faster than the original in pure Python, so all 1,152 strategy regression tests finish in minutes; a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) that turns rolling-retrain sweeps into coffee-break experiments; runonce/runnext dual-mode parity so vectorized and event-driven engines must agree; and asserted metric baselines that keep you optimizing the strategy, not chasing engine drift.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/19-volatility-systems.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
