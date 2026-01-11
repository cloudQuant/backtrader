### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/hikyuu
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### hikyuu项目简介
hikyuu是一个基于C++/Python的开源量化交易研究框架，具有以下核心特点：
- **C++核心**: 底层使用C++实现，Python绑定，高性能
- **系统交易**: 完整的系统化交易框架（System Trader）
- **组件化**: 信号指示器、止损、止盈、资金管理等独立组件
- **技术分析**: 丰富的技术指标库
- **数据管理**: 高效的K线数据管理
- **交互分析**: 支持Jupyter交互式分析

### 重点借鉴方向
1. **System组件化**: 交易系统组件化设计（SG/ST/TP/MM/SL/PG）
2. **高性能计算**: C++核心带来的性能优势
3. **指标体系**: Indicator指标计算框架
4. **资金管理**: MoneyManager资金管理模块
5. **选股器**: Selector选股和组合管理
6. **环境管理**: Environment市场环境评估

---

## 架构对比分析

### Backtrader 核心特点

**优势:**
1. **成熟的Line系统**: 基于循环缓冲区的高效时间序列数据管理
2. **完整的回测引擎**: Cerebro统一管理策略、数据、经纪商、分析器
3. **丰富的技术指标**: 60+内置技术指标
4. **性能优化**: 支持向量化(once模式)和事件驱动(next模式)双执行模式
5. **Cython加速**: 关键路径使用Cython优化
6. **多市场支持**: 支持股票、期货、加密货币等多种市场
7. **Python优先**: 纯Python实现，易于扩展和定制

**局限:**
1. **策略耦合度高**: 信号生成、资金管理、风控都在Strategy中耦合
2. **缺少组件化**: 无法独立配置止损、止盈、资金管理等模块
3. **多系统组合弱**: 缺少统一的多策略组合管理框架
4. **选股功能缺失**: 没有独立的选股器组件
5. **市场环境判断**: 缺少系统化的市场环境评估机制
6. **资金管理简单**: 主要基于固定比例，缺少高级算法

### Hikyuu 核心特点

**优势:**
1. **高度组件化**: SG/ST/TP/MM/CN/EV/AF/SE等独立组件，灵活组合
2. **C++高性能**: 核心计算使用C++，性能优异
3. **系统化交易**: System类完整封装交易逻辑
4. **独立资金管理**: MoneyManager专门负责仓位计算
5. **选股器系统**: Selector独立管理多标的选择
6. **资金分配**: AllocateFunds独立管理多系统资金分配
7. **市场环境**: Environment评估市场状态
8. **工厂模式**: crtSG/crtMM等快速创建组件
9. **延迟交易**: 支持信号延迟执行机制

**局限:**
1. **C++门槛高**: 扩展需要C++知识
2. **学习曲线**: 组件众多，概念复杂
3. **Python集成**: Python接口不如原生Python框架灵活
4. **文档质量**: 中文文档为主，英文资料较少

---

## 需求规格文档

### 1. System组件化架构 (优先级: 高)

**需求描述:**
引入Hikyuu式的System组件化架构，将交易系统拆解为独立可配置的组件。

**功能需求:**
1. **SignalGenerator (SG)**: 信号生成器，独立负责买卖信号
2. **StopLoss (ST)**: 止损组件，独立管理止损逻辑
3. **TakeProfit (TP)**: 止盈组件，独立管理止盈逻辑
4. **MoneyManager (MM)**: 资金管理器，独立计算仓位
5. **Condition (CN)**: 条件过滤器，验证交易条件
6. **Environment (EV)**: 环境评估器，评估市场环境

**非功能需求:**
1. 兼容现有Strategy系统
2. 组件可独立测试
3. 支持组件组合和复用

### 2. 增强的资金管理系统 (优先级: 高)

**需求描述:**
引入更强大的资金管理模块，支持多种仓位计算算法。

**功能需求:**
1. **固定数量**: 每次交易固定股数
2. **固定金额**: 每次交易固定金额
3. **固定比例**: 每次交易占用资金比例
4. **固定风险**: 基于止损幅度的风险计算
5. **凯利公式**: 基于胜率和赔率的仓位计算
6. **ATR仓位**: 基于波动率的仓位计算
7. **动态仓位**: 根据市场状态调整仓位

**非功能需求:**
1. 支持多数据源独立计算
2. 支持总资金和可用资金计算

### 3. 选股器系统 (优先级: 中)

**需求描述:**
引入独立的选股器组件，支持多因子选股和动态股票池管理。

**功能需求:**
1. **固定选股**: 固定股票池
2. **多因子选股**: 基于多因子评分选股
3. **信号选股**: 基于交易信号选股
4. **动态过滤**: 支持动态添加/移除股票
5. **板块轮动**: 支持板块轮动策略
6. **系统原型**: 支持原型系统克隆

**非功能需求:**
1. 支持大规模股票池（1000+）
2. 高效的增量计算

### 4. 资金分配系统 (优先级: 中)

**需求描述:**
引入独立的资金分配器，管理多策略/多标的的资金分配。

**功能需求:**
1. **等权重分配**: 所有选中标的等权重
2. **固定权重**: 预定义的固定权重
3. **因子权重**: 基于因子值的权重分配
4. **动态调整**: 支持定期再平衡
5. **资金预留**: 支持保留部分现金

**非功能需求:**
1. 支持总资产和可用资金分配
2. 支持最小交易单位

### 5. 市场环境评估 (优先级: 低)

**需求描述:**
引入市场环境评估组件，根据市场状态动态调整策略。

**功能需求:**
1. **趋势判断**: 识别牛/熊/震荡市
2. **波动率评估**: 识别高/低波动环境
3. **环境切换**: 支持环境切换信号
4. **策略开关**: 根据环境自动启停策略
5. **仓位调整**: 根据环境动态调整总仓位

### 6. 工厂函数系统 (优先级: 低)

**需求描述:**
提供便捷的工厂函数，快速创建常用组件。

**功能需求:**
1. **crtSG()**: 创建信号生成器
2. **crtMM()**: 创建资金管理器
3. **crtST()**: 创建止损组件
4. **crtTP()**: 创建止盈组件
5. **crtSE()**: 创建选股器
6. **crtAF()**: 创建资金分配器

---

## 设计文档

### 1. System组件化设计

#### 1.1 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                     System (交易系统)                    │
├─────────────────────────────────────────────────────────┤
│  Components:                                            │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐          │
│  │ SignalGen  │ │ MoneyMgr   │ │ StopLoss   │          │
│  │   (SG)     │ │   (MM)     │ │   (ST)     │          │
│  └────────────┘ └────────────┘ └────────────┘          │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐          │
│  │ TakeProfit │ │ Condition  │ │Environment │          │
│  │   (TP)     │ │   (CN)     │ │   (EV)     │          │
│  └────────────┘ └────────────┘ └────────────┘          │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   TradeManager (经纪商)                  │
└─────────────────────────────────────────────────────────┘
```

#### 1.2 核心类设计

```python
# backtrader/system/system.py
class System(MetaBase):
    """
    交易系统类，组合各个交易组件
    """
    params = (
        ('sg', None),      # SignalGenerator
        ('mm', None),      # MoneyManager
        ('st', None),      # StopLoss
        ('tp', None),      # TakeProfit
        ('cn', None),      # Condition
        ('ev', None),      # Environment
    )

    def __init__(self):
        super().__init__()
        self._components = {}

        # 注册各组件
        if self.p.sg:
            self._components['sg'] = self.p.sg
        if self.p.mm:
            self._components['mm'] = self.p.mm
        if self.p.st:
            self._components['st'] = self.p.st
        if self.p.tp:
            self._components['tp'] = self.p.tp
        if self.p.cn:
            self._components['cn'] = self.p.cn
        if self.p.ev:
            self._components['ev'] = self.p.ev

    def next(self):
        """系统主逻辑"""
        # 1. 环境检查
        if self.p.ev and not self.p.ev.is_valid():
            # 环境不合适，平仓
            self._close_all_positions()
            return

        # 2. 条件检查
        if self.p.cn and not self.p.cn.is_valid():
            return

        # 3. 信号检查
        signal = self._check_signal()

        # 4. 执行交易
        if signal == 1:  # 买入信号
            self._execute_buy()
        elif signal == -1:  # 卖出信号
            self._execute_sell()

        # 5. 止损止盈检查
        self._check_risk_management()
```

#### 1.3 SignalGenerator设计

```python
# backtrader/system/signal.py
class SignalBase(MetaBase):
    """信号生成器基类"""
    params = ()

    def __init__(self):
        super().__init__()

    def is_buy(self):
        """是否产生买入信号"""
        return False

    def is_sell(self):
        """是否产生卖出信号"""
        return False

    def get_signal(self):
        """获取当前信号: 1=买入, -1=卖出, 0=无"""
        if self.is_buy():
            return 1
        elif self.is_sell():
            return -1
        return 0

# 具体实现示例
class CrossSignal(SignalBase):
    """金叉死叉信号"""
    params = (
        ('fast', None),
        ('slow', None),
    )

    def __init__(self):
        super().__init__()
        self.cross_up = bt.ind.CrossOver(self.p.fast, self.p.slow)
        self.cross_down = bt.ind.CrossDown(self.p.fast, self.p.slow)

    def is_buy(self):
        return self.cross_up[0] > 0

    def is_sell(self):
        return self.cross_down[0] > 0
```

#### 1.4 MoneyManager设计

```python
# backtrader/system/moneymanager.py
class MoneyManagerBase(MetaBase):
    """资金管理器基类"""
    params = ()

    def __init__(self):
        super().__init__()

    def get_size(self, data, price=None):
        """
        计算交易数量

        Args:
            data: 数据源
            price: 交易价格（None则使用当前价格）

        Returns:
            交易数量（负数表示卖出）
        """
        raise NotImplementedError

class FixedMoney(MoneyManagerBase):
    """固定金额资金管理"""
    params = (('money', 10000),)

    def get_size(self, data, price=None):
        price = price or data.close[0]
        return int(self.p.money / price)

class FixedPercent(MoneyManagerBase):
    """固定比例资金管理"""
    params = (('percent', 0.1),)  # 10%

    def get_size(self, data, price=None):
        price = price or data.close[0]
        available = self.strategy.broker.getvalue() * self.p.percent
        return int(available / price)

class RiskPercent(MoneyManagerBase):
    """风险比例资金管理（基于止损）"""
    params = (('risk_percent', 0.02),)  # 每次风险2%

    def get_size(self, data, price=None):
        price = price or data.close[0]

        # 获取止损幅度
        stoploss = self.system.p.st
        if stoploss and hasattr(stoploss, 'get_stop_price'):
            stop_price = stoploss.get_stop_price(data)
            risk_per_share = abs(price - stop_price)
        else:
            # 默认5%止损
            risk_per_share = price * 0.05

        if risk_per_share == 0:
            return 0

        total_risk = self.strategy.broker.getvalue() * self.p.risk_percent
        return int(total_risk / risk_per_share)

class KellyCriterion(MoneyManagerBase):
    """凯利公式资金管理"""
    params = (
        ('win_rate', 0.5),      # 胜率
        ('avg_win', 1.0),       # 平均盈利
        ('avg_loss', 1.0),      # 平均亏损
        ('fraction', 0.5),      # 凯利分数（实际使用比例）
    )

    def get_size(self, data, price=None):
        price = price or data.close[0]

        # 凯利公式: f = (b*p - q) / b
        # b = avg_win / avg_loss (盈亏比)
        # p = win_rate (胜率)
        # q = 1 - p (败率)
        b = self.p.avg_win / self.p.avg_loss if self.p.avg_loss > 0 else 1
        p = self.p.win_rate
        q = 1 - p
        f = (b * p - q) / b if b > 0 else 0

        # 使用部分凯利
        f = max(0, f) * self.p.fraction

        # 计算仓位
        capital = self.strategy.broker.getvalue()
        return int(capital * f / price)
```

#### 1.5 StopLoss设计

```python
# backtrader/system/stoploss.py
class StopLossBase(MetaBase):
    """止损基类"""
    params = ()

    def __init__(self):
        super().__init__()

    def get_stop_price(self, data, position_type='long'):
        """
        获取止损价格

        Args:
            data: 数据源
            position_type: 'long' 或 'short'

        Returns:
            止损价格
        """
        raise NotImplementedError

    def check_stop(self, data, position_type='long'):
        """检查是否触发止损"""
        stop_price = self.get_stop_price(data, position_type)

        if position_type == 'long':
            return data.close[0] < stop_price
        else:
            return data.close[0] > stop_price

class FixedPercentStop(StopLossBase):
    """固定百分比止损"""
    params = (('percent', 0.05),)  # 5%止损

    def get_stop_price(self, data, position_type='long'):
        entry_price = self.get_entry_price(data)

        if position_type == 'long':
            return entry_price * (1 - self.p.percent)
        else:
            return entry_price * (1 + self.p.percent)

    def get_entry_price(self, data):
        """获取入场价格"""
        position = self.strategy.getposition(data)
        return position.price

class ATRStop(StopLossBase):
    """ATR止损"""
    params = (('atr_period', 14), ('multiplier', 2.0))

    def __init__(self):
        super().__init__()
        self.atr = bt.ind.ATR(period=self.p.atr_period)

    def get_stop_price(self, data, position_type='long'):
        entry_price = self.get_entry_price(data)
        atr_value = self.atr[0]

        if position_type == 'long':
            return entry_price - self.p.multiplier * atr_value
        else:
            return entry_price + self.p.multiplier * atr_value

class TrailingStop(StopLossBase):
    """移动止损"""
    params = (('percent', 0.05),)

    def __init__(self):
        super().__init__()
        self._highest = None  # 多头最高价
        self._lowest = None   # 空头最低价

    def get_stop_price(self, data, position_type='long'):
        current_price = data.close[0]

        if position_type == 'long':
            if self._highest is None or current_price > self._highest:
                self._highest = current_price
            return self._highest * (1 - self.p.percent)
        else:
            if self._lowest is None or current_price < self._lowest:
                self._lowest = current_price
            return self._lowest * (1 + self.p.percent)
```

#### 1.6 Environment设计

```python
# backtrader/system/environment.py
class EnvironmentBase(MetaBase):
    """市场环境评估基类"""
    params = ()

    def __init__(self):
        super().__init__()
        self._state = 'unknown'  # bullish, bearish, neutral

    def is_valid(self):
        """当前环境是否适合交易"""
        return self._state != 'bearish'

    def get_state(self):
        """获取当前市场状态"""
        return self._state

    def update(self):
        """更新环境状态"""
        raise NotImplementedError

class TrendEnvironment(EnvironmentBase):
    """趋势环境判断"""
    params = (
        ('fast_period', 20),
        ('slow_period', 60),
    )

    def __init__(self):
        super().__init__()
        self.fast_ma = bt.ind.SMA(period=self.p.fast_period)
        self.slow_ma = bt.ind.SMA(period=self.p.slow_period)

    def update(self):
        if self.fast_ma[0] > self.slow_ma[0]:
            self._state = 'bullish'
        elif self.fast_ma[0] < self.slow_ma[0]:
            self._state = 'bearish'
        else:
            self._state = 'neutral'

class VolatilityEnvironment(EnvironmentBase):
    """波动率环境判断"""
    params = (
        ('atr_period', 14),
        ('high_threshold', 1.5),  # 高波动阈值
        ('low_threshold', 0.8),   # 低波动阈值
    )

    def __init__(self):
        super().__init__()
        self.atr = bt.ind.ATR(period=self.p.atr_period)
        # 计算ATR的移动平均作为基准
        self.atr_ma = bt.ind.SMA(self.atr, period=50)

    def update(self):
        current_atr = self.atr[0]
        avg_atr = self.atr_ma[0]

        if avg_atr > 0:
            ratio = current_atr / avg_atr
            if ratio > self.p.high_threshold:
                self._state = 'high_volatility'
            elif ratio < self.p.low_threshold:
                self._state = 'low_volatility'
            else:
                self._state = 'normal'
```

### 2. 选股器设计

```python
# backtrader/system/selector.py
class SelectorBase(MetaBase):
    """选股器基类"""
    params = ()

    def __init__(self):
        super().__init__()
        self._selected_stocks = set()
        self._stock_scores = {}

    def get_selected(self):
        """获取选中的股票列表"""
        return list(self._selected_stocks)

    def get_scores(self):
        """获取股票评分"""
        return self._stock_scores

    def select(self):
        """执行选股"""
        raise NotImplementedError

class FixedSelector(SelectorBase):
    """固定股票池选股器"""
    params = (('stocks', []),)

    def select(self):
        self._selected_stocks = set(self.p.stocks)
        self._stock_scores = {s: 1.0 for s in self.p.stocks}

class MultiFactorSelector(SelectorBase):
    """多因子选股器"""
    params = (
        ('factors', []),           # 因子列表
        ('factor_weights', []),    # 因子权重
        ('top_n', 50),             # 选择前N只
    )

    def __init__(self):
        super().__init__()

    def select(self, data_map):
        """
        执行多因子选股

        Args:
            data_map: {stock_code: data} 字典
        """
        scores = {}

        for stock, data in data_map.items():
            stock_score = 0
            for i, factor in enumerate(self.p.factors):
                weight = self.p.factor_weights[i] if i < len(self.p.factor_weights) else 1.0
                factor_value = factor.get_value(data)
                stock_score += factor_value * weight

            # 标准化
            scores[stock] = stock_score

        # 排序并选择前N只
        sorted_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self._selected_stocks = {s[0] for s in sorted_stocks[:self.p.top_n]}
        self._stock_scores = scores

class SignalSelector(SelectorBase):
    """信号选股器"""
    params = (('signal', None), ('top_n', 50))

    def select(self, data_map):
        """基于信号强度选股"""
        scores = {}

        for stock, data in data_map.items():
            signal_strength = self.p.signal.get_strength(data)
            scores[stock] = signal_strength

        sorted_stocks = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        self._selected_stocks = {s[0] for s in sorted_stocks[:self.p.top_n] if s[1] > 0}
        self._stock_scores = scores
```

### 3. 资金分配器设计

```python
# backtrader/system/allocatefunds.py
class AllocateFundsBase(MetaBase):
    """资金分配器基类"""
    params = ()

    def __init__(self):
        super().__init__()

    def allocate(self, selected_stocks, scores=None):
        """
        计算资金分配权重

        Args:
            selected_stocks: 选中的股票列表
            scores: 股票评分字典

        Returns:
            {stock: weight} 字典
        """
        raise NotImplementedError

class EqualWeightAlloc(AllocateFundsBase):
    """等权重分配"""
    params = ()

    def allocate(self, selected_stocks, scores=None):
        n = len(selected_stocks)
        if n == 0:
            return {}
        weight = 1.0 / n
        return {stock: weight for stock in selected_stocks}

class FactorWeightAlloc(AllocateFundsBase):
    """基于因子权重的分配"""
    params = ()

    def allocate(self, selected_stocks, scores=None):
        if not scores:
            return EqualWeightAlloc().allocate(selected_stocks)

        # 提取选中股票的分数
        selected_scores = {s: scores.get(s, 0) for s in selected_stocks}
        total = sum(selected_scores.values())

        if total == 0:
            return EqualWeightAlloc().allocate(selected_stocks)

        return {s: v / total for s, v in selected_scores.items()}

class FixedWeightAlloc(AllocateFundsBase):
    """固定权重分配"""
    params = (('weights', {}),)  # {stock: weight} 字典

    def allocate(self, selected_stocks, scores=None):
        result = {}
        for stock in selected_stocks:
            result[stock] = self.p.weights.get(stock, 0)

        # 归一化
        total = sum(result.values())
        if total > 0:
            result = {s: w / total for s, w in result.items()}

        return result
```

### 4. 工厂函数设计

```python
# backtrader/system/factory.py
def crtSG(signal_type, **params):
    """
    创建信号生成器

    Args:
        signal_type: 信号类型
        **params: 参数

    Returns:
        SignalBase实例
    """
    if signal_type == 'cross':
        return CrossSignal(**params)
    elif signal_type == 'single':
        return SingleSignal(**params)
    # ... 更多类型
    raise ValueError(f'Unknown signal type: {signal_type}')

def crtMM(mm_type='fixed_percent', **params):
    """创建资金管理器"""
    if mm_type == 'fixed_money':
        return FixedMoney(**params)
    elif mm_type == 'fixed_percent':
        return FixedPercent(**params)
    elif mm_type == 'risk':
        return RiskPercent(**params)
    elif mm_type == 'kelly':
        return KellyCriterion(**params)
    raise ValueError(f'Unknown money manager type: {mm_type}')

def crtST(st_type='fixed_percent', **params):
    """创建止损组件"""
    if st_type == 'fixed_percent':
        return FixedPercentStop(**params)
    elif st_type == 'atr':
        return ATRStop(**params)
    elif st_type == 'trailing':
        return TrailingStop(**params)
    raise ValueError(f'Unknown stoploss type: {st_type}')

def crtSE(se_type='fixed', **params):
    """创建选股器"""
    if se_type == 'fixed':
        return FixedSelector(**params)
    elif se_type == 'multi_factor':
        return MultiFactorSelector(**params)
    elif se_type == 'signal':
        return SignalSelector(**params)
    raise ValueError(f'Unknown selector type: {se_type}')

def crtAF(af_type='equal_weight', **params):
    """创建资金分配器"""
    if af_type == 'equal_weight':
        return EqualWeightAlloc(**params)
    elif af_type == 'factor_weight':
        return FactorWeightAlloc(**params)
    elif af_type == 'fixed_weight':
        return FixedWeightAlloc(**params)
    raise ValueError(f'Unknown allocator type: {af_type}')

# 便捷创建System
def crtSystem(sg=None, mm=None, st=None, tp=None, cn=None, ev=None):
    """创建交易系统"""
    return System(sg=sg, mm=mm, st=st, tp=tp, cn=cn, ev=ev)
```

### 5. 使用示例

#### 5.1 基础System使用

```python
import backtrader as bt
from backtrader.system import crtSystem, crtSG, crtMM, crtST

# 创建Cerebro
cerebro = bt.Cerebro()

# 添加数据
data = bt.feeds.PandasData(dataname=df)
cerebro.adddata(data)

# 创建信号
ma_fast = bt.ind.SMA(period=10)
ma_slow = bt.ind.SMA(period=30)
sg = crtSG('cross', fast=ma_fast, slow=ma_slow)

# 创建资金管理
mm = crtMM('fixed_percent', percent=0.1)

# 创建止损
st = crtST('fixed_percent', percent=0.05)

# 创建系统
system = crtSystem(sg=sg, mm=mm, st=st)

# 添加策略
cerebro.addstrategy(SystemStrategy, system=system)

# 运行
result = cerebro.run()
```

#### 5.2 完整组件化策略

```python
class MySystem(bt.System):
    params = (
        ('fast_period', 10),
        ('slow_period', 30),
        ('risk_per_trade', 0.02),
    )

    def __init__(self):
        # 创建组件
        ma_fast = bt.ind.SMA(period=self.p.fast_period)
        ma_slow = bt.ind.SMA(period=self.p.slow_period)

        sg = CrossSignal(fast=ma_fast, slow=ma_slow)
        mm = RiskPercent(risk_percent=self.p.risk_per_trade)
        st = ATRStop(atr_period=14, multiplier=2.0)
        ev = TrendEnvironment(fast_period=20, slow_period=60)

        # 初始化系统
        super().__init__(sg=sg, mm=mm, st=st, ev=ev)

# 使用
cerebro.addstrategy(MySystem)
```

#### 5.3 多策略组合

```python
# 创建多个系统
systems = []

for fast, slow in [(5, 20), (10, 30), (20, 60)]:
    ma_fast = bt.ind.SMA(period=fast)
    ma_slow = bt.ind.SMA(period=slow)
    sg = CrossSignal(fast=ma_fast, slow=ma_slow)
    mm = FixedPercent(percent=0.05)
    st = ATRStop(atr_period=14, multiplier=2.0)

    systems.append(crtSystem(sg=sg, mm=mm, st=st))

# 创建选股器和分配器
selector = SignalSelector(signal=CombinedSignal(systems))
allocator = EqualWeightAlloc()

# 添加组合策略
cerebro.addstrategy(PortfolioStrategy,
                    systems=systems,
                    selector=selector,
                    allocator=allocator)
```

### 6. 实施路线图

#### 阶段1: 基础组件框架 (2-3周)
- [ ] 创建system包结构
- [ ] 实现System基类
- [ ] 实现SignalBase和基础信号
- [ ] 实现MoneyManagerBase和基础MM
- [ ] 实现StopLossBase和基础止损

#### 阶段2: 高级组件 (2周)
- [ ] 实现TakeProfit组件
- [ ] 实现Condition组件
- [ ] 实现Environment组件
- [ ] 添加更多MM实现（凯利、ATR等）

#### 阶段3: 选股和分配 (2周)
- [ ] 实现SelectorBase
- [ ] 实现多因子选股器
- [ ] 实现AllocateFundsBase
- [ ] 实现各种分配器

#### 阶段4: 工厂和集成 (1周)
- [ ] 实现工厂函数
- [ ] 创建Portfolio策略
- [ ] 文档和示例

#### 阶段5: 测试和优化 (1周)
- [ ] 单元测试
- [ ] 集成测试
- [ ] 性能对比测试

---

## 附录: 关键文件路径

### Backtrader关键文件
- `cerebro.py`: 核心引擎
- `strategy.py`: Strategy基类
- `linebuffer.py`: Line缓冲区
- `indicator.py`: Indicator基类
- `broker.py`: Broker基类

### Hikyuu关键文件
- `hikyuu_cpp/hikyuu/trade_sys/system/System.h`: System核心
- `hikyuu_cpp/hikyuu/trade_sys/signal/SignalBase.h`: 信号基类
- `hikyuu_cpp/hikyuu/trade_sys/moneymanager/MoneyManagerBase.h`: 资金管理
- `hikyuu_cpp/hikyuu/trade_sys/stoploss/StoplossBase.h`: 止损基类
- `hikyuu_cpp/hikyuu/trade_sys/selector/SelectorBase.h`: 选股器
- `hikyuu_cpp/hikyuu/trade_sys/allocatefunds/AllocateFundsBase.h`: 资金分配
- `hikyuu_cpp/hikyuu/trade_sys/environment/EnvironmentBase.h`: 环境评估
