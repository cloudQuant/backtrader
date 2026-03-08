### 背景

backtrader 已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化 backtrader。

### 任务

1. 阅读研究分析 backtrader 这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/zvt
3. 借鉴这个新项目的优点和功能，给 backtrader 优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

---
## 架构对比分析

### Backtrader 核心特点

- *优势:**
1. **成熟的 Line 系统**: 基于循环缓冲区的高效时间序列数据管理
2. **完整的回测引擎**: Cerebro 统一管理策略、数据、经纪商、分析器
3. **丰富的技术指标**: 60+内置技术指标
4. **性能优化**: 支持向量化(once 模式)和事件驱动(next 模式)双执行模式
5. **Cython 加速**: 关键路径使用 Cython 优化
6. **多市场支持**: 支持股票、期货、加密货币等多种市场

- *局限:**
1. **初始化复杂**: 移除元类后的 donew()模式仍然复杂
2. **Factor 系统缺失**: 没有统一的因子计算和管理框架
3. **数据接口分散**: 各数据源独立实现，缺少统一抽象
4. **多周期策略支持弱**: 虽支持多周期数据，但因子合成不够优雅
5. **信号系统不完善**: 缺少标准化的信号生成和管理机制

### ZVT 核心特点

- *优势:**
1. **统一的 Schema 系统**: 所有数据继承 Mixin 基类，提供统一的 record_data()和 query_data()接口
2. **优雅的 Factor 流水线**: Data → Transformer → Accumulator → Scorer → Signal
3. **多数据源架构**: 每个 Schema 可注册多个 Provider，自动路由
4. **因子持久化**: 计算结果可持久化到数据库，避免重复计算
5. **实体中心设计**: 以 Entity 为核心，天然支持多资产组合
6. **动态注册机制**: 使用元类自动注册 Factor、Schema、Recorder
7. **成本建模完善**: 内置滑点、手续费等成本模型
8. **目标选择系统**: Factor 直接输出 target 列表，简化策略开发

- *局限:**
1. **性能不如 Backtrader**: 缺少向量化加速
2. **社区较小**: 相比 Backtrader 生态不够完善
3. **实时交易支持弱**: 主要面向研究场景

---
## 需求规格文档

### 1. 统一的 Factor 系统 (优先级: 高)

- *需求描述:**

Backtrader 需要引入统一的因子计算框架，支持数据转换、累积计算、评分和信号生成的流水线模式。

- *功能需求:**
1. **Transformer**: 无状态数据转换，实现 MA、MACD 等基础计算
2. **Accumulator**: 有状态累积器，支持跨时间窗口的状态维护
3. **Scorer**: 评分系统，支持 Rank、Quantile 等评分方式
4. **Factor**: 统一的因子基类，整合上述组件

- *非功能需求:**
1. 兼容现有 Indicator 系统，平滑迁移
2. 支持因子结果持久化
3. 保持高性能特性

### 2. 统一的数据访问接口 (优先级: 高)

- *需求描述:**

参考 ZVT 的 Schema 系统，为 Backtrader 的数据源提供统一的访问接口。

- *功能需求:**
1. 定义 DataFeed 的基类接口，包含统一的 query()方法
2. 支持多数据源注册和自动切换
3. 支持数据源能力查询（支持的时间周期、数据字段等）

- *非功能需求:**
1. 不破坏现有 DataFeed API
2. 保持向后兼容

### 3. 目标选择系统 (优先级: 中)

- *需求描述:**

引入 Target 概念，Factor 直接输出可交易的标的列表，简化策略开发。

- *功能需求:**
1. Factor 可输出 long_targets、short_targets、keep_targets
2. 支持多种选择方式（绝对值、百分比、排名）
3. 支持多因子合成

### 4. 因子持久化 (优先级: 中)

- *需求描述:**

支持将计算后的因子值保存到数据库，避免重复计算。

- *功能需求:**
1. 支持 SQLite/PostgreSQL 等数据库
2. 自动处理增量更新
3. 支持按时间范围查询

### 5. 动态注册机制 (优先级: 低)

- *需求描述:**

参考 ZVT 的元类注册，自动注册 Indicator、DataFeed 等组件。

- *功能需求:**
1. 定义组件时自动注册到全局注册表
2. 支持按名称查找和创建组件
3. 支持组件能力查询

### 6. 实体中心设计 (优先级: 低)

- *需求描述:**

引入 Entity 概念，更好地支持多资产组合策略。

- *功能需求:**
1. 定义 Entity 基类
2. 支持按 Entity 分组计算因子
3. 支持跨 Entity 的因子排名

---
## 设计文档

### 1. Factor 系统设计

#### 1.1 架构设计

```bash
                    ┌─────────────────┐
                    │   FactorBase    │
                    └────────┬────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
        ┌───────▼──────┐ ┌──▼────────┐ ┌▼──────────┐
        │ Transformer  │ │Accumulator│ │  Scorer   │
        └──────────────┘ └───────────┘ └───────────┘

```

#### 1.2 类设计

```python

# backtrader/factor/factor_base.py

class FactorBase(LineIterator):
    """
    因子基类，整合 Transformer、Accumulator、Scorer
    """
    params = (
        ('transformer', None),  # Transformer 实例
        ('accumulator', None),  # Accumulator 实例
        ('scorer', None),       # Scorer 实例
        ('persist', False),     # 是否持久化
    )

    def __init__(self):
        super().__init__()
        self.targets = {
            'long': [],
            'short': [],
            'keep': []
        }

    def compute(self):
        """计算因子值"""

# 1. Transformer 转换数据
        if self.p.transformer:
            self.pipe_df = self.p.transformer.transform(self.data)

# 2. Accumulator 累积计算
        if self.p.accumulator:
            self.factor_df, self.state = self.p.accumulator.acc(
                self.pipe_df, self.state
            )

# 3. Scorer 评分
        if self.p.scorer:
            self.score_df = self.p.scorer.score(self.factor_df)

# 4. 生成目标列表
        self._generate_targets()

    def get_targets(self, timestamp=None, target_type='long'):
        """获取目标列表"""
        return self.targets.get(target_type, [])

```

#### 1.3 Transformer 设计

```python

# backtrader/factor/transformer.py

class Transformer(object):
    """无状态数据转换器基类"""
    def transform(self, data):
        """转换输入数据"""
        raise NotImplementedError

class MaTransformer(Transformer):
    """移动平均转换器"""
    params = (('windows', [5, 10, 20, 60]),)

    def transform(self, data):
        result = {}
        for window in self.p.windows:
            result[f'ma{window}'] = self._compute_ma(data, window)
        return result

```

#### 1.4 Accumulator 设计

```python

# backtrader/factor/accumulator.py

class Accumulator(object):
    """有状态累积器基类"""
    def __init__(self):
        self.state = {}

    def acc(self, data, state=None):
        """
        累积计算
        返回: (result, new_state)
        """
        raise NotImplementedError

```

#### 1.5 Scorer 设计

```python

# backtrader/factor/scorer.py

class Scorer(object):
    """评分器基类"""
    def score(self, data):
        """对数据进行评分"""
        raise NotImplementedError

class RankScorer(Scorer):
    """排名评分器"""
    params = (('ascending', True),)

    def score(self, data):
        return data.rank(ascending=self.p.ascending)

class QuantileScorer(Scorer):
    """分位数评分器"""
    params = (('levels', [0, 0.25, 0.5, 0.75, 1.0]),)

    def score(self, data):
        return pd.cut(data, bins=self.p.levels, labels=False)

```

### 2. 统一数据接口设计

#### 2.1 DataFeed 注册系统

```python

# backtrader/feeds/registry.py

class DataFeedRegistry(object):
    """数据源注册表"""
    _feeds = {}

    @classmethod
    def register(cls, name, feed_class, capabilities=None):
        """注册数据源"""
        cls._feeds[name] = {
            'class': feed_class,
            'capabilities': capabilities or {}
        }

    @classmethod
    def get_feed(cls, name):
        """获取数据源类"""
        return cls._feeds.get(name, {})['class']

    @classmethod
    def list_feeds(cls):
        """列出所有数据源"""
        return list(cls._feeds.keys())

# 使用装饰器注册

def register_feed(name, capabilities=None):
    def decorator(cls):
        DataFeedRegistry.register(name, cls, capabilities)
        return cls
    return decorator

```

#### 2.2 统一查询接口

```python

# backtrader/feeds/base.py

class FeedBase(with_metaclass(MetaBase, LineSeries)):
    """增强的数据源基类"""
    _capabilities = {
        'timeframes': [],  # 支持的时间周期
        'fields': [],      # 支持的字段
        'live': False,     # 是否支持实时数据
    }

    @classmethod
    def query(cls, codes=None, start=None, end=None, timeframe=None):
        """
        统一的数据查询接口

        Args:
            codes: 标的代码列表
            start: 开始时间
            end: 结束时间
            timeframe: 时间周期

        Returns:
            DataFrame with multi-index (code, timestamp)
        """
        raise NotImplementedError

```

### 3. 目标选择系统设计

```python

# backtrader/factor/target.py

class TargetSelector(object):
    """目标选择器"""

    @staticmethod
    def select_by_threshold(data, threshold=None, top_n=None, mode='long'):
        """
        按阈值选择目标

        Args:
            data: {code: value} 字典
            threshold: 阈值
            top_n: 选择前 N 个
            mode: 'long' | 'short' | 'keep'

        Returns:
            选中的 code 列表
        """
        df = pd.Series(data)
        if mode == 'long':
            if threshold:
                return df[df > threshold].index.tolist()
            if top_n:
                return df.nlargest(top_n).index.tolist()
        elif mode == 'short':
            if threshold:
                return df[df < threshold].index.tolist()
            if top_n:
                return df.nsmallest(top_n).index.tolist()
        return []

    @staticmethod
    def select_by_percent(data, percent=0.1, mode='long'):
        """按百分比选择"""
        df = pd.Series(data)
        n = int(len(df) * percent)
        if mode == 'long':
            return df.nlargest(n).index.tolist()
        else:
            return df.nsmallest(n).index.tolist()

```

### 4. 因子持久化设计

```python

# backtrader/factor/storage.py

class FactorStorage(object):
    """因子存储"""

    def __init__(self, db_path='factors.db'):
        self.db_path = db_path
        self._conn = None

    def save(self, factor_name, timestamp, data):
        """保存因子值"""

# 实现数据库存储逻辑
        pass

    def load(self, factor_name, start=None, end=None):
        """加载因子值"""

# 实现数据库查询逻辑
        pass

    def exists(self, factor_name, timestamp):
        """检查因子值是否存在"""
        pass

```

### 5. 使用示例

#### 5.1 定义简单因子

```python
import backtrader as bt

class MaFactor(bt.FactorBase):
    params = (
        ('short_window', 5),
        ('long_window', 20),
    )

    def __init__(self):

# 创建 Transformer
        transformer = bt.factor.MaTransformer(
            windows=[self.p.short_window, self.p.long_window]
        )

        super().__init__(transformer=transformer)

    def _generate_targets(self):

# 金叉做多
        short_ma = self.factor_df[f'ma{self.p.short_window}']
        long_ma = self.factor_df[f'ma{self.p.long_window}']

        cross_up = (short_ma > long_ma) & (short_ma.shift(1) <= long_ma.shift(1))
        cross_down = (short_ma < long_ma) & (short_ma.shift(1) >= long_ma.shift(1))

        self.targets['long'] = cross_up[cross_up].index.tolist()
        self.targets['short'] = cross_down[cross_down].index.tolist()

```

#### 5.2 策略中使用因子

```python
class FactorStrategy(bt.Strategy):
    params = (
        ('factor', None),
        ('position_pct', 0.1),
    )

    def __init__(self):
        self.factor = self.p.factor

    def next(self):

# 获取因子目标
        long_targets = self.factor.get_targets(
            timestamp=self.datetime.date(),
            target_type='long'
        )

# 执行交易
        for target in long_targets:
            if self.getposition(target).size == 0:
                self.order_target_percent(
                    target,
                    target=self.p.position_pct
                )

```

### 6. 实施路线图

#### 阶段 1: 基础框架 (2-3 周)

- [ ] 创建 factor 包结构
- [ ] 实现 FactorBase 基类
- [ ] 实现 Transformer 基类和 MaTransformer
- [ ] 实现 Accumulator 基类
- [ ] 实现 Scorer 基类和基础 Scorer

#### 阶段 2: 数据接口 (1-2 周)

- [ ] 实现 DataFeedRegistry
- [ ] 为现有 DataFeed 添加 query 接口
- [ ] 实现 capabilities 定义

#### 阶段 3: 目标选择 (1 周)

- [ ] 实现 TargetSelector
- [ ] 集成到 FactorBase

#### 阶段 4: 持久化 (1-2 周)

- [ ] 实现 FactorStorage
- [ ] 支持 SQLite
- [ ] 增量更新逻辑

#### 阶段 5: 集成测试 (1 周)

- [ ] 编写测试用例
- [ ] 性能对比测试
- [ ] 文档更新

---
## 附录: 关键文件路径

### Backtrader 关键文件

- `cerebro.py`: 核心引擎
- `linebuffer.py`: Line 缓冲区实现
- `indicator.py`: Indicator 基类
- `strategy.py`: Strategy 基类
- `feed.py`: DataFeed 基类

### ZVT 关键文件

- `src/zvt/contract/factor.py`: Factor 系统核心
- `src/zvt/contract/schema.py`: Schema 系统
- `src/zvt/trader/trader.py`: 交易引擎
- `src/zvt/factors/technical_factor.py`: 技术因子实现
