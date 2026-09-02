# Macro at the Desk: COT Positioning, Real Rates, and a Three-Factor FX Model

> Strategy Compendium · No. 13 · Category `commodity_currency` (21 strategies) · 2026-09-02

Why does the Australian dollar track iron ore? Why does gold fear rate hikes? Both answers live on one macro chain: **rates decide carry, carry decides flows, flows decide prices**. Rising real rates make holding yieldless gold expensive; returning risk appetite lifts high-beta commodity currencies. That chain hands macro strategies a shared fate — you must watch variables the chart does not show.

The 21 backtests in `tests/functional/strategies/commodity_currency/` orbit that chain: CFTC positioning, real-rate proxies, equity and bond momentum factors, cross-sectional skewness and inventory. Each is a self-contained regression. We deep-dive three.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Change-point trading | XAUUSD daily 2008-2025 | Rolling mean/vol ratio detects regime shifts | `test_0001_gold_change_point_trading.py` |
| Walk-forward | XAUUSD daily 2008-2025 | Optimize in-window, trade out-of-window | `test_0002_gold_walk_forward.py` |
| Factor timing | XAUUSD/IVV/GTIP monthly | Value + momentum factors set gold exposure | `test_0003_gold_factor_timing.py` |
| Gold COT | XAUUSD weekly + CFTC reports | Follow commercials at z-score extremes | `test_0004_gold_cot.py` |
| Currency prediction | XAUUSD/DXY/EURUSD/USDJPY | Rolling regression on FX returns | `test_0005_gold_currency_prediction.py` |
| Commodity trend | XAUUSD daily 2008-2025 | Classic fast/slow MA trend system | `test_0006_gold_commodity_trend.py` |
| Quantpedia combo | XAUUSD daily 2008-2025 | Long-only blend of three gold anomalies | `test_0007_gold_quantpedia_strategies.py` |
| Strategy lifecycle | XAUUSD daily 2010-2025 | Sharpe decay and drawdown health of SMA200 | `test_0008_gold_strategy_lifecycle.py` |
| ETF ranking | GLD/IAU/GDX/GDXJ/BAR | Risk-adjusted momentum rotation across five ETFs | `test_0009_gold_ranking_system.py` |
| Real-rate signal | XAUUSD/IEF/GTIP daily | ETF log-ratio proxies real rates | `test_0010_gold_real_rate_signal.py` |
| Dow-gold ratio | XAUUSD/DJIA daily | Mean reversion of the gold/DJIA ratio | `test_0011_djia_gold_ratio_strategy.py` |
| GDX overnight | GDX daily | Overnight session effect + 50-day trend filter | `test_0012_gdx_overnight_session_strategy.py` |
| ARIMA-GARCH | XAUUSD daily | ARIMA for direction, GARCH for size | `test_0013_arima_garch_gold_strategy.py` |
| Multi-signal timing | XAUUSD daily | SMA/momentum/vol regime/RSI weighted ladder | `test_0014_gold_market_timing.py` |
| Commodity skewness | XAU/XAG/XPT/XPD/DBC | Long-short precious-metal skewness factor | `test_0015_commodity_skewness_strategy.py` |
| Macro FX | 4 FX pairs + IVV/IEF | Growth/rates/trend z-scores scaled by beta | `test_0016_macro_fx_strategy.py` |
| Metal inventory | XAU/XAG/XPT/XPD daily | Inventory-driven allocation across four metals | `test_0017_metal_inventory_strategy.py` |
| FX regression learning | EURUSD daily 2022-2025 | Carry/momentum/value/vol rolling regression | `test_0018_fx_regression_learning_strategy.py` |
| KA Gold Bot | XAUUSD M5 2025-12 | MT5 minute-level gold bot with spread filter | `test_0019_0019_ka_gold_bot_mt5.py` |
| SilverTrend v3 | XAUUSD M15 2025-2026 | SilverTrend indicator EA port | `test_0020_0698_silvertrend_v3.py` |
| SilverTrend dual-TF | XAUUSD M15 + H1 | H1 signals, M15 execution | `test_0021_0910_silvertrend.py` |

## Deep Dive 1: Macro FX — Three-Factor Z-Scores, Scaled by Beta

[test_0016_macro_fx_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/commodity_currency/test_0016_macro_fx_strategy.py) trades EURUSD, AUDUSD, NZDUSD, and GBPUSD — but every signal comes from two instruments it never trades: IVV (S&P 500 ETF, growth proxy) and IEF (Treasuries, rates proxy):

```python
growth_factor = _zscore(ivv['close'].pct_change(macro_lookback), zscore_lookback)
rates_factor = _zscore(-ief['close'].pct_change(macro_lookback), zscore_lookback)
...
raw_signal = (
    float(factor_weights.get('growth', 0.4)) * growth_factor * beta +
    float(factor_weights.get('rates', 0.35)) * rates_factor * beta +
    float(factor_weights.get('trend', 0.25)) * pair_trend
)
target_percent = raw_signal.clip(lower=-signal_threshold, upper=signal_threshold) / max(signal_threshold, 1e-6) * max_pair_weight
```

Two design choices deserve chewing. The **rates factor is negated**: bonds up (yields down) → positive rates factor → bigger commodity-currency longs — the macro chain as one line of code. And **beta scaling**: AUDUSD and NZDUSD, the textbook commodity currencies, get beta 1.0; GBPUSD 0.8, EURUSD 0.6. The composite is clipped at ±0.5, mapped to a ±25% per-pair cap, rebalanced every 21 trading days. Baseline: 4,331 daily bars over 2008-2025, 259 trades, final value 1,040,485.14 (+4.05%), profit factor 1.037, max drawdown 34.82% — an equity curve as flat as a currency portfolio should be.

## Deep Dive 2: Gold COT — Following the "Smart Money"

Every Friday the CFTC publishes the Commitments of Traders report, splitting positions into commercials (hedgers) and non-commercials (speculators). The classic hypothesis: commercials are the smart money, speculators are the crowd. [test_0004_gold_cot.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/commodity_currency/test_0004_gold_cot.py) encodes it as 156-week (three-year) rolling z-scores:

```python
out['commercial_z'] = (cot_weekly['commercial_net'] - commercial_mean) / commercial_std
out['speculator_z'] = (cot_weekly['speculator_net'] - spec_mean) / spec_std
long_entry = (out['commercial_z'] >= extreme_threshold) & (out['speculator_z'] <= -extreme_threshold)
long_exit = (out['commercial_z'] < exit_threshold) & (out['speculator_z'] > -exit_threshold)
```

Enter when commercials are extremely long (z ≥ +2.0) while speculators are extremely short (z ≤ −2.0); exit as both revert toward neutral (±1.0). Size scales with extremity — 3% base, 5% cap — plus a 3% stop and a "three consecutive losses, pause four weeks" cooldown. The engineering is serious too: daily XAUUSD is resampled to W-FRI weeks and aligned with COT releases (888 usable bars), the CFTC archive auto-downloaded when the local cache is missing. The result is honest: 22 trades, 36.36% win rate, final value 997,205.05 (−0.28%), profit factor 0.749. The smart-money hypothesis did not pay on twenty years of gold — and the baseline records exactly that.

## Deep Dive 3: Real-Rate Signal — An ETF Log-Ratio Proxy

Real rates (nominal minus inflation expectations) are the first-order variable in gold pricing. The trick in [test_0010_gold_real_rate_signal.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/commodity_currency/test_0010_gold_real_rate_signal.py): skip the macro database — a ratio of two ETFs approximates the level:

```python
ratio = nominal['close'] / inflation['close']          # IEF / GTIP
signal_df['real_rate_proxy'] = np.log(ratio)
signal_df['real_rate_change'] = signal_df['real_rate_proxy'] - signal_df['real_rate_proxy'].shift(signal_window)
signal_df['real_rate_trend'] = signal_df['real_rate_proxy'] - signal_df['real_rate_proxy'].rolling(trend_window).mean()
...
active = rr_change < entry_threshold and rr_trend < 0 and drawdown > -stop_loss_pct
```

When the proxy is falling over 63 days and below its 126-day trend — gold-supportive — and gold itself is not in a deep (>8%) drawdown, exposure scales from 50% to 100% by signal strength; annualized volatility above 25% halves the target; rebalancing is monthly. Baseline over 2011-2025: 2,748 daily bars, only 10 trades, final value 1,064,691.53 (+6.47%), profit factor 1.284, max drawdown 25.10%, Sharpe 0.135. Low frequency, low turnover, transparent logic — the typical physique of a macro signal strategy.

## The Rest of the Bench

- **Change-point / Walk-forward** (`test_0001/0002`): one hunts regime shifts, the other fights overfitting with rolling re-optimization — methodology more than money.
- **Factor timing / Quantpedia combo / Multi-signal timing** (`test_0003/0007/0014`): a gold factor zoo — value, momentum, volatility regimes, RSI.
- **Currency prediction / FX regression learning** (`test_0005/0018`): rolling-regression siblings — one predicts gold from FX, one autoregresses EURUSD.
- **Dow-gold ratio / GDX overnight** (`test_0011/0012`): classic ratio timing and a miner-equity session effect.
- **ARIMA-GARCH** (`test_0013`): forecast direction with ARIMA, size the position with GARCH.
- **Skewness / Inventory** (`test_0015/0017`): cross-sectional metal factors betting on distribution shape and physical inventories.
- **KA Gold Bot / SilverTrend ×2** (`test_0019/0020/0021`): minute-level EA ports giving the macro shelf some intraday fireworks.

## Run It Yourself

```bash
# The whole category (21 strategies)
pytest tests/functional/strategies/commodity_currency/ -v

# Just Macro FX
pytest tests/functional/strategies/commodity_currency/test_0016_macro_fx_strategy.py -v

# Just Gold COT (first run may download the CFTC historical archive)
pytest tests/functional/strategies/commodity_currency/test_0004_gold_cot.py -v
```

## Why Study Macro Strategies Here

The natural enemies of macro strategies are sluggish pipelines and silent result drift: multi-series alignment, resampling, external data — any wobble rewrites the conclusion. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) pins those down with 1,152 strategy regression tests and per-strategy asserted metric baselines — every number above must reproduce on every rerun. The pure Python engine runs 46% faster than the original, so multi-factor experiments finish same-day; the C++ backend (`pip install back-trader-cpp`) delivers a median 128x speedup; runonce/runnext dual-mode parity keeps both execution paths on the same page.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/26-commodity-currency.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
