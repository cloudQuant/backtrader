#!/usr/bin/env python
import sys
sys.path.insert(0, '/home/yun/Documents/backtrader')
sys.path.insert(0, '/home/yun/Documents/backtrader/tests/original_tests')

import backtrader as bt
import testcommon
from test_strategy_unoptimized import RunStrategy

# Monkey patch stop() to not assert
original_stop = RunStrategy.stop
def patched_stop(self):
    pass  # Don't assert, just continue

RunStrategy.stop = patched_stop

# Test all 12 configurations
configs = []
for runonce in [True, False]:
    for preload in [True, False]:
        for exactbars in [-2, -1, False]:
            configs.append((runonce, preload, exactbars))

print("Testing all 12 configurations:")
print("=" * 80)

results = []
for i, (runonce, preload, exactbars) in enumerate(configs, 1):
    # Get fresh data for each test
    datas = [testcommon.getdata(0)]

    # Create cerebro with this configuration
    cerebro = bt.Cerebro(runonce=runonce, preload=preload, exactbars=exactbars)
    cerebro.adddata(datas[0])
    cerebro.addstrategy(RunStrategy, printdata=False, printops=False, stocklike=False)

    # Run the strategy
    strats = cerebro.run()
    strat = strats[0]
    value = cerebro.broker.getvalue()
    cash = cerebro.broker.getcash()
    buys = len(strat.buycreate)
    sells = len(strat.sellcreate)

    # Store result
    results.append({
        'runonce': runonce,
        'preload': preload,
        'exactbars': exactbars,
        'value': value,
        'cash': cash,
        'buys': buys,
        'sells': sells
    })

    # Print progress
    status = "✓ PASS" if abs(value - 12795.00) < 1.0 else "✗ FAIL"
    eb_str = f"{exactbars:>5}" if exactbars is not False else "False"
    print(f"{i:2d}. runonce={str(runonce):5s} preload={str(preload):5s} exactbars={eb_str} → "
          f"value={value:8.2f} buys={buys:2d} sells={sells:2d} {status}")

print("\n" + "=" * 80)
print("Summary:")

# Count passes and fails
expected_value = 12795.00
passed = sum(1 for r in results if abs(r['value'] - expected_value) < 1.0)
failed = len(results) - failed

print(f"Passed: {passed}/12")
print(f"Failed: {failed}/12")

if failed > 0:
    print("\nFailed configurations:")
    for r in results:
        if abs(r['value'] - expected_value) >= 1.0:
            eb_str = f"{r['exactbars']:>5}" if r['exactbars'] is not False else "False"
            print(f"  runonce={str(r['runonce']):5s} preload={str(r['preload']):5s} "
                  f"exactbars={eb_str} → value={r['value']:8.2f} (expected {expected_value:.2f})")
            if r['buys'] == 0:
                print(f"    → NO TRADES (CrossOver not generating signals)")

print("\n" + "=" * 80)
