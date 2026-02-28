# Phase 4: 桥接与实盘交易

> 周期: 2周 | 优先级: 🟡 中 | 风险: 中

---

## 1. 目标

实现Channel到LineSeries的可选桥接，以及实盘WebSocket数据接入。

### 1.1 核心目标

- ✅ ChannelBridge实现（可选）
- ✅ LiveEventQueue实现
- ✅ CCXT WebSocket集成
- ✅ 实盘数据验证

---

## 2. 实施内容

### 2.1 ChannelBridge实现（4天）

**文件**: `backtrader/channels/bridge.py`

```python
from backtrader import LineSeries

class ChannelBridge(LineSeries):
    """Channel到LineSeries的桥接（可选）
    
    警告：
    - 不支持runonce模式
    - 性能开销大（200倍）
    - 仅用于需要指标系统的场景
    """
    
    lines = ('value',)
    
    params = (
        ('channel', None),
        ('field', 'price'),  # tick.price, ob.mid_price等
    )
    
    def __init__(self):
        if self.p.channel is None:
            raise ValueError("channel parameter required")
        
        self._channel = self.p.channel
        self._field = self.p.field
        
        # 禁用runonce
        self._runonce = False
    
    def _load(self):
        """从Channel加载数据到LineSeries"""
        # 获取最新事件
        latest = self._channel.latest
        if latest is None:
            return False
        
        # 提取字段值
        value = self._extract_field(latest)
        
        # 写入line
        self.lines.value[0] = value
        
        return True
    
    def _extract_field(self, event):
        """提取事件字段"""
        if hasattr(event, self._field):
            return getattr(event, self._field)
        
        # 支持嵌套字段，如 'best_bid.price'
        parts = self._field.split('.')
        obj = event
        for part in parts:
            obj = getattr(obj, part)
        return obj

# 使用示例
class BridgeStrategy(bt.Strategy):
    def __init__(self):
        # 创建桥接
        self.tick_price = ChannelBridge(
            channel=self._channels[('tick', 'BTC/USDT')],
            field='price'
        )
        
        # 可以使用指标
        self.sma = bt.indicators.SMA(self.tick_price, period=20)
    
    def next(self):
        print(f"Tick Price: {self.tick_price[0]}, SMA: {self.sma[0]}")
```

**测试**: `tests/phase4/test_channel_bridge.py`

```python
def test_channel_bridge_basic():
    """测试基本桥接功能"""
    channel = TickChannel('BTC/USDT')
    bridge = ChannelBridge(channel=channel, field='price')
    
    # 推送tick
    channel.push(TickEvent(timestamp=100.0, price=50000, volume=1.0, direction='buy'))
    
    # 加载到bridge
    bridge._load()
    
    assert bridge.lines.value[0] == 50000

def test_bridge_with_indicator():
    """测试桥接与指标"""
    cerebro = bt.Cerebro()
    cerebro.add_channel(TickChannel, symbol='BTC/USDT', dataname='...')
    
    class BridgeTestStrategy(bt.Strategy):
        def __init__(self):
            self.bridge = ChannelBridge(
                channel=self._channels[('tick', 'BTC/USDT')],
                field='price'
            )
            self.sma = bt.indicators.SMA(self.bridge, period=5)
    
    cerebro.addstrategy(BridgeTestStrategy)
    results = cerebro.run(mode=bt.RunMode.TICK)
    
    # 验证SMA计算正确
    # ...
```

---

### 2.2 LiveEventQueue实现（3天）

**文件**: `backtrader/channels/live_queue.py`

```python
import queue
import threading
from backtrader.channel import Event, EventPriority

class LiveEventQueue:
    """实盘事件队列 - 实时数据"""
    
    def __init__(self, max_queue_size=10000):
        self._queue = queue.PriorityQueue(maxsize=max_queue_size)
        self._sequence = 0
        self._lock = threading.Lock()
        self._stopped = False
    
    def push(self, event):
        """推送事件（线程安全）"""
        with self._lock:
            if self._stopped:
                return
            
            # 包装为优先级事件
            priority_event = (
                event.timestamp,
                event.priority,
                self._sequence,
                event
            )
            self._sequence += 1
            
            try:
                self._queue.put(priority_event, block=False)
            except queue.Full:
                # 队列满，丢弃最旧事件
                self._queue.get()
                self._queue.put(priority_event)
    
    def pop(self, timeout=1.0):
        """弹出事件（阻塞）"""
        try:
            _, _, _, event = self._queue.get(timeout=timeout)
            return event
        except queue.Empty:
            return None
    
    def stop(self):
        """停止队列"""
        self._stopped = True
```

---

### 2.3 CCXT WebSocket集成（5天）

**文件**: `backtrader/feeds/ccxt_live_tick.py`

```python
import ccxt.pro as ccxtpro
import asyncio
from backtrader.channels.tick import TickChannel, TickEvent
from backtrader.channels.live_queue import LiveEventQueue

class CCXTLiveTickFeed:
    """CCXT实盘Tick数据源"""
    
    def __init__(self, exchange_id, symbol, event_queue):
        self.exchange_id = exchange_id
        self.symbol = symbol
        self.event_queue = event_queue
        self.exchange = None
        self._running = False
    
    async def start(self):
        """启动WebSocket连接"""
        exchange_class = getattr(ccxtpro, self.exchange_id)
        self.exchange = exchange_class()
        self._running = True
        
        try:
            while self._running:
                trades = await self.exchange.watch_trades(self.symbol)
                
                for trade in trades:
                    event = TickEvent(
                        timestamp=trade['timestamp'] / 1000.0,
                        price=trade['price'],
                        volume=trade['amount'],
                        direction='buy' if trade['side'] == 'buy' else 'sell',
                        trade_id=trade['id'],
                        symbol=self.symbol
                    )
                    
                    # 推送到事件队列
                    self.event_queue.push(Event(
                        timestamp=event.timestamp,
                        priority=EventPriority.TICK,
                        channel_type='tick',
                        channel_name=self.symbol,
                        data=event
                    ))
        
        finally:
            await self.exchange.close()
    
    def stop(self):
        """停止WebSocket"""
        self._running = False

# 使用示例
def run_live_trading():
    cerebro = bt.Cerebro()
    
    # 创建实盘事件队列
    live_queue = LiveEventQueue()
    
    # 启动CCXT WebSocket
    feed = CCXTLiveTickFeed('binance', 'BTC/USDT', live_queue)
    
    # 在后台线程运行WebSocket
    def run_ws():
        asyncio.run(feed.start())
    
    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()
    
    # 配置Cerebro使用实盘队列
    cerebro._event_queue = live_queue
    
    # 运行策略
    cerebro.addstrategy(LiveStrategy)
    cerebro.run(mode=bt.RunMode.TICK)
    
    # 停止
    feed.stop()
```

**测试**: `tests/phase4/test_live_trading.py`

```python
def test_live_event_queue():
    """测试实盘事件队列"""
    queue = LiveEventQueue()
    
    # 推送事件
    event1 = Event(timestamp=100.0, priority=30, channel_type='tick')
    event2 = Event(timestamp=100.0, priority=20, channel_type='orderbook')
    
    queue.push(event1)
    queue.push(event2)
    
    # 弹出事件（按优先级）
    e1 = queue.pop(timeout=1.0)
    assert e1.priority == 20
    
    e2 = queue.pop(timeout=1.0)
    assert e2.priority == 30

def test_ccxt_websocket_integration():
    """测试CCXT WebSocket集成（模拟）"""
    # 使用mock避免真实连接
    # ...
```

---

### 2.4 实盘数据验证（2天）

**文件**: `backtrader/channels/live_validator.py`

```python
class LiveDataValidator:
    """实盘数据验证器"""
    
    def __init__(self):
        self._last_timestamps = {}
        self._anomaly_count = {}
    
    def validate(self, event):
        """验证实盘数据"""
        key = (event.channel_type, event.channel_name)
        
        # 1. 时间戳检查
        last_ts = self._last_timestamps.get(key, 0)
        if event.timestamp < last_ts:
            self._record_anomaly(key, 'out_of_order')
            return False
        
        # 2. 时间跳跃检查（>1小时视为异常）
        if last_ts > 0 and event.timestamp - last_ts > 3600:
            self._record_anomaly(key, 'time_jump')
            # 警告但不拒绝
        
        # 3. 数据合理性检查
        if event.channel_type == 'tick':
            if event.data.price <= 0 or event.data.volume < 0:
                self._record_anomaly(key, 'invalid_data')
                return False
        
        self._last_timestamps[key] = event.timestamp
        return True
    
    def _record_anomaly(self, key, anomaly_type):
        """记录异常"""
        if key not in self._anomaly_count:
            self._anomaly_count[key] = {}
        
        self._anomaly_count[key][anomaly_type] = \
            self._anomaly_count[key].get(anomaly_type, 0) + 1
    
    def get_anomaly_report(self):
        """获取异常报告"""
        return self._anomaly_count
```

---

## 3. 交付物

### 3.1 代码

- [ ] `backtrader/channels/bridge.py` - ChannelBridge
- [ ] `backtrader/channels/live_queue.py` - LiveEventQueue
- [ ] `backtrader/feeds/ccxt_live_tick.py` - CCXT集成
- [ ] `backtrader/channels/live_validator.py` - 实盘验证

### 3.2 测试

- [ ] `tests/phase4/test_channel_bridge.py`
- [ ] `tests/phase4/test_live_trading.py`
- [ ] `tests/phase4/test_live_validator.py`

### 3.3 文档

- [ ] Phase 4完成报告
- [ ] 实盘交易指南
- [ ] ChannelBridge使用说明

---

## 4. 验收标准

### 4.1 功能验收

- [ ] ChannelBridge正常工作
- [ ] LiveEventQueue线程安全
- [ ] CCXT WebSocket稳定连接
- [ ] 实盘数据验证有效

### 4.2 实盘验证

- [ ] WebSocket连接稳定（>1小时）
- [ ] 数据延迟 < 100ms
- [ ] 异常处理正确
- [ ] 自动重连正常

### 4.3 回归验证

- [ ] 回归测试100%通过
- [ ] 向后兼容性保持

---

## 5. 时间表

| 任务 | 工作量 |
|------|--------|
| ChannelBridge | 4天 |
| LiveEventQueue | 3天 |
| CCXT集成 | 5天 |
| 实盘验证 | 2天 |

**总计**: 14天（2周）

---

## 6. 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| WebSocket不稳定 | 中 | 高 | 自动重连+心跳检测 |
| 数据延迟过高 | 中 | 中 | 监控+告警 |
| Bridge性能问题 | 低 | 中 | 文档说明限制 |

---

## 7. 下一步

Phase 4完成后，进入Phase 5：文档与示例。
