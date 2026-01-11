### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/abu
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### abu项目简介
abu是一个Python量化交易框架，专注于A股市场，具有以下核心特点：
- **机器学习集成**: 深度集成机器学习算法
- **因子挖掘**: 自动化因子挖掘和分析
- **回测分析**: 详细的回测结果分析
- **择时策略**: 多种择时策略实现
- **选股系统**: 完善的选股框架
- **教学友好**: 丰富的文档和教程

### 重点借鉴方向
1. **因子框架**: AbuFactor因子计算框架
2. **择时系统**: 择时策略的模块化设计
3. **机器学习**: ML模型集成方式
4. **回测分析**: 回测结果的详细分析
5. **滑点模型**: 滑点建模方法
6. **仓位管理**: 仓位控制策略

---

## 一、项目对比分析

### 1.1 abu 项目核心特性

| 特性 | 描述 |
|------|------|
| **因子框架** | AbuFactorBuyBase/AbuFactorSellBase 买入/卖出因子基类 |
| **方向混入** | BuyCallMixin/BuyPutMixin 混入模式 |
| **仓位管理** | AbuAtrPosition/AbuKellyPosition/AbuPtPosition |
| **滑点模型** | AbuSlippageBuyMean/AbuSlippageSellMean 概率模型 |
| **UMP系统** | 机器学习拦截决策系统 |
| **选股因子** | AlphaBu 选股模块 |
| **指标封装** | AbuND* 系列技术指标 |
| **回测度量** | AbuMetricsBase 完整度量体系 |

### 1.2 backtrader 现有能力对比

| 能力 | backtrader | abu | 差距 |
|------|-----------|-----|------|
| **策略模块** | Strategy 类 | 因子基类 + 混入 | abu 更模块化 |
| **仓位管理** | sizer | PositionBase 多种策略 | abu 更丰富 |
| **滑点** | SlippageFixed/Percent | 概率模型 | abu 更精细化 |
| **机器学习** | 无 | UMP 系统 | backtrader 缺少 |
| **指标系统** | indicators | AbuND* | 两者相似 |

### 1.3 差距分析

| 方面 | abu | backtrader | 差距 |
|------|-----|-----------|------|
| **因子化** | 买入/卖出因子独立 | Strategy 集成 | backtrader 可因子化 |
| **方向策略** | Mixin 模式 | 无明确区分 | backtrader 可借鉴 |
| **仓位管理** | 多种动态仓位 | sizer 有限 | backtrader 可扩展 |
| **滑点模型** | 概率成交 | 固定滑点 | backtrader 可改进 |
| **ML集成** | UMP 拦截系统 | 无 | backtrader 可添加 |

---

## 二、需求规格文档

### 2.1 功能需求

#### FR1: 因子策略系统
创建独立的买入/卖出因子：

- **FR1.1**: FactorBuyBase - 买入因子基类
- **FR1.2**: FactorSellBase - 卖出因子基类
- **FR1.3**: DirectionMixin - 方向混入类（Call/Put）
- **FR1.4**: 因子组合和参数配置

#### FR2: 动态仓位管理
更丰富的仓位管理策略：

- **FR2.1**: ATRPosition - 基于ATR的动态仓位
- **FR2.2**: KellyPosition - 凯利公式仓位
- **FR2.3**: RiskParityPosition - 风险平价仓位
- **FR2.4**: 动态调整机制

#### FR3: 概率滑点模型
更真实的滑点建模：

- **FR3.1**: 涨停板特殊处理
- **FR3.2**: 二项分布成交概率
- **FR3.3**: 价格区间内分布成交
- **FR3.4**: 多档位滑点

#### FR4: 机器学习拦截
UMP 风控拦截系统：

- **FR4.1**: EdgeModel - 边缘拦截模型
- **FR4.2**: MainModel - 主决策模型
- **FR4.3**: 特征工程自动化
- **FR4.4**: 模型训练和预测

### 2.2 非功能需求

- **NFR1**: 性能 - 因子系统不能显著降低回测速度
- **NFR2**: 兼容性 - 与现有 backtrader API 兼容
- **FR3**: 可扩展性 - 易于添加新因子和策略
- **NFR4**: 可选性 - 所有新功能为可选

### 2.3 用户故事

| ID | 故事描述 | 优先级 |
|----|---------|--------|
| US1 | 作为量化研究员，我想使用因子化的方式构建策略，便于组合和复用 | P0 |
| US2 | 作为风控经理，我想使用动态仓位管理，根据市场波动调整仓位 | P0 |
| US3 | 作为策略开发者，我想使用更真实的滑点模型，提高回测准确性 | P1 |
| US4 | 作为分析师，我想使用机器学习拦截交易信号，提高策略表现 | P1 |

---

## 三、设计文档

### 3.1 模块结构设计

```
backtrader/
├── factors/                   # 新增因子模块
│   ├── __init__.py
│   ├── base.py                # 因子基类
│   ├── buy.py                 # 买入因子
│   └── sell.py                # 卖出因子
├── position/                   # 新增仓位管理模块
│   ├── __init__.py
│   ├── base.py                # 仓位基类
│   ├── atr.py                 # ATR仓位
│   ├── kelly.py               # 凯利仓位
│   └── riskparity.py          # 风险平价仓位
├── slippage/                   # 增强滑点模块
│   ├── __init__.py
│   └── probability.py          # 概率滑点模型
└── ml/                         # 新增机器学习模块
    ├── __init__.py
    ├── edge.py                 # 边缘模型
    ├── main.py                # 主模型
    └── feature.py             # 特征工程
```

### 3.2 核心类设计

#### 3.2.1 因子基类

```python
"""
因子策略基类

参考：abu/abupy/FactorBuyBu/ABuFactorBuyBase.py
"""
from abc import ABCMeta, abstractmethod
from enum import Enum


class Direction(Enum):
    """交易方向"""
    CALL = 1.0   # 看涨
    PUT = -1.0    # 看跌


class CallMixin:
    """看涨混入类"""

    @property
    def direction_type(self) -> str:
        return "call"

    @property
    def expect_direction(self) -> float:
        return Direction.CALL.value


class PutMixin:
    """看跌混入类"""

    @property
    def direction_type(self) -> str:
        return "put"

    @property
    def expect_direction(self) -> float:
        return Direction.PUT.value


class FactorBuyBase:
    """买入因子基类

    参考：AbuFactorBuyBase
    每个买入因子必须混入一个方向类（CallMixin 或 PutMixin）
    """

    def __init__(self, data, **kwargs):
        self.data = data
        self._init_self(**kwargs)

    def _init_self(self, **kwargs):
        """子类初始化"""
        pass

    def fit_day(self, today_index):
        """计算买入信号

        Args:
            today_index: 当前交易日索引

        Returns:
            bool: 是否买入
        """
        raise NotImplementedError

    def create_order(self, size):
        """创建订单"""
        from backtrader.order import Order
        return Order(
            size=size,
            exectype=self._get_order_type(),
            direction=self._get_order_direction()
        )

    def _get_order_type(self):
        return Order.Market

    def _get_order_direction(self):
        if hasattr(self, 'expect_direction'):
            if self.expect_direction > 0:
                return Order.Buy
            else:
                return Order.Sell
        return Order.Buy


class FactorSellBase:
    """卖出因子基类

    参考：AbuFactorSellBase
    卖出因子可同时支持 CALL 和 PUT 方向
    """

    def __init__(self, strategy, **kwargs):
        self.strategy = strategy
        self._init_self(**kwargs)

    def _init_self(self, **kwargs):
        """子类初始化"""
        pass

    def support_direction(self) -> list:
        """支持的方向列表

        Returns:
            list: [Direction.CALL, Direction.PUT] 或只包含一个
        """
        return [Direction.CALL, Direction.PUT]

    def fit_day(self, today_index, order):
        """计算卖出信号

        Args:
            today_index: 当前交易日索引
            order: 待检查的订单

        Returns:
            bool: 是否卖出
        """
        raise NotImplementedError
```

#### 3.2.2 ATR 仓位管理

```python
"""
ATR 动态仓位管理

参考：abu/abupy/BetaBu/ABuAtrPosition.py
"""
import backtrader as bt
from backtrader.indicators import ATR


class ATRPosition(bt.Sizer):
    """基于 ATR 的动态仓位管理

    参考：AbuAtrPosition
    仓位大小与 ATR 成反比，波动越大仓位越小
    """

    params = (
        ('atr_period', 14),       # ATR 周期
        ('atr_base_price', 20),   # 基准价格
        ('atr_pos_base', 0.5),    # 基准仓位比例
        ('pos_max', 0.75),         # 最大仓位比例
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.atr = ATR(self.data, period=self.p.atr_period)

    def _getsizing(self, comminfo, cash, data, isbuy):
        """计算仓位大小

        Args:
            comminfo: 佣金信息
            cash: 可用资金
            data: 数据对象
            isbuy: 是否买入

        Returns:
            float: 仓位大小（股数）
        """
        if len(self.atr) < self.p.atr_period:
            return 0

        # 获取当前价格和 ATR
        price = data.close[0]
        atr = self.atr[0]

        if atr == 0:
            return 0

        # 计算基准单位的 ATR 比例
        atr_rate = (price * self.p.atr_base_price) / atr

        # 计算目标仓位比例
        target_pos = self.p.atr_pos_base * atr_rate
        target_pos = min(target_pos, self.p.pos_max)

        # 计算可买入的股数
        risk_cash = cash * target_pos
        shares = int(risk_cash / price)

        return shares


class KellyPosition(bt.Sizer):
    """凯利公式仓位管理

    参考：AbuKellyPosition
    凯利公式：f = (bp - sl) / (b - sl)
    f: 仓位比例
    bp: 胜率（赢的概率）
    sl: 赔率（输的概率）
    b: 赔赔比
    """

    params = (
        ('win_rate', 0.6),       # 预期胜率
        ('avg_win', 1.0),        # 平均盈利
        ('avg_loss', 1.0),       # 平均亏损
        ('pos_max', 0.75),        # 最大仓位比例
    )

    def _getsizing(self, comminfo, cash, data, isbuy):
        """计算凯利公式仓位"""
        # 凯利公式
        win_rate = max(min(self.p.win_rate, 0.99), 0.01)
        loss_rate = 1 - win_rate

        if self.p.avg_loss == 0:
            kelly_f = win_rate
        else:
            # b = avg_win / avg_loss
            win_loss_ratio = self.p.avg_win / self.p.avg_loss
            kelly_f = (win_rate * win_loss_ratio - loss_rate) / win_loss_ratio

        kelly_f = max(min(kelly_f, self.p.pos_max), 0)

        # 计算可买入的股数
        risk_cash = cash * kelly_f
        shares = int(risk_cash / data.close[0])

        return shares
```

#### 3.2.3 概率滑点模型

```python
"""
概率滑点模型

参考：abu/abupy/SlippageBu
"""
import backtrader as bt
import numpy as np


class ProbabilitySlippage(bt.Slippage.SlippageBase):
    """概率滑点模型

    参考：AbuSlippageBuyMean
    模拟真实交易中的成交概率，特别是在涨停板等特殊情况下
    """

    params = (
        ('deal_prob', 1.0),      # 成交概率
        ('limit_up_deal_chance', 0.5),  # 涨停板成交概率
    )

    def _get_price_slippage(self, price, isbuy):
        """获取滑点价格

        使用二项分布模拟成交概率
        """
        # 检查是否涨停板
        is_limit_up = self._check_limit_up(price)

        # 确定成交概率
        if is_limit_up:
            deal_chance = self.p.limit_up_deal_chance
        else:
            deal_chance = self.p.deal_prob

        # 二项分布决定是否成交
        deal = np.random.binomial(1, deal_chance)

        if deal == 0:
            # 未成交，返回 None 或滑点价格
            slippage_price = price * (1.01 if isbuy else 0.99)
        else:
            # 成交，返回原价
            slippage_price = price

        return slippage_price

    def _check_limit_up(self, price):
        """检查是否涨停"""
        # 检查价格是否达到涨停限制
        # 这里简化处理，实际需要根据涨跌停板规则
        return False


class MultiLevelSlippage(bt.CommInfo):
    """多档位滑点模型

    模拟真实的订单簿成交情况
    """

    def __init__(self):
        pass

    def get_slippage_info(self, order):
        """获取滑点信息

        Returns:
            dict: 包含成交价、成交量等信息
        """
        # 模拟订单簿
        order_book = self._get_order_book(order)

        # 计算成交价和成交量
        result = self._match_order(order, order_book)

        return result

    def _get_order_book(self, order):
        """获取模拟订单簿"""
        # 这里简化处理，实际需要根据历史数据构建
        return {
            'bid': [(order.created.price * 0.999, 1000),
                  (order.created.price * 0.998, 2000),
                  (order.created.price * 0.997, 3000)],
            'ask': [(order.created.price * 1.001, 1000),
                  (order.created.price * 1.002, 2000),
                  (order.created.price * 1.003, 3000)]
        }

    def _match_order(self, order, order_book):
        """撮合订单"""
        if order.isbuy():
            # 买入单，使用 ask 价格
            for price, volume in order_book['ask']:
                if volume >= order.size:
                    return {'price': price, 'volume': order.size}
                else:
                    order.size -= volume
        else:
            # 卖出单，使用 bid 价格
            for price, volume in order_book['bid']:
                if volume >= order.size:
                    return {'price': price, 'volume': order.size}
                else:
                    order.size -= volume

        return {'price': order.created.price, 'volume': order.size}
```

#### 3.2.4 机器学习拦截系统

```python
"""
机器学习拦截系统

参考：abu/abupy/UmpBu
"""
from abc import ABC, abstractmethod
import numpy as np


class EdgeModel:
    """边缘拦截模型

    参考：AbuUmpEdgeDeg/AbuUmpPrice/AbuUmpWave
    针对特定交易信号进行拦截
    """

    def __init__(self, model_type='price'):
        """
        Args:
            model_type: 模型类型 ('price', 'deg', 'wave')
        """
        self.model_type = model_type
        self.model = None

    def train(self, features, labels):
        """训练模型

        Args:
            features: 特征数据
            labels: 标签数据（1: 通过, 0: 拦截）
        """
        # 这里可以使用 sklearn 或其他 ML 库
        from sklearn.ensemble import RandomForestClassifier

        self.model = RandomForestClassifier()
        self.model.fit(features, labels)

    def predict(self, features):
        """预测是否拦截

        Args:
            features: 交易特征

        Returns:
            bool: True 表示拦截，False 表示通过
        """
        if self.model is None:
            return False

        prob = self.model.predict_proba(features)
        return prob[0][1] < 0.5  # 如果通过概率小于0.5，则拦截

    def extract_features(self, data, order):
        """提取特征

        Args:
            data: 当前数据
            order: 订单信息

        Returns:
            np.array: 特征向量
        """
        features = []

        if self.model_type == 'price':
            # 价格相关特征
            features.append(data.close[0] / data.close[-1] - 1)
            features.append(data.close[0] / data.close[-5] - 1)
            features.append(data.close[0] / data.close[-10] - 1)
            features.append(data.close[0] / data.close[-20] - 1)

        elif self.model_type == 'deg':
            # 角度特征
            features.append(np.degrees(np.arctan2(
                data.close[0] - data.close[-5],
                5
            )))

        elif self.model_type == 'wave':
            # 波动特征
            returns = np.log(data.close[1:] / data.close[:-1])
            features.append(np.std(returns[-20:]))
            features.append(np.mean(returns[-5:]))

        return np.array(features).reshape(1, -1)


class MainModel:
    """主决策模型

    参考：AbuUmpMainDeg/AbuUmpMainPrice/AbuUmpMainWave
    综合多个边缘模型的决策
    """

    def __init__(self):
        self.edge_models = []

    def add_edge_model(self, edge_model):
        """添加边缘模型"""
        self.edge_models.append(edge_model)

    def predict(self, features_dict):
        """综合预测

        Args:
            features_dict: 各模型的特征字典

        Returns:
            bool: True 表示拦截，False 表示通过
        """
        # 综合多个边缘模型的决策
        block_count = 0

        for model, features in zip(self.edge_models, features_dict.values()):
            if model.predict(features):
                block_count += 1

        # 如果超过一半的模型建议拦截，则拦截
        return block_count > len(self.edge_models) / 2


class UMPManager:
    """UMP 管理器

    参考：AbuUmpManager
    统一管理机器学习模型的训练和预测
    """

    def __init__(self):
        self.edge_models = {}
        self.main_model = MainModel()

    def make_block_decision(self, order, data):
        """做拦截决策

        Args:
            order: 订单对象
            data: 当前数据

        Returns:
            bool: 是否拦截该订单
        """
        features_dict = {}

        # 提取各模型的特征
        for model_type, model in self.edge_models.items():
            features_dict[model_type] = model.extract_features(data, order)

        # 主模型决策
        return self.main_model.predict(features_dict)

    def train(self, historical_data, orders, results):
        """训练模型

        Args:
            historical_data: 历史数据
            orders: 历史订单
            results: 交易结果
        """
        # 训练各个边缘模型
        for model_type, model in self.edge_models.items():
            features = []
            labels = []

            for order, result in zip(orders, results):
                feature = model.extract_features(historical_data, order)
                features.append(feature)
                labels.append(1 if result.profit > 0 else 0)

            model.train(features, labels)
```

### 3.3 API 设计

```python
import backtrader as bt
from backtrader.factors import FactorBuyBase, FactorSellBase, CallMixin, PutMixin
from backtrader.position import ATRPosition, KellyPosition
from backtrader.slippage import ProbabilitySlippage
from backtrader.ml import EdgeModel, UMPManager


# 1. 定义买入因子
class BreakoutFactor(FactorBuyBase, CallMixin):
    """突破买入因子"""

    params = (
        ('period', 20),
        ('threshold', 0.02),  # 突破阈值 2%
    )

    def _init_self(self):
        self.high = bt.indicators.Highest(self.data.close, period=self.p.period)

    def fit_day(self, today_index):
        if len(self.high) < 1:
            return False

        # 检查是否突破
        prev_high = self.high[-1]
        current = self.data.close[0]

        if current > prev_high * (1 + self.p.threshold):
            return True

        return False


# 2. 定义卖出因子
class ATRStopLossFactor(FactorSellBase):
    """ATR 止损因子"""

    params = (
        ('atr_period', 14),
        ('atr_multiplier', 2.0),
    )

    def _init_self(self):
        self.atr = bt.indicators.ATR(self.strategy.data, period=self.p.atr_period)
        self.entry_price = {}
        self.entry_bar = {}

    def support_direction(self):
        return [Direction.CALL, Direction.PUT]

    def fit_day(self, today_index, order):
        # 获取入场价格
        if order.ref not in self.entry_price:
            self.entry_price[order.ref] = order.created.price
            self.entry_bar[order.ref] = today_index
            return False

        entry_price = self.entry_price[order.ref]
        entry_bar = self.entry_bar[order.ref]

        # 计算 ATR 止损位
        if today_index - entry_bar >= self.p.atr_period:
            avg_atr = self.atr[entry_bar:today_index].mean()
            stop_loss_price = entry_price - order.expect_direction * avg_atr * self.p.atr_multiplier

            current_price = self.strategy.data.close[0]

            # 检查是否触发止损
            if order.expect_direction > 0:  # 多头
                if current_price < stop_loss_price:
                    return True
            else:  # 空头
                if current_price > stop_loss_price:
                    return True

        return False


# 3. 使用因子策略
class FactorStrategy(bt.Strategy):
    """因子策略"""

    def __init__(self):
        # 买入因子列表
        self.buy_factors = [
            BreakoutFactor(self.data, period=20, threshold=0.02),
            BreakoutFactor(self.data, period=60, threshold=0.03),
        ]

        # 卖出因子列表
        self.sell_factors = [
            ATRStopLossFactor(self, atr_period=14, atr_multiplier=2.0),
        ]

    def next(self):
        # 检查卖出因子
        for order in self.orders:
            for sell_factor in self.sell_factors:
                if sell_factor.fit_day(len(self), order):
                    self.close(order=order)

        # 检查买入因子
        for buy_factor in self.buy_factors:
            if buy_factor.fit_day(len(self)):
                size = 100  # 可以使用仓位管理器计算
                self.buy(size=size)


# 4. 使用动态仓位管理
cerebro = bt.Cerebro()
cerebro.addstrategy(
    FactorStrategy,
    # 添加 ATR 仓位管理
    position=ATRPosition(
        atr_period=14,
        atr_base_price=20,
        atr_pos_base=0.5,
        pos_max=0.75
    )
)

# 5. 使用凯利仓位管理
cerebro.addstrategy(
    FactorStrategy,
    position=KellyPosition(
        win_rate=0.6,
        avg_win=1.0,
        avg_loss=0.5,
        pos_max=0.75
    )
)

# 6. 使用概率滑点
cerebro.broker.set_slippage(ProbabilitySlippage(deal_prob=0.95))

# 7. 使用机器学习拦截
ump_manager = UMPManager()
ump_manager.edge_models['price'] = EdgeModel('price')
ump_manager.edge_models['deg'] = EdgeModel('deg')

# 训练模型
# ump_manager.train(historical_data, orders, results)

# 在策略中使用
class MLStrategy(bt.Strategy):
    def __init__(self):
        self.ump_manager = UMPManager()

    def next(self):
        if self._should_buy():
            order = self.buy(size=100)

            # UMP 决策
            if self.ump_manager.make_block_decision(order, self.data):
                self.cancel(order)
```

### 3.4 组件化架构

```
┌────────────────────────────────────────────────────────────┐
│                    Backtrader Factor Components              │
├────────────────────────────────────────────────────────────┤
│  Factor System                                              │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  FactorBuyBase (买入因子基类)                       │ │
│  │  ├── CallMixin (看涨混入)                            │ │
│  │  ├── PutMixin (看跌混入)                             │ │
│  │  └── fit_day() - 决策方法                             │ │
│  ├──────────────────────────────────────────────────────┤ │
│  │  FactorSellBase (卖出因子基类)                      │ │
│  │  ├── support_direction() - 支持的方向                  │ │
│  │  └── fit_day() - 决策方法                             │ │
│  └──────────────────────────────────────────────────────┘ │
│           ↓ 组合
│  ┌──────────────────────────────────────────────────────┐ │
│  │  FactorStrategy (因子策略)                           │ │
│  │  ├── buy_factors: List[FactorBuyBase]                │ │
│  │  └── sell_factors: List[FactorSellBase]              │ │
│  └──────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  Position Management                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐              │
│  │ATRPosition│ │KellyPos  │ │RiskParityPos  │              │
│  └──────────┘ └──────────┘ └──────────────┘              │
│           ↓                                              │
│  动态调整仓位大小基于：ATR波动率 / 凯利公式 / 风险平价     │
├────────────────────────────────────────────────────────────┤
│  Slippage Model                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  ProbabilitySlippage                                 │ │
│  │  - 涨停板特殊处理                                    │ │
│  │  - 二项分布成交概率                                │ │
│  │  - 价格区间分布成交                                 │ │
│  └──────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  MultiLevelSlippage                                  │ │
│  │  - 订单簿模拟                                        │ │
│  │  - 多档位成交                                        │ │
│  └──────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────┤
│  Machine Learning                                          │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  EdgeModel (边缘模型)                                │ │
│  │  - PriceModel   - DegModel    - WaveModel          │ │
│  │  - 针对特定信号类型进行拦截                         │ │
│  └──────────────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────┐ │
│  │  MainModel (主决策模型)                              │ │
│  │  - 综合多个边缘模型的决策                            │ │
│  │  - 投票或加权平均                                    │ │
│  └──────────────────────────────────────────────────────┘ │
│           ↓
│  ┌──────────────────────────────────────────────────────┐ │
│  │  UMPManager (UMP 管理器)                            │ │
│  │  - 模型训练和预测                                      │ │
│  │  - 特征工程管理                                      │ │
│  └──────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────┘
```

---

## 四、实施计划

### 4.1 实施阶段

| 阶段 | 任务 | 预计工作量 |
|------|------|-----------|
| Phase 1 | 创建 factors 目录，实现因子基类 | 1天 |
| Phase 2 | 实现买入/卖出因子示例 | 1天 |
| Phase 3 | 实现 ATR 和 Kelly 仓位管理 | 1.5天 |
| Phase 4 | 实现概率滑点模型 | 1.5天 |
| Phase 5 | 实现机器学习拦截系统 | 2天 |
| Phase 6 | 测试和文档 | 1天 |

### 4.2 优先级

1. **P0**: FactorBase - 因子基类和方向混入
2. **P0**: ATRPosition - ATR 动态仓位
3. **P1**: ProbabilitySlippage - 概率滑点模型
4. **P1**: KellyPosition - 凯利公式仓位
5. **P2**: EdgeModel - 机器学习边缘模型
6. **P2**: UMPManager - UMP 管理器

---

## 五、参考资料

### 5.1 关键参考代码

- abu/abupy/FactorBuyBu/ABuFactorBuyBase.py - 买入因子基类
- abu/abupy/FactorSellBu/ABuFactorSellBase.py - 卖出因子基类
- abu/abupy/BetaBu/ABuAtrPosition.py - ATR 仓位管理
- abu/abupy/BetaBu/ABuKellyPosition.py - 凯利仓位管理
- abu/abupy/BetaBu/ABuPositionBase.py - 仓位基类
- abu/abupy/SlippageBu/ - 滑点模型
- abu/abupy/UmpBu/ - UMP 机器学习系统

### 5.2 关键设计模式

1. **Mixin 模式** - CallMixin/PutMixin 方向混入
2. **模板方法模式** - fit_day() 抽象方法
3. **策略模式** - 不同仓位策略的选择
4. **责任链模式** - 多个卖出因子的链式处理

### 5.3 backtrader 可复用组件

- `backtrader/strategy.py` - 策略基类
- `backtrader/sizers/` - 现有 sizer
- `backtrader/slippage/` - 现有滑点
- `backtrader/indicators/` - 技术指标
