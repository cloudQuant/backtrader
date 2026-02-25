# 测试迁移计划 - 渐进式迁移

> 迁移策略: 新测试使用新模式 + 选择性迁移现有测试

## 迁移优先级

### 阶段 1: 新测试 (立即执行) ✅

**规则**: 所有新编写的测试必须使用新模式

**检查清单**:
- [ ] 包含测试 ID (格式: `test_EPIC_STORY_LEVEL_SEQ_description`)
- [ ] 包含优先级标记 (`@pytest.mark.priority_pN`)
- [ ] 使用 fixtures 而非手动设置
- [ ] 使用工厂函数创建对象

### 阶段 2: 高频测试 (推荐优先迁移)

以下测试文件因为经常被修改/调试，建议优先迁移：

| 文件 | 优先级 | 预计时间 |
|------|--------|----------|
| `test_strategy.py` | 高 | 30分钟 |
| `test_cerebro.py` | 高 | 30分钟 |
| `test_broker.py` | 高 | 15分钟 |
| `test_indicator_base.py` | 中 | 20分钟 |
| `test_feed.py` | 中 | 15分钟 |

### 阶段 3: 核心模块测试 (按需迁移)

核心模块测试，在需要修改时顺便迁移：

- `tests/add_tests/test_analyzer_*.py` - 分析器测试
- `tests/add_tests/test_observer_*.py` - 观察器测试
- `tests/add_tests/test_sizer_*.py` - 仓位管理测试

### 阶段 4: 其他测试 (保持现状)

运行良好、低频修改的测试可以保持现状：
- `tests/original_tests/` - 原版测试
- `tests/add_tests/test_ind_*.py` - 大量指标测试

## 迁移示例

### 迁移前 (test_strategy.py)

```python
def test_strategy_basic(main=False):
    """Test basic strategy functionality with a single data feed."""
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

    results = cerebro.run()

    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0

    final_value = cerebro.broker.getvalue()
    assert final_value > 0
```

### 迁移后

```python
@pytest.mark.priority_p0
def test_2_1_IT_001_strategy_basic_execution(cerebro_with_data, simple_strategy):
    """Test 2.1-IT-001: Verify basic strategy executes correctly.

    Priority: P0 - Critical (core strategy execution)
    Epic: 2 (Strategy), Story: 1 (Basic Execution), Level: IT, Seq: 001

    Args:
        cerebro_with_data: Cerebro with data pre-loaded (fixture)
        simple_strategy: Simple SMA strategy class (fixture)
    """
    # Arrange - Fixtures provide setup
    cerebro_with_data.addstrategy(simple_strategy)

    # Act
    results = cerebro_with_data.run()

    # Assert
    assert len(results) > 0
    strat = results[0]
    assert len(strat) > 0
    assert cerebro_with_data.broker.getvalue() > 0
```

### 使用工厂函数的替代方案

```python
@pytest.mark.priority_p0
def test_2_1_IT_002_strategy_with_factory():
    """Test 2.1-IT-002: Verify strategy with factory pattern."""
    # Arrange - Use factory for complete setup
    cerebro = setup_basic_backtest(
        cash=10000.0,
        strategy=create_simple_sma_strategy(period=15),
        data_feeds=[create_data_feed()],
    )

    # Act
    results = cerebro.run()

    # Assert - Use validation helper
    summary = validate_backtest_results(results, min_bars=1)
    assert summary["bars_processed"] > 0
```

## 迁移模板

### 基本模板

```python
import pytest
from tests.test_utils.factories import create_data_feed, create_cerebro

@pytest.mark.priority_p0  # 或 P1, P2, P3
def test_EPIC_STORY_LEVEL_SEQ_description(fixture1, fixture2):
    """Test EPIC.STORY-LEVEL-SEQ: Brief description.

    Priority: P0 - Critical / P1 - High / P2 - Medium / P3 - Low
    Epic: X (模块名)
    Story: Y (功能)
    Level: UT / IT / E2E
    Seq: ZZZ

    Args:
        fixture1: Description
        fixture2: Description
    """
    # Arrange - 使用 fixtures/工厂设置

    # Act - 执行被测试的功能

    # Assert - 验证结果
```

## 迁移检查清单

每个迁移的测试应该：

- [ ] 添加测试 ID 到函数名
- [ ] 添加优先级标记
- [ ] 移除 `main` 参数（改用 pytest 运行）
- [ ] 使用 fixtures 替代手动设置
- [ ] 使用工厂函数创建对象
- [ ] 更新 docstring 包含测试 ID 信息
- [ ] 验证测试仍然通过

## 迁移脚本（可选）

如需批量迁移，可以创建辅助脚本：

```python
# scripts/migrate_test.py
import re
from pathlib import Path

def add_priority_marker(content):
    """Add P2 marker to tests without priority."""
    # 在每个 def test_ 前添加 @pytest.mark.priority_p2
    # 仅用于没有标记的测试
    pass

def remove_main_param(content):
    """Remove main=False parameter from test functions."""
    # 移除 main 参数和相关代码
    pass

def migrate_file(filepath):
    """Migrate a single test file."""
    content = filepath.read_text()
    content = add_priority_marker(content)
    content = remove_main_param(content)
    filepath.write_text(content)
```

## 执行计划

1. **本周**: 新测试使用新模式 ✅
2. **下周**: 迁移高频测试 (test_strategy.py, test_cerebro.py)
3. **按需**: 其他测试在修改时顺便迁移

## 成功指标

- [ ] 所有新测试使用新模式
- [ ] 高频测试完成迁移
- [ ] 测试通过率保持 100%
- [ ] 测试执行时间没有显著增加
