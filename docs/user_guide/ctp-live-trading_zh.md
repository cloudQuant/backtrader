---
title: CTP 实盘交易指南
description: 使用 CTP 接口进行中国期货实盘和模拟交易
---

# CTP 实盘交易指南

CTP (Comprehensive Transaction Platform) 是中国期货市场最广泛使用的交易接口。本指南介绍如何使用 backtrader 的 CTP 模块进行实盘和模拟交易。

## CTP 介绍

CTP 是上海期货信息技术有限公司开发的综合交易平台，为期货公司提供标准化的交易和行情接口。

### 功能特性

- 支持中国所有期货交易所 (上期所、大商所、郑商所、中金所、能源中心、广期所)
- 实时行情订阅 (Tick 数据)
- 订单报单、撤单、查询
- 持仓查询、资金查询
- 自动重连机制
- SimNow 模拟环境支持

### 系统要求

```bash
# 安装依赖
pip install ctp-python akshare

# ctp-python: CTP 官方 C++ API 的 Python 包装
# akshare: 用于历史数据回填
```

## SimNow 模拟环境

SimNow 是上期技术提供的免费模拟交易环境，适合测试策略。

### 模拟环境地址

| 环境 | 交易服务器 | 行情服务器 | 数据时间 |
|------|-----------|-----------|---------|
| 电信 7x24 | `tcp://180.168.146.187:10101` | `tcp://180.168.146.187:10111` | 7x24 小时 |
| 电信 (最近) | `tcp://182.254.243.31:30001` | `tcp://182.254.243.31:30011` | 实盘时段 |
| 移动 7x24 | `tcp://180.168.146.187:10102` | `tcp://180.168.146.187:10112` | 7x24 小时 |

### 模拟账户配置

```python
# SimNow 默认配置
DEFAULT_BROKER_ID = "9999"
DEFAULT_APP_ID = "simnow_client_test"
DEFAULT_AUTH_CODE = "0000000000000000"

# 用户ID和密码需要在 SimNow 官网注册
# https://www.simnow.com.cn/
```

## 配置说明

### 基本配置参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `td_front` | 交易前置地址 | `tcp://180.168.146.187:10101` |
| `md_front` | 行情前置地址 | `tcp://180.168.146.187:10111` |
| `broker_id` | 期货公司代码 | `"9999"` (SimNow) |
| `user_id` | 用户代码 | `"your_id"` |
| `password` | 密码 | `"your_password"` |
| `app_id` | 应用代码 | `"simnow_client_test"` |
| `auth_code` | 授权码 | `"0000000000000000"` |

### 合约代码格式

CTP 合约代码格式：`合约代码.交易所代码`

```python
"rb2501.SHFE"    # 螺纹钢 2025年1月，上期所
"IF2506.CFFEX"   # 沪深300股指期货，中金所
"m2505.DCE"      # 豆粕，大商所
"TA501.CZCE"     # PTA，郑商所
"nr2411.INE"     # 20号胶，能源中心
"pb2501.GFEX"    # 工业硅，广期所
```

### 交易所代码

| 交易所 | 代码 | 主要品种 |
|--------|------|---------|
| 上海期货交易所 | SHFE | 铜、铝、锌、铅、镍、锡、黄金、白银、螺纹钢、热卷、燃油、沥青、橡胶 |
| 大连商品交易所 | DCE | 豆粕、豆油、棕榈油、玉米、淀粉、焦炭、焦煤、铁矿石、聚乙烯、聚丙烯、PVC |
| 郑州商品交易所 | CZCE | 白糖、棉花、PTA、菜油、菜粕、甲醇、玻璃、纯碱、尿素、短纤 |
| 中国金融期货交易所 | CFFEX | 沪深300股指、上证50股指、中证500股指、国债期货 |
| 上海国际能源交易中心 | INE | 原油、20号胶 |
| 广州期货交易所 | GFEX | 工业硅、碳酸锂 |

## 数据源设置

### 创建 CTP 数据源

```python
import backtrader as bt

# 方式 1: 通过 Store 创建
store = bt.stores.CTPStore(
    td_front='tcp://180.168.146.187:10101',
    md_front='tcp://180.168.146.187:10111',
    broker_id='9999',
    user_id='your_id',
    password='your_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
)

data = store.getdata(
    dataname='rb2501.SHFE',  # 合约代码
    timeframe=bt.TimeFrame.Minutes,  # 时间周期
    compression=1,  # 压缩比例
    num_init_backfill=100,  # 回填K线数量
)
```

### 数据源参数

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `historical` | `False` | 是否只使用历史数据，不接收实时行情 |
| `num_init_backfill` | `100` | 历史K线回填数量 |
| `tick_mode` | `False` | 是否使用 Tick 模式 (每笔交易一根K线) |
| `backfill_retries` | `2` | 历史数据回填重试次数 |

### 添加到 Cerebro

```python
cerebro = bt.Cerebro()

# 添加数据
cerebro.adddata(data)

# 或直接添加多个合约
for symbol in ['rb2501.SHFE', 'IF2506.CFFEX', 'm2505.DCE']:
    data = store.getdata(dataname=symbol, timeframe=bt.TimeFrame.Minutes)
    cerebro.adddata(data)
```

## 经纪人设置

### 设置 CTP 经纪人

```python
# 方式 1: 通过 Store 获取
broker = store.getbroker()
cerebro.setbroker(broker)

# 方式 2: 直接设置
cerebro.setbroker(bt.brokers.CTPBroker(
    td_front='tcp://180.168.146.187:10101',
    md_front='tcp://180.168.146.187:10111',
    broker_id='9999',
    user_id='your_id',
    password='your_password',
    app_id='simnow_client_test',
    auth_code='0000000000000000',
))
```

### 经纪人参数

| 参数 | 默认值 | 说明 |
|------|-------|------|
| `use_positions` | `True` | 启动时使用账户现有持仓 |
| `commission` | `0.0` | 每手手续费 (绝对值) |
| `stop_slippage_ticks` | `0.0` | 止损单最大滑点跳动数 |

## 订单管理

### 市价单

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # 市价买入 1 手
        self.buy(size=1)

        # 市价卖出 1 手
        self.sell(size=1)
```

### 限价单

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # 限价买入
        price = self.data.close[0] - 10  # 低于当前价格 10 点
        self.buy(price=price, size=1)

        # 限价卖出
        price = self.data.close[0] + 10
        self.sell(price=price, size=1)
```

### 止损单

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.entry_price = None

    def next(self):
        if not self.position:
            # 开仓
            self.buy(size=1)
            self.entry_price = self.data.close[0]
        else:
            # 止损: 价格跌破开仓价 2%
            stop_price = self.entry_price * 0.98
            self.sell(price=stop_price, exectype=bt.Order.Stop, size=1)

            # 止损限价单
            # self.sell(price=stop_price, plimit=stop_price-5,
            #           exectype=bt.Order.StopLimit, size=1)
```

### 撤单

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.order = None

    def next(self):
        if self.order:
            # 撤销待处理订单
            self.cancel(self.order)
            self.order = None

        # 下新单
        self.order = self.buy(size=1)
```

### 订单状态监控

```python
class MyStrategy(bt.Strategy):
    def notify_order(self, order):
        """订单状态变化通知"""
        status = order.getstatusname()

        if order.status in [order.Submitted, order.Accepted]:
            print(f'订单已提交: {order.ref}')

        elif order.status in [order.Completed]:
            if order.isbuy():
                print(f'买入成交: 价格={order.executed.price:.2f}, '
                      f'数量={order.executed.size}, 手续费={order.executed.comm:.2f}')
            else:
                print(f'卖出成交: 价格={order.executed.price:.2f}, '
                      f'数量={order.executed.size}, 手续费={order.executed.comm:.2f}')

        elif order.status in [order.Canceled]:
            print(f'订单已撤销: {order.ref}')

        elif order.status in [order.Rejected]:
            print(f'订单被拒绝: {order.ref}')
```

## 持仓管理

### 获取持仓信息

```python
class MyStrategy(bt.Strategy):
    def next(self):
        # 获取当前持仓
        pos = self.getposition()
        print(f'持仓数量: {pos.size}, 开仓均价: {pos.price:.2f}')

        # 获取可用资金
        cash = self.getcash()
        print(f'可用资金: {cash:.2f}')

        # 获取总资产
        value = self.getvalue()
        print(f'总资产: {value:.2f}')
```

### 自动平仓逻辑

```python
class MyStrategy(bt.Strategy):
    params = (
        ('max_hold_bars', 10),  # 最大持仓K线数
        ('target_profit_pct', 0.02),  # 目标利润 2%
    )

    def __init__(self):
        self.hold_bars = 0
        self.entry_price = None

    def next(self):
        if not self.position:
            self.buy(size=1)
            self.entry_price = self.data.close[0]
            self.hold_bars = 0
        else:
            self.hold_bars += 1

            # 止盈
            if self.data.close[0] >= self.entry_price * (1 + self.p.target_profit_pct):
                self.sell(size=1)
                return

            # 时间止损
            if self.hold_bars >= self.p.max_hold_bars:
                self.sell(size=1)
```

## 完整代码示例

### 简单双均线策略

```python
#!/usr/bin/env python
"""CTP 实盘交易示例 - 双均线策略"""

import backtrader as bt
import logging

logging.basicConfig(level=logging.INFO)

class DualMovingAverage(bt.Strategy):
    """双均线策略"""

    params = (
        ('fast_period', 5),
        ('slow_period', 20),
    )

    def __init__(self):
        # 计算均线
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

        self.order = None

    def next(self):
        # 只在无持仓时交易
        if self.order:
            return

        if not self.position:
            # 金叉买入
            if self.crossover > 0:
                self.order = self.buy(size=1)
                print(f'[金叉] 买入: 价格={self.data.close[0]:.2f}')
        else:
            # 死叉卖出
            if self.crossover < 0:
                self.order = self.sell(size=1)
                print(f'[死叉] 卖出: 价格={self.data.close[0]:.2f}')

    def notify_order(self, order):
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f'[成交] 买入: 价格={order.executed.price:.2f}, '
                      f'数量={order.executed.size}')
            else:
                print(f'[成交] 卖出: 价格={order.executed.price:.2f}, '
                      f'数量={order.executed.size}')
            self.order = None

def main():
    # 创建 Cerebro
    cerebro = bt.Cerebro()

    # 添加策略
    cerebro.addstrategy(DualMovingAverage, fast_period=5, slow_period=20)

    # 创建 CTP Store
    store = bt.stores.CTPStore(
        td_front='tcp://180.168.146.187:10101',
        md_front='tcp://180.168.146.187:10111',
        broker_id='9999',
        user_id='your_id',
        password='your_password',
        app_id='simnow_client_test',
        auth_code='0000000000000000',
    )

    # 添加数据
    data = store.getdata(
        dataname='rb2501.SHFE',
        timeframe=bt.TimeFrame.Minutes,
        compression=1,
        num_init_backfill=100,
    )
    cerebro.adddata(data)

    # 设置经纪人
    cerebro.setbroker(store.getbroker())

    # 设置初始资金
    cerebro.broker.setcash(100000.0)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

    print('=' * 50)
    print('开始实盘交易...')
    print(f'初始资金: {cerebro.broker.getvalue():.2f}')
    print('=' * 50)

    # 运行
    try:
        results = cerebro.run()
    except KeyboardInterrupt:
        print('\n交易已停止')

    print('=' * 50)
    print(f'最终资金: {cerebro.broker.getvalue():.2f}')
    print('=' * 50)

if __name__ == '__main__':
    main()
```

### 多品种策略

```python
#!/usr/bin/env python
"""多品种 CTP 实盘交易"""

import backtrader as bt

class MultiSymbolStrategy(bt.Strategy):
    """多品种策略"""

    def __init__(self):
        # 为每个数据源计算指标
        for data in self.datas:
            data.ma20 = bt.indicators.SMA(data.close, period=20)

    def next(self):
        for data in self.datas:
            # 检查该品种是否有持仓
            pos = self.getposition(data)

            if not pos:
                # 价格低于20日均线时买入
                if data.close[0] < data.ma20[0]:
                    self.buy(data=data, size=1)
                    print(f'{data._name}: 买入 @ {data.close[0]:.2f}')
            else:
                # 价格高于20日均线时卖出
                if data.close[0] > data.ma20[0]:
                    self.sell(data=data, size=1)
                    print(f'{data._name}: 卖出 @ {data.close[0]:.2f}')

def main():
    cerebro = bt.Cerebro()
    cerebro.addstrategy(MultiSymbolStrategy)

    # 创建 Store
    store = bt.stores.CTPStore(
        td_front='tcp://180.168.146.187:10101',
        md_front='tcp://180.168.146.187:10111',
        broker_id='9999',
        user_id='your_id',
        password='your_password',
        app_id='simnow_client_test',
        auth_code='0000000000000000',
    )

    # 添加多个品种
    symbols = ['rb2501.SHFE', 'm2505.DCE', 'IF2506.CFFEX']
    for symbol in symbols:
        data = store.getdata(
            dataname=symbol,
            timeframe=bt.TimeFrame.Minutes,
            compression=5,
        )
        cerebro.adddata(data, name=symbol)

    # 设置经纪人
    cerebro.setbroker(store.getbroker())
    cerebro.broker.setcash(1000000.0)

    # 运行
    cerebro.run()

if __name__ == '__main__':
    main()
```

## 风险控制

### 单品种最大持仓

```python
class RiskControlStrategy(bt.Strategy):
    params = (
        ('max_size', 5),  # 单品种最大持仓手数
    )

    def next(self):
        pos = self.getposition()

        # 检查持仓限制
        if abs(pos.size) >= self.p.max_size:
            return

        # 正常交易逻辑
        if not self.position:
            self.buy(size=1)
```

### 总持仓限制

```python
class TotalPositionLimitStrategy(bt.Strategy):
    params = (
        ('max_total_size', 10),  # 总持仓手数限制
    )

    def __init__(self):
        self.total_position = 0

    def next(self):
        # 计算总持仓
        self.total_position = sum(
            abs(self.getposition(data).size) for data in self.datas
        )

        if self.total_position >= self.p.max_total_size:
            return  # 达到总持仓限制

        # 正常交易逻辑
        ...
```

### 每日亏损限制

```python
class DailyLossLimitStrategy(bt.Strategy):
    params = (
        ('max_daily_loss', 5000),  # 最大日亏损
    )

    def __init__(self):
        self.daily_pnl = 0
        self.last_date = None

    def next(self):
        current_date = self.data.datetime.date(0)

        # 新的一天，重置盈亏
        if self.last_date != current_date:
            self.daily_pnl = 0
            self.last_date = current_date

        # 检查日亏损限制
        if self.daily_pnl <= -self.p.max_daily_loss:
            print(f'达到日亏损限制 {self.p.max_daily_loss}，停止交易')
            # 平掉所有持仓
            for data in self.datas:
                pos = self.getposition(data)
                if pos.size > 0:
                    self.sell(data=data, size=abs(pos.size))
                elif pos.size < 0:
                    self.buy(data=data, size=abs(pos.size))
            return

    def notify_trade(self, trade):
        if trade.isclosed:
            self.daily_pnl += trade.pnl
```

## 断线重连

CTP 模块内置自动重连机制，连接断开后会自动尝试重新连接。

### 监听连接状态

```python
class ConnectionMonitorStrategy(bt.Strategy):
    def __init__(self):
        # 注册断线回调
        self.o.store.on_disconnect(self.on_disconnect)
        self.o.store.on_reconnect(self.on_reconnect)

    def on_disconnect(self, reason):
        print(f'连接断开: 原因代码={reason}')

    def on_reconnect(self):
        print('连接已恢复')

    def next(self):
        # 检查连接状态
        if not self.o.store.is_connected:
            print('未连接，等待重连...')
            return

        # 正常交易逻辑
        ...
```

## 故障排除

### 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 连接超时 | 服务器地址错误或网络问题 | 检查服务器地址，确认网络连接 |
| 登录失败 | 用户名密码错误或账户被禁用 | 检查账户信息，联系期货公司 |
| 订单被拒 | 持仓不足、资金不足或合约不允许 | 检查账户状态，确认合约可交易 |
| 行情断流 | 行情服务器问题 | 系统会自动重连 |
| 数据回填失败 | akshare 未安装或网络问题 | 安装 akshare，检查网络连接 |

### 错误代码

| 错误代码 | 说明 |
|---------|------|
| 0 | 成功 |
| 3 | 未找到请求的合约 |
| 11 | 不支持的功能 |
| 17 | 不支持的行情 |
| 26 | 账户不存在 |
| 39 | 客户端未登录 |
| 42 | 报单被拒绝 |
| 45 | 平仓数量超过持仓 |
| 47 | 客户交易权限被暂停 |
| 48 | 客户开户状态被拒绝 |
| 75 | 登录失败 (频繁登录被禁) |
| 91 | 合约不存在或已下架 |

### 调试技巧

```python
# 启用详细日志
import logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
)

# 检查连接状态
store = bt.stores.CTPStore(...)
print(f'已连接: {store.is_connected}')
print(f'交易端已登录: {store.trader_spi.loggedin}')
print(f'行情端已登录: {store.md_spi.loggedin}')

# 检查账户信息
store.get_balance()
print(f'可用资金: {store.get_cash()}')
print(f'总资产: {store.get_value()}')

# 检查持仓
positions = store.get_positions()
for pos in positions:
    print(f'{pos["instrument"]} {pos["direction"]} '
          f'持仓:{pos["volume"]} 均价:{pos["avg_price"]:.2f}')
```

### 查询频率限制

CTP 接口有查询频率限制 (约 1 秒 1 次)，频繁查询可能被限流：

```python
# 错误: 在 next() 中频繁查询
def next(self):
    cash = self.getcash()  # 每个K线都查询

# 正确: 缓存查询结果
def __init__(self):
    self._last_cash = None
    self._cash_counter = 0

def next(self):
    self._cash_counter += 1
    if self._cash_counter % 10 == 0:  # 每10个K线查询一次
        self._last_cash = self.getcash()
```

## 实盘注意事项

1. **测试充分**: 在模拟环境充分测试后再接入实盘
2. **资金安全**: 首次使用小额资金测试
3. **异常处理**: 做好异常捕获和日志记录
4. **监控告警**: 设置持仓、盈亏、异常情况的告警
5. **数据备份**: 定期备份交易日志和策略参数
6. **网络稳定**: 确保网络连接稳定，考虑使用专线
7. **合约换月**: 注意合约到期换月处理
8. **交易时段**: 避开集合竞价和收盘前最后几分钟
9. **滑点风险**: 实盘滑点可能大于模拟，预留滑点空间

## 下一步学习

- [策略开发](strategies_zh.md) - 构建有效的交易策略
- [分析器](analyzers_zh.md) - 评估策略性能
- [观察器](observers_zh.md) - 监控策略行为
