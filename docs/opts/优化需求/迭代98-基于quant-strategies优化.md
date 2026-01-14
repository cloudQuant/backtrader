### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/quant-strategies
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### quant-strategies项目简介
quant-strategies是量化交易策略合集，具有以下核心特点：
- **策略合集**: 多种量化策略
- **学术策略**: 学术论文策略实现
- **因子策略**: 因子投资策略
- **动量策略**: 动量类策略
- **均值回归**: 均值回归策略
- **机器学习**: ML策略

### 重点借鉴方向
1. **策略分类**: 策略分类体系
2. **学术实现**: 学术策略实现
3. **因子构建**: 因子构建方法
4. **回测框架**: 回测框架设计
5. **策略评价**: 策略评价方法
6. **代码组织**: 代码组织方式

---

## 项目对比分析

### Backtrader vs Quant-Strategies

| 维度 | Backtrader | Quant-Strategies |
|------|-----------|------------------|
| **核心定位** | 通用回测框架 | 策略合集+回测框架 |
| **策略组织** | 用户自行管理 | 策略工厂模式统一管理 |
| **策略分类** | 无内置分类 | 技术/情绪/对冲/ML分类 |
| **学术策略** | 需自行实现 | 部分学术策略已实现 |
| **情绪指标** | 无内置 | 市场情绪策略 |
| **对冲系统** | 基础支持 | 多账户对冲系统 |
| **风险管理** | 基础止损 | ATR/动态回撤/波动率自适应 |
| **回测引擎** | Cerebro | 封装的BacktestEngine |
| **评价体系** | Analyzer分散 | 统一评价报告 |
| **强化学习** | 无 | FinRL框架集成 |

### Backtrader可借鉴的优势

1. **策略工厂模式**：统一管理和注册策略
2. **策略分类体系**：按类型组织策略
3. **市场情绪策略**：多维度情绪指标构建
4. **多账户对冲**：ETF+期货对冲系统
5. **增强的风险管理**：ATR自适应、动态止损
6. **统一评价报告**：完整的策略绩效报告
7. **强化学习集成**：RL策略框架

---

## 功能需求文档

### FR-01 策略工厂 [高优先级]

**描述**: 建立策略注册和管理机制

**需求**:
- FR-01.1 定义StrategyRegistry注册中心
- FR-01.2 策略自动发现和注册
- FR-01.3 策略元数据管理（名称、描述、分类）
- FR-01.4 策略参数元信息获取
- FR-01.5 策略实例化和配置

**验收标准**:
- 通过策略名称获取策略类
- 支持按分类查询策略
- 自动提取策略参数信息

### FR-02 策略分类体系 [中优先级]

**描述**: 建立策略分类和组织系统

**需求**:
- FR-02.1 定义策略分类枚举
- FR-02.2 策略标签系统
- FR-02.3 按分类浏览策略
- FR-02.4 策略搜索功能

**验收标准**:
- 支持5+种策略分类
- 可按分类和标签筛选
- 搜索结果准确

### FR-03 市场情绪策略 [高优先级]

**描述**: 实现市场情绪驱动的交易策略

**需求**:
- FR-03.1 情绪指标计算（涨跌比、换手率、波动率）
- FR-03.2 多维度情绪合成
- FR-03.3 动态情绪阈值
- FR-03.4 情绪状态识别（恐慌/贪婪/中性）
- FR-03.5 情绪驱动的仓位管理

**验收标准**:
- 支持5+种情绪指标
- 情绪状态识别准确率>60%
- 支持历史情绪分析

### FR-04 双动量策略 [中优先级]

**描述**: 实现绝对动量和相对动量策略

**需求**:
- FR-04.1 绝对动量计算
- FR-04.2 相对动量计算
- FR-04.3 动量合成得分
- FR-04.4 动量轮动逻辑
- FR-04.5 动量失效检测

**验收标准**:
- 支持多时间周期动量
- 动量轮动信号准确
- 支持多资产轮动

### FR-05 多账户对冲系统 [中优先级]

**描述**: 实现多账户协同和对冲功能

**需求**:
- FR-05.1 多账户管理
- FR-05.2 账户间资金分配
- FR-05.3 对冲比例计算
- FR-05.4 对冲信号触发
- FR-05.5 对冲效果评估

**验收标准**:
- 支持2+个独立账户
- 对冲比例自动计算
- 对冲效果可量化

### FR-06 增强风险管理 [高优先级]

**描述**: 实现动态风险管理系统

**需求**:
- FR-06.1 ATR自适应止损
- FR-06.2 动态回撤控制
- FR-06.3 波动率自适应仓位
- FR-06.4 跟踪止损
- FR-06.5 风险预算管理

**验收标准**:
- 支持5+种风险控制方法
- 止损触发准确
- 仓位调整及时

### FR-07 策略评价报告 [高优先级]

**描述**: 生成统一的策略绩效报告

**需求**:
- FR-07.1 收益指标（总收益、年化收益）
- FR-07.2 风险指标（夏普、最大回撤、波动率）
- FR-07.3 交易指标（胜率、盈亏比、SQN）
- FR-07.4 图表生成（净值曲线、回撤图）
- FR-07.5 报告导出（HTML/PDF/Excel）

**验收标准**:
- 包含15+项评价指标
- 图表美观清晰
- 支持多格式导出

### FR-08 强化学习策略框架 [低优先级]

**描述**: 集成强化学习交易策略

**需求**:
- FR-08.1 状态空间构建
- FR-08.2 动作空间定义
- FR-08.3 奖励函数设计
- FR-08.4 模型训练接口
- FR-08.5 模型推理集成

**验收标准**:
- 支持2+种RL算法
- 状态特征可配置
- 训练结果可复现

### FR-09 情绪指标库 [中优先级]

**描述**: 建立市场情绪指标计算库

**需求**:
- FR-09.1 涨跌比指标（ADR）
- FR-09.2 涨停跌停比
- FR-09.3 新高新低比
- FR-09.4 市场广度指标
- FR-09.5 投资者恐慌指数（VIX风格）

**验收标准**:
- 支持10+种情绪指标
- 计算性能优化
- 支持实时计算

### FR-10 回测引擎封装 [高优先级]

**描述**: 封装简化版的回测引擎

**需求**:
- FR-10.1 一键回测接口
- FR-10.2 参数配置简化
- FR-10.3 数据源自动适配
- FR-10.4 结果自动分析
- FR-10.5 批量回测支持

**验收标准**:
- 单次回测<5行代码
- 支持100+参数组合批量回测
- 结果格式统一

---

## 设计文档

### 1. 策略工厂设计

#### 1.1 策略注册中心

```python
from typing import Dict, Type, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
import backtrader as bt

class StrategyCategory(Enum):
    """策略分类"""
    TREND_FOLLOWING = "趋势跟踪"      # 趋势跟踪类策略
    MEAN_REVERSION = "均值回归"      # 均值回归类策略
    MOMENTUM = "动量策略"            # 动量类策略
    SENTIMENT = "情绪驱动"           # 情绪驱动策略
    HEDGING = "对冲策略"             # 对冲策略
    ML = "机器学习"                  # 机器学习策略
    ARBITRAGE = "套利策略"           # 套利策略
    MARKET_MAKING = "做市策略"       # 做市策略

@dataclass
class StrategyMetadata:
    """策略元数据"""
    name: str                          # 策略名称
    description: str                   # 策略描述
    category: StrategyCategory         # 策略分类
    author: str = ""                   # 作者
    version: str = "1.0.0"             # 版本
    tags: List[str] = field(default_factory=list)  # 标签
    parameters: Dict[str, Any] = field(default_factory=dict)  # 参数说明

class StrategyRegistry:
    """策略注册中心"""

    _strategies: Dict[str, Type[bt.Strategy]] = {}
    _metadata: Dict[str, StrategyMetadata] = {}

    @classmethod
    def register(cls, strategy_class: Type[bt.Strategy],
                metadata: StrategyMetadata):
        """注册策略"""
        cls._strategies[metadata.name] = strategy_class
        cls._metadata[metadata.name] = metadata

    @classmethod
    def get(cls, name: str) -> Optional[Type[bt.Strategy]]:
        """获取策略类"""
        return cls._strategies.get(name)

    @classmethod
    def get_metadata(cls, name: str) -> Optional[StrategyMetadata]:
        """获取策略元数据"""
        return cls._metadata.get(name)

    @classmethod
    def list_strategies(cls, category: StrategyCategory = None) -> List[str]:
        """列出策略"""
        if category is None:
            return list(cls._strategies.keys())
        return [
            name for name, meta in cls._metadata.items()
            if meta.category == category
        ]

    @classmethod
    def get_parameters(cls, name: str) -> Dict[str, Any]:
        """获取策略参数"""
        strategy_class = cls.get(name)
        if strategy_class is None:
            return {}

        params = getattr(strategy_class, 'params', ())
        return {
            name: {
                'default': value,
                'doc': f'Parameter {name}'
            }
            for name, value in params._getpairs()
        }

# 装饰器注册
def register_strategy(metadata: StrategyMetadata):
    """策略注册装饰器"""
    def decorator(cls: Type[bt.Strategy]):
        StrategyRegistry.register(cls, metadata)
        return cls
    return decorator
```

#### 1.2 策略工厂

```python
class StrategyFactory:
    """策略工厂"""

    def __init__(self, registry: StrategyRegistry = None):
        self.registry = registry or StrategyRegistry

    def create_strategy(self, name: str, **kwargs) -> bt.Strategy:
        """创建策略实例"""
        strategy_class = self.registry.get(name)
        if strategy_class is None:
            raise ValueError(f"Strategy {name} not found")

        # 验证参数
        params = self.registry.get_parameters(name)
        for key in kwargs:
            if key not in params:
                raise ValueError(f"Unknown parameter: {key}")

        return strategy_class(**kwargs)

    def create_strategy_with_config(self, name: str,
                                   config: Dict[str, Any]) -> bt.Strategy:
        """从配置创建策略"""
        return self.create_strategy(name, **config)

    def get_strategy_info(self, name: str) -> Dict[str, Any]:
        """获取策略完整信息"""
        metadata = self.registry.get_metadata(name)
        parameters = self.registry.get_parameters(name)

        return {
            'name': metadata.name if metadata else name,
            'description': metadata.description if metadata else '',
            'category': metadata.category.value if metadata else '',
            'parameters': parameters
        }

    def search_strategies(self, keyword: str) -> List[str]:
        """搜索策略"""
        results = []
        keyword = keyword.lower()

        for name, meta in self.registry._metadata.items():
            if (keyword in name.lower() or
                keyword in meta.description.lower() or
                any(keyword in tag.lower() for tag in meta.tags)):
                results.append(name)

        return results
```

### 2. 市场情绪策略设计

#### 2.1 情绪指标计算器

```python
import pandas as pd
import numpy as np
from typing import Dict, List, Optional

class SentimentCalculator:
    """市场情绪指标计算器"""

    @staticmethod
    def advance_decline_ratio(up_count: int, down_count: int) -> float:
        """
        计算涨跌比（ADR）

        Args:
            up_count: 上涨股票数量
            down_count: 下跌股票数量

        Returns:
            涨跌比值
        """
        if down_count == 0:
            return up_count if up_count > 0 else 1.0
        return up_count / down_count

    @staticmethod
    def limit_up_down_ratio(limit_up: int, limit_down: int) -> float:
        """计算涨跌停比"""
        if limit_down == 0:
            return limit_up if limit_up > 0 else 1.0
        return limit_up / limit_down

    @staticmethod
    def new_high_low_ratio(new_high: int, new_low: int) -> float:
        """计算新高新低比"""
        if new_low == 0:
            return new_high if new_high > 0 else 1.0
        return new_high / new_low

    @staticmethod
    def market_breadth(participation_rate: float) -> float:
        """
        市场广度指标

        Args:
            participation_rate: 参与度（上涨股票数/总股票数）

        Returns:
            市场广度值
        """
        return participation_rate * 100

    @staticmethod
    def volatility_sentiment(volatility: float,
                            vol_ma: float,
                            vol_threshold: float = 25.0) -> str:
        """
        基于波动率的情绪状态

        Args:
            volatility: 当前波动率
            vol_ma: 波动率均值
            vol_threshold: 高波动阈值

        Returns:
            情绪状态: 'extreme_fear', 'fear', 'neutral', 'greed', 'extreme_greed'
        """
        if volatility > vol_threshold:
            return 'extreme_fear'
        elif volatility > vol_ma * 1.5:
            return 'fear'
        elif volatility < vol_ma * 0.5:
            return 'extreme_greed'
        elif volatility < vol_ma * 0.8:
            return 'greed'
        else:
            return 'neutral'

    @staticmethod
    def composite_sentiment(indicators: Dict[str, float],
                           weights: Dict[str, float] = None) -> float:
        """
        综合情绪指数

        Args:
            indicators: 各情绪指标值
            weights: 指标权重

        Returns:
            综合情绪指数 (0-100, 50为中性)
        """
        if weights is None:
            weights = {
                'adr': 0.3,
                'limit_ratio': 0.2,
                'new_high_low': 0.2,
                'breadth': 0.15,
                'volatility': 0.15
            }

        # 归一化处理
        normalized = {}
        if 'adr' in indicators:
            # ADR > 3 为极度贪婪
            normalized['adr'] = min(indicators['adr'] / 3.0, 1.0) * 100
        if 'limit_ratio' in indicators:
            # 涨停比 > 2 为极度贪婪
            normalized['limit_ratio'] = min(indicators['limit_ratio'] / 2.0, 1.0) * 100
        if 'new_high_low' in indicators:
            # 新高新低比 > 3 为极度贪婪
            normalized['new_high_low'] = min(indicators['new_high_low'] / 3.0, 1.0) * 100
        if 'breadth' in indicators:
            # 直接使用百分比
            normalized['breadth'] = indicators['breadth']
        if 'volatility' in indicators:
            # 波动率反向（低波动=贪婪）
            normalized['volatility'] = max(100 - indicators['volatility'], 0)

        # 加权合成
        composite = sum(normalized.get(k, 50) * w
                       for k, w in weights.items())

        return composite

class MarketSentimentIndicator(bt.Indicator):
    """市场情绪技术指标"""

    lines = ('sentiment', 'adr', 'limit_ratio', 'breadth')
    params = (
        ('adr_window', 5),
        ('sentiment_threshold_low', 30),
        ('sentiment_threshold_high', 70),
    )

    plotinfo = dict(subplot=True)

    def __init__(self):
        # 计算各子指标
        self.calculator = SentimentCalculator()

        # 这里简化处理，实际需要从市场数据计算
        # 使用价格动量作为情绪的代理指标
        momentum = bt.indicators.ROC(self.data.close, period=self.p.adr_window)

        # 将动量转换为情绪值 (0-100)
        self.lines.sentiment = 50 + momentum / 2

    def next(self):
        # 情绪状态
        if self.lines.sentiment[0] < self.p.sentiment_threshold_low:
            self.state = 'fear'
        elif self.lines.sentiment[0] > self.p.sentiment_threshold_high:
            self.state = 'greed'
        else:
            self.state = 'neutral'
```

#### 2.2 市场情绪策略

```python
@register_strategy(StrategyMetadata(
    name="市场情绪策略",
    description="基于市场情绪指标的动态交易策略",
    category=StrategyCategory.SENTIMENT,
    tags=["情绪", "自适应", "多因子"],
    parameters={
        'sentiment_core': {'default': 40.0, 'doc': '核心情绪阈值'},
        'sentiment_secondary': {'default': 60.0, 'doc': '次级情绪阈值'},
        'momentum_short': {'default': 10, 'doc': '短期动量周期'},
        'momentum_long': {'default': 60, 'doc': '长期动量周期'},
        'vol_threshold': {'default': 20.0, 'doc': '高波动阈值'},
    }
))
class MarketSentimentStrategy(bt.Strategy):
    """市场情绪策略"""

    params = (
        # 情绪参数
        ('sentiment_core', 40.0),       # 核心情绪阈值
        ('sentiment_secondary', 60.0),  # 次级情绪阈值

        # 动量参数
        ('momentum_short', 10),
        ('momentum_long', 60),

        # 波动率参数
        ('vol_window', 20),
        ('vol_threshold', 20.0),
        ('garch_vol_threshold', 25.0),

        # 交易参数
        ('position_size', 0.95),
        ('risk_per_trade', 0.02),
        ('trail_percent', 2.0),
    )

    def __init__(self):
        # 情绪指标
        self.sentiment = MarketSentimentIndicator(self.data)

        # 动量指标
        self.mom_short = bt.indicators.Momentum(
            self.data.close, period=self.p.momentum_short
        )
        self.mom_long = bt.indicators.Momentum(
            self.data.close, period=self.p.momentum_long
        )

        # 波动率指标
        self.volatility = bt.indicators.StandardDeviation(
            self.data.close, period=self.p.vol_window
        )

        # 趋势确认
        self.ema_short = bt.indicators.EMA(self.data, period=20)
        self.ema_long = bt.indicators.EMA(self.data, period=60)
        self.trend = self.ema_short - self.ema_long

        # ATR止损
        self.atr = bt.indicators.ATR(self.data, period=14)

        # 订单追踪
        self.order = None
        self.entry_price = None
        self.stop_price = None

    def next(self):
        """主交易逻辑"""
        # 等待未完成订单
        if self.order:
            return

        # 没有持仓时寻找入场机会
        if not self.position:
            self._check_entry()
        else:
            self._check_exit()

    def _check_entry(self):
        """检查入场条件"""
        sentiment = self.sentiment.lines.sentiment[0]
        vol = self.volatility.lines.volatility[0]

        # 恐慌情绪 + 趋势向上 + 动量转正
        if (sentiment < self.p.sentiment_core and
            self.trend[0] > 0 and
            self.mom_short[0] > 0):

            self._enter_long()

        # 极度贪婪 + 趋势向下 + 动量转负
        elif (sentiment > self.p.sentiment_secondary and
              self.trend[0] < 0 and
              self.mom_short[0] < 0):

            self._enter_short()

    def _check_exit(self):
        """检查出场条件"""
        sentiment = self.sentiment.lines.sentiment[0]
        current_price = self.data.close[0]

        # 更新跟踪止损
        if self.entry_price:
            if self.position.size > 0:  # 多头
                self.stop_price = max(
                    self.stop_price or 0,
                    current_price * (1 - self.p.trail_percent / 100)
                )
            else:  # 空头
                self.stop_price = min(
                    self.stop_price or float('inf'),
                    current_price * (1 + self.p.trail_percent / 100)
                )

        # 情绪反转出场
        if self.position.size > 0:  # 多头持仓
            if sentiment > self.p.sentiment_secondary:
                self._close_position("情绪反转")
            elif current_price <= self.stop_price:
                self._close_position("跟踪止损")
        else:  # 空头持仓
            if sentiment < self.p.sentiment_core:
                self._close_position("情绪反转")
            elif current_price >= self.stop_price:
                self._close_position("跟踪止损")

    def _enter_long(self):
        """开多仓"""
        # 根据ATR计算仓位
        atr_value = self.atr.lines.atr[0]
        risk_amount = self.broker.getvalue() * self.p.risk_per_trade
        size = int(risk_amount / (atr_value * 2))

        self.order = self.buy(size=size)
        self.entry_price = self.data.close[0]
        self.stop_price = self.entry_price * (1 - self.p.trail_percent / 100)

    def _enter_short(self):
        """开空仓"""
        self.order = self.sell(size=self.broker.getvalue() * self.p.position_size /
                              self.data.close[0])
        self.entry_price = self.data.close[0]
        self.stop_price = self.entry_price * (1 + self.p.trail_percent / 100)

    def _close_position(self, reason: str):
        """平仓"""
        self.order = self.close()
        print(f"[{self.datas[0].datetime.date(0)}] 平仓: {reason}")

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            self.order = None
```

### 3. 双动量策略设计

```python
@register_strategy(StrategyMetadata(
    name="双动量轮动策略",
    description="基于绝对动量和相对动量的资产轮动策略",
    category=StrategyCategory.MOMENTUM,
    tags=["动量", "轮动", "多资产"],
))
class DualMomentumStrategy(bt.Strategy):
    """双动量策略"""

    params = (
        ('momentum_short', 12),   # 短期动量周期
        ('momentum_long', 126),   # 长期动量周期
        ('lookback', 252),        # 回望期
        ('top_n', 3),             # 选择Top N资产
        ('cash', 10000.0),
        ('commission', 0.001),
    )

    def __init__(self):
        # 为每个数据流计算动量
        self.inds = {}
        for d in self.datas:
            self.inds[d] = {}

            # 短期动量
            self.inds[d]['mom_short'] = bt.indicators.Momentum(
                d.close, period=self.p.momentum_short
            )

            # 长期动量
            self.inds[d]['mom_long'] = bt.indicators.Momentum(
                d.close, period=self.p.momentum_long
            )

            # 动量得分
            self.inds[d]['momentum_score'] = (
                self.inds[d]['mom_short'] /
                (abs(self.inds[d]['mom_long']) + 1e-6)
            )

            # 绝对动量（正收益）
            self.inds[d]['abs_momentum'] = (
                d.close / d.close(-self.p.lookback) - 1
            )

        self.rebalance_days = 20  # 每月调仓
        self.days_since_rebalance = 0

    def next(self):
        """主逻辑"""
        self.days_since_rebalance += 1

        # 调仓日
        if self.days_since_rebalance >= self.rebalance_days:
            self._rebalance()
            self.days_since_rebalance = 0

    def _rebalance(self):
        """执行调仓"""
        # 获取所有资产的动量得分
        scores = []
        for d in self.datas:
            if len(d) < self.p.lookback:
                continue

            abs_mom = self.inds[d]['abs_momentum'][0]
            mom_score = self.inds[d]['momentum_score'][0]

            # 绝对动量必须为正
            if abs_mom > 0:
                scores.append((d, mom_score))

        # 按动量得分排序，选择Top N
        scores.sort(key=lambda x: x[1], reverse=True)
        selected = scores[:self.p.top_n] if scores else []

        # 平仓不在选择中的资产
        for d in self.datas:
            if d not in [s[0] for s in selected]:
                self.close(data=d)

        # 等权配置选中的资产
        if selected:
            weight = 1.0 / len(selected)
            for d, _ in selected:
                target_value = self.broker.getvalue() * weight
                target_size = int(target_value / d.close[0])
                self.order_target_size(data=d, target=target_size)
```

### 4. 多账户对冲系统设计

```python
from typing import Dict, List
from dataclasses import dataclass

@dataclass
class AccountInfo:
    """账户信息"""
    name: str
    account_type: str  # 'stock', 'futures', 'etf'
    initial_cash: float
    cash: float = 0.0
    value: float = 0.0

class MultiAccountManager:
    """多账户管理器"""

    def __init__(self):
        self.accounts: Dict[str, AccountInfo] = {}
        self.hedge_ratio: float = 0.5  # 对冲比例
        self.hedge_threshold: float = 0.1  # 对冲触发阈值

    def add_account(self, name: str, account_type: str,
                   initial_cash: float):
        """添加账户"""
        self.accounts[name] = AccountInfo(
            name=name,
            account_type=account_type,
            initial_cash=initial_cash
        )

    def get_account(self, name: str) -> AccountInfo:
        """获取账户"""
        return self.accounts.get(name)

    def calculate_hedge_ratio(self, spot_account: str,
                             futures_account: str) -> float:
        """计算对冲比例"""
        spot = self.get_account(spot_account)
        futures = self.get_account(futures_account)

        if not spot or not futures:
            return 0.0

        spot_value = spot.value
        futures_value = futures.value

        # 目标对冲比例
        target_hedge = self.hedge_ratio * spot_value

        # 当前对冲比例
        current_hedge = abs(futures_value)

        # 计算调整比例
        if spot_value > 0:
            return target_hedge / spot_value
        return 0.0

class HedgingStrategy(bt.Strategy):
    """对冲策略基类"""

    params = (
        ('hedge_account', None),      # 对冲账户名称
        ('hedge_ratio', 0.5),         # 对冲比例
        ('rebalance_threshold', 0.1), # 再平衡阈值
    )

    def __init__(self):
        self.hedge_manager = MultiAccountManager()
        self.hedge_positions: Dict[str, float] = {}

    def next(self):
        """主逻辑"""
        # 获取现货账户总价值
        total_value = self.broker.getvalue()

        # 计算目标对冲仓位
        hedge_value = total_value * self.p.hedge_ratio

        # 当前对冲偏离
        current_hedge = sum(abs(pos) * price
                           for pos, price in self.hedge_positions.items())

        deviation = abs(current_hedge - hedge_value) / total_value

        # 超过阈值时调整
        if deviation > self.p.rebalance_threshold:
            self._rebalance_hedge(hedge_value)

    def _rebalance_hedge(self, target_value: float):
        """再平衡对冲仓位"""
        # 子类实现具体逻辑
        pass

@register_strategy(StrategyMetadata(
    name="双均线对冲策略",
    description="双均线策略与期货对冲结合",
    category=StrategyCategory.HEDGING,
    tags=["对冲", "双均线"],
))
class DualMAHedgingStrategy(HedgingStrategy):
    """双均线对冲策略"""

    params = (
        ('fast_period', 5),
        ('slow_period', 20),
        ('hedge_ratio', 0.5),
        ('hedge_symbol', 'IF300'),  # 对冲期货品种
    )

    def __init__(self):
        super().__init__()

        # 双均线
        self.fast_ma = bt.indicators.SMA(self.data, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        # 金叉开多
        if self.crossover[0] > 0:
            self._enter_hedge('short')  # 对冲空单

        # 死叉平仓
        elif self.crossover[0] < 0:
            self._exit_hedge()

    def _enter_hedge(self, direction: str):
        """开对冲仓位"""
        hedge_size = self.broker.getvalue() * self.p.hedge_ratio
        # 实际实现需要连接期货账户
        print(f"开对冲仓: {direction}, 数量: {hedge_size}")

    def _exit_hedge(self):
        """平对冲仓位"""
        print("平对冲仓")
```

### 5. 增强风险管理设计

```python
class EnhancedRiskManager:
    """增强风险管理器"""

    def __init__(self, strategy: bt.Strategy):
        self.strategy = strategy
        self.peak_value = strategy.broker.getvalue()
        self.max_drawdown = 0.15

    def check_drawdown(self) -> bool:
        """检查回撤是否超限"""
        current_value = self.strategy.broker.getvalue()

        # 更新峰值
        if current_value > self.peak_value:
            self.peak_value = current_value
            return False

        # 计算回撤
        drawdown = (self.peak_value - current_value) / self.peak_value

        # 超过最大回撤，停止交易
        if drawdown > self.max_drawdown:
            return True

        return False

    def calculate_position_size(self, entry_price: float,
                               stop_price: float) -> int:
        """基于ATR的仓位计算"""
        atr = self.strategy.atr[0]
        account_value = self.strategy.broker.getvalue()
        risk_ratio = 0.02  # 单笔风险2%

        # 风险金额
        risk_amount = account_value * risk_ratio

        # 止损距离
        stop_distance = abs(entry_price - stop_price)
        if stop_distance == 0:
            stop_distance = atr * 2

        # 计算仓位
        size = int(risk_amount / stop_distance)

        return size

class TrailingStop(bt.Indicator):
    """跟踪止损指标"""

    lines = ('stop', 'direction')
    params = (('trail_percent', 2.0),)

    plotinfo = dict(subplot=False)

    def __init__(self):
        self.direction = 1  # 1 for long, -1 for short
        self.high_since_entry = self.data.close[0]
        self.low_since_entry = self.data.close[0]

    def next(self):
        price = self.data.close[0]

        # 更新极值
        self.high_since_entry = max(self.high_since_entry, price)
        self.low_since_entry = min(self.low_since_entry, price)

        # 根据方向计算止损
        if self.direction == 1:  # 多头
            self.lines.stop[0] = price * (1 - self.p.trail_percent / 100)
        else:  # 空头
            self.lines.stop[0] = price * (1 + self.p.trail_percent / 100)

class VolatilityAdjustedSizer(bt.Sizer):
    """波动率调整仓位器"""

    params = (('vol_period', 20), ('target_vol', 0.15))

    def _getsizing(self, data, broker):
        # 计算目标仓位
        vol = bt.indicators.StandardDeviation(
            data, period=self.p.vol_period
        )

        target_size = (self.p.target_vol / (vol[0] + 1e-6))

        # 限制仓位范围
        target_size = min(max(target_size, 0.3), 1.0)

        account_value = broker.getvalue()
        return int(account_value * target_size / data.close[0])
```

### 6. 策略评价报告设计

```python
from typing import Dict, Any, Optional
import pandas as pd
from datetime import datetime

class StrategyReport:
    """策略评价报告生成器"""

    def __init__(self, strategy_results):
        self.results = strategy_results
        self.strat = strategy_results[0]

    def generate_metrics(self) -> Dict[str, Any]:
        """生成评价指标"""
        # 获取各个analyzer的结果
        sharpe = self.strat.analyzers.sharpe.get_analysis()
        drawdown = self.strat.analyzers.drawdown.get_analysis()
        returns = self.strat.analyzers.returns.get_analysis()
        trades = self.strat.analyzers.trades.get_analysis()
        sqn = self.strat.analyzers.sqn.get_analysis()

        return {
            # 收益指标
            'total_return': returns.get('rtot', 0),
            'annualized_return': returns.get('rnorm', 0) * 100,
            'avg_monthly_return': returns.get('ravg', 0) * 100,

            # 风险指标
            'sharpe_ratio': sharpe.get('sharperatio', 0),
            'max_drawdown': drawdown.get('max', {}).get('drawdown', 0),
            'max_drawdown_duration': drawdown.get('max', {}).get('len', 0),
            'annual_volatility': returns.get('rnorm', 0),

            # 交易指标
            'total_trades': trades.get('total', {}).get('total', 0),
            'win_rate': self._calculate_win_rate(trades),
            'profit_factor': self._calculate_profit_factor(trades),
            'avg_trade_return': self._calculate_avg_trade(trades),
            'sqn': sqn.get('sqn', 0),
        }

    def _calculate_win_rate(self, trades: Dict) -> float:
        """计算胜率"""
        total = trades.get('total', {}).get('total', 0)
        won = trades.get('won', {}).get('total', 0)
        if total == 0:
            return 0.0
        return won / total * 100

    def _calculate_profit_factor(self, trades: Dict) -> float:
        """计算盈亏比"""
        won = trades.get('won', {}).get('pnl', {}).get('total', 0)
        lost = trades.get('lost', {}).get('pnl', {}).get('total', 0)
        if lost == 0:
            return float('inf') if won > 0 else 0.0
        return abs(won / lost)

    def _calculate_avg_trade(self, trades: Dict) -> float:
        """计算平均交易收益"""
        total = trades.get('total', {}).get('total', 0)
        pnl_total = trades.get('total', {}).get('pnl', {}).get('total', 0)
        if total == 0:
            return 0.0
        return pnl_total / total

    def generate_dataframe(self) -> pd.DataFrame:
        """生成结果DataFrame"""
        # 获取净值曲线
        values = self.strat.stats.broker.value
        dates = self.strat.stats.broker.value_idx

        df = pd.DataFrame({
            'date': dates,
            'portfolio_value': values,
            'returns': pd.Series(values).pct_change()
        })

        return df

    def generate_html_report(self, output_path: str):
        """生成HTML报告"""
        metrics = self.generate_metrics()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>策略回测报告</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .metric {{ display: inline-block; margin: 10px; padding: 15px;
                          background: #f0f0f0; border-radius: 5px; min-width: 150px; }}
                .metric-value {{ font-size: 24px; font-weight: bold; }}
                .metric-label {{ color: #666; font-size: 14px; }}
                h1 {{ color: #333; }}
                h2 {{ color: #666; border-bottom: 2px solid #ddd; padding-bottom: 10px; }}
            </style>
        </head>
        <body>
            <h1>策略回测报告</h1>
            <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

            <h2>收益指标</h2>
            <div class="metric">
                <div class="metric-value">{metrics['total_return']:.2%}</div>
                <div class="metric-label">总收益率</div>
            </div>
            <div class="metric">
                <div class="metric-value">{metrics['annualized_return']:.2f}%</div>
                <div class="metric-label">年化收益率</div>
            </div>

            <h2>风险指标</h2>
            <div class="metric">
                <div class="metric-value">{metrics['sharpe_ratio']:.2f}</div>
                <div class="metric-label">夏普比率</div>
            </div>
            <div class="metric">
                <div class="metric-value">{metrics['max_drawdown']:.2%}</div>
                <div class="metric-label">最大回撤</div>
            </div>

            <h2>交易指标</h2>
            <div class="metric">
                <div class="metric-value">{metrics['total_trades']}</div>
                <div class="metric-label">总交易次数</div>
            </div>
            <div class="metric">
                <div class="metric-value">{metrics['win_rate']:.1f}%</div>
                <div class="metric-label">胜率</div>
            </div>
            <div class="metric">
                <div class="metric-value">{metrics['profit_factor']:.2f}</div>
                <div class="metric-label">盈亏比</div>
            </div>
            <div class="metric">
                <div class="metric-value">{metrics['sqn']:.2f}</div>
                <div class="metric-label">系统质量指数</div>
            </div>
        </body>
        </html>
        """

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
```

### 7. 回测引擎封装设计

```python
class BacktestEngine:
    """简化版回测引擎"""

    def __init__(self, initial_cash: float = 100000.0,
                 commission: float = 0.00025):
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash)
        self.cerebro.broker.setcommission(commission)

        # 默认分析器
        self._setup_default_analyzers()

    def _setup_default_analyzers(self):
        """设置默认分析器"""
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

    def add_data(self, data, name: str = None):
        """添加数据"""
        self.cerebro.adddata(data, name=name)

    def add_strategy(self, strategy_class, **kwargs):
        """添加策略"""
        self.cerebro.addstrategy(strategy_class, **kwargs)

    def run(self) -> 'StrategyReport':
        """运行回测"""
        print(f'初始资金: {self.cerebro.broker.getvalue():.2f}')

        results = self.cerebro.run()

        print(f'最终资金: {self.cerebro.broker.getvalue():.2f}')
        print(f'收益率: {(self.cerebro.broker.getvalue() /
                           self.cerebro.broker.startingcash - 1) * 100:.2f}%')

        return StrategyReport(results)

    def plot(self, **kwargs):
        """绘图"""
        self.cerebro.plot(**kwargs)

# 快速回测函数
def quick_backtest(strategy_name: str,
                  data_feeds: List[bt.feed.Feed],
                  strategy_params: Dict = None,
                  initial_cash: float = 100000.0) -> StrategyReport:
    """
    快速回测函数

    Args:
        strategy_name: 策略名称
        data_feeds: 数据源列表
        strategy_params: 策略参数
        initial_cash: 初始资金

    Returns:
        策略报告
    """
    # 获取策略类
    strategy_class = StrategyRegistry.get(strategy_name)
    if strategy_class is None:
        raise ValueError(f"策略 {strategy_name} 未找到")

    # 创建回测引擎
    engine = BacktestEngine(initial_cash=initial_cash)

    # 添加数据
    for feed in data_feeds:
        engine.add_data(feed)

    # 添加策略
    params = strategy_params or {}
    engine.add_strategy(strategy_class, **params)

    # 运行回测
    return engine.run()
```

### 8. 强化学习策略框架设计

```python
import gym
from gym import spaces
import numpy as np

class TradingEnv(gym.Env):
    """交易环境"""

    metadata = {'render.modes': ['human']}

    def __init__(self, data: pd.DataFrame, initial_balance: float = 10000):
        super().__init__()

        self.data = data
        self.initial_balance = initial_balance
        self.current_step = 0

        # 动作空间: 0=持有, 1=买入, 2=卖出
        self.action_space = spaces.Discrete(3)

        # 状态空间: [价格特征, 技术指标, 持仓状态]
        n_features = 10
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(n_features,), dtype=np.float32
        )

        # 账户状态
        self.balance = initial_balance
        self.shares = 0
        self.total_shares_bought = 0
        self.total_shares_sold = 0

    def step(self, action):
        """执行动作"""
        # 获取当前价格
        price = self.data.iloc[self.current_step]['close']

        # 执行动作
        if action == 1:  # 买入
            shares_to_buy = int(self.balance / price)
            self.balance -= shares_to_buy * price
            self.shares += shares_to_buy
            self.total_shares_bought += shares_to_buy
        elif action == 2:  # 卖出
            self.balance += self.shares * price
            self.shares = 0
            self.total_shares_sold += self.shares

        # 移动到下一步
        self.current_step += 1
        done = self.current_step >= len(self.data) - 1

        # 计算奖励
        current_price = self.data.iloc[self.current_step]['close']
        portfolio_value = self.balance + self.shares * current_price
        reward = (portfolio_value - self.initial_balance) / self.initial_balance

        # 获取新状态
        obs = self._get_observation()

        return obs, reward, done, {}

    def reset(self):
        """重置环境"""
        self.current_step = 0
        self.balance = self.initial_balance
        self.shares = 0
        return self._get_observation()

    def _get_observation(self) -> np.ndarray:
        """获取观察状态"""
        row = self.data.iloc[self.current_step]

        # 价格特征
        price_norm = row['close'] / self.data['close'].max()

        # 技术指标
        sma_short = row['close'] / self.data['close'].rolling(20).mean().iloc[self.current_step]
        sma_long = row['close'] / self.data['close'].rolling(60).mean().iloc[self.current_step]

        # 持仓状态
        position_ratio = (self.shares * row['close']) / self.initial_balance

        return np.array([
            price_norm,
            sma_short,
            sma_long,
            position_ratio,
            # ...更多特征
        ], dtype=np.float32)

class RLTradingStrategy(bt.Strategy):
    """强化学习交易策略"""

    params = (
        ('model_path', None),
        ('state_window', 30),
    )

    def __init__(self):
        self.model = None
        self.state_window = self.p.state_window

        # 加载模型
        if self.p.model_path:
            self._load_model()

    def _load_model(self):
        """加载训练好的模型"""
        # 使用stable-baselines3或其他RL库
        from stable_baselines3 import PPO
        self.model = PPO.load(self.p.model_path)

    def _get_state(self) -> np.ndarray:
        """构建状态空间"""
        # 收集最近N根bar的数据
        states = []
        for i in range(-self.state_window, 0):
            states.append([
                self.data.open[i],
                self.data.high[i],
                self.data.low[i],
                self.data.close[i],
                self.data.volume[i],
            ])

        # 添加技术指标
        states[-1].extend([
            self.inds['ema_short'][0],
            self.inds['ema_long'][0],
            self.inds['rsi'][0],
            self.inds['macd'][0],
        ])

        # 添加账户状态
        position = self.position.size / self.broker.getvalue() if self.position else 0
        states[-1].append(position)

        return np.array(states, dtype=np.float32).flatten()

    def next(self):
        """主逻辑"""
        if self.model is None:
            return

        # 获取当前状态
        state = self._get_state()

        # 模型预测
        action, _ = self.model.predict(state)

        # 执行动作
        if action == 1 and not self.position:
            self.buy()
        elif action == 2 and self.position:
            self.sell()
```

---

## 实施计划

### 第一阶段：策略工厂（1周）

1. 实现StrategyRegistry注册中心
2. 实现StrategyFactory工厂类
3. 实现策略元数据管理
4. 单元测试

### 第二阶段：市场情绪策略（2周）

1. 实现SentimentCalculator
2. 实现MarketSentimentIndicator
3. 实现MarketSentimentStrategy
4. 回测验证

### 第三阶段：风险管理增强（1周）

1. 实现EnhancedRiskManager
2. 实现TrailingStop指标
3. 实现VolatilityAdjustedSizer
4. 集成测试

### 第四阶段：多账户对冲（2周）

1. 实现MultiAccountManager
2. 实现HedgingStrategy基类
3. 实现DualMAHedgingStrategy
4. 对冲效果评估

### 第五阶段：报告和回测引擎（1周）

1. 实现StrategyReport
2. 实现BacktestEngine封装
3. HTML报告生成
4. 集成测试

### 第六阶段：强化学习框架（2周）

1. 实现TradingEnv环境
2. 实现RLTradingStrategy
3. FinRL集成
4. 示例和文档

---

## API兼容性保证

1. **策略继承自bt.Strategy**：所有策略保持原有接口
2. **指标继承自bt.Indicator**：所有指标保持原有接口
3. **分析器使用原生接口**：不改变analyzer使用方式
4. **新增功能独立模块**：不影响现有代码

---

## 使用示例

### 示例1：使用策略工厂

```python
from backtrader.strategy_factory import StrategyRegistry, StrategyFactory

# 列出所有策略
strategies = StrategyRegistry.list_strategies()
print("可用策略:", strategies)

# 按分类查询
trend_strategies = StrategyRegistry.list_strategies(
    StrategyCategory.TREND_FOLLOWING
)

# 获取策略信息
factory = StrategyFactory()
info = factory.get_strategy_info("市场情绪策略")
print(info)

# 创建策略
strategy = factory.create_strategy(
    "市场情绪策略",
    sentiment_core=35.0,
    momentum_short=12
)
```

### 示例2：快速回测

```python
from backtrader.backtest_engine import quick_backtest

# 加载数据
data = bt.feeds.PandasData(dataname=df)

# 一行代码回测
report = quick_backtest(
    strategy_name="市场情绪策略",
    data_feeds=[data],
    strategy_params={'sentiment_core': 40.0},
    initial_cash=100000
)

# 生成报告
metrics = report.generate_metrics()
print(f"夏普比率: {metrics['sharpe_ratio']:.2f}")
report.generate_html_report('report.html')
```

### 示例3：情绪策略使用

```python
cerebro = bt.Cerebro()

# 添加数据
cerebro.adddata(data)

# 添加情绪策略
cerebro.addstrategy(
    MarketSentimentStrategy,
    sentiment_core=40.0,
    sentiment_secondary=60.0,
    momentum_short=10,
    momentum_long=60,
    trail_percent=2.0
)

# 运行
results = cerebro.run()
```

### 示例4：多账户对冲

```python
# 现货账户
cerebro_spot = bt.Cerebro()
cerebro_spot.addstrategy(
    DualMAHedgingStrategy,
    fast_period=5,
    slow_period=20,
    hedge_ratio=0.5
)

# 期货账户（对冲）
cerebro_futures = bt.Cerebro()
# ... 添加期货数据

# 运行对冲策略
# ...
