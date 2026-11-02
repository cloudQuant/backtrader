"""60.01-R8 baseline: BT tick projection and Store copy costs (median of 7 runs)."""
import copy, statistics, sys, timeit, platform
sys.path[:0] = [".", "tests/unit/feeds"]
import test_market_tick_adapter_baseline as T
from backtrader.feeds.market_tick_adapter import adapt_market_tick_event
from backtrader.feeds._btapi_cohort import _tick_value
ev = T._event()
fields = adapt_market_tick_event(ev)
def med(fn, n):
    return statistics.median(min(timeit.repeat(fn, number=n, repeat=1)) / n * 1e9 for _ in range(7))
print(platform.python_version(), platform.machine())
print(f"adapt_market_tick_event        {med(lambda: adapt_market_tick_event(ev), 20000):8.0f} ns")
print(f"deepcopy(adapted namespace)    {med(lambda: copy.deepcopy(fields), 2000):8.0f} ns  (Store does this twice per tick: write + snapshot read)")
print(f"deepcopy(MarketTickEvent)      {med(lambda: copy.deepcopy(ev), 2000):8.0f} ns")
print(f"_tick_value hit (object)       {med(lambda: _tick_value(fields, 'price', 'last_price'), 500000):8.0f} ns")
print(f"_tick_value miss->default      {med(lambda: _tick_value(fields, 'nope', default=0.0), 500000):8.0f} ns")
print(f"plain attribute read           {med(lambda: fields.last_price, 1000000):8.0f} ns")
from backtrader.utils.tick_snapshot import snapshot_tick
print(f"snapshot_tick(adapted ns)      {med(lambda: snapshot_tick(fields), 20000):8.0f} ns")
