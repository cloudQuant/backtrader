# WebSocket 实时数据流使用指南

本文档说明如何在 backtrader-ccxt 中使用 WebSocket 获取实时市场数据。

## 目录

1. [概述](#概述)
2. [安装依赖](#安装依赖)
3. [三种数据获取方式对比](#三种数据获取方式对比)
4. [使用 WebSocket](#使用-websocket)
5. [配置参数](#配置参数)
6. [故障排除](#故障排除)

---

## 概述

backtrader-ccxt 支持三种数据获取方式：

| 方式 | 延迟 | API 配额 | 复杂度 | 依赖 |
|------|------|----------|--------|------|
| **REST 轮询** | 高（每分钟请求） | 消耗大 | 低 | 只需 ccxt |
| **多线程** | 中 | 中等 | 中 | 只需 ccxt |
| **WebSocket** | **极低（推送）** | **极低**** | 中 | **ccxt.pro** |

### WebSocket 优势

- **低延迟**：数据由交易所推送，无需轮询
- **节省配额**：不消耗 REST API 请求配额
- **实时性**：K线收盘后立即推送
- **多交易对**：可同时订阅多个交易对

---

## 安装依赖

### 1. 安装 ccxt.pro

```bash
pip install ccxtpro
```

或者使用国内镜像：

```bash
pip install ccxt.pro -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 验证安装

```python
import ccxt.pro
print(ccxt.__version__)  # 应显示版本号
```

---

## 三种数据获取方式对比

### 方式 1：REST 轮询（默认）

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    # 不指定 use_websocket，默认使用 REST
)
```

**特点**：
- 每分钟发起一次 HTTP 请求
- 适合不频繁运行的策略
- 简单可靠

### 方式 2：多线程

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_threaded_data=True,  # 启用多线程
)
```

**特点**：
- 后台线程定时获取数据
- 主线程不阻塞
- 仍消耗 REST API 配额

### 方式 3：WebSocket（推荐）

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_websocket=True,  # 使用 WebSocket
)
```

**特点**：
- 极低延迟
- 交易所主动推送
- 最节省配额

---

## 使用 WebSocket

### 基础示例

```python
import backtrader as bt
from backtrader.stores.ccxtstore import CCXTStore
from backtrader.feeds.ccxtfeed import CCXTFeed

# 创建 Store
store = CCXTStore(
    exchange='okx',
    currency='USDT',
    config={'apiKey': 'xxx', 'secret': 'xxx', 'password': 'xxx'},
)

# 创建数据源，使用 WebSocket
data = CCXTFeed(
    store=store,
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(minutes=100),  # 历史数据
    backfill_start=True,      # 先加载历史数据
    historical=False,         # 历史数据后继续实时模式
    use_websocket=True,       # 启用 WebSocket
)

cerebro = bt.Cerebro()
cerebro.adddata(data)
cerebro.run()
```

### 完整策略示例

```python
#!/usr/bin/env python
import backtrader as bt
from backtrader.stores.ccxtstore import CCXTStore

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.dataclose = self.data.close

    def next(self):
        if len(self.data) >= 10:  # 等待足够数据
            print(f"Price: {self.data.close[0]}")

# 创建引擎
cerebro = bt.Cerebro()

# 添加策略
cerebro.addstrategy(MyStrategy)

# 设置初始资金
cerebro.broker.setcash(1000)

# 创建 Store
store = CCXTStore(
    exchange='okx',
    currency='USDT',
    config={'apiKey': 'your_key', 'secret': 'your_secret', 'password': 'your_pass'}
)

# 创建数据源 - 使用 WebSocket
data = store.getdata(
    dataname='BTC/USDT',
    name='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(minutes=100),
    use_websocket=True,
    backfill_start=True,
    historical=False
)

cerebro.adddata(data)
cerebro.run()
```

---

## 配置参数

### CCXTFeed 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `use_websocket` | `False` | 是否启用 WebSocket |
| `use_threaded_data` | `False` | 是否启用多线程 |
| `ohlcv_limit` | `100` | 每次获取的最大K线数 |
| `drop_newest` | `False` | 是否丢弃最新K线（可能未完成） |
| `ws_reconnect_delay` | `5.0` | WebSocket 重连延迟（秒） |
| `ws_max_reconnect_delay` | `60.0` | WebSocket 最大重连延迟（秒） |
| `debug` | `False` | 是否输出调试信息 |

### WebSocket 支持的交易所

以下交易所支持 ccxt.pro WebSocket：

| 交易所 | 支持状态 |
|--------|----------|
| Binance | ✅ 完整支持 |
| OKX | ✅ 完整支持 |
| Bybit | ✅ 完整支持 |
| KuCoin | ✅ 完整支持 |
| Bitget | ✅ 部分支持 |
| Kraken | ✅ 部分支持 |

> **注意**：不同交易所的 WebSocket 实现可能有所不同，请以实际测试为准。

---

## 数据流程

### WebSocket 数据流程

```
┌─────────────────────────────────────────────────────────────┐
│                    交易所 WebSocket 服务器                        │
│                         ↑                                       │
│                         │ 推送                                   │
│                         │                                       │
┌────────────────────────┴─────────────────────────────────────────┐
│              ccxt.pro WebSocket 客户端 (后台线程)                  │
│                        │                                       │
│                        │ watch_ohlcv()                        │
│                        │                                       │
│                 ┌──────┴────────────────┐                          │
│                 │                       │                          │
│             ┌───┴────┐              ┌────┴──────────┐              │
│             │ Queue │              │ CCXTWebSocket   │              │
│             └───┬────┘              │    Manager      │              │
│                 │                    └──────────────────┘              │
│                 │                                                   │
│                 │                                                   │
┌────────────────┴─────────────────────────────────────────────────┐
│                  backtrader 主线程                                │
│                                                             │
│  cerebro.run() → next() → _load() → _load_bar()             │
│                     ↑                                       │
│                     │ 从 Queue 读取                             │
│                     │                                       │
│                 ┌───┴────────┐                                     │
│                 │ CCXTFeed   │                                     │
│                 └────────────┘                                     │
└─────────────────────────────────────────────────────────────┘
```

### 工作流程

1. **历史数据加载**（REST API）
   - 策略启动时使用 REST API 加载历史K线
   - 用于初始化技术指标（如布林带、ATR等）
   - 不触发任何交易信号

2. **切换到实时模式**（WebSocket）
   - 历史数据加载完成后发送 `LIVE` 通知
   - 启动 WebSocket 连接
   - 订阅实时 OHLCV 数据

3. **实时数据推送**
   - 交易所每分钟推送新的K线数据
   - 通过 WebSocket 回调放入队列
   - 主线程从队列读取并更新策略

4. **断线重连**
   - 自动检测连接状态
   - 指数退避重连（1秒 → 2秒 → 4秒...）
   - 重连后自动恢复订阅

---

## 故障排除

### 问题 1：WebSocket 不可用

**错误信息**：
```
[WS] WebSocket not available. Install ccxt.pro: pip install ccxtpro
```

**解决方法**：
```bash
pip install ccxtpro
```

### 问题 2：连接失败

**错误信息**：
```
WebSocket connection error: ...
```

**可能原因**：
1. 网络问题
2. 交易所维护
3. API 密钥错误

**解决方法**：
- 检查网络连接
- 验证 API 密钥
- 查看 OKX 状态页

### 问题 3：没有数据推送

**排查步骤**：
1. 检查交易对是否正确
2. 确认交易所支持该交易对的 WebSocket
3. 启用 `debug=True` 查看详细信息

```python
data = store.getdata(
    ...
    debug=True,  # 输出调试信息
)
```

### 问题 4：数据重复或缺失

**可能原因**：
- 时区问题
- 交易所时钟不准确

**解决方法**：
- 使用 `drop_newest=True` 丢弃可能不完整的最新K线
- 确保系统时间准确

---

## 最佳实践

### 1. 生产环境配置

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    fromdate=datetime.utcnow() - timedelta(minutes=500),
    backfill_start=True,
    historical=False,
    use_websocket=True,          # 使用 WebSocket
    ohlcv_limit=100,
    drop_newest=True,            # 丢弃可能不完整的K线
    ws_reconnect_delay=5.0,       # 重连延迟
    ws_max_reconnect_delay=60.0,  # 最大重连延迟
)
```

### 2. 多交易对订阅

```python
# 为多个交易对创建数据源
symbols = ['BTC/USDT', 'ETH/USDT', 'MINA/USDT:USDT']

for symbol in symbols:
    data = store.getdata(
        dataname=symbol,
        timeframe=bt.TimeFrame.Minutes,
        use_websocket=True,
        ...
    )
    cerebro.adddata(data)
```

### 3. 错误处理

在策略中添加错误处理：

```python
class MyStrategy(bt.Strategy):
    def notify_data(self, data, status, *args, **kwargs):
        if status == data.DISCONNECTED:
            self.log('[ERROR] 数据连接断开！')
            # 可以在这里添加告警逻辑

    def notify_order(self, order):
        if order.status in [order.Rejected, order.Margin]:
            self.log(f'[ERROR] 订单失败: {order.status}')
```

---

## 性能对比

### API 调用次数（运行1小时）

| 方式 | API 调用次数 | 说明 |
|------|-------------|------|
| REST 轮询 | ~60 次 | 每分钟请求一次 |
| 多线程 | ~60 次 | 仍然是 REST，只是后台执行 |
| WebSocket | ~2 次 | 只在开始时连接 + 可能重连 |

### 数据延迟

| 方式 | 延迟 |
|------|------|
| REST 轮询 | 100-500ms |
| WebSocket | 10-50ms |

---

## 相关文档

- [CCXT 官方文档](https://docs.ccxt.com/)
- [ccxt.pro 文档](https://docs.ccxt.com/#prox)
- [backtrader 文档](https://www.backtrader.com/docu/)
- [策略配置指南](./STRATEGY_GUIDE.md)
