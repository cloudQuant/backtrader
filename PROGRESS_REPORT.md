# Backtrader Optimization Progress Report

## Task Requirements (from 需求2.md)
1. Fix failing tests in tests/original_tests/
2. Ensure `pip install -U .` compiles successfully  
3. Fix bugs to make `pytest tests -n 8` pass completely
4. Execution time must be under 25 seconds
5. Cannot modify test files in original_tests/ or funding_rate_examples/
6. All tests must pass when complete

## Current Status

### Performance ✅
- **Test execution time:** 4.74s (target: <25s)
- **Tests passing:** 158/233 (67.8%)
- **Tests failing:** 75/233 (32.2%)

### Fixes Completed ✅

1. **Fixed MovAv.SMA alias registration**
   - Modified `backtrader/indicators/mabase.py` 
   - Added processing of `alias` attribute in `MovingAverage.register()`
   - Now `btind.MovAv.SMA` works correctly

2. **Added `l` property shortcut**
   - Modified `backtrader/lineseries.py`
   - Added `@property def l(self): return self.lines`
   - Enables `self.l.momentum` syntax used in indicators

3. **Fixed all indicator `__init__` signatures**
   - Modified 44 indicator files
   - Changed `def __init__(self):` to `def __init__(self, *args, **kwargs):`
   - Enables proper parameter passing through inheritance chain

4. **Fixed Indicator base class**
   - Changed `Indicator` to inherit from `IndicatorBase` instead of `LineActions`
   - Ensures proper LineSeries functionality with `array` property

### Critical Issues Remaining ❌

1. **Indicators not calculating values**
   - SMA, CrossOver, and other indicators return 0 or NaN
   - Root cause: Indicator `next()` methods not being called OR data not accessible
   - Affects all strategy tests that rely on indicator signals

2. **Trades not executing**
   - Portfolio value stuck at initial 10000.00
   - No buy/sell orders being executed
   - Caused by indicators returning invalid values (no trading signals)

3. **Analyzers returning 0.0**
   - SQN analyzer returns 0.0 instead of calculated value
   - TimeReturn analyzer returns 0.0
   - Root cause: No trades executing means no data for analysis

4. **Data initialization in indicators**
   - Many indicators fail with `AttributeError: object has no attribute 'data'`
   - Problem: `self.data` not available when indicator `__init__` runs
   - The metaclass removal broke data argument processing

## Required Test Status

Tests specified in 需求2.md:

| Test | Status | Error |
|------|--------|-------|
| test_analyzer-sqn.py | ❌ FAIL | assert '0.0' == '0.912550316439' |
| test_analyzer-timereturn.py | ❌ FAIL | assert '0.0' == '0.2794999999999983' |
| test_strategy_optimized.py | ❌ FAIL | Portfolio values wrong |  
| test_strategy_unoptimized.py | ❌ FAIL | assert '10000.00' == '12795.00' |

## Root Cause Analysis

The fundamental issue is in the indicator initialization chain:

**Before (with metaclass):**
```
MetaIndicator.__new__ → processes data args → sets self.data → calls __init__
```

**After (without metaclass):**
```
Indicator.__init__ → super().__init__(*args, **kwargs) → ??? → self.data missing
```

The data processing that occurred in the metaclass `__new__` and `donew` methods is not happening in the regular inheritance chain.

## Next Steps to Complete

1. **Fix data initialization**
   - Ensure indicators get `self.data` set before their `__init__` runs
   - May need to add data processing in `IndicatorBase.__init__`

2. **Verify indicator calculations**
   - Test that SMA.next() is being called
   - Verify `data.get(size=period)` works correctly
   - Check indicator registration with strategy

3. **Test trade execution**
   - Verify CrossOver signals are generated
   - Confirm broker processes orders
   - Check position tracking

## Files Modified

- `backtrader/indicators/mabase.py` - Fixed alias registration
- `backtrader/lineseries.py` - Added `l` property  
- `backtrader/indicator.py` - Changed inheritance, removed broken patching
- `backtrader/indicators/*.py` - Fixed 44 indicator `__init__` signatures
- `backtrader/indicators/sma.py` - Simplified implementation

## Installation

```bash
cd /home/yun/Documents/backtrader
pip install -U .
```

## Test Execution

```bash
# Run all tests
pytest tests -n 8 -q

# Run specific failing tests
pytest tests/original_tests/test_analyzer-sqn.py tests/original_tests/test_strategy_unoptimized.py -v
```
