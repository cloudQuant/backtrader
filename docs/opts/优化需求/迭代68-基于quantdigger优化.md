### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/quantdigger
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### quantdigger项目简介
quantdigger是一个A股量化回测框架，具有以下核心特点：
- **期货支持**: 专注于期货市场的量化回测
- **可视化**: 内置K线和交易可视化
- **信号系统**: 灵活的交易信号系统
- **多周期**: 支持多周期数据分析
- **技术指标**: 内置常用技术指标
- **事件驱动**: 基于事件的回测引擎

### 重点借鉴方向
1. **绘图系统**: 可视化绘图系统设计
2. **信号系统**: 交易信号定义和管理
3. **多周期**: 多周期数据同步处理
4. **合约管理**: 期货合约管理
5. **数据系列**: DataSeries数据系列
6. **交易逻辑**: 交易逻辑抽象

---

# 项目分析报告

## 一、Backtrader 项目回顾

### 1.1 核心架构

Backtrader 采用**事件驱动架构**，核心组件：

| 组件 | 功能 |
|------|------|
| **Cerebro** | 回测引擎，协调所有组件 |
| **Line System** | 时间序列数据管理 |
| **Strategy** | 策略基类 |
| **Indicator** | 技术指标 |
| **Analyzer** | 性能分析器 |
| **Broker** | 订单执行和资金管理 |

### 1.2 当前优势

1. **成熟的回测系统**：完整的数据处理、订单执行、业绩分析
2. **丰富的技术指标**：60+ 内置指标
3. **多种数据源**：支持 CSV、Pandas、实时数据等
4. **灵活的策略系统**：继承式策略定义

### 1.3 相对不足

1. **可视化较弱**：绘图功能相对简单
2. **期货支持有限**：期货保证金、平今等细节不够完善
3. **策略语法复杂**：新手学习曲线较陡
4. **多周期支持**：多周期数据同步处理不够直观

---

## 二、QuantDigger 项目深度分析

### 2.1 核心架构设计

QuantDigger 采用**上下文模式 + 代理模式**的架构：

```
┌─────────────────────────────────────────────────────────────────┐
│                        ExecuteUnit                              │
│  (执行单元 - 策略运行的物理容器)                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│  │   Strategy   │───▶│   Context    │───▶│   DataRef    │     │
│  │   (策略)     │    │   (上下文)   │    │  (数据引用)  │     │
│  └──────────────┘    └──────────────┘    └──────────────┘     │
│                                │                                │
│                       ┌─────────┴─────────┐                    │
│                       ▼                   ▼                    │
│              ┌──────────────┐    ┌──────────────┐              │
│              │TradingDelegator│  │PlotterDelegator│             │
│              │  (交易代理)   │    │  (绘图代理)   │              │
│              └──────────────┘    └──────────────┘              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 数据系列系统（Series System）

**核心文件**：`quantdigger/engine/series.py`

**关键设计**：运算符重载实现直观的数据访问

```python
class NumberSeries(SeriesBase):
    """数字序列变量 - 支持运算符重载"""

    # 比较运算符
    def __eq__(self, r):
        return self[0] == float(r)

    def __lt__(self, r):
        return self[0] < float(r)

    # 算术运算符
    def __add__(self, r):
        return self[0] + float(r)

    def __getitem__(self, index):
        """支持历史数据访问"""
        i = self.curbar - index
        if i < 0 or index < 0:
            return self._default
        return float(self.data[i])
```

**使用示例**：
```python
# QuantDigger 风格
if ctx.ma10[1] < ctx.ma20[1] and ctx.ma10[0] > ctx.ma20[0]:
    ctx.buy(ctx.close[0], 1)  # 金叉买入
```

### 2.3 技术指标系统

**核心文件**：`quantdigger/technicals/common.py`

**装饰器注册机制**：

```python
# 指标注册装饰器
def register_tech(name):
    def decorator(cls):
        TechRegistry.register(name, cls)
        return cls
    return decorator

# 使用装饰器注册指标
@register_tech('MA')
class MA(TechnicalBase):
    @tech_init
    def __init__(self, data, n, name='MA', style='y', lw=1):
        super(MA, self).__init__(name)
        self._args = [ndarray(data), n]

    def _vector_algo(self, data, n):
        """向量化运行，使用 TA-Lib"""
        self.values = talib.SMA(data, n)

    def plot(self, widget):
        """内置绘图方法"""
        self.widget = widget
        self.plot_line(self.values, self.style, lw=self.lw)
```

**多值指标支持**（布林带）：

```python
@register_tech('BOLL')
class BOLL(TechnicalBase):
    def _vector_algo(self, data, n, a1, a2):
        """返回多值"""
        u, m, l = talib.BBANDS(data, n, a1, a2)
        self.values = {
            'upper': u,
            'middler': m,
            'lower': l
        }

    def plot(self, widget):
        """绘制多条线"""
        self.widget = widget
        self.plot_line(self.values['upper'], self.styles[0], lw=self.lw)
        self.plot_line(self.values['middler'], self.styles[1], lw=self.lw)
        self.plot_line(self.values['lower'], self.styles[2], lw=self.lw)
```

### 2.4 绘图系统

**核心文件**：`quantdigger/widgets/plotter.py`

**绘图基类设计**：

```python
class Plotter(object):
    """系统绘图基类"""

    def __init__(self, name, widget):
        self._upper = self._lower = None  # y轴范围
        self._xdata = None                # x轴数据

    def plot_line(self, *args, **kwargs):
        """画线 - 支持多种绘图容器"""
        # 自动区分 matplotlib 和 Qt 容器
        if isinstance(self.widget, Axes):
            self.ax_widget.plot_line(self.widget, ...)
        else:
            self.qt_widget.plot_line(self.widget, ...)

    def y_interval(self, w_left, w_right):
        """计算可视区域的y轴范围"""
        if len(self._upper) == 2:
            return max(self._upper), min(self._lower)
        # 动态计算可视区域内的最大最小值
        ymax = np.max(self._upper[w_left: w_right])
        ymin = np.min(self._lower[w_left: w_right])
        return ymax, ymin
```

**参数自动装饰器**：

```python
def plot_init(method):
    """根据被修饰函数的参数构造属性"""
    def wrapper(self, *args, **kwargs):
        magic = inspect.getargspec(method)
        arg_names = magic.args[1:]
        # 默认参数
        default = dict((x, y) for x, y in zip(
            magic.args[-len(magic.defaults):],
            magic.defaults))
        # 调用参数
        method_args = {}
        for i, arg in enumerate(args):
            method_args[arg_names[i]] = arg
        method_args.update(kwargs)
        # 合并并创建属性
        default.update(method_args)
        for key, value in six.iteritems(default):
            setattr(self, key, value)
        # 运行构造函数
        rst = method(self, *args, **kwargs)
        self._init_bound()  # 计算绘图范围
        return rst
    return wrapper
```

### 2.5 上下文系统

**核心文件**：`quantdigger/engine/context/context.py`

**关键设计**：属性代理实现透明的数据访问

```python
class Context(PlotterDelegator, TradingDelegator):
    """上下文 - 策略运行环境"""

    def __getattr__(self, name):
        """属性代理 - 自动从数据源获取"""
        original = self.data_ref.original
        derived = self.data_ref._pcontract_data.derived
        if hasattr(original, name):
            return getattr(original, name)
        elif hasattr(derived, name):
            return getattr(derived, name)

    def __setattr__(self, name, value):
        """属性设置 - 自动添加为自定义序列"""
        if name in ['dt_series', 'strategy', ...]:
            # 内部属性
            super(Context, self).__setattr__(name, value)
        else:
            # 自定义序列变量
            if isinstance(value, SeriesBase):
                value.reset_data([], self.data_ref.original.size)
            self.data_ref.add_item(name, value)

    @property
    def close(self):
        """k 线收盘价序列"""
        return self.data_ref.original.close

    @property
    def curbar(self):
        """当前是第几根 k 线"""
        if self.on_bar:
            return self.aligned_bar_index + 1
        else:
            return self.data_ref.original.curbar
```

### 2.6 期货合约管理

**核心文件**：`quantdigger/datastruct.py`

**合约结构**：

```python
class Contract(object):
    """合约"""
    def __init__(self, str_contract):
        info = str_contract.split('.')
        self.code = info[0].upper()      # 合约代码
        self.exchange = info[1].upper()  # 交易所

    @classmethod
    def long_margin_ratio(cls, strcontract):
        """多头保证金比例"""

    @classmethod
    def short_margin_ratio(cls, strcontract):
        """空头保证金比例"""

    @classmethod
    def volume_multiple(cls, strcontract):
        """合约乘数"""
```

**PContract（周期合约）**：

```python
class PContract(object):
    """特定周期的合约"""
    def __init__(self, contract, period):
        self.contract = contract  # 合约对象
        self.period = period      # 周期

    @classmethod
    def from_string(cls, strpcon):
        """从字符串解析，如 'BB.SHFE-1.Day'"""
        t = strpcon.split('-')
        return cls(Contract(t[0]), Period(t[1]))
```

**交易类型支持**：

```python
class TradeSide(object):
    BUY = 1          # 多头开仓
    SHORT = 2        # 空头开仓
    COVER = 3        # 空头平仓
    SELL = 4         # 多头平仓
    COVER_TODAY = 5  # 空头平今
    SELL_TODAY = 6   # 多头平今
```

### 2.7 策略基类

**核心文件**：`quantdigger/engine/strategy.py`

**简洁的策略接口**：

```python
class Strategy(object):
    """策略基类"""

    def on_init(self, ctx):
        """初始化数据"""
        return

    def on_symbol_init(self, ctx):
        """逐合约初始化"""
        return

    def on_symbol_step(self, ctx):
        """逐合约逐根 k 线运行"""
        return

    def on_bar(self, ctx):
        """逐根 k 线运行"""
        return

    def on_exit(self, ctx):
        """策略结束前运行"""
        return
```

**策略示例**：

```python
class DoubleMA(Strategy):
    """双均线策略"""

    def on_init(self, ctx):
        """初始化指标"""
        ctx.ma10 = MA(ctx.close, 10)
        ctx.ma20 = MA(ctx.close, 20)

    def on_bar(self, ctx):
        """主逻辑"""
        # 使用运算符重载实现直观的条件判断
        if ctx.pos() == 0 and ctx.ma10[1] < ctx.ma20[1] and ctx.ma10[0] > ctx.ma20[0]:
            ctx.buy(ctx.close[0], 1)  # 金叉买入
        elif ctx.pos() > 0 and ctx.ma10[1] > ctx.ma20[1] and ctx.ma10[0] < ctx.ma20[0]:
            ctx.sell(ctx.close[0], ctx.pos())  # 死叉卖出
```

### 2.8 多周期数据同步

**数据对齐机制**：

```python
class DataRef(object):
    """数据引用管理器"""

    def datetime_aligned(self, context_dt):
        """检查时间是否对齐"""
        return (self.original.datetime[0] <= context_dt and
                self.original.next_datetime <= context_dt)

    def rolling_forward(self, context_dt_update_func):
        """向前推进数据"""
        if self.original.has_pending_data:
            context_dt_update_func(self.original.next_datetime)
            return True
```

### 2.9 组合策略支持

```python
# 支持一个组合中运行多个策略
profiles = add_strategies(['BB.SHFE-1.Day'], [
    {'strategy': DemoStrategy('A1'), 'capital': 50000.0 * 0.5},
    {'strategy': DemoStrategy2('A2'), 'capital': 50000.0 * 0.5},
])
```

---

## 三、架构对比分析

| 维度 | Backtrader | QuantDigger |
|------|------------|-------------|
| **架构模式** | 事件驱动 + Line System | 上下文模式 + 代理模式 |
| **数据访问** | `data.close[0]` | `ctx.close[0]` |
| **运算符支持** | 有限 | 完整的运算符重载 |
| **策略语法** | 继承式 + 生命周期方法 | 简化的生命周期方法 |
| **指标系统** | Line 嵌套 | 装饰器注册 + TA-Lib |
| **绘图系统** | 基础 matplotlib | 内置绘图代理 |
| **期货支持** | 基础 | 完整（保证金、平今等） |
| **多周期** | 数据重采样 | PContract 设计 |

---

# 需求文档

## 一、优化目标

借鉴 QuantDigger 的设计优势，为 backtrader 新增以下功能：

1. **运算符增强**：支持序列对象的运算符重载
2. **简化策略接口**：提供更简洁的策略基类
3. **增强绘图系统**：内置可视化绘图能力
4. **期货完善**：完善期货保证金和平今支持
5. **指标装饰器**：简化指标注册和开发

## 二、功能需求

### FR1: 序列运算符增强

**优先级**：高

**描述**：
为 Line 对象添加完整的运算符重载，支持直观的数据比较和算术运算。

**功能点**：
1. 比较运算符：`==`, `!=`, `<`, `<=`, `>`, `>=`
2. 算术运算符：`+`, `-`, `*`, `/`, `**`, `%`
3. 位运算符：`&`, `|`, `^`
4. 复合赋值：`+=`, `-=`, `*=`, `/=`

**API 设计**：
```python
import backtrader as bt

# 当前方式（繁琐）
if self.crossover > 0:
    self.buy()

# 优化后（直观）
if self.ma_fast[0] > self.ma_slow[0] and self.ma_fast[-1] <= self.ma_slow[-1]:
    self.buy()
```

### FR2: 简化策略接口

**优先级**：中

**描述**：
提供更简洁的策略基类，降低新手学习门槛。

**功能点**：
1. 简化的生命周期方法
2. 透明的数据访问
3. 自动指标管理

**API 设计**：
```python
import backtrader as bt

class SimpleStrategy(bt.Strategy):
    """简化策略基类"""

    # 直接通过属性访问数据
    def on_bar(self):
        if self.ma10[1] < self.ma20[1] and self.ma10[0] > self.ma20[0]:
            self.buy(self.close[0], 1)
```

### FR3: 增强绘图系统

**优先级**：中

**描述**：
提供内置的绘图系统，支持 K 线、指标、信号的自动绘制。

**功能点**：
1. K 线图自动绘制
2. 指标叠加绘制
3. 买卖信号标记
4. 多子图支持
5. 交互式缩放

**API 设计**：
```python
import backtrader as bt

# 自动绘图
cerebro = bt.Cerebro()

# 启用自动绘图
cerebro.setautoplot(
    indicators=True,    # 绘制指标
    signals=True,       # 绘制信号
    volume=True,        # 绘制成交量
    style='candle',     # K线风格
)

# 运行并显示
cerebro.run()
cerebro.plot()
```

### FR4: 期货完善支持

**优先级**：高

**描述**：
完善期货交易的支持，包括保证金、平今等细节。

**功能点**：
1. 多头/空头保证金计算
2. 平今优先逻辑
3. 合约乘数支持
4. 持仓成本计算

**API 设计**：
```python
import backtrader as bt

# 期货手续费
class FutureCommission(bt.CommissionInfo):
    params = (
        ('mult', 10),           # 合约乘数
        ('long_margin', 0.08),  # 多头保证金 8%
        ('short_margin', 0.08), # 空头保证金 8%
        ('commission', 10),     # 每手手续费
    )

# 平今优先
cerebro.broker.set_coc(True)  # Close Today First
```

### FR5: 指标装饰器

**优先级**：中

**描述**：
使用装饰器简化指标的注册和开发。

**API 设计**：
```python
import backtrader as bt

# 指标装饰器
@bt.indicator.register('CustomMA')
class CustomMA(bt.Indicator):
    params = (('period', 20),)
    lines = ('ma',)

    def __init__(self):
        self.lines.ma = bt.indicators.SMA(self.data, period=self.p.period)

    def plot(self, widget):
        """内置绘图方法"""
        widget.plot_line(self.lines.ma, style='y', lw=1)
```

---

## 三、非功能需求

### NFR1: 兼容性

- 新增功能与现有 API 兼容
- 不破坏现有策略代码

### NFR2: 性能

- 运算符重载不增加额外开销
- 绘图系统支持大数据量

### NFR3: 可用性

- 提供清晰的错误提示
- 丰富的文档和示例

---

# 设计文档

## 一、总体架构设计

### 1.1 新增模块结构

```
backtrader/
├── indicators/
│   └── decorators.py        # 新增：指标装饰器
├── lines/
│   └── operators.py         # 新增：运算符重载
├── strategy/
│   └── simple.py            # 新增：简化策略基类
├── plotting/                # 新增：绘图模块
│   ├── __init__.py
│   ├── base.py              # 绘图基类
│   ├── widgets/             # 绘图组件
│   │   ├── matplotlib.py    # matplotlib 后端
│   │   └── plotly.py        # plotly 后端
│   └── schemes.py           # 绘图配色方案
└── futures/                 # 新增：期货支持
    ├── __init__.py
    ├── commission.py        # 期货手续费
    └── position.py          # 期货持仓
```

## 二、详细设计

### 2.1 序列运算符增强

**文件位置**：`backtrader/lines/operators.py`

**核心类**：

```python
class LineOps:
    """Line 对象运算符混入类"""

    def __eq__(self, other):
        """相等比较"""
        if isinstance(other, LineSingle):
            return self._cmp(other, lambda a, b: a == b)
        return self._cmp_scalar(other, lambda a, b: a == b)

    def __lt__(self, other):
        """小于比较"""
        if isinstance(other, LineSingle):
            return self._cmp(other, lambda a, b: a < b)
        return self._cmp_scalar(other, lambda a, b: a < b)

    def __le__(self, other):
        """小于等于比较"""
        if isinstance(other, LineSingle):
            return self._cmp(other, lambda a, b: a <= b)
        return self._cmp_scalar(other, lambda a, b: a <= b)

    def __gt__(self, other):
        """大于比较"""
        if isinstance(other, LineSingle):
            return self._cmp(other, lambda a, b: a > b)
        return self._cmp_scalar(other, lambda a, b: a > b)

    def __ge__(self, other):
        """大于等于比较"""
        if isinstance(other, LineSingle):
            return self._cmp(other, lambda a, b: a >= b)
        return self._cmp_scalar(other, lambda a, b: a >= b)

    def __add__(self, other):
        """加法"""
        if isinstance(other, LineSingle):
            return self._arithmetic(other, lambda a, b: a + b)
        return self._arithmetic_scalar(other, lambda a, b: a + b)

    def __sub__(self, other):
        """减法"""
        if isinstance(other, LineSingle):
            return self._arithmetic(other, lambda a, b: a - b)
        return self._arithmetic_scalar(other, lambda a, b: a - b)

    def __mul__(self, other):
        """乘法"""
        if isinstance(other, LineSingle):
            return self._arithmetic(other, lambda a, b: a * b)
        return self._arithmetic_scalar(other, lambda a, b: a * b)

    def __truediv__(self, other):
        """除法"""
        if isinstance(other, LineSingle):
            return self._arithmetic(other, lambda a, b: a / b)
        return self._arithmetic_scalar(other, lambda a, b: a / b)

    def __and__(self, other):
        """位与 - 用于条件组合"""
        if isinstance(other, LineSingle):
            return self._logic(other, lambda a, b: a and b)
        return self._logic_scalar(other, lambda a, b: a and b)

    def __or__(self, other):
        """位或 - 用于条件组合"""
        if isinstance(other, LineSingle):
            return self._logic(other, lambda a, b: a or b)
        return self._logic_scalar(other, lambda a, b: a or b)

    # 在 LineSingle 或 LineBuffer 中混入此类
```

### 2.2 简化策略基类

**文件位置**：`backtrader/strategy/simple.py`

**核心类**：

```python
class SimpleStrategy(Strategy):
    """
    简化的策略基类

    特点：
        - 通过属性直接访问数据
        - 自动指标管理
        - 简化的交易方法
    """

    def __getattr__(self, name):
        """属性代理 - 从数据源获取"""
        # 1. 检查是否是数据线
        if hasattr(self.data, name):
            return getattr(self.data, name)
        # 2. 检查是否是指标
        if name in self._indicators:
            return self._indicators[name]
        # 3. 检查是否是其他属性
        return super().__getattr__(name)

    def __setattr__(self, name, value):
        """属性设置"""
        # 如果是 Line 或 Indicator，自动管理
        if isinstance(value, (LineSingle, IndicatorBase)):
            self._indicators[name] = value
        else:
            super().__setattr__(name, value)

    def buy(self, price=None, size=None, **kwargs):
        """
        简化的买入方法

        Args:
            price: 价格，None 表示市价
            size: 数量，None 表示使用默认数量
        """
        if price is None:
            price = self.data.close[0]
        if size is None:
            size = self.getsizer()
        return super().buy(size=size, price=price, **kwargs)

    def sell(self, price=None, size=None, **kwargs):
        """简化的卖出方法"""
        if price is None:
            price = self.data.close[0]
        if size is None:
            size = self.getsizer()
        return super().sell(size=size, price=price, **kwargs)

    @property
    def pos(self):
        """当前持仓"""
        return self.getposition().size
```

### 2.3 增强绘图系统

**文件位置**：`backtrader/plotting/base.py`

**核心类**：

```python
class Plotter:
    """
    绘图器基类

    支持：
        - K 线图
        - 指标叠加
        - 信号标记
        - 多子图
    """

    def __init__(self, cerebro):
        self.cerebro = cerebro
        self.strategies = cerebro.runstrats
        self.indicators = []
        self.signals = []

    def plot(self, style='candle', indicators=True, signals=True, volume=True):
        """
        绘制回测结果

        Args:
            style: K 线风格 ('candle', 'bar', 'line')
            indicators: 是否绘制指标
            signals: 是否绘制信号
            volume: 是否绘制成交量
        """
        import matplotlib.pyplot as plt
        from matplotlib.gridspec import GridSpec

        # 创建图表
        fig = plt.figure(figsize=(15, 10))
        gs = GridSpec(4, 1, figure=fig, height_ratios=[3, 1, 1, 1])

        # 主图：K 线 + 叠加指标
        ax_main = fig.add_subplot(gs[0])
        self._plot_klines(ax_main, style)

        if indicators:
            self._plot_indicators(ax_main)

        if signals:
            self._plot_signals(ax_main)

        # 成交量图
        if volume:
            ax_vol = fig.add_subplot(gs[1], sharex=ax_main)
            self._plot_volume(ax_vol)

        # 其他指标子图
        self._plot_subplot_indicators(gs[2:])

        plt.tight_layout()
        plt.show()

    def _plot_klines(self, ax, style):
        """绘制 K 线"""
        import mpl_finance as mpf

        data = self._get_ohlc_data()
        if style == 'candle':
            mpf.candlestick2_ochl(ax, data['open'], data['close'],
                                   data['high'], data['low'],
                                   width=0.6, colorup='r', colordown='g')
        else:
            # 其他风格
            pass

    def _plot_indicators(self, ax):
        """绘制叠加指标"""
        for strat in self.strategies:
            for indicator in strat.getindicators():
                if hasattr(indicator, 'plot_override'):
                    # 使用自定义绘图
                    indicator.plot_override(ax)
                elif hasattr(indicator, 'lines'):
                    # 默认绘图
                    for line in indicator.lines:
                        ax.plot(line.array, label=indicator.__class__.__name__)

    def _plot_signals(self, ax):
        """绘制买卖信号"""
        for strat in self.strategies:
            trades = strat.analyzers.trade.get_analysis() or []
            for trade in trades:
                if trade.isbuy:
                    ax.scatter(trade.dt, trade.price, marker='^', color='r', s=100)
                else:
                    ax.scatter(trade.dt, trade.price, marker='v', color='g', s=100)
```

### 2.4 期货完善支持

**文件位置**：`backtrader/futures/commission.py`

**核心类**：

```python
class FutureCommission(CommissionInfo):
    """
    期货手续费和保证金

    支持：
        - 多头/空头保证金
        - 平今优先
        - 合约乘数
    """

    params = (
        ('mult', 1),              # 合约乘数
        ('long_margin', 0.08),    # 多头保证金比例
        ('short_margin', 0.08),   # 空头保证金比例
        ('commission', 0),        # 每手手续费
        ('commission_pct', 0),    # 手续费比例
        ('close_today_first', True),  # 平今优先
    )

    def get_margin(self, size, price):
        """
        计算保证金

        Args:
            size: 手数
            price: 价格
        """
        value = abs(size) * price * self.p.mult
        if size > 0:
            return value * self.p.long_margin
        else:
            return value * self.p.short_margin

    def _getcommission(self, size, price):
        """
        计算手续费

        支持按手数和按金额两种方式
        """
        # 按手数
        comm_by_lot = abs(size) * self.p.commission

        # 按金额
        comm_by_pct = abs(size) * price * self.p.mult * self.p.commission_pct

        return comm_by_lot + comm_by_pct

    def profitandloss(self, size, price, pnlonly=False):
        """
        计算盈亏

        支持平今优先逻辑
        """
        # 获取当前持仓
        position = self.getposition(size)

        if self.p.close_today_first:
            # 平今优先
            today_size = self._get_today_position(size)
            if today_size != 0:
                # 平今部分
                pnl_today = self._calc_pnl(today_size, price, is_today=True)
                # 平昨部分
                pnl_yesterday = self._calc_pnl(size - today_size, price, is_today=False)
                return pnl_today + pnl_yesterday

        return self._calc_pnl(size, price, is_today=False)

    def _get_today_position(self, size):
        """获取今日持仓"""
        # 实现今日持仓计算
        pass

    def _calc_pnl(self, size, price, is_today):
        """计算盈亏"""
        # 实现盈亏计算
        pass
```

### 2.5 指标装饰器

**文件位置**：`backtrader/indicators/decorators.py`

**核心实现**：

```python
from functools import wraps

# 指标注册表
_indicator_registry = {}

def register(name=None):
    """
    指标注册装饰器

    用法:
        @bt.indicator.register('MyMA')
        class MyMA(bt.Indicator):
            pass
    """
    def decorator(cls):
        # 确定指标名称
        ind_name = name or cls.__name__

        # 注册到全局表
        _indicator_registry[ind_name] = cls

        # 添加到 indicators 模块
        from backtrader import indicators
        setattr(indicators, ind_name, cls)

        return cls
    return decorator

def plot_init(method):
    """
    绘图初始化装饰器

    用法:
        class MyIndicator(bt.Indicator):
            @plot_init
            def __init__(self, data, period=20, style='y', lw=1):
                pass
    """
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        # 获取参数信息
        import inspect
        magic = inspect.getfullargspec(method)
        arg_names = magic.args[1:]  # 跳过 self

        # 默认参数
        defaults = dict(zip(magic.args[-len(magic.defaults or []):],
                            magic.defaults or []))

        # 调用参数
        method_args = {}
        for i, arg in enumerate(args):
            if i < len(arg_names):
                method_args[arg_names[i]] = arg

        # 合并参数
        defaults.update(method_args)
        defaults.update(kwargs)

        # 设置为属性
        for key, value in defaults.items():
            setattr(self, key, value)

        # 调用原始方法
        result = method(self, *args, **kwargs)

        # 初始化绘图范围
        if hasattr(self, '_init_plot_bound'):
            self._init_plot_bound()

        return result
    return wrapper
```

## 三、使用示例

### 3.1 运算符增强示例

```python
import backtrader as bt

class Strategy(bt.Strategy):
    def __init__(self):
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        # 使用运算符重载
        if self.ma10[0] > self.ma20[0] and self.ma10[-1] <= self.ma20[-1]:
            self.buy(size=100)

        # 复合条件
        golden_cross = (self.ma10[0] > self.ma20[0]) & (self.ma10[-1] <= self.ma20[-1])
        if golden_cross:
            self.buy(size=100)
```

### 3.2 简化策略示例

```python
import backtrader as bt

class MyStrategy(bt.SimpleStrategy):
    """简化策略"""

    def on_init(self):
        """初始化指标"""
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

    def on_bar(self):
        """主逻辑"""
        # 直接通过属性访问数据
        if self.ma10[1] < self.ma20[1] and self.ma10[0] > self.ma20[0]:
            if self.pos == 0:
                # 简化的买入方法
                self.buy(self.close[0], 100)

        elif self.ma10[1] > self.ma20[1] and self.ma10[0] < self.ma20[0]:
            if self.pos > 0:
                # 平仓
                self.sell(self.close[0], self.pos)
```

### 3.3 指标装饰器示例

```python
import backtrader as bt

@bt.indicator.register('CustomBOLL')
class CustomBOLL(bt.Indicator):
    """
    自定义布林带指标

    使用装饰器自动注册和设置绘图参数
    """
    params = (('period', 20), ('devfactor', 2))

    @bt.indicator.plot_init
    def __init__(self, data, period=20, devfactor=2,
                 style_upper='r', style_mid='y', style_lower='g', lw=1):
        super().__init__()
        self.mid = bt.indicators.SMA(data, period=period)
        std = bt.indicators.StdDev(data, period=period)

        self.upper = self.mid + devfactor * std
        self.lower = self.mid - devfactor * std

        # 绘图属性已自动设置
        self.style_upper = style_upper
        self.style_mid = style_mid
        self.style_lower = style_lower
        self.lw = lw

    def plot(self, widget):
        """自定义绘图"""
        widget.plot_line(self.upper, self.style_upper, lw=self.lw)
        widget.plot_line(self.mid, self.style_mid, lw=self.lw)
        widget.plot_line(self.lower, self.style_lower, lw=self.lw)
```

### 3.4 自动绘图示例

```python
import backtrader as bt

# 创建 Cerebro
cerebro = bt.Cerebro()

# 添加数据和策略
cerebro.adddata(data)
cerebro.addstrategy(MyStrategy)

# 启用自动绘图
cerebro.setautoplot(
    style='candle',        # K 线风格
    indicators=True,       # 绘制指标
    signals=True,         # 绘制信号
    volume=True,          # 绘制成交量
    subplot_indicators=['RSI'],  # 需要单独绘制子图的指标
)

# 运行
results = cerebro.run()

# 自动显示图表
cerebro.plot()
```

### 3.5 期货策略示例

```python
import backtrader as bt

# 期货手续费
class FutureComm(bt.FutureCommission):
    params = dict(
        mult=10,              # 合约乘数
        long_margin=0.08,     # 多头保证金 8%
        short_margin=0.08,    # 空头保证金 8%
        commission=10,        # 每手 10 元
    )

# 期货策略
class FutureStrategy(bt.SimpleStrategy):
    def on_bar(self):
        # 获取当前价格
        price = self.close[0]

        # 简单的突破策略
        if self.close[0] > self.close.max(period=20)[-1]:
            if self.pos == 0:
                # 开多仓
                self.buy(price, 1)
        elif self.close[0] < self.close.min(period=20)[-1]:
            if self.pos == 0:
                # 开空仓
                self.sell(price, 1)
        elif self.pos > 0 and self.close[0] < self.close.min(period=10)[-1]:
            # 平多仓
            self.sell(price, self.pos)
        elif self.pos < 0 and self.close[0] > self.close.max(period=10)[-1]:
            # 平空仓
            self.buy(price, -self.pos)

# 设置
cerebro = bt.Cerebro()
cerebro.adddata(future_data)
cerebro.addstrategy(FutureStrategy)
cerebro.broker.setcommission(FutureComm())
cerebro.broker.set_coc(True)  # 平今优先

# 运行
results = cerebro.run()
```

## 四、实施计划

### Phase 1: 运算符增强 (优先级：高)

1. 实现 `LineOps` 混入类
2. 修改 `LineSingle` 和 `LineBuffer` 添加运算符
3. 单元测试

### Phase 2: 期货完善支持 (优先级：高)

1. 实现 `FutureCommission`
2. 实现平今优先逻辑
3. 集成测试

### Phase 3: 简化策略接口 (优先级：中)

1. 实现 `SimpleStrategy`
2. 实现属性代理
3. 示例和文档

### Phase 4: 绘图系统 (优先级：中)

1. 实现 `Plotter` 基类
2. 实现 K 线绘制
3. 实现指标和信号绘制
4. 集成到 Cerebro

### Phase 5: 指标装饰器 (优先级：低)

1. 实现装饰器
2. 更新指标注册系统
3. 示例和文档

---

## 附录

### A. 参考资料

1. **QuantDigger**: https://github.com/QuantFans/quantdigger
2. **TA-Lib**: https://ta-lib.org/
3. **mpl_finance**: https://github.com/matplotlib/mpl-finance

### B. 代码对比

**Backtrader 原始写法**：
```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.ma10 = bt.indicators.SMA(self.data.close, period=10)
        self.ma20 = bt.indicators.SMA(self.data.close, period=20)
        self.crossover = bt.indicators.CrossOver(self.ma10, self.ma20)

    def next(self):
        if self.crossover[0] > 0:
            self.buy()
```

**优化后的写法**：
```python
class MyStrategy(bt.SimpleStrategy):
    def on_init(self):
        self.ma10 = bt.indicators.SMA(self.close, period=10)
        self.ma20 = bt.indicators.SMA(self.close, period=20)

    def on_bar(self):
        if self.ma10[1] < self.ma20[1] and self.ma10[0] > self.ma20[0]:
            if self.pos == 0:
                self.buy(self.close[0], 100)
```

---

*文档版本：v1.0*
*创建日期：2026-01-08*
*作者：Claude*
