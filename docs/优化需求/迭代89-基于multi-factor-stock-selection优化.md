### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/multi-factor-stock-selection
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### multi-factor-stock-selection项目简介
multi-factor-stock-selection是一个多因子选股框架，具有以下核心特点：
- **多因子模型**: 多因子选股模型
- **因子计算**: 因子值计算
- **因子评价**: 因子有效性评价
- **因子组合**: 因子组合优化
- **选股策略**: 选股策略实现
- **组合构建**: 投资组合构建

### 重点借鉴方向
1. **因子模型**: 多因子模型设计
2. **因子计算**: 因子计算引擎
3. **因子评价**: 因子评价体系
4. **因子合成**: 因子合成方法
5. **选股逻辑**: 选股逻辑实现
6. **组合优化**: 组合优化方法

---

## 项目对比分析

### Backtrader vs Multi-Factor-Stock-Selection

| 维度 | Backtrader | Multi-Factor-Stock-Selection |
|------|-----------|------------------------------|
| **核心定位** | 通用回测框架 | 多因子选股专用框架 |
| **数据模型** | Line系统（时间序列） | DataFrame（截面数据） |
| **因子系统** | 内置60+技术指标 | 财务/技术/情绪多因子体系 |
| **因子评价** | 无内置评价机制 | IC/ICIR/因子退场机制 |
| **选股策略** | 需自行实现 | 内置评分选股引擎 |
| **组合构建** | 手动分配仓位 | 等权/优化权重自动分配 |
| **回测模式** | 事件驱动（逐bar） | 批量处理（向量化） |
| **多资产支持** | 原生支持 | 专门针对股票池 |
| **因子合成** | 无 | Z-score标准化+加权合成 |
| **机器学习** | 无 | LightGBM集成 |

### Backtrader可借鉴的优势

1. **因子生命周期管理**：因子墓地机制、动态IC监控
2. **因子评价体系**：IC/ICIR计算、因子有效性评估
3. **截面分析能力**：多股票横向比较、排序选股
4. **因子合成引擎**：标准化、加权、机器学习合成
5. **批量处理优化**：向量化计算、性能优化

---

## 功能需求文档

### FR-01 因子基础框架 [高优先级]

**描述**: 建立统一的因子计算和管理框架

**需求**:
- FR-01.1 定义因子基类 `FactorBase`，所有因子继承此类
- FR-01.2 支持因子的注册和发现机制
- FR-01.3 支持因子参数配置
- FR-01.4 支持因子计算结果缓存

**验收标准**:
- 可以通过继承基类轻松添加新因子
- 因子计算结果可被后续模块复用

### FR-02 因子计算引擎 [高优先级]

**描述**: 实现高效的因子批量计算引擎

**需求**:
- FR-02.1 支持财务因子计算（PE、PB、ROE、营收增长等）
- FR-02.2 支持技术因子计算（动量、波动率、乖离率等）
- FR-02.3 支持情绪因子计算（换手率、涨跌停、连板等）
- FR-02.4 支持自定义时间窗口参数
- FR-02.5 支持分组计算（按股票分组）

**验收标准**:
- 支持至少20种常用因子
- 计算性能优化（向量化）
- 支持缺失值和极端值处理

### FR-03 因子评价体系 [高优先级]

**描述**: 建立因子有效性评价机制

**需求**:
- FR-03.1 IC（Information Coefficient）计算
- FR-03.2 ICIR（IC信息比率）计算
- FR-03.3 Rank IC计算
- FR-03.4 因子衰减分析
- FR-03.5 因子分层回测

**验收标准**:
- 支持日度/周度/月度IC计算
- 输出IC统计报告（均值、标准差、t统计量）
- 支持IC时序可视化

### FR-04 因子合成引擎 [中优先级]

**描述**: 实现多因子合成方法

**需求**:
- FR-04.1 Z-score标准化
- FR-04.2 Min-Max标准化
- FR-04.3 等权合成
- FR-04.4 IC加权合成
- FR-04.5 最大化ICIR加权
- FR-04.6 机器学习合成（LightGBM/XGBoost）

**验收标准**:
- 支持至少5种合成方法
- 合成结果可验证
- 支持因子权重动态调整

### FR-05 选股策略引擎 [高优先级]

**描述**: 实现基于因子评分的选股策略

**需求**:
- FR-05.1 单因子选股
- FR-05.2 多因子综合评分选股
- FR-05.3 分层选股（按因子值分组）
- FR-05.4 条件过滤选股（行业/市值/ST等）
- FR-05.5 动态调仓（定期/触发式）

**验收标准**:
- 支持Top N选股
- 支持分层回测
- 选股结果可导出

### FR-06 组合构建器 [中优先级]

**描述**: 实现投资组合权重分配

**需求**:
- FR-06.1 等权分配
- FR-06.2 市值加权
- FR-06.3 因子值加权
- FR-06.4 风险平价
- FR-06.5 最小方差组合
- FR-06.6 行业中性约束

**验收标准**:
- 支持至少4种权重分配方法
- 权重和为1（或目标仓位）
- 支持约束条件设置

### FR-07 因子生命周期管理 [中优先级]

**描述**: 实现因子退场和替换机制

**需求**:
- FR-07.1 因子IC监控
- FR-07.2 因子失效检测（连续低IC）
- FR-07.3 因子自动退场
- FR-07.4 因子归档（因子墓地）
- FR-07.5 新因子上线流程

**验收标准**:
- 连续3个月ICIR<0.3触发退场警告
- 退场因子自动归档
- 支持因子恢复

### FR-08 截面分析工具 [中优先级]

**描述**: 增强多股票截面分析能力

**需求**:
- FR-08.1 截面因子值计算
- FR-08.2 截面排序和分位数
- FR-08.3 行业截面分析
- FR-08.4 截面中性化

**验收标准**:
- 支持按日期/行业分组截面分析
- 支持行业中性化处理

---

## 设计文档

### 1. 因子系统架构设计

#### 1.1 因子基类设计

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import pandas as pd
import numpy as np

@dataclass
class FactorParams:
    """因子参数配置"""
    name: str
    description: str = ""
    category: str = "technical"  # technical, financial, sentiment, macro
    windows: List[int] = None
    required_fields: List[str] = None

class FactorBase(ABC):
    """因子基类 - 所有因子继承此类"""

    def __init__(self, params: FactorParams):
        self.params = params
        self.name = params.name
        self.category = params.category
        self._cache = {}

    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """
        计算因子值

        Args:
            data: 包含OHLCV等字段的数据框

        Returns:
            因子值序列
        """
        pass

    def validate_data(self, data: pd.DataFrame) -> bool:
        """验证数据是否包含所需字段"""
        if self.params.required_fields is None:
            return True
        return all(field in data.columns for field in self.params.required_fields)

    def handle_extremes(self, series: pd.Series, method: str = 'clip',
                       lower: float = None, upper: float = None) -> pd.Series:
        """处理极端值"""
        if method == 'clip':
            if lower is None:
                lower = series.quantile(0.01)
            if upper is None:
                upper = series.quantile(0.99)
            return series.clip(lower, upper)
        elif method == 'winsorize':
            # 缩尾处理
            return (series.clip(lower, upper) - lower) / (upper - lower)
        return series

    def handle_missing(self, series: pd.Series, method: str = 'ffill') -> pd.Series:
        """处理缺失值"""
        if method == 'ffill':
            return series.fillna(method='ffill')
        elif method == 'mean':
            return series.fillna(series.mean())
        elif method == 'drop':
            return series.dropna()
        return series

    def standardize(self, series: pd.Series, method: str = 'zscore') -> pd.Series:
        """标准化"""
        if method == 'zscore':
            return (series - series.mean()) / (series.std() + 1e-8)
        elif method == 'minmax':
            return (series - series.min()) / (series.max() - series.min() + 1e-8)
        elif method == 'rank':
            return series.rank(pct=True)
        return series

# 注册机制
_factor_registry = {}

def register_factor(cls: FactorBase):
    """因子注册装饰器"""
    _factor_registry[cls.params.name] = cls
    return cls

def get_factor(name: str) -> FactorBase:
    """获取已注册因子"""
    if name not in _factor_registry:
        raise ValueError(f"Factor {name} not found")
    return _factor_registry[name]

def list_factors(category: str = None) -> List[str]:
    """列出已注册因子"""
    if category is None:
        return list(_factor_registry.keys())
    return [name for name, cls in _factor_registry.items()
            if cls.category == category]
```

#### 1.2 技术因子实现

```python
@register_factor
class MomentumFactor(FactorBase):
    """动量因子"""

    def __init__(self, window: int = 20):
        params = FactorParams(
            name=f"momentum_{window}",
            description=f"{window}期动量因子",
            category="technical",
            windows=[window],
            required_fields=['close']
        )
        super().__init__(params)
        self.window = window

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """计算动量 = 当前价格 / N日前价格 - 1"""
        return data['close'].pct_change(self.window)

@register_factor
class VolatilityFactor(FactorBase):
    """波动率因子"""

    def __init__(self, window: int = 20):
        params = FactorParams(
            name=f"volatility_{window}",
            description=f"{window}期波动率因子",
            category="technical",
            windows=[window],
            required_fields=['close']
        )
        super().__init__(params)
        self.window = window

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """计算波动率 = 收益率标准差"""
        returns = data['close'].pct_change()
        return returns.rolling(window=self.window).std()

@register_factor
class BiasFactor(FactorBase):
    """乖离率因子"""

    def __init__(self, window: int = 20):
        params = FactorParams(
            name=f"bias_{window}",
            description=f"{window}期乖离率因子",
            category="technical",
            windows=[window],
            required_fields=['close']
        )
        super().__init__(params)
        self.window = window

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """计算乖离率 = (收盘价 - 均线) / 均线"""
        ma = data['close'].rolling(window=self.window).mean()
        return (data['close'] - ma) / ma

@register_factor
class RSIFactor(FactorBase):
    """RSI因子"""

    def __init__(self, window: int = 14):
        params = FactorParams(
            name=f"rsi_{window}",
            description=f"{window}期RSI因子",
            category="technical",
            windows=[window],
            required_fields=['close']
        )
        super().__init__(params)
        self.window = window

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """计算RSI"""
        delta = data['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.window).mean()
        rs = gain / (loss + 1e-8)
        return 100 - (100 / (1 + rs))
```

#### 1.3 财务因子实现

```python
@register_factor
class PEFactor(FactorBase):
    """PE估值因子（倒数，越小越好）"""

    def __init__(self):
        params = FactorParams(
            name="pe_ttm_inv",
            description="PE倒数因子",
            category="financial",
            required_fields=['pe_ttm']
        )
        super().__init__(params)

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """PE倒数 = 1/PE"""
        pe = data['pe_ttm'].replace([None, 0], np.nan).fillna(method='ffill')
        return 1 / (pe + 1e-8)

@register_factor
class ROEFactor(FactorBase):
    """ROE盈利能力因子"""

    def __init__(self):
        params = FactorParams(
            name="roe_ttm",
            description="ROE因子",
            category="financial",
            required_fields=['roe']
        )
        super().__init__(params)

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """ROE = 净资产收益率"""
        return data['roe'].replace([None], np.nan).fillna(method='ffill')

@register_factor
class RevenueGrowthFactor(FactorBase):
    """营收增长因子"""

    def __init__(self):
        params = FactorParams(
            name="revenue_growth",
            description="营收增长率因子",
            category="financial",
            required_fields=['revenue_yoy']
        )
        super().__init__(params)

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """营收同比增长率"""
        return data['revenue_yoy'].replace([None], np.nan).fillna(method='ffill') / 100

@register_factor
class GPFactor(FactorBase):
    """毛利率因子"""

    def __init__(self):
        params = FactorParams(
            name="gross_profit_margin",
            description="毛利率因子",
            category="financial",
            required_fields=['grossprofit_margin']
        )
        super().__init__(params)

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """毛利率"""
        return data['grossprofit_margin'].replace([None], np.nan).fillna(method='ffill') / 100
```

#### 1.4 情绪因子实现

```python
@register_factor
class TurnoverFactor(FactorBase):
    """换手率因子"""

    def __init__(self):
        params = FactorParams(
            name="turnover_rate",
            description="换手率因子",
            category="sentiment",
            required_fields=['vol', 'float_share']
        )
        super().__init__(params)

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """换手率 = 成交量 / 流通股本"""
        return data['vol'] / (data['float_share'] + 1e-8)

@register_factor
class LimitUpFactor(FactorBase):
    """涨停因子"""

    def __init__(self):
        params = FactorParams(
            name="is_limit_up",
            description="涨停标记因子",
            category="sentiment",
            required_fields=['pct_chg']
        )
        super().__init__(params)

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """涨停标记"""
        return (data['pct_chg'] >= 9.9).astype(int)

@register_factor
class ConsecutiveLimitUpFactor(FactorBase):
    """连板因子"""

    def __init__(self):
        params = FactorParams(
            name="consecutive_limit_up",
            description="连续涨停天数因子",
            category="sentiment",
            required_fields=['pct_chg']
        )
        super().__init__(params)

    def calculate(self, data: pd.DataFrame) -> pd.Series:
        """计算连续涨停次数"""
        is_limit = (data['pct_chg'] >= 9.9).astype(int)
        consecutive = pd.Series(0, index=data.index)

        count = 0
        for i in range(len(data)):
            if is_limit.iloc[i] == 1:
                count += 1
            else:
                count = 0
            consecutive.iloc[i] = count

        return consecutive
```

### 2. 因子评价系统设计

```python
from typing import Dict, List, Tuple, Optional
from scipy import stats
import pandas as pd

class FactorEvaluator:
    """因子评价器 - 评估因子有效性"""

    def __init__(self, data: pd.DataFrame, future_return_col: str = 'future_return'):
        """
        Args:
            data: 包含因子值和未来收益率的数据
            future_return_col: 未来收益率列名
        """
        self.data = data
        self.future_return_col = future_return_col

    def calculate_ic(self, factor_name: str, method: str = 'spearman',
                    by_date: bool = True) -> pd.Series:
        """
        计算IC（信息系数）

        Args:
            factor_name: 因子列名
            method: 'spearman' 或 'pearson'
            by_date: 是否按日计算

        Returns:
            IC序列
        """
        if by_date:
            ic_series = {}
            for date, group in self.data.groupby('trade_date'):
                factor_values = group[factor_name]
                return_values = group[self.future_return_col]

                # 剔除无效值
                valid_mask = factor_values.notna() & return_values.notna()
                if valid_mask.sum() < 10:  # 至少10个有效样本
                    continue

                if method == 'spearman':
                    ic, _ = stats.spearmanr(
                        factor_values[valid_mask],
                        return_values[valid_mask]
                    )
                else:
                    ic, _ = stats.pearsonr(
                        factor_values[valid_mask],
                        return_values[valid_mask]
                    )
                ic_series[date] = ic

            return pd.Series(ic_series)

        # 整体IC
        return self.data[factor_name].corr(
            self.data[self.future_return_col],
            method=method
        )

    def calculate_icir(self, ic_series: pd.Series) -> float:
        """
        计算ICIR（IC信息比率）= IC均值 / IC标准差

        Args:
            ic_series: IC序列

        Returns:
            ICIR值
        """
        return ic_series.mean() / (ic_series.std() + 1e-8)

    def calculate_rank_ic(self, factor_name: str) -> float:
        """计算Rank IC"""
        rank_factor = self.data[factor_name].rank(pct=True)
        rank_return = self.data[self.future_return_col].rank(pct=True)
        return rank_factor.corr(rank_return)

    def ic_statistics(self, factor_name: str) -> Dict[str, float]:
        """
        计算IC统计信息

        Returns:
            {
                'ic_mean': IC均值,
                'ic_std': IC标准差,
                'icir': IC信息比率,
                'ic_abs_mean': IC绝对值均值,
                'ic_positive_ratio': IC为正的比例,
                't_stat': t统计量
            }
        """
        ic_series = self.calculate_ic(factor_name)

        return {
            'ic_mean': ic_series.mean(),
            'ic_std': ic_series.std(),
            'icir': self.calculate_icir(ic_series),
            'ic_abs_mean': ic_series.abs().mean(),
            'ic_positive_ratio': (ic_series > 0).sum() / len(ic_series),
            't_stat': ic_series.mean() / (ic_series.std() / np.sqrt(len(ic_series)))
        }

    def factor_decay_analysis(self, factor_name: str,
                            periods: List[int] = [1, 5, 10, 20]) -> pd.DataFrame:
        """
        因子衰减分析 - 计算不同持有期的IC

        Args:
            factor_name: 因子名称
            periods: 持有期列表

        Returns:
            不同持有期的IC值
        """
        results = {}

        for period in periods:
            future_col = f'future_{period}d_return'
            if future_col in self.data.columns:
                ic = self.data[factor_name].corr(
                    self.data[future_col],
                    method='spearman'
                )
                results[period] = ic

        return pd.DataFrame.from_dict(results, orient='index', columns=['IC'])

    def layered_returns(self, factor_name: str, n_layers: int = 5) -> pd.DataFrame:
        """
        因子分层回测 - 计算各层平均收益

        Args:
            factor_name: 因子名称
            n_layers: 分层数

        Returns:
            各层统计信息
        """
        # 按日期分组计算分位数
        self.data[f'{factor_name}_layer'] = self.data.groupby('trade_date')[
            factor_name
        ].transform(lambda x: pd.qcut(x.rank(method='first'), n_layers, labels=False, duplicates='drop'))

        # 计算各层平均收益
        layer_returns = self.data.groupby(f'{factor_name}_layer')[self.future_return_col].agg([
            ('mean_return', 'mean'),
            ('std_return', 'std'),
            ('count', 'count')
        ])

        return layer_returns

    def evaluate_all_factors(self, factor_names: List[str]) -> pd.DataFrame:
        """批量评估所有因子"""
        results = []

        for factor_name in factor_names:
            try:
                stats = self.ic_statistics(factor_name)
                stats['factor_name'] = factor_name
                results.append(stats)
            except Exception as e:
                print(f"评估因子 {factor_name} 失败: {e}")

        return pd.DataFrame(results).set_index('factor_name')

    def is_valid_factor(self, factor_name: str,
                       min_ic: float = 0.02,
                       min_icir: float = 0.3) -> bool:
        """
        判断因子是否有效

        Args:
            factor_name: 因子名称
            min_ic: 最小IC阈值
            min_icir: 最小ICIR阈值

        Returns:
            是否为有效因子
        """
        stats = self.ic_statistics(factor_name)
        return abs(stats['ic_mean']) >= min_ic and abs(stats['icir']) >= min_icir
```

### 3. 因子合成引擎设计

```python
from typing import Dict, List, Callable, Optional
from sklearn.ensemble import RandomForestRegressor
import lightgbm as lgb

class FactorCompositor:
    """因子合成引擎"""

    def __init__(self, method: str = 'equal_weight'):
        """
        Args:
            method: 合成方法
                - 'equal_weight': 等权
                - 'ic_weight': IC加权
                - 'icir_weight': ICIR加权
                - 'max_icir': 最大化ICIR
                - 'ml': 机器学习
        """
        self.method = method
        self.weights = {}
        self.ml_model = None

    def standardize_factors(self, data: pd.DataFrame,
                           factor_names: List[str],
                           method: str = 'zscore') -> pd.DataFrame:
        """
        因子标准化

        Args:
            data: 原始数据
            factor_names: 因子列表
            method: 标准化方法

        Returns:
            标准化后的数据
        """
        result = data.copy()

        for factor in factor_names:
            if factor not in data.columns:
                continue

            # 按日期截面标准化
            result[f'{factor}_std'] = result.groupby('trade_date')[factor].transform(
                lambda x: (x - x.mean()) / (x.std() + 1e-8)
            )

            # 极端值处理
            result[f'{factor}_std'] = result.groupby('trade_date')[f'{factor}_std'].transform(
                lambda x: x.clip(x.quantile(0.01), x.quantile(0.99))
            )

        return result

    def calculate_equal_weights(self, factor_names: List[str]) -> Dict[str, float]:
        """计算等权重"""
        n = len(factor_names)
        return {factor: 1.0 / n for factor in factor_names}

    def calculate_ic_weights(self, factor_names: List[str],
                            evaluator: FactorEvaluator) -> Dict[str, float]:
        """
        计算IC权重

        权重 = |IC| / sum(|IC|)
        """
        ic_values = {}
        for factor in factor_names:
            ic_series = evaluator.calculate_ic(factor)
            ic_values[factor] = abs(ic_series.mean())

        total_ic = sum(ic_values.values())
        return {factor: ic / total_ic for factor, ic in ic_values.items()}

    def calculate_icir_weights(self, factor_names: List[str],
                              evaluator: FactorEvaluator) -> Dict[str, float]:
        """
        计算ICIR权重

        权重 = |ICIR| / sum(|ICIR|)
        """
        icir_values = {}
        for factor in factor_names:
            ic_series = evaluator.calculate_ic(factor)
            icir_values[factor] = abs(evaluator.calculate_icir(ic_series))

        total_icir = sum(icir_values.values())
        return {factor: icir / total_icir for factor, icir in icir_values.items()}

    def optimize_max_icir(self, factor_names: List[str],
                         evaluator: FactorEvaluator,
                         max_iter: int = 1000) -> Dict[str, float]:
        """
        优化权重以最大化ICIR（使用简单梯度法）

        这是一个简化的实现，实际可以使用更复杂的优化算法
        """
        from scipy.optimize import minimize

        def objective(weights):
            # 计算加权合成因子
            weighted_ic = sum(
                weights[i] * evaluator.calculate_ic(factor).mean()
                for i, factor in enumerate(factor_names)
            )
            return -abs(weighted_ic)  # 最大化IC = 最小化负IC

        # 约束：权重和为1，权重非负
        constraints = {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        bounds = [(0, 1) for _ in factor_names]

        # 初始等权重
        x0 = np.array([1.0 / len(factor_names)] * len(factor_names))

        result = minimize(objective, x0, bounds=bounds,
                         constraints=constraints, method='SLSQP')

        return dict(zip(factor_names, result.x))

    def train_ml_model(self, data: pd.DataFrame,
                      factor_names: List[str],
                      target_col: str,
                      model_type: str = 'lightgbm'):
        """
        训练机器学习模型

        Args:
            data: 训练数据
            factor_names: 因子列表
            target_col: 目标变量（未来收益）
            model_type: 'lightgbm' 或 'random_forest'
        """
        X = data[factor_names].fillna(0)
        y = data[target_col].fillna(0)

        if model_type == 'lightgbm':
            self.ml_model = lgb.LGBMRegressor(
                num_leaves=31,
                learning_rate=0.05,
                n_estimators=100,
                random_state=42
            )
        else:
            self.ml_model = RandomForestRegressor(
                n_estimators=100,
                max_depth=10,
                random_state=42
            )

        self.ml_model.fit(X, y)

        # 返回特征重要性
        importance = pd.DataFrame({
            'factor': factor_names,
            'importance': self.ml_model.feature_importances_
        }).sort_values('importance', ascending=False)

        return importance

    def compose(self, data: pd.DataFrame,
               factor_names: List[str],
               evaluator: Optional[FactorEvaluator] = None) -> pd.Series:
        """
        合成因子

        Args:
            data: 标准化后的数据
            factor_names: 因子列表
            evaluator: 因子评价器（用于IC相关方法）

        Returns:
            合成因子值
        """
        std_factor_names = [f'{f}_std' for f in factor_names]

        if self.method == 'equal_weight':
            self.weights = self.calculate_equal_weights(factor_names)

        elif self.method == 'ic_weight' and evaluator:
            self.weights = self.calculate_ic_weights(factor_names, evaluator)

        elif self.method == 'icir_weight' and evaluator:
            self.weights = self.calculate_icir_weights(factor_names, evaluator)

        elif self.method == 'max_icir' and evaluator:
            self.weights = self.optimize_max_icir(factor_names, evaluator)

        # 加权合成
        composite = pd.Series(0.0, index=data.index)
        for factor, weight in self.weights.items():
            composite += data[f'{factor}_std'] * weight

        return composite

    def get_feature_importance(self) -> Optional[pd.DataFrame]:
        """获取ML模型的特征重要性"""
        if self.ml_model is None:
            return None
        return pd.DataFrame({
            'factor': self.ml_model.feature_name_,
            'importance': self.ml_model.feature_importances_
        }).sort_values('importance', ascending=False)
```

### 4. 选股策略引擎设计

```python
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable

class SelectionMethod(Enum):
    """选股方法"""
    TOP_N = "top_n"  # 按综合评分选Top N
    LAYERED = "layered"  # 分层选股
    PERCENTILE = "percentile"  # 按分位数选股
    CONDITION = "condition"  # 条件过滤

@dataclass
class SelectionResult:
    """选股结果"""
    trade_date: str
    selected_stocks: List[str]
    weights: Dict[str, float]
    scores: Dict[str, float]

class FilterCondition:
    """过滤条件基类"""

    def __init__(self, name: str):
        self.name = name

    def filter(self, data: pd.DataFrame, date: str) -> pd.DataFrame:
        """应用过滤条件"""
        pass

class IndustryFilter(FilterCondition):
    """行业过滤"""

    def __init__(self, include_industries: List[str] = None,
                 exclude_industries: List[str] = None):
        super().__init__("industry_filter")
        self.include_industries = include_industries
        self.exclude_industries = exclude_industries

    def filter(self, data: pd.DataFrame, date: str) -> pd.DataFrame:
        """过滤行业"""
        date_data = data[data['trade_date'] == date].copy()

        if self.include_industries:
            date_data = date_data[
                date_data['industry'].isin(self.include_industries)
            ]

        if self.exclude_industries:
            date_data = date_data[
                ~date_data['industry'].isin(self.exclude_industries)
            ]

        return date_data

class MarketCapFilter(FilterCondition):
    """市值过滤"""

    def __init__(self, min_cap: float = None, max_cap: float = None):
        super().__init__("market_cap_filter")
        self.min_cap = min_cap
        self.max_cap = max_cap

    def filter(self, data: pd.DataFrame, date: str) -> pd.DataFrame:
        """过滤市值"""
        date_data = data[data['trade_date'] == date].copy()

        if self.min_cap is not None:
            date_data = date_data[date_data['market_cap'] >= self.min_cap]

        if self.max_cap is not None:
            date_data = date_data[date_data['market_cap'] <= self.max_cap]

        return date_data

class STFilter(FilterCondition):
    """ST股票过滤"""

    def __init__(self, exclude_st: bool = True):
        super().__init__("st_filter")
        self.exclude_st = exclude_st

    def filter(self, data: pd.DataFrame, date: str) -> pd.DataFrame:
        """过滤ST股票"""
        if not self.exclude_st:
            return data[data['trade_date'] == date].copy()

        date_data = data[data['trade_date'] == date].copy()
        date_data = date_data[~date_data['name'].str.contains('ST')]
        return date_data

class StockSelector:
    """选股策略引擎"""

    def __init__(self, method: SelectionMethod = SelectionMethod.TOP_N):
        self.method = method
        self.filters: List[FilterCondition] = []
        self.compositor = FactorCompositor(method='equal_weight')

    def add_filter(self, filter_cond: FilterCondition):
        """添加过滤条件"""
        self.filters.append(filter_cond)

    def remove_filter(self, filter_name: str):
        """移除过滤条件"""
        self.filters = [f for f in self.filters if f.name != filter_name]

    def select_by_top_n(self, data: pd.DataFrame, date: str,
                       factor_names: List[str],
                       top_n: int = 50) -> SelectionResult:
        """按综合评分选Top N股票"""
        date_data = data[data['trade_date'] == date].copy()

        # 应用过滤条件
        for filter_cond in self.filters:
            date_data = filter_cond.filter(date_data, date)

        # 计算综合评分
        std_factors = [f'{f}_std' for f in factor_names]
        date_data['composite_score'] = date_data[std_factors].mean(axis=1)

        # 选Top N
        date_data = date_data.nlargest(top_n, 'composite_score')

        # 等权权重
        weights = {row['ts_code']: 1.0 / len(date_data)
                  for _, row in date_data.iterrows()}

        scores = {row['ts_code']: row['composite_score']
                 for _, row in date_data.iterrows()}

        return SelectionResult(
            trade_date=date,
            selected_stocks=date_data['ts_code'].tolist(),
            weights=weights,
            scores=scores
        )

    def select_by_layer(self, data: pd.DataFrame, date: str,
                       factor_name: str,
                       n_layers: int = 5,
                       select_layer: int = 0) -> SelectionResult:
        """分层选股 - 选择指定层"""
        date_data = data[data['trade_date'] == date].copy()

        # 应用过滤条件
        for filter_cond in self.filters:
            date_data = filter_cond.filter(date_data, date)

        # 计算分位数
        date_data['layer'] = pd.qcut(
            date_data[factor_name].rank(method='first'),
            n_layers,
            labels=False,
            duplicates='drop'
        )

        # 选择指定层
        layer_data = date_data[date_data['layer'] == select_layer]

        weights = {row['ts_code']: 1.0 / len(layer_data)
                  for _, row in layer_data.iterrows()}

        scores = {row['ts_code']: row[factor_name]
                 for _, row in layer_data.iterrows()}

        return SelectionResult(
            trade_date=date,
            selected_stocks=layer_data['ts_code'].tolist(),
            weights=weights,
            scores=scores
        )

    def select_by_percentile(self, data: pd.DataFrame, date: str,
                            factor_name: str,
                            percentile: float = 0.8) -> SelectionResult:
        """按分位数选股"""
        date_data = data[data['trade_date'] == date].copy()

        # 应用过滤条件
        for filter_cond in self.filters:
            date_data = filter_cond.filter(date_data, date)

        # 计算阈值
        threshold = date_data[factor_name].quantile(percentile)
        selected = date_data[date_data[factor_name] >= threshold]

        weights = {row['ts_code']: 1.0 / len(selected)
                  for _, row in selected.iterrows()}

        scores = {row['ts_code']: row[factor_name]
                 for _, row in selected.iterrows()}

        return SelectionResult(
            trade_date=date,
            selected_stocks=selected['ts_code'].tolist(),
            weights=weights,
            scores=scores
        )

    def batch_select(self, data: pd.DataFrame,
                    dates: List[str],
                    factor_names: List[str],
                    top_n: int = 50) -> List[SelectionResult]:
        """批量选股"""
        results = []

        for date in dates:
            result = self.select_by_top_n(data, date, factor_names, top_n)
            results.append(result)

        return results
```

### 5. 组合构建器设计

```python
from enum import Enum
from typing import Dict, List, Optional
import cvxpy as cp

class WeightMethod(Enum):
    """权重分配方法"""
    EQUAL = "equal"  # 等权
    MARKET_CAP = "market_cap"  # 市值加权
    FACTOR = "factor"  # 因子值加权
    RISK_PARITY = "risk_parity"  # 风险平价
    MIN_VARIANCE = "min_variance"  # 最小方差
    MAX_DIVERSIFICATION = "max_diversification"  # 最大分散化

class PortfolioConstructor:
    """投资组合构建器"""

    def __init__(self, method: WeightMethod = WeightMethod.EQUAL):
        self.method = method

    def equal_weight(self, stocks: List[str]) -> Dict[str, float]:
        """等权分配"""
        n = len(stocks)
        return {stock: 1.0 / n for stock in stocks}

    def market_cap_weight(self, data: pd.DataFrame, date: str,
                         stocks: List[str]) -> Dict[str, float]:
        """市值加权"""
        date_data = data[data['trade_date'] == date]
        date_data = date_data[date_data['ts_code'].isin(stocks)]

        total_cap = date_data['market_cap'].sum()

        weights = {}
        for _, row in date_data.iterrows():
            weights[row['ts_code']] = row['market_cap'] / total_cap

        return weights

    def factor_weight(self, data: pd.DataFrame, date: str,
                     stocks: List[str],
                     factor_name: str) -> Dict[str, float]:
        """因子值加权"""
        date_data = data[data['trade_date'] == date]
        date_data = date_data[date_data['ts_code'].isin(stocks)]

        # 使用因子值的排名（避免极端值影响）
        factor_ranks = date_data[factor_name].rank(pct=True)
        total_rank = factor_ranks.sum()

        weights = {}
        for ts_code, rank in factor_ranks.items():
            weights[ts_code] = rank / total_rank

        return weights

    def risk_parity_weight(self, cov_matrix: pd.DataFrame,
                          max_iter: int = 1000,
                          tolerance: float = 1e-6) -> Dict[str, float]:
        """
        风险平价权重

        使每只股票对组合风险的贡献相等
        """
        n = len(cov_matrix)

        # 初始化权重
        w = np.ones(n) / n

        for _ in range(max_iter):
            # 计算资产对组合的边际风险贡献
            portfolio_var = w @ cov_matrix @ w
            marginal_contrib = cov_matrix @ w
            contrib = w * marginal_contrib

            # 更新权重
            new_w = 1 / (n * contrib)
            new_w = new_w / new_w.sum()

            # 检查收敛
            if np.max(np.abs(new_w - w)) < tolerance:
                break
            w = new_w

        return dict(zip(cov_matrix.index, w))

    def min_variance_weight(self, returns: pd.DataFrame,
                           cov_matrix: pd.DataFrame = None,
                           long_only: bool = True) -> Dict[str, float]:
        """
        最小方差组合

        优化问题：min w'Σw
        s.t. sum(w) = 1
        """
        if cov_matrix is None:
            cov_matrix = returns.cov() * 252  # 年化协方差

        n = len(cov_matrix)
        w = cp.Variable(n)

        # 目标函数：最小化方差
        risk = cp.quad_form(w, cov_matrix.values)
        objective = cp.Minimize(risk)

        # 约束条件
        constraints = [cp.sum(w) == 1]

        if long_only:
            constraints.append(w >= 0)

        # 求解
        problem = cp.Problem(objective, constraints)
        problem.solve()

        return dict(zip(cov_matrix.index, w.value))

    def max_diversification_weight(self, cov_matrix: pd.DataFrame,
                                  assets_std: pd.Series) -> Dict[str, float]:
        """
        最大分散化组合

        最大化：w'σ / sqrt(w'Σw)
        """
        n = len(cov_matrix)
        w = cp.Variable(n)

        # 分散化比率
        portfolio_vol = cp.sqrt(cp.quad_form(w, cov_matrix.values))
        weighted_avg_std = assets_std.values @ w
        diversification_ratio = weighted_avg_std / portfolio_vol

        objective = cp.Maximize(diversification_ratio)

        # 约束条件
        constraints = [cp.sum(w) == 1, w >= 0]

        # 求解
        problem = cp.Problem(objective, constraints)
        problem.solve()

        return dict(zip(cov_matrix.index, w.value))

    def construct(self, data: pd.DataFrame, date: str,
                 stocks: List[str],
                 returns: pd.DataFrame = None,
                 factor_name: str = None,
                 cov_matrix: pd.DataFrame = None) -> Dict[str, float]:
        """
        构建投资组合

        Args:
            data: 数据
            date: 日期
            stocks: 股票列表
            returns: 收益率数据（用于风险模型）
            factor_name: 因子名称（用于因子加权）
            cov_matrix: 协方差矩阵（用于风险模型）

        Returns:
            股票权重字典
        """
        if self.method == WeightMethod.EQUAL:
            return self.equal_weight(stocks)

        elif self.method == WeightMethod.MARKET_CAP:
            return self.market_cap_weight(data, date, stocks)

        elif self.method == WeightMethod.FACTOR:
            if factor_name is None:
                raise ValueError("factor_name is required for FACTOR method")
            return self.factor_weight(data, date, stocks, factor_name)

        elif self.method == WeightMethod.RISK_PARITY:
            if cov_matrix is None:
                raise ValueError("cov_matrix is required for RISK_PARITY method")
            return self.risk_parity_weight(cov_matrix)

        elif self.method == WeightMethod.MIN_VARIANCE:
            if returns is None:
                raise ValueError("returns is required for MIN_VARIANCE method")
            return self.min_variance_weight(returns, cov_matrix)

        elif self.method == WeightMethod.MAX_DIVERSIFICATION:
            if cov_matrix is None:
                raise ValueError("cov_matrix is required for MAX_DIVERSIFICATION method")
            assets_std = np.sqrt(np.diag(cov_matrix))
            return self.max_diversification_weight(cov_matrix, assets_std)

        raise ValueError(f"Unknown method: {self.method}")
```

### 6. 因子生命周期管理设计

```python
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import shutil
import json

@dataclass
class FactorStatus:
    """因子状态"""
    name: str
    is_active: bool
    create_date: str
    retire_date: Optional[str] = None
    retire_reason: str = ""
    ic_history: List[float] = None
    icir_history: List[float] = None

class FactorGraveyard:
    """因子墓地 - 管理退场因子"""

    def __init__(self, graveyard_path: str = 'factor_graveyard'):
        self.graveyard_path = graveyard_path
        os.makedirs(graveyard_path, exist_ok=True)
        self.status_file = os.path.join(graveyard_path, 'factor_status.json')
        self._load_status()

    def _load_status(self):
        """加载因子状态"""
        if os.path.exists(self.status_file):
            with open(self.status_file, 'r') as f:
                data = json.load(f)
                self.status = {
                    name: FactorStatus(**status)
                    for name, status in data.items()
                }
        else:
            self.status = {}

    def _save_status(self):
        """保存因子状态"""
        data = {
            name: {
                'name': s.name,
                'is_active': s.is_active,
                'create_date': s.create_date,
                'retire_date': s.retire_date,
                'retire_reason': s.retire_reason,
                'ic_history': s.ic_history or [],
                'icir_history': s.icir_history or []
            }
            for name, s in self.status.items()
        }
        with open(self.status_file, 'w') as f:
            json.dump(data, f, indent=2)

    def register_factor(self, name: str):
        """注册新因子"""
        if name not in self.status:
            self.status[name] = FactorStatus(
                name=name,
                is_active=True,
                create_date=datetime.now().strftime('%Y-%m-%d'),
                ic_history=[],
                icir_history=[]
            )
            self._save_status()

    def retire_factor(self, name: str, reason: str):
        """退场因子"""
        if name in self.status:
            self.status[name].is_active = False
            self.status[name].retire_date = datetime.now().strftime('%Y-%m-%d')
            self.status[name].retire_reason = reason
            self._save_status()

            # 移动因子文件到墓地
            factor_file = f'factors/{name}.py'
            if os.path.exists(factor_file):
                shutil.move(factor_file,
                           os.path.join(self.graveyard_path, f'{name}.py'))

    def revive_factor(self, name: str):
        """复活因子"""
        if name in self.status and not self.status[name].is_active:
            self.status[name].is_active = True
            self.status[name].retire_date = None
            self.status[name].retire_reason = ""
            self._save_status()

            # 移回因子文件
            grave_file = os.path.join(self.graveyard_path, f'{name}.py')
            if os.path.exists(grave_file):
                shutil.move(grave_file, f'factors/{name}.py')

    def update_performance(self, name: str, ic: float, icir: float):
        """更新因子表现"""
        if name in self.status:
            self.status[name].ic_history.append(ic)
            self.status[name].icir_history.append(icir)
            self._save_status()

    def check_underperforming_factors(self,
                                     min_icir: float = 0.3,
                                     consecutive_periods: int = 3) -> List[str]:
        """
        检查表现不佳的因子

        Args:
            min_icir: 最小ICIR阈值
            consecutive_periods: 连续低ICIR的期数

        Returns:
            需要退场的因子列表
        """
        underperforming = []

        for name, status in self.status.items():
            if not status.is_active:
                continue

            if len(status.icir_history) < consecutive_periods:
                continue

            # 检查最近N期ICIR
            recent_icir = status.icir_history[-consecutive_periods:]
            if all(icir < min_icir for icir in recent_icir):
                underperforming.append(name)

        return underperforming

    def get_active_factors(self) -> List[str]:
        """获取活跃因子列表"""
        return [name for name, status in self.status.items()
                if status.is_active]

    def get_retired_factors(self) -> List[str]:
        """获取已退场因子列表"""
        return [name for name, status in self.status.items()
                if not status.is_active]
```

### 7. 整合到Backtrader

```python
import backtrader as bt

class MultiFactorStrategy(bt.Strategy):
    """多因子选股策略 - Backtrader集成"""

    params = (
        # 因子配置
        ('factor_names', ['momentum_20', 'volatility_20', 'pe_ttm_inv', 'roe_ttm']),
        ('factor_method', 'equal_weight'),  # equal_weight, ic_weight, icir_weight

        # 选股配置
        ('top_n', 50),
        ('rebalance_days', 20),  # 调仓周期

        # 组合配置
        ('weight_method', 'equal'),  # equal, market_cap, factor

        # 过滤条件
        ('exclude_st', True),
        ('min_market_cap', None),
        ('max_market_cap', None),
    )

    def __init__(self):
        # 初始化因子计算器
        self.factors = {}
        for factor_name in self.params.factor_names:
            factor_class = get_factor(factor_name)
            self.factors[factor_name] = factor_class()

        # 初始化因子合成器
        self.compositor = FactorCompositor(method=self.params.factor_method)

        # 初始化选股器
        self.selector = StockSelector(method=SelectionMethod.TOP_N)
        if self.params.exclude_st:
            self.selector.add_filter(STFilter(exclude_st=True))
        if self.params.min_market_cap or self.params.max_market_cap:
            self.selector.add_filter(MarketCapFilter(
                min_cap=self.params.min_market_cap,
                max_cap=self.params.max_market_cap
            ))

        # 初始化组合构建器
        self.constructor = PortfolioConstructor(method=self.params.weight_method)

        # 调仓计数器
        self.days_since_rebalance = 0

        # 当前持仓
        self.current_positions = {}

    def next(self):
        """每个bar调用"""
        self.days_since_rebalance += 1

        # 判断是否需要调仓
        if self.days_since_rebalance >= self.params.rebalance_days:
            self._rebalance()
            self.days_since_rebalance = 0

    def _rebalance(self):
        """执行调仓"""
        # 获取当前日期的所有股票数据
        current_data = self._get_cross_section_data()

        # 计算因子值
        for factor_name, factor in self.factors.items():
            current_data[factor_name] = factor.calculate(current_data)

        # 标准化因子
        current_data = self.compositor.standardize_factors(
            current_data,
            self.params.factor_names
        )

        # 选股
        selection_result = self.selector.select_by_top_n(
            current_data,
            self.datas[0].datetime.date(0),
            self.params.factor_names,
            self.params.top_n
        )

        # 构建组合
        if self.params.weight_method == 'equal':
            weights = selection_result.weights
        else:
            # 其他权重方法需要额外数据
            weights = selection_result.weights

        # 执行交易
        self._execute_trades(weights)

    def _get_cross_section_data(self) -> pd.DataFrame:
        """获取截面数据"""
        # 从data feeds中获取当前所有股票的数据
        data_dict = {}

        for data in self.datas:
            if len(data) > 0:
                ts_code = data._name
                data_dict[ts_code] = {
                    'open': data.open[0],
                    'high': data.high[0],
                    'low': data.low[0],
                    'close': data.close[0],
                    'volume': data.volume[0],
                    # ... 其他字段
                }

        return pd.DataFrame.from_dict(data_dict, orient='index')

    def _execute_trades(self, target_weights: Dict[str, float]):
        """执行交易"""
        # 平仓不在目标组合中的股票
        for stock in list(self.current_positions.keys()):
            if stock not in target_weights:
                self.order_target_percent(data=stock, target=0)

        # 调整到目标权重
        for stock, weight in target_weights.items():
            self.order_target_percent(data=stock, target=weight)

        # 更新当前持仓
        self.current_positions = target_weights.copy()

# 使用示例
def run_multi_factor_backtest():
    cerebro = bt.Cerebro()

    # 添加数据
    # ... 添加多只股票的数据

    # 添加策略
    cerebro.addstrategy(
        MultiFactorStrategy,
        factor_names=['momentum_20', 'volatility_20', 'pe_ttm_inv', 'roe_ttm'],
        factor_method='equal_weight',
        top_n=50,
        rebalance_days=20
    )

    # 运行回测
    result = cerebro.run()
```

---

## 实施计划

### 第一阶段：基础框架搭建（2周）

1. 实现FactorBase基类和因子注册机制
2. 实现FactorEvaluator评价器
3. 添加常用技术因子（动量、波动率、RSI等）
4. 单元测试

### 第二阶段：因子扩展（2周）

1. 添加财务因子（PE、PB、ROE、营收增长等）
2. 添加情绪因子（换手率、涨跌停等）
3. 实现因子标准化和极端值处理
4. 单元测试

### 第三阶段：因子合成与选股（2周）

1. 实现FactorCompositor合成引擎
2. 实现StockSelector选股引擎
3. 实现PortfolioConstructor组合构建器
4. 集成测试

### 第四阶段：因子生命周期管理（1周）

1. 实现FactorGraveyard
2. 实现因子监控和退场机制
3. 单元测试

### 第五阶段：Backtrader集成（2周）

1. 实现MultiFactorStrategy
2. 实现多数据源处理
3. 集成测试
4. 文档编写

### 第六阶段：优化与完善（1周）

1. 性能优化
2. 边界情况处理
3. 错误处理
4. 用户文档

---

## API兼容性保证

1. **新增功能不影响现有API**：所有新增功能作为独立模块
2. **可选集成**：用户可以选择性使用多因子功能
3. **向后兼容**：现有策略继续正常工作
4. **渐进式迁移**：用户可以逐步将策略迁移到新框架

---

## 使用示例

### 示例1：计算因子并评价

```python
# 加载数据
data = pd.read_csv('stock_data.csv')

# 初始化评价器
evaluator = FactorEvaluator(data, future_return_col='future_5d_return')

# 评价因子
stats = evaluator.ic_statistics('momentum_20')
print(f"IC均值: {stats['ic_mean']:.4f}")
print(f"ICIR: {stats['icir']:.4f}")
```

### 示例2：因子合成

```python
# 初始化合成器
compositor = FactorCompositor(method='ic_weight')

# 标准化因子
std_data = compositor.standardize_factors(
    data,
    ['momentum_20', 'volatility_20', 'pe_ttm_inv']
)

# 合成因子
composite = compositor.compose(
    std_data,
    ['momentum_20', 'volatility_20', 'pe_ttm_inv'],
    evaluator=evaluator
)
```

### 示例3：选股策略

```python
# 初始化选股器
selector = StockSelector(method=SelectionMethod.TOP_N)
selector.add_filter(STFilter(exclude_st=True))
selector.add_filter(MarketCapFilter(min_cap=50))  # 市值>50亿

# 选股
result = selector.select_by_top_n(
    data,
    '2024-01-01',
    ['momentum_20', 'volatility_20', 'pe_ttm_inv'],
    top_n=50
)

print(f"选中股票: {len(result.selected_stocks)}只")
```

### 示例4：Backtrader回测

```python
cerebro = bt.Cerebro()

# 添加策略
cerebro.addstrategy(
    MultiFactorStrategy,
    factor_names=['momentum_20', 'volatility_20', 'pe_ttm_inv'],
    factor_method='icir_weight',
    top_n=50,
    rebalance_days=20
)

# 添加多只股票数据
for stock in stock_list:
    data = bt.feeds.PandasData(dataname=load_stock_data(stock))
    cerebro.adddata(data, name=stock)

# 运行回测
result = cerebro.run()
```
