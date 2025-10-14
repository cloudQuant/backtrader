# CLAUDE.md

本文件为 Claude AI 助手提供在此代码仓库中工作的指导信息。

## 项目概述

这是 backtrader Python 量化交易和回测库的增强版本。在保持与原版 backtrader 兼容的基础上，增加了以下特性：
- 🪙 **加密货币交易支持**：通过 CCXT 集成100+加密货币交易所
- 🏦 **多市场支持**：股票、期货（CTP）、外汇（Oanda）、加密货币
- 📈 **丰富的技术指标**：内置50+技术指标
- 📊 **资金费率回测**：支持加密货币永续合约的资金费率回测
- 🔧 **改进的兼容性**：支持 Python 3.8-3.13

## 开发命令

### 安装和设置

```bash
# 克隆仓库
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader

# 安装依赖
pip install -r requirements.txt

# 安装包（开发模式）
pip install -e .

# 或使用常规安装
pip install .
```

### 测试

```bash
# 运行所有测试（并行执行）
pytest tests -n 4

# 运行特定测试目录
pytest tests/original_tests         # 核心功能测试
pytest tests/base_functions         # 基础功能测试
pytest tests/funding_rate_examples  # 加密货币资金费率测试

# 运行单个测试文件
pytest tests/original_tests/test_ind_sma.py

# 查看测试覆盖率
pytest tests --cov=backtrader --cov-report=html
```

### 构建发布包

```bash
# 构建源码包和wheel包
python setup.py sdist bdist_wheel

# 或使用 build 工具
pip install build
python -m build
```

## 项目架构

### 核心组件

#### 1. Cerebro 引擎 (`cerebro.py`)
- 核心调度引擎，协调数据源、策略、经纪商和观察者
- 支持参数优化（多进程）
- 管理回测生命周期（start → prenext → next → stop）
- 关键参数：
  - `preload`: 是否预加载数据（默认True）
  - `runonce`: 向量化运行指标计算（默认True）
  - `exactbars`: 内存管理模式（0/-1/-2）
  - `stdstats`: 是否添加默认观察者（默认True）

#### 2. Strategy 策略 (`strategy.py`)
- 策略基类，所有交易策略继承此类
- 事件驱动架构：`__init__` → `prenext` → `next` → `notify_order` → `notify_trade`
- 内置方法：
  - `buy()` / `sell()`: 下单
  - `close()`: 平仓
  - `notify_order()`: 订单状态通知
  - `notify_trade()`: 交易通知
  - `log()`: 日志记录

#### 3. Data Feeds 数据源 (`feeds/`)
支持多种数据源：
- **CSV 文件**：`GenericCSVData`, `BacktraderCSVData`
- **Pandas DataFrame**：`PandasData`
- **在线数据**：`YahooFinanceData`, `QuandlData`
- **加密货币**：`CCXTFeed`（支持实时和历史数据）
- **期货**：`CTPData`（中国期货市场）
- **外汇**：`OandaData`
- **股票**：`IBData`（Interactive Brokers）
- **其他**：`InfluxFeed`, `MT4CSV`, `SierraChartCSV`, `VChartData`

#### 4. Brokers 经纪商 (`brokers/`)
- **BackBroker** (`bbroker.py`): 默认回测经纪商
- **CCXTBroker** (`ccxtbroker.py`): 加密货币交易所经纪商
- **CTPBroker** (`ctpbroker.py`): CTP期货经纪商
- **IBBroker** (`ibbroker.py`): Interactive Brokers 经纪商
- **OandaBroker** (`oandabroker.py`): Oanda 外汇经纪商
- **VCBroker** (`vcbroker.py`): VChart 经纪商

#### 5. Indicators 技术指标 (`indicators/`)
50+ 内置技术指标，包括：
- **趋势指标**：SMA, EMA, WMA, DEMA, TEMA, HMA, KAMA, ZLEMA
- **震荡指标**：RSI, MACD, Stochastic, CCI, Williams %R, RMI
- **动量指标**：Momentum, ROC, TSI, KST, PrettyGoodOscillator
- **波动率指标**：ATR, Bollinger Bands, Envelope
- **其他**：Aroon, Ichimoku, PSAR, Vortex, DPO, DV2

#### 6. Analyzers 分析器 (`analyzers/`)
性能分析工具：
- **SharpeRatio**: 夏普比率
- **DrawDown**: 最大回撤分析
- **Returns**: 收益率分析
- **TradeAnalyzer**: 交易统计
- **SQN**: 系统质量数（System Quality Number）
- **TimeReturn**: 时间序列收益
- **AnnualReturn**: 年化收益
- **Calmar**: 卡玛比率
- **VWR**: 可变权重收益
- **PyFolio**: PyFolio 集成

#### 7. Observers 观察者 (`observers/`)
- **Broker**: 现金和总价值观察器
- **BuySell**: 买卖信号观察器
- **Trades**: 交易观察器
- **DrawDown**: 回撤观察器
- **Benchmark**: 基准对比观察器
- **TimeReturn**: 时间收益观察器

### 关键目录说明

```
backtrader/
├── __init__.py          # 包初始化，导出所有公共API
├── cerebro.py           # 核心引擎
├── strategy.py          # 策略基类
├── broker.py            # 经纪商基类
├── feed.py              # 数据源基类
├── order.py             # 订单类
├── position.py          # 持仓类
├── trade.py             # 交易类
├── indicator.py         # 指标基类
├── analyzer.py          # 分析器基类
├── observer.py          # 观察者基类
├── sizer.py             # 仓位管理器基类
├── brokers/             # 各类经纪商实现
├── feeds/               # 各类数据源实现
├── indicators/          # 技术指标库
├── analyzers/           # 分析器库
├── observers/           # 观察者库
├── sizers/              # 仓位管理器
├── stores/              # 数据和经纪商存储接口
├── filters/             # 数据过滤器
├── commissions/         # 佣金模型
└── utils/               # 工具函数

strategies/              # 示例策略
tests/                   # 测试套件
├── original_tests/      # 核心功能测试
├── base_functions/      # 基础功能测试
├── funding_rate_examples/  # 资金费率测试
└── datas/               # 测试数据
```

## 重要功能特性

### 1. 加密货币交易 (CCXT)

项目通过 CCXT 库集成了加密货币交易功能：

**核心文件**：
- `stores/ccxtstore.py`: CCXT 存储接口（单例模式）
- `feeds/ccxtfeed.py`: CCXT 数据源
- `brokers/ccxtbroker.py`: CCXT 经纪商

**支持的功能**：
- 100+ 交易所支持（Binance, OKX, Huobi等）
- 历史数据回测和实时交易
- 多种时间周期（1m, 5m, 15m, 1h, 4h, 1d等）
- 资金费率回测（永续合约）
- 订单类型：市价单、限价单、止损单

### 2. CTP 期货交易

支持中国期货市场的 CTP 接口：

**核心文件**：
- `stores/ctpstore.py`: CTP 存储接口
- `feeds/ctpdata.py`: CTP 数据源
- `brokers/ctpbroker.py`: CTP 经纪商

**支持的功能**：
- 实时行情订阅
- 期货合约交易
- 多空双向持仓
- 实时账户信息

### 3. 资金费率回测

针对加密货币永续合约的资金费率回测功能：

**实现位置**：
- 测试示例：`tests/funding_rate_examples/test_base_funding_rate.py`
- 相关数据处理在 CCXT feeds 和 brokers 中

### 4. 多时间周期支持

支持在同一策略中使用多个时间周期的数据：

```python
# 在策略中添加多个时间周期
cerebro.resampledata(data, timeframe=bt.TimeFrame.Minutes, compression=60)
```

### 5. 参数优化

支持多进程参数优化：

```python
# 使用 optstrategy 进行参数优化
cerebro.optstrategy(MyStrategy, period=range(10, 31))
cerebro.run(maxcpus=4)  # 使用4个CPU核心
```

## 代码风格和约定

### Python 版本兼容性

- 支持 Python 3.8 - 3.13
- 使用 `from __future__ import` 确保向后兼容
- 使用 `utils.py3` 模块处理 Python 2/3 差异

### 元类设计

项目大量使用元类（Metaclass）实现高级功能：
- `MetaParams`: 参数管理
- `MetaStrategy`: 策略元类
- `MetaLineIterator`: 行迭代器元类
- `MetaIndicator`: 指标元类

### Lines 对象

核心数据结构，用于存储时间序列数据：
```python
class MyIndicator(bt.Indicator):
    lines = ('signal',)  # 定义输出线
    
    def __init__(self):
        self.lines.signal = self.data.close > self.data.close(-1)
```

### 参数系统

使用 `params` 元组定义可配置参数：
```python
class MyStrategy(bt.Strategy):
    params = (
        ('period', 20),
        ('stake', 10),
    )
    
    def __init__(self):
        self.sma = bt.indicators.SMA(period=self.params.period)
```

## 测试框架

### 测试结构

- **pytest** 作为测试框架
- **pytest-xdist** 支持并行测试
- **pytest-cov** 测试覆盖率
- **pytest-benchmark** 性能基准测试

### 测试分类

1. **original_tests/**: 83个核心功能测试
   - 指标测试（test_ind_*.py）
   - 数据测试（test_data_*.py）
   - 分析器测试（test_analyzer-*.py）
   - 策略测试（test_strategy_*.py）

2. **base_functions/**: 基础功能测试
   - NumPy 转换测试

3. **funding_rate_examples/**: 加密货币特定功能
   - 资金费率回测测试

### 测试数据

- 位置：`tests/datas/`
- 格式：CSV 和 TXT 文件
- 包含多种市场数据（股票、期货等）

## 常见开发任务

### 添加新指标

1. 在 `backtrader/indicators/` 创建新文件
2. 继承 `bt.Indicator` 基类
3. 定义 `lines` 和 `params`
4. 实现计算逻辑
5. 在 `indicators/__init__.py` 中导出

### 添加新数据源

1. 在 `backtrader/feeds/` 创建新文件
2. 继承 `bt.DataBase`
3. 实现 `_load()` 方法
4. 在 `feeds/__init__.py` 中导出

### 添加新分析器

1. 在 `backtrader/analyzers/` 创建新文件
2. 继承 `bt.Analyzer`
3. 实现 `start()`, `next()`, `stop()` 方法
4. 使用 `create_analysis()` 初始化结果
5. 在 `analyzers/__init__.py` 中导出

## 性能优化建议

### 回测加速

1. **使用 runonce 模式**：`cerebro = bt.Cerebro(runonce=True)`
2. **预加载数据**：`cerebro = bt.Cerebro(preload=True)`
3. **减少指标计算**：只使用必要的指标
4. **内存优化**：使用 `exactbars` 参数

### 内存优化

```python
# 节省内存
cerebro = bt.Cerebro(exactbars=1)  # 只保留最小必要数据

# 保留所有数据用于绘图
cerebro = bt.Cerebro(exactbars=-1)
```

## 常见问题

### 1. 如何访问历史数据？

```python
# 在策略中
current_close = self.data.close[0]   # 当前收盘价
previous_close = self.data.close[-1]  # 上一根K线收盘价
```

### 2. 如何处理多个数据源？

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.data0 = self.datas[0]  # 主数据
        self.data1 = self.datas[1]  # 辅助数据
```

### 3. 如何自定义佣金？

```python
cerebro.broker.setcommission(commission=0.001)  # 0.1% 佣金
```

### 4. 如何设置初始资金？

```python
cerebro.broker.setcash(100000.0)  # 设置10万初始资金
```

## 相关资源

- **官方文档**: https://www.backtrader.com/
- **CSDN教程**: https://blog.csdn.net/qq_26948675/category_10220116.html
- **问题反馈**: https://gitee.com/yunjinqi/backtrader/issues
- **源码仓库**: 
  - Gitee: https://gitee.com/yunjinqi/backtrader
  - GitHub: https://github.com/cloudQuant/backtrader

## 版本信息

- **当前版本**: 1.9.76.123
- **Python支持**: 3.8, 3.9, 3.10, 3.11, 3.12, 3.13
- **主要依赖**: matplotlib, pandas, numpy, ccxt, pytest

## 许可证

GNU General Public License v3.0
