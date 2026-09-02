# 订单类型实战：Bracket、OCO 与跟踪止损，把风险管理写进订单簿

> 量化策略图鉴 · 第 38 篇 · 分类 `order_types`（6 个策略）· 2026-09-02

策略决定"什么时候买卖"，订单决定"以什么方式买卖"。大多数回测教程只教你 `self.buy()`，然后假装它是免费的：立即、足额、无滑点地成交。真实市场里，止损单、限价单、OCO 组合的执行细节，往往比信号本身更影响净收益。一个常见的悲剧是：信号完美、入场精准，然后去吃饭忘了挂止损。

本篇解读 `tests/functional/strategies/order_types/` 下的 6 个订单类型回测。它们不是六种"策略思想"，而是策略与市场之间的六种接口契约——bracket 三件套如何让"下单即带止损"成为原子操作，OCO 如何让一组订单互斥成交。这一篇是"策略 + 框架功能"的结合写法。

## 分类速览

| 策略 | 数据 | 核心思想 | 源码 |
|------|------|----------|------|
| 止损单 | 可转债指数日线 | 金叉买入成交后自动挂 3% 止损卖单，死叉主动平仓 | `test_05_stop_order_strategy.py` |
| Bracket 三件套 | 2005-2006 日线 | 限价主单 + 止损 + 止盈打包提交，父单成交激活子单 | `test_37_bracket_order_strategy.py` |
| OCO 订单 | 2005-2006 日线 | 三张不同深度的限价买单联动，任一成交其余自动撤销 | `test_41_oco_order_strategy.py` |
| StopTrail 跟踪止损 | 2005-2006 日线 | 均线交叉入场模板，预留 trailpercent 跟踪止损参数 | `test_42_stoptrail_strategy.py` |
| Order Target | YHOO 2005-2006 日线 | 按日期计算目标仓位百分比，`order_target_percent` 调仓 | `test_43_order_target_strategy.py` |
| Order Close | 2005-2006 日线 | `exectype=bt.Order.Close` 以当根收盘价成交 | `test_61_order_close.py` |

## 深读一：Bracket 三件套——把止损变成原子操作

回测里"下单后忘记止损"不会发生，因为代码永远记得。但 bracket 单的价值在于把这种"记得"从策略逻辑下沉到订单结构本身：**主单、止损单、止盈单作为一个整体提交，主单成交的瞬间，两个子单自动激活；任一子单成交，另一个自动撤销**。人性漏洞被订单簿堵死。

实现（[test_37_bracket_order_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/order_types/test_37_bracket_order_strategy.py)）在金叉出现时一次性构造三张单：

```python
if self.cross > 0.0:
    close = self.data.close[0]
    p1 = close * (1.0 - self.p.limit)      # 主单：低 0.5% 的限价买单
    p2 = p1 - 0.02 * close                 # 止损：主单价下方 2% 收盘价
    p3 = p1 + 0.02 * close                 # 止盈：主单价上方 2% 收盘价

    o1 = self.buy(exectype=bt.Order.Limit, price=p1,
                  valid=valid1, transmit=False)
    o2 = self.sell(exectype=bt.Order.Stop, price=p2,
                   parent=o1, transmit=False)
    o3 = self.sell(exectype=bt.Order.Limit, price=p3,
                   parent=o1, transmit=True)   # 最后一张把三张一起发出
```

关键是 `transmit` 与 `parent` 两个参数：前两张单 `transmit=False` 暂扣在手里，直到第三张 `transmit=True` 才整组提交；`parent=o1` 声明母子关系，引擎据此在主单成交后激活子单、在一张子单成交后撤销另一张。2005-2006 数据上共触发 8 笔完整交易（4 胜 4 负，胜率 50%），终值 99,875.56——测试以 `abs(final_value - 99875.56) < 0.01` 锁定基线。注意主单是限价单且 3 天有效：若价格不回落，整组过期作废，这在牛市里会错过行情，也是 bracket 的代价之一。

## 深读二：OCO——一组订单，只有一个未来

OCO（One-Cancels-Other）解决另一个问题：**你想在回调时买入，但不知道会回调多深**。与其猜一个价位，不如在三个深度各挂一张限价单，并声明它们互斥——谁先成交，其余全部撤销。

[test_41_oco_order_strategy.py](https://github.com/cloudQuant/backtrader/blob/development/tests/functional/strategies/order_types/test_41_oco_order_strategy.py) 在金叉时挂出三张买单，深度按平方、立方递增：

```python
p1 = self.data.close[0] * (1.0 - self.p.limit)          # 低 0.5%
p2 = self.data.close[0] * (1.0 - 2 * 2 * self.p.limit)  # 低 2%
p3 = self.data.close[0] * (1.0 - 3 * 3 * self.p.limit)  # 低 4.5%

o1 = self.buy(exectype=bt.Order.Limit, price=p1, valid=valid1, size=1)
o2 = self.buy(exectype=bt.Order.Limit, price=p2, valid=valid2, oco=o1, size=1)
o3 = self.buy(exectype=bt.Order.Limit, price=p3, valid=valid3, oco=o1, size=1)
```

`oco=o1` 把后两张单挂到第一张的 OCO 组里；近端单只给 3 天有效期（`limdays=3`），远端单给 1000 天——赌"浅回调很快出现，深回调值得等"。成交后持有 10 根 K 线按时间平仓。回测终值 99,936.20，Sharpe 为 -728 这种极端值并非 bug，而是"单笔 1 股小仓位 + 稀疏交易"下年化波动极小导致的比值放大——测试注释特意说明：这些数值确认的是 **OCO 撤销机制工作正常**，而非策略盈利能力。这正是回归测试的本分：验证的是框架行为，不是收益。

## 其余策略，快速点将

- **止损单**（`test_05`）：可转债指数上，买入成交后在 `notify_order` 里立刻挂 `self.sell(exectype=bt.Order.Stop, price=buy_price * 0.97)`；死叉出现则先 `self.cancel(stop_order)` 再市价平仓——"先撤后平"的顺序是管理挂单的经典细节。全程 211 次买入、106 次被止损扫出。
- **StopTrail**（`test_42`）：脱胎于官方 stoptrail 样例，参数里保留 `trailpercent=0.02`；本版 `next()` 实际以金叉/死叉市价单驱动（终值 105,190.30、Sharpe 1.19），把它改造成真正的 `sell(exectype=bt.Order.StopTrail, trailpercent=0.02)` 是最好的练习题。
- **Order Target**（`test_43`）：不写买卖方向，只声明目标——奇数月仓位 = 日期/100，偶数月 = (31-日期)/100，`order_target_percent` 自动算出差额下单。这是从"交易思维"切换到"仓位管理思维"的入口。
- **Order Close**（`test_61`）：`exectype=bt.Order.Close` 让订单以当根收盘价成交（配合 `seteosbar(True)`），省掉"次日开盘成交"的一根 K 线延迟，终值 102,995.50。

## 一条命令跑起来

```bash
# 整个分类（6 个策略，runonce/runnext 双模式自动对拍）
pytest tests/functional/strategies/order_types/ -v

# 只跑 Bracket 三件套
pytest tests/functional/strategies/order_types/test_37_bracket_order_strategy.py -v
```

## 为什么在这个项目上研究订单类型

订单类型是回测保真度最容易失真的地方：限价单是否触及就成交、止损单的触发价与成交价差异、OCO 撤销的时序——每一处都依赖经纪商模拟器的实现精度。[cloudQuant/backtrader](https://github.com/cloudQuant/backtrader) 用 1,152 个策略回归测试把这些行为钉死成断言基线，任何订单语义的漂移都会立刻报警；runonce/runnext 双引擎对拍则保证向量化加速没有改变订单撮合的结果。纯 Python 引擎比原版快 46%，装上 C++ 后端（`pip install back-trader-cpp`）中位 128 倍加速——足够你把六种订单类型在同一份数据上排列组合，找出属于你的那一份执行细节。

觉得有用，去 [GitHub](https://github.com/cloudQuant/backtrader) 给个 Star；想系统学习，从[系列总览](00-overview.md)开始。

> 风险提示：本篇仅供教育与研究目的。以上回测均基于历史数据，不构成投资建议；算法交易存在重大亏损风险。
