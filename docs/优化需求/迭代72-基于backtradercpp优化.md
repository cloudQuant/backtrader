### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/backtradercpp
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### backtradercpp项目简介
backtradercpp是backtrader的C++实现版本，具有以下核心特点：
- **C++实现**: 高性能的C++实现
- **类似API**: 与backtrader类似的API设计
- **编译优化**: 编译时优化，运行速度快
- **内存管理**: 高效的内存管理
- **多线程**: 支持多线程回测
- **跨平台**: 跨平台支持

### 重点借鉴方向
1. **性能优化**: C++性能优化技术
2. **内存布局**: 数据内存布局优化
3. **模板编程**: C++模板元编程
4. **多线程**: 多线程并行回测
5. **数据结构**: 高效数据结构设计
6. **API设计**: C++ API设计模式

---

## 一、项目对比分析

### 1.1 架构设计对比

| 特性 | Backtrader (Python) | BacktraderCpp (C++) |
|------|---------------------|---------------------|
| **核心架构** | LineBuffer + Cerebro引擎 | Eigen数组 + FeedAggregator |
| **数据存储** | LineBuffer循环缓冲 | boost::circular_buffer + Eigen::Array |
| **向量计算** | numpy数组 | Eigen::Array (向量化) |
| **类型系统** | 动态类型 | 静态类型 + concepts约束 |
| **内存管理** | Python GC + 数组缓冲 | 手动管理 + 智能指针 |
| **并发模型** | multiprocessing | OpenMP (数据读取) |

### 1.2 BacktraderCpp的核心优势

#### 1.2.1 Eigen数组系统

BacktraderCpp使用Eigen进行高效数组运算：

```cpp
using VecArrXd = Eigen::Array<double, Eigen::Dynamic, 1>;
using RowArrayXd = Eigen::Array<double, Eigen::Dynamic, Eigen::Dynamic, Eigen::RowMajor>;
using VecArrXi = Eigen::Array<int, Eigen::Dynamic, 1>;
```

**优势**：
- 编译时优化，SIMD指令自动向量化
- 零开销抽象，表达式模板避免临时对象
- 内存布局紧凑，缓存友好

#### 1.2.2 循环缓冲区设计

```cpp
template <typename T> class FeedDataBuffer {
    int window_ = 1;
    boost::circular_buffer<T> data_;  // 固定容量循环缓冲
};
```

**优势**：
- 固定内存占用，避免动态分配
- 自动覆盖旧数据，无需手动管理
- 索引访问O(1)时间复杂度

#### 1.2.3 状态机模式

```cpp
enum State { Valid, Invalid, Finished };
std::vector<State> status_;  // 每个数据源独立状态
```

**优势**：
- 清晰的状态转换
- 支持多数据源异步对齐
- 易于扩展新状态

#### 1.2.4 并行数据读取

```cpp
#pragma omp parallel for
for (int i = 0; i < assets_; ++i) {
    std::getline(raw_files[i], raw_line_buffer[i]);
    std::getline(adj_files[i], adj_line_buffer[i]);
}
```

**优势**：
- 多资产数据并行加载
- 充分利用多核CPU
- 减少I/O等待时间

#### 1.2.5 价格评估器模式

```cpp
struct GenericPriceEvaluator {
    virtual double price(const PriceEvaluatorInput& input) = 0;
};

struct EvalOpen : GenericPriceEvaluator {
    int tag = 0;  // 0:exact, 1: open+v, 2:open*v
    double v = 0;
};
```

**优势**：
- 灵活的价格计算策略
- 支持开盘价调整（涨跌停限制）
- 策略模式易于扩展

#### 1.2.6 策略状态持久化

```cpp
class StrategyDumpUtil {
    void save();  // Boost序列化
    void load();
    void set_timed_var(const ptime& t, const std::string& key, double v);
};
```

**优势**：
- 支持策略状态保存/恢复
- 时间序列变量存储
- 二进制序列化高效

#### 1.2.7 参数优化器

```cpp
class TableRunner {
    // 笛卡尔积参数组合
    static std::vector<std::vector<std::pair<std::string, double>>>
    GenerateCartesianProduct(...);
};
```

**优势**：
- 自动生成参数组合
- 状态栈管理（push_state/pop_state）
- 避免重复初始化

### 1.3 Python可借鉴的设计

虽然Python没有C++的性能特性，但可以借鉴其设计思想：

1. **循环缓冲区**: `collections.deque` + 固定长度
2. **状态机**: 显式状态枚举
3. **评估器模式**: 函数式价格计算
4. **状态持久化**: pickle/shelve序列化
5. **笛卡尔积**: itertools.product
6. **并行I/O**: concurrent.futures ThreadPoolExecutor

---

## 二、需求文档

### 2.1 优化目标

借鉴BacktraderCpp的设计优势，对Backtrader进行以下优化：

1. **数据缓冲优化**: 引入更高效的循环缓冲机制
2. **并行数据加载**: 多数据源并行读取
3. **价格评估器**: 灵活的价格计算框架
4. **状态持久化**: 策略状态保存与恢复
5. **参数优化改进**: 更高效的参数组合生成
6. **内存优化**: 减少不必要的数据复制

### 2.2 详细需求

#### 需求1: 高效循环缓冲区

**描述**: 实现基于deque的固定容量循环缓冲

**功能点**:
- 使用`collections.deque`设置maxlen
- 负索引访问（-1表示最新）
- 自动覆盖旧数据
- O(1)时间复杂度的push/pop

**验收标准**:
- 提供CyclicBuffer类
- 支持类似list的索引访问
- 性能测试优于当前LineBuffer

#### 需求2: 并行数据加载器

**描述**: 多CSV文件并行加载

**功能点**:
- 使用ThreadPoolExecutor并行读取
- 自动检测CPU核心数
- 支持进度回调
- 异常隔离（单个文件失败不影响其他）

**验收标准**:
- 加载1000个文件速度提升50%+
- 提供ParallelCSVLoader类
- 与现有CSV接口兼容

#### 需求3: 价格评估器框架

**描述**: 灵活的价格计算策略

**功能点**:
- 基础评估器: Open/Close/High/Low
- 调整评估器: Open + offset, Open * factor
- 涨跌停评估器: 自动限制在涨跌停价格
- 自定义评估器: 用户传入函数

**验收标准**:
- 提供PriceEvaluator基类
- 至少5种内置评估器
- 支持lambda函数自定义

#### 需求4: 策略状态管理器

**描述**: 保存和恢复策略状态

**功能点**:
- 变量快照: 当前时刻所有变量值
- 时间序列变量: 按时间存储的变量历史
- 持久化: 保存到文件（pickle/json）
- 断点续跑: 从保存点继续回测

**验收标准**:
- 提供StateManager类
- 支持变量注册和自动保存
- 性能开销<5%

#### 需求5: 改进的参数优化

**描述**: 更高效的参数组合生成和执行

**功能点**:
- 笛卡尔积自动生成
- 懒加载: 按需创建Cerebro实例
- 结果缓存: 避免重复计算
- 并行执行: 多进程参数搜索

**验收标准**:
- 提供ParamOptimizer类
- 支持itertools.product风格参数网格
- 并行效率提升与核心数成正比

#### 需求6: 零拷贝数据访问

**描述**: 减少数据在内存中的复制

**功能点**:
- 视图访问: 返回数据视图而非副本
- 共享底层数据: 多个指标共享同一数据源
- 延迟计算: 仅在需要时计算

**验收标准**:
- 内存使用减少20%+
- 与现有API完全兼容
- 性能测试通过

---

## 三、设计文档

### 3.1 循环缓冲区设计

#### 3.1.1 CyclicBuffer类

```python
from collections import deque
from typing import TypeVar, Generic, Iterable, Optional
import numpy as np

T = TypeVar('T')

class CyclicBuffer(Generic[T]):
    """固定容量的循环缓冲区

    特点:
    - 使用deque实现O(1)的append/pop
    - 支持负索引访问（-1是最新的）
    - 自动覆盖旧数据
    """

    def __init__(self, capacity: int, dtype: Optional[type] = None):
        """初始化缓冲区

        Args:
            capacity: 缓冲区容量
            dtype: 数据类型（用于numpy数组优化）
        """
        self._capacity = capacity
        self._dtype = dtype
        self._buffer: deque = deque(maxlen=capacity)
        self._array_cache: Optional[np.ndarray] = None
        self._cache_valid = False

    def append(self, value: T) -> None:
        """添加新值"""
        self._buffer.append(value)
        self._cache_valid = False

    def extend(self, values: Iterable[T]) -> None:
        """批量添加"""
        self._buffer.extend(values)
        self._cache_valid = False

    def __getitem__(self, index: int) -> T:
        """支持正负索引

        -1: 最新值
        0: 最早的值
        """
        if index < 0:
            # 负索引: -1是最新的
            index = len(self._buffer) + index
        return self._buffer[index]

    def __len__(self) -> int:
        return len(self._buffer)

    @property
    def full(self) -> bool:
        """缓冲区是否已满"""
        return len(self._buffer) == self._capacity

    @property
    def capacity(self) -> int:
        return self._capacity

    def to_array(self) -> np.ndarray:
        """转换为numpy数组（缓存优化）"""
        if not self._cache_valid or self._array_cache is None:
            if self._dtype:
                self._array_cache = np.array(self._buffer, dtype=self._dtype)
            else:
                self._array_cache = np.array(self._buffer)
            self._cache_valid = True
        return self._array_cache

    def clear(self) -> None:
        """清空缓冲区"""
        self._buffer.clear()
        self._cache_valid = False

    def __repr__(self) -> str:
        return f"CyclicBuffer(size={len(self)}/{self._capacity}, data={list(self._buffer)})"
```

#### 3.1.2 集成到LineSeries

```python
class LineSeries:
    """支持循环缓冲的LineSeries"""

    def __init__(self, capacity: Optional[int] = None):
        self._use_cyclic = capacity is not None
        if self._use_cyclic:
            self._buffer = CyclicBuffer(capacity, dtype=float)
        else:
            self._buffer = []  # 原有实现

    def forward(self, value: float) -> None:
        """推进数据"""
        if self._use_cyclic:
            self._buffer.append(value)
        else:
            self._buffer.append(value)

    def __getitem__(self, index: int) -> float:
        return self._buffer[index]

    def __len__(self) -> int:
        return len(self._buffer)
```

### 3.2 并行数据加载器设计

#### 3.2.1 ParallelCSVLoader类

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Callable, Optional
import pandas as pd

class ParallelCSVLoader:
    """并行加载多个CSV文件"""

    def __init__(self, max_workers: Optional[int] = None):
        """初始化加载器

        Args:
            max_workers: 最大线程数，默认为CPU核心数
        """
        self._max_workers = max_workers or os.cpu_count()

    def load_directory(
        self,
        directory: Path,
        pattern: str = "*.csv",
        read_args: Optional[Dict] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """并行加载目录下的所有CSV文件

        Args:
            directory: 目录路径
            pattern: 文件匹配模式
            read_args: 传递给pandas.read_csv的参数
            progress_callback: 进度回调(completed, total)

        Returns:
            文件名到DataFrame的映射
        """
        files = list(directory.glob(pattern))
        read_args = read_args or {}
        results = {}

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            # 提交所有任务
            future_to_file = {
                executor.submit(self._load_single, f, read_args): f
                for f in files
            }

            # 收集结果
            completed = 0
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    df = future.result()
                    results[file_path.stem] = df
                except Exception as e:
                    print(f"Error loading {file_path}: {e}")

                completed += 1
                if progress_callback:
                    progress_callback(completed, len(files))

        return results

    def _load_single(self, file_path: Path, read_args: Dict) -> pd.DataFrame:
        """加载单个文件"""
        return pd.read_csv(file_path, **read_args)

    def load_multiple(
        self,
        file_paths: List[Path],
        read_args: Optional[Dict] = None,
    ) -> List[pd.DataFrame]:
        """并行加载多个指定文件"""
        read_args = read_args or {}
        results = [None] * len(file_paths)

        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_index = {
                executor.submit(self._load_single, f, read_args): i
                for i, f in enumerate(file_paths)
            }

            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                except Exception as e:
                    print(f"Error loading file {index}: {e}")
                    results[index] = pd.DataFrame()

        return results
```

#### 3.2.2 集成到CSV Data Feed

```python
class CSVDirectoryDataFeed(bt.FeedBase):
    """使用并行加载的目录数据源"""

    params = (
        ('directory', None),
        ('pattern', '*.csv'),
        ('parallel', True),
        ('max_workers', None),
    )

    def __init__(self):
        super().__init__()

        if self.p.parallel:
            loader = ParallelCSVLoader(self.p.max_workers)
            self._data_frames = loader.load_directory(
                Path(self.p.directory),
                self.p.pattern,
            )
        else:
            # 原有的顺序加载逻辑
            self._data_frames = self._load_sequential()
```

### 3.3 价格评估器框架设计

#### 3.3.1 评估器基类

```python
from typing import Protocol
from dataclasses import dataclass

@dataclass
class PriceInput:
    """价格输入数据"""
    open: float
    high: float
    low: float
    close: float

class PriceEvaluator(Protocol):
    """价格评估器协议"""

    def evaluate(self, input: PriceInput) -> float:
        """根据输入计算目标价格"""
        ...

class PriceEvaluator:
    """价格评估器基类"""

    def evaluate(self, input: PriceInput) -> float:
        raise NotImplementedError

    def __or__(self, other: 'PriceEvaluator') -> 'ChainedEvaluator':
        """串联评估器"""
        return ChainedEvaluator([self, other])

    def __add__(self, offset: float) -> 'OffsetEvaluator':
        """加偏移量"""
        return OffsetEvaluator(self, offset)

    def __mul__(self, factor: float) -> 'ScaleEvaluator':
        """缩放因子"""
        return ScaleEvaluator(self, factor)
```

#### 3.3.2 内置评估器

```python
class OpenEvaluator(PriceEvaluator):
    """开盘价评估器"""

    def evaluate(self, input: PriceInput) -> float:
        return input.open

class CloseEvaluator(PriceEvaluator):
    """收盘价评估器"""

    def evaluate(self, input: PriceInput) -> float:
        return input.close

class MidEvaluator(PriceEvaluator):
    """中间价评估器"""

    def evaluate(self, input: PriceInput) -> float:
        return (input.open + input.close) / 2

class OffsetEvaluator(PriceEvaluator):
    """偏移评估器: base + offset"""

    def __init__(self, base: PriceEvaluator, offset: float):
        self._base = base
        self._offset = offset

    def evaluate(self, input: PriceInput) -> float:
        return self._base.evaluate(input) + self._offset

class ScaleEvaluator(PriceEvaluator):
    """缩放评估器: base * factor"""

    def __init__(self, base: PriceEvaluator, factor: float):
        self._base = base
        self._factor = factor

    def evaluate(self, input: PriceInput) -> float:
        return self._base.evaluate(input) * self._factor

class LimitEvaluator(PriceEvaluator):
    """涨跌停限制评估器"""

    def __init__(
        self,
        base: PriceEvaluator,
        limit_up: float = 1.10,  # 涨停10%
        limit_down: float = 0.90,  # 跌停10%
        reference: PriceEvaluator = None,
    ):
        self._base = base
        self._limit_up = limit_up
        self._limit_down = limit_down
        self._reference = reference or CloseEvaluator()

    def evaluate(self, input: PriceInput) -> float:
        price = self._base.evaluate(input)
        ref_price = self._reference.evaluate(input)

        # 限制在涨跌停范围内
        return max(
            min(price, ref_price * self._limit_up),
            ref_price * self._limit_down
        )

# 便捷函数
def open_price() -> PriceEvaluator:
    return OpenEvaluator()

def close_price() -> PriceEvaluator:
    return CloseEvaluator()

def mid_price() -> PriceEvaluator:
    return MidEvaluator()

def with_offset(evaluator: PriceEvaluator, offset: float) -> PriceEvaluator:
    return evaluator + offset

def with_scale(evaluator: PriceEvaluator, factor: float) -> PriceEvaluator:
    return evaluator * factor

def with_limit(
    evaluator: PriceEvaluator,
    limit_up: float = 1.10,
    limit_down: float = 0.90,
) -> PriceEvaluator:
    return LimitEvaluator(evaluator, limit_up, limit_down)
```

#### 3.3.3 在Strategy中使用

```python
class EnhancedStrategy(bt.Strategy):
    """使用价格评估器的策略"""

    params = (
        ('price_evaluator', open_price()),  # 可配置的价格评估器
    )

    def next(self):
        # 获取价格输入
        price_input = PriceInput(
            open=self.data.open[0],
            high=self.data.high[0],
            low=self.data.low[0],
            close=self.data.close[0],
        )

        # 使用评估器计算目标价格
        target_price = self.p.price_evaluator.evaluate(price_input)

        # 下单
        if self.should_buy():
            self.buy(price=target_price)

# 使用示例
cerebro.addstrategy(
    EnhancedStrategy,
    price_evaluator=open_price() + 0.01  # 开盘价 + 0.01
)

cerebro.addstrategy(
    EnhancedStrategy,
    price_evaluator=with_limit(open_price(), 1.095, 0.905)  # 限制涨跌停
)
```

### 3.4 策略状态管理器设计

#### 3.4.1 StateManager类

```python
import pickle
from typing import Any, Dict, Optional, Union
from pathlib import Path
import shelve
import json

class StateManager:
    """策略状态管理器

    功能:
    - 变量快照保存
    - 时间序列变量记录
    - 持久化存储
    - 断点续跑
    """

    def __init__(
        self,
        strategy: 'bt.Strategy',
        storage_path: Optional[Path] = None,
        auto_save: bool = False,
        save_interval: int = 100,
    ):
        """初始化状态管理器

        Args:
            strategy: 关联的策略实例
            storage_path: 存储路径
            auto_save: 是否自动保存
            save_interval: 自动保存间隔（bar数）
        """
        self._strategy = strategy
        self._storage_path = storage_path or Path('strategy_state.db')
        self._auto_save = auto_save
        self._save_interval = save_interval

        # 变量存储
        self._variables: Dict[str, Any] = {}
        self._timed_variables: Dict[Any, Dict[str, Any]] = {}  # time -> variables

        # 计数器
        self._bar_count = 0

    def register(self, name: str, value: Any = None) -> None:
        """注册变量

        Args:
            name: 变量名
            value: 初始值
        """
        self._variables[name] = value

    def set(self, name: str, value: Any) -> None:
        """设置变量值"""
        self._variables[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        """获取变量值"""
        return self._variables.get(name, default)

    def set_timed(self, time: Any, name: str, value: Any) -> None:
        """设置带时间戳的变量"""
        if time not in self._timed_variables:
            self._timed_variables[time] = {}
        self._timed_variables[time][name] = value

    def get_timed(self, time: Any, name: str, default: Any = None) -> Any:
        """获取指定时间的变量值"""
        return self._timed_variables.get(time, {}).get(name, default)

    def snapshot(self) -> Dict[str, Any]:
        """创建当前状态快照"""
        return {
            'variables': self._variables.copy(),
            'timed_variables': dict(self._timed_variables),
            'bar_count': self._bar_count,
        }

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """从快照恢复状态"""
        self._variables = snapshot['variables'].copy()
        self._timed_variables = {
            k: v.copy() for k, v in snapshot['timed_variables'].items()
        }
        self._bar_count = snapshot['bar_count']

    def save(self, path: Optional[Path] = None) -> None:
        """保存到文件"""
        path = path or self._storage_path

        if path.suffix == '.json':
            self._save_json(path)
        elif path.suffix == '.pkl':
            self._save_pickle(path)
        else:
            self._save_shelve(path)

    def _save_pickle(self, path: Path) -> None:
        """使用pickle保存"""
        with open(path, 'wb') as f:
            pickle.dump(self.snapshot(), f)

    def _save_json(self, path: Path) -> None:
        """使用JSON保存（仅支持可序列化类型）"""
        with open(path, 'w') as f:
            json.dump(self.snapshot(), f, default=str)

    def _save_shelve(self, path: Path) -> None:
        """使用shelve保存（支持增量更新）"""
        with shelve.open(str(path.with_suffix(''))) as db:
            db['variables'] = self._variables
            db['timed_variables'] = self._timed_variables
            db['bar_count'] = self._bar_count

    def load(self, path: Optional[Path] = None) -> None:
        """从文件加载"""
        path = path or self._storage_path

        if path.suffix == '.json':
            self._load_json(path)
        elif path.suffix == '.pkl':
            self._load_pickle(path)
        else:
            self._load_shelve(path)

    def _load_pickle(self, path: Path) -> None:
        """使用pickle加载"""
        with open(path, 'rb') as f:
            snapshot = pickle.load(f)
        self.restore(snapshot)

    def _load_json(self, path: Path) -> None:
        """使用JSON加载"""
        with open(path, 'r') as f:
            snapshot = json.load(f)
        self.restore(snapshot)

    def _load_shelve(self, path: Path) -> None:
        """使用shelve加载"""
        with shelve.open(str(path.with_suffix(''))) as db:
            self._variables = db.get('variables', {})
            self._timed_variables = db.get('timed_variables', {})
            self._bar_count = db.get('bar_count', 0)

    def on_bar(self) -> None:
        """在每个bar调用"""
        self._bar_count += 1
        if self._auto_save and self._bar_count % self._save_interval == 0:
            self.save()

    def reset(self) -> None:
        """重置状态"""
        self._variables.clear()
        self._timed_variables.clear()
        self._bar_count = 0
```

#### 3.4.2 集成到Strategy

```python
class StatefulStrategy(bt.Strategy):
    """支持状态管理的策略基类"""

    def __init__(self):
        super().__init__()
        self.state = StateManager(self)

    def next(self):
        # 自动调用状态管理器
        self.state.on_bar()

        # 策略逻辑
        self.run_strategy()

    def run_strategy(self):
        raise NotImplementedError

# 使用示例
class MyStrategy(StatefulStrategy):
    params = (
        ('state_file', 'my_strategy_state.pkl'),
        ('auto_save', True),
    )

    def __init__(self):
        super().__init__()
        self.state.register('my_var', 0)
        self.state.register('total_trades', 0)

        # 尝试加载之前的状态
        try:
            self.state.load(self.p.state_file)
            print(f"Restored state: bar_count={self.state._bar_count}")
        except FileNotFoundError:
            print("Starting fresh")

    def run_strategy(self):
        # 设置变量
        current_value = self.calculate_signal()
        self.state.set('my_var', current_value)

        # 设置带时间戳的变量
        self.state.set_timed(
            self.datetime.datetime(0),
            'signal',
            current_value
        )

        # 使用变量
        if self.state.get('my_var', 0) > 0:
            self.buy()

        # 自动保存由on_bar处理
```

### 3.5 参数优化器设计

#### 3.5.1 ParamOptimizer类

```python
import itertools
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, Optional
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, as_completed

@dataclass
class ParamResult:
    """参数优化结果"""
    params: Dict[str, Any]
    metrics: Dict[str, float]
    error: Optional[str] = None

@dataclass
class OptimizationResult:
    """优化总结果"""
    results: List[ParamResult] = field(default_factory=list)
    best_params: Optional[Dict[str, Any]] = None
    best_metric: Optional[float] = None
    metric_name: str = 'sharpe'

    def get_best(self) -> Optional[ParamResult]:
        """获取最佳结果"""
        if not self.results:
            return None
        valid_results = [r for r in self.results if r.error is None]
        if not valid_results:
            return None
        return max(valid_results, key=lambda r: r.metrics.get(self.metric_name, -float('inf')))

class ParamOptimizer:
    """参数优化器

    功能:
    - 笛卡尔积参数网格
    - 并行执行
    - 结果缓存
    - 进度跟踪
    """

    def __init__(
        self,
        cerebro_factory: Callable[[], 'bt.Cerebro'],
        param_space: Dict[str, List[Any]],
        metric: str = 'sharpe',
        maximize: bool = True,
        max_workers: Optional[int] = None,
        cache: bool = True,
    ):
        """初始化优化器

        Args:
            cerebro_factory: Cerebro工厂函数
            param_space: 参数空间 {参数名: [值列表]}
            metric: 优化指标名称
            maximize: 是否最大化指标
            max_workers: 最大工作进程数
            cache: 是否缓存结果
        """
        self._cerebro_factory = cerebro_factory
        self._param_space = param_space
        self._metric = metric
        self._maximize = maximize
        self._max_workers = max_workers or mp.cpu_count()
        self._cache = cache
        self._result_cache: Dict[Tuple, ParamResult] = {}

    def generate_param_combinations(self) -> List[Dict[str, Any]]:
        """生成所有参数组合（笛卡尔积）"""
        param_names = list(self._param_space.keys())
        param_values = [self._param_space[name] for name in param_names]

        combinations = []
        for values in itertools.product(*param_values):
            param_dict = dict(zip(param_names, values))
            combinations.append(param_dict)

        return combinations

    def run_single(self, params: Dict[str, Any]) -> ParamResult:
        """运行单个参数组合"""
        # 检查缓存
        cache_key = tuple(sorted(params.items()))
        if self._cache and cache_key in self._result_cache:
            return self._result_cache[cache_key]

        try:
            # 创建Cerebro实例
            cerebro = self._cerebro_factory()

            # 设置参数
            cerebro.optstrategy(**params)

            # 运行
            results = cerebro.run()

            # 提取指标
            if results and len(results) > 0:
                strat = results[0]
                metrics = self._extract_metrics(strat)
            else:
                metrics = {}

            result = ParamResult(params=params, metrics=metrics)

            # 缓存结果
            if self._cache:
                self._result_cache[cache_key] = result

            return result

        except Exception as e:
            return ParamResult(params=params, metrics={}, error=str(e))

    def _extract_metrics(self, strategy) -> Dict[str, float]:
        """从策略中提取指标"""
        metrics = {}

        # 常用分析器
        if hasattr(strategy, 'analyzers'):
            for analyzer in strategy.analyzers:
                if hasattr(analyzer, 'get_analysis'):
                    analysis = analyzer.get_analysis()
                    if isinstance(analysis, dict):
                        metrics.update(analysis)

        return metrics

    def run(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> OptimizationResult:
        """运行所有参数组合

        Args:
            progress_callback: 进度回调(completed, total)
        """
        combinations = self.generate_param_combinations()
        results = []

        # 并行执行
        with ProcessPoolExecutor(max_workers=self._max_workers) as executor:
            future_to_params = {
                executor.submit(self.run_single, combo): combo
                for combo in combinations
            }

            completed = 0
            for future in as_completed(future_to_params):
                result = future.result()
                results.append(result)

                completed += 1
                if progress_callback:
                    progress_callback(completed, len(combinations))

        opt_result = OptimizationResult(
            results=results,
            metric_name=self._metric,
        )

        # 设置最佳结果
        best = opt_result.get_best()
        if best:
            opt_result.best_params = best.params
            opt_result.best_metric = best.metrics.get(self._metric)

        return opt_result

    def run_sequential(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> OptimizationResult:
        """顺序执行（用于调试）"""
        combinations = self.generate_param_combinations()
        results = []

        for i, combo in enumerate(combinations):
            result = self.run_single(combo)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, len(combinations))

        opt_result = OptimizationResult(
            results=results,
            metric_name=self._metric,
        )

        best = opt_result.get_best()
        if best:
            opt_result.best_params = best.params
            opt_result.best_metric = best.metrics.get(self._metric)

        return opt_result
```

#### 3.5.2 使用示例

```python
# 定义Cerebro工厂
def create_cerebro():
    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    return cerebro

# 定义参数空间
param_space = {
    'period': [5, 10, 20, 30],
    'devfactor': [1.5, 2.0, 2.5],
}

# 创建优化器
optimizer = ParamOptimizer(
    cerebro_factory=create_cerebro,
    param_space=param_space,
    metric='sharpe',
    maximize=True,
    max_workers=4,
)

# 运行优化
def progress_callback(completed, total):
    print(f"Progress: {completed}/{total} ({completed/total*100:.1f}%)")

result = optimizer.run(progress_callback=progress_callback)

# 打印结果
print(f"Best params: {result.best_params}")
print(f"Best Sharpe: {result.best_metric:.4f}")

# 查看所有结果
for r in result.results:
    if r.error is None:
        print(f"{r.params}: sharpe={r.metrics.get('sharpe', 'N/A')}")
```

### 3.6 零拷贝数据访问设计

#### 3.6.1 数据视图类

```python
import numpy as np
from typing import Sequence, Union

class DataView:
    """数据视图，避免复制

    提供对底层数组的只读访问，不创建副本
    """

    def __init__(self, array: np.ndarray):
        """创建数据视图

        Args:
            array: 底层数组
        """
        self._array = array
        self._view = array.view()  # 创建视图而非副本

    def __getitem__(self, key: Union[int, slice, Sequence]) -> np.ndarray:
        """获取数据视图"""
        result = self._view[key]
        # 确保返回的也是视图
        if isinstance(result, np.ndarray):
            return result.view()
        return result

    def __array__(self) -> np.ndarray:
        """支持numpy转换（返回视图）"""
        return self._view

    @property
    def shape(self) -> tuple:
        return self._view.shape

    @property
    def dtype(self) -> np.dtype:
        return self._view.dtype

    @property
    def size(self) -> int:
        return self._view.size

    def __len__(self) -> int:
        return len(self._view)

    def __repr__(self) -> str:
        return f"DataView(shape={self.shape}, dtype={self.dtype})"

class LineBuffer:
    """优化的Line缓冲区"""

    def __init__(self, size: int, minperiod: int = 1):
        self._size = size
        self._minperiod = minperiod
        self._array = np.zeros(size, dtype=float)
        self._idx = 0
        self._len = 0

    def forward(self, value: float) -> None:
        """推进数据"""
        self._array[self._idx] = value
        self._idx = (self._idx + 1) % self._size
        if self._len < self._size:
            self._len += 1

    def get_view(self, length: Optional[int] = None) -> DataView:
        """获取数据视图（零拷贝）

        Args:
            length: 返回最近N个数据，None表示全部

        Returns:
            数据视图对象
        """
        if length is None:
            length = self._len

        # 构造正确顺序的视图
        if self._len < self._size:
            # 未填满，直接切片
            array_view = self._array[:self._len]
        else:
            # 已填满，需要从idx开始（循环缓冲）
            array_view = np.concatenate([
                self._array[self._idx:],
                self._array[:self._idx]
            ])

        if length < len(array_view):
            array_view = array_view[-length:]

        return DataView(array_view)

    def __getitem__(self, key: int) -> float:
        """索引访问

        0: 最旧的值
        -1: 最新的值
        """
        if key < 0:
            # 负索引
            key = self._len + key
        if key < 0 or key >= self._len:
            raise IndexError(f"Index {key} out of range [0, {self._len})")

        actual_idx = (self._idx - self._len + key) % self._size
        return self._array[actual_idx]
```

### 3.7 实现优先级

| 优先级 | 功能 | 复杂度 | 收益 |
|--------|------|--------|------|
| P0 | 循环缓冲区(CyclicBuffer) | 低 | 高 |
| P0 | 参数优化器改进 | 中 | 高 |
| P1 | 并行数据加载 | 中 | 中 |
| P1 | 价格评估器框架 | 低 | 中 |
| P2 | 策略状态管理器 | 高 | 中 |
| P2 | 零拷贝数据访问 | 高 | 低 |

### 3.8 兼容性保证

所有新功能通过以下方式保证兼容性：
1. 新增类不修改现有API
2. 通过可选参数启用新功能
3. 默认行为保持不变
4. 提供渐进式迁移路径

---

## 四、实施计划

### 阶段一：循环缓冲区（3天）
1. 实现CyclicBuffer类
2. 性能测试对比
3. 文档编写

### 阶段二：参数优化器（1周）
1. 实现ParamOptimizer类
2. 并行执行支持
3. 缓存机制
4. 测试用例

### 阶段三：并行数据加载（5天）
1. 实现ParallelCSVLoader
2. 集成到现有DataFeed
3. 性能测试

### 阶段四：价格评估器（3天）
1. 实现评估器框架
2. 内置评估器
3. 策略集成

### 阶段五：状态管理器（1周）
1. 实现StateManager
2. 序列化支持
3. 断点续跑功能

### 阶段六：零拷贝优化（5天）
1. 实现DataView类
2. LineBuffer重构
3. 内存测试

---

## 五、总结

通过借鉴BacktraderCpp的以下优秀设计，Backtrader可以获得显著的性能提升：

1. **Eigen风格的数组操作**: 使用numpy的view机制减少内存复制
2. **循环缓冲区**: 固定内存占用，O(1)访问
3. **状态机模式**: 清晰的数据流控制
4. **并行I/O**: 多核数据加载
5. **评估器模式**: 灵活的价格计算
6. **状态持久化**: 支持断点续跑
7. **高效参数优化**: 笛卡尔积 + 并行执行

这些改进将使Backtrader在保持Python易用性的同时，获得接近C++实现的性能表现。
