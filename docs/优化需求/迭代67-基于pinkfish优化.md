### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/pinkfish
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### pinkfish项目简介
pinkfish是一个专注于投资组合分析的回测框架，具有以下核心特点：
- **组合分析**: 专注于投资组合级别的分析
- **简洁设计**: 代码结构简单清晰
- **Pandas集成**: 深度集成pandas数据处理
- **基准对比**: 内置基准对比功能
- **日历管理**: 交易日历管理
- **装饰器模式**: 技术指标装饰器

### 重点借鉴方向
1. **组合管理**: Portfolio组合管理设计
2. **基准对比**: Benchmark基准对比
3. **交易日志**: TradeLog交易日志系统
4. **性能指标**: 完善的性能指标计算
5. **数据获取**: 简洁的数据获取接口
6. **日历系统**: 灵活的交易日历管理

---

## 一、项目对比分析

### 1.1 pinkfish 核心特性

| 特性 | 描述 |
|------|------|
| **Portfolio 类** | 多资产组合管理，支持权重调整和再平衡 |
| **TradeLog 类** | 单资产交易记录，支持多头/空头和保证金 |
| **Benchmark 类** | 等权重基准策略，年度再平衡 |
| **pfstatistics** | 80+ 性能指标计算 |
| **技术指标装饰器** | `@technical_indicator` 装饰器模式 |
| **日历系统** | 支持股票日历和连续日历 |
| **数据缓存** | CSV 缓存机制 |

### 1.2 backtrader 现有能力对比

| 能力 | backtrader | pinkfish | 差距 |
|------|-----------|----------|------|
| **组合管理** | 通过多数据源实现 | 原生 Portfolio 类 | pinkfish 更便捷 |
| **交易日志** | 内置但分散 | 专门的 TradeLog 类 | pinkfish 更系统 |
| **性能指标** | Analyzers 系统 | 80+ 统一指标 | pinkfish 更全面 |
| **基准对比** | 需手动实现 | 内置 Benchmark 类 | pinkfish 更直接 |
| **日历系统** | 部分支持 | 完整日历管理 | pinkfish 更完善 |
| **数据缓存** | 需自己实现 | 内置 CSV 缓存 | pinkfish 更方便 |

### 1.3 差距分析

| 方面 | pinkfish | backtrader | 差距 |
|------|----------|-----------|------|
| **组合权重管理** | `adjust_percent()` 批量调整 | 需手动计算 | backtrader 可借鉴 |
| **交易日志** | 完整的交易配对记录 | 分散在 broker 中 | backtrader 可改进 |
| **性能指标** | 统一的 `stats()` 函数 | 多个 Analyzer 类 | 各有优势 |
| **装饰器模式** | 技术指标装饰器 | 无 | backtrader 可添加 |
| **日历管理** | 灵活的日历切换 | 较固定 | backtrader 可增强 |

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 增强的组合管理
更便捷的多资产组合管理：

- **FR1.1**: PortfolioMixin - 组合管理混入类
- **FR1.2**: `adjust_percent()` - 按权重调整仓位
- **FR1.3**: `adjust_percents()` - 批量权重调整
- **FR1.4**: `rebalance()` - 定期再平衡功能

#### FR2: 统一的交易日志
完整的交易记录和配对系统：

- **FR2.1**: TradeLog 类 - 交易日志管理
- **FR2.2**: 交易配对 - 开仓/平仓自动配对
- **FR2.3**: `get_log()` - 获取交易日志 DataFrame
- **FR2.4**: `merge_trades` - 合并同日交易

#### FR3: 增强的性能指标
更全面的回测性能分析：

- **FR3.1**: Expected Shortfall - 尾部风险指标
- **FR3.2**: 滚动回撤/上涨 - 周期性指标
- **FR3.3**: 时间在市占比 - 市场参与度
- **FR3.4**: 连续盈亏统计 - 最长连续记录

#### FR4: 技术指标装饰器
简化技术指标添加：

- **FR4.1**: `@technical_indicator` 装饰器
- **FR4.2**: 自动列命名
- **FR4.3**: 多符号批量添加

### 2.2 非功能需求

- **NFR1**: 性能 - 不影响回测速度
- **NFR2**: 兼容性 - 与现有 backtrader API 兼容
- **NFR3**: 可选性 - 所有新功能为可选
- **NFR4**: 简洁性 - API 简单易用

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为量化研究员，我想使用便捷的权重调整方法管理组合，简化再平衡逻辑 | P0 |
| US2 | 作为分析师，我想获取完整的交易配对日志，便于分析每笔交易 | P0 |
| US3 | 作为风控经理，我想查看 Expected Shortfall 等风险指标 | P1 |
| US4 | 作为开发者，我想使用装饰器添加技术指标，提高代码可读性 | P1 |

---

## 三、设计文档

### 3.1 模块结构设计

```
backtrader/
├── portfolio/              # 新增组合管理模块
│   ├── __init__.py
│   ├── mixin.py            # PortfolioMixin 混入类
│   └── rebalance.py        # 再平衡策略
├── tradelog/               # 新增交易日志模块
│   ├── __init__.py
│   ├── tradelog.py         # TradeLog 类
│   └── dailybal.py         # DailyBal 类
├── indicators/             # 增强指标模块
│   ├── decorator.py        # 技术指标装饰器
│   └── ...
└── analyzers/              # 增强分析器
    ├── expected_shortfall.py
    └── rolling_stats.py
```

### 3.2 核心类设计

#### 3.2.1 PortfolioMixin

```python
"""
Portfolio Mixin for backtrader
参考：pinkfish/pinkfish/portfolio.py
"""
import backtrader as bt
from backtrader.utils.py3 import itemsrepr


class PortfolioMixin:
    """
    组合管理混入类

    为 Strategy 添加便捷的组合管理功能
    """

    def adjust_percent(self, data, weight, direction='long'):
        """
        调整单个数据到目标权重

        Args:
            data: 数据源
            weight: 目标权重 (0-1)
            direction: 'long' 或 'short'

        Returns:
            int: 调整的股数
        """
        if not (0 <= weight <= 1):
            raise ValueError(f'weight should be between 0 and 1, got {weight}')

        # 计算当前总资金
        total_value = self.broker.getvalue()
        cash = self.broker.getcash()

        # 计算目标价值
        target_value = total_value * weight
        current_value = self.getposition(data).size * data.close[0]

        # 计算需要调整的价值
        if direction == 'long':
            diff_value = target_value - current_value
        else:
            diff_value = -(target_value - current_value)

        # 计算股数
        shares = int(diff_value / data.close[0])

        # 执行交易
        if shares > 0:
            self.buy(data=data, size=shares)
        elif shares < 0:
            self.sell(data=data, size=-shares)

        return shares

    def adjust_percents(self, weights_dict, field='close'):
        """
        批量调整多个数据到目标权重

        Args:
            weights_dict: {data: weight} 字典
            field: 价格字段

        Returns:
            dict: 调整结果
        """
        # 验证权重总和
        total_weight = sum(weights_dict.values())
        if not (0 <= total_weight <= 1.01):  # 允许小误差
            raise ValueError(f'weights should sum to <= 1, got {total_weight}')

        results = {}

        # 获取当前权重
        current_weights = {}
        total_value = self.broker.getvalue()
        for data in weights_dict.keys():
            position = self.getposition(data)
            current_weights[data] = (
                position.size * getattr(data, field)[0] / total_value
                if total_value > 0 else 0
            )

        # 计算权重变化并排序（先卖出后买入）
        weight_changes = {}
        for data, target_weight in weights_dict.items():
            weight_changes[data] = target_weight - current_weights.get(data, 0)

        # 按变化排序（负值优先）
        sorted_items = sorted(weight_changes.items(),
                            key=lambda x: x[1])

        # 执行调整
        for data, change in sorted_items:
            if abs(change) < 0.0001:  # 忽略微小变化
                continue
            results[data] = self.adjust_percent(
                data,
                current_weights.get(data, 0) + change
            )

        return results

    def get_portfolio_weights(self, field='close'):
        """
        获取当前组合权重

        Returns:
            dict: {data: weight}
        """
        weights = {}
        total_value = self.broker.getvalue()

        for data in self.datas:
            position = self.getposition(data)
            if position.size != 0:
                weights[data] = (
                    position.size * getattr(data, field)[0] / total_value
                )

        return weights

    def print_holdings(self, show_percent=False):
        """
        打印当前持仓

        Args:
            show_percent: 显示百分比而非股数
        """
        date = self.data.datetime.date(0)
        print(f'{date.strftime("%Y-%m-%d")}', end=' ')

        if show_percent:
            weights = self.get_portfolio_weights()
            total = sum(weights.values())
            for data, weight in weights.items():
                print(f'{data._name}:{weight*100:4.1f}', end=' ')
            cash_weight = self.broker.getcash() / self.broker.getvalue()
            print(f'cash: {cash_weight*100:4.1f}', end=' ')
            print(f'total: {total*100:4.1f}')
        else:
            for data in self.datas:
                position = self.getposition(data)
                if position.size != 0:
                    print(f'{data._name}:{position.size:3}', end=' ')
            cash = self.broker.getcash()
            print(f'cash: {cash:8,.2f}', end=' ')
            print(f'total: {self.broker.getvalue():9,.2f}')


# 使用示例
class MyStrategy(bt.Strategy, PortfolioMixin):
    def __init__(self):
        # 初始化指标
        self.sma_short = bt.indicators.SMA(self.data0, period=20)
        self.sma_long = bt.indicators.SMA(self.data0, period=50)

    def next(self):
        # 金叉买入
        if bt.indicators.CrossOver(self.sma_short, self.sma_long) > 0:
            # 调整到 60% 仓位
            self.adjust_percent(self.data0, 0.6)

        # 死叉卖出
        elif bt.indicators.CrossOver(self.sma_short, self.sma_long) < 0:
            self.adjust_percent(self.data0, 0)

    def next(self):
        # 批量调整多个资产
        weights = {
            self.data0: 0.4,
            self.data1: 0.3,
            self.data2: 0.3
        }
        self.adjust_percents(weights)
```

#### 3.2.2 TradeLog 类

```python
"""
TradeLog for backtrader
参考：pinkfish/pinkfish/trade.py
"""
import pandas as pd
from backtrader.utils.py3 import with_metaclass


class Direction:
    """交易方向"""
    LONG, SHORT = ['LONG', 'SHRT']


class TradeLog:
    """
    交易日志管理类

    记录每笔交易的完整信息，支持交易配对
    """

    def __init__(self, strategy=None):
        """
        Args:
            strategy: backtrader Strategy 实例
        """
        self.strategy = strategy
        self._raw_trades = []  # 原始交易记录
        self._paired_trades = []  # 配对的交易
        self._open_trades = {}  # 未平仓交易 {data: [trades]}

    def record_trade(self, order):
        """
        记录交易

        Args:
            order: backtrader Order 对象
        """
        if order.status != order.Completed:
            return

        trade = {
            'date': self.strategy.data.datetime.date(0),
            'data': order.data,
            'price': order.executed.price,
            'size': order.executed.size,
            'value': order.executed.value,
            'commission': order.executed.comm,
            'type': 'buy' if order.isbuy() else 'sell'
        }

        self._raw_trades.append(trade)

    def pair_trades(self):
        """配对交易（先进先出）"""
        # 按数据源分组
        trades_by_data = {}
        for trade in self._raw_trades:
            data = trade['data']
            if data not in trades_by_data:
                trades_by_data[data] = []
            trades_by_data[data].append(trade)

        # 为每个数据源配对交易
        for data, trades in trades_by_data.items():
            open_trades = []
            for trade in trades:
                if trade['type'] == 'buy':
                    # 开仓
                    open_trades.append(trade)
                elif trade['type'] == 'sell' and open_trades:
                    # 平仓 - 配对
                    entry = open_trades.pop(0)
                    paired = self._create_pair(entry, trade)
                    self._paired_trades.append(paired)

    def _create_pair(self, entry, exit):
        """创建配对交易"""
        direction = Direction.LONG if entry['type'] == 'buy' else Direction.SHORT

        if direction == Direction.LONG:
            pl_points = exit['price'] - entry['price']
        else:
            pl_points = -(exit['price'] - entry['price'])

        pl_cash = pl_points * exit['size']
        pct_gain = pl_points / entry['price'] * 100

        return {
            'entry_date': entry['date'],
            'entry_price': entry['price'],
            'exit_date': exit['date'],
            'exit_price': exit['price'],
            'size': exit['size'],
            'pl_points': pl_points,
            'pl_cash': pl_cash,
            'pct_gain': pct_gain,
            'direction': direction,
            'commission': entry['commission'] + exit['commission']
        }

    def get_log(self, merge_trades=False):
        """
        获取交易日志

        Returns:
            pd.DataFrame: 交易日志
        """
        if not self._paired_trades:
            self.pair_trades()

        columns = [
            'entry_date', 'entry_price', 'exit_date', 'exit_price',
            'size', 'pl_points', 'pl_cash', 'pct_gain',
            'direction', 'commission'
        ]

        df = pd.DataFrame(self._paired_trades, columns=columns)

        if merge_trades and not df.empty:
            # 合并同日交易
            df = df.groupby(['entry_date', 'exit_date', 'direction']).agg({
                'entry_price': 'mean',
                'exit_price': 'mean',
                'size': 'sum',
                'pl_points': 'sum',
                'pl_cash': 'sum',
                'pct_gain': 'mean',
                'commission': 'sum'
            }).reset_index()

        return df

    def get_raw_log(self):
        """
        获取原始交易日志

        Returns:
            pd.DataFrame: 原始交易日志
        """
        columns = ['date', 'data', 'price', 'size', 'value', 'commission', 'type']
        df = pd.DataFrame(self._raw_trades, columns=columns)
        df['data'] = df['data'].apply(lambda x: x._name if hasattr(x, '_name') else str(x))
        return df


# Strategy 中使用 TradeLog
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.tradelog = TradeLog(self)

    def notify_order(self, order):
        if order.status == order.Completed:
            self.tradelog.record_trade(order)

    def stop(self):
        # 获取交易日志
        tlog = self.tradelog.get_log()
        print("\n交易日志:")
        print(tlog)
```

#### 3.2.3 技术指标装饰器

```python
"""
Technical Indicator Decorator
参考：pinkfish/pinkfish/portfolio.py
"""
from functools import wraps
import pandas as pd
import backtrader as bt


def technical_indicator(output_column_suffix, input_column_suffix='close'):
    """
    技术指标装饰器

    为多个数据源批量添加技术指标

    Args:
        output_column_suffix: 输出列后缀
        input_column_suffix: 输入列后缀 (默认 'close')

    Example:
        @technical_indicator('MA30')
        def sma30(self, data, input_column=None):
            return bt.indicators.SMA(data, period=30)

        # 自动为每个 data 添加 MA30 列
        # data0_MA30, data1_MA30, ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            # 获取所有数据源
            datas = self.datas if hasattr(self, 'datas') else [self.data]

            indicators = {}
            for data in datas:
                # 调用原函数获取指标
                indicator = func(self, data, **kwargs)
                # 存储指标
                name = f"{data._name}_{output_column_suffix}"
                indicators[name] = indicator
                # 添加到策略属性
                setattr(self, name.replace('.', '_'), indicator)

            return indicators

        return wrapper
    return decorator


# 使用示例
class MyStrategy(bt.Strategy):
    def __init__(self):
        # 使用装饰器批量添加指标
        self._add_indicators()

    @technical_indicator('SMA20')
    def _sma20(self, data, input_column=None):
        return bt.indicators.SMA(data.close, period=20)

    @technical_indicator('SMA50')
    def _sma50(self, data, input_column=None):
        return bt.indicators.SMA(data.close, period=50)

    @technical_indicator('RSI')
    def _rsi(self, data, input_column=None):
        return bt.indicators.RSI(data.close, period=14)

    def next(self):
        # 直接使用装饰器添加的指标
        if self.data0_SMA20[0] > self.data0_SMA50[0]:
            self.buy(data=self.data0)
```

### 3.3 增强的性能分析器

```python
"""
Enhanced Analyzers
"""
import backtrader as bt
import numpy as np


class ExpectedShortfall(bt.Analyzer):
    """
    Expected Shortfall (ES) 分析器

    计算尾部风险（最坏5%情况下的平均损失）
    """

    def __init__(self):
        self.returns = []

    def next(self):
        # 计算日收益率
        if len(self.strategy.data) > 1:
            prev_value = self.strategy.broker.getvalue(-1)
            curr_value = self.strategy.broker.getvalue()
            ret = (curr_value - prev_value) / prev_value
            self.returns.append(ret)

    def get_analysis(self):
        if not self.returns:
            return {'expected_shortfall': 0.0}

        returns = np.array(self.returns)
        # 取最坏的5%
        worst_returns = returns[returns < 0]
        n = int(len(worst_returns) * 0.05)
        n = max(1, n)  # 至少1个

        if len(worst_returns) > 0:
            es = np.mean(np.sort(worst_returns)[:n]) * 100
        else:
            es = 0.0

        return {'expected_shortfall': es}


class TimeInMarket(bt.Analyzer):
    """
    市场参与度分析器
    """

    def __init__(self):
        self.days_in_market = 0
        self.total_days = 0

    def next(self):
        self.total_days += 1
        # 检查是否有持仓
        has_position = any(
            self.strategy.getposition(data).size != 0
            for data in self.strategy.datas
        )
        if has_position:
            self.days_in_market += 1

    def get_analysis(self):
        pct = (self.days_in_market / self.total_days * 100) if self.total_days > 0 else 0
        return {
            'days_in_market': self.days_in_market,
            'total_days': self.total_days,
            'pct_time_in_market': pct
        }


class RollingDrawdown(bt.Analyzer):
    """
    滚动回撤分析器
    """

    params = (
        ('period', 252),  # 默认一年
    )

    def __init__(self):
        self.equity_curve = []

    def next(self):
        self.equity_curve.append(self.strategy.broker.getvalue())

    def get_analysis(self):
        equity = np.array(self.equity_curve)
        period = self.p.period

        if len(equity) < period + 1:
            return {
                'avg_rolling_drawdown': 0.0,
                'max_rolling_drawdown': 0.0
            }

        rolling_dd = []
        for i in range(len(equity) - period):
            window = equity[i:i+period+1]
            running_max = np.maximum.accumulate(window)
            dd = (window - running_max) / running_max * 100
            rolling_dd.append(dd.min())

        return {
            'avg_rolling_drawdown': np.mean(rolling_dd),
            'max_rolling_drawdown': min(rolling_dd) if rolling_dd else 0.0
        }
```

### 3.4 Benchmark 类设计

```python
"""
Benchmark Strategy
参考：pinkfish/pinkfish/benchmark.py
"""
import backtrader as bt
from datetime import datetime


class Benchmark(bt.Strategy):
    """
    等权重基准策略

    买入并持有，年度再平衡
    """

    params = (
        ('rebalance_freq', 'yearly'),  # 'yearly', 'monthly', 'weekly'
        ('rebalance_day', 1),  # 再基准日
    )

    def __init__(self):
        self.rebalance_counter = 0
        self.last_rebalance_year = None
        self.last_rebalance_month = None
        self.last_rebalance_week = None

    def next(self):
        current_date = self.data.datetime.date(0)
        need_rebalance = False

        # 检查是否需要再平衡
        if self.p.rebalance_freq == 'yearly':
            if self.last_rebalance_year != current_date.year:
                need_rebalance = True
                self.last_rebalance_year = current_date.year

        elif self.p.rebalance_freq == 'monthly':
            if (self.last_rebalance_month != current_date.month or
                self.last_rebalance_month is None):
                need_rebalance = True
                self.last_rebalance_month = current_date.month

        elif self.p.rebalance_freq == 'weekly':
            # 简化处理：每周第一天
            if current_date.weekday() == self.p.rebalance_day:
                if self.last_rebalance_week != current_date.isocalendar()[1]:
                    need_rebalance = True
                    self.last_rebalance_week = current_date.isocalendar()[1]

        # 执行再平衡
        if need_rebalance or len(self) == 1:
            self.rebalance()

    def rebalance(self):
        """等权重再平衡"""
        num_assets = len(self.datas)
        if num_assets == 0:
            return

        weight = 1.0 / num_assets
        weights = {data: weight for data in self.datas}

        total_value = self.broker.getvalue()

        for data, target_weight in weights.items():
            position = self.getposition(data)
            current_value = position.size * data.close[0]
            target_value = total_value * target_weight

            diff = target_value - current_value
            shares = int(abs(diff) / data.close[0])

            if diff > 0:
                self.buy(data=data, size=shares)
            elif diff < 0:
                self.sell(data=data, size=shares)

    def stop(self):
        """结束时清仓（可选）"""
        pass


# 使用示例
def run_backtest():
    cerebro = bt.Cerebro()

    # 添加数据
    data1 = bt.feeds.YahooFinanceData(dataname='SPY', fromdate=datetime(2020, 1, 1))
    data2 = bt.feeds.YahooFinanceData(dataname='TLT', fromdate=datetime(2020, 1, 1))
    data3 = bt.feeds.YahooFinanceData(dataname='GLD', fromdate=datetime(2020, 1, 1))

    cerebro.adddata(data1, name='SPY')
    cerebro.adddata(data2, name='TLT')
    cerebro.adddata(data3, name='GLD')

    # 添加基准策略
    cerebro.addstrategy(Benchmark, rebalance_freq='yearly')

    # 运行
    results = cerebro.run()
    return results[0]
```

---

## 四、API 设计

### 4.1 组合管理 API

```python
import backtrader as bt
from backtrader.portfolio import PortfolioMixin

class MyStrategy(bt.Strategy, PortfolioMixin):

    def next(self):
        # 1. 单资产权重调整
        self.adjust_percent(self.data0, 0.6)  # 调整到 60%

        # 2. 多资产批量调整
        weights = {
            self.data0: 0.4,
            self.data1: 0.3,
            self.data2: 0.3
        }
        self.adjust_percents(weights)

        # 3. 获取当前权重
        current = self.get_portfolio_weights()
        print(current)

        # 4. 打印持仓
        self.print_holdings(show_percent=True)
```

### 4.2 交易日志 API

```python
from backtrader.tradelog import TradeLog

class MyStrategy(bt.Strategy):

    def __init__(self):
        self.tradelog = TradeLog(self)

    def notify_order(self, order):
        if order.status == order.Completed:
            self.tradelog.record_trade(order)

    def stop(self):
        # 获取配对交易日志
        tlog = self.tradelog.get_log()
        print(tlog)

        # 获取原始交易日志
        rlog = self.tradelog.get_raw_log()
        print(rlog)

        # 分析交易统计
        print(f"总交易次数: {len(tlog)}")
        print(f"盈利交易: {(tlog['pl_cash'] > 0).sum()}")
        print(f"平均盈利: {tlog['pl_cash'].mean():.2f}")
        print(f"胜率: {(tlog['pl_cash'] > 0).sum() / len(tlog) * 100:.1f}%")
```

### 4.3 增强分析器 API

```python
from backtrader.analyzers import (
    ExpectedShortfall,
    TimeInMarket,
    RollingDrawdown
)

cerebro = bt.Cerebro()

# 添加分析器
cerebro.addanalyzer(ExpectedShortfall)
cerebro.addanalyzer(TimeInMarket)
cerebro.addanalyzer(RollingDrawdown, period=252)

# 运行
strat = cerebro.run()[0]

# 获取结果
es = strat.analyzers.expectedshortfall.get_analysis()
tim = strat.analyzers.timeinmarket.get_analysis()
rdd = strat.analyzers.rollingdrawdown.get_analysis()

print(f"Expected Shortfall: {es['expected_shortfall']:.2f}%")
print(f"Time in Market: {tim['pct_time_in_market']:.1f}%")
print(f"Avg Rolling DD: {rdd['avg_rolling_drawdown']:.2f}%")
```

---

## 五、实施计划

### 5.1 实施阶段

| 阶段 | 内容 | 时间 |
|------|------|------|
| Phase 1 | PortfolioMixin 基础实现 | 1天 |
| Phase 2 | TradeLog 类实现 | 1.5天 |
| Phase 3 | 技术指标装饰器 | 0.5天 |
| Phase 4 | 增强分析器 (ES, TIM, RDD) | 1天 |
| Phase 5 | Benchmark 策略 | 0.5天 |
| Phase 6 | 测试和文档 | 1天 |

### 5.2 优先级

1. **P0**: PortfolioMixin - 组合管理混入
2. **P0**: TradeLog - 交易日志系统
3. **P1**: ExpectedShortfall - ES 风险指标
4. **P1**: 技术指标装饰器
5. **P2**: Benchmark 策略
6. **P2**: RollingDrawdown - 滚动回撤

---

## 六、参考资料

### 6.1 关键参考代码

- pinkfish/pinkfish/portfolio.py - 组合管理核心
- pinkfish/pinkfish/trade.py - 交易日志系统
- pinkfish/pinkfish/benchmark.py - 基准策略
- pinkfish/pinkfish/pfstatistics.py - 性能统计
- pinkfish/pinkfish/fetch.py - 数据获取

### 6.2 关键设计模式

1. **装饰器模式** - `@technical_indicator`
2. **混入模式** - PortfolioMixin
3. **工厂方法** - TradeLog 配对交易
4. **单例模式** - TradeLog.instance

### 6.3 pinkfish 核心函数

```python
# Portfolio 核心方法
portfolio.fetch_timeseries()      # 获取多资产数据
portfolio.adjust_percent()        # 单资产权重调整
portfolio.adjust_percents()       # 批量权重调整
portfolio.share_percent()         # 获取权重
portfolio.performance_per_symbol()  # 按标的绩效
portfolio.correlation_map()       # 相关性热图

# TradeLog 核心方法
tlog.enter_trade() / buy()        # 开仓
tlog.exit_trade() / sell()        # 平仓
tlog.sell_short()                 # 卖空
tlog.buy2cover()                  # 平空
tlog.get_log()                    # 获取交易日志
tlog.get_log_raw()                # 获取原始日志

# pfstatistics 核心函数
pf.stats()                        # 计算所有统计指标
pf.summary()                      # 生成摘要表格
pf.currency()                     # 格式化货币
```

### 6.4 backtrader 可复用组件

- `backtrader/strategy.py` - 策略基类
- `backtrader/broker.py` - Broker 和订单管理
- `backtrader/analyzer.py` - 分析器基类
- `backtrader/indicators/*` - 技术指标
- `backtrader/feeds/*` - 数据源
