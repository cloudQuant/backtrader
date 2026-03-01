# Jupyter Notebook 交互式教程

本教程将帮助您在 Jupyter Notebook/Lab 中高效使用 Backtrader 进行量化交易策略开发、回测和分析。

## 目录

1. [环境安装与设置](#环境安装与设置)
2. [快速开始](#快速开始)
3. [数据加载与探索](#数据加载与探索)
4. [策略开发工作流](#策略开发工作流)
5. [可视化与绘图](#可视化与绘图)
6. [参数敏感性分析](#参数敏感性分析)
7. [多策略比较](#多策略比较)
8. [实时数据监控](#实时数据监控)
9. [结果导出与报告](#结果导出与报告)
10. [最佳实践](#最佳实践)

---

## 环境安装与设置

### 安装必要依赖

在开始之前，请确保已安装以下依赖：

```bash
# 核心依赖
pip install backtrader

# Jupyter 环境
pip install jupyter jupyterlab

# 可视化库
pip install matplotlib plotly

# 数据处理
pip install pandas numpy

# 可选：财经数据获取
pip install yfinance
```

### 启动 Jupyter Notebook

```bash
# 启动 Jupyter Notebook
jupyter notebook

# 或启动 JupyterLab（推荐）
jupyter lab
```

### 配置显示设置

在笔记本的第一个单元格中，设置常用的显示选项：

```python
# 在 Jupyter 中设置显示选项
%matplotlib inline
%load_ext autoreload
%autoreload 2

import warnings
warnings.filterwarnings('ignore')

# 设置 pandas 显示选项
import pandas as pd
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)

print("环境设置完成!")
```

### 验证 Backtrader 安装

```python
import backtrader as bt
print(f"Backtrader 版本: {bt.__version__}")
print("Backtrader 安装成功!")
```

---

## 快速开始

### 第一个回测示例

```python
import backtrader as bt
import pandas as pd
import datetime

# 1. 创建一个简单的策略
class SimpleStrategy(bt.Strategy):
    """简单移动平均线交叉策略"""

    params = (
        ('ma_period', 20),
    )

    def __init__(self):
        # 计算移动平均线
        self.ma = bt.indicators.SMA(self.data.close, period=self.params.ma_period)
        self.close = self.data.close

    def next(self):
        # 如果没有持仓
        if not self.position:
            # 价格上穿均线时买入
            if self.close[0] > self.ma[0] and self.close[-1] <= self.ma[-1]:
                self.buy()
        else:
            # 价格下穿均线时卖出
            if self.close[0] < self.ma[0] and self.close[-1] >= self.ma[-1]:
                self.sell()

# 2. 创建 Cerebro 引擎
cerebro = bt.Cerebro()

# 3. 添加策略
cerebro.addstrategy(SimpleStrategy, ma_period=20)

# 4. 加载数据（这里使用示例数据）
data = bt.feeds.BacktraderCSVData(
    dataname='path/to/your/data.csv',
    fromdate=datetime.datetime(2020, 1, 1),
    todate=datetime.datetime(2023, 12, 31)
)
cerebro.adddata(data)

# 5. 设置初始资金
cerebro.broker.setcash(10000.0)

# 6. 运行回测
print(f'初始资金: {cerebro.broker.getvalue():.2f}')
results = cerebro.run()
print(f'最终资金: {cerebro.broker.getvalue():.2f}')
```

---

## 数据加载与探索

### 从 CSV 文件加载数据

```python
# 方法1: 使用 Backtrader 内置格式
data = bt.feeds.BacktraderCSVData(
    dataname='data.csv',
    datetime=0,      # datetime 列索引
    time=1,          # time 列索引（可选）
    open=2,          # open 列索引
    high=3,          # high 列索引
    low=4,           # low 列索引
    close=5,         # close 列索引
    volume=6,        # volume 列索引
    openinterest=-1  # 无 openinterest
)

# 方法2: 使用 GenericCSVData 自定义格式
data = bt.feeds.GenericCSVData(
    dataname='custom_data.csv',
    dtformat='%Y-%m-%d',  # 日期格式
    datetime=0,
    time=-1,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1
)
```

### 从 Pandas DataFrame 加载数据

```python
# 使用 yfinance 获取数据
import yfinance as yf

# 下载数据
df = yf.download('AAPL', start='2020-01-01', end='2023-12-31')

# 重置索引（Backtrader 需要 datetime 作为列）
df = df.reset_index()

# 转换为 Backtrader 数据源
data = bt.feeds.PandasData(
    dataname=df,
    datetime=None,  # 自动检测索引
    open='Open',
    high='High',
    low='Low',
    close='Close',
    volume='Volume',
    openinterest=None
)

# 添加到 Cerebro
cerebro = bt.Cerebro()
cerebro.adddata(data)
```

### 自定义 Pandas 数据源

```python
# 创建自定义数据类，支持更多字段
class EnhancedPandasData(bt.feeds.PandasData):
    """扩展的 Pandas 数据源，支持更多字段"""

    lines = ('pe_ratio', 'market_cap')  # 新增线条

    # 设置列映射
    params = (
        ('datetime', None),
        ('open', 'Open'),
        ('high', 'High'),
        ('low', 'Low'),
        ('close', 'Close'),
        ('volume', 'Volume'),
        ('openinterest', None),
        ('pe_ratio', 'PE_Ratio'),      # 自定义字段
        ('market_cap', 'Market_Cap'),  # 自定义字段
    )

# 使用示例
# df['PE_Ratio'] = ...  # 添加自定义列
# df['Market_Cap'] = ...
# data = EnhancedPandasData(dataname=df)
```

### 数据探索

```python
# 在笔记本中可视化数据
import matplotlib.pyplot as plt

# 加载数据到 DataFrame 进行探索
df = yf.download('AAPL', start='2020-01-01', end='2023-12-31')

# 基本统计信息
print("数据概览:")
print(df.info())
print("\n统计信息:")
print(df.describe())

# 绘制价格走势
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

# 价格走势
df['Close'].plot(ax=axes[0], title='AAPL 收盘价')
axes[0].set_ylabel('价格')

# 成交量
df['Volume'].plot(ax=axes[1], title='成交量')
axes[1].set_ylabel('成交量')

plt.tight_layout()
plt.show()

# 计算基本指标
df['SMA20'] = df['Close'].rolling(window=20).mean()
df['SMA50'] = df['Close'].rolling(window=50).mean()

# 绘制价格和均线
plt.figure(figsize=(14, 6))
plt.plot(df.index, df['Close'], label='收盘价', linewidth=2)
plt.plot(df.index, df['SMA20'], label='20日均线', alpha=0.7)
plt.plot(df.index, df['SMA50'], label='50日均线', alpha=0.7)
plt.title('AAPL 价格与移动平均线')
plt.xlabel('日期')
plt.ylabel('价格')
plt.legend()
plt.grid(True, alpha=0.3)
plt.show()
```

---

## 策略开发工作流

### 策略模板

在 Jupyter 中，可以分步骤开发策略：

```python
class StrategyTemplate(bt.Strategy):
    """策略开发模板"""

    # 1. 定义参数
    params = (
        ('entry_period', 20),
        ('exit_period', 10),
        ('stop_loss', 0.02),  # 2% 止损
    )

    # 2. 初始化
    def __init__(self):
        # 指标
        self.entry_ma = bt.indicators.SMA(self.data.close, period=self.p.entry_period)
        self.exit_ma = bt.indicators.SMA(self.data.close, period=self.p.exit_period)
        self.crossover = bt.indicators.CrossOver(self.data.close, self.entry_ma)

        # 状态变量
        self.order = None
        self.entry_price = None

    # 3. 订单通知
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.entry_price = order.executed.price
                print(f'买入: {order.executed.price:.2f}, 数量: {order.executed.size}')
            else:
                print(f'卖出: {order.executed.price:.2f}, 数量: {order.executed.size}')

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print('订单取消/保证金不足/拒绝')

        self.order = None

    # 4. 交易通知
    def notify_trade(self, trade):
        if trade.isclosed:
            print(f'交易利润: {trade.pnl:.2f}, 净利润: {trade.pnlcomm:.2f}')

    # 5. 主逻辑
    def next(self):
        # 等待当前订单完成
        if self.order:
            return

        # 没有持仓时寻找入场机会
        if not self.position:
            if self.crossover > 0:  # 金叉
                self.order = self.buy()
        else:
            # 止损检查
            if self.data.close[0] < self.entry_price * (1 - self.p.stop_loss):
                self.order = self.close()
            # 止盈检查
            elif self.data.close[0] < self.exit_ma[0]:
                self.order = self.sell()
```

### 在笔记本中测试策略

```python
# 创建测试函数
def run_strategy(data, strategy_class, cash=10000, **kwargs):
    """运行策略并返回结果"""
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(strategy_class, **kwargs)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.001)  # 0.1% 手续费

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    print(f'初始资金: {cash:.2f}')
    results = cerebro.run()
    strat = results[0]

    print(f'最终资金: {cerebro.broker.getvalue():.2f}')
    print(f'总收益率: {(cerebro.broker.getvalue() / cash - 1) * 100:.2f}%')

    # 打印分析结果
    print('\n=== 性能指标 ===')
    print(f"夏普比率: {strat.analyzers.sharpe.get_analysis().get('sharperatio', 'N/A')}")

    drawdown = strat.analyzers.drawdown.get_analysis()
    print(f"最大回撤: {drawdown.get('max', {}).get('drawdown', 0):.2f}%")

    trades = strat.analyzers.trades.get_analysis()
    if trades:
        print(f"交易次数: {trades.get('total', {}).get('total', 0)}")
        print(f"胜率: {trades.get('won', {}).get('total', 0) / trades.get('total', {}).get('total', 1) * 100:.2f}%")

    return cerebro, strat

# 运行测试
cerebro, strategy = run_strategy(
    data,
    StrategyTemplate,
    entry_period=20,
    exit_period=10,
    stop_loss=0.02
)
```

---

## 可视化与绘图

### 使用 Matplotlib 绘图

```python
# 基本绘图
%matplotlib inline

fig = cerebro.plot(style='candlestick', barup='red', bardown='green')[0][0]
fig.set_size_inches(14, 8)
```

### 使用 Plotly 交互式绘图

```python
# Plotly 提供更好的交互体验
import plotly.graph_objects as go
from backtrader.plot import PlotScheme

# 创建 Plotly 图表
def plot_backtrader_results(cerebro, title='回测结果'):
    """使用 Plotly 绘制回测结果"""

    # 获取数据
    strat = cerebro.run()[0]

    # 提取数据
    dates = [d.datetime.date(0) for d in strat.data]
    closes = [d.close[0] for d in strat.data]

    # 创建图表
    fig = go.Figure()

    # 添加 K 线图
    fig.add_trace(go.Candlestick(
        x=dates,
        open=[d.open[0] for d in strat.data],
        high=[d.high[0] for d in strat.data],
        low=[d.low[0] for d in strat.data],
        close=closes,
        name='K线'
    ))

    # 添加移动平均线
    if hasattr(strat, 'entry_ma'):
        fig.add_trace(go.Scatter(
            x=dates,
            y=[strat.entry_ma[i] for i in range(len(dates))],
            mode='lines',
            name='入场均线',
            line=dict(color='blue', width=1)
        ))

    fig.update_layout(
        title=title,
        xaxis_title='日期',
        yaxis_title='价格',
        template='plotly_dark',
        height=600
    )

    fig.show()

# 使用示例
plot_backtrader_results(cerebro, 'SMA 交叉策略回测')
```

### 自定义可视化

```python
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

def plot_custom_results(cerebro, strategy):
    """自定义回测结果可视化"""

    # 获取数据
    data = strategy.data
    dates = [data.datetime.date(i) for i in range(len(data))]

    # 创建子图
    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

    # 1. 价格和指标
    axes[0].plot(dates, [data.close[i] for i in range(len(data))],
                 label='收盘价', linewidth=2)
    if hasattr(strategy, 'entry_ma'):
        axes[0].plot(dates, [strategy.entry_ma[i] for i in range(len(dates))],
                     label=f'入场MA({strategy.p.entry_period})', alpha=0.7)
    if hasattr(strategy, 'exit_ma'):
        axes[0].plot(dates, [strategy.exit_ma[i] for i in range(len(dates))],
                     label=f'出场MA({strategy.p.exit_period})', alpha=0.7)
    axes[0].set_ylabel('价格')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[0].set_title('策略价格走势')

    # 2. 持仓情况
    if hasattr(strategy, '_orders'):
        axes[1].plot(dates, strategy._position_history, label='持仓', color='orange')
    axes[1].set_ylabel('持仓数量')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)
    axes[1].set_title('持仓变化')

    # 3. 累计收益
    if hasattr(strategy, '_value_history'):
        axes[2].plot(dates, strategy._value_history, label='账户价值', color='green')
        axes[2].axhline(y=10000, color='r', linestyle='--', label='初始资金')
    axes[2].set_ylabel('账户价值')
    axes[2].set_xlabel('日期')
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)
    axes[2].set_title('账户价值变化')

    plt.tight_layout()
    plt.show()

# 使用示例
plot_custom_results(cerebro, strategy)
```

### 收益曲线可视化

```python
def plot_returns_curve(strategy):
    """绘制收益曲线"""

    # 获取收益率分析
    returns = strategy.analyzers.returns.get_analysis()

    # 提取月度收益
    if 'rtot' in returns:
        total_return = returns['rtot'] * 100
        print(f'总收益率: {total_return:.2f}%')

    if 'ravg' in returns:
        avg_return = returns['ravg'] * 100
        print(f'平均收益率: {avg_return:.4f}%')

    # 绘制累计收益曲线（需要从策略中收集）
    fig, ax = plt.subplots(figsize=(14, 6))

    # 这里需要在策略中记录每日收益
    # 示例代码
    ax.plot(strategy._dates, strategy._returns, label='累计收益', linewidth=2)
    ax.axhline(y=0, color='r', linestyle='--', alpha=0.5)
    ax.set_xlabel('日期')
    ax.set_ylabel('累计收益率 (%)')
    ax.set_title('策略累计收益曲线')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()
```

---

## 参数敏感性分析

### 使用 ipywidgets 交互式参数调整

```python
from ipywidgets import interact, IntSlider, FloatSlider
import ipywidgets as widgets

# 创建交互式参数调整函数
def interactive_backtest(ma_period=20, stop_loss=0.02):
    """交互式回测"""

    # 创建策略
    class TestStrategy(bt.Strategy):
        params = (
            ('ma_period', ma_period),
            ('stop_loss', stop_loss),
        )

        def __init__(self):
            self.ma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
            self.crossover = bt.indicators.CrossOver(self.data.close, self.ma)
            self.entry_price = None

        def next(self):
            if not self.position:
                if self.crossover > 0:
                    self.buy()
                    self.entry_price = self.data.close[0]
            else:
                if self.data.close[0] < self.entry_price * (1 - self.p.stop_loss):
                    self.close()
                elif self.crossover < 0:
                    self.close()

    # 运行回测
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(TestStrategy)
    cerebro.broker.setcash(10000)
    cerebro.broker.setcommission(commission=0.001)

    results = cerebro.run()
    final_value = cerebro.broker.getvalue()

    # 显示结果
    print(f'MA周期: {ma_period}')
    print(f'止损: {stop_loss * 100:.1f}%')
    print(f'最终资金: {final_value:.2f}')
    print(f'收益率: {(final_value / 10000 - 1) * 100:.2f}%')

    return cerebro

# 创建交互式控件
interact(
    interactive_backtest,
    ma_period=IntSlider(min=5, max=50, step=1, value=20, description='MA周期'),
    stop_loss=FloatSlider(min=0.01, max=0.1, step=0.01, value=0.02, description='止损')
)
```

### 参数网格搜索

```python
import pandas as pd
from itertools import product

def parameter_grid_search(data, strategy_class, param_grid, cash=10000):
    """参数网格搜索"""

    # 生成所有参数组合
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())
    all_combinations = list(product(*param_values))

    results = []

    print(f'开始参数搜索，共 {len(all_combinations)} 种组合...')

    for i, combination in enumerate(all_combinations):
        # 创建参数字典
        params = dict(zip(param_names, combination))

        # 运行回测
        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(strategy_class, **params)
        cerebro.broker.setcash(cash)
        cerebro.broker.setcommission(commission=0.001)

        try:
            cerebro.run()
            final_value = cerebro.broker.getvalue()
            returns = (final_value / cash - 1) * 100

            results.append({
                **params,
                'final_value': final_value,
                'returns': returns
            })

        except Exception as e:
            print(f'参数组合 {params} 出错: {e}')
            results.append({
                **params,
                'final_value': 0,
                'returns': -100
            })

    # 转换为 DataFrame
    results_df = pd.DataFrame(results)

    # 按收益率排序
    results_df = results_df.sort_values('returns', ascending=False)

    return results_df

# 使用示例
param_grid = {
    'ma_period': [10, 20, 30, 40, 50],
    'stop_loss': [0.02, 0.05, 0.1]
}

results_df = parameter_grid_search(data, StrategyTemplate, param_grid)
print("\n最佳参数组合:")
print(results_df.head())
```

### 参数热力图

```python
import seaborn as sns

def plot_parameter_heatmap(results_df, param1, param2, metric='returns'):
    """绘制参数热力图"""

    # 创建透视表
    pivot_table = results_df.pivot_table(
        values=metric,
        index=param1,
        columns=param2,
        aggfunc='mean'
    )

    # 绘制热力图
    plt.figure(figsize=(10, 8))
    sns.heatmap(pivot_table, annot=True, fmt='.2f', cmap='RdYlGn', center=0)
    plt.title(f'{param1} vs {param2} 参数热力图')
    plt.xlabel(param2)
    plt.ylabel(param1)
    plt.show()

# 使用示例
plot_parameter_heatmap(results_df, 'ma_period', 'stop_loss')
```

### 参数优化曲线

```python
def plot_parameter_sensitivity(results_df, param_name):
    """绘制参数敏感性曲线"""

    # 按参数分组计算平均收益
    grouped = results_df.groupby(param_name)['returns'].agg(['mean', 'std', 'min', 'max'])

    # 绘制曲线
    fig, ax = plt.subplots(figsize=(12, 6))

    ax.plot(grouped.index, grouped['mean'], 'o-', label='平均收益', linewidth=2)
    ax.fill_between(grouped.index, grouped['min'], grouped['max'], alpha=0.3, label='收益范围')

    ax.set_xlabel(param_name)
    ax.set_ylabel('收益率 (%)')
    ax.set_title(f'{param_name} 参数敏感性分析')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.show()

# 使用示例
plot_parameter_sensitivity(results_df, 'ma_period')
```

---

## 多策略比较

### 同时运行多个策略

```python
def compare_strategies(data, strategies_dict, cash=10000):
    """比较多个策略"""

    results = {}

    for name, (strategy_class, params) in strategies_dict.items():
        print(f'运行策略: {name}')

        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(strategy_class, **params)
        cerebro.broker.setcash(cash)
        cerebro.broker.setcommission(commission=0.001)

        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe', timeframe=bt.TimeFrame.Days)
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

        strat_results = cerebro.run()
        strat = strat_results[0]

        # 收集结果
        results[name] = {
            'final_value': cerebro.broker.getvalue(),
            'returns': (cerebro.broker.getvalue() / cash - 1) * 100,
            'sharpe': strat.analyzers.sharpe.get_analysis().get('sharperatio', 0),
            'max_drawdown': strat.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0),
            'trades': strat.analyzers.trades.get_analysis().get('total', {}).get('total', 0),
            'won_trades': strat.analyzers.trades.get_analysis().get('won', {}).get('total', 0),
        }

    # 转换为 DataFrame
    results_df = pd.DataFrame(results).T
    results_df = results_df.sort_values('returns', ascending=False)

    return results_df

# 定义要比较的策略
strategies = {
    'SMA_10': (StrategyTemplate, {'entry_period': 10, 'exit_period': 5}),
    'SMA_20': (StrategyTemplate, {'entry_period': 20, 'exit_period': 10}),
    'SMA_30': (StrategyTemplate, {'entry_period': 30, 'exit_period': 15}),
    'SMA_50': (StrategyTemplate, {'entry_period': 50, 'exit_period': 20}),
}

# 运行比较
comparison = compare_strategies(data, strategies)
print("\n策略比较结果:")
print(comparison)
```

### 策略比较可视化

```python
def plot_strategy_comparison(results_df):
    """可视化策略比较结果"""

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # 1. 收益率比较
    ax1 = axes[0, 0]
    colors = ['green' if x > 0 else 'red' for x in results_df['returns']]
    ax1.bar(results_df.index, results_df['returns'], color=colors)
    ax1.set_ylabel('收益率 (%)')
    ax1.set_title('策略收益率比较')
    ax1.axhline(y=0, color='black', linestyle='--', alpha=0.5)
    ax1.tick_params(axis='x', rotation=45)

    # 2. 夏普比率比较
    ax2 = axes[0, 1]
    ax2.bar(results_df.index, results_df['sharpe'], color='steelblue')
    ax2.set_ylabel('夏普比率')
    ax2.set_title('夏普比率比较')
    ax2.axhline(y=1, color='orange', linestyle='--', label='基准线')
    ax2.legend()
    ax2.tick_params(axis='x', rotation=45)

    # 3. 最大回撤比较
    ax3 = axes[1, 0]
    ax3.bar(results_df.index, results_df['max_drawdown'], color='crimson')
    ax3.set_ylabel('最大回撤 (%)')
    ax3.set_title('最大回撤比较')
    ax3.tick_params(axis='x', rotation=45)

    # 4. 交易次数比较
    ax4 = axes[1, 1]
    trades = results_df['trades']
    won = results_df['won_trades']
    ax4.bar(results_df.index, trades, label='总交易', color='steelblue', alpha=0.7)
    ax4.bar(results_df.index, won, label='盈利交易', color='green', alpha=0.7)
    ax4.set_ylabel('交易次数')
    ax4.set_title('交易次数比较')
    ax4.legend()
    ax4.tick_params(axis='x', rotation=45)

    plt.tight_layout()
    plt.show()

# 使用示例
plot_strategy_comparison(comparison)
```

### 累计收益曲线比较

```python
def plot_equity_curves(data, strategies_dict, cash=10000):
    """绘制多个策略的累计收益曲线"""

    plt.figure(figsize=(14, 8))

    for name, (strategy_class, params) in strategies_dict.items():
        # 修改策略以记录每日价值
        class EquityStrategy(strategy_class):
            def __init__(self):
                super().__init__()
                self.equity_curve = []

            def next(self):
                super().next()
                self.equity_curve.append(self.broker.getvalue())

        cerebro = bt.Cerebro()
        cerebro.adddata(data)
        cerebro.addstrategy(EquityStrategy, **params)
        cerebro.broker.setcash(cash)
        cerebro.broker.setcommission(commission=0.001)

        strat = cerebro.run()[0]

        # 获取日期
        dates = [data.datetime.date(i) for i in range(len(data))[:len(strat.equity_curve)]]

        # 绘制曲线
        plt.plot(dates, strat.equity_curve, label=name, linewidth=2)

    plt.axhline(y=cash, color='black', linestyle='--', alpha=0.5, label='初始资金')
    plt.xlabel('日期')
    plt.ylabel('账户价值')
    plt.title('策略累计收益曲线比较')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()

# 使用示例
plot_equity_curves(data, strategies)
```

---

## 实时数据监控

### 使用 CCXT 实时数据

```python
# 注意：需要安装 ccxt
# pip install ccxt

class LiveStrategy(bt.Strategy):
    """实时交易策略"""

    params = (
        ('symbol', 'BTC/USDT'),
        ('interval', '1h'),
    )

    def __init__(self):
        self.ma = bt.indicators.SMA(self.data.close, period=20)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

    def next(self):
        # 只在有足够数据时交易
        if len(self.data) < 20:
            return

        # 实时监控逻辑
        if not self.position:
            if self.data.close[0] > self.ma[0] and self.rsi[0] < 70:
                self.buy(size=0.01)  # 小仓位测试
        else:
            if self.rsi[0] > 70 or self.data.close[0] < self.ma[0]:
                self.sell(size=self.position.size)

# 实时数据存储
from backtrader.stores import CCXTStore

# 创建实时数据源
store = CCXTStore(
    exchange='binance',
    currency='USDT',
    config={'apiKey': 'your_api_key', 'secret': 'your_secret'},
    retries=5,
    debug=False
)

# 实时数据 feed
data = store.getdata(
    dataname='BTC/USDT',
    name='BTCUSDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=60,
    ohlcv_limit=100,
    drop_newest=True
)

# 注意：实时交易需要谨慎，建议先在测试网测试
```

### 模拟实时数据流

```python
import time
from IPython.display import clear_output

class MonitoringStrategy(bt.Strategy):
    """带监控功能的策略"""

    def __init__(self):
        self.ma = bt.indicators.SMA(self.data.close, period=20)
        self.data_close = self.data.close
        self.data_datetime = self.data.datetime

    def next(self):
        # 每10个bar输出一次状态
        if len(self.data) % 10 == 0:
            clear_output(wait=True)

            current_time = self.data_datetime.datetime(0)
            current_price = self.data_close[0]
            current_ma = self.ma[0]

            print(f'时间: {current_time}')
            print(f'价格: {current_price:.2f}')
            print(f'MA20: {current_ma:.2f}')
            print(f'持仓: {self.position.size}')
            print(f'账户价值: {self.broker.getvalue():.2f}')

            # 绘制简单的价格图
            prices = [self.data_close[-i] for i in range(min(50, len(self.data)))]
            plt.figure(figsize=(10, 3))
            plt.plot(prices[-20:], 'o-')
            plt.title(f'最近价格 (当前: {current_price:.2f})')
            plt.grid(True, alpha=0.3)
            plt.show()

# 在笔记本中运行（需要数据流支持）
# cerebro = bt.Cerebro()
# cerebro.adddata(live_data)
# cerebro.addstrategy(MonitoringStrategy)
# cerebro.run()
```

---

## 结果导出与报告

### 导出交易记录

```python
def export_trades(cerebro, strategy, filename='trades.csv'):
    """导出交易记录到 CSV"""

    # 获取交易分析器结果
    trade_analysis = strategy.analyzers.trades.get_analysis()

    if not trade_analysis or 'total' not in trade_analysis:
        print('没有交易记录')
        return

    # 创建交易记录列表
    trades_list = []

    # 从策略中获取交易详情
    if hasattr(strategy, '_trades'):
        for trade in strategy._trades:
            trades_list.append({
                'entry_date': trade.entry_date,
                'exit_date': trade.exit_date,
                'entry_price': trade.entry_price,
                'exit_price': trade.exit_price,
                'size': trade.size,
                'pnl': trade.pnl,
                'pnl_net': trade.pnlcomm,
            })

    # 转换为 DataFrame
    df = pd.DataFrame(trades_list)

    # 导出
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f'交易记录已导出到: {filename}')

    return df

# 使用示例
trades_df = export_trades(cerebro, strategy)
print(trades_df.head())
```

### 导出性能报告

```python
def export_performance_report(strategy, filename='performance_report.xlsx'):
    """导出性能报告到 Excel"""

    # 获取所有分析器结果
    sharpe = strategy.analyzers.sharpe.get_analysis()
    drawdown = strategy.analyzers.drawdown.get_analysis()
    returns = strategy.analyzers.returns.get_analysis()
    trades = strategy.analyzers.trades.get_analysis()

    # 创建 Excel writer
    with pd.ExcelWriter(filename, engine='openpyxl') as writer:

        # 1. 摘要页
        summary_data = {
            '指标': ['总收益率', '年化收益率', '夏普比率', '最大回撤', '交易次数', '胜率'],
            '值': [
                f"{returns.get('rtot', 0) * 100:.2f}%",
                f"{returns.get('ravg', 0) * 100 * 252:.2f}%",  # 假设年化
                f"{sharpe.get('sharperatio', 0):.4f}",
                f"{drawdown.get('max', {}).get('drawdown', 0):.2f}%",
                trades.get('total', {}).get('total', 0),
                f"{trades.get('won', {}).get('total', 0) / max(trades.get('total', {}).get('total', 1), 1) * 100:.2f}%"
            ]
        }
        summary_df = pd.DataFrame(summary_data)
        summary_df.to_excel(writer, sheet_name='摘要', index=False)

        # 2. 回撤分析
        if 'drawdowns' in drawdown:
            dd_data = []
            for dd in drawdown['drawdowns']:
                dd_data.append({
                    '日期': dd.get('date', ''),
                    '回撤': f"{dd.get('drawdown', 0):.2f}%",
                    '持续天数': dd.get('len', 0)
                })
            dd_df = pd.DataFrame(dd_data)
            dd_df.to_excel(writer, sheet_name='回撤分析', index=False)

        # 3. 月度收益
        if 'rmonth' in returns:
            monthly_data = []
            for month, ret in returns['rmonth'].items():
                monthly_data.append({
                    '月份': month,
                    '收益率': f"{ret * 100:.2f}%"
                })
            monthly_df = pd.DataFrame(monthly_data)
            monthly_df.to_excel(writer, sheet_name='月度收益', index=False)

    print(f'性能报告已导出到: {filename}')

# 使用示例
export_performance_report(strategy)
```

### 生成 HTML 报告

```python
from IPython.display import HTML

def generate_html_report(cerebro, strategy, template='report_template.html'):
    """生成 HTML 格式的报告"""

    # 获取分析结果
    sharpe = strategy.analyzers.sharpe.get_analysis().get('sharperatio', 0)
    drawdown = strategy.analyzers.drawdown.get_analysis().get('max', {}).get('drawdown', 0)
    returns = strategy.analyzers.returns.get_analysis()

    # 创建 HTML 报告
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Backtrader 回测报告</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            .header {{ background: #2c3e50; color: white; padding: 20px; }}
            .metrics {{ display: flex; flex-wrap: wrap; gap: 20px; margin: 20px 0; }}
            .metric-card {{ background: #ecf0f1; padding: 15px; border-radius: 5px; flex: 1; min-width: 200px; }}
            .metric-value {{ font-size: 24px; font-weight: bold; color: #2c3e50; }}
            .metric-label {{ color: #7f8c8d; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Backtrader 回测报告</h1>
            <p>生成时间: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>

        <div class="metrics">
            <div class="metric-card">
                <div class="metric-label">总收益率</div>
                <div class="metric-value">{returns.get('rtot', 0) * 100:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">夏普比率</div>
                <div class="metric-value">{sharpe:.4f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value">{drawdown:.2f}%</div>
            </div>
        </div>

        <h2>详细分析</h2>
        <p>这里可以添加更多详细信息...</p>
    </body>
    </html>
    """

    return HTML(html_template)

# 使用示例
html_report = generate_html_report(cerebro, strategy)
display(html_report)
```

---

## 最佳实践

### 笔记本组织结构

推荐的组织结构：

```python
# %% [markdown]
# # 策略回测笔记本
#
# ## 1. 导入和设置
# ## 2. 数据加载
# ## 3. 策略定义
# ## 4. 回测执行
# ## 5. 结果分析
# ## 6. 参数优化

# %%
# 1. 导入和设置
import backtrader as bt
import pandas as pd
import matplotlib.pyplot as plt
%matplotlib inline

# %%
# 2. 数据加载
# 数据加载代码...

# %%
# 3. 策略定义
class MyStrategy(bt.Strategy):
    pass

# %%
# 4. 回测执行
# 回测代码...
```

### 性能优化技巧

```python
# 1. 使用 preload 选项
cerebro = bt.Cerebro(preload=True)  # 默认开启，预加载数据到内存

# 2. 使用 runonce 优化
cerebro.run(runonce=True)  # 批量处理，更快

# 3. 减少输出
class QuietStrategy(bt.Strategy):
    def __init__(self):
        self.verbose = False  # 控制输出

    def log(self, txt):
        if self.verbose:
            print(txt)

# 4. 使用缓存
class CachedStrategy(bt.Strategy):
    def __init__(self):
        self.close = self.data.close  # 缓存引用
        self.ma = bt.indicators.SMA(self.close, period=20)  # 只计算一次
```

### 调试技巧

```python
# 使用调试模式
class DebugStrategy(bt.Strategy):
    def __init__(self):
        self._debug = True

    def log(self, txt):
        if self._debug:
            dt = self.data.datetime.date(0)
            print(f'{dt} {txt}')

    def next(self):
        self.log(f'Close: {self.data.close[0]:.2f}')
        self.log(f'MA: {self.ma[0]:.2f}')
        self.log(f'Position: {self.position.size}')
```

### 策略版本管理

```python
# 在笔记本中保存策略版本
import pickle

def save_strategy(strategy, filename):
    """保存策略对象"""
    with open(filename, 'wb') as f:
        pickle.dump(strategy, f)

def load_strategy(filename):
    """加载策略对象"""
    with open(filename, 'rb') as f:
        return pickle.load(f)

# 保存回测结果
def save_backtest_results(cerebro, strategy, name):
    """保存回测结果"""
    results = {
        'strategy_name': name,
        'final_value': cerebro.broker.getvalue(),
        'returns': (cerebro.broker.getvalue() / 10000 - 1) * 100,
        'sharpe': strategy.analyzers.sharpe.get_analysis().get('sharperatio', 0),
    }

    with open(f'{name}_results.pkl', 'wb') as f:
        pickle.dump(results, f)
```

---

## 总结

Jupyter Notebook 是一个强大的 Backtrader 开发环境，提供：

1. **交互式开发**：快速迭代和测试策略
2. **可视化分析**：丰富的图表展示
3. **参数优化**：交互式参数调整
4. **多策略比较**：并排对比不同策略
5. **结果导出**：多种格式输出

### 下一步

- 探索更多指标：[指标系统](../opts/user_guide/indicators.md)
- 学习高级策略：[策略开发指南](../opts/user_guide/strategies.md)
- 了解数据源：[数据源配置](../opts/user_guide/data_feeds.md)
- 参数优化：[参数优化指南](../opts/user_guide/optimization.md)

### 参考资源

- [Backtrader 官方文档](https://www.backtrader.com/docu/)
- [Plotly 文档](https://plotly.com/python/)
- [ipywidgets 文档](https://ipywidgets.readthedocs.io/)
