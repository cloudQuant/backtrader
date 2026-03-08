---
title: Sizer API
description: Sizer 类完整 API 参考

---
# Sizer API

`Sizer` 类用于计算交易订单的仓位大小。它基于可用资金、风险参数和其他因素来确定每次下单的数量。

## 类定义

```python
class backtrader.Sizer:
    """仓位计算器基类。"""

```

## 核心方法

### `__init__(self, **kwargs)`

初始化 Sizer 实例。

```python
def __init__(self, **kwargs):
    super().__init__(**kwargs)

```

### `getsizing(self, data, isbuy)`

获取订单的仓位大小。这是公开接口，内部调用 `_getsizing` 方法。

| 参数 | 类型 | 描述 |

|-----------|------|-------------|

| `data` | Data | 目标数据源 |

| `isbuy` | bool | True 表示买入，False 表示卖出 |

| 返回值 | 描述 |

|-----------|-------------|

| int | 订单的仓位大小 |

```python
def getsizing(self, data, isbuy):
    comminfo = self.broker.getcommissioninfo(data)
    return self._getsizing(comminfo, self.broker.getcash(), data, isbuy)

```

### `_getsizing(self, comminfo, cash, data, isbuy)`

- *必须被子类重写**。实现实际的仓位计算逻辑。

| 参数 | 类型 | 描述 |

|-----------|------|-------------|

| `comminfo` | CommissionInfo | 佣金信息对象，包含佣金计算方法 |

| `cash` | float | 当前可用现金 |

| `data` | Data | 目标数据源 |

| `isbuy` | bool | True 表示买入，False 表示卖出 |

| 返回值 | 描述 |

|-----------|-------------|

| int | 订单的仓位大小，返回 0 表示不执行 |

```python
def _getsizing(self, comminfo, cash, data, isbuy):

# 实现仓位计算逻辑
    raise NotImplementedError

```

### `set(self, strategy, broker)`

设置策略和经纪人引用。

| 参数 | 类型 | 描述 |

|-----------|------|-------------|

| `strategy` | Strategy | 使用此 sizer 的策略实例 |

| `broker` | Broker | 经纪人实例，用于获取组合信息 |

```python
def set(self, strategy, broker):
    self.strategy = strategy
    self.broker = broker

```

## 内置 Sizer

### FixedSize - 固定数量

始终返回固定数量的 Sizer。

- *参数**:

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `stake` | int | 1 | 固定仓位大小 |

| `tranches` | int | 1 | 将仓位分成多少份 |

```python
import backtrader as bt

# 始终买入 100 股

cerebro.addsizer(bt.sizers.FixedSize, stake=100)

# 分 4 份建仓，每次 25 股

cerebro.addsizer(bt.sizers.FixedSize, stake=100, tranches=4)

```

### FixedReverser - 固定数量反转

根据是否有持仓来决定仓位大小。

- 开仓时：返回 `stake`
- 反转持仓时：返回 `2 *stake`

- *参数**:

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `stake` | int | 1 | 基础仓位大小 |

```python
cerebro.addsizer(bt.sizers.FixedReverser, stake=100)

# 无持仓时：买入 100 股

# 有 100 股持仓时：卖出 200 股（平多 100 + 开空 100）

```

### FixedSizeTarget - 固定目标数量

返回固定的目标仓位大小，适用于目标订单。

- *参数**:

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `stake` | int | 1 | 目标仓位大小 |

| `tranches` | int | 1 | 将仓位分成多少份 |

```python
cerebro.addsizer(bt.sizers.FixedSizeTarget, stake=1000)

# 配合 target_order_size 使用

cerebro.target_order_size(data, target=0)  # 目标仓位为 0

```

### PercentSizer - 可用资金百分比

基于可用现金的百分比计算仓位大小。

- *参数**:

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `percents` | float | 20 | 使用现金的百分比 (0-100) |

| `retint` | bool | False | 是否返回整数 |

```python

# 使用 30% 的可用资金

cerebro.addsizer(bt.sizers.PercentSizer, percents=30)

# 返回整数仓位

cerebro.addsizer(bt.sizers.PercentSizer, percents=20, retint=True)

```

- *注意**: 如果已有持仓，`PercentSizer` 直接使用当前持仓大小作为订单数量。

### AllInSizer - 全仓

使用 100% 可用资金的 Sizer，继承自 `PercentSizer`。

- *参数**:

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `percents` | float | 100 | 使用现金的百分比 (固定为 100) |

```python
cerebro.addsizer(bt.sizers.AllInSizer)

# 每次下单都使用全部可用资金

```

### PercentSizerInt - 整数百分比

与 `PercentSizer` 相同，但始终返回整数。

- *参数**:

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `percents` | float | 20 | 使用现金的百分比 (0-100) |

| `retint` | bool | True | 固定为 True |

```python
cerebro.addsizer(bt.sizers.PercentSizerInt, percents=25)

# 返回整数仓位大小

```

### AllInSizerInt - 全仓整数

使用 100% 可用资金并返回整数的 Sizer。

- *参数**:

| 参数 | 类型 | 默认值 | 描述 |

|-----------|------|---------|-------------|

| `percents` | float | 100 | 使用现金的百分比 (固定为 100) |

```python
cerebro.addsizer(bt.sizers.AllInSizerInt)

# 每次下单都使用全部可用资金，返回整数

```

## 自定义 Sizer 开发

创建自定义 Sizer 只需继承 `Sizer` 基类并重写 `_getsizing` 方法。

### 基本模板

```python
import backtrader as bt

class MySizer(bt.Sizer):
    params = (
        ('my_param', 0.1),  # 自定义参数
    )

    def _getsizing(self, comminfo, cash, data, isbuy):

# 计算仓位大小
        price = data.close[0]
        size = int(cash *self.p.my_param / price)
        return size

```

### 风险百分比 Sizer 示例

基于账户价值的固定风险百分比计算仓位。

```python
class RiskPercentSizer(bt.Sizer):
    """
    基于风险百分比计算仓位。
    每次交易的风险不超过账户价值的指定百分比。
    """
    params = (
        ('risk', 0.02),  # 风险百分比 (2%)
    )

    def _getsizing(self, comminfo, cash, data, isbuy):

# 这里简化计算，实际应结合止损距离
        price = data.close[0]
        risk_amount = self.broker.getvalue()*self.p.risk
        size = int(risk_amount / price)
        return size

```

### ATR 风险调整 Sizer 示例

基于 ATR (Average True Range) 动态调整仓位大小。

```python
class ATRRiskSizer(bt.Sizer):
    """
    基于 ATR 计算仓位。
    仓位大小 = 账户风险 / (ATR* 风险倍数)
    """
    params = (
        ('risk', 0.02),      # 账户风险百分比
        ('atr_mult', 2.0),   # ATR 风险倍数
        ('atr_period', 14),  # ATR 周期
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.atr = bt.indicators.ATR(period=self.p.atr_period)

    def _getsizing(self, comminfo, cash, data, isbuy):
        if len(self.atr) < self.p.atr_period:
            return 0

        account_value = self.broker.getvalue()
        risk_amount = account_value *self.p.risk
        atr_value = self.atr[0]

        if atr_value == 0:
            return 0

# 每股风险 = ATR*风险倍数
        risk_per_share = atr_value*self.p.atr_mult

# 计算仓位
        size = int(risk_amount / risk_per_share)

# 确保不超过可用资金
        max_size = int(cash / data.close[0])
        return min(size, max_size)

```

### 凯利公式 Sizer 示例

基于凯利公式计算最优仓位大小。

```python
class KellySizer(bt.Sizer):
    """
    凯利公式仓位计算。
    f = (bp - q) / b
    f: 仓位比例
    b: 赔率 (平均盈利 / 平均亏损)
    p: 胜率
    q: 败率 (1 - p)
    """
    params = (
        ('win_rate', 0.55),      # 胜率
        ('avg_win', 1.5),        # 平均盈利倍数
        ('avg_loss', 1.0),       # 平均亏损倍数
        ('kelly_fraction', 0.5), # 凯利分数 (0.5 表示半凯利)
    )

    def _getsizing(self, comminfo, cash, data, isbuy):

# 计算赔率
        b = self.p.avg_win / self.p.avg_loss
        p = self.p.win_rate
        q = 1 - p

# 凯利公式
        kelly_f = (b*p - q) / b

# 应用凯利分数
        f = kelly_f*self.p.kelly_fraction

# 限制在 0-100% 范围内
        f = max(0, min(f, 1.0))

# 计算仓位
        price = data.close[0]
        size = int(cash* f / price)

        return max(0, size)

```

## 与 Cerebro 集成

### 添加默认 Sizer

使用 `addsizer` 方法为所有策略设置默认 Sizer。

```python
cerebro = bt.Cerebro()

# 设置默认 Sizer

cerebro.addsizer(bt.sizers.FixedSize, stake=100)

# 添加策略时自动使用此 Sizer

cerebro.addstrategy(MyStrategy)

```

### 为特定策略添加 Sizer

使用 `addsizer_byidx` 为特定索引的策略设置 Sizer。

```python

# 添加第一个策略

strat1 = cerebro.addstrategy(MyStrategy1)

# 添加第二个策略

strat2 = cerebro.addstrategy(MyStrategy2)

# 为第二个策略设置专用 Sizer

cerebro.addsizer_byidx(strat2, bt.sizers.PercentSizer, percents=50)

```

### 在策略中设置 Sizer

在策略内部动态设置 Sizer。

```python
class MyStrategy(bt.Strategy):
    def __init__(self):

# 设置 Sizer
        self.setsizer(bt.sizers.PercentSizer(percents=30))

    def next(self):

# 不指定 size，使用 Sizer 计算
        self.buy()

```

### 直接获取仓位大小

在策略中直接调用 Sizer 获取仓位。

```python
class MyStrategy(bt.Strategy):
    def next(self):

# 获取买入仓位大小
        buy_size = self.getsizing(isbuy=True)

# 获取卖出仓位大小
        sell_size = self.getsizing(isbuy=False)

        if buy_size > 0:
            self.buy(size=buy_size)

```

## Sizer 属性

在 `_getsizing` 方法中可访问以下属性：

| 属性 | 类型 | 描述 |

|-----------|------|-------------|

| `strategy` | Strategy | 使用此 Sizer 的策略实例 |

| `broker` | Broker | 经纪人实例 |

```python
def _getsizing(self, comminfo, cash, data, isbuy):

# 访问策略
    position = self.strategy.getposition(data)

# 访问经纪人
    account_value = self.broker.getvalue()

# 访问佣金信息
    commission = comminfo.getcommission(size, price)

    return calculated_size

```

## 完整示例

```python
import backtrader as bt

class TestStrategy(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        if not self.position:
            if self.data.close[0] > self.sma[0]:

# 不指定 size，使用 Sizer 自动计算
                self.buy()
        else:
            if self.data.close[0] < self.sma[0]:
                self.sell()

# 创建 Cerebro

cerebro = bt.Cerebro()

# 添加数据

data = bt.feeds.YahooFinanceData(dataname='AAPL', fromdate='2020-01-01')
cerebro.adddata(data)

# 设置初始资金

cerebro.broker.setcash(10000)

# 添加 Sizer - 使用 30% 资金

cerebro.addsizer(bt.sizers.PercentSizer, percents=30)

# 添加策略

cerebro.addstrategy(TestStrategy)

# 运行

result = cerebro.run()

```

## 最佳实践

1. **始终检查可用资金**: 在 Sizer 中确保计算的仓位不超过可用资金

2. **返回整数**: 大多数经纪人要求整数仓位大小

3. **处理特殊情况**: 检查 ATR 等指标是否有足够的数据

4. **风险控制**: 将仓位大小限制在合理范围内，避免过度集中

5. **测试不同 Sizer**: 比较不同仓位管理策略的效果

## 下一步学习

- [Strategy API](strategy_zh.md) - 策略开发
- [Broker API](broker_zh.md) - 经纪人和订单管理
- [Indicator API](indicator_zh.md) - 技术指标开发
