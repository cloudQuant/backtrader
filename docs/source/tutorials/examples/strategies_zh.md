---
title: 策略示例库
description: 常见交易策略的完整工作示例

---
# 策略示例库

本节提供了流行交易策略的完整、可运行实现。每个示例都包含完整的源代码、参数说明和预期性能特征。

## 目录

- [趋势跟踪策略](#趋势跟踪策略双移动平均)
- [均值回归策略](#均值回归策略布林带)
- [突破策略](#突破策略唐奇安通道)
- [网格交易策略](#网格交易策略)
- [套利策略](#套利策略日历价差)
- [动量策略](#动量策略超级趋势)

---
## 趋势跟踪策略（双移动平均）

### 概述

双移动平均交叉策略是最基本的趋势跟踪方法之一。当短期移动平均线向上穿越长期移动平均线时产生买入信号（金叉），当短期移动平均线向下穿越长期移动平均线时产生卖出信号（死叉）。

### 策略代码

```python
import backtrader as bt

class DualMovingAverageStrategy(bt.Strategy):
    """双移动平均交叉趋势跟踪策略。

    当短期移动平均线向上穿越长期移动平均线时买入（金叉），
    当短期移动平均线向下穿越长期移动平均线时卖出（死叉）。

    参数:
        short_period (int): 短期移动平均线周期（默认: 10）
        long_period (int): 长期移动平均线周期（默认: 30）
        position_size (float): 每笔交易使用的可用资金比例（默认: 0.95）
    """

    params = (
        ('short_period', 10),
        ('long_period', 30),
        ('position_size', 0.95),
    )

    def __init__(self):

# 计算移动平均线
        self.short_ma = bt.indicators.SMA(self.data.close, period=self.p.short_period)
        self.long_ma = bt.indicators.SMA(self.data.close, period=self.p.long_period)

# 交叉指标: 金叉为+1，死叉为-1
        self.crossover = bt.indicators.CrossOver(self.short_ma, self.long_ma)

# 跟踪订单以避免重复入场
        self.order = None

    def next(self):

# 等待待处理订单完成
        if self.order:
            return

# 无持仓 - 寻找入场机会
        if not self.position:
            if self.crossover > 0:  # 金叉
                cash = self.broker.getcash()
                price = self.data.close[0]
                size = int(cash * self.p.position_size / price)
                if size > 0:
                    self.order = self.buy(size=size)
        else:

# 有持仓 - 寻找出场机会
            if self.crossover < 0:  # 死叉
                self.order = self.close()

    def notify_order(self, order):
        """处理订单状态更新。"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

```

### 性能预期

- **市场类型**: 在趋势市场中表现最佳
- **震荡风险**: 在横盘/盘整市场中风险较高
- **胜率**: 通常为 35-45%（依靠少数大盈利）
- **盈亏比**: 在强趋势中可达 2:1 或更高

### 优化参数

| 参数 | 范围 | 影响 |

|------|------|------|

| short_period | 5-20 | 周期越短=信号越多，噪音越大 |

| long_period | 20-60 | 周期越长=信号越少，滞后越大 |

---
## 均值回归策略（布林带）

### 概述

均值回归策略从价格回归平均值的趋势中获利。布林带基于移动平均线的标准差构建动态支撑/阻力位，识别超买和超卖条件。

### 策略代码

```python
import backtrader as bt

class BollingerBandsMeanReversion(bt.Strategy):
    """布林带均值回归策略。

    使用布林带识别超买/超卖条件，并在价格显示回归均值迹象时入场。

    入场规则:

        - 当价格跌破下轨后回升至中轨时买入
        - 当价格突破上轨后回落至中轨时卖出

    参数:
        period (int): 布林带计算周期（默认: 20）
        devfactor (float): 标准差倍数（默认: 2.0）
    """

    params = (
        ('period', 20),
        ('devfactor', 2.0),
    )

    def __init__(self):

# 布林带指标
        self.bband = bt.indicators.BBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

# 跟踪信号
        self.oversold = False  # 价格跌破下轨
        self.overbought = False  # 价格突破上轨
        self.order = None

    def next(self):
        if self.order:
            return

# 检查超卖条件
        if self.data.close[0] < self.bband.lines.bot[0]:
            self.oversold = True

# 检查超买条件
        if self.data.close[0] > self.bband.lines.top[0]:
            self.overbought = True

# 入场: 价格在超卖后回升至中轨上方
        if self.oversold and self.data.close[0] > self.bband.lines.mid[0]:
            if not self.position:
                cash = self.broker.getcash()
                size = int(cash *0.95 / self.data.close[0])
                self.order = self.buy(size=size)
                self.oversold = False

# 入场: 价格在超买后回落至中轨下方时做空
        if self.overbought and self.data.close[0] < self.bband.lines.mid[0]:
            if not self.position:
                cash = self.broker.getcash()
                size = int(cash* 0.95 / self.data.close[0])
                self.order = self.sell(size=size)
                self.overbought = False

# 平多仓
        if self.position and self.position.size > 0:
            if self.data.close[0] > self.bband.lines.top[0]:
                self.order = self.close()

# 平空仓
        if self.position and self.position.size < 0:
            if self.data.close[0] < self.bband.lines.bot[0]:
                self.order = self.close()

    def notify_order(self, order):
        """处理订单状态更新。"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

```

### 性能预期

- **市场类型**: 在横盘/震荡市场中表现最佳
- **趋势风险**: 在强趋势市场中可能遭受较大亏损
- **胜率**: 通常为 55-65%
- **盈亏比**: 目标为 1:1 至 1.5:1

### 优化参数

| 参数 | 范围 | 影响 |

|------|------|------|

| period | 15-30 | 影响带状响应速度 |

| devfactor | 1.5-2.5 | 带宽越大=信号越少 |

---
## 突破策略（唐奇安通道）

### 概述

突破策略在价格突破重要支撑或阻力位时交易动量。唐奇安通道使用一段时间内的最高价和最低价来定义这些水平，非常适合早期捕捉趋势走势。

### 策略代码

```python
import backtrader as bt

class DonchianChannelBreakout(bt.Strategy):
    """唐奇安通道突破策略。

    当价格突破 N 周期最高价时买入，当价格跌破 N 周期最低价时卖出。

    入场规则:

        - 当收盘价突破周期内最高价时买入
        - 当收盘价跌破周期内最低价时卖出

    出场规则:

        - 持有多单时，当收盘价跌破最低价时平仓
        - 持有空单时，当收盘价突破最高价时平仓

    参数:
        period (int): 通道计算的回溯周期（默认: 20）
    """

    params = (
        ('period', 20),
    )

    def __init__(self):

# 唐奇安通道组件
        self.highest = bt.indicators.Highest(self.data.high, period=self.p.period)
        self.lowest = bt.indicators.Lowest(self.data.low, period=self.p.period)
        self.order = None

    def next(self):
        if self.order:
            return

# 无持仓 - 寻找突破入场
        if not self.position:

# 向上突破前高
            if self.data.close[0] > self.highest[-1]:
                cash = self.broker.getcash()
                size = int(cash *0.95 / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)

# 向下突破前低
            elif self.data.close[0] < self.lowest[-1]:
                cash = self.broker.getcash()
                size = int(cash* 0.95 / self.data.close[0])
                if size > 0:
                    self.order = self.sell(size=size)

# 多单持仓 - 寻找出场
        elif self.position.size > 0:
            if self.data.close[0] < self.lowest[-1]:
                self.order = self.close()

# 空单持仓 - 寻找出场
        else:
            if self.data.close[0] > self.highest[-1]:
                self.order = self.close()

    def notify_order(self, order):
        """处理订单状态更新。"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

```

### 性能预期

- **市场类型**: 在有明显趋势的市场中表现优异
- **假突破**: 在震荡市场中常见
- **胜率**: 通常为 30-40%（依赖大趋势）
- **盈亏比**: 在强趋势中可达 3:1

### 优化参数

| 参数 | 范围 | 影响 |

|------|------|------|

| period | 10-40 | 周期越短=突破越多，假信号越多 |

---
## 网格交易策略

### 概述

网格交易在当前价格上下以固定间隔放置买入和卖出订单。该策略从市场波动中获利，在价格在定义范围内震荡时效果最佳。

### 策略代码

```python
import backtrader as bt

class GridTradingStrategy(bt.Strategy):
    """适用于震荡市场的网格交易策略。

    在当前价格下方放置买单网格，在当前价格上方放置卖单网格。
    当价格移动时，订单在网格水平成交并在下一水平获利。

    参数:
        grid_size (float): 网格水平间的价格距离（例如 0.01 表示 1%）
        grid_levels (int): 上下各多少个网格水平（默认: 5）
        max_position (int): 最大并发持仓数（默认: 10）
    """

    params = (
        ('grid_size', 0.01),  # 1%网格
        ('grid_levels', 5),
        ('max_position', 10),
    )

    def __init__(self):
        self.grid_buy_orders = {}  # 价格 -> 订单
        self.grid_sell_orders = {}  # 价格 -> 订单
        self.grid_initialized = False
        self.base_price = None

    def next(self):
        current_price = self.data.close[0]

# 首次运行时初始化网格
        if not self.grid_initialized:
            self.base_price = current_price
            self.initialize_grid(current_price)
            self.grid_initialized = True
            return

# 检查已成交订单并放置对冲订单
        self.check_filled_orders(current_price)

# 维持网格水平
        self.rebalance_grid(current_price)

    def initialize_grid(self, current_price):
        """初始化买卖网格水平。"""
        for i in range(1, self.p.grid_levels + 1):
            buy_price = round(current_price *(1 - self.p.grid_size*i), 2)
            sell_price = round(current_price*(1 + self.p.grid_size*i), 2)

# 在当前价格下方放置买单
            if len([o for o in self.grid_buy_orders.values() if o]) < self.p.max_position:
                order = self.buy(price=buy_price, exectype=bt.Order.Limit)
                self.grid_buy_orders[buy_price] = order

# 在当前价格上方放置卖单
            if len([o for o in self.grid_sell_orders.values() if o]) < self.p.max_position:
                order = self.sell(price=sell_price, exectype=bt.Order.Limit)
                self.grid_sell_orders[sell_price] = order

    def check_filled_orders(self, current_price):
        """检查已成交订单并放置获利订单。"""

# 检查买单是否成交
        for price, order in list(self.grid_buy_orders.items()):
            if order and order.status == order.Completed:

# 在下一网格水平放置卖单获利
                profit_price = round(price*(1 + self.p.grid_size), 2)
                if profit_price not in self.grid_sell_orders:
                    self.sell(price=profit_price, size=order.executed.size,
                             exectype=bt.Order.Limit)
                del self.grid_buy_orders[price]

# 检查卖单是否成交
        for price, order in list(self.grid_sell_orders.items()):
            if order and order.status == order.Completed:

# 在下一网格水平放置买单获利
                profit_price = round(price*(1 - self.p.grid_size), 2)
                if profit_price not in self.grid_buy_orders:
                    self.buy(price=profit_price, size=abs(order.executed.size),
                            exectype=bt.Order.Limit)
                del self.grid_sell_orders[price]

    def rebalance_grid(self, current_price):
        """随着价格移动维持网格水平。"""

# 取消距离当前价格太远的订单
        for price, order in list(self.grid_buy_orders.items()):
            if order and price < current_price*(1 - self.p.grid_size*(self.p.grid_levels + 2)):
                self.cancel(order)
                del self.grid_buy_orders[price]

        for price, order in list(self.grid_sell_orders.items()):
            if order and price > current_price*(1 + self.p.grid_size* (self.p.grid_levels + 2)):
                self.cancel(order)
                del self.grid_sell_orders[price]

# 根据需要添加新网格水平
        active_orders = len([o for o in self.grid_buy_orders.values() if o]) + \
                       len([o for o in self.grid_sell_orders.values() if o])

        if active_orders < self.p.max_position:
            self.initialize_grid(current_price)

```

### 性能预期

- **市场类型**: 专为横盘/盘整市场优化
- **趋势风险**: 在强趋势中可能累积亏损头寸
- **胜率**: 高胜率，每笔交易利润较小
- **资金要求**: 需要足够资金维持多个头寸

### 优化参数

| 参数 | 范围 | 影响 |

|------|------|------|

| grid_size | 0.005-0.02 | 越小=交易越多，风险敞口越大 |

| grid_levels | 3-10 | 水平越多=所需资金越多 |

| max_position | 5-20 | 限制风险敞口 |

---
## 套利策略（日历价差）

### 概述

日历价差套利从近月和远月期货合约之间的价差中获利。这种市场中性策略交易两个相关工具之间的关系，而非方向性价格变动。

### 策略代码

```python
import backtrader as bt

class CalendarSpreadArbitrage(bt.Strategy):
    """日历价差套利策略。

    交易近月合约和远月合约之间的价差。
    当近价-远价较低时做多价差（升水），当近价-远价较高时做空价差（贴水）。

    参数:
        spread_low (float): 做多价差的下阈值
        spread_high (float): 做空价差的上阈值
    """

    params = (
        ('spread_low', 0.06),
        ('spread_high', 0.52),
    )

    def __init__(self):

# 假设 data[0]是近月合约，data[1]是远月合约
        self.near = self.datas[0]
        self.far = self.datas[1]
        self.spread_position = 0  # 1=做多价差, -1=做空价差, 0=无持仓
        self.order = None

    def next(self):
        if self.order:
            return

        current_spread = self.near.close[0] - self.far.close[0]

# 无持仓 - 寻找入场
        if self.spread_position == 0:

# 价差较低 - 买入近月，卖出远月（做多价差）
            if current_spread < self.p.spread_low:
                self.order = self.buy(data=self.near, size=1)
                self.order = self.sell(data=self.far, size=1)
                self.spread_position = 1

# 价差较高 - 卖出近月，买入远月（做空价差）
            elif current_spread > self.p.spread_high:
                self.order = self.sell(data=self.near, size=1)
                self.order = self.buy(data=self.far, size=1)
                self.spread_position = -1

# 做多价差持仓 - 寻找出场
        elif self.spread_position == 1:
            if current_spread > self.p.spread_high:
                self.close(data=self.near)
                self.close(data=self.far)
                self.spread_position = 0

# 做空价差持仓 - 寻找出场
        elif self.spread_position == -1:
            if current_spread < self.p.spread_low:
                self.close(data=self.near)
                self.close(data=self.far)
                self.spread_position = 0

    def notify_order(self, order):
        """处理订单状态更新。"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

    def notify_trade(self, trade):
        """记录交易完成。"""
        if trade.isclosed:
            print(f'交易盈亏: {trade.pnl:.2f}, 手续费: {trade.commission:.2f}')

```

### 性能预期

- **市场类型**: 具有期限结构的期货市场
- **市场中性**: 从相对价值中获利，而非方向
- **胜率**: 高胜率，稳定收益
- **资金效率**: 需要双边保证金

### 优化参数

| 参数 | 范围 | 影响 |

|------|------|------|

| spread_low | 因市场而异 | 做多价差入场点 |

| spread_high | 因市场而异 | 做空价差入场点 |

---
## 动量策略（超级趋势）

### 概述

超级趋势指标结合趋势方向和波动率产生清晰的买卖信号。在有持续趋势的市场中特别有效，并能自动调整以适应变化的波动率条件。

### 策略代码

```python
import backtrader as bt

class SuperTrendIndicator(bt.Indicator):
    """超级趋势指标。

    使用 ATR 计算动态支撑/阻力位的趋势跟踪指标。
    """

    lines = ('supertrend', 'direction')
    params = dict(
        period=10,
        multiplier=3.0,
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)
        self.hl2 = (self.data.high + self.data.low) / 2.0

    def next(self):
        if len(self) < self.p.period + 1:
            self.lines.supertrend[0] = self.hl2[0]
            self.lines.direction[0] = 1
            return

        atr = self.atr[0]
        hl2 = self.hl2[0]

        upper_band = hl2 + self.p.multiplier *atr
        lower_band = hl2 - self.p.multiplier*atr

        prev_supertrend = self.lines.supertrend[-1]
        prev_direction = self.lines.direction[-1]

        if prev_direction == 1:  # 上升趋势
            if self.data.close[0] < prev_supertrend:
                self.lines.supertrend[0] = upper_band
                self.lines.direction[0] = -1
            else:
                self.lines.supertrend[0] = max(lower_band, prev_supertrend)
                self.lines.direction[0] = 1
        else:  # 下降趋势
            if self.data.close[0] > prev_supertrend:
                self.lines.supertrend[0] = lower_band
                self.lines.direction[0] = 1
            else:
                self.lines.supertrend[0] = min(upper_band, prev_supertrend)
                self.lines.direction[0] = -1


class SuperTrendStrategy(bt.Strategy):
    """超级趋势动量策略。

    当趋势转为上升时做多，当趋势转为下降时平仓。

    参数:
        period (int): 超级趋势计算的 ATR 周期（默认: 10）
        multiplier (float): 带宽的 ATR 倍数（默认: 3.0）
    """

    params = (
        ('period', 10),
        ('multiplier', 3.0),
    )

    def __init__(self):
        self.supertrend = SuperTrendIndicator(
            self.data,
            period=self.p.period,
            multiplier=self.p.multiplier
        )
        self.order = None

    def next(self):
        if self.order:
            return

# 当趋势从下降转为上升时买入
        if not self.position:
            if (self.supertrend.direction[0] == 1 and
                self.supertrend.direction[-1] == -1):
                cash = self.broker.getcash()
                size = int(cash* 0.95 / self.data.close[0])
                if size > 0:
                    self.order = self.buy(size=size)
        else:

# 当趋势转为下降时平仓
            if self.supertrend.direction[0] == -1:
                self.order = self.close()

    def notify_order(self, order):
        """处理订单状态更新。"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        self.order = None

```

### 性能预期

- **市场类型**: 有持续走势的趋势市场
- **震荡风险**: 在震荡市场中风险适中
- **胜率**: 通常为 40-50%
- **盈亏比**: 可达 2:1 或更高

### 优化参数

| 参数 | 范围 | 影响 |

|------|------|------|

| period | 7-15 | 周期越短=越敏感 |

| multiplier | 2.0-4.0 | 值越大=信号越少，趋势过滤越好 |

---
## 运行这些示例

使用任何这些策略：

```python
import backtrader as bt
import backtrader.feeds as btfeeds

# 创建 Cerebro 引擎

cerebro = bt.Cerebro()

# 添加您选择的策略

cerebro.addstrategy(DualMovingAverageStrategy, short_period=10, long_period=30)

# 加载数据

data = btfeeds.GenericCSVData(
    dataname='your_data.csv',
    dtformat='%Y-%m-%d',
    datetime=0,
    open=1,
    high=2,
    low=3,
    close=4,
    volume=5,
    openinterest=-1
)
cerebro.adddata(data)

# 设置初始资金和手续费

cerebro.broker.setcash(100000)
cerebro.broker.setcommission(commission=0.001)

# 运行

results = cerebro.run()

# 绘图

cerebro.plot()

```

## 后续步骤

- [自定义指标](../user_guide/indicators.md) - 创建您自己的指标
- [分析器](../user_guide/analyzers.md) - 评估策略性能
- [优化](../user_guide/optimization.md) - 寻找最优参数
