# Bug: runonce=True 模式下自定义 Indicator 子指标 line 指针冻结

## 概述

在 `runonce=True`（默认）模式下，当自定义 Indicator 在 `__init__` 中创建子指标，并在 `next()` 中通过 `self.sub_indicator[0]` 访问子指标值时，某些子指标的 `[0]` 索引始终返回一个固定的冻结值，而不是当前 bar 的实际值。

## 严重程度

**高** — 导致 `runonce=True` 和 `runonce=False` 两种模式产生不同的回测结果，且用户无法察觉。

## 复现代码

```python
import backtrader as bt

class MyCustomIndicator(bt.Indicator):
    lines = ('wave', 'raw',)
    
    def __init__(self):
        self.cci = bt.indicators.CCI(self.data, period=14)  # minperiod=27
        self.rsi = bt.indicators.RSI(self.data.close, period=14)  # minperiod=15
        self.addminperiod(40)  # 大于 CCI 的 minperiod

    def next(self):
        cci_val = float(self.cci[0])  # BUG: 始终返回冻结值 -26.45
        rsi_val = float(self.rsi[0])  # 也受影响但差异较小
        # ... 使用 cci_val 和 rsi_val 计算 ...
```

## 观察到的行为

```
runonce=True:  buy=251, sell=251, trades=501, final=1013048.00
runonce=False: buy=241, sell=241, trades=481, final=1010872.40
```

两种模式结果不同。调试发现 CCI 的 line 指针被冻结：

```
BWI call=1 cci[0]=-26.4543 cci_idx=6102 (buffer末尾)
BWI call=2 cci[0]=-26.4543 cci_idx=6102
BWI call=3 cci[0]=-26.4543 cci_idx=6102
```

## 期望行为

`runonce=True` 和 `runonce=False` 应产生完全相同的结果。`self.cci[0]` 应返回当前 bar 对应的 CCI 值。

## 根本原因分析

### 执行流程（runonce=True 模式）

```
Strategy._once()
  └── BinaryWaveIndicator._once()
        ├── CCI._once(0, 6129)          ← 步骤1: CCI 批量计算所有值, idx 推到 6102
        ├── RSI._once(0, 6129)          ← 步骤2: RSI 批量计算, idx 推到末尾
        ├── EMA._once(0, 6129)          ← 步骤3: 其他子指标...
        ├── BinaryWaveIndicator.preonce(0, 39)
        ├── BinaryWaveIndicator.oncestart(39, 40)
        └── BinaryWaveIndicator.once(39, 6129)  ← 步骤4: 默认实现
              └── for i in range(39, 6129):
                    self.forward()
                    self.next()          ← 步骤5: self.cci[0] 访问 array[6102]
                                            CCI 的 idx 在步骤1已被推到末尾!
```

### 问题的精确位置

文件：`backtrader/lineiterator.py`

1. `_once()` 方法（约第1455行）对子指标调用 `_once()`：
```python
for lineiter_list in lineiterators.values():
    for lineiterator in lineiter_list:
        lineiterator._once(start, end)  # CCI 的 idx 被推到末尾
```

2. 默认 `once()` 方法（约第1560行）逐 bar 调用 `next()`：
```python
def once(self, start, end):
    for i in range(start, end):
        self.forward()
        self.next()  # self.cci[0] 访问的是 CCI 末尾的值
```

### 核心矛盾

- 步骤1中 CCI 的 `_once()` 被调用，CCI 的 line buffer 被填满，`idx` 推到末尾
- 步骤4中父指标的默认 `once()` 逐 bar 调用 `self.next()`
- 在 `self.next()` 中 `self.cci[0]` 使用 `array[idx + 0]` 访问值
- 但 CCI 的 `idx` 已经在步骤1被推到末尾，不会随父指标的逐 bar 循环而变化

## 修复方案

### 方案 A（推荐）：当父指标使用默认 once() 时，不对子指标调用 _once()

在 `_once()` 方法中，检测当前 indicator 是否有自定义的 `once()` 方法。如果没有（使用默认的 `once_via_next` 实现），则跳过对子指标的 `_once()` 调用。

```python
def _once(self, start=None, end=None):
    # ... 获取 start, end, minperiod ...
    
    # 检查是否有自定义 once() 方法（不是从 LineIterator 继承的默认实现）
    has_custom_once = any(
        'once' in cls.__dict__ 
        for cls in type(self).__mro__ 
        if cls is not LineIterator and cls is not object
    )
    
    if has_custom_once:
        # 有自定义 once()，子指标可以安全地被批量预计算
        for lineiter_list in self._lineiterators.values():
            for lineiterator in lineiter_list:
                lineiterator._once(start, end)
    # else: 子指标不被单独 _once()，将通过默认 once() 中的逐 bar 执行来驱动
    
    # ... 调用 preonce, oncestart, once ...
```

同时修改默认 `once()` 实现，在逐 bar 循环中驱动子指标：

```python
def once(self, start, end):
    for i in range(start, end):
        self.forward()
        # 驱动子指标的 _next()
        try:
            for indicator in self._lineiterators[LineIterator.IndType]:
                indicator._next()
        except (AttributeError, KeyError):
            pass
        self.next()
```

### 方案 B：修改默认 once() 为完全模拟 _next() 行为

将默认 `once()` 改为调用 `self._next()` 而不是 `self.next()`，因为 `_next()` 会先驱动子指标：

```python
def once(self, start, end):
    for i in range(start, end):
        self._next()  # _next() 会先调用子指标的 _next()，然后调用 self.next()
```

注意：这需要确保 `_next()` 中的 `_clk_update()` 在 `once()` 模式下正确工作（`forward()` 已经在 `_clk_update` 中被调用）。

### 方案 C：在 _once() 中对子指标的 _once() 调用后重置其 line 指针

在子指标的 `_once()` 调用完成后，立即 `home()` 它们，然后在默认 `once()` 的逐 bar 循环中手动 advance：

```python
# 在 _once() 中，子指标 _once() 完成后：
for lineiter_list in self._lineiterators.values():
    for lineiterator in lineiter_list:
        lineiterator._once(start, end)
        # 重置 line 指针，但保留 buffer 中的计算结果
        lineiterator.lines.home()
```

然后在默认 `once()` 中：
```python
def once(self, start, end):
    for i in range(start, end):
        self.forward()
        # advance 子指标的 line 指针（不重新计算，只移动指针）
        for lineiter_list in self._lineiterators.values():
            for lineiterator in lineiter_list:
                lineiterator.lines.advance()
        self.next()
```

## 验证测试

```python
def test_runonce_subindicator_consistency():
    """runonce=True 和 runonce=False 应产生相同结果"""
    import backtrader as bt
    
    class TestIndicator(bt.Indicator):
        lines = ('output',)
        def __init__(self):
            self.cci = bt.indicators.CCI(self.data, period=14)
            self.addminperiod(40)
        def next(self):
            self.lines.output[0] = float(self.cci[0])
    
    class TestStrategy(bt.Strategy):
        def __init__(self):
            self.ind = TestIndicator(self.data)
            self.values_runonce = []
            self.values_no_runonce = []
        def next(self):
            self.collected.append(float(self.ind.output[0]))
    
    for runonce in [True, False]:
        cerebro = bt.Cerebro(runonce=runonce)
        # 添加数据...
        cerebro.addstrategy(TestStrategy)
        results = cerebro.run()
        strat = results[0]
        values = strat.collected
    
    # 两种模式的 output 值应完全相同
    assert values_runonce == values_no_runonce
```

## 影响范围

- **受影响**：所有在 `__init__` 中创建子指标并在 `next()` 中通过 `self.xxx[0]` 访问的自定义 Indicator（没有自定义 `once()` 方法的）
- **不受影响**：
  - 标准内置指标（它们有自定义 `once()` 实现）
  - 在 Strategy 的 `__init__` 中直接创建的指标
  - 使用 `runonce=False` 模式的代码

## 相关文件

- `backtrader/lineiterator.py` — `_once()` 方法、默认 `once()` 方法、`_next()` 方法
- `backtrader/lineseries.py` — `home()` 方法
- `backtrader/linebuffer.py` — `home()` 方法、`forward()` 方法、`idx` 属性

## 发现背景

在将 `back_trader/strategies/multi_indicator_system/0029_binary_wave` 策略从 Python 转换为 C++ 时发现。C++ 实现使用正确的 CCI 值（当前 bar 的实际值），但与 Python `runonce=True` 模式的结果不匹配。经过 TradeLogger 对比和逐 bar 调试，定位到 Python 的 CCI 值被冻结在 line buffer 末尾位置。
