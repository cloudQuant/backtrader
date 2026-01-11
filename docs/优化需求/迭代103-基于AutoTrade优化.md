### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/AutoTrade
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### AutoTrade项目简介
AutoTrade是一个基于backtrader理念的自动化交易系统（实际上没有直接使用backtrader作为依赖），专注于A股实盘交易自动化。项目采用模块化设计，具有以下核心特点：

**核心架构特点**：
- **模块化策略系统**: 基于抽象基类的策略插件架构
- **多进程架构**: 采用multiprocessing实现交易执行与策略逻辑分离
- **Job依赖系统**: 支持订单间依赖关系的管理
- **券商接口抽象**: 通过Socket抽象层对接券商API

**主要功能模块**：
- **Modules/**: 策略模块，基于Module抽象类实现
- **Trade/**: 交易执行引擎（Trader、Job、Quotation）
- **Socket/**: 券商接口适配层（广发证券实现）
- **Tools/**: 工具服务（邮件通知、OCR验证码识别）

---

## 一、架构对比分析

### 1.1 整体架构对比

| 维度 | Backtrader | AutoTrade |
|------|------------|-----------|
| **核心设计理念** | 回测驱动的事件系统 | 实盘驱动的任务系统 |
| **执行模式** | 单线程同步执行（主循环） | 多进程异步执行 |
| **策略抽象** | Strategy基类，继承实现 | Module抽象基类，继承实现 |
| **订单管理** | Order对象，Broker管理 | Job对象，依赖关系管理 |
| **数据源** | Feed抽象，多种数据源 | Sina API实时行情 |
| **状态管理** | Line系统，历史状态管理 | 共享内存，当前状态管理 |

### 1.2 策略系统对比

**Backtrader Strategy**:
```python
class MyStrategy(bt.Strategy):
    params = (('period', 20),)

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.params.period)

    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()
```

**AutoTrade Module**:
```python
class MyStrategy(Module):
    def focus_list(self):
        return ['sh600004', 'sz000002']

    def need_to_trade(self, quotes, time_stamp):
        jobs = []
        # 策略逻辑
        job = self.create_new_job(time_stamp)\
            .set(Job.BUY, '600004', 'sh', 10000, 12.8)\
            .set_message('Buy order')
        jobs.append(job)
        return jobs
```

**关键差异**：
1. **触发机制**: Backtrader基于数据更新事件（next），AutoTrade基于轮询（need_to_trade）
2. **订单创建**: Backtrader直接调用buy/sell，AutoTrade创建Job对象
3. **历史访问**: Backtrader可访问历史数据，AutoTrade仅当前报价

### 1.3 订单管理系统对比

**Backtrader Order**:
- 由Broker管理
- 状态：Submitted/Accepted/Partial/Completed/Canceled/Rejected
- 订单类型：Market/Limit/Stop/StopLimit
- 生命周期管理在Broker内部

**AutoTrade Job**:
- 独立Job类，支持依赖关系
- 状态：PENDING/ENTRUSTED/TRADED_PARTLY/TRADED_ALL/CANCELED/DEAD
- 支持Job间依赖（Dependence）
- 重试机制（allow_retry_times）

**优势对比**：
- **Backtrader**: 更完整的订单类型支持，标准的生命周期管理
- **AutoTrade**: 依赖系统更强大，支持复杂的多腿策略

### 1.4 多进程架构分析

**AutoTrade的多进程设计**：
```python
class Trader(object):
    def __init__(self, account, password, notifier, ocr_service):
        self.__manager = Manager()
        self.__job_list = self.__manager.list()  # 共享内存
        self.__job_list_lock = Lock()
        self.__keep_working = Value('i', 1)

    def start(self):
        self.__process = Process(target=self.__issue_cmd)
        self.__process.start()

    def __issue_cmd(self):
        # 独立进程执行订单
        while self.__keep_working.value == 1:
            # 订单处理逻辑
            pass
```

**借鉴价值**：
1. **策略与执行分离**: 主进程运行策略，子进程执行交易
2. **共享内存通信**: 通过Manager实现进程间数据共享
3. **故障隔离**: 交易进程崩溃不影响策略逻辑

### 1.5 依赖关系系统

**AutoTrade的独特设计**：
```python
# Job可以依赖其他Job的状态
class Dependence(object):
    DEAD = -1   # 依赖的Job已死亡
    WAIT = 0    # 等待依赖满足
    READY = 1   # 依赖已满足

# 创建依赖
job2.add_dependence(Dependence(job1, Job.TRADED_ALL))
# 只有当job1全部成交后，job2才会执行
```

**应用场景**：
- 先卖后买（资金释放依赖）
- 分批建仓（前一批成交后执行下一批）
- 对冲策略（开仓成功后执行对冲）

**Backtrader缺失**: 没有内置的订单依赖机制

---

## 二、需求规格说明书

### 2.1 实盘交易增强模块

**需求ID**: REQ-103-01
**优先级**: 高

**功能描述**:
为backtrader添加实盘交易增强功能，支持与券商API的直接对接和自动化交易执行。

**详细需求**:

1. **券商接口抽象层**
   - 定义统一的券商接口规范（BrokerAdapter）
   - 支持多种券商的适配实现
   - 账户管理：登录、登出、会话保持
   - 资金查询：可用资金、总资产、持仓市值
   - 委托查询：当日委托、历史委托、委托状态

2. **实时行情接入**
   - 支持实时行情订阅（WebSocket/长轮询）
   - Level2行情数据支持（五档行情）
   - 行情数据缓存和分发机制

3. **风控限制**
   - 单笔最大委托数量限制
   - 日最大委托次数限制
   - 涨跌停价格检测
   - 资金充足性检查

**验收标准**:
- [ ] 能够连接至少3家主流券商
- [ ] 委托延迟低于500ms
- [ ] 行情更新延迟低于100ms
- [ ] 风控检查100%触发

### 2.2 订单依赖关系系统

**需求ID**: REQ-103-02
**优先级**: 高

**功能描述**:
实现订单间的依赖关系管理，支持复杂的多腿策略执行。

**详细需求**:

1. **依赖关系定义**
   ```python
   # 支持的依赖类型
   class OrderDependence:
       AFTER_SUBMITTED   # 提交后即可执行
       AFTER_ACCEPTED    # 接受后执行
       AFTER_PARTIAL     # 部分成交后执行
       AFTER_FILLED      # 全部成交后执行
       AFTER_CANCELED    # 撤单后执行
   ```

2. **依赖创建方式**
   ```python
   # 链式创建
   order2 = order1.then_execute(OrderDependence.AFTER_FILLED)

   # 显式创建
   cerebro.add_order_dependency(order2, order1, OrderDependence.AFTER_FILLED)
   ```

3. **依赖管理**
   - 自动检测依赖条件是否满足
   - 依赖链断裂时的处理策略
   - 循环依赖检测和拒绝

**验收标准**:
- [ ] 支持至少5种依赖类型
- [ ] 能够处理10层以上的依赖链
- [ ] 循环依赖检测100%准确
- [ ] 依赖超时有明确处理

### 2.3 多进程交易执行架构

**需求ID**: REQ-103-03
**优先级**: 中

**功能描述**:
将策略执行与订单委托分离到不同进程，提高系统稳定性。

**详细需求**:

1. **进程架构**
   ```
   主进程（策略执行）
     ├── 子进程A（订单委托）
     ├── 子进程B（行情接收）
     └── 子进程C（数据记录）
   ```

2. **进程间通信**
   - 使用multiprocessing.Manager共享状态
   - 消息队列用于订单传递
   - 共享内存用于行情数据

3. **进程监控**
   - 心跳检测机制
   - 进程异常自动重启
   - 优雅关闭机制

**验收标准**:
- [ ] 进程崩溃不影响其他进程
- [ ] 进程间通信延迟低于10ms
- [ ] 支持至少4个子进程
- [ ] 进程重启时间低于5秒

### 2.4 任务调度系统

**需求ID**: REQ-103-04
**优先级**: 中

**功能描述**:
实现定时任务调度功能，支持在特定时间点执行交易逻辑。

**详细需求**:

1. **定时器**
   ```python
   # 支持的定时方式
   at_time("09:30:00")        # 绝对时间
   after_market_open(min=5)   # 开盘后N分钟
   before_market_close(min=30) # 收盘前N分钟
   interval(seconds=60)       # 间隔执行
   ```

2. **任务优先级**
   - 高优先级任务优先执行
   - 相同优先级按创建时间排序

3. **任务状态**
   - PENDING: 等待执行
   - RUNNING: 正在执行
   - COMPLETED: 已完成
   - FAILED: 执行失败

**验收标准**:
- [ ] 定时误差低于100ms
- [ ] 支持至少100个并发任务
- [ ] 任务执行超时有明确处理

### 2.5 通知告警系统

**需求ID**: REQ-103-05
**优先级**: 中

**功能描述**:
提供多种渠道的通知告警功能，及时反馈交易状态。

**详细需求**:

1. **通知渠道**
   - 邮件通知（SMTP）
   - 短信通知（可选）
   - 企业微信/钉钉（Webhook）
   - 日志记录

2. **告警级别**
   ```python
   class AlertLevel:
       DEBUG    # 调试信息
       INFO     # 一般信息
       WARNING  # 警告
       ERROR    # 错误
       CRITICAL # 严重错误
   ```

3. **告警场景**
   - 订单委托成功/失败
   - 订单成交/撤单
   - 系统异常
   - 风险触发

**验收标准**:
- [ ] 通知延迟低于5秒
- [ ] 支持至少3种通知渠道
- [ ] 告警去重机制生效

### 2.6 实时行情增强

**需求ID**: REQ-103-06
**优先级**: 低

**功能描述**:
增强实时行情处理能力，支持Level2数据和多种行情源。

**详细需求**:

1. **五档行情支持**
   ```python
   # 访问五档行情
   data.ask_price_1    # 卖一价
   data.ask_volume_1   # 卖一量
   data.bid_price_1    # 买一价
   data.bid_volume_1   # 买一量
   # ... 共五档
   ```

2. **大单检测**
   - 自动检测大单交易
   - 大单流向分析
   - 主力资金流向

3. **平均成交价计算**
   ```python
   # 计算大单的平均成交价
   avg_price = data.get_avg_buy_price(amount=100000)
   ```

**验收标准**:
- [ ] 五档行情更新延迟低于50ms
- [ ] 大单检测准确率高于95%
- [ ] 支持至少3种行情源

### 2.7 模拟交易模式

**需求ID**: REQ-103-07
**优先级**: 低

**功能描述**:
提供模拟交易模式，在不实际下单的情况下验证策略。

**详细需求**:

1. **模拟模式启用**
   ```python
   cerebro = bt.Cerebro(simulate=True)
   # 或者
   order.set_simulate(True)
   ```

2. **模拟成交规则**
   - 限价单：价格优于或等于当前价成交
   - 市价单：以对手价成交
   - 部分成交处理
   - 滑点模拟

3. **模拟记录**
   - 记录所有模拟委托
   - 模拟成交记录
   - 与实盘对比分析

**验收标准**:
- [ ] 模拟逻辑与实盘一致
- [ ] 模拟结果可导出
- [ ] 支持模拟/实盘切换

---

## 三、设计文档

### 3.1 订单依赖关系系统设计

#### 3.1.1 类设计

```python
from enum import IntEnum
from typing import List, Optional, Dict
from collections import deque

class DependenceType(IntEnum):
    """依赖类型"""
    AFTER_SUBMITTED = 0   # 提交后
    AFTER_ACCEPTED = 1    # 接受后
    AFTER_PARTIAL = 2     # 部分成交后
    AFTER_FILLED = 3      # 全部成交后
    AFTER_CANCELED = 4    # 撤单后

class OrderDependence:
    """订单依赖关系"""

    def __init__(self, from_order: 'Order', dep_type: DependenceType):
        self.from_order = from_order        # 被依赖的订单
        self.dep_type = dep_type            # 依赖类型
        self._status = 'WAIT'               # WAIT/READY/FAILED

    @property
    def is_ready(self) -> bool:
        """检查依赖是否满足"""
        if self.from_order is None:
            return True

        from_order_status = self.from_order.status

        if self.dep_type == DependenceType.AFTER_SUBMITTED:
            return from_order_status in [Order.Submitted, Order.Accepted,
                                         Order.Partial, Order.Completed]
        elif self.dep_type == DependenceType.AFTER_ACCEPTED:
            return from_order_status in [Order.Accepted, Order.Partial, Order.Completed]
        elif self.dep_type == DependenceType.AFTER_PARTIAL:
            return from_order_status in [Order.Partial, Order.Completed]
        elif self.dep_type == DependenceType.AFTER_FILLED:
            return from_order_status == Order.Completed
        elif self.dep_type == DependenceType.AFTER_CANCELED:
            return from_order_status == Order.Canceled

        return False

    @property
    def is_failed(self) -> bool:
        """检查依赖是否失败（无法满足）"""
        if self.from_order is None:
            return False
        return self.from_order.status in [Order.Canceled, Order.Rejected, Order.Expired]


class EnhancedOrder(bt.Order):
    """增强的订单类，支持依赖关系"""

    def __init__(self):
        super().__init__()
        self._dependencies: List[OrderDependence] = []
        self._dependent_orders: List['EnhancedOrder'] = []

    def add_dependency(self, from_order: 'EnhancedOrder',
                       dep_type: DependenceType) -> 'EnhancedOrder':
        """添加依赖关系"""
        dep = OrderDependence(from_order, dep_type)
        self._dependencies.append(dep)
        from_order._dependent_orders.append(self)
        return self

    def then_buy(self, **kwargs) -> 'EnhancedOrder':
        """链式创建：本订单成交后买入"""
        new_order = self.owner.buy(**kwargs)
        if isinstance(new_order, EnhancedOrder):
            new_order.add_dependency(self, DependenceType.AFTER_FILLED)
        return new_order

    def then_sell(self, **kwargs) -> 'EnhancedOrder':
        """链式创建：本订单成交后卖出"""
        new_order = self.owner.sell(**kwargs)
        if isinstance(new_order, EnhancedOrder):
            new_order.add_dependency(self, DependenceType.AFTER_FILLED)
        return new_order

    @property
    def dependencies_ready(self) -> bool:
        """所有依赖是否都满足"""
        return all(d.is_ready for d in self._dependencies)

    @property
    def dependencies_failed(self) -> bool:
        """是否有依赖失败"""
        return any(d.is_failed for d in self._dependencies)


class OrderDependencyManager:
    """订单依赖管理器"""

    def __init__(self):
        self._pending_orders: deque = deque()
        self._active_orders: Dict[int, EnhancedOrder] = {}

    def submit_order(self, order: EnhancedOrder) -> bool:
        """提交订单，检查依赖"""
        if order.dependencies_failed:
            order.reject(reason='Dependency failed')
            return False

        if order.dependencies_ready:
            # 依赖满足，可以提交
            self._active_orders[order.order_id] = order
            order.submit()
            return True
        else:
            # 等待依赖满足
            self._pending_orders.append(order)
            return True

    def check_dependencies(self, order: EnhancedOrder):
        """检查是否有等待此订单的订单可以被触发"""
        for dependent in order._dependent_orders:
            if dependent in self._pending_orders and dependent.dependencies_ready:
                self._pending_orders.remove(dependent)
                self.submit_order(dependent)

    def check_circular_dependency(self, order: EnhancedOrder,
                                  visited: set = None) -> bool:
        """检测循环依赖"""
        if visited is None:
            visited = set()

        if order in visited:
            return True  # 发现循环

        visited.add(order)

        for dep in order._dependencies:
            if dep.from_order and self.check_circular_dependency(dep.from_order, visited):
                return True

        visited.remove(order)
        return False
```

#### 3.1.2 使用示例

```python
class DependencyStrategy(bt.Strategy):
    """使用订单依赖的示例策略"""

    def next(self):
        if not self.position:
            # 开仓，成交后自动设置止损
            entry_order = self.buy(size=100)
            if entry_order:
                # 链式创建止损单
                entry_order.then_sell(
                    size=100,
                    exectype=bt.Order.Stop,
                    price=self.data.close[0] * 0.95
                )

        # 更复杂的依赖示例
        # 1. 先卖出A
        # 2. A成交后买入B
        # 3. B成交后买入C
        order_a = self.sell(data=self.dataA, size=100)

        order_b = self.buy(data=self.dataB, size=100)
        order_b.add_dependency(order_a, DependenceType.AFTER_FILLED)

        order_c = self.buy(data=self.dataC, size=100)
        order_c.add_dependency(order_b, DependenceType.AFTER_FILLED)
```

### 3.2 多进程交易执行架构设计

#### 3.2.1 架构设计

```python
import multiprocessing as mp
from multiprocessing import Manager, Process, Queue, Lock, Value
from typing import Optional, Callable
import time
import logging

class ProcessArchitecture:
    """多进程交易执行架构"""

    def __init__(self):
        # 共享内存
        self.manager = Manager()
        self.shared_state = self.manager.dict()

        # 消息队列
        self.order_queue = Queue(maxsize=1000)      # 订单队列
        self.result_queue = Queue(maxsize=1000)     # 结果队列
        self.quote_queue = Queue(maxsize=10000)     # 行情队列

        # 控制标志
        self.running = Value('i', 1)

        # 进程列表
        self.processes = []

    def start(self, cerebro):
        """启动所有进程"""

        # 1. 主进程：策略执行
        # 主进程直接运行，不需要单独Process

        # 2. 订单执行进程
        order_process = Process(
            target=self._order_executor,
            args=(cerebro.broker, self.order_queue, self.result_queue, self.running)
        )
        self.processes.append(order_process)

        # 3. 行情接收进程
        quote_process = Process(
            target=self._quote_receiver,
            args=(self.quote_queue, self.running)
        )
        self.processes.append(quote_process)

        # 4. 数据记录进程
        record_process = Process(
            target=self._data_recorder,
            args=(self.result_queue, self.running)
        )
        self.processes.append(record_process)

        # 启动所有进程
        for p in self.processes:
            p.start()

    def stop(self):
        """停止所有进程"""
        self.running.value = 0
        for p in self.processes:
            p.join(timeout=5)
            if p.is_alive():
                p.terminate()

    def _order_executor(self, broker, order_queue, result_queue, running):
        """订单执行进程"""
        logging.info("Order executor process started")

        while running.value == 1:
            try:
                # 非阻塞获取订单
                order = order_queue.get(timeout=0.1)

                # 执行订单
                try:
                    # 这里调用实际的券商API
                    result = broker.execute_order(order)
                    result_queue.put(('order', order.order_id, result))
                except Exception as e:
                    result_queue.put(('error', order.order_id, str(e)))

            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Order executor error: {e}")

        logging.info("Order executor process stopped")

    def _quote_receiver(self, quote_queue, running):
        """行情接收进程"""
        logging.info("Quote receiver process started")

        while running.value == 1:
            try:
                # 接收实时行情
                quotes = self._fetch_quotes()

                # 发送到主进程
                for quote in quotes:
                    quote_queue.put(quote)

                time.sleep(0.01)  # 10ms轮询

            except Exception as e:
                logging.error(f"Quote receiver error: {e}")

        logging.info("Quote receiver process stopped")

    def _data_recorder(self, result_queue, running):
        """数据记录进程"""
        logging.info("Data recorder process started")

        while running.value == 1:
            try:
                # 获取需要记录的数据
                data = result_queue.get(timeout=0.1)

                # 写入数据库或文件
                self._record_data(data)

            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Data recorder error: {e}")

        logging.info("Data recorder process stopped")


class EnhancedCerebro(bt.Cerebro):
    """增强的Cerebro，支持多进程架构"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.process_arch = None
        self.use_multiprocess = False

    def enable_multiprocess(self):
        """启用多进程模式"""
        self.use_multiprocess = True
        self.process_arch = ProcessArchitecture()

    def run(self, **kwargs):
        """运行回测/实盘"""

        if self.use_multiprocess:
            return self._run_multiprocess(**kwargs)
        else:
            return super().run(**kwargs)

    def _run_multiprocess(self, **kwargs):
        """多进程模式运行"""

        # 启动子进程
        self.process_arch.start(self)

        try:
            # 主进程运行策略
            results = super().run(**kwargs)
            return results
        finally:
            # 停止所有子进程
            self.process_arch.stop()

    def buy(self, **kwargs):
        """重写buy方法，将订单发送到队列"""
        if self.use_multiprocess:
            # 创建订单
            order = super().buy(**kwargs)
            # 发送到订单执行进程
            self.process_arch.order_queue.put(order)
            return order
        else:
            return super().buy(**kwargs)
```

#### 3.2.2 使用示例

```python
# 创建多进程Cerebro
cerebro = bt.Cerebro()
cerebro.enable_multiprocess()

# 添加策略和数据
cerebro.addstrategy(MyStrategy)
cerebro.adddata(data)

# 运行
result = cerebro.run()
```

### 3.3 任务调度系统设计

#### 3.3.1 类设计

```python
import time
from datetime import datetime, time as dt_time
from typing import Callable, Optional, List
from enum import IntEnum
import heapq

class TaskStatus(IntEnum):
    """任务状态"""
    PENDING = 0
    RUNNING = 1
    COMPLETED = 2
    FAILED = 3
    CANCELED = 4

class TaskPriority(IntEnum):
    """任务优先级"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

class ScheduledTask:
    """定时任务"""

    def __init__(self,
                 func: Callable,
                 trigger_time: Optional[datetime] = None,
                 interval: Optional[float] = None,
                 priority: TaskPriority = TaskPriority.NORMAL):
        self.func = func
        self.trigger_time = trigger_time
        self.interval = interval
        self.priority = priority
        self.status = TaskStatus.PENDING
        self.created_at = datetime.now()
        self.run_count = 0

    def __lt__(self, other):
        """用于堆排序，优先级高的在前"""
        if self.priority != other.priority:
            return self.priority > other.priority
        if self.trigger_time and other.trigger_time:
            return self.trigger_time < other.trigger_time
        return self.created_at < other.created_at

    def should_trigger(self, now: datetime) -> bool:
        """检查是否应该触发"""
        if self.status != TaskStatus.PENDING:
            return False
        if self.trigger_time:
            return now >= self.trigger_time
        return False

    def execute(self):
        """执行任务"""
        self.status = TaskStatus.RUNNING
        try:
            result = self.func()
            self.status = TaskStatus.COMPLETED
            self.run_count += 1

            # 如果是间隔任务，重新调度
            if self.interval:
                self.trigger_time = datetime.now() + \
                    timedelta(seconds=self.interval)
                self.status = TaskStatus.PENDING

            return result
        except Exception as e:
            self.status = TaskStatus.FAILED
            raise


class TaskScheduler:
    """任务调度器"""

    def __init__(self):
        self.tasks: List[ScheduledTask] = []
        self.running = False

    def schedule_at(self, func: Callable,
                    time_str: str,
                    priority: TaskPriority = TaskPriority.NORMAL) -> ScheduledTask:
        """在指定时间执行"""
        hour, minute, second = map(int, time_str.split(':'))
        now = datetime.now()
        trigger_time = now.replace(hour=hour, minute=minute, second=second)
        if trigger_time < now:
            trigger_time += timedelta(days=1)

        task = ScheduledTask(func, trigger_time=trigger_time, priority=priority)
        heapq.heappush(self.tasks, task)
        return task

    def schedule_after_open(self, func: Callable,
                           minutes: int,
                           priority: TaskPriority = TaskPriority.NORMAL) -> ScheduledTask:
        """开盘后N分钟执行"""
        # 这里需要获取开盘时间，简化处理
        # 实际应该从交易日历获取
        def wrapper():
            # 等待开盘后N分钟
            open_time = dt_time(9, 30)
            now = datetime.now()
            if now.time() < open_time:
                return
            trigger_time = now.replace(hour=9, minute=30, second=0)
            trigger_time += timedelta(minutes=minutes)
            return func()

        return self.schedule_at(wrapper, "09:30:00", priority)

    def schedule_interval(self, func: Callable,
                         seconds: int,
                         priority: TaskPriority = TaskPriority.NORMAL) -> ScheduledTask:
        """间隔执行"""
        task = ScheduledTask(
            func,
            trigger_time=datetime.now() + timedelta(seconds=seconds),
            interval=seconds,
            priority=priority
        )
        heapq.heappush(self.tasks, task)
        return task

    def start(self):
        """启动调度器"""
        self.running = True
        while self.running:
            now = datetime.now()
            # 执行到期的任务
            while self.tasks and self.tasks[0].should_trigger(now):
                task = heapq.heappop(self.tasks)
                try:
                    task.execute()
                    # 如果是间隔任务，重新加入
                    if task.interval:
                        heapq.heappush(self.tasks, task)
                except Exception as e:
                    logging.error(f"Task execution error: {e}")

            time.sleep(0.1)  # 100ms检查一次

    def stop(self):
        """停止调度器"""
        self.running = False


# 集成到Strategy的便捷方法
class ScheduledStrategy(bt.Strategy):
    """支持定时任务的策略基类"""

    def __init__(self):
        super().__init__()
        self.scheduler = TaskScheduler()

    def start_scheduler(self):
        """启动调度器（在独立线程中运行）"""
        import threading
        self.scheduler_thread = threading.Thread(target=self.scheduler.start)
        self.scheduler_thread.daemon = True
        self.scheduler_thread.start()

    def at(self, time_str: str):
        """装饰器：在指定时间执行"""
        def decorator(func):
            self.scheduler.schedule_at(func, time_str)
            return func
        return decorator

    def every(self, seconds: int):
        """装饰器：每隔N秒执行"""
        def decorator(func):
            self.scheduler.schedule_interval(func, seconds)
            return func
        return decorator
```

#### 3.3.2 使用示例

```python
class MyScheduledStrategy(ScheduledStrategy):
    """使用定时任务的策略"""

    def __init__(self):
        super().__init__()
        self.start_scheduler()

        # 方式1：装饰器
        @self.at("09:35:00")
        def morning_trade():
            print("早盘交易时间")
            self.buy()

        @self.at("14:50:00")
        def close_position():
            print("尾盘平仓")
            self.close()

        @self.every(60)
        def monitor():
            print("每分钟监控")
            # 监控逻辑
            pass
```

### 3.4 通知告警系统设计

#### 3.4.1 类设计

```python
from abc import ABC, abstractmethod
from typing import List, Optional
import smtplib
from email.mime.text import MIMEText
import requests

class AlertLevel(IntEnum):
    """告警级别"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4

class Notifier(ABC):
    """通知器抽象基类"""

    @abstractmethod
    def send(self, message: str, level: AlertLevel = AlertLevel.INFO):
        """发送通知"""
        pass


class EmailNotifier(Notifier):
    """邮件通知器"""

    def __init__(self,
                 smtp_server: str,
                 from_addr: str,
                 password: str,
                 to_addrs: List[str]):
        self.smtp_server = smtp_server
        self.from_addr = from_addr
        self.password = password
        self.to_addrs = to_addrs

    def send(self, message: str, level: AlertLevel = AlertLevel.INFO):
        subject = f"[{level.name}] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        msg = MIMEText(message, 'plain', 'utf-8')
        msg['From'] = self.from_addr
        msg['To'] = ', '.join(self.to_addrs)
        msg['Subject'] = subject

        with smtplib.SMTP(self.smtp_server, 25) as server:
            server.starttls()
            server.login(self.from_addr, self.password)
            server.send_message(msg)


class WebhookNotifier(Notifier):
    """Webhook通知器（钉钉/企业微信）"""

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, message: str, level: AlertLevel = AlertLevel.INFO):
        payload = {
            "msgtype": "text",
            "text": {
                "content": f"[{level.name}] {message}"
            }
        }
        requests.post(self.webhook_url, json=payload)


class CompositeNotifier(Notifier):
    """组合通知器"""

    def __init__(self):
        self.notifiers: List[Notifier] = []

    def add_notifier(self, notifier: Notifier):
        """添加通知器"""
        self.notifiers.append(notifier)
        return self

    def send(self, message: str, level: AlertLevel = AlertLevel.INFO):
        """发送到所有通知器"""
        for notifier in self.notifiers:
            try:
                notifier.send(message, level)
            except Exception as e:
                logging.error(f"Notifier error: {e}")


class NotificationManager:
    """通知管理器"""

    def __init__(self):
        self.notifier = CompositeNotifier()
        self.alert_history = {}  # 用于去重

    def setup_email(self, smtp_server: str, from_addr: str,
                    password: str, to_addrs: List[str]):
        """设置邮件通知"""
        email_notifier = EmailNotifier(smtp_server, from_addr, password, to_addrs)
        self.notifier.add_notifier(email_notifier)

    def setup_webhook(self, webhook_url: str):
        """设置Webhook通知"""
        webhook_notifier = WebhookNotifier(webhook_url)
        self.notifier.add_notifier(webhook_notifier)

    def notify(self, message: str, level: AlertLevel = AlertLevel.INFO,
               dedup_key: Optional[str] = None):
        """发送通知（支持去重）"""
        # 去重逻辑
        if dedup_key:
            last_time = self.alert_history.get(dedup_key, 0)
            if time.time() - last_time < 300:  # 5分钟内不重复发送
                return
            self.alert_history[dedup_key] = time.time()

        self.notifier.send(message, level)


# 集成到Cerebro
class NotifiableCerebro(bt.Cerebro):
    """支持通知的Cerebro"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.notification_manager = NotificationManager()

    def notify(self, message: str, level: AlertLevel = AlertLevel.INFO,
               dedup_key: Optional[str] = None):
        """发送通知"""
        self.notification_manager.notify(message, level, dedup_key)
```

#### 3.4.2 使用示例

```python
# 创建支持通知的Cerebro
cerebro = NotifiableCerebro()

# 设置通知方式
cerebro.notification_manager.setup_email(
    smtp_server="smtp.example.com",
    from_addr="bot@example.com",
    password="password",
    to_addrs=["trader@example.com"]
)

cerebro.notification_manager.setup_webhook(
    webhook_url="https://oapi.dingtalk.com/robot/send?access_token=xxx"
)

# 在策略中使用
class NotifiedStrategy(bt.Strategy):
    """支持通知的策略"""

    def notify(self, message: str, level: AlertLevel = AlertLevel.INFO):
        """发送通知"""
        self.env.notification_manager.notify(message, level)

    def next(self):
        if self.data.close[0] > self.data.close[-1] * 1.05:
            self.notify("涨幅超过5%，准备买入", AlertLevel.INFO)
            self.buy()
```

### 3.5 实时行情增强设计

```python
class Level2Data(bt.feeds.DataBase):
    """Level2行情数据源"""

    lines = (
        'bid_price_1', 'bid_volume_1',
        'bid_price_2', 'bid_volume_2',
        'bid_price_3', 'bid_volume_3',
        'bid_price_4', 'bid_volume_4',
        'bid_price_5', 'bid_volume_5',
        'ask_price_1', 'ask_volume_1',
        'ask_price_2', 'ask_volume_2',
        'ask_price_3', 'ask_volume_3',
        'ask_price_4', 'ask_volume_4',
        'ask_price_5', 'ask_volume_5',
    )

    def get_avg_buy_price(self, amount: int) -> tuple:
        """计算买入指定数量的平均价格"""
        total_cost = 0
        total_volume = 0

        for i in range(1, 6):
            ask_price = getattr(self.lines, f'ask_price_{i}')[0]
            ask_volume = getattr(self.lines, f'ask_volume_{i}')[0]

            if total_volume + ask_volume >= amount:
                needed = amount - total_volume
                total_cost += needed * ask_price
                total_volume = amount
                break
            else:
                total_cost += ask_volume * ask_price
                total_volume += ask_volume

        if total_volume == 0:
            return 0, 0

        avg_price = total_cost / total_volume
        return avg_price, total_volume

    def get_avg_sell_price(self, amount: int) -> tuple:
        """计算卖出指定数量的平均价格"""
        total_cost = 0
        total_volume = 0

        for i in range(1, 6):
            bid_price = getattr(self.lines, f'bid_price_{i}')[0]
            bid_volume = getattr(self.lines, f'bid_volume_{i}')[0]

            if total_volume + bid_volume >= amount:
                needed = amount - total_volume
                total_cost += needed * bid_price
                total_volume = amount
                break
            else:
                total_cost += bid_volume * bid_price
                total_volume += bid_volume

        if total_volume == 0:
            return 0, 0

        avg_price = total_cost / total_volume
        return avg_price, total_volume


class LargeOrderDetector(bt.Indicator):
    """大单检测器"""

    lines = ('large_buy', 'large_sell', 'net_flow')

    params = (
        ('threshold', 1000000),  # 大单阈值（元）
    )

    def __init__(self):
        super().__init__()

    def next(self):
        if not hasattr(self.data, 'ask_volume_1'):
            return

        # 计算大单买入/卖出
        large_buy = 0
        large_sell = 0

        for i in range(1, 6):
            ask_price = getattr(self.data.lines, f'ask_price_{i}')[0]
            ask_vol = getattr(self.data.lines, f'ask_volume_{i}')[0]
            bid_price = getattr(self.data.lines, f'bid_price_{i}')[0]
            bid_vol = getattr(self.data.lines, f'bid_volume_{i}')[0]

            if ask_price * ask_vol > self.p.threshold:
                large_buy += ask_price * ask_vol
            if bid_price * bid_vol > self.p.threshold:
                large_sell += bid_price * bid_vol

        self.lines.large_buy[0] = large_buy
        self.lines.large_sell[0] = large_sell
        self.lines.net_flow[0] = large_buy - large_sell


# 使用示例
class Level2Strategy(bt.Strategy):
    """使用Level2数据的策略"""

    def __init__(self):
        # 添加大单检测器
        self.large_order = LargeOrderDetector(self.data)

    def next(self):
        # 检查是否有大单
        if self.large_order.net_flow[0] > 5000000:
            # 大单净流入，可能上涨
            pass

        # 计算大单买入的平均价格
        if hasattr(self.data, 'get_avg_buy_price'):
            avg_price, volume = self.data.get_avg_buy_price(100000)
            if volume >= 100000:
                self.buy(price=avg_price)
```

---

## 四、实施路线图

### 阶段一：基础增强（1-2个月）

**目标**: 实现核心增强功能，提升实盘交易能力

1. **订单依赖关系系统**（3周）
   - Week 1: 设计Dependence和EnhancedOrder类
   - Week 2: 实现OrderDependencyManager
   - Week 3: 单元测试和集成测试

2. **通知告警系统**（2周）
   - Week 1: 实现EmailNotifier和WebhookNotifier
   - Week 2: 集成到Cerebro，添加去重逻辑

3. **模拟交易模式**（1周）
   - 实现simulate标志和模拟成交逻辑

### 阶段二：架构升级（2-3个月）

**目标**: 实现多进程架构和任务调度

1. **多进程交易执行架构**（4周）
   - Week 1-2: 设计进程架构和通信机制
   - Week 3: 实现订单执行进程
   - Week 4: 实现行情接收和数据记录进程

2. **任务调度系统**（3周）
   - Week 1: 实现TaskScheduler核心逻辑
   - Week 2: 实现ScheduledStrategy
   - Week 3: 测试和优化

3. **券商接口抽象层**（4周）
   - Week 1-2: 定义BrokerAdapter接口
   - Week 3: 实现至少2家券商适配
   - Week 4: 风控检查机制

### 阶段三：功能完善（2-3个月）

**目标**: 完善Level2行情和高级功能

1. **Level2行情支持**（3周）
   - Week 1: 实现Level2Data数据源
   - Week 2: 实现LargeOrderDetector
   - Week 3: 性能优化

2. **实盘交易增强**（4周）
   - Week 1-2: 会话管理和重连机制
   - Week 3: 订单状态同步
   - Week 4: 异常处理和恢复

### 阶段四：测试和文档（1-2个月）

**目标**: 全面测试和完善文档

1. **单元测试覆盖**（2周）
2. **集成测试**（2周）
3. **文档编写**（2周）
4. **示例代码**（1周）

### 总时间估算：6-10个月

---

## 五、总结

### 5.1 AutoTrade的核心优势

1. **模块化策略系统**: 清晰的策略抽象，易于扩展
2. **Job依赖系统**: 独特的订单依赖机制，支持复杂策略
3. **多进程架构**: 稳定的进程分离设计
4. **简洁实用**: 专注于实盘交易，不过度设计

### 5.2 对Backtrader的借鉴价值

1. **订单依赖**: 这是AutoTrade最独特的功能，对复杂策略非常有价值
2. **多进程设计**: 对实盘交易的稳定性很重要
3. **任务调度**: 补充了backtrader在定时任务方面的不足
4. **模拟交易**: 对策略验证很有帮助

### 5.3 实施建议

1. **优先级**: 订单依赖 > 通知系统 > 模拟交易 > 多进程 > 任务调度
2. **兼容性**: 所有新功能都应保持与现有API的兼容
3. **渐进式**: 可以分阶段实施，每个阶段都是可用的
4. **测试**: 实盘功能需要充分的测试，建议先在模拟环境验证
