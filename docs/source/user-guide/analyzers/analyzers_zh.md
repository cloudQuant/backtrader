---
title: 分析器
description: 策略性能分析

---
# 分析器

分析器计算策略的性能指标。使用它们来评估策略效果。

## 基本用法

```python
cerebro = bt.Cerebro()

# 添加分析器

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

# 运行回测

strats = cerebro.run()

# 获取分析器结果

strat = strats[0]
sharpe = strat.analyzers.sharpe.get_analysis()
print(f'夏普比率: {sharpe["sharperatio"]:.3f}')

```

## 可用分析器

### 收益分析

```python

# Returns (基本收益指标)

cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

# 年度收益

cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual_return')

# 对数收益 (滚动)

cerebro.addanalyzer(bt.analyzers.LogReturnsRolling, _name='log_returns')

```

### 风险指标

```python

# 夏普比率

cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')

# 卡玛比率

cerebro.addanalyzer(bt.analyzers.Calmar, _name='calmar')

# SQN (系统质量数)

cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

```

### 回撤分析

```python

# 回撤分析器

cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')

# 获取结果

drawdown = strat.analyzers.drawdown.get_analysis()
print(f'最大回撤: {drawdown["max"]["drawdown"]:.2%}')
print(f'最大回撤金额: {drawdown["max"]["moneydown"]:.2f}')
print(f'最大回撤持续: {drawdown["max"]["len"]} 天')

```

### 交易分析

```python

# 交易分析器

cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# 获取结果

trades = strat.analyzers.trades.get_analysis()
print(f'总交易次数: {trades["total"]["total"]}')
print(f'胜率: {trades["won"]["total"] / trades["total"]["total"]:.2%}')
print(f'平均盈利: {trades["won"]["pnl"]["average"]:.2f}')
print(f'平均亏损: {trades["lost"]["pnl"]["average"]:.2f}')

```

### 持仓分析

```python

# 持仓分析器

cerebro.addanalyzer(bt.analyzers.Positions, _name='positions')

# 获取结果

positions = strat.analyzers.positions.get_analysis()
print(f'总持仓数: {len(positions)}')

```

### 成交分析

```python

# 成交分析器

cerebro.addanalyzer(bt.analyzers.Transactions, _name='transactions')

# 获取结果

transactions = strat.analyzers.transactions.get_analysis()
print(f'总成交数: {len(transactions)}')

```

### 周期统计

```python

# 周期统计 (月度、年度等)

cerebro.addanalyzer(bt.analyzers.PeriodStats, _name='period_stats')

# 获取结果

stats = strat.analyzers.period_stats.get_analysis()

```

### 时间收益分析

```python

# 时间收益 (按时间段统计)

cerebro.addanalyzer(bt.analyzers.TimeReturn, _name='time_return')

# 获取结果

time_return = strat.analyzers.time_return.get_analysis()

```

### VWR (成交量加权收益)

```python

# 成交量加权收益

cerebro.addanalyzer(bt.analyzers.VWR, _name='vwr')

# 获取结果

vwr = strat.analyzers.vwr.get_analysis()

```

### PyFolio 集成

```python

# PyFolio 集成用于高级分析

cerebro.addanalyzer(bt.analyzers.PyFolio, _name='pyfolio')

# 获取结果

pyfolio = strat.analyzers.pyfolio.get_analysis()

# 生成 pyfolio 报表

returns, positions, transactions, gross_lev = pyfolio

```

## 完整示例

```python
import backtrader as bt
import datetime

class TestStrategy(bt.Strategy):
    pass

# 创建 cerebro

cerebro = bt.Cerebro()

# 添加策略

cerebro.addstrategy(TestStrategy)

# 添加数据

data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime.datetime(2023, 1, 1),
    todate=datetime.datetime(2023, 12, 31)
)
cerebro.adddata(data)

# 添加分析器

cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name='annual_return')

# 设置经纪人

cerebro.broker.setcash(10000)
cerebro.broker.setcommission(0.001)

# 运行

strats = cerebro.run()
strat = strats[0]

# 打印结果

print('-' *50)
print('分析结果')
print('-'*50)

# 收益

returns = strat.analyzers.returns.get_analysis()
print(f'总收益: {returns["rtot"]:.2%}')
print(f'平均收益: {returns["ravg"]:.2%}')

# 夏普比率

sharpe = strat.analyzers.sharpe.get_analysis()
print(f'夏普比率: {sharpe["sharperatio"]:.3f}')

# 回撤

drawdown = strat.analyzers.drawdown.get_analysis()
print(f'最大回撤: {drawdown["max"]["drawdown"]:.2%}')
print(f'最大回撤持续: {drawdown["max"]["len"]} 天')

# 交易

trades = strat.analyzers.trades.get_analysis()
print(f'总交易次数: {trades["total"]["total"]}')
if trades["total"]["total"] > 0:
    print(f'胜率: {trades["won"]["total"] / trades["total"]["total"]:.2%}')

# 年度收益

annual_return = strat.analyzers.annual_return.get_analysis()
print(f'年化收益: {annual_return.get("rnorm", 0):.2%}')

print('-'* 50)
print(f'最终组合价值: {cerebro.broker.getvalue():.2f}')

```

## 分析器输出格式

大多数分析器返回包含分析结果的字典：

```python
analyzer = strat.analyzers.name.get_analysis()

# 常见访问模式

for key, value in analyzer.items():
    print(f'{key}: {value}')

```

## 自定义分析器

创建您自己的分析器：

```python
class CustomAnalyzer(bt.Analyzer):
    """
    自定义分析器示例。
    """

    def __init__(self):
        super().__init__()
        self.trades = []
        self.start_cash = None

    def start(self):
        self.start_cash = self.strategy.broker.getcash()

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'pnl': trade.pnl,
                'pnlnet': trade.pnlnet,
                'commission': trade.commission,
            })

    def get_analysis(self):
        return {
            'start_cash': self.start_cash,
            'total_trades': len(self.trades),
            'total_pnl': sum(t['pnl'] for t in self.trades),
            'total_commission': sum(t['commission'] for t in self.trades),
        }

```

## 下一步学习

- [观察器](observers_zh.md) - 监控策略行为
- [绘图](plotting_zh.md) - 可视化结果
