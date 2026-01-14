# 迭代37 - 修复 test_120 Data Replay MACD 交叉问题

## 问题描述

测试用例 `test_120_data_replay_macd.py` 在 origin 分支失败，该测试使用 MACD 指标配合 CrossOver 指标，在 replay 模式（日线数据回放为周线）下进行交易。

### 症状
- **期望值**: `final_value=106870.40`, `buy_count=9`, `sell_count=8`
- **实际值**: `final_value=107568.30`, `buy_count=10`, `sell_count=9`

通过对比日志发现，问题出在第 3 个 bar 时出现了错误的交叉信号：
- master 分支: bar_num=3, crossover=0.0
- origin 分支: bar_num=3, crossover=1.0 (错误的向上交叉)

这导致 origin 分支在第 3 个 bar 就买入了（2005-09-01），而 master 分支直到第 61 个 bar 才买入（2005-11-21）。

## 根因分析

### 问题定位过程

1. **首先排查 MACD 指标**: 对比两边的 MACD 和 signal 值，完全一致，说明 MACD 计算正确
2. **定位 CrossOver 指标**: 问题出在 CrossOver 如何判断"前一个状态"
3. **分析执行模式**: 测试使用 `preload=False`，导致指标使用 `next()` 模式而非 `once()` 模式

### 核心问题: nextstart() 在 replay 模式下的行为

在 replay 模式下：
- 日线数据被压缩为周线
- minperiod 完成后的第一个周线 bar 之前，没有"有效的压缩时间段"数据
- `nextstart()` 仍然会计算交叉信号，但此时没有有效的"前一个 bar"可以比较

**错误代码** (`backtrader/indicators/crossover.py`):
```python
def nextstart(self):
    # First bar after minperiod: check for cross using _last_nzd from prenext
    diff = self.data0[0] - self.data1[0]

    # Get previous non-zero difference (set during prenext)
    prev_nzd = self._last_nzd if self._last_nzd is not None else diff

    # Check for crossover
    up_cross = 1.0 if (prev_nzd < 0.0 and self.data0[0] > self.data1[0]) else 0.0
    down_cross = 1.0 if (prev_nzd > 0.0 and self.data0[0] < self.data1[0]) else 0.0
    self.lines.crossover[0] = up_cross - down_cross  # ← 这里会产生错误信号
```

### 为什么会出错？

在 test_120 的场景中：
- bar_num=1 (index 34): MACD=73.37 < signal=74.08, prev_nzd 来源于 prenext 期间的值
- bar_num=2 (index 35): MACD=72.90 < signal=73.98
- bar_num=3 (index 36): MACD=75.27 > signal=74.46

`nextstart()` 中的 `prev_nzd` 来自 `prenext()` 期间设置的值，这个值代表的是压缩之前的数据状态，而不是压缩后周线的"前一个 bar"。因此，基于这个值计算的交叉信号是错误的。

## 修复方案

### 修复 nextstart() 方法

**位置**: `backtrader/indicators/crossover.py:108-120`

```python
def nextstart(self):
    # CRITICAL FIX: In replay mode, the first bar after minperiod doesn't have a valid
    # "previous" bar in the compressed timeframe context. Skip crossover calculation
    # on the first bar and defer to the second bar. This prevents false positive
    # crossovers at the start of replay data.
    diff = self.data0[0] - self.data1[0]

    # Don't calculate crossover on first bar - set to 0 and update _last_nzd
    self.lines.crossover[0] = 0.0

    # Update _last_nzd for next()
    prev_nzd = self._last_nzd if self._last_nzd is not None else diff
    self._last_nzd = diff if diff != 0.0 else prev_nzd
```

### 同时修复 once() 方法

为了确保在 runonce 模式下也能正确处理，添加相同的逻辑：

**位置**: `backtrader/indicators/crossover.py:176-224`

```python
def once(self, start, end):
    # ... (前面代码保持不变)

    # CRITICAL FIX: For replay mode, skip crossover on the very first bar.
    # The first bar after minperiod doesn't have a valid "previous" bar in the
    # compressed timeframe context. Defer crossover to the second bar.
    # This prevents false positive crossovers at the start of replay data.
    first_bar = start

    # Process ALL bars from start
    for i in range(start, end):
        d0_val = d0array[i]
        d1_val = d1array[i]
        diff = d0_val - d1_val

        # Skip crossover calculation on first bar - defer to second bar
        if i == first_bar:
            crossarray[i] = 0.0
            # Still update prev_nzd for next iteration
            prev_nzd = diff if diff != 0.0 else prev_nzd
            continue

        # Check crossover using prev_nzd (from previous bar)
        up_cross = 1.0 if (prev_nzd < 0.0 and d0_val > d1_val) else 0.0
        down_cross = 1.0 if (prev_nzd > 0.0 and d0_val < d1_val) else 0.0
        crossarray[i] = up_cross - down_cross

        # Update prev_nzd for next iteration (memorize non-zero)
        prev_nzd = diff if diff != 0.0 else prev_nzd
```

## 修复原理

### Replay 模式下的"第一个 bar"问题

在 replay 模式下：
1. 原始数据（如日线）被压缩为更大时间框架（如周线）
2. minperiod 是基于压缩后的周线计算的
3. minperiod 完成后的第一个周线 bar，其"前一个状态"实际上来自压缩前的日线数据
4. 基于压缩前数据计算的交叉信号是错误的

### 解决方案

**跳过第一个 bar 的交叉计算**:
- 第一个 bar 设置 `crossover = 0.0`
- 从第二个 bar 开始正常计算交叉
- 这样确保交叉判断基于的都是同一个压缩时间框架内的数据

## 测试验证

修复后运行测试：
```bash
python -m pytest tests/strategies/test_120_data_replay_macd.py -v
```

结果：
- `bar_num`: 344 ✓
- `buy_count`: 9 ✓
- `sell_count`: 8 ✓
- `final_value`: 106870.40 ✓
- `sharpe_ratio`: 1.3228391876325063 ✓
- `annual_return`: 0.033781408229031695 ✓
- `max_drawdown`: 1.6636055151304665 ✓
- `total_trades`: 9 ✓
- 测试通过 ✓

## 经验教训

1. **Replay 模式下时间框架的转换**: 当数据被 replay 压缩时，压缩前的数据和压缩后的数据属于不同的时间框架，不能直接比较
2. **nextstart() 的特殊性**: nextstart() 只在 minperiod 完成后的第一个 bar 调用一次，在 replay 模式下需要特别处理
3. **调试技巧**: 通过对比 master 和 origin 分支的日志，特别关注第一个出现差异的 bar，可以快速定位问题
4. **两种执行模式都需要修复**: `next()/nextstart()` 和 `once()` 分别对应不同的执行模式，都需要处理 replay 模式的问题

## 相关文件

- `/backtrader/indicators/crossover.py` - CrossOver 指标修复
- `/tests/strategies/test_120_data_replay_macd.py` - 测试用例

## 相关文档

- 迭代36 - Data Replay 修复经验总结
