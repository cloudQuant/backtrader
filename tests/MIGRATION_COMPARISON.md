# 测试迁移对比示例

> 文件: test_strategy.py → test_strategy_v2.py

## 迁移对比

### 1. 测试函数命名

**迁移前**:
```python
def test_strategy_basic(main=False):
    """Test basic strategy functionality with a single data feed."""
```

**迁移后**:
```python
@pytest.mark.priority_p0
def test_2_1_IT_001_strategy_basic_execution(cerebro_with_data):
    """Test 2.1-IT-001: Verify basic strategy functionality.

    Priority: P0 - Critical (core strategy execution)
    Epic: 2 (Strategy), Story: 1 (Basic Execution), Level: IT, Seq: 001
    """
```

**变化**:
- ✅ 添加了测试 ID: `2_1_IT_001`
- ✅ 添加了优先级标记: `@pytest.mark.priority_p0`
- ✅ 移除了 `main` 参数
- ✅ 使用 fixture: `cerebro_with_data`
- ✅ 更新了 docstring 包含测试信息

---

### 2. 数据设置

**迁移前**:
```python
def test_strategy_basic(main=False):
    cerebro = bt.Cerebro()

    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")

    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(SampleStrategy1, printlog=main)
    cerebro.broker.setcash(10000.0)
```

**迁移后**:
```python
@pytest.mark.priority_p0
def test_2_1_IT_001_strategy_basic_execution(cerebro_with_data):
    """Test 2.1-IT-001: Verify basic strategy functionality."""
    # Fixture 已提供数据和 Cerebro 设置
    cerebro_with_data.addstrategy(SampleStrategy1)
    cerebro_with_data.broker.setcash(10000.0)
```

**变化**:
- ✅ 减少了 15 行设置代码
- ✅ 使用 `cerebro_with_data` fixture
- ✅ 移除了路径拼接逻辑
- ✅ 移除了 `main` 参数处理

---

### 3. 断言部分

**迁移前**:
```python
    results = cerebro.run()

    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0  # Processed bars

    final_value = cerebro.broker.getvalue()
    if main:
        pass  # Removed for performance
    assert final_value > 0  # Verify broker value is valid
```

**迁移后**:
```python
    # Act
    results = cerebro_with_data.run()

    # Assert - Verify strategy ran successfully
    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0  # Processed bars

    final_value = cerebro_with_data.broker.getvalue()
    assert final_value > 0  # Verify broker value is valid
```

**变化**:
- ✅ 添加了注释分隔 Arrange/Act/Assert
- ✅ 移除了 `main` 条件判断

---

## 代码量对比

| 指标 | 迁移前 | 迁移后 | 变化 |
|------|--------|--------|------|
| 函数签名行数 | 2 | 3 | +1 (文档) |
| 设置代码行数 | ~15 | ~3 | -12 (-80%) |
| 断言代码行数 | ~8 | ~7 | -1 |
| **总行数** | **~25** | **~13** | **-48%** |

## 运行方式对比

### 迁移前

```bash
# 直接运行 (Python)
python tests/add_tests/test_strategy.py

# 使用 pytest
pytest tests/add_tests/test_strategy.py -v
```

### 迁移后

```bash
# 使用 pytest (推荐)
pytest tests/add_tests/test_strategy_v2.py -v

# 仅运行 P0 测试
pytest tests/add_tests/test_strategy_v2.py -v -m priority_p0

# 直接运行 (仍然支持)
python tests/add_tests/test_strategy_v2.py
```

## 功能对比

| 功能 | 迁移前 | 迁移后 |
|------|--------|--------|
| 基本测试 | ✅ | ✅ |
| 多数据源 | ✅ | ✅ |
| 参数优化 | ✅ | ✅ |
| 测试 ID | ❌ | ✅ |
| 优先级标记 | ❌ | ✅ |
| Fixtures 支持 | ❌ | ✅ |
| 工厂函数 | ❌ | ✅ |
| 选择性执行 | ❌ | ✅ |
| 代码复用 | 低 | 高 |

## 迁移收益

1. **代码减少**: 每个测试函数减少约 50% 代码
2. **可维护性**: 设置逻辑集中在 fixtures/工厂
3. **可追溯性**: 测试 ID 映射到需求
4. **执行效率**: 可按优先级选择性运行
5. **一致性**: 所有测试使用相同模式

## 迁移清单

完成迁移后，检查以下项目：

- [ ] 所有测试有测试 ID
- [ ] 所有测试有优先级标记
- [ ] 移除所有 `main` 参数
- [ ] 使用 fixtures 替代手动设置
- [ ] 使用工厂函数创建对象
- [ ] 测试仍然通过
- [ ] 添加 Arrange/Act/Assert 注释
- [ ] 更新 docstring 包含测试 ID 信息
