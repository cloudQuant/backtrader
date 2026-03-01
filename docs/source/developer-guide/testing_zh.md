---
title: 测试指南
description: Backtrader 开发者测试实践和指南
---

# 测试指南

本指南介绍为 Backtrader 框架贡献代码时的测试实践和指南。

## 目录

- [测试框架](#测试框架)
- [测试组织](#测试组织)
- [测试分类](#测试分类)
- [测试标记](#测试标记)
- [编写测试](#编写测试)
- [夹具和辅助工具](#夹具和辅助工具)
- [覆盖率要求](#覆盖率要求)
- [运行测试](#运行测试)

## 测试框架

Backtrader 使用 **pytest** 作为测试框架。主要特性：

- **pytest**: 测试运行器和断言库
- **pytest-cov**: 覆盖率报告
- **pytest-xdist**: 并行测试执行

### 安装

```bash
pip install pytest pytest-cov pytest-xdist
```

### 配置

测试配置在 `pytest.ini` 中定义：

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*

markers =
    priority_p0: 关键测试 - 核心功能
    priority_p1: 高优先级测试 - 核心用户流程
    priority_p2: 中优先级测试 - 次要功能
    priority_p3: 低优先级测试 - 很少使用的功能
    integration: 需要实时交易所连接的集成测试
    websocket: WebSocket 专用集成测试
    trading: 在模拟交易所进行真实订单的测试

filterwarnings =
    ignore::RuntimeWarning
    ignore::DeprecationWarning
```

## 测试组织

### 目录结构

```
tests/
├── conftest.py              # 共享夹具和配置
├── datas/                   # 测试数据文件
├── original_tests/          # 核心功能测试
├── add_tests/               # 额外测试覆盖
├── strategies/              # 策略专用测试
├── base_functions/          # 基础函数测试
└── integration/             # 集成测试
```

### 测试文件命名

- 测试文件必须以 `test_` 开头：`test_indicator.py`、`test_strategy.py`
- 测试类必须以 `Test` 开头：`TestSMA`、`TestBroker`
- 测试函数必须以 `test_` 开头：`test_sma_calculation()`

## 测试分类

### 单元测试

单元测试独立测试各个组件。它们应该：

- 使用模拟数据（无外部依赖）
- 快速执行（每个测试 < 1 秒）
- 每个测试只测试一个行为

```python
def test_sma_calculation():
    """测试 SMA 指标计算正确。"""
    # 创建测试数据
    data = [1, 2, 3, 4, 5]
    period = 3

    # 预期结果
    expected = 3.0  # (3 + 4 + 5) / 3

    # 运行测试
    result = calculate_sma(data, period)

    # 断言
    assert result == expected
```

### 集成测试

集成测试验证多个组件协同工作。它们：

- 使用真实数据源或测试网络连接
- 标记为 `@pytest.mark.integration`
- 可能需要 API 密钥或外部服务

```python
import backtrader as bt
import pytest

@pytest.mark.integration
def test_ib_connection():
    """测试 Interactive Brokers 连接（需要测试网络）。"""
    cerebro = bt.Cerebro()
    store = bt.stores.IBStore(port=7497)  # 模拟交易端口
    data = store.getdata(dataname='AAPL')

    cerebro.adddata(data)
    result = cerebro.run()
    assert len(result) > 0
```

### 优先级

测试按优先级分类：

| 优先级 | 描述 | 使用场景 |
|--------|------|----------|
| `priority_p0` | 关键 - 核心功能 | 必要功能、数据加载、订单执行 |
| `priority_p1` | 高 - 经常使用 | 常见指标、标准策略 |
| `priority_p2` | 中 - 次要功能 | 较少见的指标、边界情况 |
| `priority_p3` | 低 - 很少使用 | 冷门功能、遗留代码 |

## 测试标记

### 使用标记

```python
import pytest

@pytest.mark.priority_p0
def test_data_feed_loading():
    """关键测试 - 数据源必须正确加载。"""
    pass

@pytest.mark.priority_p1
@pytest.mark.integration
def test_live_api_connection():
    """高优先级集成测试。"""
    pass

@pytest.mark.websocket
async def test_websocket_feed():
    """WebSocket 专用测试。"""
    pass
```

### 使用标记运行

```bash
# 仅运行关键测试
pytest tests/ -m "priority_p0"

# 跳过集成测试
pytest tests/ -m "not integration"

# 运行多个标记
pytest tests/ -m "priority_p0 or priority_p1"

# 跳过 WebSocket 测试
pytest tests/ -m "not websocket"
```

## 编写测试

### 测试结构

良好的测试遵循 Arrange-Act-Assert 模式：

```python
def test_indicator_calculation():
    """测试指标计算预期值。"""
    # Arrange - 设置测试数据和条件
    cerebro = bt.Cerebro()
    data = create_test_data()
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)

    # Act - 执行被测试的代码
    result = cerebro.run()

    # Assert - 验证预期结果
    assert len(result) == 1
    assert result[0].analyzers.sharpe.get_analysis()['sharperatio'] > 0
```

### 完整测试示例

以下是测试指标的完整示例：

```python
#!/usr/bin/env python
"""测试简单移动平均线指标。"""

import backtrader as bt
import pytest
import datetime

class TestStrategy(bt.Strategy):
    """用于 SMA 验证的测试策略。"""

    params = (
        ('period', 15),
    )

    def __init__(self):
        """初始化指标和测试参数。"""
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)
        self.expected_values = []
        self.actual_values = []

    def next(self):
        """记录 SMA 值以供验证。"""
        if len(self.data) > self.p.period:
            self.actual_values.append(self.sma[0])

    def stop(self):
        """验证 SMA 计算。"""
        assert len(self.actual_values) > 0, "没有计算 SMA 值"
        # 此处添加其他断言


@pytest.mark.priority_p0
def test_sma_basic_calculation():
    """测试 SMA 使用基本数据正确计算。"""
    cerebro = bt.Cerebro()

    # 创建简单测试数据
    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 1, 31),  # 一个月
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy, period=15)
    cerebro.broker.setcash(10000.0)

    results = cerebro.run()

    # 验证策略已运行
    assert len(results) == 1
    strat = results[0]

    # 验证 SMA 已计算
    assert hasattr(strat, 'sma')
    assert len(strat.sma) > 0


@pytest.mark.priority_p1
@pytest.mark.parametrize("period", [5, 10, 15, 20, 30])
def test_sma_different_periods(period):
    """测试不同周期值的 SMA。"""
    cerebro = bt.Cerebro()

    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 2, 28),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy, period=period)

    results = cerebro.run()
    assert len(results) == 1


@pytest.mark.priority_p2
def test_sma_with_multiple_data_feeds():
    """测试多数据源的 SMA。"""
    cerebro = bt.Cerebro()

    data1 = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 3, 31),
    )

    data2 = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-002.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 3, 31),
    )

    cerebro.adddata(data1)
    cerebro.adddata(data2)
    cerebro.addstrategy(TestStrategy, period=10)

    results = cerebro.run()
    assert len(results) == 1
```

### 测试策略

测试交易策略时，重点关注：

1. **订单执行**：验证订单正确下达
2. **持仓管理**：检查持仓按预期开/平仓
3. **指标使用**：确保指标正确初始化

```python
def test_strategy_buy_signal():
    """测试策略在信号时执行买入。"""
    cerebro = bt.Cerebro()

    class BuyTestStrategy(bt.Strategy):
        def __init__(self):
            self.buy_executed = False
            self.sma_fast = bt.indicators.SMA(period=5)
            self.sma_slow = bt.indicators.SMA(period=15)

        def next(self):
            if not self.buy_executed:
                if self.sma_fast[0] > self.sma_slow[0]:
                    self.buy()
                    self.buy_executed = True

    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 6, 30),
    )

    cerebro.adddata(data)
    cerebro.addstrategy(BuyTestStrategy)

    results = cerebro.run()
    strat = results[0]

    # 验证至少执行了一个买入订单
    assert strat.buy_executed
```

### 使用模拟数据测试

对于独立的单元测试，创建模拟数据：

```python
import backtrader as bt

class MockData(bt.feeds.PandasData):
    """用于测试的模拟数据源。"""
    params = (
        ('datetime', None),
        ('open', -1),
        ('high', -1),
        ('low', -1),
        ('close', -1),
        ('volume', -1),
        ('openinterest', -1),
    )

def create_mock_data():
    """创建简单的模拟数据源。"""
    import pandas as pd

    dates = pd.date_range('2023-01-01', periods=100, freq='D')
    data = pd.DataFrame({
        'datetime': dates,
        'open': 100 + range(100),
        'high': 102 + range(100),
        'low': 99 + range(100),
        'close': 101 + range(100),
        'volume': 1000,
    })

    return MockData(dataname=data)

def test_with_mock_data():
    """使用模拟数据测试指标。"""
    cerebro = bt.Cerebro()
    data = create_mock_data()
    cerebro.adddata(data)
    cerebro.addstrategy(bt.Strategy)

    result = cerebro.run()
    assert len(result) > 0
```

## 夹具和辅助工具

### 内置夹具

`conftest.py` 文件提供共享夹具：

```python
@pytest.fixture
def sample_data(datas_path):
    """为测试提供标准样本数据源。"""
    datapath = datas_path / "2006-day-001.txt"
    data = bt.feeds.BacktraderCSVData(
        dataname=str(datapath),
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )
    return data

@pytest.fixture
def cerebro_engine():
    """提供基本 Cerebro 引擎实例。"""
    cerebro = bt.Cerebro()
    yield cerebro
    # 清理
    cerebro = None

@pytest.fixture
def cerebro_with_cash(cerebro_engine):
    """提供设置了初始资金的 Cerebro。"""
    cerebro_engine.broker.setcash(10000.0)
    return cerebro_engine
```

### 使用夹具

```python
def test_with_fixture(sample_data, cerebro_engine):
    """使用 conftest.py 中的夹具进行测试。"""
    cerebro_engine.adddata(sample_data)
    cerebro_engine.addstrategy(bt.Strategy)

    result = cerebro_engine.run()
    assert len(result) > 0
```

### 创建自定义夹具

```python
# 在您的测试文件或 conftest.py 中
@pytest.fixture
def macd_indicator():
    """创建带有标准参数的 MACD 指标。"""
    class MACDStrategy(bt.Strategy):
        def __init__(self):
            self.macd = bt.indicators.MACD(period_me1=12,
                                           period_me2=26,
                                           period_signal=9)

    return MACDStrategy
```

## 覆盖率要求

### 覆盖率配置

覆盖率在 `pyproject.toml` 中配置：

```toml
[tool.coverage.run]
source = ["backtrader"]
omit = [
    "*/tests/*",
    "*/test_*",
    "setup.py",
    "*/crypto_tests/*"
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if self.debug:",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

### 运行覆盖率

```bash
# 生成覆盖率报告
pytest tests/ --cov=backtrader --cov-report=term-missing

# 生成 HTML 报告
pytest tests/ --cov=backtrader --cov-report=html

# 结合标记使用
pytest tests/ -m "not integration" --cov=backtrader
```

### 覆盖率目标

- **新代码**：目标是 90%+ 的覆盖率
- **关键路径**：100% 覆盖率（P0 测试）
- **现有代码**：保持当前覆盖率水平

## 运行测试

### 基本命令

```bash
# 运行所有测试
pytest tests/ -v

# 并行运行（4 个工作进程）
pytest tests/ -n 4 -v

# 运行特定测试文件
pytest tests/add_tests/test_sma.py -v

# 运行特定测试函数
pytest tests/add_tests/test_sma.py::test_sma_calculation -v

# 首次失败时停止
pytest tests/ -x

# 失败时显示局部变量
pytest tests/ -l

# 显示详细输出和打印语句
pytest tests/ -s
```

### 按类别运行

```bash
# 指标测试
pytest tests/add_tests/test_ind*.py tests/original_tests/test_ind*.py -v

# 策略测试
pytest tests/add_tests/test_strategy*.py tests/original_tests/test_strategy*.py -v

# 分析器测试
pytest tests/add_tests/test_analyzer*.py tests/original_tests/test_analyzer*.py -v

# 经纪人测试
pytest tests/add_tests/test_broker.py -v
```

### 使用 Make 运行

```bash
# 运行所有测试
make test

# 运行带覆盖率
make test-coverage

# 运行特定测试文件
make test-file TEST=tests/add_tests/test_sma.py
```

### 持续测试

开发时使用 pytest-watch 自动运行测试：

```bash
pip install pytest-watch
ptw tests/ -- -v
```

## 最佳实践

### 应该做的：

1. **先写测试**（尽可能采用 TDD 方法）
2. **使用描述性测试名称**：`test_sma_calculates_correctly()` 而不是 `test_1()`
3. **保持测试独立** - 测试之间无共享状态
4. **使用夹具**处理通用设置
5. **模拟外部依赖** - API 调用、文件 I/O
6. **测试边界情况** - 空数据、最小周期、边界条件
7. **添加文档字符串**说明测试内容
8. **使用标记**进行测试分类

### 不应该做的：

1. **不要硬编码路径** - 使用夹具或相对路径
2. **不要测试实现细节** - 测试行为
3. **不要编写庞大的测试** - 一个概念一个断言
4. **不要忽略测试** - 修复或标记为预期失败
5. **不要在单元测试中使用实时数据**
6. **不要提交注释掉的代码**

## 调试测试

### 使用 pdb

```python
def test_failing_case():
    """需要调试的失败测试。"""
    import pdb; pdb.set_trace()

    cerebro = bt.Cerebro()
    # ... 其余测试代码
```

### 使用 pytest 的 pdb

```bash
# 失败时进入调试器
pytest tests/ --pdb

# 出错时进入调试器（不仅仅是失败）
pytest tests/ --pdb --trace
```

### 打印测试输出

```bash
# 显示打印语句
pytest tests/ -s -v

# 捕获输出但在失败时显示
pytest tests/ --capture=no
```

## 测试数据

### 测试数据文件

测试数据位于 `tests/datas/` 目录：

```
tests/datas/
├── 2006-day-001.txt      # 2006年日线数据
├── 2006-day-002.txt      # 2006年日线数据（第二组）
├── 2006-week-001.txt     # 2006年周线数据
└── ...
```

### 创建测试数据

```python
def create_test_csv(filename, num_bars=100):
    """创建测试 CSV 数据文件。"""
    import csv
    from datetime import datetime, timedelta

    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['datetime', 'open', 'high', 'low', 'close', 'volume', 'openinterest'])

        dt = datetime(2023, 1, 1)
        for i in range(num_bars):
            base_price = 100.0 + i * 0.1
            writer.writerow([
                dt.strftime('%Y-%m-%d %H:%M:%S'),
                base_price,        # open
                base_price + 0.5,  # high
                base_price - 0.5,  # low
                base_price + 0.2,  # close
                1000,              # volume
                0                  # openinterest
            ])
            dt += timedelta(days=1)
```

## 常见测试场景

### 测试指标注册

```python
def test_indicator_registration():
    """测试指标正确注册到策略。"""
    cerebro = bt.Cerebro()

    class TestStrategy(bt.Strategy):
        def __init__(self):
            self.sma = bt.indicators.SMA(period=10)

    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
    )

    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    cerebro.run()

    # 验证策略已运行
    assert len(cerebro.runstrats[0]) > 0
```

### 测试分析器

```python
def test_sharpe_analyzer():
    """测试夏普比率分析器。"""
    cerebro = bt.Cerebro()

    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
        fromdate=datetime.datetime(2006, 1, 1),
        todate=datetime.datetime(2006, 12, 31),
    )

    cerebro.adddata(data)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

    results = cerebro.run()
    strat = results[0]

    # 验证分析器存在并返回有效值
    assert hasattr(strat.analyzers, 'sharpe')
    analysis = strat.analyzers.sharpe.get_analysis()
    assert 'sharperatio' in analysis
```

### 测试观察器

```python
def test_drawdown_observer():
    """测试回撤观察器。"""
    cerebro = bt.Cerebro()

    data = bt.feeds.BacktraderCSVData(
        dataname='tests/datas/2006-day-001.txt',
    )

    cerebro.adddata(data)
    cerebro.addobserver(bt.observers.DrawDown)

    results = cerebro.run()
    strat = results[0]

    # 验证观察器已附加
    assert len(strat.observers) > 0
```

## 另请参阅

- [开发环境设置](setup_zh.md)
- [代码风格](style_zh.md)
- [贡献指南](contributing_zh.md)
