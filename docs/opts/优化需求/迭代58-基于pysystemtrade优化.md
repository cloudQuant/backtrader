### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/pysystemtrade
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### pysystemtrade项目简介
pysystemtrade是Rob Carver开发的系统化交易框架，基于其著作《Systematic Trading》，具有以下核心特点：
- **理论基础**: 基于完整的系统化交易理论
- **期货交易**: 专注于期货市场的系统化交易
- **预测组合**: 多种预测信号的组合方法
- **仓位调整**: 科学的仓位管理和调整
- **成本优化**: 交易成本的最优化
- **生产级别**: 支持真实的生产环境部署

### 重点借鉴方向
1. **系统理论**: 系统化交易的理论框架
2. **预测规则**: ForecastScalarFixed预测规则设计
3. **仓位管理**: Position sizing科学方法
4. **组合优化**: Portfolio优化算法
5. **成本分析**: 滑点和成本建模
6. **生产系统**: 生产环境的系统设计

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
| **Sizer** | 仓位管理（基础） |

### 1.2 当前优势

1. **成熟的 Line 系统**：高效的圆形缓冲区
2. **丰富的功能库**：60+ 指标、22 种分析器
3. **多种运行模式**：runonce、next、live
4. **性能优化**：Cython 扩展、TS/CS 模式

### 1.3 相对不足

1. **仓位管理**：仅提供基础的 Sizer 接口
2. **信号组合**：无多信号组合机制
3. **成本分析**：简化的手续费模型
4. **波动率目标**：无系统性波动率目标管理

---

## 二、PySystemTrade 项目深度分析

### 2.1 核心架构：阶段化设计模式

PySystemTrade 采用独特的**阶段化架构**（Stage-based Architecture）：

```
数据阶段 (RawData)
    ↓
规则阶段 (Rules) → Raw Forecast
    ↓
预测缩放阶段 (ForecastScaleCap) → Scaled Forecast
    ↓
预测组合阶段 (ForecastCombine) → Combined Forecast
    ↓
仓位调整阶段 (PositionSizing) → Subsystem Position
    ↓
组合阶段 (Portfolios) → Portfolio Position
    ↓
账户阶段 (Accounts) → Actual Position
```

### 2.2 预测系统（核心创新）

#### 2.2.1 预测流程

```
Raw Forecast
    ↓ [Scaling by Forecast Scalar]
Scaled Forecast
    ↓ [Capping at ±20]
Capped Forecast
    ↓ [Weighting by Forecast Weights]
Weighted Forecasts
    ↓ [Sum + FDM]
Combined Forecast
```

**关键代码**（`forecast_scale_cap.py:65-105`）：
```python
def get_capped_forecast(self, instrument_code, rule_variation_name):
    scaled_forecast = self.get_scaled_forecast(instrument_code, rule_variation_name)
    upper_cap = self.get_forecast_cap()  # 默认 20
    lower_floor = self.get_forecast_floor()  # 默认 -20
    return scaled_forecast.clip(upper=upper_cap, lower=lower_floor)

def get_scaled_forecast(self, instrument_code, rule_variation_name):
    raw_forecast = self.get_raw_forecast(instrument_code, rule_variation_name)
    forecast_scalar = self.get_forecast_scalar(instrument_code, rule_variation_name)
    return raw_forecast * forecast_scalar
```

#### 2.2.2 预测缩放器（Forecast Scalar）

预测缩放器的目标是使预测的**平均绝对值**等于目标值（默认 10）：

```python
# 固定缩放器
forecast_scalar = target_abs_forecast / avg_abs_forecast

# 估计缩放器（使用滚动窗口）
forecast_scalar = ts_estimator(cs_forecasts, target_abs_forecast=10)
```

#### 2.2.3 预测分散化乘数（FDM）

FDM 用于调整组合预测，考虑预测之间的相关性：

```python
# forecast_combine.py:1107-1164
def get_forecast_diversification_multiplier_estimated(self, instrument_code):
    correlation_list = self.get_forecast_correlation_matrices(instrument_code)
    weight_df = self.get_forecast_weights(instrument_code)

    # FDM = 1 / sqrt(weights.T @ corr @ weights)
    ts_fdm = idm_func(correlation_list, weight_df, **div_mult_params)
    return ts_fdm
```

### 2.3 仓位管理系统

#### 2.3.1 波动率目标仓位调整

核心公式（`positionsizing.py:126-133`）：

```python
# Kelly 公式变体
subsystem_position_raw = vol_scalar * forecast / avg_abs_forecast

# 其中：
vol_scalar = daily_cash_vol_target / instr_value_vol
# daily_cash_vol_target = annual_vol_target% * capital / sqrt(252)
# instr_value_vol = block_value * daily_percentage_vol
```

**完整流程**：
```
1. 获取目标波动率（如年化 16%）
2. 计算日波动率目标：16% / sqrt(252) ≈ 1%
3. 计算工具波动率：block_value * daily_vol
4. 计算波动率缩放因子：vol_target / instr_vol
5. 计算仓位：vol_scalar * forecast / avg_abs_forecast
```

#### 2.3.2 Buffer 系统

防止过度交易的缓冲机制（`buffering.py`）：

```python
def calculate_buffers(position, vol_scalar, **kwargs):
    # 根据波动率和绝对仓位大小计算缓冲区
    # 波动率越大，缓冲区越大
    # 仓位越大，缓冲区越大
    pass
```

### 2.4 组合优化系统

#### 2.4.1 工具分散化乘数（IDM）

```python
# portfolio.py:289-330
def get_estimated_instrument_diversification_multiplier(self):
    correlation_list = self.get_instrument_correlation_matrix()
    weight_df = self.get_instrument_weights()

    # 类似 FDM，但用于工具级别
    ts_idm = idm_func(correlation_list, weight_df, **div_mult_params)
    return ts_idm
```

#### 2.4.2 工具权重估计

支持多种权重估计方法（`portfolio.py:622-651`）：
- **固定权重**：用户指定
- **等权重**：1/N
- **估计权重**：基于历史回报优化（shrinkage、bootstrap 等）

### 2.5 成本分析系统

#### 2.5.1 夏普比率成本

```python
# sysproduction/reporting/data/costs.py
def get_SR_cost_calculation_for_instrument(data, instrument_code):
    # SR_cost = cost_per_trade / (price * ann_stdev)
    # 以夏普比率单位表示交易成本
    SR_cost = costs_object.calculate_sr_cost(
        blocks_traded=blocks_traded,
        block_price_multiplier=block_price_multiplier,
        ann_stdev_price_units=ann_stdev_price_units,
        price=price,
    )
    return dict(SR_cost=SR_cost, percentage_cost=percentage_cost)
```

#### 2.5.2 滑点分解

```python
# sysproduction/reporting/data/trades.py
# 滑点来源分解：
delay_slippage = price_slippage(...)           # 延迟导致的滑点
bid_ask_slippage = calculate_bid_ask_slippage(...)  # 买卖价差
execution_slippage = calculate_execution_slippage(...)  # 执行滑点
versus_limit_slippage = calculate_limit_order_slippage(...)  # 限价单滑点

total_slippage = delay + bid_ask + execution + versus_limit
```

### 2.6 缓存系统

三级缓存机制（`system_cache.py`）：

```python
@input          # 输入缓存：来自其他阶段
@diagnostic     # 诊断缓存：中间结果
@output         # 输出缓存：关键输出
@dont_cache      # 不缓存：每次重新计算
```

---

## 三、架构对比分析

| 维度 | Backtrader | PySystemTrade |
|------|------------|---------------|
| **架构模式** | 事件驱动 | 阶段化流水线 |
| **信号处理** | 单一策略逻辑 | 多规则预测组合 |
| **仓位管理** | Sizer（基础） | 波动率目标仓位 |
| **组合管理** | 手动实现 | 内置组合优化 |
| **成本分析** | 简单手续费 | SR 成本 + 滑点分解 |
| **缓存系统** | 无 | 三级智能缓存 |
| **理论支持** | 技术分析为主 | 完整系统化交易理论 |
| **生产级别** | 中 | 高（监控、报告） |

---

# 需求文档

## 一、优化目标

借鉴 PySystemTrade 的系统化交易理论，为 backtrader 新增以下高级功能：

1. **预测组合系统**：多信号规则组合和 FDM
2. **波动率目标仓位**：科学的仓位管理
3. **组合优化器**：工具级组合管理
4. **成本分析器**：SR 成本和滑点分解
5. **智能缓存系统**：三级缓存提升性能

## 二、功能需求

### FR1: 预测组合系统

**优先级**：高

**描述**：
实现类似 PySystemTrade 的预测组合系统，支持多个交易规则的信号组合。

**功能点**：
1. 预测缩放（Forecast Scaling）：使预测平均绝对值等于目标
2. 预测限制（Forecast Capping）：限制预测在 ±20 范围内
3. 预测权重（Forecast Weights）：支持固定和估计权重
4. 预测分散化乘数（FDM）：基于相关性调整组合预测
5. EWMA 权重平滑

**API 设计**：
```python
import backtrader as bt

# 创建预测组合器
forecast_combiner = bt.forecast.ForecastCombiner(
    target_abs_forecast=10.0,      # 目标平均绝对预测
    forecast_cap=20.0,             # 预测上限
    forecast_floor=-20.0,          # 预测下限
    fdm_method='estimated',        # FDM 方法: 'fixed' | 'estimated'
    weight_ewma_span=125,          # 权重平滑窗口
)

# 添加预测规则
forecast_combiner.add_rule(
    name='ewmac8',
    rule_func=ewmac_forecast,
    data='data.close',
    weight=0.5,
    forecast_scalar=5.3,
)

forecast_combiner.add_rule(
    name='ewmac16',
    rule_func=ewmac_forecast,
    data='data.close',
    weight=0.5,
    forecast_scalar=5.3,
)

# 在策略中使用
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.combined_forecast = forecast_combiner(self.data)

    def next(self):
        if self.combined_forecast[0] > 10:
            self.buy()
        elif self.combined_forecast[0] < -10:
            self.sell()
```

### FR2: 波动率目标仓位管理

**优先级**：高

**描述**：
实现基于波动率目标的仓位管理系统，确保组合波动率符合目标。

**功能点**：
1. 目标波动率设置（如年化 16%）
2. 工具波动率计算
3. 波动率缩放因子计算
4. Buffer 系统防止过度交易
5. 长仓约束支持

**API 设计**：
```python
import backtrader as bt

# 波动率目标 Sizer
class VolTargetSizer(bt.Sizer):
    params = (
        ('target_vol', 0.16),        # 年化目标波动率
        ('annualization', 252),       # 年化系数
        ('use_buffer', True),         # 使用缓冲区
        ('buffer_pct', 0.10),        # 缓冲区百分比
    )

    def _getsizing(self, comminfo, data, isbuy):
        # 获取当前价格
        price = data.close[0]

        # 计算工具波动率
        instr_vol = self.get_instrument_volatility(data)

        # 计算波动率缩放因子
        daily_vol_target = self.p.target_vol / (self.p.annualization ** 0.5)
        vol_scalar = daily_vol_target / instr_vol

        # 获取预测信号
        forecast = self.get_forecast()

        # 计算目标仓位
        target_pos = vol_scalar * forecast / self.avg_abs_forecast

        # 应用缓冲区
        if self.p.use_buffer:
            target_pos = self.apply_buffer(target_pos)

        return int(target_pos)
```

### FR3: 组合优化器

**优先级**：中

**描述**：
实现工具级组合优化，支持工具权重估计和分散化乘数。

**功能点**：
1. 工具权重优化（固定、等权重、估计）
2. 工具分散化乘数（IDM）
3. 相关性矩阵估计
4. 组合波动率计算
5. 风险覆盖系统

**API 设计**：
```python
import backtrader as bt

# 组合优化器
optimizer = bt.portfolio.PortfolioOptimizer(
    target_vol=0.16,
    idm_method='estimated',        # IDM 方法
    weight_method='shrinkage',     # 权重估计方法
    rebalance_freq='M',            # 再平衡频率
    max_leverage=3.0,              # 最大杠杆
)

# 添加工具
optimizer.add_instrument('EDOLLAR', weight=0.5)
optimizer.add_instrument('US10', weight=0.5)

# 获取优化后的仓位
optimized_positions = optimizer.get_positions()
```

### FR4: 成本分析器

**优先级**：中

**描述**：
实现详细的交易成本分析，包括 SR 成本和滑点分解。

**功能点**：
1. 夏普比率成本计算
2. 百分比成本计算
3. 滑点来源分解
4. 换手率分析
5. 成本可视化

**API 设计**：
```python
import backtrader as bt

# 成本分析器
class CostAnalyzer(bt.Analyzer):
    params = (
        ('ann_vol', 0.16),           # 年化波动率
        ('cost_basis', 'SR'),        # 成本基准: 'SR' | 'percentage'
    )

    def get_analysis(self):
        return dict(
            sr_cost=self._sr_cost,
            percentage_cost=self._pct_cost,
            slippage_breakdown=self._slippage_breakdown,
            turnover=self._turnover,
        )

# 使用
cerebro.addanalyzer(CostAnalyzer, ann_vol=0.16)
results = cerebro.run()
cost_analysis = results[0].analyzers.costanalyzer.get_analysis()
```

### FR5: 智能缓存系统

**优先级**：中

**描述**：
实现类似 PySystemTrade 的三级缓存系统，提升回测性能。

**功能点**：
1. Input 缓存：来自其他模块的输入
2. Diagnostic 缓存：中间诊断结果
3. Output 缓存：关键输出结果
4. Protected 缓存：受保护的缓存
5. 缓存失效和更新策略

**API 设计**：
```python
import backtrader as bt
from backtrader.utils.cache import input, diagnostic, output, dont_cache

class MyIndicator(bt.Indicator):
    @input
    def get_price_data(self):
        # 来自数据源的输入，会被缓存
        return self.data.close[0]

    @diagnostic
    def calculate_intermediate(self):
        # 中间结果，会被缓存用于诊断
        return self.get_price_data() * 2

    @output
    def final_value(self):
        # 关键输出，会被缓存
        return self.calculate_intermediate() + 1

    @dont_cache
    def get_live_value(self):
        # 实时值，不缓存
        return self.data.volume[0]
```

---

## 三、非功能需求

### NFR1: 性能

- 缓存系统应提供 50% 以上的性能提升
- 波动率计算使用高效的滚动窗口

### NFR2: 兼容性

- 新增功能与现有 backtrader API 兼容
- 策略可以逐步迁移到新系统

### NFR3: 可用性

- 提供完整的文档和示例
- 清晰的错误提示

---

# 设计文档

## 一、总体架构设计

### 1.1 新增模块结构

```
backtrader/
├── forecast/               # 新增：预测组合模块
│   ├── __init__.py
│   ├── combiner.py         # 预测组合器
│   ├── scaling.py          # 预测缩放
│   ├── capping.py          # 预测限制
│   ├── weights.py          # 权重估计
│   ├── fdm.py              # 分散化乘数
│   └── rules.py            # 交易规则
├── sizers/
│   ├── voltarget.py        # 新增：波动率目标 Sizer
│   └── buffer.py           # 新增：缓冲区计算
├── portfolio/              # 新增：组合管理模块
│   ├── __init__.py
│   ├── optimizer.py        # 组合优化器
│   ├── idm.py              # 工具分散化乘数
│   └── weights.py          # 工具权重
├── analyzers/
│   └── cost.py             # 新增：成本分析器
└── utils/
    └── cache.py            # 新增：缓存装饰器
```

## 二、详细设计

### 2.1 预测组合器设计

**文件位置**：`backtrader/forecast/combiner.py`

**核心类**：

```python
class ForecastCombiner(bt.Indicator):
    """
    预测组合器

    组合多个预测规则，产生单一的组合预测信号。

    流程：
        Raw Forecast → Scaled → Capped → Weighted → Combined
    """

    params = (
        ('target_abs_forecast', 10.0),
        ('forecast_cap', 20.0),
        ('forecast_floor', -20.0),
        ('fdm_method', 'estimated'),      # 'fixed' | 'estimated'
        ('weight_ewma_span', 125),
        ('use_estimated_weights', False),
    )

    plotskip = True  # 不绘制

    def __init__(self):
        # 预测规则字典
        self.rules = {}

        # 组合预测线
        self.lines.combined_forecast = bt.LineZero()

    def add_rule(self, name, rule_func, data='close', weight=1.0,
                 forecast_scalar=None, other_args=None):
        """添加预测规则"""
        self.rules[name] = {
            'func': rule_func,
            'data': data,
            'weight': weight,
            'forecast_scalar': forecast_scalar,
            'other_args': other_args or {},
        }

    def calculate(self):
        """计算组合预测"""
        # 1. 获取所有原始预测
        raw_forecasts = self._get_raw_forecasts()

        # 2. 缩放预测
        scaled_forecasts = self._scale_forecasts(raw_forecasts)

        # 3. 限制预测
        capped_forecasts = self._cap_forecasts(scaled_forecasts)

        # 4. 获取权重
        weights = self._get_forecast_weights()

        # 5. 计算加权预测
        weighted_forecasts = capped_forecasts * weights

        # 6. 求和
        combined = weighted_forecasts.sum(axis=1)

        # 7. 应用 FDM
        fdm = self._get_fdm()
        self.lines.combined_forecast[0] = combined * fdm

    def _get_raw_forecasts(self):
        """获取所有原始预测"""
        forecasts = {}
        for name, rule in self.rules.items():
            # 获取数据
            data = self._get_data(rule['data'])

            # 计算预测
            forecast = rule['func'](data, **rule['other_args'])
            forecasts[name] = forecast
        return pd.DataFrame(forecasts)

    def _scale_forecasts(self, forecasts):
        """缩放预测使平均绝对值等于目标"""
        for col in forecasts.columns:
            rule = self.rules[col]

            if rule['forecast_scalar'] is not None:
                # 使用固定缩放器
                forecasts[col] = forecasts[col] * rule['forecast_scalar']
            else:
                # 使用估计缩放器
                avg_abs = forecasts[col].abs().rolling(500).mean()
                scalar = self.p.target_abs_forecast / avg_abs
                forecasts[col] = forecasts[col] * scalar

        return forecasts

    def _cap_forecasts(self, forecasts):
        """限制预测范围"""
        return forecasts.clip(
            lower=self.p.forecast_floor,
            upper=self.p.forecast_cap
        )

    def _get_forecast_weights(self):
        """获取预测权重"""
        if not self.p.use_estimated_weights:
            # 使用固定权重
            weights = pd.Series(
                [self.rules[name]['weight'] for name in self.rules.keys()],
                index=list(self.rules.keys())
            )
        else:
            # 使用估计权重（需要实现）
            weights = self._estimate_weights()

        # EWMA 平滑
        weights = weights.ewm(span=self.p.weight_ewma_span).mean()

        # 标准化
        weights = weights / weights.sum()

        return weights

    def _get_fdm(self):
        """获取预测分散化乘数"""
        if self.p.fdm_method == 'fixed':
            return 1.0
        else:
            # 估计 FDM
            forecasts = self._get_capped_forecasts()
            corr = forecasts.rolling(250).corr()

            # FDM = 1 / sqrt(w' @ C @ w)
            weights = self._get_forecast_weights()
            fdm = 1.0 / np.sqrt(weights.T @ corr.values @ weights)
            return fdm
```

### 2.2 波动率目标 Sizer 设计

**文件位置**：`backtrader/sizers/voltarget.py`

**核心类**：

```python
class VolTargetSizer(bt.Sizer):
    """
    基于波动率目标的仓位管理器

    目标：使投资组合的波动率达到预定目标（如年化 16%）

    公式：
        position = vol_scalar * forecast / avg_abs_forecast

    其中：
        vol_scalar = daily_vol_target / instrument_value_vol
    """

    params = (
        ('target_vol', 0.16),            # 年化目标波动率
        ('annualization', 252),           # 年化系数
        ('lookback', 30),                 # 波动率计算窗口
        ('avg_abs_forecast', 10.0),       # 平均绝对预测
        ('use_buffer', True),             # 使用缓冲区
        ('buffer_pct', 0.10),             # 缓冲区百分比
        ('long_only', False),             # 仅做多
    )

    def __init__(self):
        super().__init__()

    def _getsizing(self, comminfo, data, isbuy):
        # 当前价格
        price = data.close[0]

        # 计算工具波动率
        instr_value_vol = self._get_instrument_value_vol(data)

        # 计算日波动率目标
        daily_vol_target = self.p.target_vol / np.sqrt(self.p.annualization)

        # 计算波动率缩放因子
        vol_scalar = daily_vol_target / instr_value_vol

        # 获取预测信号（从策略获取）
        forecast = self.strategy.get_forecast()

        # 计算原始仓位
        raw_position = vol_scalar * forecast / self.p.avg_abs_forecast

        # 应用约束
        if self.p.long_only:
            raw_position = max(0, raw_position)

        # 计算合约数
        point_value = comminfo.getpseudosize()
        contracts = raw_position / point_value

        # 应用缓冲区
        if self.p.use_buffer:
            current_pos = self.strategy.getposition(data).size
            buffer = abs(current_pos) * self.p.buffer_pct
            buffer = max(buffer, 1)  # 至少1个合约的缓冲

            if abs(contracts - current_pos) < buffer:
                contracts = current_pos  # 不交易

        return int(contracts)

    def _get_instrument_value_vol(self, data):
        """
        计算工具价值波动率

        等于：价格 * 日收益率波动率
        """
        # 计算日收益率
        returns = data.close.get(size=self.p.lookback)
        returns = returns.pct_change().dropna()

        # 计算波动率
        daily_vol = returns.std()

        # 工具价值波动率
        instr_value_vol = data.close[0] * daily_vol

        return instr_value_vol
```

### 2.3 组合优化器设计

**文件位置**：`backtrader/portfolio/optimizer.py`

**核心类**：

```python
class PortfolioOptimizer:
    """
    组合优化器

    功能：
        1. 工具权重优化
        2. 分散化乘数计算
        3. 组合波动率控制
    """

    def __init__(self, target_vol=0.16, idm_method='estimated',
                 weight_method='shrinkage', max_leverage=3.0):
        self.target_vol = target_vol
        self.idm_method = idm_method
        self.weight_method = weight_method
        self.max_leverage = max_leverage

        self.instruments = {}  # 工具字典

    def add_instrument(self, code, data, weight=None):
        """添加工具"""
        self.instruments[code] = {
            'data': data,
            'weight': weight,
            'subsystem_position': None,
        }

    def optimize_weights(self, returns=None):
        """优化工具权重"""
        if self.weight_method == 'fixed':
            return self._get_fixed_weights()
        elif self.weight_method == 'equal':
            return self._get_equal_weights()
        elif self.weight_method == 'shrinkage':
            return self._shrinkage_weights(returns)
        else:
            raise ValueError(f"Unknown weight method: {self.weight_method}")

    def calculate_idm(self, weights=None, corr_matrix=None):
        """
        计算工具分散化乘数

        IDM = 1 / sqrt(w' @ C @ w)
        """
        if self.idm_method == 'fixed':
            return 1.0

        if weights is None:
            weights = self.optimize_weights()

        if corr_matrix is None:
            corr_matrix = self._estimate_correlation()

        w = np.array(list(weights.values()))
        C = corr_matrix.values

        idm = 1.0 / np.sqrt(w.T @ C @ w)
        return idm

    def get_positions(self):
        """获取优化后的仓位"""
        # 获取工具权重
        weights = self.optimize_weights()

        # 计算 IDM
        idm = self.calculate_idm()

        # 计算最终仓位
        positions = {}
        for code, instr in self.instruments.items():
            weight = weights.get(code, 0)
            subsystem_pos = instr['subsystem_position']

            # 最终仓位 = 子系统仓位 × 权重 × IDM
            positions[code] = subsystem_pos * weight * idm

        return positions

    def _shrinkage_weights(self, returns):
        """使用收缩估计器优化权重"""
        # Ledoit-Wolf 收缩估计
        # 简化实现
        n = len(self.instruments)
        if returns is not None:
            # 使用历史回报计算协方差
            cov = returns.cov()
            mu = returns.mean()

            # 简单的均值方差优化
            inv_cov = np.linalg.inv(cov)
            ones = np.ones(n)

            # 最优权重（无约束）
            w = inv_cov @ mu
            w = w / w.sum()
        else:
            # 等权重
            w = np.ones(n) / n

        return dict(zip(self.instruments.keys(), w))

    def _estimate_correlation(self):
        """估计工具相关性矩阵"""
        # 从数据中计算相关性
        returns_data = {}
        for code, instr in self.instruments.items():
            data = instr['data']
            returns = data.close.get(size=100).pct_change().dropna()
            returns_data[code] = returns

        df = pd.DataFrame(returns_data)
        return df.corr()
```

### 2.4 成本分析器设计

**文件位置**：`backtrader/analyzers/cost.py`

**核心类**：

```python
class CostAnalyzer(bt.Analyzer):
    """
    成本分析器

    分析交易成本，包括：
        1. SR 成本（夏普比率成本）
        2. 百分比成本
        3. 滑点分解
        4. 换手率
    """

    params = (
        ('ann_vol', 0.16),              # 年化波动率
        ('cost_basis', 'SR'),           # 成本基准
    )

    def __init__(self):
        super().__init__()

        self.trades = []        # 交易记录
        self.slippage = []      # 滑点记录
        self.turnover = []      # 换手率

    def notify_trade(self, trade):
        """记录交易"""
        self.trades.append({
            'pnl': trade.pnl,
            'commission': trade.commission,
            'size': trade.size,
            'price': trade.price,
            'value': trade.value,
        })

    def notify_order(self, order):
        """记录订单滑点"""
        if order.status == order.Completed:
            # 计算滑点
            executed = order.executed
            if hasattr(executed, 'slippage'):
                self.slippage.append({
                    'slippage': executed.slippage,
                    'pnl': executed.pnl,
                    'commission': executed.commission,
                })

    def get_analysis(self):
        """返回成本分析结果"""
        total_pnl = sum(t['pnl'] for t in self.trades)
        total_comm = sum(t['commission'] for t in self.trades)
        total_value = sum(abs(t['value']) for t in self.trades)

        # 百分比成本
        pct_cost = total_comm / total_value if total_value > 0 else 0

        # SR 成本
        daily_vol = self.p.ann_vol / np.sqrt(252)
        sr_cost = pct_cost / daily_vol

        # 滑点分析
        if self.slippage:
            total_slippage = sum(s['slippage'] for s in self.slippage)
            avg_slippage = total_slippage / len(self.slippage)
        else:
            avg_slippage = 0

        # 换手率
        if self.strategy.broker.getvalue() > 0:
            turnover = total_value / self.strategy.broker.getvalue()
        else:
            turnover = 0

        return dict(
            total_pnl=total_pnl,
            total_commission=total_comm,
            percentage_cost=pct_cost,
            sr_cost=sr_cost,
            avg_slippage=avg_slippage,
            turnover=turnover,
            num_trades=len(self.trades),
        )
```

### 2.5 缓存系统设计

**文件位置**：`backtrader/utils/cache.py`

**核心装饰器**：

```python
from functools import wraps
import hashlib
import pickle

class CacheManager:
    """缓存管理器"""

    def __init__(self):
        self._cache = {}
        self._input_cache = {}
        self._diagnostic_cache = {}
        self._output_cache = {}

    def get(self, key, cache_type='default'):
        """获取缓存值"""
        cache = self._get_cache(cache_type)
        return cache.get(key)

    def set(self, key, value, cache_type='default'):
        """设置缓存值"""
        cache = self._get_cache(cache_type)
        cache[key] = value

    def clear(self, cache_type=None):
        """清除缓存"""
        if cache_type is None:
            self._cache.clear()
            self._input_cache.clear()
            self._diagnostic_cache.clear()
            self._output_cache.clear()
        else:
            cache = self._get_cache(cache_type)
            cache.clear()

    def _get_cache(self, cache_type):
        """获取指定类型的缓存"""
        if cache_type == 'input':
            return self._input_cache
        elif cache_type == 'diagnostic':
            return self._diagnostic_cache
        elif cache_type == 'output':
            return self._output_cache
        else:
            return self._cache

# 全局缓存管理器
_cache_manager = CacheManager()

def input(func):
    """输入缓存装饰器"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        # 生成缓存键
        key = _make_cache_key(func.__name__, args, kwargs)

        # 检查缓存
        value = _cache_manager.get(key, 'input')
        if value is not None:
            return value

        # 计算并缓存
        value = func(self, *args, **kwargs)
        _cache_manager.set(key, value, 'input')
        return value

    return wrapper

def diagnostic(func):
    """诊断缓存装饰器"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        key = _make_cache_key(func.__name__, args, kwargs)

        value = _cache_manager.get(key, 'diagnostic')
        if value is not None:
            return value

        value = func(self, *args, **kwargs)
        _cache_manager.set(key, value, 'diagnostic')
        return value

    return wrapper

def output(func):
    """输出缓存装饰器"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        key = _make_cache_key(func.__name__, args, kwargs)

        value = _cache_manager.get(key, 'output')
        if value is not None:
            return value

        value = func(self, *args, **kwargs)
        _cache_manager.set(key, value, 'output')
        return value

    return wrapper

def dont_cache(func):
    """不缓存装饰器（标记用）"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        return func(self, *args, **kwargs)

    return wrapper

def _make_cache_key(func_name, args, kwargs):
    """生成缓存键"""
    key_parts = [func_name]

    # 添加参数
    for arg in args:
        key_parts.append(str(arg))

    # 添加关键字参数
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")

    key_string = ":".join(key_parts)
    return hashlib.md5(key_string.encode()).hexdigest()
```

## 三、实施计划

### Phase 1: 预测组合系统 (优先级：高)

1. 实现 ForecastCombiner 基础功能
2. 实现预测缩放和限制
3. 实现权重估计和 FDM
4. 单元测试

### Phase 2: 波动率目标仓位 (优先级：高)

1. 实现 VolTargetSizer
2. 实现 Buffer 系统
3. 集成测试

### Phase 3: 组合优化器 (优先级：中)

1. 实现 PortfolioOptimizer
2. 实现工具权重优化
3. 实现 IDM
4. 组合测试

### Phase 4: 成本分析器 (优先级：中)

1. 实现 CostAnalyzer
2. 实现 SR 成本计算
3. 实现滑点分解
4. 集成测试

### Phase 5: 缓存系统 (优先级：中)

1. 实现缓存管理器
2. 实现装饰器
3. 性能测试

### Phase 6: 文档和示例 (优先级：低)

1. API 文档
2. 使用示例
3. 教程

## 四、测试策略

### 4.1 单元测试

- 预测组合器：验证组合预测正确性
- 波动率 Sizer：验证仓位计算正确性
- 组合优化器：验证权重和 IDM 计算
- 成本分析器：验证成本计算正确性

### 4.2 集成测试

- 使用双均线策略进行测试
- 对比优化前后的策略表现
- 验证组合波动率目标

### 4.3 性能测试

- 测试缓存系统的性能提升
- 测试大数据量下的表现

---

## 附录

### A. 参考资料

1. **PySystemTrade**: https://github.com/robcarver17/pysystemtrade
2. **Systematic Trading**: Rob Carver 的著作
3. **波动率目标**: https://github.com/robcarver17/ pysystemtrade/blob/master/docs/volatility.md
4. **预测缩放**: https://github.com/robcarver17/ pysystemtrade/blob/master/docs/forecasting.md

### B. 代码示例

**完整策略示例**：

```python
import backtrader as bt
from backtrader.forecast import ForecastCombiner
from backtrader.sizers import VolTargetSizer
from backtrader.analyzers import CostAnalyzer

# EWMAC 预测规则
def ewmac_forecast(price, fast=8, slow=32):
    fast_ma = price.ewm(span=fast).mean()
    slow_ma = price.ewm(span=slow).mean()
    return (fast_ma - slow_ma) / price * 1000

# 创建策略
class SystematicStrategy(bt.Strategy):
    params = (
        ('target_vol', 0.16),
    )

    def __init__(self):
        # 创建预测组合器
        self.combiner = ForecastCombiner(
            target_abs_forecast=10.0,
            forecast_cap=20.0,
            fdm_method='estimated',
        )

        # 添加规则
        self.combiner.add_rule('ewmac8', ewmac_forecast, fast=8, slow=32, weight=0.5)
        self.combiner.add_rule('ewmac16', ewmac_forecast, fast=16, slow=64, weight=0.5)

        # 计算组合预测
        self.combined_forecast = self.combiner(self.data)

    def get_forecast(self):
        """获取当前预测信号"""
        return self.combined_forecast[0]

# 设置回测
cerebro = bt.Cerebro()

# 添加数据
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(SystematicStrategy, target_vol=0.16)

# 设置 Sizer
cerebro.addsizer(VolTargetSizer, target_vol=0.16)

# 添加成本分析器
cerebro.addanalyzer(CostAnalyzer, ann_vol=0.16)

# 运行
results = cerebro.run()
```

---

*文档版本：v1.0*
*创建日期：2026-01-08*
*作者：Claude*
