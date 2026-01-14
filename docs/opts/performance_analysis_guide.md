# Performance Analysis Guide

## Overview

This guide explains how to analyze the performance of backtrader tests and compare performance between different branches (e.g., `remove-metaprogramming` vs `master`).

## Tool: profile_performance.py

### Purpose

The `profile_performance.py` script is designed to:
1. Profile the execution of `test_strategy_unoptimized.py`
2. Track function call counts and execution times
3. Identify performance bottlenecks
4. Generate comprehensive reports saved to log files

### Features

The profiling script provides detailed analysis including:

- **Top functions by cumulative time**: Functions that consume the most time including sub-function calls
- **Top functions by total time**: Functions consuming time in their own execution (excluding sub-calls)
- **Top functions by call count**: Most frequently called functions
- **Backtrader-specific analysis**: Filtering for backtrader module functions
- **Strategy-specific analysis**: Focusing on strategy.py functions
- **Indicator-specific analysis**: Analyzing indicator performance
- **Line buffer operations**: Performance of line-related functions
- **Detailed call statistics**: Breakdown of function callers and callees
- **Summary statistics**: Overall execution metrics

### Usage

#### Basic Usage

Run the profiling script from the project root:

```bash
python profile_performance.py
```

The script will:
1. Execute the test with profiling enabled
2. Generate a detailed report file named: `performance_profile_<branch>_<timestamp>.log`
3. Display top 20 functions in the console

#### Example Output File

```
performance_profile_remove-metaprogramming_20251026_170210.log
```

### Report Sections

#### Section 1: Top Functions by Cumulative Time
Shows functions that take the most time including all sub-function calls. This helps identify high-level bottlenecks.

#### Section 2: Top Functions by Total Time (excluding sub-calls)
Shows functions that consume the most time in their own execution. Useful for finding inefficient implementations.

#### Section 3: Top Functions by Call Count
Identifies functions that are called most frequently. High call counts can indicate optimization opportunities.

#### Section 4: Backtrader-Specific Functions
Filters the results to show only backtrader module functions, helping focus on backtrader-specific performance issues.

#### Section 5: Strategy-Specific Functions
Focuses on `strategy.py` functions to analyze strategy execution performance.

#### Section 6: Indicator-Specific Functions
Analyzes indicator calculation performance.

#### Section 7: Line Buffer Operations
Shows performance of line buffer operations, which are critical for backtrader's data management.

#### Section 8: Detailed Call Statistics
Provides a breakdown of which functions call which other functions, helping understand the call graph.

#### Section 9: Summary Statistics
Overall statistics including:
- Total function calls
- Total primitive calls
- Total unique functions
- Total execution time
- Average time per call

## Comparing Branch Performance

### Step 1: Profile the Current Branch

```bash
# On remove-metaprogramming branch
git checkout remove-metaprogramming
python profile_performance.py
```

This generates: `performance_profile_remove-metaprogramming_<timestamp>.log`

### Step 2: Profile the Master Branch

```bash
# Switch to master branch
git checkout master
python profile_performance.py
```

This generates: `performance_profile_master_<timestamp>.log`

### Step 3: Compare the Reports

Compare key metrics between the two log files:

1. **Total Execution Time**: Found in the header of each report
2. **Top Functions**: Compare the top 20-50 functions by cumulative/total time
3. **Call Counts**: Check if certain functions are called more/less frequently
4. **Backtrader Functions**: Focus on backtrader-specific performance differences

### Key Metrics to Compare

#### 1. Overall Execution Time
```
Total Execution Time: X.XXXX seconds
```

#### 2. Hot Functions
Look for functions with:
- High cumulative time (>10% of total)
- High call counts (>10,000 calls)
- High total time per call

#### 3. Backtrader Core Functions
Focus on these modules:
- `strategy.py` - Strategy execution
- `indicator.py` - Indicator calculations
- `linebuffer.py` - Data buffer operations
- `lineseries.py` - Line series operations
- `lineiterator.py` - Iteration logic

## Performance Analysis Workflow

### 1. Identify Bottlenecks

Run the profiling script and examine Section 1 (Top Functions by Cumulative Time):

```python
# Example bottleneck indicators:
# - Function taking >20% of total time
# - Functions called >100,000 times
# - Functions with high time/call ratio
```

### 2. Analyze Root Causes

Look at Section 8 (Detailed Call Statistics) to understand:
- Which functions call the bottleneck function
- How deep the call stack is
- Are there redundant calls?

### 3. Compare Implementations

For branch comparison:
1. Find the same function in both reports
2. Compare: call count, total time, cumulative time
3. Determine if changes improved or degraded performance

### 4. Document Findings

Create a summary with:
- Overall performance change (% faster/slower)
- Top 5 improved functions
- Top 5 degraded functions
- Root cause analysis
- Recommendations

## Example Analysis Template

```markdown
## Performance Comparison: remove-metaprogramming vs master

### Overall Results
- Master branch: 15.23 seconds
- Remove-metaprogramming branch: 16.75 seconds
- **Difference: +10% slower**

### Top Bottlenecks

#### remove-metaprogramming branch
1. `__len__` (lineseries.py): 489,132 calls, 0.163s total
2. `_getminperstatus` (lineiterator.py): 11,220 calls, 0.009s total
3. `__getitem__` (linebuffer.py): 456,584 calls, 0.051s total

#### master branch
1. Function1: X calls, Y seconds
2. Function2: X calls, Y seconds
3. Function3: X calls, Y seconds

### Key Differences

1. **Function X**
   - Master: N calls, T seconds
   - Remove-metaprogramming: N calls, T seconds
   - Analysis: ...

2. **Function Y**
   - Master: N calls, T seconds
   - Remove-metaprogramming: N calls, T seconds
   - Analysis: ...

### Recommendations

1. Optimize Function X by...
2. Reduce calls to Function Y by...
3. Consider alternative approach for...
```

## Advanced Usage

### Custom Test Files

To profile a different test file, modify the `test_path` variable in `profile_performance.py`:

```python
test_path = r'tests\original_tests\test_strategy_optimized.py'
```

### Filter by Function Name

Use grep/findstr to filter the report:

```bash
# Windows (PowerShell)
Get-Content performance_profile_*.log | Select-String "strategy.py"

# Linux/Mac
grep "strategy.py" performance_profile_*.log
```

### Extract Specific Sections

```bash
# Extract Section 1 only
Get-Content performance_profile_*.log | Select-String -Pattern "SECTION 1" -Context 0,100
```

## Troubleshooting

### Issue: Script fails to import test module

**Solution**: Ensure you're running from the project root directory:
```bash
cd F:\source_code\backtrader
python profile_performance.py
```

### Issue: No log file generated

**Solution**: Check console output for errors. Ensure write permissions in the project directory.

### Issue: Different execution times on each run

**Solution**: This is normal. Run the profiling 3-5 times and average the results for more accurate comparison.

## Best Practices

1. **Multiple Runs**: Profile each branch 3-5 times and average results
2. **Clean Environment**: Close other applications to minimize interference
3. **Same Machine**: Always compare on the same hardware
4. **Document Everything**: Keep logs and notes for future reference
5. **Focus on Significant Changes**: Look for >5% differences in key metrics
6. **Verify Changes**: Re-run after making optimizations to confirm improvements

## References

- Python cProfile documentation: https://docs.python.org/3/library/profile.html
- pstats documentation: https://docs.python.org/3/library/profile.html#the-stats-class
- Backtrader documentation: https://www.backtrader.com/


