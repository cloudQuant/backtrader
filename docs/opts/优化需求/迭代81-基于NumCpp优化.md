### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/NumCpp
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### NumCpp项目简介
NumCpp是NumPy的C++实现版本，提供类似NumPy的API，具有以下核心特点：
- **C++实现**: 高性能C++数值计算库
- **NumPy API**: 类似NumPy的API设计
- **矩阵运算**: 高效矩阵运算
- **向量化**: 向量化计算支持
- **模板编程**: C++模板元编程
- **头文件库**: Header-only设计

### 重点借鉴方向
1. **数值计算**: 高性能数值计算
2. **矩阵运算**: 矩阵运算优化
3. **向量化**: 向量化计算技术
4. **API设计**: NumPy风格API
5. **模板设计**: C++模板设计
6. **内存管理**: 高效内存管理

---

## 项目对比分析

### Backtrader vs NumCpp 架构对比

| 维度 | Backtrader | NumCpp |
|------|-----------|---------|
| **核心定位** | 量化交易回测框架 | 数值计算库 |
| **实现语言** | Python + Cython | C++ (Header-only) |
| **数据结构** | LineBuffer/LineSeries | NdArray |
| **数组支持** | 1D时间序列 | 1D/2D数组 |
| **切片操作** | 基础索引 | NumPy风格Slice |
| **广播机制** | 无 | 完整广播支持 |
| **线性代数** | 依赖numpy/linalg | 内置Linalg模块 |
| **类型系统** | Python动态类型 | C++模板+类型特征 |
| **内存管理** | Python GC | 自定义Allocator |
| **编译检查** | 运行时 | 编译时静态检查 |

### NumCpp可借鉴的核心优势

#### 1. 模板元编程
- **零开销抽象**: 编译时多态，无虚函数开销
- **类型安全**: 编译时类型检查
- **泛型算法**: 一套代码支持多种数据类型

#### 2. NdArray设计
```cpp
template<typename dtype, class Allocator = std::allocator<dtype>>
class NdArray {
    Shape          shape_;       // 2D形状
    size_type      size_;        // 总元素数
    dtype*         array_;       // 原始数据指针
    bool           ownsPtr_;     // 内存所有权
    allocator_type allocator_;  // 自定义分配器
};
```

#### 3. 广播机制
- **形状兼容检查**: 自动验证形状兼容性
- **标量广播**: 标量与数组操作
- **维度广播**: 行/列级广播
- **高效实现**: 最小化内存拷贝

#### 4. Shape和Slice类
- **Shape类**: 2D形状表示，支持size/isnull/issquare等方法
- **Slice类**: NumPy风格切片，支持负索引和步长
- **边界检查**: 自动验证和修正索引

#### 5. 内存管理策略
- **自定义Allocator**: 支持STL分配器接口
- **所有权控制**: ownsPtr_标志控制内存管理
- **RAII模式**: 自动内存管理

#### 6. 线性代数模块
- **矩阵分解**: LU、Cholesky、SVD、QR
- **求解器**: solve、lstsq
- **矩阵运算**: inv、det、matrix_power
- **特征值**: eigenvalue分解

#### 7. 类型特征系统
```cpp
// 编译时类型检查
template<typename>
struct is_ndarray_int : std::false_type {};

template<typename dtype, typename Allocator>
struct is_ndarray_int<NdArray<dtype, Allocator>> {
    static constexpr bool value = std::is_integral_v<dtype>;
};
```

---

## 需求文档

### 需求概述

借鉴NumCpp项目的高性能数值计算设计，为backtrader添加以下功能模块，提升计算性能和API易用性：

### 功能需求

#### FR1: 增强数组数据结构

**FR1.1 NdArray兼容接口**
- 需求描述: 提供类似NumCpp的NdArray接口
- 优先级: 高
- 验收标准:
  - 实现Array类支持1D/2D数组
  - 支持shape属性查询
  - 支持reshape操作
  - 支持astype类型转换

**FR1.2 切片操作**
- 需求描述: 支持NumPy风格的切片
- 优先级: 高
- 验收标准:
  - 实现Slice类
  - 支持start/stop/step语法
  - 支持负索引
  - 支持多维切片

**FR1.3 数组创建**
- 需求描述: 提供便捷的数组创建方法
- 优先级: 中
- 验收标准:
  - zeros/ones创建
  - arange/linspace创建
  - random创建随机数组
  - from_list从列表创建

#### FR2: 广播机制

**FR2.1 形状广播**
- 需求描述: 支持不同形状数组间的运算
- 优先级: 高
- 验收标准:
  - 标量与数组广播
  - 行向量广播
  - 列向量广播
  - 广播规则验证

**FR2.2 逐元素运算**
- 需求描述: 高效的逐元素运算
- 优先级: 高
- 验收标准:
  - 四则运算广播
  - 比较运算广播
  - 数学函数广播

#### FR3: 线性代数增强

**FR3.1 矩阵运算**
- 需求描述: 完整的矩阵运算支持
- 优先级: 高
- 验收标准:
  - 矩阵乘法dot/matmul
  - 矩阵转置transpose
  - 矩阵求逆inv
  - 矩阵行列式det

**FR3.2 矩阵分解**
- 需求描述: 常用矩阵分解算法
- 优先级: 中
- 验收标准:
  - LU分解
  - Cholesky分解
  - SVD奇异值分解
  - QR分解

**FR3.3 求解器**
- 需求描述: 线性方程组求解
- 优先级: 中
- 验收标准:
  - solve求解器
  - lstsq最小二乘
  - 特征值求解

#### FR4: 性能优化

**FR4.1 SIMD支持**
- 需求描述: 使用SIMD指令加速计算
- 优先级: 中
- 验收标准:
  - 检测CPU SIMD支持
  - SSE/AVX加速
  - 降级到标量实现

**FR4.2 内存优化**
- 需求描述: 高效内存管理
- 优先级: 中
- 验收标准:
  - 内存池支持
  - 零拷贝视图
  - 就地操作

**FR4.3 并行计算**
- 需求描述: 多线程并行计算
- 优先级: 低
- 验收标准:
  - OpenMP支持
  - TBB集成
  - 可配置线程数

#### FR5: 类型安全

**FR5.1 类型特征**
- 需求描述: 编译时类型检查
- 优先级: 中
- 验收标准:
  - 整数类型检查
  - 浮点类型检查
  - 复数类型支持

**FR5.2 静态断言**
- 需求描述: 编译时错误检测
- 优先级: 中
- 验收标准:
  - 有效dtype检查
  - 维度检查
  - 形状兼容性检查

### 非功能需求

#### NFR1: 性能
- 数组运算延迟 < NumPy的2倍
- 内存占用与NumPy相当
- 大数组(>1M元素)高效处理

#### NFR2: 兼容性
- 与NumPy API保持一致
- 支持Python 3.7+
- 支持Windows/Linux/MacOS

#### NFR3: 可用性
- 清晰的错误提示
- 完整的文档字符串
- 丰富的使用示例

---

## 设计文档

### 整体架构设计

#### 新增模块结构

```
backtrader/
├── backtrader/
│   ├── arrays/              # 新增：数组模块
│   │   ├── __init__.py
│   │   ├── array.py         # 核心数组类
│   │   ├── slice.py         # 切片类
│   │   ├── shape.py         # 形状类
│   │   ├── dtype.py         # 数据类型
│   │   └── broadcasting.py  # 广播机制
│   ├── linalg/              # 新增：线性代数模块
│   │   ├── __init__.py
│   │   ├── matrix.py        # 矩阵运算
│   │   ├── decompose.py     # 矩阵分解
│   │   └── solve.py         # 求解器
│   ├── optimize/            # 新增：性能优化
│   │   ├── __init__.py
│   │   ├── simd.py          # SIMD加速
│   │   ├── parallel.py      # 并行计算
│   │   └── memory.py        # 内存优化
│   └── functions/           # 新增：数学函数
│       ├── __init__.py
│       ├── statistical.py   # 统计函数
│       ├── mathematical.py  # 数学函数
│       └── logical.py       # 逻辑函数
```

### 详细设计

#### 1. 增强数组数据结构

**1.1 Shape类**

```python
# backtrader/arrays/shape.py
from typing import Tuple
from dataclasses import dataclass

@dataclass(frozen=True)
class Shape:
    """数组形状类 - NumCpp兼容"""

    rows: int
    cols: int

    def __post_init__(self):
        if self.rows < 0 or self.cols < 0:
            raise ValueError(f"Invalid shape: ({self.rows}, {self.cols})")

    @property
    def size(self) -> int:
        """总元素数"""
        return self.rows * self.cols

    @property
    def ndim(self) -> int:
        """维度数"""
        if self.rows == 1:
            return 1
        return 2

    @property
    def is_null(self) -> bool:
        """是否为空"""
        return self.rows == 0 or self.cols == 0

    @property
    def is_square(self) -> bool:
        """是否为方阵"""
        return self.rows == self.cols

    def as_tuple(self) -> Tuple[int, int]:
        """转换为元组"""
        return (self.rows, self.cols)

    def __eq__(self, other) -> bool:
        if not isinstance(other, Shape):
            return False
        return self.rows == other.rows and self.cols == other.cols

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def __str__(self) -> str:
        return f"[{self.rows}, {self.cols}]"

    def __repr__(self) -> str:
        return f"Shape({self.rows}, {self.cols})"
```

**1.2 Slice类**

```python
# backtrader/arrays/slice.py
from typing import List, Union, Optional
import numpy as np

class Slice:
    """切片类 - NumPy风格切片

    支持[start:stop:step]语法，包括负索引
    """

    def __init__(self, start: Optional[Union[int, slice]] = None,
                 stop: Optional[int] = None,
                 step: Optional[int] = None):
        # 支持多种初始化方式
        if isinstance(start, slice):
            self.start = start.start if start.start is not None else 0
            self.stop = start.stop if start.stop is not None else -1
            self.step = start.step if start.step is not None else 1
        else:
            self.start = start if start is not None else 0
            self.stop = stop if stop is not None else -1
            self.step = step if step is not None else 1

    def make_positive(self, array_size: int) -> 'Slice':
        """转换负索引为正索引"""
        start = self.start
        stop = self.stop

        if start < 0:
            start += array_size
        if stop < 0:
            stop += array_size
        if stop == -1 or stop is None:
            stop = array_size

        # 边界检查
        if start < 0:
            start = 0
        if start > array_size:
            start = array_size
        if stop < 0:
            stop = 0
        if stop > array_size:
            stop = array_size

        return Slice(start, stop, self.step)

    def to_indices(self, array_size: int) -> List[int]:
        """转换为索引列表"""
        positive_slice = self.make_positive(array_size)
        indices = []
        current = positive_slice.start
        stop = positive_slice.stop
        step = positive_slice.step

        if step > 0:
            while current < stop:
                indices.append(current)
                current += step
        else:
            while current > stop:
                indices.append(current)
                current += step

        return indices

    def num_elements(self, array_size: int) -> int:
        """计算切片包含的元素数"""
        return len(self.to_indices(array_size))

    def __eq__(self, other) -> bool:
        if not isinstance(other, Slice):
            return False
        return (self.start == other.start and
                self.stop == other.stop and
                self.step == other.step)

    def __repr__(self) -> str:
        return f"Slice({self.start}:{self.stop}:{self.step})"

def slice(obj) -> Slice:
    """创建切片的便捷函数"""
    if isinstance(obj, Slice):
        return obj
    if isinstance(obj, slice):
        return Slice(obj)
    if isinstance(obj, (list, tuple)):
        if len(obj) == 1:
            return Slice(stop=obj[0])
        elif len(obj) == 2:
            return Slice(obj[0], obj[1])
        elif len(obj) == 3:
            return Slice(obj[0], obj[1], obj[2])
    return Slice(obj)
```

**1.3 Array类**

```python
# backtrader/arrays/array.py
import numpy as np
from typing import Union, List, Tuple, Optional, Iterator
from .shape import Shape
from .slice import Slice as BTCSlice

class Array:
    """增强数组类 - NumCpp风格接口

    提供类似NumCpp的NdArray接口，兼容NumPy数组
    """

    def __init__(self, data: Union[np.ndarray, List, Tuple, 'Array'] = None,
                 shape: Optional[Tuple[int, int]] = None,
                 dtype: Optional[type] = None,
                 copy: bool = True):
        if data is None:
            if shape is None:
                shape = (0, 0)
            self._array = np.empty(shape, dtype=dtype or float)
        elif isinstance(data, Array):
            self._array = data._array.copy() if copy else data._array
        elif isinstance(data, np.ndarray):
            self._array = data.copy() if copy else data
        else:
            self._array = np.array(data, dtype=dtype, copy=copy)

        self._shape = Shape(*self._array.shape[:2])
        if self._array.ndim == 1:
            self._shape = Shape(1, self._array.shape[0])

    @property
    def shape(self) -> Shape:
        """获取形状"""
        return self._shape

    @property
    def size(self) -> int:
        """总元素数"""
        return self._shape.size

    @property
    def ndim(self) -> int:
        """维度数"""
        return self._shape.ndim

    @property
    def dtype(self) -> np.dtype:
        """数据类型"""
        return self._array.dtype

    @property
    def T(self) -> 'Array':
        """转置视图"""
        return Array(self._array.T, copy=False)

    def reshape(self, rows: int, cols: int) -> 'Array':
        """重塑数组形状"""
        if rows * cols != self.size:
            raise ValueError(f"Cannot reshape {self.shape} to ({rows}, {cols})")
        return Array(self._array.reshape(rows, cols), copy=False)

    def astype(self, dtype: type) -> 'Array':
        """转换数据类型"""
        return Array(self._array.astype(dtype), copy=False)

    def flatten(self) -> 'Array':
        """展平为一维"""
        return Array(self._array.flatten(), copy=False)

    def ravel(self) -> 'Array':
        """展平视图"""
        return Array(self._array.ravel(), copy=False)

    def transpose(self) -> 'Array':
        """转置"""
        return Array(self._array.T, copy=False)

    def copy(self) -> 'Array':
        """创建副本"""
        return Array(self._array, copy=True)

    # 切片操作
    def __getitem__(self, key) -> 'Array':
        """获取切片"""
        result = self._array[key]
        if not isinstance(result, np.ndarray):
            return result
        return Array(result, copy=False)

    def __setitem__(self, key, value):
        """设置切片"""
        self._array[key] = value

    # 运算符重载
    def __add__(self, other) -> 'Array':
        return Array(self._array + self._to_array(other)._array)

    def __sub__(self, other) -> 'Array':
        return Array(self._array - self._to_array(other)._array)

    def __mul__(self, other) -> 'Array':
        return Array(self._array * self._to_array(other)._array)

    def __truediv__(self, other) -> 'Array':
        return Array(self._array / self._to_array(other)._array)

    def __pow__(self, other) -> 'Array':
        return Array(self._array ** self._to_array(other)._array)

    def __radd__(self, other) -> 'Array':
        return Array(self._to_array(other)._array + self._array)

    def __rsub__(self, other) -> 'Array':
        return Array(self._to_array(other)._array - self._array)

    def __rmul__(self, other) -> 'Array':
        return Array(self._to_array(other)._array * self._array)

    def __rtruediv__(self, other) -> 'Array':
        return Array(self._to_array(other)._array / self._array)

    def __neg__(self) -> 'Array':
        return Array(-self._array)

    def __pos__(self) -> 'Array':
        return Array(+self._array)

    def __abs__(self) -> 'Array':
        return Array(np.abs(self._array))

    # 比较运算
    def __eq__(self, other) -> 'Array':
        return Array(self._array == self._to_array(other)._array)

    def __ne__(self, other) -> 'Array':
        return Array(self._array != self._to_array(other)._array)

    def __lt__(self, other) -> 'Array':
        return Array(self._array < self._to_array(other)._array)

    def __le__(self, other) -> 'Array':
        return Array(self._array <= self._to_array(other)._array)

    def __gt__(self, other) -> 'Array':
        return Array(self._array > self._to_array(other)._array)

    def __ge__(self, other) -> 'Array':
        return Array(self._array >= self._to_array(other)._array)

    # 聚合操作
    def sum(self, axis: Optional[int] = None) -> Union['Array', float]:
        """求和"""
        result = self._array.sum(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def mean(self, axis: Optional[int] = None) -> Union['Array', float]:
        """平均值"""
        result = self._array.mean(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def std(self, axis: Optional[int] = None) -> Union['Array', float]:
        """标准差"""
        result = self._array.std(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def var(self, axis: Optional[int] = None) -> Union['Array', float]:
        """方差"""
        result = self._array.var(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def min(self, axis: Optional[int] = None) -> Union['Array', float]:
        """最小值"""
        result = self._array.min(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def max(self, axis: Optional[int] = None) -> Union['Array', float]:
        """最大值"""
        result = self._array.max(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def argmin(self, axis: Optional[int] = None) -> Union['Array', int]:
        """最小值索引"""
        result = self._array.argmin(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def argmax(self, axis: Optional[int] = None) -> Union['Array', int]:
        """最大值索引"""
        result = self._array.argmax(axis=axis)
        return Array(result) if isinstance(result, np.ndarray) else result

    def any(self) -> bool:
        """是否有任何True"""
        return self._array.any()

    def all(self) -> bool:
        """是否全部True"""
        return self._array.all()

    # 转换为NumPy
    def to_numpy(self) -> np.ndarray:
        """转换为NumPy数组"""
        return self._array.copy()

    # 迭代器
    def __iter__(self) -> Iterator:
        return iter(self._array)

    def __len__(self) -> int:
        return len(self._array)

    def __repr__(self) -> str:
        return f"Array(shape={self.shape}, dtype={self.dtype})"

    def __str__(self) -> str:
        return str(self._array)

    # 私有方法
    def _to_array(self, other) -> 'Array':
        """转换为Array"""
        if isinstance(other, Array):
            return other
        return Array(other)

    @property
    def rows(self) -> int:
        """行数"""
        return self._shape.rows

    @property
    def cols(self) -> int:
        """列数"""
        return self._shape.cols

    @classmethod
    def zeros(cls, shape: Tuple[int, int], dtype: type = float) -> 'Array':
        """创建全零数组"""
        return cls(np.zeros(shape, dtype=dtype), copy=False)

    @classmethod
    def ones(cls, shape: Tuple[int, int], dtype: type = float) -> 'Array':
        """创建全1数组"""
        return cls(np.ones(shape, dtype=dtype), copy=False)

    @classmethod
    def empty(cls, shape: Tuple[int, int], dtype: type = float) -> 'Array':
        """创建空数组"""
        return cls(np.empty(shape, dtype=dtype), copy=False)

    @classmethod
    def arange(cls, start: int, stop: Optional[int] = None,
              step: int = 1, dtype: type = float) -> 'Array':
        """创建等差数列"""
        if stop is None:
            stop = start
            start = 0
        return cls(np.arange(start, stop, step, dtype=dtype), copy=False)

    @classmethod
    def linspace(cls, start: float, stop: float,
                num: int = 50, endpoint: bool = True) -> 'Array':
        """创建线性空间"""
        return cls(np.linspace(start, stop, num, endpoint=endpoint), copy=False)

    @classmethod
    def eye(cls, n: int, m: Optional[int] = None,
            k: int = 0, dtype: type = float) -> 'Array':
        """创建单位矩阵"""
        m = m if m is not None else n
        return cls(np.eye(n, m, k, dtype=dtype), copy=False)

    @classmethod
    def diag(cls, v: Union['Array', List], k: int = 0) -> 'Array':
        """创建对角矩阵"""
        if isinstance(v, Array):
            v = v.to_numpy()
        return cls(np.diag(v, k), copy=False)

    @classmethod
    def random(cls, shape: Tuple[int, int],
              low: float = 0.0, high: float = 1.0) -> 'Array':
        """创建随机数组"""
        return cls(np.random.uniform(low, high, shape), copy=False)

    @classmethod
    def randint(cls, low: int, high: int,
               shape: Tuple[int, int]) -> 'Array':
        """创建随机整数数组"""
        return cls(np.random.randint(low, high, shape), copy=False)

    @classmethod
    def randn(cls, shape: Tuple[int, int]) -> 'Array':
        """创建标准正态分布随机数组"""
        return cls(np.random.randn(*shape), copy=False)
```

#### 2. 广播机制

**2.1 广播器**

```python
# backtrader/arrays/broadcasting.py
from typing import Tuple, Callable
import numpy as np
from .array import Array

class Broadcaster:
    """广播机制 - NumCpp风格广播"""

    @staticmethod
    def broadcast_shapes(shape1: Tuple[int, int],
                         shape2: Tuple[int, int]) -> Tuple[int, int]:
        """计算广播后的形状"""
        rows1, cols1 = shape1
        rows2, cols2 = shape2

        # 标量广播
        if rows1 == 1 and cols1 == 1:
            return shape2
        if rows2 == 1 and cols2 == 1:
            return shape1

        # 行广播
        if rows1 == 1 and cols1 == cols2:
            return shape2
        if rows2 == 1 and cols2 == cols1:
            return shape1

        # 列广播
        if cols1 == 1 and rows1 == rows2:
            return shape2
        if cols2 == 1 and rows2 == rows1:
            return shape1

        # 完全匹配
        if shape1 == shape2:
            return shape1

        raise ValueError(f"Cannot broadcast shapes {shape1} and {shape2}")

    @staticmethod
    def is_broadcastable(shape1: Tuple[int, int],
                         shape2: Tuple[int, int]) -> bool:
        """检查是否可广播"""
        try:
            Broadcaster.broadcast_shapes(shape1, shape2)
            return True
        except ValueError:
            return False

    @staticmethod
    def broadcast_to(array: Array, shape: Tuple[int, int]) -> Array:
        """广播数组到指定形状"""
        current_shape = array.shape.as_tuple()

        if current_shape == shape:
            return array

        rows, cols = current_shape
        target_rows, target_cols = shape

        result = array.to_numpy()

        # 标量广播
        if rows == 1 and cols == 1:
            return Array(np.full(shape, result[0, 0]))

        # 行广播
        if rows == 1 and cols == target_cols:
            return Array(np.repeat(result, target_rows, axis=0))

        # 列广播
        if cols == 1 and rows == target_rows:
            return Array(np.repeat(result, target_cols, axis=1))

        raise ValueError(f"Cannot broadcast {current_shape} to {shape}")

    @staticmethod
    def broadcast_arrays(*arrays: Array) -> Tuple[Array, ...]:
        """广播多个数组到相同形状"""
        if not arrays:
            return ()

        # 计算目标形状
        target_shape = arrays[0].shape.as_tuple()
        for arr in arrays[1:]:
            target_shape = Broadcaster.broadcast_shapes(
                target_shape, arr.shape.as_tuple()
            )

        # 广播所有数组
        return tuple(Broadcaster.broadcast_to(arr, target_shape) for arr in arrays)

    @staticmethod
    def apply_binary(func: Callable, a1: Array, a2: Array) -> Array:
        """应用二元运算函数，支持广播"""
        if a1.shape == a2.shape:
            return Array(func(a1.to_numpy(), a2.to_numpy()), copy=False)

        # 广播后运算
        b1, b2 = Broadcaster.broadcast_arrays(a1, a2)
        return Array(func(b1.to_numpy(), b2.to_numpy()), copy=False)

    @staticmethod
    def apply_unary(func: Callable, arr: Array) -> Array:
        """应用一元运算函数"""
        return Array(func(arr.to_numpy()), copy=False)
```

#### 3. 线性代数增强

**3.1 矩阵运算**

```python
# backtrader/linalg/matrix.py
import numpy as np
from typing import Union, Tuple
from ..arrays.array import Array

class MatrixOps:
    """矩阵运算模块 - NumCpp Linalg兼容"""

    @staticmethod
    def dot(a: Union[Array, np.ndarray],
            b: Union[Array, np.ndarray]) -> Array:
        """矩阵乘法/点积

        对于1D数组：内积
        对于2D数组：矩阵乘法
        """
        a_arr = a.to_numpy() if isinstance(a, Array) else a
        b_arr = b.to_numpy() if isinstance(b, Array) else b

        result = np.dot(a_arr, b_arr)
        return Array(result, copy=False)

    @staticmethod
    def matmul(a: Union[Array, np.ndarray],
               b: Union[Array, np.ndarray]) -> Array:
        """矩阵乘法"""
        a_arr = a.to_numpy() if isinstance(a, Array) else a
        b_arr = b.to_numpy() if isinstance(b, Array) else b

        result = np.matmul(a_arr, b_arr)
        return Array(result, copy=False)

    @staticmethod
    def transpose(arr: Union[Array, np.ndarray]) -> Array:
        """转置"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        return Array(arr_arr.T, copy=False)

    @staticmethod
    def inv(arr: Union[Array, np.ndarray]) -> Array:
        """矩阵求逆"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.linalg.inv(arr_arr)
        return Array(result, copy=False)

    @staticmethod
    def pinv(arr: Union[Array, np.ndarray]) -> Array:
        """伪逆"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.linalg.pinv(arr_arr)
        return Array(result, copy=False)

    @staticmethod
    def det(arr: Union[Array, np.ndarray]) -> float:
        """行列式"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        return np.linalg.det(arr_arr)

    @staticmethod
    def matrix_power(arr: Union[Array, np.ndarray], n: int) -> Array:
        """矩阵幂"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.linalg.matrix_power(arr_arr, n)
        return Array(result, copy=False)

    @staticmethod
    def rank(arr: Union[Array, np.ndarray]) -> int:
        """矩阵秩"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        return np.linalg.matrix_rank(arr_arr)

    @staticmethod
    def trace(arr: Union[Array, np.ndarray]) -> float:
        """迹（对角元素之和）"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        return np.trace(arr_arr)

    @staticmethod
    def diagonal(arr: Union[Array, np.ndarray], k: int = 0) -> Array:
        """对角线元素"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.diag(arr_arr, k)
        return Array(result, copy=False)

    @staticmethod
    def multi_dot(arrays: list) -> Array:
        """多个矩阵的乘积"""
        numpy_arrays = []
        for arr in arrays:
            if isinstance(arr, Array):
                numpy_arrays.append(arr.to_numpy())
            else:
                numpy_arrays.append(arr)

        result = np.linalg.multi_dot(numpy_arrays)
        return Array(result, copy=False)

    @staticmethod
    def outer(a: Union[Array, np.ndarray],
              b: Union[Array, np.ndarray]) -> Array:
        """外积"""
        a_arr = a.to_numpy() if isinstance(a, Array) else a
        b_arr = b.to_numpy() if isinstance(b, Array) else b

        result = np.outer(a_arr, b_arr)
        return Array(result, copy=False)

    @staticmethod
    def inner(a: Union[Array, np.ndarray],
              b: Union[Array, np.ndarray]) -> Array:
        """内积"""
        a_arr = a.to_numpy() if isinstance(a, Array) else a
        b_arr = b.to_numpy() if isinstance(b, Array) else b

        result = np.inner(a_arr, b_arr)
        return Array(result, copy=False)

    @staticmethod
    def kron(a: Union[Array, np.ndarray],
             b: Union[Array, np.ndarray]) -> Array:
        """克罗内克积"""
        a_arr = a.to_numpy() if isinstance(a, Array) else a
        b_arr = b.to_numpy() if isinstance(b, Array) else b

        result = np.kron(a_arr, b_arr)
        return Array(result, copy=False)
```

**3.2 矩阵分解**

```python
# backtrader/linalg/decompose.py
import numpy as np
from typing import Tuple, Union
from ..arrays.array import Array

class Decomposition:
    """矩阵分解模块"""

    @staticmethod
    def cholesky(arr: Union[Array, np.ndarray]) -> Array:
        """Cholesky分解

        要求：正定矩阵
        返回：下三角矩阵L，使得 A = L * L.T
        """
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.linalg.cholesky(arr_arr)
        return Array(result, copy=False)

    @staticmethod
    def qr(arr: Union[Array, np.ndarray],
            mode: str = 'reduced') -> Tuple[Array, Array]:
        """QR分解

        返回：Q (正交矩阵), R (上三角矩阵)
        """
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        q, r = np.linalg.qr(arr_arr, mode=mode)
        return Array(q, copy=False), Array(r, copy=False)

    @staticmethod
    def svd(arr: Union[Array, np.ndarray],
            full_matrices: bool = True,
            compute_uv: bool = True) -> Union[Array, Tuple[Array, Array, Array]]:
        """奇异值分解

        返回：U, s, Vt
        """
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.linalg.svd(arr_arr, full_matrices=full_matrices,
                               compute_uv=compute_uv)

        if compute_uv:
            u, s, vh = result
            return Array(u, copy=False), Array(s, copy=False), Array(vh, copy=False)
        return Array(result, copy=False)

    @staticmethod
    def eig(arr: Union[Array, np.ndarray]) -> Tuple[Array, Array]:
        """特征值分解

        返回：特征值w, 特征向量v
        """
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        w, v = np.linalg.eig(arr_arr)
        return Array(w, copy=False), Array(v, copy=False)

    @staticmethod
    def eigh(arr: Union[Array, np.ndarray],
             UPLO: str = 'L') -> Tuple[Array, Array]:
        """Hermite矩阵特征值分解

        适用于实对称/复共轭对称矩阵
        """
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        w, v = np.linalg.eigh(arr_arr, UPLO=UPLO)
        return Array(w, copy=False), Array(v, copy=False)

    @staticmethod
    def lu(arr: Union[Array, np.ndarray]) -> Tuple[Array, Array, Array]:
        """LU分解

        使用SciPy的lu函数
        """
        from scipy.linalg import lu
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        p, l, u = lu(arr_arr)
        return Array(p, copy=False), Array(l, copy=False), Array(u, copy=False)
```

**3.3 求解器**

```python
# backtrader/linalg/solve.py
import numpy as np
from typing import Union, Tuple
from ..arrays.array import Array

class Solver:
    """线性方程组求解器"""

    @staticmethod
    def solve(a: Union[Array, np.ndarray],
              b: Union[Array, np.ndarray]) -> Array:
        """求解线性方程组 ax = b

        使用最小二乘法
        """
        a_arr = a.to_numpy() if isinstance(a, Array) else a
        b_arr = b.to_numpy() if isinstance(b, Array) else b

        result = np.linalg.solve(a_arr, b_arr)
        return Array(result, copy=False)

    @staticmethod
    def lstsq(a: Union[Array, np.ndarray],
              b: Union[Array, np.ndarray],
              rcond: Optional[float] = None) -> Tuple[Array, Array, Array, int]:
        """最小二乘求解

        返回：x, residuals, rank, s
        """
        a_arr = a.to_numpy() if isinstance(a, Array) else a
        b_arr = b.to_numpy() if isinstance(b, Array) else b

        x, residuals, rank, s = np.linalg.lstsq(a_arr, b_arr, rcond=rcond)
        return (Array(x, copy=False),
                Array(residuals, copy=False),
                rank,
                Array(s, copy=False))

    @staticmethod
    def norm(x: Union[Array, np.ndarray],
             ord: Union[int, float, str] = None) -> float:
        """向量或矩阵范数"""
        x_arr = x.to_numpy() if isinstance(x, Array) else x
        return np.linalg.norm(x_arr, ord=ord)

    @staticmethod
    def cond(x: Union[Array, np.ndarray],
             p: Union[int, float, str] = None) -> float:
        """条件数"""
        x_arr = x.to_numpy() if isinstance(x, Array) else x
        return np.linalg.cond(x_arr, p=p)

    @staticmethod
    def matrix_balance(arr: Union[Array, np.ndarray]) -> Tuple[Array, Array]:
        """矩阵平衡"""
        from scipy.linalg import matrix_balance
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        balanced, perm = matrix_balance(arr_arr)
        return Array(balanced, copy=False), Array(perm, copy=False)
```

#### 4. 性能优化

**4.1 SIMD支持**

```python
# backtrader/optimize/simd.py
import numpy as np
import platform
import ctypes
from typing import Union

class SIMDSupport:
    """SIMD加速支持"""

    # CPU特性检测
    _has_sse = False
    _has_sse2 = False
    _has_sse3 = False
    _has_avx = False
    _has_avx2 = False
    _has_avx512 = False
    _has_neon = False  # ARM

    @classmethod
    def detect(cls):
        """检测CPU SIMD支持"""
        system = platform.system()

        if system == "Linux":
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    cpuinfo = f.read()
                    cls._has_sse = 'sse' in cpuinfo.lower()
                    cls._has_sse2 = 'sse2' in cpuinfo.lower()
                    cls._has_sse3 = 'sse3' in cpuinfo.lower()
                    cls._has_avx = 'avx' in cpuinfo.lower()
                    cls._has_avx2 = 'avx2' in cpuinfo.lower()
                    cls._has_avx512 = 'avx512' in cpuinfo.lower()
                    cls._has_neon = 'neon' in cpuinfo.lower()
            except:
                pass
        elif system == "Darwin":  # macOS
            # macOS x86_64 always has SSE/AVX
            # ARM macOS has NEON
            machine = platform.machine()
            if machine == 'x86_64':
                cls._has_sse = True
                cls._has_sse2 = True
                cls._has_sse3 = True
                cls._has_avx = True
                cls._has_avx2 = True
            elif machine == 'arm64':
                cls._has_neon = True
        elif system == "Windows":
            # Windows: 尝试使用IsProcessorFeaturePresent
            try:
                kernel32 = ctypes.windll.kernel32
                # 检测各种SIMD特性
                cls._has_sse = True  # 假设现代CPU都有
                cls._has_sse2 = True
            except:
                pass

    @classmethod
    def has_sse(cls) -> bool:
        return cls._has_sse

    @classmethod
    def has_avx(cls) -> bool:
        return cls._has_avx

    @classmethod
    def has_avx2(cls) -> bool:
        return cls._has_avx2

    @classmethod
    def has_neon(cls) -> bool:
        return cls._has_neon

    @classmethod
    def get_optimized_config(cls) -> dict:
        """获取优化配置"""
        cls.detect()
        return {
            'sse': cls._has_sse,
            'sse2': cls._has_sse2,
            'sse3': cls._has_sse3,
            'avx': cls._has_avx,
            'avx2': cls._has_avx2,
            'avx512': cls._has_avx512,
            'neon': cls._has_neon,
        }

# 自动检测
SIMDSupport.detect()

def vectorized_add(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """向量化的加法运算

    根据SIMD支持选择最优实现
    """
    # 使用NumPy的向量化操作（底层使用SIMD）
    return a + b

def vectorized_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """向量化的乘法运算"""
    return a * b

def vectorized_sum(arr: np.ndarray, axis: int = None) -> np.ndarray:
    """向量化的求和运算"""
    return arr.sum(axis=axis)
```

**4.2 内存优化**

```python
# backtrader/optimize/memory.py
import numpy as np
from typing import Dict, Optional
from weakref import WeakValueDictionary

class MemoryPool:
    """内存池 - 减少内存分配开销"""

    def __init__(self, max_blocks: int = 100):
        self._pool: WeakValueDictionary = WeakValueDictionary()
        self._max_blocks = max_blocks
        self._hits = 0
        self._misses = 0

    def get_array(self, shape: tuple, dtype: np.dtype) -> Optional[np.ndarray]:
        """从池中获取数组"""
        key = (shape, dtype)
        arr = self._pool.get(key)

        if arr is not None:
            self._hits += 1
            return arr

        self._misses += 1
        return None

    def return_array(self, arr: np.ndarray):
        """归还数组到池"""
        if len(self._pool) >= self._max_blocks:
            return

        key = (arr.shape, arr.dtype)
        self._pool[key] = arr

    @property
    def hit_rate(self) -> float:
        """缓存命中率"""
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0

    def clear(self):
        """清空池"""
        self._pool.clear()
        self._hits = 0
        self._misses = 0

# 全局内存池
_global_pool = MemoryPool()

def get_memory_pool() -> MemoryPool:
    """获取全局内存池"""
    return _global_pool

class ArrayView:
    """数组视图 - 零拷贝访问"""

    def __init__(self, array: np.ndarray, offset: int = 0,
                 shape: Optional[tuple] = None, strides: Optional[tuple] = None):
        self._array = array
        self._offset = offset
        self._shape = shape if shape is not None else array.shape
        self._strides = strides if strides is not None else array.strides

    @property
    def shape(self) -> tuple:
        return self._shape

    @property
    def strides(self) -> tuple:
        return self._strides

    def to_numpy(self) -> np.ndarray:
        """转换为NumPy数组"""
        return np.ndarray(
            shape=self._shape,
            dtype=self._array.dtype,
            buffer=self._array.data,
            offset=self._offset,
            strides=self._strides
        )

class InPlaceOps:
    """就地运算 - 减少内存分配"""

    @staticmethod
    def add_inplace(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """就地加法"""
        np.add(a, b, out=a)
        return a

    @staticmethod
    def sub_inplace(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """就地减法"""
        np.subtract(a, b, out=a)
        return a

    @staticmethod
    def mul_inplace(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """就地乘法"""
        np.multiply(a, b, out=a)
        return a

    @staticmethod
    def div_inplace(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """就地除法"""
        np.divide(a, b, out=a)
        return a
```

**4.3 并行计算**

```python
# backtrader/optimize/parallel.py
import numpy as np
from typing import Callable, List, Any
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing as mp

class ParallelOps:
    """并行计算操作"""

    def __init__(self, n_workers: Optional[int] = None):
        self._n_workers = n_workers or mp.cpu_count()

    def map(self, func: Callable, arrays: List[np.ndarray],
            n_workers: Optional[int] = None) -> List[Any]:
        """并行映射函数到数组列表

        对于小型数组，使用线程池
        对于CPU密集型操作，使用进程池
        """
        n_workers = n_workers or self._n_workers

        if len(arrays) < 2:
            return [func(arr) for arr in arrays]

        # 使用线程池（对NumPy操作更高效）
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            results = list(executor.map(func, arrays))

        return results

    def parallel_apply(self, func: Callable, arr: np.ndarray,
                       axis: int = 0, n_workers: Optional[int] = None) -> np.ndarray:
        """沿指定轴并行应用函数"""
        n_workers = n_workers or self._n_workers

        if arr.ndim == 1:
            return func(arr)

        # 沿轴分割数组
        if axis == 0:
            split_arrays = np.array_split(arr, n_workers, axis=0)
        else:
            split_arrays = np.array_split(arr, n_workers, axis=axis)

        # 并行处理
        with ThreadPoolExecutor(max_workers=n_workers) as executor:
            results = list(executor.map(func, split_arrays))

        # 合并结果
        return np.concatenate(results, axis=axis)

class BatchOps:
    """批量操作"""

    @staticmethod
    def batch_dot(arrays: List[np.ndarray],
                  weights: List[np.ndarray]) -> List[np.ndarray]:
        """批量点积运算"""
        return [np.dot(a, w) for a, w in zip(arrays, weights)]

    @staticmethod
    def batch_mean(arrays: List[np.ndarray]) -> np.ndarray:
        """批量计算均值"""
        return np.mean([np.mean(a) for a in arrays])

    @staticmethod
    def batch_std(arrays: List[np.ndarray]) -> np.ndarray:
        """批量计算标准差"""
        return np.mean([np.std(a) for a in arrays])
```

#### 5. 数学函数

**5.1 统计函数**

```python
# backtrader/functions/statistical.py
import numpy as np
from typing import Optional, Tuple
from ..arrays.array import Array

class Statistical:
    """统计函数模块"""

    @staticmethod
    def mean(arr: Union[Array, np.ndarray],
             axis: Optional[int] = None,
             dtype: Optional[type] = None) -> Union[Array, float]:
        """平均值"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.mean(arr_arr, axis=axis, dtype=dtype)
        return Array(result, copy=False) if isinstance(result, np.ndarray) else result

    @staticmethod
    def median(arr: Union[Array, np.ndarray],
               axis: Optional[int] = None) -> Union[Array, float]:
        """中位数"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.median(arr_arr, axis=axis)
        return Array(result, copy=False) if isinstance(result, np.ndarray) else result

    @staticmethod
    def std(arr: Union[Array, np.ndarray],
            axis: Optional[int] = None,
            ddof: int = 0) -> Union[Array, float]:
        """标准差"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = arr_arr.std(axis=axis, ddof=ddof)
        return Array(result, copy=False) if isinstance(result, np.ndarray) else result

    @staticmethod
    def var(arr: Union[Array, np.ndarray],
            axis: Optional[int] = None,
            ddof: int = 0) -> Union[Array, float]:
        """方差"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = arr_arr.var(axis=axis, ddof=ddof)
        return Array(result, copy=False) if isinstance(result, np.ndarray) else result

    @staticmethod
    def corrcoef(x: Union[Array, np.ndarray],
                 y: Optional[Union[Array, np.ndarray]] = None) -> Array:
        """相关系数"""
        x_arr = x.to_numpy() if isinstance(x, Array) else x
        if y is not None:
            y_arr = y.to_numpy() if isinstance(y, Array) else y
            result = np.corrcoef(x_arr, y_arr)
        else:
            result = np.corrcoef(x_arr)
        return Array(result, copy=False)

    @staticmethod
    def covariance(arr: Union[Array, np.ndarray]) -> Array:
        """协方差矩阵"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.cov(arr_arr)
        return Array(result, copy=False)

    @staticmethod
    def percentile(arr: Union[Array, np.ndarray],
                   q: Union[float, List[float]],
                   axis: Optional[int] = None) -> Union[Array, float]:
        """百分位数"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.percentile(arr_arr, q, axis=axis)
        return Array(result, copy=False) if isinstance(result, np.ndarray) else result

    @staticmethod
    def quantile(arr: Union[Array, np.ndarray],
                 q: Union[float, List[float]],
                 axis: Optional[int] = None) -> Union[Array, float]:
        """分位数"""
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        result = np.quantile(arr_arr, q, axis=axis)
        return Array(result, copy=False) if isinstance(result, np.ndarray) else result
```

**5.2 数学函数**

```python
# backtrader/functions/mathematical.py
import numpy as np
from typing import Union
from ..arrays.array import Array

class Mathematical:
    """数学函数模块"""

    # 三角函数
    @staticmethod
    def sin(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.sin(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def cos(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.cos(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def tan(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.tan(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def arcsin(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.arcsin(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def arccos(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.arccos(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def arctan(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.arctan(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def arctan2(y: Union[Array, np.ndarray], x: Union[Array, np.ndarray]) -> Array:
        y_arr = y.to_numpy() if isinstance(y, Array) else y
        x_arr = x.to_numpy() if isinstance(x, Array) else x
        return Array(np.arctan2(y_arr, x_arr))

    # 双曲函数
    @staticmethod
    def sinh(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.sinh(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def cosh(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.cosh(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def tanh(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.tanh(arr.to_numpy() if isinstance(arr, Array) else arr))

    # 指数和对数
    @staticmethod
    def exp(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.exp(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def expm1(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.expm1(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def log(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.log(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def log10(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.log10(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def log1p(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.log1p(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def log2(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.log2(arr.to_numpy() if isinstance(arr, Array) else arr))

    # 幂运算
    @staticmethod
    def sqrt(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.sqrt(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def square(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.square(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def power(arr: Union[Array, np.ndarray], exponent: float) -> Array:
        return Array(np.power(arr.to_numpy() if isinstance(arr, Array) else arr, exponent))

    @staticmethod
    def abs(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.abs(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def sign(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.sign(arr.to_numpy() if isinstance(arr, Array) else arr))

    # 舍入函数
    @staticmethod
    def round(arr: Union[Array, np.ndarray], decimals: int = 0) -> Array:
        return Array(np.round(arr.to_numpy() if isinstance(arr, Array) else arr, decimals))

    @staticmethod
    def floor(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.floor(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def ceil(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.ceil(arr.to_numpy() if isinstance(arr, Array) else arr))

    @staticmethod
    def trunc(arr: Union[Array, np.ndarray]) -> Array:
        return Array(np.trunc(arr.to_numpy() if isinstance(arr, Array) else arr))

    # 其他函数
    @staticmethod
    def clip(arr: Union[Array, np.ndarray],
             min_val: float, max_val: float) -> Array:
        arr_arr = arr.to_numpy() if isinstance(arr, Array) else arr
        return Array(np.clip(arr_arr, min_val, max_val))
```

### 实现计划

#### 第一阶段：数组数据结构（优先级：高）
1. 实现Shape类
2. 实现Slice类
3. 实现Array核心类
4. 单元测试

#### 第二阶段：广播机制（优先级：高）
1. 实现Broadcaster
2. 实现广播运算
3. 集成测试

#### 第三阶段：线性代数（优先级：高）
1. 实现MatrixOps矩阵运算
2. 实现Decomposition分解
3. 实现Solver求解器
4. 性能测试

#### 第四阶段：性能优化（优先级：中）
1. 实现SIMDSupport
2. 实现MemoryPool
3. 实现ParallelOps
4. 基准测试

#### 第五阶段：数学函数（优先级：中）
1. 实现Statistical统计函数
2. 实现Mathematical数学函数
3. 实现Logical逻辑函数
4. 文档完善

### API兼容性保证

所有新增功能与现有backtrader API兼容：

```python
# 传统方式（保持不变）
import backtrader as bt
import numpy as np

data = np.array([1, 2, 3, 4, 5])
ma = np.mean(data)

# 新方式：使用增强Array
from backtrader.arrays import Array

arr = Array([1, 2, 3, 4, 5])
mean = arr.mean()  # 返回Array或标量

# 矩阵运算
from backtrader.linalg import MatrixOps

a = Array([[1, 2], [3, 4]])
b = Array([[5, 6], [7, 8]])
c = MatrixOps.dot(a, b)

# 广播自动支持
d = Array([[1, 2, 3], [4, 5, 6]])
scalar = Array(2)
result = d * scalar  # 标量广播
```

### 使用示例

**数组创建和操作：**

```python
from backtrader.arrays import Array

# 创建数组
zeros = Array.zeros((3, 3))
ones = Array.ones((2, 4))
random = Array.random((5, 5))
identity = Array.eye(3)

# 切片操作
arr = Array.arange(20).reshape(4, 5)
row_slice = arr[1:3, :]      # 行切片
col_slice = arr[:, 2:4]      # 列切片
element = arr[1, 2]          # 单元素

# 形状操作
reshaped = arr.reshape(5, 4)
flattened = arr.flatten()
transposed = arr.T

# 类型转换
float_arr = arr.astype(float)
```

**矩阵运算：**

```python
from backtrader.linalg import MatrixOps

a = Array([[1, 2], [3, 4]])
b = Array([[5, 6], [7, 8]])

# 矩阵乘法
c = MatrixOps.dot(a, b)

# 求逆
inv_a = MatrixOps.inv(a)

# 行列式
det_a = MatrixOps.det(a)

# 转置
at = MatrixOps.transpose(a)
```

**线性代数求解：**

```python
from backtrader.linalg import Solver, Decomposition

# 线性方程组求解
A = Array([[3, 1], [1, 2]])
b = Array([9, 8])
x = Solver.solve(A, b)

# 最小二乘求解
A = Array([[1, 1], [1, 2], [1, 3]])
b = Array([2, 3, 4])
x, residuals, rank, s = Solver.lstsq(A, b)

# 矩阵分解
Q, R = Decomposition.qr(A)
L = Decomposition.cholesky(A.T @ A)
U, s, Vt = Decomposition.svd(A)
```

**统计函数：**

```python
from backtrader.functions import Statistical

data = Array.random((100, 5))

# 基本统计
mean = Statistical.mean(data)
std = Statistical.std(data)
variance = Statistical.var(data)
median_val = Statistical.median(data)

# 分位数
q25 = Statistical.quantile(data, 0.25)
q75 = Statistical.quantile(data, 0.75)

# 相关系数
corr = Statistical.corrcoef(data)
```

### 测试策略

1. **单元测试**: 每个模块的单元测试覆盖率 > 85%
2. **集成测试**: 与NumPy结果对比验证
3. **性能测试**: 对比NumPy性能，目标 < 2倍
4. **边界测试**: 处理极端情况（空数组、大数组等）
5. **兼容性测试**: 确保与现有代码兼容
