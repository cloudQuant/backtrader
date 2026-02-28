# 多策略架构：单数据源 + 订单路由

## 场景描述

在同一个合约上运行多个策略（参数不同）时，面临两个核心问题：

1. **重复订阅**：每个策略都订阅相同的 WebSocket 数据（K 线、Tick），造成资源浪费
2. **订单混淆**：多个策略的订单需要区分来源，避免混淆

## 解决方案

```bash
┌────────────────────────────────────────────────────────────────────────┐
│                          数据源进程 (data_feed.py)                      │
│                                                                         │
│  ┌──────────┐                                                          │
│  │  OKX     │  WebSocket: OP-USDT (仅订阅一次)                          │
│  │          │  ← K 线 1m, Tick                                          │
│  └────┬─────┘                                                          │
│       │                                                                │
│       ↓                                                                │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │                    ZeroMQ Publisher                             │  │
│  │                                                                  │  │
│  │   publish("market.OP-USDT.kline.1m", kline_data)                │  │
│  │   publish("market.OP-USDT.tick",   tick_data)                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ ZeroMQ (IPC)
                                    ↓
┌────────────────────────────────────────────────────────────────────────┐
│                           策略进程 (strategy.py)                        │
│                                                                         │
│   ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐    │
│   │   策略 A         │   │   策略 B         │   │   策略 C         │    │
│   │   (参数组 1)      │   │   (参数组 2)      │   │   (参数组 3)      │    │
│   │                 │   │                 │   │                 │    │
│   │  Subscriber     │   │  Subscriber     │   │  Subscriber     │    │
│   │  "market.OP-    │   │  "market.OP-    │   │  "market.OP-    │    │
│   │   USDT."        │   │   USDT."        │   │   USDT."        │    │
│   │        ↓        │   │        ↓        │   │        ↓        │    │
│   │  策略逻辑       │   │  策略逻辑       │   │  策略逻辑       │    │
│   │        ↓        │   │        ↓        │   │        ↓        │    │
│   │  Publisher      │   │  Publisher      │   │  Publisher      │    │
│   │  "order.A"      │   │  "order.B"      │   │  "order.C"      │    │
│   └─────────────────┘   └─────────────────┘   └─────────────────┘    │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ ZeroMQ (IPC)
                                    ↓
┌────────────────────────────────────────────────────────────────────────┐
│                        订单网关进程 (order_gateway.py)                  │
│                                                                         │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                    ZeroMQ Subscriber                           │  │
│   │   subscribe("order.") → 接收所有策略订单                        │  │
│   └──────────────────────────────────────────────────────────────────┘  │
│                                    ↓                                   │
│   ┌─────────────────────────────────────────────────────────────────┐  │
│   │                      订单处理逻辑                               │  │
│   │   1. 识别 strategy_id                                           │  │
│   │   2. 策略级风控（限流、仓位等）                                  │  │
│   │   3. 调用 BtApi 下单                                            │  │
│   └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘

```bash

- --

## 核心组件

### 1. 数据源进程 (data_feed.py)

- *职责**：订阅 OKX WebSocket，发布行情数据到 ZeroMQ

```python

# data_feed.py

import time
import pickle
import zmq
from bt_api_py import BtApi

class MarketDataPublisher:
    """行情数据发布端"""

    def __init__(self, bind_addr: str = "ipc:///tmp/market_data.ipc"):
        self.ctx = zmq.Context()
        self.socket = self.ctx.socket(zmq.PUB)
        self.socket.bind(bind_addr)
        self.bind_addr = bind_addr
        print(f"[数据源] ZeroMQ 绑定到 {bind_addr}")

    def publish_kline(self, symbol: str, period: str, kline_data: dict):
        """发布 K 线数据"""
        topic = f"market.{symbol}.kline.{period}"
        self.socket.send_multipart([topic.encode(), pickle.dumps(kline_data)])

    def publish_tick(self, symbol: str, tick_data: dict):
        """发布 Tick 数据"""
        topic = f"market.{symbol}.tick"
        self.socket.send_multipart([topic.encode(), pickle.dumps(tick_data)])


def run_data_feed():
    """运行数据源进程"""
    exchange_kwargs = {
        "OKX___SWAP": {
            "public_key": "your_public_key",
            "private_key": "your_private_key",
            "passphrase": "your_passphrase",
        }
    }

    bt_api = BtApi(exchange_kwargs, debug=True)
    publisher = MarketDataPublisher()

    symbol = "OP-USDT"

# 订阅 K 线 和 Tick (只订阅一次！)
    bt_api.subscribe(f"OKX___SWAP___{symbol}", topics=[
        {"topic": "kline", "symbol": symbol, "period": "1m"},
        {"topic": "tick", "symbol": symbol},
    ])

    print(f"[数据源] 已订阅 {symbol} 的 K 线和 Tick 数据")

    data_queue = bt_api.get_data_queue("OKX___SWAP")

    while True:
        try:
            data = data_queue.get(timeout=1)

            if hasattr(data, 'symbol'):  # K 线数据
                publisher.publish_kline(
                    symbol=data.symbol,
                    period="1m",
                    kline_data={
                        "symbol": data.symbol,
                        "open": data.open,
                        "high": data.high,
                        "low": data.low,
                        "close": data.close,
                        "volume": data.volume,
                        "timestamp": data.timestamp,
                    }
                )
            elif hasattr(data, 'last_price'):  # Tick 数据
                publisher.publish_tick(
                    symbol=data.symbol,
                    tick_data={
                        "symbol": data.symbol,
                        "last_price": data.last_price,
                        "bid_price": data.bid_price,
                        "ask_price": data.ask_price,
                        "timestamp": data.timestamp,
                    }
                )
        except Exception as e:
            print(f"[数据源] 错误: {e}")
            continue

```bash

- --

### 2. 策略基类 (strategy.py)

- *职责**：订阅行情数据，实现策略逻辑，发送订单

```python

# strategy.py

import pickle
import zmq
from dataclasses import dataclass
from typing import Callable

@dataclass
class OrderRequest:
    """统一订单格式"""
    strategy_id: str
    symbol: str
    side: str      # buy / sell
    volume: float
    price: float
    order_type: str  # limit / market


class StrategyBase:
    """策略基类 - 处理数据订阅和订单发送"""

    def __init__(self,
                 strategy_id: str,
                 strategy_name: str,
                 market_data_addr: str = "ipc:///tmp/market_data.ipc",
                 order_addr: str = "ipc:///tmp/orders.ipc"):

        self.strategy_id = strategy_id
        self.strategy_name = strategy_name

# 订阅行情数据
        self.sub_ctx = zmq.Context()
        self.sub_socket = self.sub_ctx.socket(zmq.SUB)
        self.sub_socket.connect(market_data_addr)

# 订阅指定合约的所有数据
        self.sub_socket.setsockopt(zmq.SUBSCRIBE, b"market.OP-USDT.")

        print(f"[{strategy_id}] 已订阅行情数据")

# 订单发布
        self.pub_ctx = zmq.Context()
        self.pub_socket = self.pub_ctx.socket(zmq.PUB)
        self.pub_socket.connect(order_addr)

        print(f"[{strategy_id}] 订单发送器已连接")

# 回调函数
        self.on_kline_callback = None
        self.on_tick_callback = None

    def on_kline(self, func: Callable):
        """注册 K 线回调"""
        self.on_kline_callback = func
        return func

    def on_tick(self, func: Callable):
        """注册 Tick 回调"""
        self.on_tick_callback = func
        return func

    def send_order(self, symbol: str, side: str, volume: float,
                   price: float, order_type: str = "limit"):
        """发送订单（自动带上 strategy_id）"""
        order = OrderRequest(
            strategy_id=self.strategy_id,
            symbol=symbol,
            side=side,
            volume=volume,
            price=price,
            order_type=order_type,
        )

        topic = f"order.{self.strategy_id}"
        self.pub_socket.send_multipart([topic.encode(), pickle.dumps(order)])
        print(f"[{self.strategy_id}] 发送订单: {side} {volume} {symbol} @ {price}")

    def run(self):
        """运行策略主循环"""
        print(f"[{self.strategy_id}] 策略启动...")

        while True:
            try:
                topic_bytes, data_bytes = self.sub_socket.recv_multipart()
                data = pickle.loads(data_bytes)
                topic = topic_bytes.decode()

                if ".kline." in topic:
                    if self.on_kline_callback:
                        self.on_kline_callback(data)
                elif ".tick" in topic:
                    if self.on_tick_callback:
                        self.on_tick_callback(data)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[{self.strategy_id}] 错误: {e}")
                continue

```bash

- --

### 3. 订单网关 (order_gateway.py)

- *职责**：接收策略订单，执行风控，调用 BtApi 下单

```python

# order_gateway.py

import pickle
import zmq
from bt_api_py import BtApi

class OrderGateway:
    """订单网关 - 接收策略订单并执行"""

    def __init__(self,
                 bind_addr: str = "ipc:///tmp/orders.ipc",
                 exchange_kwargs: dict = None):

        if exchange_kwargs is None:
            exchange_kwargs = {
                "OKX___SWAP": {
                    "public_key": "your_public_key",
                    "private_key": "your_private_key",
                    "passphrase": "your_passphrase",
                }
            }

        self.bt_api = BtApi(exchange_kwargs)

# ZeroMQ 订阅所有订单
        self.ctx = zmq.Context()
        self.socket = self.ctx.socket(zmq.SUB)
        self.socket.bind(bind_addr)
        self.socket.setsockopt(zmq.SUBSCRIBE, b"order.")

        print(f"[订单网关] 绑定到 {bind_addr}")

# 策略配置（每个策略独立的风控参数）
        self.strategy_configs = {
            "strategy_a": {
                "max_position": 1.0,           # 最大仓位
                "max_orders_per_hour": 100,     # 每小时最大订单数
            },
            "strategy_b": {
                "max_position": 0.5,
                "max_orders_per_hour": 50,
            },
            "strategy_c": {
                "max_position": 2.0,
                "max_orders_per_hour": 200,
            },
        }

# 当前仓位记录
        self.positions = {"strategy_a": 0, "strategy_b": 0, "strategy_c": 0}

# 订单计数器
        self.order_counts = {"strategy_a": [], "strategy_b": [], "strategy_c": []}

    def check_risk(self, strategy_id: str, order) -> bool:
        """风控检查"""
        config = self.strategy_configs.get(strategy_id)
        if not config:
            print(f"[订单网关] 未知策略: {strategy_id}")
            return False

# 检查仓位限制
        current_pos = self.positions.get(strategy_id, 0)
        new_pos = current_pos + (order.volume if order.side == "buy" else -order.volume)
        if abs(new_pos) > config["max_position"]:
            print(f"[订单网关] {strategy_id} 超过仓位限制! 当前: {current_pos}, 新: {new_pos}, 限制: {config['max_position']}")
            return False

# 检查频率限制
        now = time.time()
        self.order_counts[strategy_id] = [
            t for t in self.order_counts[strategy_id] if now - t < 3600
        ]
        if len(self.order_counts[strategy_id]) >= config["max_orders_per_hour"]:
            print(f"[订单网关] {strategy_id} 超过频率限制!")
            return False

        return True

    def run(self):
        """运行订单网关"""
        print("[订单网关] 启动...")

        while True:
            try:
                topic_bytes, data_bytes = self.socket.recv_multipart()
                order = pickle.loads(data_bytes)

                strategy_id = order.strategy_id

                print(f"[订单网关] 收到 [{strategy_id}] 订单: "
                      f"{order.side} {order.volume} {order.symbol} @ {order.price}")

# 风控检查
                if not self.check_risk(strategy_id, order):
                    print(f"[订单网关] 订单被风控拒绝!")
                    continue

# 执行订单
                try:
                    result = self.bt_api.make_order(
                        "OKX___SWAP",
                        order.symbol,
                        order.volume,
                        order.price,
                        order.order_type,
                    )
                    print(f"[订单网关] 订单已发送: {result}")

# 更新仓位
                    if order.side == "buy":
                        self.positions[strategy_id] += order.volume
                    else:
                        self.positions[strategy_id] -= order.volume

# 记录订单时间
                    self.order_counts[strategy_id].append(time.time())

                except Exception as e:
                    print(f"[订单网关] 下单失败: {e}")

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[订单网关] 错误: {e}")
                continue

```bash

- --

### 4. 突破策略实现示例

```python
class BreakoutStrategy(StrategyBase):
    """突破策略"""

    def __init__(self, strategy_id: str,
                 lookback: int,         # 回看周期
                 breakout_pct: float,   # 突破百分比
                 volume: float):        # 下单数量

        super().__init__(strategy_id, f"突破策略_{strategy_id}")

        self.lookback = lookback
        self.breakout_pct = breakout_pct
        self.volume = volume

        self.klines = []
        self.position = 0  # 0=空仓, 1=多仓, -1=空仓

        self.on_kline(self._on_kline)

    def _on_kline(self, kline: dict):
        """K 线数据回调"""
        self.klines.append(kline)
        if len(self.klines) > self.lookback + 10:
            self.klines = self.klines[-(self.lookback + 10):]

        if len(self.klines) < self.lookback:
            return

# 计算突破价
        recent = self.klines[-self.lookback:]
        high_max = max(k["high"] for k in recent)
        low_min = min(k["low"] for k in recent)

        current_close = kline["close"]

# 向上突破
        if self.position <= 0 and current_close > high_max *(1 + self.breakout_pct):
            print(f"[{self.strategy_id}] 向上突破! 价格: {current_close}, 高点: {high_max}")
            self.send_order("OP-USDT", "buy", self.volume, current_close, "limit")
            self.position = 1

# 向下突破
        elif self.position >= 0 and current_close < low_min* (1 - self.breakout_pct):
            print(f"[{self.strategy_id}] 向下突破! 价格: {current_close}, 低点: {low_min}")
            self.send_order("OP-USDT", "sell", self.volume, current_close, "limit")
            self.position = -1

```bash

- --

### 5. 启动脚本 (run_all.py)

```python

# run_all.py

import multiprocessing
import time

def run_data_feed():
    from data_feed import run_data_feed
    run_data_feed()

def run_strategy_a():
    from strategy import BreakoutStrategy
    strategy = BreakoutStrategy(
        strategy_id="strategy_a",
        lookback=20,
        breakout_pct=0.01,  # 1% 突破
        volume=0.1,
    )
    strategy.run()

def run_strategy_b():
    from strategy import BreakoutStrategy
    strategy = BreakoutStrategy(
        strategy_id="strategy_b",
        lookback=50,
        breakout_pct=0.02,  # 2% 突破
        volume=0.05,
    )
    strategy.run()

def run_strategy_c():
    from strategy import BreakoutStrategy
    strategy = BreakoutStrategy(
        strategy_id="strategy_c",
        lookback=100,
        breakout_pct=0.005,  # 0.5% 突破
        volume=0.2,
    )
    strategy.run()

def run_order_gateway():
    from order_gateway import OrderGateway
    gateway = OrderGateway()
    gateway.run()

if __name__ == "__main__":
    processes = []

# 启动数据源
    p = multiprocessing.Process(target=run_data_feed, name="DataFeed")
    p.start()
    processes.append(p)
    time.sleep(2)  # 等待数据源启动

# 启动订单网关
    p = multiprocessing.Process(target=run_order_gateway, name="OrderGateway")
    p.start()
    processes.append(p)
    time.sleep(1)

# 启动策略
    for func in [run_strategy_a, run_strategy_b, run_strategy_c]:
        p = multiprocessing.Process(target=func)
        p.start()
        processes.append(p)

# 等待
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()

```bash

- --

## ZeroMQ Topic 设计

| 发布端 Topic | 订阅端过滤器 | 说明 |

|-------------|-------------|------|

| `market.OP-USDT.kline.1m` | `market.OP-USDT.` | 接收 OP-USDT 所有数据 |

| `market.OP-USDT.tick` | `market.OP-USDT.kline.` | 只接收 K 线 |

| `order.strategy_a` | `order.` | 接收所有策略订单 |

| `order.strategy_b` | `order.strategy_a` | 只接收策略 A 的订单 |

- --

## 问题解决方案总结

| 问题 | 解决方案 |

|------|----------|

| 重复订阅 WebSocket | 单数据源进程订阅一次，通过 ZeroMQ 分发 |

| 订单混淆 | 每个策略发送订单时带 strategy_id，使用 ZeroMQ topic 分离 |

| 策略隔离 | 每个策略独立进程，崩溃不影响其他策略 |

| 统一风控 | 订单网关集中管理所有策略的订单和风险 |

- --

## 性能指标

| 指标 | 值 |

|------|-----|

| ZeroMQ 延迟 | <10μs (IPC) |

| 单数据源带宽 | 1 个合约的 K 线 + Tick |

| 支持策略数 | 理论无限制 (受限于系统资源) |

| 订单识别 | 通过 strategy_id 精确匹配 |

- --

## 扩展方向

1. **订单结果回传**：网关将订单执行结果发布到 `result.{strategy_id}` topic
2. **策略状态监控**：每个策略定期发布心跳和状态
3. **动态配置**：支持运行时修改策略参数和风控阈值
4. **持久化**：添加 Kafka 支持订单和行情的持久化存储
