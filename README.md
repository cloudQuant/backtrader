

# backtrader

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-GPLv3-green.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

**[English](README.en.md)** | **中文**

---

## 介绍

backtrader 是基于 [backtrader](https://www.backtrader.com/) 打造的专业量化投研工具，专注于中低频交易策略开发。项目采用双分支开发模式：

- **master 分支**：与官方主流 backtrader 保持同步，在其基础上增加部分功能扩展和 bug 修复，可直接运行 CSDN 专栏中的策略示例
- **dev 分支**：持续开发新功能，探索 C++ 底层重写以支持 tick 级别高频回测，完善后将合并到 master

---

## 主要特性

| 特性 | 描述 |
|------|------|
| 🚀 **高性能回测** | 支持向量化（runonce）和事件驱动（runnext）两种回测模式 |
| 📊 **Plotly 交互图表** | 支持 10 万+ 数据点的交互式绑图，缩放、平移、悬停查看 |
| 📈 **一键生成报告** | 自动生成 HTML/PDF/JSON 格式的专业回测报告 |
| 🔧 **丰富分析器** | 夏普比率、最大回撤、SQN 评级、收益统计等全面指标 |
| 📦 **模块化设计** | 策略、指标、交易费用、数据源均可灵活扩展 |
| 🌍 **多数据源支持** | CSV、Pandas、Yahoo、CCXT、IB 等多种数据接入方式 |

---

## 安装教程

### 环境要求

- Python 3.9+（推荐 3.11，性能更佳）
- Windows / macOS / Linux

### 安装步骤

```bash
# 1. 克隆项目
git clone https://gitee.com/yunjinqi/backtrader.git
cd backtrader

# 2. 安装依赖
pip install -r requirements.txt

# 3. 编译 Cython 扩展（Mac/Linux）
cd backtrader && python -W ignore compile_cython_numba_files.py && cd .. && pip install -U ./

# 3. 编译 Cython 扩展（Windows）
cd backtrader; python -W ignore compile_cython_numba_files.py; cd ..; pip install -U ./

# 4. 运行测试
pytest ./backtrader/tests -n 4
```

---

## 快速开始

### 基本回测流程

```python
import backtrader as bt
import pandas as pd

# 1. 创建策略
class SmaCross(bt.Strategy):
    params = (('fast', 10), ('slow', 30))
    
    def __init__(self):
        sma_fast = bt.indicators.SimpleMovingAverage(period=self.params.fast)
        sma_slow = bt.indicators.SimpleMovingAverage(period=self.params.slow)
        self.crossover = bt.indicators.CrossOver(sma_fast, sma_slow)
    
    def next(self):
        if not self.position:
            if self.crossover > 0:
                self.buy()
        elif self.crossover < 0:
            self.close()

# 2. 创建引擎
cerebro = bt.Cerebro()

# 3. 加载数据（CSV 格式）
data = bt.feeds.GenericCSVData(
    dataname='data.csv',
    datetime=0, open=1, high=2, low=3, close=4, volume=5,
    openinterest=-1, fromdate='2020-01-01', todate='2023-12-31'
)
cerebro.adddata(data)

# 4. 添加策略和分析器
cerebro.addstrategy(SmaCross)
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

# 5. 运行回测
results = cerebro.run()

# 6. 查看结果
print(f"夏普比率: {results[0].analyzers.sharpe.get_analysis()['sharpeRatio']:.2f}")
print(f"最大回撤: {results[0].analyzers.drawdown.get_analysis()['max']['drawdown']:.2f}%")

# 7. 绑图
cerebro.plot(backend="plotly", style="candle")
```

### Plotly 交互式图表

```python
import backtrader as bt

cerebro = bt.Cerebro()
# ... 添加策略和数据 ...

cerebro.run()

# 使用 Plotly 后端（推荐大数据量使用）
cerebro.plot(backend="plotly", style="candle")

# 保存为 HTML 文件
from backtrader.plot import PlotlyPlot
plotter = PlotlyPlot(style='candle')
figs = plotter.plot(results[0])
figs[0].write_html("chart.html")
```

### 生成回测报告

```python
import backtrader as bt

cerebro = bt.Cerebro()
cerebro.addstrategy(MyStrategy)
cerebro.adddata(data)

# 自动添加报告所需分析器
cerebro.add_report_analyzers(riskfree_rate=0.02)

cerebro.run()

# 一键生成报告
cerebro.generate_report('backtest_report.html', user='Trader', memo='双均线策略')

# 生成 PDF 报告
cerebro.generate_report('backtest_report.pdf', format='pdf')

# 导出 JSON 数据
cerebro.generate_report('backtest_data.json', format='json')
```

---

## 示例代码

项目提供了丰富的示例代码，位于 `examples/` 目录：

| 示例文件 | 功能说明 |
|----------|----------|
| `example_plotly_charts.py` | Plotly 交互式图表、配色方案、HTML 导出 |
| `example_bokeh_charts.py` | Bokeh 图表、主题、标签页、Recorder |
| `example_report_generation.py` | 报告生成、PDF/JSON 导出、性能指标 |

运行示例：

```bash
python examples/example_plotly_charts.py
python examples/example_bokeh_charts.py
python examples/example_report_generation.py
```

---

## 文档资源

- **官方文档**：[https://www.backtrader.com/](https://www.backtrader.com/)
- **中文教程**：[https://yunjinqi.blog.csdn.net/](https://yunjinqi.blog.csdn.net/)
- **本项目文档**：[docs/](/docs/)
  - [快速开始](/docs/getting_started/quickstart.md)
  - [用户指南](/docs/user_guide/)
  - [策略开发指南](/docs/user_guide/strategies.md)
  - [指标系统指南](/docs/user_guide/indicators.md)
  - [参数系统使用](/docs/user_guide/parameter_system_quick_start.md)

---

## 项目架构

```
backtrader/
├── backtrader/              # 核心代码
│   ├── analyzer.py          # 分析器基类
│   ├── analyzers/           # 各类分析器实现
│   ├── broker.py            # 经纪商基类
│   ├── brokers/             # 经纪商实现
│   ├── cerebro.py           # 主引擎
│   ├── dataseries.py        # 数据序列
│   ├── feed.py              # 数据源基类
│   ├── feeds/               # 各类数据源
│   ├── filters/             # 数据过滤器
│   ├── indicator.py         # 指标基类
│   ├── indicators/          # 技术指标实现
│   ├── linebuffer.py        # 核心线缓冲系统
│   ├── lineiterator.py      # 迭代器基类
│   ├── lineroot.py          # 根类定义
│   ├── lineseries.py        # 线序列实现
│   ├── observer.py          # 观察者基类
│   ├── observers/           # 观察者实现
│   ├── order.py             # 订单类
│   ├── parameters.py        # 参数管理系统
│   ├── plot/                # 绑图模块
│   ├── reports/             # 报告生成
│   ├── resamplerfilter.py   # 重采样/回放
│   ├── sizer.py             # 仓位管理
│   ├── store.py             # 存储基类
│   ├── stores/              # 数据存储实现
│   ├── strategy.py          # 策略基类
│   └── timer.py             # 定时器
├── examples/                # 示例代码
├── tests/                   # 测试用例
├── docs/                    # 文档
└── requirements.txt         # 依赖列表
```

---

## 技术亮点

### 1. Line 系统核心设计

backtrader 的核心是 Line 系统，用于处理时间序列数据：

- **LineBuffer**：底层数据存储，支持高效的前向/后向遍历
- **LineSeries**：多线序列，承载 OHLCV 等数据
- **LineIterator**：迭代器基类，指标、策略、观察者都继承自此类

### 2. 双模式回测

| 模式 | 特点 | 适用场景 |
|------|------|----------|
| **runonce** | 向量化批量计算，性能高 | 中低频、研发调试 |
| **runnext** | 事件驱动逐根计算 | 高频、需要实时逻辑 |

### 3. 参数系统重构

项目正在逐步移除元编程，引入显式参数描述符系统：

```python
# 新方式：显式参数定义
class MyStrategy(bt.Strategy):
    period = bt.parameters.Int(default=20, min_val=1, max_val=200)
    threshold = bt.parameters.Float(default=0.02, min_val=0.0)
```

---

## 测试

```bash
# 运行所有测试（推荐并行执行）
pytest ./backtrader/tests -n 4

# 运行特定测试
pytest ./backtrader/tests/test_backtrader.py -v

# 运行策略测试
pytest ./tests/strategies/ -v

# 查看测试覆盖率
pytest --cov=backtrader ./backtrader/tests
```

---

## 贡献指南

欢迎提交 Issue 和 Pull Request：

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/xxx`
3. 提交更改：`git commit -m "Add xxx"`
4. 推送分支：`git push origin feature/xxx`
5. 提交 Pull Request

---

## 许可证

本项目采用 [GPLv3](LICENSE) 许可证开源。

---

## 联系方式

- 项目地址：[https://gitee.com/yunjinqi/backtrader](https://gitee.com/yunjinqi/backtrader)
- 作者博客：[https://yunjinqi.blog.csdn.net/](https://yunjinqi.blog.csdn.net/)
- 问题反馈：[https://gitee.com/yunjinqi/backtrader/issues](https://gitee.com/yunjinqi/backtrader/issues)

---

*如果本项目对您有帮助，欢迎 Star 支持！*