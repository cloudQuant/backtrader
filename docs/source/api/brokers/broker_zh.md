---
title: 交易经纪商 API
description: 完整的经纪商类 API 参考文档

---
# 交易经纪商 API

`Broker` 类负责 Backtrader 中的订单执行、持仓跟踪和资金管理。它在回测期间模拟经纪商行为，支持多种订单类型、佣金方案和保证金要求。

## 类定义

```python
class backtrader.BrokerBase:
    """经纪商实现的基类。"""

class backtrader.brokers.BackBroker:
    """回测用的经纪商模拟器（别名：BrokerBack）。"""

```

## 经纪商参数

### `cash`（默认：10000.0）

回测的初始资金。

```python
cerebro = bt.Cerebro()
cerebro.broker.setcash(100000.0)

```

### `commission`（默认：CommInfoBase(percabs=True)）

所有资产的默认佣金方案。

```python

# 百分比佣金

cerebro.broker.setcommission(commission=0.001)  # 0.1%

# 固定佣金

cerebro.broker.setcommission(commission=2.0, commtype=bt.CommInfoBase.COMM_FIXED)

```

### `checksubmit`（默认：True）

是否在接受订单前检查保证金/资金。

### `eosbar`（默认：False）

将与收盘时间相同的柱视为收盘柱。

### `filler`（默认：None）

用于部分订单执行的数量填充器可调用对象。

### 滑点参数

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `slip_perc` | float | 0.0 | 百分比滑点（0.01 = 1%） |

| `slip_fixed` | float | 0.0 | 固定滑点（价格单位） |

| `slip_open` | bool | False | 对开盘价格应用滑点 |

| `slip_match` | bool | True | 将滑点限制在最高/最低价格 |

| `slip_limit` | bool | True | 允许限价订单与滑点匹配 |

| `slip_out` | bool | False | 在最高-最低范围外提供滑点 |

### `coc`（默认：False）

作弊收盘：将市价订单与同一柱的收盘价匹配。

### `coo`（默认：False）

作弊开盘：将市价订单与开盘价匹配。

### `fundmode` / `fundstartval`（默认：False / 100.0）

类基金业绩跟踪模式。

## 资金和价值方法

### `getcash()` / `get_cash()`

获取当前可用资金。

```python
cash = cerebro.broker.getcash()

# 或从策略中

cash = self.broker.getcash()

```

### `setcash(amount)` / `set_cash(amount)`

设置经纪商资金金额。

```python
cerebro.broker.setcash(100000.0)

```

### `getvalue(datas=None)` / `get_value(datas=None)`

获取投资组合价值。如果 `datas` 为 None，则返回总投资组合价值。

```python

# 总价值

total_value = self.broker.getvalue()

# 特定数据的价值

data_value = self.broker.getvalue([self.data])

```

### `add_cash(amount)` / `add_cash(amount)`

向系统添加或移除资金。

```python

# 添加资金

cerebro.broker.add_cash(50000.0)

# 移除资金

cerebro.broker.add_cash(-10000.0)

```

## 持仓管理

### `getposition(data)`

获取特定数据源的持仓。

```python
position = self.broker.getposition(self.data)
size = position.size  # 正值=多头，负值=空头

price = position.price  # 平均入场价格

```

- *持仓属性**：

| 属性 | 类型 | 描述 |

|-----------|------|-------------|

| `size` | float | 持仓规模（正值=多头，负值=空头） |

| `price` | float | 平均入场价格 |

| `price_adj` | float | 调整后价格（用于股票） |

| `adjbase` | float | 期货的调整基准 |

## 佣金设置

### `setcommission(...)`

设置交易的佣金方案。

```python

# 股票类 + 百分比佣金

cerebro.broker.setcommission(
    commission=0.001,      # 0.1% 佣金
    stocklike=True
)

# 期货 + 保证金 + 固定佣金

cerebro.broker.setcommission(
    commission=2.0,        # 每张合约 $2
    margin=5000,           # 每张合约 $5000 保证金
    mult=10,               # 乘数
    stocklike=False,       # 期货
    commtype=bt.CommInfoBase.COMM_FIXED
)

# 杠杆交易

cerebro.broker.setcommission(
    commission=0.0005,
    leverage=2.0,          # 2 倍杠杆
    margin=0.5             # 50% 保证金

)

```

- *参数**：

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `commission` | float | 0.0 | 佣金金额 |

| `margin` | float | None | 保证金要求 |

| `mult` | float | 1.0 | 价值/利润的乘数 |

| `commtype` | int | None | COMM_PERC (0) 或 COMM_FIXED (1) |

| `stocklike` | bool | False | 股票类 (True) 或期货类 (False) |

| `percabs` | bool | True | 百分比为绝对值 (0.01 = 1%) |

| `interest` | float | 0.0 | 空头年利率 |

| `leverage` | float | 1.0 | 杠杆乘数 |

| `automargin` | bool/float | False | 自动保证金计算 |

| `name` | str | None | 资产名称（None = 默认） |

### `addcommissioninfo(comminfo, name=None)`

添加自定义 CommissionInfo 对象。

```python
class MyCommInfo(bt.CommInfoBase):
    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * 5.0  # 固定 $5 佣金

cerebro.broker.addcommissioninfo(MyCommInfo(), name='AAPL')

```

## 订单管理

### `buy(owner, data, size, **kwargs)`

创建买单。

```python

# 从策略中

order = self.buy(size=10)

# 从 cerebro 中

order = cerebro.broker.buy(
    owner=strategy,
    data=data,
    size=10,
    price=100.0
)

```

- *参数**：

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `owner` | Strategy | 必需 | 创建订单的策略 |

| `data` | Data feed | 必需 | 订单的数据源 |

| `size` | float | 必需 | 订单规模（正数） |

| `price` | float | None | 限价 |

| `plimit` | float | None | 止损限价的限价 |

| `exectype` | Order.ExecType | None | 执行类型 |

| `valid` | Order.Valid | None | 有效期 |

| `tradeid` | int | 0 | 交易标识符 |

| `oco` | Order | None | 一键取消其他订单 |

| `trailamount` | float | None | 追踪金额 |

| `trailpercent` | float | None | 追踪百分比 |

| `parent` | Order | None | 父订单（括号订单） |

| `transmit` | bool | True | 立即传输 |

### `sell(owner, data, size, **kwargs)`

创建卖单。参数与 `buy()` 相同。

```python

# 卖出全部持仓

order = self.sell()

# 止损

order = self.sell(price=95.0, exectype=bt.Order.Stop)

```

### `cancel(order, bracket=False)`

取消挂单。

```python
self.cancel(order)

```

### `get_orders_open(safe=False)`

获取挂单的可迭代对象。

```python

# 获取订单（只读）

open_orders = self.broker.get_orders_open()

# 获取可编辑副本

open_orders = self.broker.get_orders_open(safe=True)

```

## 订单类型

### 市价单

以下一个可用价格执行。

```python
order = self.buy()  # 市价单

```

### 限价单

以指定价格或更优价格执行。

```python

# 以 100 或更低价格买入

order = self.buy(price=100.0, exectype=bt.Order.Limit)

```

### 止损单

当止损价达到时转换为市价单。

```python

# 止损价 95

order = self.sell(price=95.0, exectype=bt.Order.Stop)

```

### 止损限价单

当止损价达到时转换为限价单。

```python

# 止损 95，限价 94.5

order = self.sell(price=94.5, plimit=95.0, exectype=bt.Order.StopLimit)

```

### 收盘单

在交易日收盘价格执行。

```python
order = self.buy(exectype=bt.Order.Close)

```

### 追踪止损单

止损价格随价格变动调整。

```python
order = self.sell(trailamount=2.0, exectype=bt.Order.StopTrail)
order = self.sell(trailpercent=0.05, exectype=bt.Order.StopTrail)

```

## 滑点配置

### 百分比滑点

```python
cerebro.broker.set_slippage_perc(
    perc=0.001,        # 0.1% 滑点
    slip_open=True,
    slip_limit=True,
    slip_match=True,
    slip_out=False
)

```

### 固定滑点

```python
cerebro.broker.set_slippage_fixed(
    fixed=0.02,        # 每股 $0.02
    slip_open=True,
    slip_limit=True,
    slip_match=True
)

```

## 基金模式

### `set_fundmode(fundmode, fundstartval=None)`

启用类基金业绩跟踪。

```python

# 启用基金模式，初始净值 $100

cerebro.broker.set_fundmode(True, fundstartval=100.0)

# 获取基金价值

fund_value = cerebro.broker.get_fundvalue()
fund_shares = cerebro.broker.get_fundshares()

```

### `set_fundstartval(fundstartval)`

设置基金跟踪的起始值。

```python
cerebro.broker.set_fundstartval(100.0)

```

## 其他配置方法

### `set_coc(coc)`

启用/禁用作弊收盘。

```python
cerebro.broker.set_coc(True)  # 允许当日执行

```

### `set_coo(coo)`

启用/禁用作弊开盘。

```python
cerebro.broker.set_coo(True)

```

### `set_checksubmit(checksubmit)`

启用/禁用提交前的资金/保证金检查。

```python
cerebro.broker.set_checksubmit(False)  # 禁用检查

```

### `set_filler(filler)`

设置部分执行的数量填充器。

```python
def my_filler(order, price, ago):

# 基于成交量返回可执行数量
    volume = order.data.volume[ago]
    return min(order.executed.remsize, volume *0.1)

cerebro.broker.set_filler(my_filler)

```

## 历史订单

### `add_order_history(orders, notify=True)`

向经纪商添加历史订单。

```python

# 格式：[datetime, size, price, data_index]

orders = [
    [datetime(2023, 1, 1), 100, 150.0, 0],
    [datetime(2023, 1, 2), -100, 155.0, 0],
]
cerebro.broker.add_order_history(orders, notify=False)

```

### `set_fund_history(fund)`

设置用于跟踪的基金历史。

```python

# 格式：[datetime, share_value, net_asset_value]

fund_history = [
    [datetime(2023, 1, 1), 100.0, 100000.0],
    [datetime(2023, 1, 2), 101.5, 101500.0],
]
cerebro.broker.set_fund_history(fund_history)

```

## 佣金信息类

### CommInfoBase

基础佣金方案类。

```python
comminfo = bt.CommInfoBase(
    commission=0.001,
    margin=5000,
    mult=10,
    stocklike=False,
    commtype=bt.CommInfoBase.COMM_PERC,
    leverage=2.0
)

```

### CommissionInfo

标准佣金方案（默认 percabs=True）。

### ComminfoDC

数字货币佣金方案。

```python
cerebro.broker.setcommission(
    commission=0.001,
    margin=0.1,
    mult=10,
    interest=3.0
)

```

### ComminfoFuturesPercent

期货百分比佣金。

### ComminfoFuturesFixed

期货固定佣金。

### ComminfoFundingRate

永续合约的资金费率。

## 内置经纪商实现

### BackBroker

默认的回测经纪商。

```python

# 自动（默认）

cerebro = bt.Cerebro()

# 手动

broker = bt.brokers.BackBroker(cash=100000)
cerebro.setbroker(broker)

```

### CCXTBroker

加密货币交易所经纪商（需要 ccxt）。

```python
import ccxt
exchange = ccxt.binance()

broker = bt.brokers.CCXTBroker(
    exchange=exchange,
    wallet_exposure=0.33  # 使用 33% 的钱包

)
cerebro.setbroker(broker)

```

### CTPBroker

中国期货经纪商（需要 ctpbee）。

### IBBroker

Interactive Brokers 经纪商（需要 ibpy）。

### OandaBroker

OANDA 经纪商（需要 oandapy）。

### VCBroker

VisualChart 经纪商。

## 完整示例

```python
import backtrader as bt
from datetime import datetime

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.data.close[0] > self.sma[0]:

# 使用限价单买入
                cash = self.broker.getcash()
                size = int(cash / self.data.close[0]*0.95)
                self.order = self.buy(
                    size=size,
                    price=self.data.close[0]*0.99,
                    exectype=bt.Order.Limit
                )
        else:
            if self.data.close[0] < self.sma[0]:

# 使用止损卖出
                self.order = self.sell(
                    size=self.position.size,
                    exectype=bt.Order.Stop,
                    price=self.position.price* 0.95
                )

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            if order.isbuy():
                print(f'买入: {order.executed.size:.2f} @ {order.executed.price:.2f}')
            else:
                print(f'卖出: {order.executed.size:.2f} @ {order.executed.price:.2f}')

        self.order = None

    def notify_trade(self, trade):
        if trade.isclosed:
            print(f'交易盈亏: {trade.pnl:.2f}, 佣金: {trade.commission:.2f}')

# 创建 cerebro

cerebro = bt.Cerebro()

# 添加策略

cerebro.addstrategy(MyStrategy)

# 添加数据

data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate=datetime(2020, 1, 1))
cerebro.adddata(data)

# 设置经纪商参数

cerebro.broker.setcash(100000.0)
cerebro.broker.setcommission(commission=0.001)  # 0.1%

# 设置滑点

cerebro.broker.set_slippage_perc(perc=0.0005)  # 0.05%

# 运行

result = cerebro.run()
print(f'最终价值: {cerebro.broker.getvalue():.2f}')

```

## 下一步

- [策略 API](strategy_zh.md) - 交易策略
- [指标 API](indicator_zh.md) - 技术指标
- [分析器 API](analyzer_zh.md) - 绩效分析
- [数据源 API](data-feeds_zh.md) - 数据源
