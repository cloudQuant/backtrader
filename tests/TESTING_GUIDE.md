# Backtrader 测试指南

> 基于 TEA 测试审查报告的改进实施指南

## 概述

本指南描述了基于 TEA 测试质量审查报告实施的测试改进。这些改进旨在提高测试套件的可维护性、可追溯性和执行效率。

## 改进内容

### 1. 测试 ID (Test IDs)

- *目的**: 为每个测试提供唯一标识符，便于需求追溯和覆盖率报告。

- *格式**: `{EPIC}.{STORY}-{LEVEL}-{SEQ}`

| 组件 | 说明 | 示例 |

|------|------|------|

| EPIC | 主要功能区域 (1=Cerebro, 2=Strategy, 3=Indicator, 4=Broker) | 1 |

| STORY | Epic 内的用户故事 | 1 |

| LEVEL | 测试层级 (UT=单元, IT=集成, E2E=端到端) | UT |

| SEQ | 序列号 (001, 002, ...) | 001 |

- *示例**:

```python
def test_1_1_UT_001_cerebro_basic_execution():
    """Test 1.1-UT-001: Verify Cerebro can execute a basic backtest."""
    pass

```bash

### 2. 优先级标记 (Priority Markers)

- *目的**: 支持选择性测试执行，优化 CI/CD 流程。

| 优先级 | 说明 | 标记 | 使用场景 |

|--------|------|------|----------|

| P0 | 关键 - 核心功能 | `@pytest.mark.priority_p0` | 烟雾测试、预提交验证 |

| P1 | 高 - 经常使用的功能 | `@pytest.mark.priority_p1` | 常规回归测试 |

| P2 | 中 - 次要功能 | `@pytest.mark.priority_p2` | 完整回归测试 |

| P3 | 低 - 很少使用 | `@pytest.mark.priority_p3` | 全面测试 |

- *示例**:

```python
import pytest

@pytest.mark.priority_p0
def test_critical_function():
    """关键功能测试 - 包含在烟雾测试中"""
    pass

@pytest.mark.priority_p2
def test_secondary_feature():
    """次要功能测试 - 仅在完整回归中运行"""
    pass

```bash

- *按优先级运行**:

```bash

# 仅运行 P0 测试 (烟雾测试)

pytest tests/ -v -m priority_p0

# 运行 P0 和 P1 测试 (预提交验证)

pytest tests/ -v -m "priority_p0 or priority_p1"

# 运行所有测试

pytest tests/ -v

```bash

### 3. Pytest Fixtures

- *目的**: 减少代码重复，自动清理，提高测试隔离性。

- *内置 Fixtures**:

| Fixture | 描述 | 返回值 |

|---------|------|--------|

| `sample_data` | 标准日线数据源 | bt.feeds.BacktraderCSVData |

| `sample_data_multi` | 多个数据源 | list |

| `week_data` | 周线数据源 | bt.feeds.BacktraderCSVData |

| `cerebro_engine` | 基本 Cerebro 实例 | bt.Cerebro |

| `cerebro_with_cash` | 带初始资金的 Cerebro | bt.Cerebro |

| `cerebro_with_data` | 已加载数据的 Cerebro | bt.Cerebro |

| `simple_strategy` | 简单 SMA 策略类 | type |

| `crossover_strategy` | 交叉策略类 | type |

| `temp_dir` | 临时目录 | str |

| `clean_env` | 自动清理 (autouse) | None |

- *示例**:

```python
def test_with_fixtures(sample_data, cerebro_engine):
    """使用 fixtures 的测试示例"""

# 无需手动设置 - fixtures 自动提供
    cerebro_engine.adddata(sample_data)
    results = cerebro_engine.run()
    assert len(results) > 0

```bash

### 4. 数据工厂模式 (Data Factory Pattern)

- *目的**: 中心化测试配置，支持并行执行。

- *工厂函数**:

| 函数 | 描述 |

|------|------|

| `create_data_feed()` | 创建数据源 |

| `create_cerebro()` | 创建 Cerebro 实例 |

| `create_simple_sma_strategy()` | 创建简单 SMA 策略 |

| `create_crossover_strategy()` | 创建交叉策略 |

| `create_sma_indicator()` | 创建 SMA 指标 |

| `create_ema_indicator()` | 创建 EMA 指标 |

| `create_macd_indicator()` | 创建 MACD 指标 |

| `create_sharpe_analyzer()` | 创建夏普比率分析器 |

| `setup_basic_backtest()` | 完整回测设置 |

- *示例**:

```python
from tests.test_utils.factories import (
    create_data_feed,
    create_cerebro,
    create_crossover_strategy,
)

def test_with_factories():
    """使用工厂函数的测试示例"""
    data = create_data_feed()  # 使用默认参数
    cerebro = create_cerebro(cash=10000.0)
    cerebro.adddata(data)

# ... 测试逻辑

```bash

### 5. 清理钩子 (Cleanup Hooks)

- *目的**: 确保测试隔离，防止状态泄漏。

- *自动清理**:

```python
@pytest.fixture(autouse=True)
def clean_test_environment():
    """每个测试后自动运行"""
    yield

# 清理逻辑

```bash

## 迁移指南

### 从旧模式迁移

- *旧代码**:

```python
def test_feed(main=False):
    """Test data feed loading."""
    cerebro = bt.Cerebro()
    modpath = os.path.dirname(os.path.abspath(__file__))
    datapath = os.path.join(modpath, "../datas/2006-day-001.txt")
    data = bt.feeds.BacktraderCSVData(
        dataname=datapath,
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )
    cerebro.adddata(data)
    cerebro.addstrategy(SimpleStrategy)
    results = cerebro.run()
    assert len(results) > 0

```bash

- *新代码**:

```python
@pytest.mark.priority_p0
def test_1_1_UT_001_feed_loading(sample_data, cerebro_engine, simple_strategy):
    """Test 1.1-UT-001: Verify data feed loads correctly.

    Priority: P0 - Critical
    """

# Fixtures 自动提供设置
    cerebro_engine.adddata(sample_data)
    cerebro_engine.addstrategy(simple_strategy)
    results = cerebro_engine.run()
    assert len(results) > 0

```bash

### 迁移步骤

1. **添加测试 ID**: 重命名函数包含 ID
2. **添加优先级标记**: 根据重要性添加 `@pytest.mark.priority_pN`
3. **使用 fixtures**: 替换手动设置为 fixtures
4. **使用工厂函数**: 替换重复的创建代码为工厂调用
5. **移除 `main` 参数**: 改用 pytest 运行

## 目录结构

```bash
tests/
├── conftest.py                 # pytest 配置和 fixtures

├── pytest.ini                  # pytest 配置文件

├── test_utils/
│   ├── __init__.py
│   └── factories.py            # 数据工厂函数

├── examples/
│   └── test_improved_examples.py  # 改进后的示例测试

├── add_tests/                  # 新增测试 (原有)

├── original_tests/             # 原版测试 (原有)

└── datas/                      # 测试数据

```bash

## 运行测试

```bash

# 运行所有测试

pytest tests/ -v

# 运行特定优先级的测试

pytest tests/ -v -m priority_p0

# 运行特定文件

pytest tests/examples/test_improved_examples.py -v

# 运行特定测试

pytest tests/examples/test_improved_examples.py::test_1_1_UT_001_cerebro_basic_execution -v

# 生成覆盖率报告

pytest tests/ --cov=backtrader --cov-report=html

# 并行运行 (需要 pytest-xdist)

pytest tests/ -n 4 -v

```bash

## 编写新测试的清单

- [ ] 添加测试 ID (格式: `test_EPIC_STORY_LEVEL_SEQ_description`)
- [ ] 添加优先级标记 (`@pytest.mark.priority_pN`)
- [ ] 编写详细的 docstring
- [ ] 使用 fixtures 而非手动设置
- [ ] 使用工厂函数创建对象
- [ ] 确保测试独立（不依赖其他测试）
- [ ] 验证断言明确可见
- [ ] 保持测试文件在 300 行以内

## 参考资料

- **TEA 测试审查报告**: `_bmad-output/test-artifacts/test-review.md`
- **pytest 文档**: <https://docs.pytest.org/>
- **测试知识库**: `_bmad/tea/testarch/knowledge/`
