<div align="center">

# 🚀 Backtrader

**专业级 Python 量化交易回测框架**

[![Version](https://img.shields.io/badge/Version-1.0.0-blue.svg)]()
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPLv3-orange.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

[**English**](README.en.md) | **中文**

[📖 在线文档](https://gitee.com/cloudquant/backtrader/wikis) · 
[🐛 问题反馈](https://gitee.com/cloudquant/backtrader/issues) · 
[💬 讨论区](https://gitee.com/cloudquant/backtrader/issues)

</div>

---

## 📋 目录

- [项目简介](#-项目简介)
- [核心特性](#-核心特性)
- [快速安装](#-快速安装)
- [5 分钟入门教程](#-5-分钟入门教程)
- [核心概念详解](#-核心概念详解)
- [内置组件一览](#-内置组件一览)
- [进阶教程](#-进阶教程)
- [项目架构](#-项目架构)
- [API 文档](#-api-文档)
- [常见问题](#-常见问题)
- [贡献指南](#-贡献指南)
- [许可证](#-许可证)

---

## 🎯 项目简介

Backtrader 是一个功能强大、灵活易用的 Python 量化交易回测框架。本项目基于 [backtrader](https://www.backtrader.com/) 进行了大量优化和功能扩展，专注于中低频交易策略的研发与回测。

### 为什么选择 Backtrader？

| 对比项 | Backtrader | 其他框架 |
|--------|------------|----------|
| 学习曲线 | ⭐⭐ 平缓 | ⭐⭐⭐⭐ 陡峭 |
| 策略开发效率 | ⭐⭐⭐⭐⭐ 极高 | ⭐⭐⭐ 一般 |
| 内置指标数量 | 50+ | 10-30 |
| 数据源支持 | 20+ | 5-10 |
| 社区活跃度 | ⭐⭐⭐⭐ 活跃 | ⭐⭐ 一般 |
| 文档完整度 | ⭐⭐⭐⭐⭐ 完整 | ⭐⭐⭐ 一般 |

### 项目分支

- **master 分支**：稳定版本，包含功能扩展和 bug 修复
- **dev 分支**：开发版本，探索 C++ 底层重写以支持高频回测

---

## ✨ 核心特性

### 🚀 高性能回测引擎

```
支持两种回测模式：
├── runonce (向量化模式) - 批量计算，性能最优，适合研发调试
└── runnext (事件驱动模式) - 逐 Bar 计算，适合复杂逻辑和实盘对接
```

### 📊 丰富的可视化

- **Plotly 交互图表**：支持 10 万+ 数据点，缩放、平移、悬停查看
- **Bokeh 实时图表**：支持实时数据更新和多标签页
- **Matplotlib 静态图表**：经典绑图，适合论文和报告

### 📈 专业回测报告

一键生成包含以下内容的专业报告：
- 资金曲线和回撤图表
- 夏普比率、卡玛比率、SQN 评级
- 详细的交易统计和盈亏分析
- 支持 HTML、PDF、JSON 格式导出

### 🔧 50+ 内置技术指标

涵盖均线、动量、波动率、趋势等多个类别，开箱即用。

### 📦 模块化架构

策略、指标、分析器、数据源均可独立扩展，灵活组合。

### 🌍 20+ 数据源支持

CSV、Pandas、Yahoo Finance、Interactive Brokers、CCXT 加密货币等。

---

## 📥 快速安装

### 环境要求

- **Python**: 3.9+（推荐 3.11，性能提升约 15%）
- **操作系统**: Windows / macOS / Linux
- **内存**: 建议 4GB+

### 方式一：pip 安装（推荐）

```bash
# 从 Gitee 克隆（国内推荐）
git clone https://gitee.com/cloudquant/backtrader.git
cd backtrader

# 或从 GitHub 克隆
git clone https://github.com/cloudquant/backtrader.git
cd backtrader

# 安装依赖
pip install -r requirements.txt

# 安装 backtrader
pip install -e .
```

### 方式二：带 Cython 加速安装

```bash
# macOS / Linux
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U ./

# Windows
cd backtrader; python -W ignore compile_cython_numba_files.py; cd ..; pip install -U ./
```

### 验证安装

```python
import backtrader as bt
print(f"Backtrader 版本: {bt.__version__}")
# 输出: Backtrader 版本: 1.0.0
```

### 运行测试

```bash
pytest ./backtrader/tests -n 4 -v
```

---

## 🎓 5 分钟入门教程

### 第一步：理解回测流程

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   数据准备   │ -> │   策略编写   │ -> │   运行回测   │
└─────────────┘    └─────────────┘    └─────────────┘
       │                  │                  │
       v                  v                  v
  CSV/Pandas/API      继承 Strategy      cerebro.run()
                      实现 next()
```

### 第二步：编写第一个策略

```python
import backtrader as bt

# 定义策略：双均线金叉死叉
class SmaCrossStrategy(bt.Strategy):
    """
    双均线交叉策略：
    - 短期均线上穿长期均线时买入
    - 短期均线下穿长期均线时卖出
    """
    # 策略参数（可在回测时动态调整）
    params = (
        ('fast_period', 10),   # 短期均线周期
        ('slow_period', 30),   # 长期均线周期
    )
    
    def __init__(self):
        """初始化：计算指标（只执行一次）"""
        # 计算均线
        self.fast_sma = bt.indicators.SMA(
            self.data.close, 
            period=self.params.fast_period
        )
        self.slow_sma = bt.indicators.SMA(
            self.data.close, 
            period=self.params.slow_period
        )
        # 计算交叉信号
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
    
    def next(self):
        """每个 Bar 执行的交易逻辑"""
        if not self.position:  # 没有持仓
            if self.crossover > 0:  # 金叉
                self.buy()  # 买入
        else:  # 有持仓
            if self.crossover < 0:  # 死叉
                self.close()  # 平仓
```

### 第三步：准备数据

```python
# 方式一：从 CSV 文件加载
data = bt.feeds.GenericCSVData(
    dataname='your_data.csv',
    datetime=0,      # 日期列索引
    open=1,          # 开盘价列索引
    high=2,          # 最高价列索引
    low=3,           # 最低价列索引
    close=4,         # 收盘价列索引
    volume=5,        # 成交量列索引
    openinterest=-1, # 无持仓量
    dtformat='%Y-%m-%d',  # 日期格式
)

# 方式二：从 Pandas DataFrame 加载
import pandas as pd
df = pd.read_csv('your_data.csv', parse_dates=['date'], index_col='date')
data = bt.feeds.PandasData(dataname=df)

# 方式三：从 Yahoo Finance 下载
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2023, 12, 31),
)
```

### 第四步：运行回测

```python
# 创建回测引擎
cerebro = bt.Cerebro()

# 添加数据
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(SmaCrossStrategy)

# 设置初始资金
cerebro.broker.setcash(100000)

# 设置手续费（万分之三）
cerebro.broker.setcommission(commission=0.0003)

# 添加分析器
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# 运行回测
print(f'初始资金: {cerebro.broker.getvalue():,.2f}')
results = cerebro.run()
print(f'最终资金: {cerebro.broker.getvalue():,.2f}')

# 获取分析结果
strat = results[0]
sharpe = strat.analyzers.sharpe.get_analysis()
drawdown = strat.analyzers.drawdown.get_analysis()
trades = strat.analyzers.trades.get_analysis()

print(f"夏普比率: {sharpe.get('sharperatio', 'N/A')}")
print(f"最大回撤: {drawdown['max']['drawdown']:.2f}%")
print(f"总交易次数: {trades['total']['total']}")
```

### 第五步：可视化结果

```python
# 使用 Plotly 交互式图表（推荐）
cerebro.plot(backend='plotly', style='candle')

# 或使用传统 Matplotlib
cerebro.plot()

# 保存为 HTML 文件
from backtrader.plot import PlotlyPlot
plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html('backtest_chart.html')
```

---

## 📚 核心概念详解

### 1. Cerebro - 回测引擎

Cerebro 是 Backtrader 的核心引擎，负责协调所有组件。

```python
cerebro = bt.Cerebro()

# 核心方法
cerebro.adddata(data)              # 添加数据
cerebro.addstrategy(Strategy)      # 添加策略
cerebro.addanalyzer(Analyzer)      # 添加分析器
cerebro.addobserver(Observer)      # 添加观察者
cerebro.addsizer(Sizer)            # 添加仓位管理
cerebro.broker.setcash(100000)     # 设置初始资金
cerebro.broker.setcommission(0.001) # 设置手续费
results = cerebro.run()            # 运行回测
cerebro.plot()                     # 绑图
```

### 2. Strategy - 策略

策略是交易逻辑的核心，必须实现 `next()` 方法。

```python
class MyStrategy(bt.Strategy):
    params = (
        ('param1', 10),
        ('param2', 0.5),
    )
    
    def __init__(self):
        """初始化指标和变量"""
        self.sma = bt.indicators.SMA(period=self.params.param1)
    
    def next(self):
        """每个 Bar 的交易逻辑"""
        pass
    
    def notify_order(self, order):
        """订单状态变化通知"""
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f'买入: {order.executed.price}')
            else:
                print(f'卖出: {order.executed.price}')
    
    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            print(f'交易盈亏: {trade.pnl:.2f}')
```

### 3. Lines - 数据线

Backtrader 的核心数据结构，用于访问时间序列数据。

```python
# 在策略中访问数据
self.data.close[0]     # 当前 Bar 的收盘价
self.data.close[-1]    # 上一个 Bar 的收盘价
self.data.close[-2]    # 上上个 Bar 的收盘价
self.data.open[0]      # 当前 Bar 的开盘价
self.data.high[0]      # 当前 Bar 的最高价
self.data.low[0]       # 当前 Bar 的最低价
self.data.volume[0]    # 当前 Bar 的成交量
self.data.datetime[0]  # 当前 Bar 的时间（数字格式）

# 转换为日期时间
import backtrader as bt
current_dt = bt.num2date(self.data.datetime[0])
```

### 4. 订单类型

```python
# 市价单
self.buy()                          # 市价买入
self.sell()                         # 市价卖出
self.close()                        # 平仓

# 限价单
self.buy(price=100, exectype=bt.Order.Limit)
self.sell(price=110, exectype=bt.Order.Limit)

# 止损单
self.sell(price=95, exectype=bt.Order.Stop)

# 止盈止损单
self.buy_bracket(
    price=100,           # 入场价
    stopprice=95,        # 止损价
    limitprice=110,      # 止盈价
)

# 指定数量
self.buy(size=100)      # 买入 100 股

# 目标持仓
self.order_target_size(target=100)    # 调整到 100 股
self.order_target_percent(target=0.5) # 调整到 50% 仓位
self.order_target_value(target=10000) # 调整到 10000 元市值
```

---

## 📦 内置组件一览

### 技术指标（50+）

| 类别 | 指标 |
|------|------|
| **均线类** | SMA, EMA, WMA, SMMA, DEMA, TEMA, KAMA, HMA, ZLEMA |
| **动量类** | RSI, ROC, Momentum, Williams %R, Ultimate Oscillator |
| **波动率** | ATR, Bollinger Bands, Standard Deviation, True Range |
| **趋势类** | ADX, Aroon, Parabolic SAR, Ichimoku, DPO |
| **振荡器** | MACD, Stochastic, CCI, TSI, TRIX |
| **成交量** | OBV, MFI, AD, Volume Oscillator |
| **其他** | Pivot Points, Heikin Ashi, CrossOver |

### 分析器（17+）

| 分析器 | 功能 |
|--------|------|
| `SharpeRatio` | 夏普比率 |
| `DrawDown` | 最大回撤 |
| `TradeAnalyzer` | 交易统计 |
| `Returns` | 收益分析 |
| `AnnualReturn` | 年化收益 |
| `Calmar` | 卡玛比率 |
| `SQN` | 系统质量数 |
| `VWR` | 方差加权收益 |
| `TimeReturn` | 时间加权收益 |
| `PyFolio` | PyFolio 集成 |
| `Positions` | 持仓分析 |
| `Transactions` | 交易记录 |
| `Leverage` | 杠杆分析 |

### 数据源（20+）

| 数据源 | 说明 |
|--------|------|
| `GenericCSVData` | 通用 CSV |
| `PandasData` | Pandas DataFrame |
| `YahooFinanceData` | Yahoo Finance |
| `IBData` | Interactive Brokers |
| `CCXTFeed` | CCXT 加密货币 |
| `OandaData` | Oanda 外汇 |
| `QuandlData` | Quandl 数据 |
| `InfluxData` | InfluxDB |
| `VCData` | VisualChart |

---

## 🔬 进阶教程

### 参数优化

```python
# 网格搜索优化
cerebro.optstrategy(
    SmaCrossStrategy,
    fast_period=range(5, 20, 5),    # 5, 10, 15
    slow_period=range(20, 60, 10),  # 20, 30, 40, 50
)

# 运行优化
results = cerebro.run(maxcpus=4)  # 使用 4 核并行

# 获取最优参数
for result in results:
    strat = result[0]
    sharpe = strat.analyzers.sharpe.get_analysis()
    print(f"参数: fast={strat.params.fast_period}, slow={strat.params.slow_period}")
    print(f"夏普比率: {sharpe.get('sharperatio', 'N/A')}")
```

### 多数据源回测

```python
# 添加多个数据源
data1 = bt.feeds.PandasData(dataname=df1, name='stock1')
data2 = bt.feeds.PandasData(dataname=df2, name='stock2')

cerebro.adddata(data1)
cerebro.adddata(data2)

# 在策略中访问
class MultiDataStrategy(bt.Strategy):
    def next(self):
        # 访问第一个数据源
        price1 = self.datas[0].close[0]
        # 访问第二个数据源
        price2 = self.datas[1].close[0]
        
        # 或使用名称访问
        # self.getdatabyname('stock1').close[0]
```

### 自定义指标

```python
class MyIndicator(bt.Indicator):
    """自定义指标示例"""
    lines = ('myline',)  # 定义输出线
    params = (('period', 20),)  # 定义参数
    
    def __init__(self):
        self.lines.myline = bt.indicators.SMA(
            self.data.close, 
            period=self.params.period
        ) * 2 - bt.indicators.SMA(
            self.data.close, 
            period=self.params.period * 2
        )
```

### 自定义分析器

```python
class MyAnalyzer(bt.Analyzer):
    """自定义分析器示例"""
    
    def __init__(self):
        self.returns = []
    
    def next(self):
        self.returns.append(self.strategy.broker.getvalue())
    
    def get_analysis(self):
        return {
            'total_return': (self.returns[-1] / self.returns[0] - 1) * 100,
            'max_value': max(self.returns),
            'min_value': min(self.returns),
        }
```

### 生成专业报告

```python
# 添加报告所需的分析器
cerebro.add_report_analyzers(riskfree_rate=0.02)

# 运行回测
results = cerebro.run()

# 生成 HTML 报告
cerebro.generate_report(
    'backtest_report.html',
    user='量化研究员',
    memo='双均线策略回测报告'
)

# 生成 PDF 报告
cerebro.generate_report('backtest_report.pdf', format='pdf')

# 导出 JSON 数据
cerebro.generate_report('backtest_data.json', format='json')
```

---

## 🏗 项目架构

```
backtrader/
├── backtrader/                 # 核心代码库
│   ├── __init__.py            # 包入口
│   ├── version.py             # 版本信息
│   │
│   ├── # === 核心引擎 ===
│   ├── cerebro.py             # 主引擎（88KB）- 回测调度核心
│   ├── strategy.py            # 策略基类（100KB）- 策略开发基础
│   │
│   ├── # === 数据系统 ===
│   ├── linebuffer.py          # 线缓冲（103KB）- 核心数据结构
│   ├── lineiterator.py        # 迭代器（95KB）- 数据遍历
│   ├── lineseries.py          # 线序列（76KB）- 多线管理
│   ├── lineroot.py            # 根类（37KB）- 基础定义
│   ├── dataseries.py          # 数据序列（12KB）
│   ├── feed.py                # 数据源基类（51KB）
│   ├── feeds/                 # 数据源实现（21个）
│   │   ├── csvgeneric.py      # 通用 CSV
│   │   ├── pandafeed.py       # Pandas
│   │   ├── yahoo.py           # Yahoo Finance
│   │   ├── ibdata.py          # Interactive Brokers
│   │   └── ...
│   │
│   ├── # === 交易系统 ===
│   ├── broker.py              # 经纪商基类
│   ├── brokers/               # 经纪商实现
│   ├── order.py               # 订单类（37KB）
│   ├── trade.py               # 交易类（16KB）
│   ├── position.py            # 持仓类（11KB）
│   ├── comminfo.py            # 手续费（16KB）
│   │
│   ├── # === 指标系统 ===
│   ├── indicator.py           # 指标基类（15KB）
│   ├── indicators/            # 技术指标（52个）
│   │   ├── sma.py             # 简单移动平均
│   │   ├── ema.py             # 指数移动平均
│   │   ├── rsi.py             # 相对强弱指标
│   │   ├── macd.py            # MACD
│   │   ├── bollinger.py       # 布林带
│   │   └── ...
│   │
│   ├── # === 分析系统 ===
│   ├── analyzer.py            # 分析器基类（21KB）
│   ├── analyzers/             # 分析器实现（17个）
│   │   ├── sharpe.py          # 夏普比率
│   │   ├── drawdown.py        # 最大回撤
│   │   ├── tradeanalyzer.py   # 交易统计
│   │   └── ...
│   │
│   ├── # === 可视化 ===
│   ├── plot/                  # 绑图模块
│   │   ├── plot_plotly.py     # Plotly 绑图
│   │   └── plot.py            # Matplotlib 绑图
│   ├── bokeh/                 # Bokeh 图表
│   ├── reports/               # 报告生成
│   │
│   ├── # === 其他模块 ===
│   ├── sizer.py               # 仓位管理
│   ├── sizers/                # 仓位管理实现
│   ├── observer.py            # 观察者基类
│   ├── observers/             # 观察者实现
│   ├── filters/               # 数据过滤器
│   ├── timer.py               # 定时器
│   ├── signal.py              # 信号系统
│   ├── metabase.py            # 元类系统（83KB）
│   └── parameters.py          # 参数系统（76KB）
│
├── examples/                   # 示例代码
├── tests/                      # 测试用例
├── docs/                       # 文档
│   ├── source/                # Sphinx 文档源
│   └── build_docs.sh          # 文档构建脚本
├── requirements.txt            # 依赖列表
├── setup.py                   # 安装脚本
├── README.md                  # 中文说明
└── README.en.md               # 英文说明
```

---

## 📖 API 文档

完整的 API 文档可通过以下方式访问：

### 在线文档

构建本地文档：

```bash
cd docs
pip install -r requirements.txt
./build_docs.sh all
./build_docs.sh serve
# 访问 http://localhost:8000
```

### 常用 API 速查

```python
import backtrader as bt

# Cerebro
cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.addstrategy(Strategy, param1=value1)
cerebro.addanalyzer(bt.analyzers.SharpeRatio)
cerebro.broker.setcash(100000)
cerebro.broker.setcommission(commission=0.001)
results = cerebro.run()
cerebro.plot()

# Strategy
self.buy(size=100)
self.sell(size=100)
self.close()
self.order_target_percent(target=0.5)
self.position.size  # 当前持仓
self.broker.getvalue()  # 账户价值
self.broker.getcash()  # 可用现金

# Data
self.data.close[0]   # 当前收盘价
self.data.close[-1]  # 上一收盘价
len(self.data)       # 已处理的 Bar 数量

# Indicators
bt.indicators.SMA(data, period=20)
bt.indicators.EMA(data, period=20)
bt.indicators.RSI(data, period=14)
bt.indicators.MACD(data)
bt.indicators.BollingerBands(data)
bt.indicators.ATR(data)
bt.indicators.CrossOver(line1, line2)
```

---

## ❓ 常见问题

### Q1: 如何处理复权数据？

```python
# 建议使用前复权数据进行回测
# 或在数据加载后进行复权处理
data = bt.feeds.PandasData(
    dataname=df,
    adjclose=True,  # 使用复权收盘价
)
```

### Q2: 如何设置滑点？

```python
cerebro.broker.set_slippage_fixed(0.01)  # 固定滑点
cerebro.broker.set_slippage_perc(0.001)  # 百分比滑点
```

### Q3: 如何限制单笔交易数量？

```python
class FixedSizer(bt.Sizer):
    params = (('stake', 100),)
    
    def _getsizing(self, comminfo, cash, data, isbuy):
        return self.params.stake

cerebro.addsizer(FixedSizer, stake=100)
```

### Q4: 如何获取所有交易记录？

```python
cerebro.addanalyzer(bt.analyzers.Transactions, _name='txn')
results = cerebro.run()
transactions = results[0].analyzers.txn.get_analysis()
```

### Q5: 回测速度慢怎么办？

```python
# 1. 使用 runonce 模式（默认）
cerebro.run(runonce=True)

# 2. 减少数据量
# 3. 安装 Cython 加速
# 4. 使用多进程优化（参数优化时）
cerebro.run(maxcpus=4)
```

---

## 🤝 贡献指南

我们欢迎各种形式的贡献！

### 提交问题

1. 检查是否已存在相似问题
2. 提供详细的复现步骤
3. 附上错误日志和环境信息

### 提交代码

```bash
# 1. Fork 仓库
# 2. 创建分支
git checkout -b feature/your-feature

# 3. 提交代码
git commit -m "feat: add your feature"

# 4. 推送分支
git push origin feature/your-feature

# 5. 创建 Pull Request
```

### 代码规范

- 遵循 PEP 8 规范
- 添加适当的文档字符串
- 编写单元测试

---

## 📄 许可证

本项目采用 [GPLv3](LICENSE) 许可证开源。

---

## 📞 联系方式

- **Gitee**: [https://gitee.com/yunjinqi/backtrader](https://gitee.com/yunjinqi/backtrader)
- **GitHub**: [https://github.com/cloudquant/backtrader](https://github.com/cloudquant/backtrader)
- **作者博客**: [https://yunjinqi.blog.csdn.net/](https://yunjinqi.blog.csdn.net/)
- **问题反馈**: [https://gitee.com/yunjinqi/backtrader/issues](https://gitee.com/yunjinqi/backtrader/issues)

---

<div align="center">

**如果本项目对您有帮助，请点个 ⭐ Star 支持我们！**

Made with ❤️ by CloudQuant

</div>