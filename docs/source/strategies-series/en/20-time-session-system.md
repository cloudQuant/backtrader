# Time-Session Systems: Night Channels and Open-Time Shorts — the Clock as a Signal

> Strategy Compendium · No. 20 · Category `time_session_system` (7 strategies) · 2026-09-02

FX and gold trade around the clock, but their liquidity has a clear heartbeat: volatility compresses through the Asian session, lifts at the European open, and amplifies again in New York. Every "open" brings a brief repricing — dealers requote, stops accumulate, news impulses release. If that intraday rhythm is stable enough, then **the clock itself is a signal**: no indicator required — open at a fixed time, close at a fixed time, and bet on the daily drift between two hands of the watch.

It sounds like folklore, but it has a proper name in market-microstructure research — the **time-of-day effect** — and open-time repricing with cross-market relays is exactly where it comes from. The 7 strategies in `tests/functional/strategies/time_session_system/`, all ports of real MT5 EAs, run on XAUUSD (gold) with $1,000,000 initial, zero commission, and a 100x multiplier. Together they span the spectrum from a bare timetable to time-plus-price hybrids.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Simple Pending Orders Time | XAUUSD M1 | Straddle stop orders at 15:00, cancel/flatten at window end | `test_0001_simple_pending_orders_time.py` |
| Night Flat Trade | XAUUSD M1 exec / H1 signal | Night channel from 3 prior H1 bars, quadrant mean-reversion entries | `test_0002_night_flat_trade.py` |
| OpenTime | XAUUSD M15 | Short at 18:45 daily, flat at 20:45 | `test_0003_opentime.py` |
| 21hour | XAUUSD M5 | Straddle breakouts at 08:00/22:00, forced flat at 21:00/23:00 | `test_0004_21hour.py` |
| Opening Closing on Time v2 | XAUUSD M15 | Enter at 05:00 along EMA50/200, flat at 21:01 | `test_0005_opening_closing_on_time_v2.py` |
| Exp_TimesDirection | XAUUSD M15 | Fixed-direction scheduled open/close (pure timetable) | `test_0006_times_direction.py` |
| Open Close on Time | XAUUSD M15 | Enter on the first bar past the open time, exit past the close time | `test_0007_open_close_on_time.py` |

## Deep Dive 1: Night Flat Trade — a Box in the Night, Regression by Quadrant

The most meticulously engineered of the seven. The hypothesis of [test_0002_night_flat_trade.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_session_system/test_0002_night_flat_trade.py): **late at night the book thins, price compresses into a box, and the edges mean-revert**. M1 bars execute; `resampledata` builds an H1 signal feed; signals are evaluated only inside the two-hour window around `open_hour` (configured as 0:00):

```python
hour = signal_dt.hour
if hour < int(self.p.open_hour) or hour > int(self.p.open_hour) + 1:
    return
if self.position:
    return

highs = [float(self.data1.high[-i]) for i in range(3)]
lows = [float(self.data1.low[-i]) for i in range(3)]
highest = max(highs)
lowest = min(lows)
diff = highest - lowest

pip = self._pip_value()
diff_min = float(self.p.diff_min_pips) * pip
diff_max = float(self.p.diff_max_pips) * pip
if not (diff > diff_min and diff < diff_max):
    return
```

Three gates fall in sequence: the clock, then a channel from the **previous 3 H1 bars'** highs and lows, then the channel width must sit between 100 and 400 pips — too narrow has no meat, too wide isn't consolidation. Entries are precise to the quadrant:

```python
if bid > lowest and bid <= lowest + diff / 4.0:
    sl = lowest - diff / 3.0
    tp = ask + float(self.p.take_profit_pips) * pip if int(self.p.take_profit_pips) > 0 else None
```

Price in the **lower quadrant** buys, with the stop a third of the channel below the floor (`lowest − diff/3`); the upper quadrant sells symmetrically. Exits use a 50-pip fixed target plus 15/5-pip trailing protection. Sizing is equally deliberate: fixed `lots=0.1`, or derived from `risk=5.0%` and `margin_per_lot=1000` — the risk budget written into the position formula, not guessed. The honest cost is selectivity: over the five-day window (2026-03-05 to 03-10, 4,562 M1 bars) exactly **one** short trade triggered — profitable, final value 1,000,061.30. It demonstrates two things at once: how session filters and volatility gates work, and how meaningless any win rate becomes when the sample is one trade.

## Deep Dive 2: OpenTime — the Clock, and Nothing Else

Strip time-session trading to its skeleton and you get [test_0003_opentime.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/time_session_system/test_0003_opentime.py). Its `next()` contains not a single price condition:

```python
def next(self):
    self.bar_num += 1
    dt = self.data.datetime.datetime(0)
    if self.order is not None:
        return
    if bool(self.p.time_close) and dt.hour == int(self.p.close_hour) and dt.minute == int(self.p.close_minute) and self.position:
        self.order = self.close()
        return
    self._manage_position()
    if self.order is not None or self.position:
        return
    if dt.hour == int(self.p.trade_hour) and dt.minute == int(self.p.trade_minute):
        key = self._window_key(dt)
        if self.last_open_key == key:
            return
        self.last_open_key = key
        if bool(self.p.use_buy):
            self._arm('buy', float(self.data.close[0]))
            return
        if bool(self.p.use_sell):
            self._arm('sell', float(self.data.close[0]))
```

Every day at 18:45 open one short (`use_sell=True`, and `stop_loss=0/take_profit=0` — completely naked); at 20:45 flatten it. The `_window_key` — a date-plus-time string — prevents duplicate opens inside one window. One more detail deserves a circle: at load time every bar's timestamp is shifted forward 15 minutes so bars are stamped at their **close**, meaning the configured 18:45 refers to "this M15 bar closes at 18:45." The classic pitfall of session-strategy ports is the source EA and the backtest engine disagreeing about timestamp semantics — off by one bar, and every open time drifts with it. Over the three-month window: 67 trades, 37 wins / 30 losses (55.2% win rate), profit factor 1.53, final value 1,002,199.70. A fixed two-hour nightly gold short earning that says the evening drift in this data leaned downward — and note that it is simultaneously **a hypothesis test with almost no degrees of freedom**: no indicator, nothing to tune, the answer to "should this hour be shorted?" is printed in plain sight. `Exp_TimesDirection` (`test_0006`) and `Open Close on Time` (`test_0007`) are its near kin, differing only in window-detection details — side by side they form a controlled experiment isolating that one variable.

## The Rest of the Bench

- **21hour** (`test_0004`): a steadier variant — schedule the formation, let price pick the direction. At 08:00 (day window, flat by 21:00) and 22:00 (night window, flat by 23:00), it places a pair of breakout stop orders ±5 points around price; whichever fills first trades, the other dies, and the position carries a 40-point target. On 18,328 M5 bars: 129 trades, 56.6% win rate — but profit factor 0.836 and final value 996,443.90. A win rate above half and still losing money: the classic payoff-ratio deficit. Beside OpenTime's bare timetable, "more structure" did not automatically buy "better results."
- **Simple Pending Orders Time** (`test_0001`): the minimalist sibling of 21hour — one pair of offset breakout orders daily at 15:00, canceled and flattened at window end, running on M1 precision.
- **Opening Closing on Time v2** (`test_0005`): a timetable with a direction filter — at 05:00 go long if EMA50 sits above EMA200, short otherwise; flat at 21:01 with a 30-point stop and 50-point target. A hybrid of MA-trend framing and session discipline.

## Run It Yourself

```bash
# The whole category (7 strategies, runonce=True, asserting migration-time baselines)
pytest tests/functional/strategies/time_session_system/ -v

# Just Night Flat Trade
pytest tests/functional/strategies/time_session_system/test_0002_night_flat_trade.py -v
```

## Why Study Time-Session Trading Here

Session strategies live and die on **timestamp exactness**: whether bars align on open or close, which side of the resampling boundary a bar belongs to, the act-once-per-window latch — slip by one bar anywhere and every scheduled open drifts wholesale. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) pins all of it into asserted baselines across 1,152 strategy regression tests, and runonce/runnext dual-mode parity guarantees the vectorized and event-driven engines open the same position at the same minute. The pure Python engine runs 46% faster than the original; the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — sweeping `trade_hour` from 18 through 23 takes minutes, and the robustness of a session hypothesis is checked on the spot.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/33-time-session-systems.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
