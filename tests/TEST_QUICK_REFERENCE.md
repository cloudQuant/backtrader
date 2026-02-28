# 测试快速参考

## 运行测试

```bash

# 快速烟雾测试 (P0 only - ~30 秒)

pytest tests/ -v -m priority_p0

# 预提交验证 (P0 + P1 - ~1 分钟)

pytest tests/ -v -m "priority_p0 or priority_p1"

# 完整回归 (所有测试)

pytest tests/ -v

# 运行特定文件

pytest tests/add_tests/test_strategy.py -v

# 运行特定测试

pytest tests/add_tests/test_strategy.py::test_strategy_basic -v

# 并行执行 (4 核)

pytest tests/ -n 4 -v

# 生成覆盖率报告

pytest tests/ --cov=backtrader --cov-report=html

```bash

## 新测试模式

### 1. 使用 Fixtures

```python
def test_example(sample_data, cerebro_engine):
    """fixtures 自动提供设置"""
    cerebro_engine.adddata(sample_data)
    results = cerebro_engine.run()
    assert len(results) > 0

```bash

### 2. 使用工厂函数

```python
from tests.test_utils.factories import create_data_feed, create_cerebro

def test_example():
    """工厂函数简化对象创建"""
    data = create_data_feed()
    cerebro = create_cerebro(cash=10000.0)
    cerebro.adddata(data)
    results = cerebro.run()
    assert len(results) > 0

```bash

### 3. 完整设置

```python
from tests.test_utils.factories import setup_basic_backtest, create_data_feed, create_crossover_strategy, create_sharpe_analyzer

def test_example():
    """一行代码完成完整设置"""
    cerebro = setup_basic_backtest(
        cash=10000.0,
        strategy=create_crossover_strategy(),
        data_feeds=[create_data_feed()],
        analyzers=[create_sharpe_analyzer()],
        commission=0.001,
    )
    results = cerebro.run()
    assert len(results) > 0

```bash

## 测试 ID 格式

```bash
test_EPIC_STORY_LEVEL_SEQ_description

EPIC:   1=Cerebro, 2=Strategy, 3=Indicator, 4=Broker
STORY:  用户故事编号
LEVEL:  UT=单元, IT=集成, E2E=端到端
SEQ:    001, 002, ...

示例: test_1_1_UT_001_cerebro_basic_execution

```bash

## 优先级标记

| 标记 | 用途 | 运行命令 |

|------|------|----------|

| `@pytest.mark.priority_p0` | 关键功能 | `-m priority_p0` |

| `@pytest.mark.priority_p1` | 高频功能 | `-m "priority_p0 or priority_p1"` |

| `@pytest.mark.priority_p2` | 次要功能 | 默认包含 |

| `@pytest.mark.priority_p3` | 低优先级 | 完整回归 |

## 可用 Fixtures

| Fixture | 提供内容 |

|---------|----------|

| `sample_data` | 2006 日线数据 |

| `sample_data_multi` | 多个数据源 |

| `cerebro_engine` | 空 Cerebro 实例 |

| `cerebro_with_cash` | 带 10000 现金的 Cerebro |

| `cerebro_with_data` | 已加载数据的 Cerebro |

| `simple_strategy` | 简单 SMA 策略类 |

| `crossover_strategy` | 交叉策略类 |

## 可用工厂函数

| 函数 | 描述 |

|------|------|

| `create_data_feed()` | 创建数据源 |

| `create_cerebro()` | 创建 Cerebro |

| `create_simple_sma_strategy()` | 创建 SMA 策略 |

| `create_crossover_strategy()` | 创建交叉策略 |

| `create_sma_indicator()` | 创建 SMA 指标 |

| `create_ema_indicator()` | 创建 EMA 指标 |

| `create_macd_indicator()` | 创建 MACD 指标 |

| `create_sharpe_analyzer()` | 创建夏普分析器 |

| `setup_basic_backtest()` | 完整回测设置 |
