# Performance Comparison Report

Generated: 2025-10-27 08:45:36

====================================================================================================

## Overall Performance

| Metric | master | remove-metaprogramming | Difference |
|--------|----------|----------|------------|
| **Execution Time** | 63.1081s | 81.8313s | +18.7232s (+29.67%) ⚠️ **SLOWER** |

### Summary

- Functions improved (faster): **24**
- Functions degraded (slower): **47**
- New functions: **221**
- Removed functions: **221**

## Top 20 Degraded Functions (Slower)

Functions that became slower in the second branch:

| Function | Branch 1 | Branch 2 | Difference | % Change |
|----------|----------|----------|------------|----------|
| `{built-in method builtins.hasattr}` | 1.2370s | 7.4580s | +6.2210s | +502.91% |
| `{built-in method builtins.len}` | 8.0610s | 13.2500s | +5.1890s | +64.37% |
| `{built-in method builtins.setattr}` | 0.5890s | 4.6480s | +4.0590s | +689.13% |
| `{built-in method builtins.getattr}` | 1.3010s | 5.1760s | +3.8750s | +297.85% |
| `F:\source_code\backtrader\backtrader\indicators\__init__.py:1(<module>)` | 0.2870s | 2.0730s | +1.7860s | +622.30% |
| `F:\source_code\backtrader\backtrader\indicators\ols.py:1(<module>)` | 0.0010s | 1.4650s | +1.4640s | +146400.00% |
| `F:\source_code\backtrader\backtrader\indicators\hurst.py:1(<module>)` | 0.0000s | 0.2170s | +0.2170s | +0.00% |
| `{method 'append' of 'list' objects}` | 0.1110s | 0.2210s | +0.1100s | +99.10% |
| `F:\source_code\backtrader\backtrader\indicators\basicops.py:1(<module>)` | 0.0050s | 0.1030s | +0.0980s | +1960.00% |
| `F:\source_code\backtrader\backtrader\indicators\sma.py:1(<module>)` | 0.0010s | 0.0920s | +0.0910s | +9100.00% |
| `{built-in method builtins.any}` | 0.4850s | 0.5160s | +0.0310s | +6.39% |
| `F:\source_code\backtrader\backtrader\indicators\rsi.py:1(<module>)` | 0.0020s | 0.0260s | +0.0240s | +1200.00% |
| `F:\source_code\backtrader\backtrader\indicators\oscillator.py:1(<module>)` | 0.0140s | 0.0310s | +0.0170s | +121.43% |
| `F:\source_code\backtrader\backtrader\indicators\stochastic.py:1(<module>)` | 0.0020s | 0.0140s | +0.0120s | +600.00% |
| `F:\source_code\backtrader\backtrader\indicators\directionalmove.py:1(<module>)` | 0.0030s | 0.0150s | +0.0120s | +400.00% |
| `F:\source_code\backtrader\backtrader\indicators\envelope.py:1(<module>)` | 0.0100s | 0.0220s | +0.0120s | +120.00% |
| `F:\source_code\backtrader\backtrader\indicators\priceoscillator.py:1(<module>)` | 0.0020s | 0.0120s | +0.0100s | +500.00% |
| `F:\source_code\backtrader\backtrader\indicators\momentum.py:1(<module>)` | 0.0010s | 0.0100s | +0.0090s | +900.00% |
| `F:\source_code\backtrader\backtrader\indicators\pivotpoint.py:1(<module>)` | 0.0010s | 0.0090s | +0.0080s | +800.00% |
| `F:\source_code\backtrader\backtrader\indicators\williams.py:1(<module>)` | 0.0000s | 0.0070s | +0.0070s | +0.00% |

## Top 20 Improved Functions (Faster)

Functions that became faster in the second branch:

| Function | Branch 1 | Branch 2 | Difference | % Change |
|----------|----------|----------|------------|----------|
| `{built-in method builtins.max}` | 1.4110s | 0.7530s | -0.6580s | -46.63% |
| `<frozen importlib._bootstrap>:1304(_find_and_load_unlocked)` | 2.6560s | 2.2420s | -0.4140s | -15.59% |
| `<frozen importlib._bootstrap>:1349(_find_and_load)` | 2.6560s | 2.2420s | -0.4140s | -15.59% |
| `{built-in method builtins.__import__}` | 2.6560s | 2.2420s | -0.4140s | -15.59% |
| `<frozen importlib._bootstrap>:911(_load_unlocked)` | 2.6550s | 2.2410s | -0.4140s | -15.59% |
| `<frozen importlib._bootstrap_external>:1020(exec_module)` | 2.6550s | 2.2410s | -0.4140s | -15.59% |
| `<frozen importlib._bootstrap>:480(_call_with_frames_removed)` | 2.6530s | 2.2410s | -0.4120s | -15.53% |
| `F:\source_code\backtrader\tests\original_tests\test_strategy_optimized.py:1(<mod` | 2.6520s | 2.2410s | -0.4110s | -15.50% |
| `F:\source_code\backtrader\tests\original_tests\testcommon.py:1(<module>)` | 2.6490s | 2.2400s | -0.4090s | -15.44% |
| `F:\source_code\backtrader\backtrader\__init__.py:1(<module>)` | 2.6430s | 2.2390s | -0.4040s | -15.29% |
| `{method 'append' of 'array.array' objects}` | 0.6840s | 0.3080s | -0.3760s | -54.97% |
| `{method 'append' of 'collections.deque' objects}` | 0.6230s | 0.3180s | -0.3050s | -48.96% |
| `F:\source_code\backtrader\backtrader\indicators\myind.py:1(<module>)` | 0.1050s | 0.0150s | -0.0900s | -85.71% |
| `F:\source_code\backtrader\backtrader\utils\dateintern.py:305(date2num)` | 0.5140s | 0.4340s | -0.0800s | -15.56% |
| `{method 'readline' of '_io.TextIOWrapper' objects}` | 0.2260s | 0.1740s | -0.0520s | -23.01% |
| `{built-in method builtins.next}` | 0.1770s | 0.1370s | -0.0400s | -22.60% |
| `{built-in method builtins.divmod}` | 0.3000s | 0.2630s | -0.0370s | -12.33% |
| `{method 'popleft' of 'collections.deque' objects}` | 0.1940s | 0.1720s | -0.0220s | -11.34% |
| `{built-in method fromordinal}` | 0.1470s | 0.1310s | -0.0160s | -10.88% |
| `D:\anaconda3\Lib\site-packages\scipy\_lib\_docscrape.py:77(read_to_next_empty_li` | 0.0310s | 0.0270s | -0.0040s | -12.90% |

## Backtrader-Specific Functions Analysis

- Backtrader functions degraded: **39**
- Backtrader functions improved: **6**

### Top 10 Degraded Backtrader Functions

| Function | Cumtime Diff | % Change |
|----------|--------------|----------|
| `F:\source_code\backtrader\backtrader\indicators\__init__.py:1(<module>)` | +1.7860s | +622.30% |
| `F:\source_code\backtrader\backtrader\indicators\ols.py:1(<module>)` | +1.4640s | +146400.00% |
| `F:\source_code\backtrader\backtrader\indicators\hurst.py:1(<module>)` | +0.2170s | +0.00% |
| `F:\source_code\backtrader\backtrader\indicators\basicops.py:1(<module>)` | +0.0980s | +1960.00% |
| `F:\source_code\backtrader\backtrader\indicators\sma.py:1(<module>)` | +0.0910s | +9100.00% |
| `F:\source_code\backtrader\backtrader\indicators\rsi.py:1(<module>)` | +0.0240s | +1200.00% |
| `F:\source_code\backtrader\backtrader\indicators\oscillator.py:1(<module>)` | +0.0170s | +121.43% |
| `F:\source_code\backtrader\backtrader\indicators\stochastic.py:1(<module>)` | +0.0120s | +600.00% |
| `F:\source_code\backtrader\backtrader\indicators\directionalmove.py:1(<module>)` | +0.0120s | +400.00% |
| `F:\source_code\backtrader\backtrader\indicators\envelope.py:1(<module>)` | +0.0120s | +120.00% |

## Recommendations

### ⚠️ Performance Regression Detected

The second branch (remove-metaprogramming) is **29.67% slower** than the first branch (master).

**Actions to take:**

1. Review the top degraded functions listed above
2. Analyze why these functions became slower
3. Consider reverting changes or implementing optimizations
4. Profile individual functions for deeper analysis

### Key Areas to Investigate

**strategy.py** (+0.0050s)
  - <module>: +0.0050s


---

*Report generated by compare_performance.py*
