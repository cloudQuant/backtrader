# CCXT 实盘交易指南

> 更新日期: 2026-02-24

本指南介绍如何使用 Backtrader + CCXT 进行加密货币实盘交易。

---

## 1. 快速开始

### 1.1 安装依赖

```bash
pip install ccxt        # REST API
pip install ccxtpro     # WebSocket (可选但推荐)
```

### 1.2 配置交易所

**方式 A: 直接传参**

```python
import backtrader as bt

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_api_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
    }
)
```

**方式 B: 使用 .env 文件 (推荐)**

创建 `.env` 文件:
```env
EXCHANGE_ID=binance
EXCHANGE_API_KEY=your_api_key
EXCHANGE_SECRET=your_secret
EXCHANGE_CURRENCY=USDT
```

```python
from backtrader.ccxt.config_helper import load_exchange_config

config = load_exchange_config()
store = bt.stores.CCXTStore(**config)
```

### 1.3 最小实盘示例

```python
import backtrader as bt

class SimpleStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)

    def next(self):
        if self.data.close[0] > self.sma[0] and not self.position:
            self.buy(size=0.001)
        elif self.data.close[0] < self.sma[0] and self.position:
            self.sell(size=0.001)

# 创建引擎
cerebro = bt.Cerebro()

# 创建 Store
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'YOUR_KEY',
        'secret': 'YOUR_SECRET',
        'enableRateLimit': True,
    }
)

# 添加数据源 (REST 轮询)
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=15,
    ohlcv_limit=100,
    drop_newest=True,
)
cerebro.adddata(data)

# 设置 Broker
broker = store.getbroker()
cerebro.setbroker(broker)

# 添加策略
cerebro.addstrategy(SimpleStrategy)

# 运行
cerebro.run()
```

---

## 2. 数据源配置

### 2.1 REST 轮询模式 (默认)

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=15,
    ohlcv_limit=100,       # 每次请求获取的 bar 数量
    drop_newest=True,       # 丢弃最新未完成 bar
    historical=False,       # False = 实时模式
    backfill_start=True,    # 启动时回补历史数据
)
```

### 2.2 WebSocket 模式 (推荐，低延迟)

需要安装 `ccxtpro`:

```python
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=1,
    use_websocket=True,                # 启用 WebSocket
    ws_reconnect_delay=5.0,            # 重连延迟 (秒)
    ws_max_reconnect_delay=60.0,       # 最大重连延迟
    ws_health_check_interval=30.0,     # 健康检查间隔
    backfill_start=True,
)
```

**WebSocket 特性**:
- 自动重连 (指数退避: 5s → 10s → 20s → ... → 60s)
- 断线时自动回退到 REST 轮询
- 重连后自动数据回补 (间隔 > 60s 时触发)
- Stale connection 检测

### 2.3 历史数据模式

```python
from datetime import datetime

data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=60,
    historical=True,                    # 仅获取历史数据
    fromdate=datetime(2025, 1, 1),
    todate=datetime(2025, 12, 31),
    ohlcv_limit=500,
)
```

---

## 3. Broker 配置

### 3.1 基础配置

```python
broker = store.getbroker(
    debug=False,                        # 调试输出
    use_threaded_order_manager=True,    # 后台订单检查 (推荐)
    max_retries=3,                      # API 重试次数
    retry_delay=1.0,                    # 重试基础延迟 (秒)
)
cerebro.setbroker(broker)
```

### 3.2 ThreadedOrderManager

启用后，订单状态检查在后台线程运行，不阻塞策略主循环:

```python
broker = store.getbroker(
    use_threaded_order_manager=True,    # 启用
)
```

**优势**:
- 策略 `next()` 不因 API 延迟阻塞
- 订单更新通过线程安全队列传递
- 自动清理已完成/取消的订单

### 3.3 错误处理

Broker 内置了完善的错误处理:

| 场景 | 行为 |
|------|------|
| 网络超时 | 自动重试 (最多 3 次, 指数退避) |
| 交易所不可用 | 自动重试 |
| 余额不足 | 拒绝订单, 通知策略 |
| 订单不存在 | 标记取消, 从跟踪列表移除 |
| 交易所断连 | 跳过 API 调用, 等待重连 |
| 连续失败 ≥ 10 次 | 轮询间隔从 3s 退避到 30s |

**在策略中处理订单通知**:

```python
class MyStrategy(bt.Strategy):
    def notify_order(self, order):
        if order.status in [order.Completed]:
            print(f'订单完成: {order.executed.price}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f'订单失败: {order.getstatusname()}')
```

---

## 4. 交易所特定配置

### 4.1 使用 ExchangeConfig

```python
from backtrader.ccxt.config import ExchangeConfig

# 获取交易所默认参数
params = ExchangeConfig.get_params('binance')
# {'rateLimit': 1200, 'enableRateLimit': True, ...}

# 获取费率
fees = ExchangeConfig.get_fees('binance')
# {'maker': 0.001, 'taker': 0.001}

# 合并用户配置与默认配置
config = ExchangeConfig.merge_config('okx', {
    'apiKey': 'your_key',
    'secret': 'your_secret',
    'password': 'your_passphrase',
})
```

### 4.2 支持的交易所

| 交易所 | exchange_id | 特殊配置 |
|--------|-------------|----------|
| Binance | `binance` | 期货需 `defaultType: 'future'` |
| OKX | `okx` | 需要 `password` (passphrase) |
| Bybit | `bybit` | 期货需 `defaultType: 'linear'` |
| Bitget | `bitget` | 需要 `password` |
| Gate.io | `gate` | — |
| Huobi | `huobi` | — |

### 4.3 期货交易示例 (Binance)

```python
store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'your_key',
        'secret': 'your_secret',
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',    # 期货模式
        },
    }
)
```

---

## 5. 限流管理

### 5.1 自动限流

CCXTStore 自动集成 RateLimiter:

```python
# 默认: 根据交易所配置自动设置
store = bt.stores.CCXTStore(exchange='binance', ...)

# 自定义 RPM (每分钟请求数)
from backtrader.ccxt.ratelimit import RateLimiter
limiter = RateLimiter(requests_per_minute=600)
```

### 5.2 自适应限流

```python
from backtrader.ccxt.ratelimit import AdaptiveRateLimiter

limiter = AdaptiveRateLimiter(
    initial_rpm=1200,    # 初始 RPM
    min_rpm=60,          # 最低 RPM (被限流时)
    max_rpm=2400,        # 最高 RPM (无错误时逐步提升)
)
```

---

## 6. 连接管理

### 6.1 ConnectionManager

自动管理连接健康和重连:

```python
from backtrader.ccxt.connection import ConnectionManager

# 通常不需要手动创建, CCXTStore 自动管理
# 但可以注册回调:
manager = store._connection_manager  # 如果存在

manager.on_disconnect(lambda: print("交易所断连!"))
manager.on_reconnect(lambda: print("已重新连接"))
```

### 6.2 重连机制

```
断线检测 (health check 失败)
    │
    ├── 触发 disconnect 回调
    │
    └── 重连循环 (指数退避):
        ├── 第 1 次: 等待 5s
        ├── 第 2 次: 等待 10s
        ├── 第 3 次: 等待 20s
        ├── ...
        └── 最大: 等待 60s
            │
            └── 重连成功
                ├── 触发 reconnect 回调
                └── 回补缺失数据
```

---

## 7. 完整实盘模板

```python
import backtrader as bt
from datetime import datetime

class LiveStrategy(bt.Strategy):
    params = (
        ('fast', 10),
        ('slow', 30),
        ('stake', 0.001),
    )

    def __init__(self):
        super().__init__()
        self.fast_sma = bt.indicators.SMA(self.data, period=self.p.fast)
        self.slow_sma = bt.indicators.SMA(self.data, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.fast_sma, self.slow_sma)
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status in [order.Completed]:
            if order.isbuy():
                print(f'[BUY] Price: {order.executed.price:.2f}, '
                      f'Size: {order.executed.size:.6f}')
            else:
                print(f'[SELL] Price: {order.executed.price:.2f}, '
                      f'Size: {order.executed.size:.6f}')
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            print(f'[ORDER FAILED] {order.getstatusname()}')
        self.order = None

    def next(self):
        if self.order:
            return

        if not self.position:
            if self.crossover > 0:
                self.order = self.buy(size=self.p.stake)
        else:
            if self.crossover < 0:
                self.order = self.sell(size=self.p.stake)


# === 配置 ===
cerebro = bt.Cerebro()

store = bt.stores.CCXTStore(
    exchange='binance',
    currency='USDT',
    config={
        'apiKey': 'YOUR_KEY',
        'secret': 'YOUR_SECRET',
        'enableRateLimit': True,
    }
)

# WebSocket 数据源
data = store.getdata(
    dataname='BTC/USDT',
    timeframe=bt.TimeFrame.Minutes,
    compression=5,
    use_websocket=True,
    backfill_start=True,
    ohlcv_limit=100,
    drop_newest=True,
)
cerebro.adddata(data)

# Broker (带后台订单检查)
broker = store.getbroker(
    use_threaded_order_manager=True,
    max_retries=3,
)
cerebro.setbroker(broker)

# 策略
cerebro.addstrategy(LiveStrategy)

# 运行
print('Starting live trading...')
cerebro.run()
```

---

## 8. 常见问题

### Q: WebSocket 连接失败怎么办?

确认已安装 `ccxtpro`:
```bash
pip install ccxtpro
```
如果交易所不支持 WebSocket，系统会自动回退到 REST 轮询。

### Q: 如何查看 API 调用日志?

```python
broker = store.getbroker(debug=True)
data = store.getdata(..., debug=True)
```

### Q: 订单一直 Submitted 状态?

可能原因:
1. 价格偏离市场太远 (限价单)
2. 交易所 API 延迟
3. 网络问题导致状态更新失败

解决: 启用 `use_threaded_order_manager=True`，订单状态在后台持续检查。

### Q: 如何支持多品种?

```python
data_btc = store.getdata(dataname='BTC/USDT', ...)
data_eth = store.getdata(dataname='ETH/USDT', ...)
cerebro.adddata(data_btc)
cerebro.adddata(data_eth)
```

### Q: 如何处理资金费率?

使用 `ccxtfeed_funding.py`:
```python
from backtrader.feeds.ccxtfeed_funding import CCXTFeedWithFunding

data = CCXTFeedWithFunding(
    store=store,
    dataname='BTC/USDT',
    use_websocket=True,
)
```

---

## 9. 参考

| 文档 | 路径 |
|------|------|
| 架构文档 | `docs/ARCHITECTURE.md` |
| WebSocket 详细指南 | `docs/WEBSOCKET_GUIDE.md` |
| 资金费率指南 | `docs/FUNDING_RATE_GUIDE.md` |
| 环境配置 | `CCXT_ENV_CONFIG.md` |
| CCXT 需求文档 | `docs/opts/优化需求/迭代94-CCXT实盘交易优化-完整版.md` |
| 测试 | `tests/new_functions/test_ccxt_*.py` |
