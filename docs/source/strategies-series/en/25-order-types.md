# Order Types in Action: Brackets, OCO, and Risk Management Written into the Order Book

> Strategy Compendium · No. 25 · Category `order_types` (6 strategies) · 2026-09-02

Strategy decides *when* to buy or sell; order type decides *how*. Most backtesting tutorials teach you `self.buy()` and then pretend it's free: instant, full-size, no slippage. In real markets, the execution details of stops, limits, and OCO groups often matter more to net P&L than the signal itself. The classic tragedy: perfect signal, precise entry — then lunch runs long and nobody placed the stop.

This article covers the 6 order-type backtests in `tests/functional/strategies/order_types/`. They are not six "strategy ideas" but six interface contracts between your strategy and the market — how the bracket trio makes "every entry carries a stop" an atomic operation, how OCO makes a group of orders mutually exclusive. Consider this the "framework feature + strategy" episode of the series: a working tour of backtrader's order API.

## Category at a Glance

| Strategy | Data | Core idea | Source |
|----------|------|-----------|--------|
| Stop order | Convertible-bond index, daily | After a golden-cross fill, auto-place a 3% stop; exit on dead cross | `test_05_stop_order_strategy.py` |
| Bracket trio | 2005-2006 daily | Limit main + stop + target submitted as one package; child orders arm on parent fill | `test_37_bracket_order_strategy.py` |
| OCO orders | 2005-2006 daily | Three limit buys at different depths; one fill cancels the rest | `test_41_oco_order_strategy.py` |
| StopTrail | 2005-2006 daily | MA-cross entry template with a `trailpercent` parameter on standby | `test_42_stoptrail_strategy.py` |
| Order Target | YHOO 2005-2006 daily | Compute target position percent by date; `order_target_percent` does the diff | `test_43_order_target_strategy.py` |
| Order Close | 2005-2006 daily | `exectype=bt.Order.Close` fills at the current bar's close | `test_61_order_close.py` |

## Deep Dive 1: Bracket — Making the Stop an Atomic Operation

In a backtest, "forgot the stop" never happens — code always remembers. The bracket order's value is sinking that memory into the **order structure itself**: main order, stop-loss, and take-profit submitted as one unit; the moment the main order fills, both children arm; when either child fills, the other is cancelled. The human loophole is closed by the order book.

The implementation ([test_37_bracket_order_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/order_types/test_37_bracket_order_strategy.py)) builds the trio in one shot on a golden cross:

```python
if self.cross > 0.0:
    close = self.data.close[0]
    p1 = close * (1.0 - self.p.limit)      # main: limit buy 0.5% below
    p2 = p1 - 0.02 * close                 # stop: 2% of close below p1
    p3 = p1 + 0.02 * close                 # target: 2% of close above p1

    o1 = self.buy(exectype=bt.Order.Limit, price=p1,
                  valid=valid1, transmit=False)
    o2 = self.sell(exectype=bt.Order.Stop, price=p2,
                   valid=valid2, parent=o1, transmit=False)
    o3 = self.sell(exectype=bt.Order.Limit, price=p3,
                   valid=valid3, parent=o1, transmit=True)   # last order ships the group
```

The keys are `transmit` and `parent`: the first two orders are held back with `transmit=False` until the third one's `transmit=True` releases the whole group; `parent=o1` declares the hierarchy the engine uses to arm children on fill and cancel the sibling when one side executes. On 2005-2006 data this yields 8 completed round trips (4 wins, 4 losses — a clean 50%), final value 99,875.56, pinned by `abs(final_value - 99875.56) < 0.01`. Note the main order is a limit valid for 3 days: if price never pulls back, the whole package expires — in a bull run you miss the move. That's the bracket's price of discipline.

## Deep Dive 2: OCO — One Group of Orders, Only One Future

OCO (One-Cancels-Other) solves the opposite problem: **you want to buy the dip, but you don't know how deep the dip runs.** Instead of guessing one price, place a limit order at each of three depths and declare them mutually exclusive — first to fill cancels the rest.

[test_41_oco_order_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/order_types/test_41_oco_order_strategy.py) hangs three buys on a golden cross, depths growing with the square and cube of the offset:

```python
p1 = self.data.close[0] * (1.0 - self.p.limit)          # 0.5% below
p2 = self.data.close[0] * (1.0 - 2 * 2 * self.p.limit)  # 2% below
p3 = self.data.close[0] * (1.0 - 3 * 3 * self.p.limit)  # 4.5% below

o1 = self.buy(exectype=bt.Order.Limit, price=p1, valid=valid1, size=1)
o2 = self.buy(exectype=bt.Order.Limit, price=p2, valid=valid2, oco=o1, size=1)
o3 = self.buy(exectype=bt.Order.Limit, price=p3, valid=valid3, oco=o1, size=1)
```

`oco=o1` links the later orders into the first one's group. The near order gets only 3 days of validity (`limdays=3`), the far ones get 1,000 — betting that shallow pullbacks come fast while deep ones are worth waiting for. After a fill, the position is held 10 bars and closed by time. The backtest ends at 99,936.20 with a Sharpe of **-728** — an extreme value that is not a bug but the arithmetic of 1-share positions with sparse trades under tiny annualized volatility. The test's own comment says it plainly: these numbers confirm the **OCO cancellation mechanism works**, not that the strategy profits. That is a regression test doing its actual job — validating framework behavior, not returns.

## The Rest of the Bench

- **Stop order** (`test_05`): on the convertible-bond index, the fill triggers `self.sell(exectype=bt.Order.Stop, price=buy_price * 0.97)` inside `notify_order`; a dead cross cancels the stop before the market close — cancel-then-close ordering is the classic detail of managing resting orders. 211 buys over the run, 106 stopped out.
- **StopTrail** (`test_42`): descended from the official stoptrail sample, params keep `trailpercent=0.02`; this version runs on cross-driven market orders (final 105,190.30, Sharpe 1.19). Rewriting it as a true `sell(exectype=bt.Order.StopTrail, trailpercent=0.02)` is the best exercise on this page.
- **Order Target** (`test_43`): declare targets, not trades — odd months hold `date/100` percent, even months `(31-date)/100`, and `order_target_percent` computes and places the difference. The on-ramp from "trade thinking" to "position thinking."
- **Order Close** (`test_61`): `exectype=bt.Order.Close` fills at the current bar's close (paired with `seteosbar(True)`), removing the one-bar next-open delay; final value 102,995.50.

## Run It Yourself

```bash
# The whole category (6 strategies, runonce/runnext dual-mode parity)
pytest tests/functional/strategies/order_types/ -v

# Just the bracket trio
pytest tests/functional/strategies/order_types/test_37_bracket_order_strategy.py -v
```

## Why Study Order Types Here

Order semantics are where backtest fidelity quietly dies: whether a limit fills on a touch, the gap between a stop's trigger and its fill price, the exact timing of OCO cancellations — all depend on broker-simulator precision. [cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) freezes these behaviors into asserted baselines across 1,152 strategy regression tests, so any drift in order semantics trips an alarm; runonce/runnext dual-mode parity guarantees vectorized speed never changed a single fill. The pure-Python engine is 46% faster than the original, and the C++ backend (`pip install back-trader-cpp`) adds a median 128x speedup — enough to permute all six order types over the same data and find the execution details that belong to *your* strategy.

Find it useful? Star the project on [GitHub](https://github.com/cloudQuant/backtrader). Start from the [series overview](00-overview.md) for the full map. A deeper (Chinese) treatment lives [here](../zh/38-order-types.md).

> Risk disclaimer: for education and research only. Backtests use historical data and do not constitute investment advice; algorithmic trading carries substantial risk of loss.
