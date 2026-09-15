# Calendar Effects: Sell in May, Turn of Month, and the FOMC Drill

> Strategy Compendium · No. 08 · Category `calendar_effects` (28 strategies) · 2026-09-02

"Sell in May and go away" — the proverb supposedly dates back to the era when the City of London still moved cash by horse-drawn carriage: as the weather warmed, gentlemen retired to the countryside, liquidity dried up, and the sensible move was to liquidate in May and return in November. It sounds like a joke, yet it is among the most repeatedly tested anomalies in the academic literature: statistically, November-through-April returns have long beaten May-through-October.

Calendar effects are simultaneously the "mystical" and the "hardest" corner of quantitative trading — mystical because the economic explanations remain contested (tax-loss selling? dividend reinvestment? vacation mood?), hard because the rules are driven purely by dates. There is nowhere for overfitting to hide, and anyone can reproduce the result with one command.

This article covers the 28 calendar and event strategies in `tests/functional/strategies/calendar_effects/`: the gold seasonality family, turn-of-month windows, option expiry and quad witching, and event-driven windows around FOMC and jobs reports. Winners and losers alike are pinned in the assertions.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Sell in May (seasonal) | XAUUSD daily 2008-2025 | Buy early November, sell early May; hold Nov-Apr only | `test_0008_0103_sell_in_may.py` |
| Turn of Month | XAUUSD daily 2008-2025 | Full exposure last 3 + first 3 days of each month, 2% stop | `test_0020_0407_turn_of_month_strategy.py` |
| Gold FOMC effect | XAUUSD daily 2008-2025 | Position 5 days before proxy FOMC dates, trend filter + vol stop | `test_0022_0016_gold_fomc_effect.py` |
| Gold calendar effect | XAUUSD daily | Monthly grouped seasonal holdings | `test_0001_0005_gold_calendar_effect.py` |
| Gold turn of month (two) | XAUUSD daily | Two parameterizations of the TOM window | `test_0002_0007_gold_turn_of_month.py` / `test_0004_0027_gold_turn_of_month.py` |
| Gold seasonality | XAUUSD daily | Historical monthly returns decide direction | `test_0003_0017_gold_seasonality.py` |
| Seasonal windows / rotation | XAUUSD daily | Fixed month windows; multi-window rotation | `test_0005_0039_gold_seasonal_windows.py` / `test_0006_0043_gold_seasonality_rotation.py` |
| End-of-month seasonality | XAUUSD daily | Harvest only the last days of each month | `test_0007_0097_gold_end_of_month_seasonality.py` |
| Thanksgiving | XAUUSD daily | Holiday-window drift around Thanksgiving | `test_0009_0256_thanksgiving_seasonality.py` |
| December OPEX | XAUUSD daily | Volatility pattern of December option-expiry week | `test_0010_0258_december_opex_seasonality.py` |
| Quad witching | XAUUSD daily | Quarterly options/futures simultaneous expiry | `test_0011_0266_quad_witching_seasonal_strategy.py` |
| Sell in August | XAUUSD daily | Reverse-testing "summer weakness" | `test_0017_0401_seasonal_sell_august_strategy.py` |
| Bitcoin seasonal anomalies | IBIT daily | Monthly anomalies of a Bitcoin ETF | `test_0014_0364_bitcoin_seasonal_anomalies_strategy.py` |
| Pre-election drift | XAUUSD daily | Long window ahead of US elections | `test_0026_0306_pre_election_drift.py` |

## Deep Dive 1: Sell in May — the Proverb, Tested

This is the most purist strategy in the category ([test_0008](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/calendar_effects/test_0008_0103_sell_in_may.py)): one rule — buy around the first trading day of November, sell around the first of May, stay flat the rest of the year. The signal generation is textbook-clean:

```python
out['month'] = out.index.month
buy_signal = out['month'] == buy_month      # buy_month = 11
sell_signal = out['month'] == sell_month    # sell_month = 5
prev_month = out['month'].shift(1)
buy_entry = (prev_month != buy_month) & buy_signal    # fires only on the bar entering November
sell_entry = (prev_month != sell_month) & sell_signal
out['holding'] = ((out['month'] >= buy_month) | (out['month'] <= 4)).astype(float)
```

Study the `holding` expression: November and December are captured by `>= 11`, January-through-April by `<= 4` — the boolean logic of a wrap-around year is where calendar strategies most often go wrong. The strategy's `next()` only acts on transitions: flat plus `buy_signal` buys in full; long plus `sell_signal` closes.

**The backtest:** XAUUSD daily 2008-2025, 1,000,000 initial, 0.02% commission with 1% margin — 18 trades in 17 years, 12 wins against 6 losses (66.7% win rate), final value 2,875,338 (+187.5%), profit factor 4.93, max drawdown 28.9%, Sharpe 0.546. These are not marketing numbers; they are test assertions (`abs(final_value - 2875338.15) < 2.88` and friends, line after line). The honest caveat: gold itself was in a great bull market over 2008-2025, so a chunk of this is beta. The strategy's real value is as a baseline — "hold all year" versus "hold six months" — and an independent second implementation (`test_0015_0366`) lives in the same directory for cross-checking.

## Deep Dive 2: Turn of Month — the Window as a Window Function

The turn-of-month effect is the tendency for returns to concentrate in the last few and first few days of each month; the usual suspects are payroll/pension inflows and institutional rebalancing. This implementation ([test_0020](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/calendar_effects/test_0020_0407_turn_of_month_strategy.py)) defines the window exactly, with groupby-rank:

```python
fwd_rank = pd.Series(range(len(out)), index=out.index).groupby(current_period).transform(
    lambda x: x.rank(method='first'))
rev_rank = pd.Series(range(len(out)), index=out.index).groupby(current_period).transform(
    lambda x: x.rank(ascending=False, method='first'))
out['is_month_end_window'] = (rev_rank <= last_days).astype(float)      # last_days = 3
out['is_month_start_window'] = (fwd_rank <= first_days).astype(float)   # first_days = 3
in_window = (out['is_month_end_window'] > 0.5) | (out['is_month_start_window'] > 0.5)
out['entry_signal'] = (in_window & (~prev_in_window)).astype(float)
out['exit_signal'] = ((~in_window) & prev_in_window).astype(float)
```

On an entry signal the strategy goes fully long via `order_target_percent(target=1.0)` and arms a 2% percentage stop: `self.stop_price = close * (1.0 - self.p.stop_loss_pct)` — the standard engineering combo of "calendar window plus risk control." The file even carries a version-compatibility lesson: pandas 3.x `fillna(False)` no longer silently downcasts object booleans, so the author explicitly keeps the object dtype so pandas 2.x and 3.x emit identical signals.

**The backtest:** same XAUUSD daily series, 1,296 of 4,638 bars inside the window (about 28% of the time), 210 trades, 115 wins against 94 losses (54.8%), final value 2,000,333 (+100.0%), profit factor 1.50, Sharpe 0.562. Achieving that while invested less than a third of the time is precisely the turn-of-month pitch.

## Deep Dive 3: the FOMC Effect — Events as Calendars

Calendar effects are not only about months; they are about dates that matter. [test_0022](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/calendar_effects/test_0022_0016_gold_fomc_effect.py) studies gold drift around Federal Reserve meetings. Since a backtest cannot fetch the real FOMC calendar, it synthesizes a proxy:

```python
FOMC_MONTHS = (1, 3, 5, 6, 7, 9, 11, 12)
# take the 3rd Wednesday of each FOMC month as the proxy date, aligned to the nearest trading day
stop_pct = float(np.clip(stop_vol_multiplier * stop_pct * math.sqrt(pre_event_days),
                         min_stop_pct, max_stop_pct))    # 2.0 x vol x sqrt(5), clipped to [1%, 5%]
if historical_drift > 0 and current_trend > 0:
    direction = 1    # long only when historical pre-event drift and current trend agree
```

Position sizing is deliberately restrained: 3% notional per event (`event_position_pct=0.03`), and after three consecutive losses the system pauses for one event. **The backtest:** 69 trades, 33 wins against 36 losses, final value 994,992 (−0.50%), Sharpe −0.17, max drawdown just 1.29%. It loses money — but transparently, with tiny positions and tight stops. As a template for "testing a hypothesis that fails, at low risk," it is unmatched; positive-return companions (`test_0024` jobs-report new high, `test_0026` pre-election drift) sit in the same directory for contrast.

## The Rest of the Bench

- **Seasonal flip & composite** (`test_0012_0275` / `test_0013_0281`): assemble single-month effects into combined signals.
- **Commodity front-running** (`test_0019_0406`, GLD data): position ahead of seasonal demand.
- **Cultural calendar gold** (`test_0021_0412`, GLD data): windows around Chinese New Year and Diwali physical-demand seasons.
- **Rate-hike cycle gold** (`test_0023_0079`): three data sources (XAUUSD/GTIP/IEF) locate the rate cycle.
- **expert_news** (`test_0028`, XAUUSD 15-minute): the category's only intraday implementation — event-window engineering on high-frequency data.

## Run It Yourself

```bash
# The whole category (28 strategies)
pytest tests/functional/strategies/calendar_effects/ -v

# Just Sell in May
pytest tests/functional/strategies/calendar_effects/test_0008_0103_sell_in_may.py -v
```

## Why Study Calendar Effects Here

Calendar rules are simple and signals are sparse, which is exactly when you need infrastructure for **massive horizontal comparison**: does the proverb hold on gold, Bitcoin, and FX alike? How much does a one-day-wider window cost? That is where [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) earns its keep: 46% faster than the original in pure Python with all 1,152 strategy regression tests finishing in minutes, a median 128x speedup with the C++ backend (`pip install back-trader-cpp`) so parameter sweeps flip by as fast as calendar pages, runonce/runnext dual-mode parity, and asserted metric baselines — so the differences you measure are strategy differences, not engine noise.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/21-calendar-effects.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
