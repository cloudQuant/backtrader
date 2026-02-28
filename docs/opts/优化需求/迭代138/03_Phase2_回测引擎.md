# Phase 2: 回测引擎与Broker

> 周期: 3周 | 优先级: 🔴 最高 | 风险: 高

---

## 1. 目标

实现Tick级回测引擎的核心逻辑，包括三种运行模式和两种新Broker。

### 1.1 核心目标

- ✅ 实现TickBroker（纯Tick撮合）
- ✅ 实现MixBroker（Tick+Bar混合撮合）
- ✅ 实现三种运行模式（BAR/TICK/MIXED）
- ✅ 实现批处理通知机制
- ✅ 确保撮合准确性

### 1.2 成功标准

| 指标 | 目标 | 测量方法 |
|------|------|---------|
| 撮合准确性 | 100% | 对比验证 |
| 1天Tick回测 | < 10秒 | 性能测试 |
| 内存使用 | < 200MB | memory_profiler |
| 回归测试 | 100%通过 | 1020/1020 |

---

## 2. 实施内容

### 2.1 TickBroker实现（5天）

#### 2.1.1 TickBroker核心逻辑

**文件**: `backtrader/brokers/tickbroker.py`

```python
import backtrader as bt
from backtrader.brokers import BackBroker
from backtrader.order import Order

class TickBroker(BackBroker):
    """Tick级订单撮合Broker"""
    
    params = (
        ('slippage_model', 'fixed'),      # 'fixed', 'percentage', 'tick'
        ('slippage_value', 0.0),          # 滑点值
        ('partial_fill', True),           # 允许部分成交
        ('market_impact', False),         # 市场冲击模型
        ('impact_factor', 0.0001),        # 冲击系数
    )
    
    def __init__(self):
        super().__init__()
        self._tick_channels = {}  # {symbol: TickChannel}
        self._pending_orders = []  # 待撮合订单
        self._matched_orders = set()  # 本timestamp已撮合订单
    
    def register_tick_channel(self, symbol, channel):
        """注册Tick通道"""
        self._tick_channels[symbol] = channel
    
    def match_tick(self, tick):
        """Tick撮合逻辑
        
        Args:
            tick: TickEvent实例
        """
        symbol = tick.symbol
        
        # 获取该symbol的待撮合订单
        orders_to_match = [
            o for o in self._pending_orders
            if self._get_order_symbol(o) == symbol
            and o.ref not in self._matched_orders
        ]
        
        for order in orders_to_match:
            if self._try_match_order(order, tick):
                self._matched_orders.add(order.ref)
    
    def _try_match_order(self, order, tick):
        """尝试撮合订单
        
        Returns:
            bool: 是否成功撮合
        """
        # 1. 检查订单方向与tick方向
        if order.isbuy() and tick.direction == 'sell':
            # 买单与卖方成交tick匹配
            match_price = tick.price
        elif order.issell() and tick.direction == 'buy':
            # 卖单与买方成交tick匹配
            match_price = tick.price
        else:
            return False
        
        # 2. 检查价格条件
        if not self._check_price_condition(order, match_price):
            return False
        
        # 3. 计算滑点
        exec_price = self._apply_slippage(order, match_price)
        
        # 4. 计算成交量
        if self.p.partial_fill:
            # 部分成交：取订单剩余量与tick量的最小值
            fill_size = min(order.executed.remsize, tick.volume)
        else:
            # 全量成交：只有tick量足够时才成交
            if tick.volume >= order.executed.remsize:
                fill_size = order.executed.remsize
            else:
                return False
        
        # 5. 执行成交
        self._execute_order(order, exec_price, fill_size, tick.timestamp)
        
        return True
    
    def _check_price_condition(self, order, price):
        """检查价格条件"""
        if order.exectype == Order.Market:
            return True
        
        elif order.exectype == Order.Limit:
            if order.isbuy():
                return price <= order.price
            else:
                return price >= order.price
        
        elif order.exectype == Order.Stop:
            if order.isbuy():
                return price >= order.price
            else:
                return price <= order.price
        
        elif order.exectype == Order.StopLimit:
            # 先检查是否触发
            if order.triggered:
                # 已触发，按limit检查
                if order.isbuy():
                    return price <= order.pricelimit
                else:
                    return price >= order.pricelimit
            else:
                # 检查是否触发
                if order.isbuy():
                    if price >= order.price:
                        order.triggered = True
                        return price <= order.pricelimit
                else:
                    if price <= order.price:
                        order.triggered = True
                        return price >= order.pricelimit
                return False
        
        return False
    
    def _apply_slippage(self, order, price):
        """应用滑点"""
        if self.p.slippage_model == 'fixed':
            if order.isbuy():
                return price + self.p.slippage_value
            else:
                return price - self.p.slippage_value
        
        elif self.p.slippage_model == 'percentage':
            if order.isbuy():
                return price * (1 + self.p.slippage_value)
            else:
                return price * (1 - self.p.slippage_value)
        
        elif self.p.slippage_model == 'tick':
            # 假设tick_size从数据中获取
            tick_size = getattr(order.data, 'tick_size', 0.01)
            if order.isbuy():
                return price + self.p.slippage_value * tick_size
            else:
                return price - self.p.slippage_value * tick_size
        
        return price
    
    def _execute_order(self, order, price, size, timestamp):
        """执行订单成交"""
        # 更新订单执行信息
        order.execute(
            dt=timestamp,
            size=size,
            price=price,
            closed=size,
            closedvalue=size * price,
            closedcomm=self._getcommission(order, size, price),
            opened=0,
            openedvalue=0,
            openedcomm=0,
            margin=0,
            pnl=0,
            psize=0,
            pprice=0
        )
        
        # 更新持仓
        self._update_position(order, size, price)
        
        # 检查订单是否完全成交
        if order.executed.remsize == 0:
            order.completed()
            self._pending_orders.remove(order)
        else:
            order.partial()
        
        # 加入通知队列
        self.notifs.append(order.clone())
    
    def _update_position(self, order, size, price):
        """更新持仓"""
        # ... 持仓更新逻辑 ...
        pass
    
    def submit(self, order):
        """提交订单"""
        order.submit()
        self._pending_orders.append(order)
        self.notifs.append(order.clone())
        return order
    
    def finalize_timestamp(self):
        """时间戳结束时清理"""
        self._matched_orders.clear()
```

**测试**: `tests/phase2/test_tick_broker.py`

```python
def test_tick_broker_market_order():
    """测试市价单撮合"""
    broker = TickBroker()
    
    # 创建订单
    order = Order(
        owner=None,
        data=None,
        size=1.0,
        price=None,
        exectype=Order.Market,
        isbuy=True
    )
    
    broker.submit(order)
    
    # 模拟tick
    tick = TickEvent(
        timestamp=100.0,
        price=50000,
        volume=2.0,
        direction='sell',
        symbol='BTC/USDT'
    )
    
    broker.match_tick(tick)
    
    # 验证成交
    assert order.status == Order.Completed
    assert order.executed.price == 50000
    assert order.executed.size == 1.0

def test_tick_broker_limit_order():
    """测试限价单撮合"""
    broker = TickBroker()
    
    # 买单：限价50000
    order = Order(
        size=1.0,
        price=50000,
        exectype=Order.Limit,
        isbuy=True
    )
    broker.submit(order)
    
    # tick价格50001，不成交
    tick1 = TickEvent(timestamp=100.0, price=50001, volume=2.0, direction='sell')
    broker.match_tick(tick1)
    assert order.status == Order.Submitted
    
    # tick价格49999，成交
    tick2 = TickEvent(timestamp=101.0, price=49999, volume=2.0, direction='sell')
    broker.match_tick(tick2)
    assert order.status == Order.Completed
    assert order.executed.price == 49999

def test_tick_broker_partial_fill():
    """测试部分成交"""
    broker = TickBroker(partial_fill=True)
    
    order = Order(size=10.0, exectype=Order.Market, isbuy=True)
    broker.submit(order)
    
    # 第一个tick：成交3
    tick1 = TickEvent(timestamp=100.0, price=50000, volume=3.0, direction='sell')
    broker.match_tick(tick1)
    assert order.status == Order.Partial
    assert order.executed.size == 3.0
    
    # 第二个tick：成交7，完全成交
    tick2 = TickEvent(timestamp=101.0, price=50001, volume=7.0, direction='sell')
    broker.match_tick(tick2)
    assert order.status == Order.Completed
    assert order.executed.size == 10.0
```

---

### 2.2 MixBroker实现（6天）

**文件**: `backtrader/brokers/mixbroker.py`

```python
class MixBroker(TickBroker):
    """混合撮合Broker（Tick优先 + Bar兜底）"""
    
    params = (
        ('tick_priority', True),          # Tick撮合优先
        ('bar_fallback', True),           # Bar兜底撮合
        ('tick_timeout', 300.0),          # Tick撮合超时（秒）
    )
    
    def __init__(self):
        super().__init__()
        self._order_submit_time = {}  # {order.ref: timestamp}
        self._tick_matched_orders = set()  # 已被tick撮合的订单
    
    def match_tick(self, tick):
        """Tick撮合 - 记录已撮合订单"""
        symbol = tick.symbol
        
        orders_to_match = [
            o for o in self._pending_orders
            if self._get_order_symbol(o) == symbol
            and o.ref not in self._matched_orders
            and o.ref not in self._tick_matched_orders
        ]
        
        for order in orders_to_match:
            if self._try_match_order(order, tick):
                self._matched_orders.add(order.ref)
                self._tick_matched_orders.add(order.ref)
    
    def finalize_bar(self, data, bar_timestamp):
        """Bar结束时的兜底撮合
        
        Args:
            data: DataBase实例
            bar_timestamp: bar的时间戳
        """
        if not self.p.bar_fallback:
            return
        
        symbol = getattr(data, '_name', 'default')
        
        # 获取未被tick撮合的订单
        orders_to_match = [
            o for o in self._pending_orders
            if self._get_order_symbol(o) == symbol
            and o.ref not in self._tick_matched_orders
        ]
        
        for order in orders_to_match:
            # 检查是否超时
            submit_time = self._order_submit_time.get(order.ref, 0)
            if bar_timestamp - submit_time > self.p.tick_timeout:
                # 超时，使用bar撮合
                self._match_with_bar(order, data, bar_timestamp)
            else:
                # 未超时，继续等待tick
                pass
    
    def _match_with_bar(self, order, data, timestamp):
        """使用Bar数据撮合订单"""
        # 使用bar的OHLC价格撮合
        if order.exectype == Order.Market:
            # 市价单：使用close价格
            exec_price = data.close[0]
        
        elif order.exectype == Order.Limit:
            # 限价单：检查是否在bar范围内
            if order.isbuy():
                if data.low[0] <= order.price:
                    exec_price = min(order.price, data.open[0])
                else:
                    return  # 未触发
            else:
                if data.high[0] >= order.price:
                    exec_price = max(order.price, data.open[0])
                else:
                    return
        
        elif order.exectype == Order.Stop:
            # 止损单
            if order.isbuy():
                if data.high[0] >= order.price:
                    exec_price = max(order.price, data.open[0])
                else:
                    return
            else:
                if data.low[0] <= order.price:
                    exec_price = min(order.price, data.open[0])
                else:
                    return
        
        else:
            return
        
        # 应用滑点
        exec_price = self._apply_slippage(order, exec_price)
        
        # 执行成交（全量）
        fill_size = order.executed.remsize
        self._execute_order(order, exec_price, fill_size, timestamp)
    
    def submit(self, order):
        """提交订单 - 记录提交时间"""
        self._order_submit_time[order.ref] = self._current_timestamp
        return super().submit(order)
```

**测试**: `tests/phase2/test_mix_broker.py`

```python
def test_mix_broker_tick_priority():
    """测试Tick优先撮合"""
    broker = MixBroker()
    
    order = Order(size=1.0, exectype=Order.Market, isbuy=True)
    broker.submit(order)
    
    # Tick撮合
    tick = TickEvent(timestamp=100.0, price=50000, volume=2.0, direction='sell')
    broker.match_tick(tick)
    
    assert order.status == Order.Completed
    assert order.executed.price == 50000
    
    # Bar兜底不应该再次撮合
    data = MockData(open=50100, high=50200, low=49900, close=50050)
    broker.finalize_bar(data, 100.5)
    
    # 验证没有重复成交
    assert order.executed.size == 1.0

def test_mix_broker_bar_fallback():
    """测试Bar兜底撮合"""
    broker = MixBroker(tick_timeout=5.0)
    broker._current_timestamp = 100.0
    
    order = Order(size=1.0, exectype=Order.Market, isbuy=True)
    broker.submit(order)
    
    # 没有tick撮合
    # ...
    
    # 超时后bar兜底
    data = MockData(open=50000, high=50100, low=49900, close=50050)
    broker.finalize_bar(data, 106.0)  # 超过5秒
    
    assert order.status == Order.Completed
    assert order.executed.price == 50050  # close价格
```

---

### 2.3 三种运行模式实现（5天）

**文件**: `backtrader/cerebro.py`

```python
from enum import Enum

class RunMode(Enum):
    """运行模式"""
    BAR = 'bar'        # 纯K线模式（向后兼容）
    TICK = 'tick'      # 纯Tick模式
    MIXED = 'mixed'    # 混合模式（Bar主时钟 + Tick辅助）

class Cerebro:
    """三种运行模式实现"""
    
    def _run_bar_mode(self, runstrats):
        """纯K线模式 - 完全向后兼容"""
        # 使用现有的_runonce或_runnext逻辑
        if self.p.preload and self.p.runonce:
            return self._runonce(runstrats)
        else:
            return self._runnext(runstrats)
    
    def _run_tick_mode(self, runstrats):
        """纯Tick模式 - 事件驱动"""
        # 初始化事件队列
        self._init_event_queue(runstrats)
        
        # 设置TickBroker
        if not isinstance(self._broker, TickBroker):
            self._broker = TickBroker()
        
        # 注册Tick通道到Broker
        for strat in runstrats:
            if hasattr(strat, '_channels'):
                for (ch_type, symbol), ch in strat._channels.items():
                    if ch_type == 'tick':
                        self._broker.register_tick_channel(symbol, ch)
        
        # 事件循环
        while True:
            try:
                event = self._event_queue.pop()
            except StopIteration:
                break
            
            self._current_timestamp = event.timestamp
            
            # 1. Broker撮合（如果是tick事件）
            if event.channel_type == 'tick':
                self._broker.match_tick(event.data)
            
            # 2. 分发事件到策略
            for strat in runstrats:
                self._safe_strategy_call(strat, '_dispatch_event', event)
            
            # 3. 批量分发通知
            self._deliver_notifications(runstrats)
            
            # 4. Broker清理
            self._broker.finalize_timestamp()
        
        return runstrats
    
    def _run_mixed_mode(self, runstrats):
        """混合模式 - Bar主时钟 + Tick辅助"""
        # 初始化事件队列
        self._init_event_queue(runstrats)
        
        # 设置MixBroker
        if not isinstance(self._broker, MixBroker):
            self._broker = MixBroker()
        
        # 注册通道
        for strat in runstrats:
            if hasattr(strat, '_channels'):
                for (ch_type, symbol), ch in strat._channels.items():
                    if ch_type == 'tick':
                        self._broker.register_tick_channel(symbol, ch)
        
        # 事件循环
        current_bar_ts = None
        bar_events = []  # 当前bar内的子事件
        
        while True:
            try:
                event = self._event_queue.pop()
            except StopIteration:
                break
            
            self._current_timestamp = event.timestamp
            
            # 检查是否是新bar
            if event.event_type == 'bar_close':
                # 处理上一个bar的所有子事件
                for sub_event in bar_events:
                    if sub_event.channel_type == 'tick':
                        self._broker.match_tick(sub_event.data)
                    
                    for strat in runstrats:
                        self._safe_strategy_call(strat, '_dispatch_event', sub_event)
                
                # Bar兜底撮合
                data = self._bar_by_name.get(event.channel_name)
                if data:
                    self._broker.finalize_bar(data, event.timestamp)
                
                # 触发策略next()
                for strat in runstrats:
                    self._safe_strategy_call(strat, 'next')
                
                # 批量通知
                self._deliver_notifications(runstrats)
                
                # 清理
                bar_events.clear()
                current_bar_ts = event.timestamp
            
            else:
                # 子事件（tick/orderbook/funding）
                bar_events.append(event)
        
        return runstrats
```

**测试**: `tests/phase2/test_run_modes.py`

```python
def test_bar_mode_backward_compatible():
    """测试BAR模式向后兼容"""
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(dataname='...'))
    cerebro.addstrategy(SimpleStrategy)
    
    results = cerebro.run()  # 默认BAR模式
    
    # 验证使用BackBroker
    assert isinstance(cerebro._broker, bt.brokers.BackBroker)
    
    # 验证结果与历史一致
    # ...

def test_tick_mode():
    """测试TICK模式"""
    cerebro = bt.Cerebro()
    cerebro.add_channel(TickChannel, symbol='BTC/USDT', dataname='...')
    cerebro.addstrategy(TickStrategy)
    
    results = cerebro.run(mode=bt.RunMode.TICK)
    
    # 验证使用TickBroker
    assert isinstance(cerebro._broker, bt.brokers.TickBroker)
    
    # 验证策略收到tick回调
    strat = results[0]
    assert strat.tick_count > 0

def test_mixed_mode():
    """测试MIXED模式"""
    cerebro = bt.Cerebro()
    cerebro.adddata(bt.feeds.GenericCSVData(dataname='...'))
    cerebro.add_channel(TickChannel, symbol='BTC/USDT', dataname='...')
    cerebro.addstrategy(MixedStrategy)
    
    results = cerebro.run(mode=bt.RunMode.MIXED)
    
    # 验证使用MixBroker
    assert isinstance(cerebro._broker, bt.brokers.MixBroker)
    
    # 验证策略收到bar和tick回调
    strat = results[0]
    assert strat.bar_count > 0
    assert strat.tick_count > 0
```

---

### 2.4 批处理通知机制（3天）

已在Phase 1实现，此处进行集成测试。

**测试**: `tests/phase2/test_batch_notifications.py`

```python
def test_notifications_within_same_timestamp():
    """测试同timestamp内通知批处理"""
    
    class NotificationTestStrategy(bt.Strategy):
        def __init__(self):
            self.notifications = []
        
        def notify_order(self, order):
            self.notifications.append({
                'timestamp': self._current_timestamp,
                'status': order.status,
                'ref': order.ref
            })
    
    # ... 设置导致同timestamp多个通知的场景 ...
    
    results = cerebro.run(mode=bt.RunMode.TICK)
    strat = results[0]
    
    # 验证通知在timestamp结束后批量分发
    # 验证通知顺序按优先级排序
    # ...
```

---

## 3. 交付物

### 3.1 代码

- [ ] `backtrader/brokers/tickbroker.py` - TickBroker
- [ ] `backtrader/brokers/mixbroker.py` - MixBroker
- [ ] `backtrader/cerebro.py` - 三种运行模式
- [ ] `backtrader/__init__.py` - 导出RunMode

### 3.2 测试

- [ ] `tests/phase2/test_tick_broker.py`
- [ ] `tests/phase2/test_mix_broker.py`
- [ ] `tests/phase2/test_run_modes.py`
- [ ] `tests/phase2/test_batch_notifications.py`
- [ ] `tests/phase2/test_accuracy.py` - 准确性验证

### 3.3 文档

- [ ] Phase 2完成报告
- [ ] Broker使用指南
- [ ] 运行模式选择指南

---

## 4. 验收标准

### 4.1 功能验收

- [ ] TickBroker正确撮合各类订单
- [ ] MixBroker无重复/遗漏撮合
- [ ] 三种模式正常切换
- [ ] 批处理通知正确

### 4.2 准确性验收

- [ ] TickBroker与手工计算一致
- [ ] MixBroker与TickBroker一致（纯tick场景）
- [ ] 订单审计无遗漏

### 4.3 性能验收

- [ ] 1天Tick回测 < 10秒
- [ ] 内存使用 < 200MB
- [ ] 回归测试100%通过

---

## 5. 时间表

| 任务 | 工作量 | 开始 | 结束 |
|------|--------|------|------|
| TickBroker实现 | 5天 | Day 1 | Day 5 |
| MixBroker实现 | 6天 | Day 6 | Day 11 |
| 三种运行模式 | 5天 | Day 12 | Day 16 |
| 批处理通知集成 | 3天 | Day 17 | Day 19 |
| 准确性验证 | 2天 | Day 20 | Day 21 |

---

## 6. 风险与应对

| 风险 | 概率 | 影响 | 应对措施 |
|------|------|------|---------|
| MixBroker撮合bug | 高 | 高 | 详细状态机设计+完善测试 |
| 性能不达标 | 中 | 高 | 性能分析+优化 |
| 回归问题 | 低 | 高 | 持续回归测试 |

---

## 7. 下一步

Phase 2完成后，进入Phase 3：OrderBook深度撮合。
