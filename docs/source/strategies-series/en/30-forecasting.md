# Forecasting Strategies: ARIMA and the Discipline of Guessing Direction

> Strategy Compendium · No. 30 · Category `forecasting` (3 strategies) · 2026-09-02

An old joke in quantitative finance: economists have predicted five of the last nine recessions. Forecasting markets — especially forecasting prices — has a worse reputation still. The extreme reading of the efficient-market hypothesis claims any linear predictability in prices is arbitraged away on sight.

But "forecasts often fail" does not mean "forecasting is useless." Split the problem: predicting tomorrow's *magnitude* (up 0.83% or 1.2%?) is nearly impossible; predicting *direction* (green candle or red?) runs slightly better than a coin flip in trending markets — and a directional position only needs direction. Combine that with exits that cut losses and let winners run, and a 55% directional hit rate can compound into positive expectancy. All three strategies in `tests/functional/strategies/forecasting/` take this path: ARIMA describes "how much tomorrow's return remembers today" in autoregressive language; the forecast oscillator measures "how far price sits from its regression-forecast line." None of them predicts a target price — each answers one binary question: up, or not.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| ARIMA forecast | XAUUSD daily, 2022-2025 | ARIMA(1,0,1) rolling one-day forecast; long when positive | `test_0001_arima_time_series_forecast.py` |
| Forecast oscillator | XAUUSD 15-min → 12-hour | Deviation of price from a linear-regression forecast, T3-smoothed crossovers | `test_0002_1003_forecastoscilator.py` |
| EMA prediction | XAUUSD 15-min + 6-hour | H6 fast/slow EMA cross predicts continuation; M15 executes | `test_0003_1010_ema_prediction.py` |

## Deep Dive: ARIMA — Guessing Tomorrow in Autoregressive Language

The three parameters of ARIMA(p, d, q) are three kinds of memory: p autoregressive terms (today's return remembers the last p days), d differences (stationarize first), q moving-average terms (memory of the last q shocks). Choosing ARIMA(1,0,1) over something grander is itself a position: the dependency structure worth modeling in daily returns is shallow — a little memory of yesterday's return, a little of yesterday's shock, and beyond that you are fitting historical noise. The classic stylized facts agree: return autocorrelation is weak; the strong structure is volatility clustering, and that is GARCH territory, not ARIMA's.

[test_0001_arima_time_series_forecast.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/forecasting/test_0001_arima_time_series_forecast.py) rolls the forecast over daily returns:

```python
for idx in range(train_window, len(out)):
    if fitted_model is None or (idx - train_window) % refit_interval == 0:
        train_series = returns.iloc[idx - train_window:idx].reset_index(drop=True)
        fitted_model = ARIMA(train_series, order=selected_order).fit()   # (1, 0, 1)
    forecast = fitted_model.forecast(steps=1)
    forecasts[idx] = float(forecast.iloc[0])

out["signal"] = np.where(np.nan_to_num(out["forecast_return"], nan=0.0) > forecast_threshold, 1.0, 0.0)
out["target_pct"] = out["signal"] * target_percent   # positive → 95% long, else flat
```

Three parameters deserve a chew: a 252-day training window (one year), **a refit every 20 days**, and a zero forecast threshold — positive forecast means long, negative means flat, never short. Fixed-interval refitting is walk-forward in its cheapest form: the model only ever sees the past, absorbs new information every 20 days, and lookahead bias never gets a chance. It also explains the architecture — features are precomputed in pandas, and `next()` merely rebalances toward `target_pct`. Model fitting and order execution live in two worlds separated by a signal table.

The backtest (gold 2022-2025, a futures-style contract with 100x multiplier): across 1,032 daily bars the strategy signals long on 740 days and flat on 292 — yet only 6 rebalances and 2 completed trades (2 wins, 0 losses), ending at 2,151,710.03. Two cautions. First, leverage flatters the optics: at 1% margin and a 100x multiplier, a 95% target position means enormous notional exposure. Second, a sample of 2 closed trades says the **forecast signal is a slow variable** — with only 5 sign switches in four years, ARIMA is catching months-scale drift in gold, not daily fluctuation. Direction can indeed be guessed — but it rides trend inertia, not a crystal ball.

## The Rest of the Bench

- **Forecast oscillator** (`test_0002`): a port of the MT4/MT5 Forecast Oscillator — the percentage deviation of price from its linear-regression forecast, smoothed with Tillson T3 and traded on line crossovers at the 12-hour timeframe. 21 trades over 111 bars, 52.4% win rate, final value 999,479.5 — high-frequency break-even, a textbook for the commission-sensitive.
- **EMA prediction** (`test_0003`): a dual-timeframe structure — fast/slow EMAs (periods 1 and 2, so aggressive they nearly track price) cross on H6 to set direction, M15 executes, with a 1,000-point stop and 2,000-point target. 55 trades, 40% win rate, final value 1,000,475.90, Sharpe 0.80 — another exhibit for "win rate is not the point."

Taken together, the category's practical lesson is clear: **forecasting in production means producing an executable directional call today, then letting exit rules stitch a small edge into positive expectancy.** Improving model accuracy by a point is brutal; improving stop discipline pays immediately — study forecasting, and you end up studying position management.

## Run It Yourself

```bash
# The whole category (3 strategies)
pytest tests/functional/strategies/forecasting/ -v

# Just the ARIMA walk-forward
pytest tests/functional/strategies/forecasting/test_0001_arima_time_series_forecast.py -v
```

## Why Study Forecasting Here

Rolling refits plus bar-by-bar replay make walk-forward backtests several times more expensive than ordinary strategies — a model fit hides behind every bar. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader)'s pure-Python engine is 46% faster than the original and the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup, so compressing the refit interval from 20 days to 5 becomes an experiment you can run over coffee. The 1,152 strategy regression tests with asserted metric baselines and runonce/runnext dual-mode parity keep every number in the pipeline reproducible and comparable — before you research forecasting, you must be able to forecast your own backtest results.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/43-forecasting.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
