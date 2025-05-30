# Backtrader 去除元编程技术实施指南

## 🛠️ 技术架构设计

### 核心设计理念

1. **显式优于隐式** - 用明确的依赖关系替代隐式的元编程查找
2. **组合优于继承** - 用组合模式替代复杂的元类继承
3. **配置优于约定** - 用配置文件替代元编程的约定
4. **静态优于动态** - 用静态定义替代动态生成

### 新架构概览

```
原架构 (元编程驱动):
MetaBase → MetaParams → 各种元类 → 动态类生成

新架构 (组合驱动):
ComponentBase → ParameterizedBase → 配置驱动 → 静态类定义
```

## 📚 核心组件详细实现

### 1. 参数管理系统

#### 1.1 ParameterDescriptor 实现

```python
class ParameterDescriptor:
    """参数描述符 - 替代动态参数属性"""
    
    def __init__(self, name=None, default=None, type_=None, doc=None, validator=None):
        self.name = name
        self.default = default
        self.type_ = type_
        self.doc = doc
        self.validator = validator
        self._attr_name = None
    
    def __set_name__(self, owner, name):
        """Python 3.6+ 特性，自动设置属性名"""
        if self.name is None:
            self.name = name
        self._attr_name = f'_param_{name}'
    
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        
        # 从参数管理器获取值
        return obj._param_manager.get(self.name, self.default)
    
    def __set__(self, obj, value):
        # 类型检查
        if self.type_ is not None and not isinstance(value, self.type_):
            try:
                value = self.type_(value)
            except (ValueError, TypeError):
                raise TypeError(f"Parameter '{self.name}' expects {self.type_.__name__}, got {type(value).__name__}")
        
        # 值验证
        if self.validator is not None:
            if not self.validator(value):
                raise ValueError(f"Invalid value for parameter '{self.name}': {value}")
        
        # 设置值
        obj._param_manager.set(self.name, value)
    
    def __delete__(self, obj):
        """删除参数值，恢复默认值"""
        obj._param_manager.reset(self.name)

class ParameterMeta(type):
    """参数元类 - 仅用于收集参数定义"""
    
    def __new__(mcs, name, bases, namespace, **kwargs):
        # 收集参数描述符
        parameters = {}
        
        # 从基类收集参数
        for base in bases:
            if hasattr(base, '_parameters'):
                parameters.update(base._parameters)
        
        # 从当前类收集参数
        for key, value in list(namespace.items()):
            if isinstance(value, ParameterDescriptor):
                parameters[key] = value
                # 不删除，让描述符保持在类中
        
        # 存储参数定义
        namespace['_parameters'] = parameters
        
        return super().__new__(mcs, name, bases, namespace)

class ParameterManager:
    """参数管理器 - 替代AutoInfoClass"""
    
    def __init__(self, parameter_definitions, initial_values=None):
        self._definitions = parameter_definitions
        self._values = {}
        self._defaults = {name: desc.default for name, desc in parameter_definitions.items()}
        
        if initial_values:
            self.update(initial_values)
    
    def get(self, name, default=None):
        """获取参数值"""
        if name in self._values:
            return self._values[name]
        elif name in self._defaults:
            return self._defaults[name]
        else:
            return default
    
    def set(self, name, value):
        """设置参数值"""
        if name in self._definitions:
            # 通过描述符进行验证在__set__中完成
            self._values[name] = value
        else:
            raise AttributeError(f"Unknown parameter: {name}")
    
    def reset(self, name):
        """重置参数为默认值"""
        if name in self._values:
            del self._values[name]
    
    def update(self, values):
        """批量更新参数"""
        if isinstance(values, dict):
            for name, value in values.items():
                if name in self._definitions:
                    self.set(name, value)
        elif hasattr(values, '_values'):
            # 另一个ParameterManager
            self._values.update(values._values)
    
    def to_dict(self):
        """转换为字典"""
        result = self._defaults.copy()
        result.update(self._values)
        return result
    
    def keys(self):
        """获取所有参数名"""
        return set(self._defaults.keys()) | set(self._values.keys())
    
    def items(self):
        """获取所有参数项"""
        return self.to_dict().items()
    
    def __getitem__(self, name):
        return self.get(name)
    
    def __setitem__(self, name, value):
        self.set(name, value)
    
    def __contains__(self, name):
        return name in self._definitions

class ParameterizedBase(metaclass=ParameterMeta):
    """带参数的基类 - 替代ParamsBase"""
    
    def __init__(self, **kwargs):
        # 初始化参数管理器
        self._param_manager = ParameterManager(self._parameters)
        
        # 分离参数和其他关键字参数
        param_kwargs = {}
        other_kwargs = {}
        
        for key, value in kwargs.items():
            if key in self._parameters:
                param_kwargs[key] = value
            else:
                other_kwargs[key] = value
        
        # 设置参数
        self._param_manager.update(param_kwargs)
        
        # 创建兼容性属性
        self.params = ParameterAccessor(self._param_manager)
        self.p = self.params
        
        # 返回非参数的kwargs供子类使用
        return other_kwargs
    
    def get_param(self, name, default=None):
        """获取参数值"""
        return self._param_manager.get(name, default)
    
    def set_param(self, name, value):
        """设置参数值"""
        self._param_manager.set(name, value)

class ParameterAccessor:
    """参数访问器 - 提供兼容的params接口"""
    
    def __init__(self, param_manager):
        self._manager = param_manager
    
    def __getattr__(self, name):
        return self._manager.get(name)
    
    def __setattr__(self, name, value):
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            self._manager.set(name, value)
    
    def __getitem__(self, name):
        return self._manager.get(name)
    
    def __setitem__(self, name, value):
        self._manager.set(name, value)
```

#### 1.2 使用示例

```python
# 定义带参数的类
class MovingAverage(ParameterizedBase):
    """移动平均指标"""
    
    # 使用描述符定义参数
    period = ParameterDescriptor(
        default=14, 
        type_=int, 
        doc="移动平均周期",
        validator=lambda x: x > 0
    )
    
    method = ParameterDescriptor(
        default='simple',
        type_=str,
        doc="移动平均方法",
        validator=lambda x: x in ['simple', 'exponential', 'weighted']
    )
    
    def __init__(self, data, **kwargs):
        # 调用父类初始化，获取非参数kwargs
        other_kwargs = super().__init__(**kwargs)
        
        self.data = data
        
        # 处理其他参数
        for key, value in other_kwargs.items():
            setattr(self, key, value)
    
    def calculate(self):
        """计算移动平均"""
        period = self.period  # 通过描述符访问
        method = self.params.method  # 通过params访问
        
        if method == 'simple':
            return self._simple_ma(period)
        elif method == 'exponential':
            return self._exponential_ma(period)

# 使用
ma = MovingAverage(data, period=20, method='exponential')
print(ma.period)  # 20
print(ma.params.method)  # exponential
print(ma.p.period)  # 20 (兼容性访问)
```

### 2. Line系统重构

#### 2.1 LineBuffer 实现

```python
import collections
import numpy as np
from typing import Union, List, Optional, Any

class LineBuffer:
    """线条缓冲区 - 高效的数据存储"""
    
    def __init__(self, maxlen: Optional[int] = None, dtype=float):
        self.maxlen = maxlen
        self.dtype = dtype
        
        # 使用numpy数组提高性能
        if maxlen:
            self._buffer = np.full(maxlen, np.nan, dtype=dtype)
            self._index = 0
            self._length = 0
        else:
            self._buffer = []
        
        self._using_numpy = maxlen is not None
    
    def append(self, value: Any):
        """添加新值"""
        if self._using_numpy:
            self._buffer[self._index] = value
            self._index = (self._index + 1) % self.maxlen
            self._length = min(self._length + 1, self.maxlen)
        else:
            self._buffer.append(value)
    
    def __len__(self) -> int:
        """缓冲区长度"""
        return self._length if self._using_numpy else len(self._buffer)
    
    def __getitem__(self, index: Union[int, slice]) -> Any:
        """获取值 - 支持负索引（相对于当前位置）"""
        if self._using_numpy:
            if isinstance(index, int):
                if index >= 0:
                    # 正索引：从最新的值开始倒数
                    actual_index = (self._index - 1 - index) % self.maxlen
                    if index >= self._length:
                        raise IndexError("Index out of range")
                    return self._buffer[actual_index]
                else:
                    # 负索引：从最老的值开始
                    actual_index = (self._index + index) % self.maxlen
                    return self._buffer[actual_index]
            else:
                # 切片访问
                return [self[i] for i in range(*index.indices(len(self)))]
        else:
            if isinstance(index, int):
                if index >= 0:
                    return self._buffer[-(index + 1)]
                else:
                    return self._buffer[index]
            else:
                return self._buffer[index]
    
    def __setitem__(self, index: int, value: Any):
        """设置值"""
        if self._using_numpy:
            if index >= 0:
                actual_index = (self._index - 1 - index) % self.maxlen
                if index >= self._length:
                    raise IndexError("Index out of range")
                self._buffer[actual_index] = value
            else:
                actual_index = (self._index + index) % self.maxlen
                self._buffer[actual_index] = value
        else:
            if index >= 0:
                self._buffer[-(index + 1)] = value
            else:
                self._buffer[index] = value
    
    def get_array(self, count: Optional[int] = None) -> np.ndarray:
        """获取数组形式的数据"""
        if self._using_numpy:
            if count is None:
                count = self._length
            
            result = np.empty(count, dtype=self.dtype)
            for i in range(count):
                if i < self._length:
                    result[i] = self[count - 1 - i]
                else:
                    result[i] = np.nan
            
            return result
        else:
            arr = np.array(self._buffer[-count:] if count else self._buffer, dtype=self.dtype)
            return arr[::-1]  # 反转以匹配访问顺序

class LineDescriptor:
    """线条描述符 - 提供便捷的线条访问"""
    
    def __init__(self, name: str, index: int, alias: Optional[str] = None):
        self.name = name
        self.index = index
        self.alias = alias or name
    
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return obj._line_buffers[self.index]
    
    def __set__(self, obj, value):
        """直接设置整个线条缓冲区"""
        if isinstance(value, LineBuffer):
            obj._line_buffers[self.index] = value
        else:
            # 设置当前值
            obj._line_buffers[self.index][0] = value
    
    def __set_name__(self, owner, name):
        if self.name is None:
            self.name = name

class LineConfiguration:
    """线条配置 - 定义线条结构"""
    
    def __init__(self, *line_names: str, aliases: Optional[dict] = None, **line_configs):
        self.line_names = list(line_names)
        self.aliases = aliases or {}
        self.line_configs = line_configs
        
        # 添加配置中指定的线条
        for name, config in line_configs.items():
            if name not in self.line_names:
                self.line_names.append(name)
    
    def add_line(self, name: str, alias: Optional[str] = None):
        """添加新线条"""
        if name not in self.line_names:
            self.line_names.append(name)
        if alias:
            self.aliases[alias] = name
    
    def add_alias(self, alias: str, line_name: str):
        """添加别名"""
        if line_name in self.line_names:
            self.aliases[alias] = line_name
        else:
            raise ValueError(f"Line '{line_name}' not found")
    
    def get_line_index(self, name: str) -> int:
        """获取线条索引"""
        # 检查直接名称
        if name in self.line_names:
            return self.line_names.index(name)
        
        # 检查别名
        if name in self.aliases:
            real_name = self.aliases[name]
            return self.line_names.index(real_name)
        
        raise KeyError(f"Line '{name}' not found")
    
    def create_descriptors(self) -> dict:
        """创建线条描述符字典"""
        descriptors = {}
        
        # 为每个线条创建描述符
        for i, name in enumerate(self.line_names):
            descriptors[name] = LineDescriptor(name, i)
        
        # 为别名创建描述符
        for alias, line_name in self.aliases.items():
            index = self.line_names.index(line_name)
            descriptors[alias] = LineDescriptor(alias, index, line_name)
        
        return descriptors

class LineSeriesMeta(type):
    """线条序列元类 - 仅用于设置描述符"""
    
    def __new__(mcs, name, bases, namespace, **kwargs):
        # 处理线条配置
        line_config = namespace.get('_line_config')
        
        # 从基类继承线条配置
        for base in bases:
            if hasattr(base, '_line_config') and line_config is None:
                line_config = base._line_config
                break
        
        # 处理lines定义
        if 'lines' in namespace:
            lines_def = namespace.pop('lines')
            if isinstance(lines_def, (tuple, list)):
                line_config = LineConfiguration(*lines_def)
            elif isinstance(lines_def, dict):
                line_config = LineConfiguration(**lines_def)
            elif isinstance(lines_def, LineConfiguration):
                line_config = lines_def
        
        # 设置默认配置
        if line_config is None:
            line_config = LineConfiguration()
        
        namespace['_line_config'] = line_config
        
        # 创建类
        cls = super().__new__(mcs, name, bases, namespace)
        
        # 添加线条描述符
        descriptors = line_config.create_descriptors()
        for desc_name, descriptor in descriptors.items():
            setattr(cls, desc_name, descriptor)
        
        return cls

class LineSeriesBase(metaclass=LineSeriesMeta):
    """线条序列基类 - 替代动态生成的LineSeries"""
    
    def __init__(self, maxlen: Optional[int] = None):
        # 初始化线条缓冲区
        line_count = len(self._line_config.line_names)
        self._line_buffers = [
            LineBuffer(maxlen=maxlen) for _ in range(line_count)
        ]
        
        # 创建兼容性访问器
        self.lines = LineAccessor(self)
        
        # 当前位置
        self._current_index = -1
    
    def advance(self, size: int = 1):
        """前进指定步数"""
        self._current_index += size
    
    def add_data(self, **line_values):
        """添加一行数据"""
        for name, value in line_values.items():
            try:
                index = self._line_config.get_line_index(name)
                self._line_buffers[index].append(value)
            except KeyError:
                # 忽略未知的线条
                pass
        
        self.advance()
    
    def __len__(self) -> int:
        """数据长度"""
        if self._line_buffers:
            return len(self._line_buffers[0])
        return 0

class LineAccessor:
    """线条访问器 - 提供兼容的lines接口"""
    
    def __init__(self, parent: LineSeriesBase):
        self._parent = parent
    
    def __getitem__(self, key: Union[int, str]) -> LineBuffer:
        """通过索引或名称访问线条"""
        if isinstance(key, int):
            if 0 <= key < len(self._parent._line_buffers):
                return self._parent._line_buffers[key]
            else:
                raise IndexError(f"Line index {key} out of range")
        elif isinstance(key, str):
            try:
                index = self._parent._line_config.get_line_index(key)
                return self._parent._line_buffers[index]
            except KeyError:
                raise KeyError(f"Line '{key}' not found")
        else:
            raise TypeError(f"Line key must be int or str, got {type(key)}")
    
    def __getattr__(self, name: str) -> LineBuffer:
        """通过属性访问线条"""
        return self[name]
    
    def __len__(self) -> int:
        """线条数量"""
        return len(self._parent._line_buffers)
```

#### 2.2 具体实现示例

```python
# OHLCV数据线条
class OHLCVLines(LineSeriesBase):
    """OHLCV数据线条"""
    
    # 定义线条配置
    _line_config = LineConfiguration(
        'open', 'high', 'low', 'close', 'volume',
        aliases={
            'o': 'open',
            'h': 'high', 
            'l': 'low',
            'c': 'close',
            'v': 'volume'
        }
    )

# 指标线条
class IndicatorLines(LineSeriesBase):
    """单线条指标"""
    
    lines = ('indicator',)  # 使用简化定义

# 多线条指标
class MACDLines(LineSeriesBase):
    """MACD指标线条"""
    
    lines = {
        'macd': {},
        'signal': {},
        'histogram': {}
    }

# 使用示例
data = OHLCVLines(maxlen=1000)

# 添加数据
data.add_data(open=100.0, high=102.0, low=99.0, close=101.0, volume=1000)

# 访问数据
print(data.close[0])  # 最新收盘价: 101.0
print(data.lines.close[0])  # 同上
print(data.lines['close'][0])  # 同上
print(data.c[0])  # 使用别名: 101.0

# 获取数组
close_array = data.close.get_array(10)  # 最近10个收盘价
```

### 3. 依赖注入系统

#### 3.1 核心实现

```python
from typing import TypeVar, Type, Any, Optional, Callable, Dict
import threading
import contextvars

T = TypeVar('T')

class ServiceDescriptor:
    """服务描述符"""
    
    def __init__(self, service_type: Type[T], factory: Optional[Callable] = None, 
                 singleton: bool = False, lazy: bool = True):
        self.service_type = service_type
        self.factory = factory or service_type
        self.singleton = singleton
        self.lazy = lazy
        self._instance = None
        self._lock = threading.Lock()
    
    def get_instance(self, container: 'DependencyContainer') -> T:
        """获取服务实例"""
        if self.singleton:
            if self._instance is None:
                with self._lock:
                    if self._instance is None:
                        self._instance = self._create_instance(container)
            return self._instance
        else:
            return self._create_instance(container)
    
    def _create_instance(self, container: 'DependencyContainer') -> T:
        """创建服务实例"""
        if callable(self.factory):
            # 尝试依赖注入
            try:
                import inspect
                sig = inspect.signature(self.factory)
                kwargs = {}
                
                for param_name, param in sig.parameters.items():
                    if param.annotation != inspect.Parameter.empty:
                        try:
                            kwargs[param_name] = container.get(param.annotation)
                        except KeyError:
                            if param.default == inspect.Parameter.empty:
                                raise
                
                return self.factory(**kwargs)
            except Exception:
                # 回退到无参数创建
                return self.factory()
        else:
            return self.factory

class DependencyContainer:
    """依赖注入容器"""
    
    def __init__(self):
        self._services: Dict[Type, ServiceDescriptor] = {}
        self._instances: Dict[Type, Any] = {}
        self._lock = threading.Lock()
        
        # 上下文变量用于处理嵌套作用域
        self._context_stack: contextvars.ContextVar = contextvars.ContextVar(
            'dependency_context', default=[]
        )
    
    def register(self, service_type: Type[T], 
                 implementation: Optional[Type[T]] = None,
                 factory: Optional[Callable] = None,
                 singleton: bool = False,
                 lazy: bool = True) -> 'DependencyContainer':
        """注册服务"""
        
        if implementation is not None:
            factory = implementation
        elif factory is None:
            factory = service_type
        
        descriptor = ServiceDescriptor(
            service_type=service_type,
            factory=factory,
            singleton=singleton,
            lazy=lazy
        )
        
        with self._lock:
            self._services[service_type] = descriptor
        
        return self
    
    def register_instance(self, service_type: Type[T], instance: T) -> 'DependencyContainer':
        """注册实例"""
        with self._lock:
            self._instances[service_type] = instance
        return self
    
    def get(self, service_type: Type[T]) -> T:
        """获取服务"""
        # 检查上下文栈
        context_stack = self._context_stack.get()
        for context in reversed(context_stack):
            if service_type in context:
                return context[service_type]
        
        # 检查已注册的实例
        if service_type in self._instances:
            return self._instances[service_type]
        
        # 检查已注册的服务
        if service_type in self._services:
            descriptor = self._services[service_type]
            return descriptor.get_instance(self)
        
        # 尝试自动创建
        try:
            return service_type()
        except Exception:
            raise KeyError(f"Service {service_type} not found and cannot be auto-created")
    
    def push_context(self, **services):
        """推入上下文"""
        context_stack = self._context_stack.get()
        new_stack = context_stack + [services]
        self._context_stack.set(new_stack)
    
    def pop_context(self):
        """弹出上下文"""
        context_stack = self._context_stack.get()
        if context_stack:
            new_stack = context_stack[:-1]
            self._context_stack.set(new_stack)
            return context_stack[-1]
        return {}
    
    def with_context(self, **services):
        """创建上下文管理器"""
        return ContextManager(self, services)

class ContextManager:
    """上下文管理器"""
    
    def __init__(self, container: DependencyContainer, services: dict):
        self.container = container
        self.services = services
    
    def __enter__(self):
        self.container.push_context(**self.services)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.container.pop_context()

# 全局容器
_global_container = DependencyContainer()

def get_container() -> DependencyContainer:
    """获取全局依赖容器"""
    return _global_container

def inject(service_type: Type[T]) -> T:
    """依赖注入装饰器"""
    return get_container().get(service_type)

class Injected:
    """依赖注入描述符"""
    
    def __init__(self, service_type: Type[T]):
        self.service_type = service_type
        self._attr_name = None
    
    def __set_name__(self, owner, name):
        self._attr_name = f'_injected_{name}'
    
    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        
        # 懒加载
        if not hasattr(obj, self._attr_name):
            service = get_container().get(self.service_type)
            setattr(obj, self._attr_name, service)
        
        return getattr(obj, self._attr_name)
```

#### 3.2 使用示例

```python
# 定义服务接口
class IBroker:
    def buy(self, symbol, quantity):
        pass
    
    def sell(self, symbol, quantity):
        pass

class IDataFeed:
    def get_data(self, symbol):
        pass

# 实现服务
class MockBroker(IBroker):
    def __init__(self, commission: float = 0.001):
        self.commission = commission
    
    def buy(self, symbol, quantity):
        print(f"Buying {quantity} of {symbol}")

class YahooBroker(IBroker):
    def __init__(self, api_key: str):
        self.api_key = api_key

class MockDataFeed(IDataFeed):
    def get_data(self, symbol):
        return f"Mock data for {symbol}"

# 配置依赖注入
container = get_container()
container.register(IBroker, MockBroker, singleton=True)
container.register(IDataFeed, MockDataFeed, singleton=True)

# 使用依赖注入
class Strategy(ParameterizedBase):
    """策略基类"""
    
    # 使用描述符注入依赖
    broker = Injected(IBroker)
    data_feed = Injected(IDataFeed)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def buy_signal(self, symbol):
        """买入信号"""
        data = self.data_feed.get_data(symbol)
        self.broker.buy(symbol, 100)

# 使用上下文管理器临时替换服务
with container.with_context(broker=YahooBroker("api_key_123")):
    strategy = Strategy()
    strategy.buy_signal("AAPL")  # 使用YahooBroker
```

## 🔄 迁移路径

### 阶段性迁移策略

#### 第一阶段：兼容层
```python
# 创建兼容层，保持原有API可用
class CompatibilityLayer:
    """兼容层 - 桥接新旧API"""
    
    @staticmethod
    def create_strategy_with_meta(strategy_class, *args, **kwargs):
        """使用新系统创建策略，但保持元类接口"""
        # 将元类创建转换为新的创建方式
        return strategy_class(*args, **kwargs)
    
    @staticmethod
    def emulate_findowner(owned, cls):
        """模拟findowner功能"""
        # 通过依赖注入容器查找
        try:
            return get_container().get(cls)
        except KeyError:
            return None
```

#### 第二阶段：渐进替换
```python
# 提供旧API的包装器
def deprecated_metaclass(original_metaclass):
    """弃用的元类包装器"""
    def wrapper(*args, **kwargs):
        import warnings
        warnings.warn(
            f"Metaclass {original_metaclass.__name__} is deprecated. "
            f"Please use the new ParameterizedBase system.",
            DeprecationWarning,
            stacklevel=2
        )
        # 转换为新的实现
        return create_with_new_system(*args, **kwargs)
    
    return wrapper
```

## 📊 性能优化

### 关键优化点

1. **LineBuffer优化**
   - 使用numpy数组提高访问速度
   - 实现循环缓冲区减少内存分配
   - 提供批量操作接口

2. **参数访问优化**
   - 使用描述符缓存参数值
   - 避免重复的类型检查
   - 实现写时复制(Copy-on-Write)

3. **依赖注入优化**
   - 实现单例模式减少对象创建
   - 使用弱引用避免循环依赖
   - 提供延迟加载机制

### 性能基准测试

```python
import time
import numpy as np

class PerformanceBenchmark:
    """性能基准测试"""
    
    def benchmark_line_access(self, iterations=1000000):
        """线条访问性能测试"""
        data = OHLCVLines(maxlen=1000)
        
        # 填充测试数据
        for i in range(1000):
            data.add_data(
                open=100+i, high=102+i, 
                low=99+i, close=101+i, volume=1000
            )
        
        # 测试访问性能
        start_time = time.time()
        for _ in range(iterations):
            value = data.close[0]
        
        end_time = time.time()
        print(f"Line access: {iterations} iterations in {end_time - start_time:.4f}s")
    
    def benchmark_parameter_access(self, iterations=1000000):
        """参数访问性能测试"""
        class TestClass(ParameterizedBase):
            period = ParameterDescriptor(default=14, type_=int)
        
        obj = TestClass(period=20)
        
        start_time = time.time()
        for _ in range(iterations):
            value = obj.period
        
        end_time = time.time()
        print(f"Parameter access: {iterations} iterations in {end_time - start_time:.4f}s")
    
    def run_all_benchmarks(self):
        """运行所有基准测试"""
        print("Running performance benchmarks...")
        self.benchmark_line_access()
        self.benchmark_parameter_access()
        print("Benchmarks completed.")

# 运行基准测试
if __name__ == "__main__":
    benchmark = PerformanceBenchmark()
    benchmark.run_all_benchmarks()
```

## 🧪 测试策略

### 单元测试

```python
import unittest
from unittest.mock import Mock, patch

class TestParameterSystem(unittest.TestCase):
    """参数系统测试"""
    
    def test_parameter_descriptor(self):
        """测试参数描述符"""
        class TestClass(ParameterizedBase):
            test_param = ParameterDescriptor(default=10, type_=int)
        
        obj = TestClass()
        
        # 测试默认值
        self.assertEqual(obj.test_param, 10)
        
        # 测试设置值
        obj.test_param = 20
        self.assertEqual(obj.test_param, 20)
        
        # 测试类型检查
        with self.assertRaises(TypeError):
            obj.test_param = "not_an_int"
    
    def test_parameter_inheritance(self):
        """测试参数继承"""
        class BaseClass(ParameterizedBase):
            base_param = ParameterDescriptor(default=1)
        
        class DerivedClass(BaseClass):
            derived_param = ParameterDescriptor(default=2)
        
        obj = DerivedClass()
        
        # 测试继承的参数
        self.assertEqual(obj.base_param, 1)
        self.assertEqual(obj.derived_param, 2)

class TestLineSystem(unittest.TestCase):
    """线条系统测试"""
    
    def test_line_buffer(self):
        """测试线条缓冲区"""
        buffer = LineBuffer(maxlen=10)
        
        # 添加数据
        for i in range(15):
            buffer.append(i)
        
        # 测试长度限制
        self.assertEqual(len(buffer), 10)
        
        # 测试最新值访问
        self.assertEqual(buffer[0], 14)  # 最新值
        self.assertEqual(buffer[1], 13)  # 前一个值
    
    def test_line_series(self):
        """测试线条序列"""
        class TestLines(LineSeriesBase):
            lines = ('test_line',)
        
        data = TestLines()
        
        # 添加数据
        data.add_data(test_line=100)
        data.add_data(test_line=200)
        
        # 测试访问
        self.assertEqual(data.test_line[0], 200)  # 最新值
        self.assertEqual(data.test_line[1], 100)  # 前一个值
        self.assertEqual(data.lines.test_line[0], 200)  # 通过lines访问

class TestDependencyInjection(unittest.TestCase):
    """依赖注入测试"""
    
    def setUp(self):
        self.container = DependencyContainer()
    
    def test_service_registration(self):
        """测试服务注册"""
        class TestService:
            pass
        
        self.container.register(TestService)
        service = self.container.get(TestService)
        
        self.assertIsInstance(service, TestService)
    
    def test_singleton_service(self):
        """测试单例服务"""
        class TestService:
            pass
        
        self.container.register(TestService, singleton=True)
        
        service1 = self.container.get(TestService)
        service2 = self.container.get(TestService)
        
        self.assertIs(service1, service2)
    
    def test_context_management(self):
        """测试上下文管理"""
        class TestService:
            pass
        
        mock_service = Mock(spec=TestService)
        
        with self.container.with_context(TestService=mock_service):
            service = self.container.get(TestService)
            self.assertIs(service, mock_service)

if __name__ == '__main__':
    unittest.main()
```

### 集成测试

```python
class IntegrationTest(unittest.TestCase):
    """集成测试"""
    
    def test_full_strategy_workflow(self):
        """测试完整的策略工作流"""
        # 设置依赖
        container = get_container()
        container.register(IBroker, MockBroker, singleton=True)
        container.register(IDataFeed, MockDataFeed, singleton=True)
        
        # 创建策略
        class TestStrategy(Strategy):
            period = ParameterDescriptor(default=14, type_=int)
            
            def next(self):
                # 模拟策略逻辑
                if len(self.data) > self.period:
                    self.broker.buy("AAPL", 100)
        
        # 创建数据
        data = OHLCVLines()
        for i in range(20):
            data.add_data(
                open=100+i, high=102+i,
                low=99+i, close=101+i, volume=1000
            )
        
        # 运行策略
        strategy = TestStrategy(period=10)
        strategy.data = data
        
        # 模拟策略执行
        for i in range(len(data)):
            strategy.next()
        
        # 验证结果
        self.assertTrue(True)  # 如果没有异常，测试通过
```

这个技术实施指南提供了去除元编程的具体实现方案。通过这些新的组件，我们可以在保持功能完整性的同时，显著提高代码的可读性和可维护性。 