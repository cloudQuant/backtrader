# Backtrader 现代化改进指南

## 目录
1. [架构优化](#架构优化)
2. [性能优化](#性能优化)
3. [功能增强](#功能增强)
4. [开发体验](#开发体验)
5. [实施路线图](#实施路线图)

## 架构优化

### 1. 核心引擎重构

#### 1.1 异步支持
```python
import asyncio
from typing import List, Dict, Any

class ModernCerebro:
    def __init__(self):
        self.strategies = []
        self.data_feeds = []
        self.brokers = []
        
    async def run(self) -> List[Any]:
        """异步运行回测/实盘"""
        await self._initialize()
        results = await self._execute_strategies()
        return results
        
    async def _initialize(self):
        """异步初始化所有组件"""
        init_tasks = [
            self._init_data_feeds(),
            self._init_brokers(),
            self._init_strategies()
        ]
        await asyncio.gather(*init_tasks)
```

#### 1.2 模块化改进
```python
from abc import ABC, abstractmethod
from typing import Protocol

class DataFeedProtocol(Protocol):
    async def fetch_data(self): ...
    async def preprocess(self): ...
    
class StrategyProtocol(Protocol):
    async def analyze(self): ...
    async def execute(self): ...

class BaseModule(ABC):
    @abstractmethod
    async def initialize(self): ...
    @abstractmethod
    async def cleanup(self): ...
```

### 2. 数据处理优化

#### 2.1 向量化计算
```python
import numpy as np
from numba import jit

@jit(nopython=True)
def calculate_indicators(prices: np.ndarray) -> np.ndarray:
    """使用Numba加速指标计算"""
    return np.mean(prices)

class OptimizedDataFeed:
    def __init__(self):
        self.data = np.array([])
        
    def process_batch(self, batch_size: int = 1000):
        """批量处理数据"""
        return calculate_indicators(self.data[:batch_size])
```

## 性能优化

### 1. 内存管理

#### 1.1 智能数据加载
```python
class SmartDataLoader:
    def __init__(self, chunk_size: int = 1000):
        self.chunk_size = chunk_size
        self.current_chunk = None
        
    async def load_chunk(self, start: int, end: int):
        """异步加载数据块"""
        self.current_chunk = await self._fetch_data(start, end)
        
    def release_chunk(self):
        """释放不需要的数据"""
        self.current_chunk = None
```

#### 1.2 缓存优化
```python
from functools import lru_cache
from typing import Dict, Any

class CacheManager:
    def __init__(self):
        self.cache: Dict[str, Any] = {}
        
    @lru_cache(maxsize=1000)
    def get_cached_data(self, key: str):
        """获取缓存数据"""
        return self.cache.get(key)
```

### 2. 并行计算

#### 2.1 多进程回测
```python
from concurrent.futures import ProcessPoolExecutor
from typing import List

class ParallelBacktester:
    def __init__(self, max_workers: int = None):
        self.max_workers = max_workers
        
    async def run_parallel(self, strategies: List[Any], data: Any):
        """并行执行回测"""
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            results = list(executor.map(self._run_strategy, strategies))
        return results
        
    def _run_single_backtest(self, args):
        """运行单个回测"""
        strategy, data = args
        return self._execute_strategy(strategy, data)
```

## 功能增强

### 1. 风险管理

```python
class RiskManager:
    def __init__(self):
        self.position_limits = {}
        self.risk_metrics = {}
        
    async def check_risk(self, order):
        """检查订单风险"""
        if not self._validate_position_limits(order):
            return False
        return await self._calculate_risk_metrics(order)
```

### 2. 实时监控

```python
class MonitoringSystem:
    def __init__(self):
        self.metrics = {}
        self.alerts = []
        
    async def update_metrics(self, new_data):
        """更新监控指标"""
        await self._process_metrics(new_data)
        await self._check_alerts()
```

## 开发体验

### 1. 日志系统

```python
import logging
from typing import Any

class StructuredLogger:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
    def log_event(self, event_type: str, data: Any):
        """结构化日志记录"""
        self.logger.info({
            'event_type': event_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
```

### 2. 调试工具

```python
class DebugTool:
    def __init__(self):
        self.breakpoints = set()
        self.watches = {}
        
    def add_watch(self, variable_name: str, condition: callable):
        """添加变量监视"""
        self.watches[variable_name] = condition
```

## 具体实现指南

### 1. 异步核心引擎实现

#### 1.1 事件循环管理
```python
class EventLoop:
    def __init__(self):
        self._loop = asyncio.get_event_loop()
        self._tasks = []
        
    async def add_task(self, coro):
        """添加异步任务"""
        task = self._loop.create_task(coro)
        self._tasks.append(task)
        
    async def run(self):
        """运行所有任务"""
        await asyncio.gather(*self._tasks)
```

#### 1.2 数据流管理
```python
from asyncio import Queue
from typing import Dict, List

class DataStreamManager:
    def __init__(self):
        self._queues: Dict[str, Queue] = {}
        self._subscribers: Dict[str, List[callable]] = {}
        
    async def publish(self, topic: str, data: Any):
        """发布数据到指定主题"""
        if topic in self._queues:
            await self._queues[topic].put(data)
            
    async def subscribe(self, topic: str, callback: callable):
        """订阅特定主题"""
        if topic not in self._subscribers:
            self._subscribers[topic] = []
        self._subscribers[topic].append(callback)
```

### 2. 性能优化实现

#### 2.1 数据预处理优化
```python
import pandas as pd
from numba import jit

class DataPreprocessor:
    def __init__(self):
        self._cache = {}
        
    @jit(nopython=True)
    def _calculate_technical_indicators(self, data: np.ndarray) -> Dict[str, np.ndarray]:
        """使用Numba加速技术指标计算"""
        return {
            'sma': self._calculate_sma(data),
            'ema': self._calculate_ema(data),
            'rsi': self._calculate_rsi(data)
        }
        
    def process_batch(self, data: pd.DataFrame) -> pd.DataFrame:
        """批量处理数据"""
        # 使用pandas的向量化操作
        processed = data.copy()
        processed['returns'] = data['close'].pct_change()
        processed['volatility'] = data['returns'].rolling(window=20).std()
        return processed
```

#### 2.2 内存优化
```python
class MemoryOptimizedDataFrame:
    def __init__(self, data: pd.DataFrame):
        self._optimize_dtypes(data)
        
    def _optimize_dtypes(self, df: pd.DataFrame):
        """优化DataFrame的数据类型"""
        for col in df.select_dtypes(include=['float64']).columns:
            df[col] = df[col].astype('float32')
        for col in df.select_dtypes(include=['int64']).columns:
            df[col] = df[col].astype('int32')
```

### 3. 实时交易增强

#### 3.1 订单管理系统
```python
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELED = "canceled"
    FILLED = "filled"

@dataclass
class Order:
    id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: OrderStatus
    created_at: datetime
    
class OrderManager:
    def __init__(self):
        self.orders: Dict[str, Order] = {}
        self.filled_orders: List[Order] = []
        
    async def submit_order(self, order: Order):
        """提交订单"""
        self.orders[order.id] = order
        await self._process_order(order)
        
    async def cancel_order(self, order_id: str):
        """取消订单"""
        if order_id in self.orders:
            order = self.orders[order_id]
            order.status = OrderStatus.CANCELED
            await self._notify_cancellation(order)
```

#### 3.2 风险控制系统
```python
class RiskController:
    def __init__(self, max_position_size: float, max_drawdown: float):
        self.max_position_size = max_position_size
        self.max_drawdown = max_drawdown
        self.current_drawdown = 0.0
        
    async def check_order(self, order: Order) -> bool:
        """检查订单是否符合风险控制要求"""
        if not await self._check_position_limit(order):
            return False
        if not await self._check_drawdown():
            return False
        return True
        
    async def update_metrics(self, portfolio_value: float):
        """更新风险指标"""
        self.current_drawdown = self._calculate_drawdown(portfolio_value)
```

### 4. 回测引擎优化

#### 4.1 并行回测实现
```python
from multiprocessing import Pool
from typing import List, Dict

class ParallelBacktester:
    def __init__(self, num_processes: int = None):
        self.num_processes = num_processes
        
    def run_parallel_backtest(self, strategies: List[Dict], data: pd.DataFrame):
        """并行执行多个回测"""
        with Pool(processes=self.num_processes) as pool:
            results = pool.map(self._run_single_backtest, 
                             [(strategy, data) for strategy in strategies])
        return results
        
    def _run_single_backtest(self, args):
        """运行单个回测"""
        strategy, data = args
        return self._execute_strategy(strategy, data)
```

#### 4.2 结果分析优化
```python
class BacktestAnalyzer:
    def __init__(self):
        self.metrics = {}
        
    def calculate_metrics(self, results: pd.DataFrame):
        """计算回测指标"""
        self.metrics['sharpe_ratio'] = self._calculate_sharpe_ratio(results)
        self.metrics['max_drawdown'] = self._calculate_max_drawdown(results)
        self.metrics['win_rate'] = self._calculate_win_rate(results)
        
    def generate_report(self) -> Dict:
        """生成回测报告"""
        return {
            'summary': self.metrics,
            'trades': self._analyze_trades(),
            'performance': self._analyze_performance()
        }
```

### 5. 开发工具实现

#### 5.1 性能分析器
```python
import cProfile
import pstats
from functools import wraps

def profile(func):
    """性能分析装饰器"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        profile = cProfile.Profile()
        try:
            return profile.runcall(func, *args, **kwargs)
        finally:
            stats = pstats.Stats(profile)
            stats.sort_stats('cumulative')
            stats.print_stats()
    return wrapper

class PerformanceAnalyzer:
    def __init__(self):
        self.metrics = {}
        
    def track_time(self, func):
        """跟踪函数执行时间"""
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            result = await func(*args, **kwargs)
            end_time = time.time()
            
            self.metrics[func.__name__] = end_time - start_time
            return result
        return wrapper
```

#### 5.2 调试工具
```python
class Debugger:
    def __init__(self):
        self.breakpoints = set()
        self.call_stack = []
        
    def set_breakpoint(self, func_name: str):
        """设置断点"""
        self.breakpoints.add(func_name)
        
    def trace_calls(self, frame, event, arg):
        """跟踪函数调用"""
        if event == 'call':
            func_name = frame.f_code.co_name
            if func_name in self.breakpoints:
                self.call_stack.append(frame)
                self._print_debug_info(frame)
```

## 实施路线图

### 第一阶段：基础架构现代化（1-2个月）
1. 实现异步核心引擎
2. 重构数据处理模块
3. 添加基础性能优化

### 第二阶段：性能优化（2-3个月）
1. 实现并行回测系统
2. 优化内存管理
3. 添加缓存系统

### 第三阶段：功能扩展（2-3个月）
1. 增强风险管理
2. 添加实时监控
3. 改进回测引擎

### 第四阶段：开发体验提升（1-2个月）
1. 改进日志系统
2. 添加调试工具
3. 完善文档系统

## 贡献指南

1. 代码风格
   - 使用 Python 类型注解
   - 遵循 PEP 8 规范
   - 编写详细的文档字符串

2. 测试要求
   - 单元测试覆盖率 > 80%
   - 添加性能基准测试
   - 包含集成测试

3. 提交规范
   - 使用语义化版本号
   - 提供详细的提交信息
   - 包含测试用例

## 注意事项

1. 向后兼容性
   - 保持核心API稳定
   - 提供迁移工具
   - 详细的升级指南

2. 性能考虑
   - 监控内存使用
   - 优化计算密集型操作
   - 减少I/O操作

3. 安全性
   - 数据验证
   - 错误处理
   - 日志审计

## 数据处理系统优化

### 6.1 高性能数据引擎
```python
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class Bar:
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    
class HighPerformanceDataEngine:
    def __init__(self):
        self._data: Dict[str, pd.DataFrame] = {}
        self._indicators: Dict[str, np.ndarray] = {}
        
    def add_data(self, symbol: str, data: pd.DataFrame):
        """添加数据到引擎"""
        # 优化数据类型以减少内存使用
        data = self._optimize_dtypes(data)
        # 预计算常用指标
        self._precalculate_indicators(symbol, data)
        self._data[symbol] = data
        
    def _optimize_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        """优化DataFrame数据类型"""
        # 将浮点数转换为float32
        float_cols = df.select_dtypes(include=['float64']).columns
        df[float_cols] = df[float_cols].astype('float32')
        
        # 将整数转换为适当的类型
        int_cols = df.select_dtypes(include=['int64']).columns
        df[int_cols] = df[int_cols].astype('int32')
        
        return df
        
    def _precalculate_indicators(self, symbol: str, data: pd.DataFrame):
        """预计算常用技术指标"""
        close = data['close'].values
        self._indicators[symbol] = {
            'sma_20': self._calculate_sma(close, 20),
            'sma_50': self._calculate_sma(close, 50),
            'rsi_14': self._calculate_rsi(close, 14)
        }
        
    @staticmethod
    @jit(nopython=True)
    def _calculate_sma(data: np.ndarray, window: int) -> np.ndarray:
        """使用Numba加速SMA计算"""
        result = np.zeros_like(data)
        for i in range(window - 1, len(data)):
            result[i] = np.mean(data[i - window + 1:i + 1])
        return result
```

### 6.2 实时数据处理
```python
from asyncio import Queue
from datetime import datetime, timedelta

class RealTimeDataProcessor:
    def __init__(self):
        self._queues: Dict[str, Queue] = {}
        self._latest_bars: Dict[str, Bar] = {}
        self._callbacks: Dict[str, List[callable]] = {}
        
    async def process_tick(self, symbol: str, tick: Dict):
        """处理实时行情数据"""
        # 更新最新行情
        self._update_latest_bar(symbol, tick)
        
        # 检查是否需要生成新的K线
        if self._should_create_new_bar(symbol):
            bar = self._create_bar(symbol)
            await self._publish_bar(symbol, bar)
            
    def _update_latest_bar(self, symbol: str, tick: Dict):
        """更新最新K线数据"""
        if symbol not in self._latest_bars:
            self._latest_bars[symbol] = Bar(
                timestamp=pd.Timestamp(tick['timestamp']),
                open=tick['price'],
                high=tick['price'],
                low=tick['price'],
                close=tick['price'],
                volume=tick['volume']
            )
        else:
            bar = self._latest_bars[symbol]
            bar.high = max(bar.high, tick['price'])
            bar.low = min(bar.low, tick['price'])
            bar.close = tick['price']
            bar.volume += tick['volume']
            
    async def _publish_bar(self, symbol: str, bar: Bar):
        """发布K线数据"""
        if symbol in self._queues:
            await self._queues[symbol].put(bar)
        
        # 触发回调
        for callback in self._callbacks.get(symbol, []):
            await callback(bar)
```

## 实时交易系统增强

### 7.1 订单路由系统
```python
from enum import Enum
from uuid import uuid4

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

class OrderRouter:
    def __init__(self):
        self._routes: Dict[str, List[str]] = {}  # symbol -> exchanges
        self._active_orders: Dict[str, Order] = {}
        
    async def route_order(self, order: Order) -> bool:
        """智能路由订单到最优交易所"""
        best_exchange = await self._find_best_exchange(order)
        if best_exchange:
            return await self._submit_to_exchange(order, best_exchange)
        return False
        
    async def _find_best_exchange(self, order: Order) -> Optional[str]:
        """找到最优的交易所"""
        if order.symbol not in self._routes:
            return None
            
        best_price = float('inf') if order.side == 'buy' else 0
        best_exchange = None
        
        for exchange in self._routes[order.symbol]:
            price = await self._get_exchange_price(exchange, order)
            if order.side == 'buy' and price < best_price:
                best_price = price
                best_exchange = exchange
            elif order.side == 'sell' and price > best_price:
                best_price = price
                best_exchange = exchange
                
        return best_exchange
```

### 7.2 智能执行引擎
```python
class ExecutionEngine:
    def __init__(self):
        self._active_orders: Dict[str, Order] = {}
        self._execution_strategies: Dict[str, callable] = {}
        
    async def execute_order(self, order: Order):
        """执行订单"""
        # 生成订单ID
        order.id = str(uuid4())
        
        # 选择执行策略
        strategy = self._select_execution_strategy(order)
        
        # 执行订单
        try:
            result = await strategy(order)
            await self._handle_execution_result(order, result)
        except Exception as e:
            await self._handle_execution_error(order, e)
            
    def _select_execution_strategy(self, order: Order) -> callable:
        """选择最适合的执行策略"""
        if order.type == OrderType.MARKET:
            return self._execute_market_order
        elif order.type == OrderType.LIMIT:
            return self._execute_limit_order
        elif order.type == OrderType.STOP:
            return self._execute_stop_order
        else:
            return self._execute_stop_limit_order
            
    async def _execute_market_order(self, order: Order):
        """执行市价单"""
        # 实现智能市价单执行逻辑
        # 1. 评估市场冲击
        impact = await self._estimate_market_impact(order)
        
        # 2. 如果订单较大，考虑拆分
        if impact > self.IMPACT_THRESHOLD:
            return await self._execute_large_order(order)
            
        # 3. 直接执行小订单
        return await self._execute_small_order(order)
```

### 8. 风险管理系统增强

#### 8.1 实时风险监控
```python
class RiskMonitor:
    def __init__(self):
        self._position_limits: Dict[str, float] = {}
        self._exposure_limits: Dict[str, float] = {}
        self._risk_metrics: Dict[str, float] = {}
        
    async def monitor_portfolio(self, portfolio: Dict):
        """监控投资组合风险"""
        # 计算风险指标
        metrics = await self._calculate_risk_metrics(portfolio)
        
        # 检查风险限制
        violations = self._check_risk_limits(metrics)
        
        # 如果发现风险违规，采取行动
        if violations:
            await self._handle_risk_violations(violations)
            
    async def _calculate_risk_metrics(self, portfolio: Dict) -> Dict:
        """计算风险指标"""
        return {
            'var': self._calculate_var(portfolio),
            'leverage': self._calculate_leverage(portfolio),
            'concentration': self._calculate_concentration(portfolio),
            'liquidity': self._calculate_liquidity(portfolio)
        }

```

### 9. 性能优化指南

#### 9.1 缓存系统
```python
from functools import lru_cache
import joblib
from typing import Any, Dict, List

class CacheManager:
    def __init__(self, cache_dir: str = ".cache"):
        self.cache_dir = cache_dir
        self._memory = joblib.Memory(cache_dir, verbose=0)
        
    @lru_cache(maxsize=1000)
    def get_cached_data(self, key: str) -> Any:
        """从内存缓存获取数据"""
        return self._data_cache.get(key)
        
    def cache_to_disk(self, func):
        """持久化缓存装饰器"""
        return self._memory.cache(func)
        
    def clear_cache(self):
        """清理缓存"""
        self._memory.clear()
        get_cached_data.cache_clear()
```

#### 9.2 性能分析工具
```python
import time
import cProfile
import line_profiler
from typing import Dict, List, Callable

class PerformanceProfiler:
    def __init__(self):
        self._profiler = line_profiler.LineProfiler()
        self._stats: Dict[str, Dict] = {}
        
    def profile_function(self, func: Callable):
        """对函数进行性能分析"""
        wrapped = self._profiler(func)
        self._profiler.enable()
        result = wrapped()
        self._profiler.disable()
        self._stats[func.__name__] = self._profiler.get_stats()
        return result
        
    def generate_report(self) -> Dict:
        """生成性能报告"""
        return {
            name: {
                'total_time': stats.total_time,
                'hits': stats.hits,
                'time_per_hit': stats.total_time / stats.hits if stats.hits else 0
            }
            for name, stats in self._stats.items()
        }
```

### 10. 测试框架

#### 10.1 单元测试框架
```python
import pytest
import numpy as np
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class TestCase:
    name: str
    input_data: Dict
    expected_output: Dict
    
class BacktestingTestSuite:
    def __init__(self):
        self.test_cases: List[TestCase] = []
        
    def add_test_case(self, test_case: TestCase):
        """添加测试用例"""
        self.test_cases.append(test_case)
        
    def run_tests(self) -> Dict[str, bool]:
        """运行所有测试用例"""
        results = {}
        for case in self.test_cases:
            try:
                actual_output = self._run_single_test(case)
                results[case.name] = self._compare_results(
                    actual_output, case.expected_output
                )
            except Exception as e:
                results[case.name] = False
        return results
        
    def _compare_results(self, actual: Dict, expected: Dict) -> bool:
        """比较测试结果"""
        # 对于numpy数组使用np.allclose
        for key in expected:
            if isinstance(expected[key], np.ndarray):
                if not np.allclose(actual[key], expected[key]):
                    return False
            elif actual[key] != expected[key]:
                return False
        return True
```

#### 10.2 集成测试框架
```python
from typing import List, Dict, Any
import asyncio
import pytest

class IntegrationTestSuite:
    def __init__(self):
        self.test_scenarios: List[Dict] = []
        
    async def test_full_workflow(self):
        """测试完整的交易流程"""
        # 1. 设置测试环境
        await self._setup_test_environment()
        
        # 2. 创建模拟数据源
        data_feed = await self._create_mock_data_feed()
        
        # 3. 初始化策略
        strategy = await self._initialize_strategy()
        
        # 4. 运行回测
        results = await self._run_backtest(strategy, data_feed)
        
        # 5. 验证结果
        assert self._validate_results(results)
        
    async def test_real_time_processing(self):
        """测试实时数据处理"""
        # 1. 创建模拟的实时数据流
        mock_stream = self._create_mock_data_stream()
        
        # 2. 设置处理管道
        processor = RealTimeDataProcessor()
        
        # 3. 处理数据
        async for data in mock_stream:
            result = await processor.process_tick('TEST', data)
            
            # 4. 验证处理结果
            assert self._validate_tick_processing(result)
```

### 11. 监控和诊断

#### 11.1 性能监控
```python
import psutil
import time
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class PerformanceMetrics:
    cpu_usage: float
    memory_usage: float
    disk_io: Dict[str, float]
    network_io: Dict[str, float]
    
class PerformanceMonitor:
    def __init__(self, interval: float = 1.0):
        self.interval = interval
        self._metrics_history: List[PerformanceMetrics] = []
        
    async def start_monitoring(self):
        """开始监控系统性能"""
        while True:
            metrics = self._collect_metrics()
            self._metrics_history.append(metrics)
            await asyncio.sleep(self.interval)
            
    def _collect_metrics(self) -> PerformanceMetrics:
        """收集性能指标"""
        return PerformanceMetrics(
            cpu_usage=psutil.cpu_percent(),
            memory_usage=psutil.virtual_memory().percent,
            disk_io=self._get_disk_io(),
            network_io=self._get_network_io()
        )
        
    def generate_report(self) -> Dict:
        """生成性能报告"""
        return {
            'cpu_usage_avg': np.mean([m.cpu_usage for m in self._metrics_history]),
            'memory_usage_avg': np.mean([m.memory_usage for m in self._metrics_history]),
            'peak_cpu_usage': max([m.cpu_usage for m in self._metrics_history]),
            'peak_memory_usage': max([m.memory_usage for m in self._metrics_history])
        }
```

#### 11.2 错误追踪
```python
import traceback
import logging
from datetime import datetime
from typing import Dict, List, Optional

class ErrorTracker:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._error_history: List[Dict] = []
        
    def track_error(self, error: Exception, context: Dict = None):
        """记录错误信息"""
        error_info = {
            'timestamp': datetime.now().isoformat(),
            'type': type(error).__name__,
            'message': str(error),
            'traceback': traceback.format_exc(),
            'context': context or {}
        }
        
        self._error_history.append(error_info)
        self.logger.error(f"Error occurred: {error_info}")
        
    def get_error_summary(self) -> Dict[str, int]:
        """获取错误统计信息"""
        error_counts = {}
        for error in self._error_history:
            error_type = error['type']
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
        return error_counts
