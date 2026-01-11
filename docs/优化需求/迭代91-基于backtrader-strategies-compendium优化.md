### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/backtrader-strategies-compendium
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### backtrader-strategies-compendium项目简介
backtrader-strategies-compendium是一个backtrader策略合集，具有以下核心特点：
- **策略合集**: 多种经典策略实现
- **示例代码**: 丰富的示例代码
- **策略模板**: 策略编写模板
- **最佳实践**: 策略编写最佳实践
- **文档完善**: 策略文档说明
- **实战经验**: 实战策略经验

### 重点借鉴方向
1. **策略模式**: 策略编写模式
2. **代码规范**: 代码规范参考
3. **策略分类**: 策略分类组织
4. **示例设计**: 示例代码设计
5. **最佳实践**: 最佳实践总结
6. **策略库**: 策略库设计

---

## 架构对比分析

### Backtrader 核心特点

**优势:**
1. **成熟的回测引擎**: Cerebro统一管理策略、数据、经纪商、分析器
2. **完整的策略系统**: 灵活的Strategy基类，支持多种策略编写方式
3. **丰富的指标库**: 60+内置技术指标
4. **灵活的数据源**: 支持多种数据格式和数据源
5. **完善的分析器**: 内置多种性能分析器

**局限:**
1. **缺少策略库**: 没有内置的常见策略集合
2. **策略模板缺失**: 缺少标准化的策略编写模板
3. **最佳实践不足**: 缺少策略编写的最佳实践指导
4. **代码示例不足**: 官方示例较少且分散
5. **策略对比困难**: 缺少统一的策略对比框架

### Backtrader-Strategies-Compendium 核心特点

**优势:**
1. **丰富的策略库**: 30+经过验证的交易策略
2. **统一的策略基类**: StrategyForComparison提供标准化接口
3. **完善的分类体系**: 按技术指标、复杂度、风格分类
4. **完整的回测环境**: 支持多策略对比和性能分析
5. **专业的风险管理**: 集成止损、止盈、移动止损、括号订单
6. **多数据源支持**: Yahoo、Alpha Vantage、本地文件
7. **详细的分析报告**: QuantStats HTML报告、多种性能指标
8. **策略参数化**: 所有策略参数可配置，便于调优
9. **多时间框架支持**: 1分钟到日线多周期分析
10. **相对强度筛选**: 内置市场相对强度分析

**局限:**
1. **数据源依赖**: 主要依赖Yahoo Finance，有请求限制
2. **专注股票市场**: 主要针对股票市场，其他市场支持不足
3. **实盘交易支持弱**: 主要面向回测研究
4. **文档分散**: 策略文档不够系统化

---

## 需求规格文档

### 1. 统一策略基类 (优先级: 高)

**需求描述:**
建立统一的策略基类，提供标准化的策略编写接口和通用功能。

**功能需求:**
1. **StrategyBase基类**: 定义统一策略接口
2. **can_buy/can_sell方法**: 标准化的买卖条件判断
3. **订单管理**: 统一的买入卖出执行逻辑
4. **参数化配置**: 支持策略参数配置
5. **日志记录**: 标准化的日志输出
6. **策略信息**: __str__方法提供策略描述

**非功能需求:**
1. 保持向后兼容现有Strategy类
2. 简化策略编写复杂度
3. 便于扩展和定制

### 2. 内置策略库 (优先级: 高)

**需求描述:**
建立常用策略库，提供经过验证的经典策略实现。

**功能需求:**
1. **趋势跟踪策略**: SuperTrend、EMA交叉、MACD、Ichimoku
2. **均值回归策略**: Bollinger Bands、RSI回归、均值回归
3. **动量策略**: RSI、MACD、Momentum、Stochastic
4. **成交量策略**: VWAP、成交量突破
5. **形态策略**: K线形态识别、价格形态
6. **多时间框架策略**: MTF分析、趋势共振

**非功能需求:**
1. 每个策略提供完整文档
2. 提供默认参数配置
3. 代码清晰易读

### 3. 策略对比框架 (优先级: 高)

**需求描述:**
建立多策略对比框架，便于评估不同策略表现。

**功能需求:**
1. **批量回测**: 同时回测多个策略
2. **性能对比**: 统一的对比指标（收益率、夏普、回撤等）
3. **对比报告**: 生成HTML/PDF对比报告
4. **参数扫描**: 支持策略参数优化
5. **排名系统**: 按多种指标对策略排名

**非功能需求:**
1. 对比结果准确可靠
2. 支持大规模回测

### 4. 风险管理增强 (优先级: 中)

**需求描述:**
增强策略的风险管理能力，提供多种风险控制工具。

**功能需求:**
1. **止损止盈**: 支持百分比和ATR止损
2. **移动止损**: Trailing Stop功能
3. **括号订单**: 同时设置止损和止盈
4. **仓位管理**: 固定仓位、等风险、凯利公式
5. **最大回撤控制**: 回撤超限停止交易
6. **每日亏损限制**: 单日最大亏损限制

**非功能需求:**
1. 风险控制逻辑可靠
2. 不影响策略主逻辑

### 5. 多数据源支持 (优先级: 中)

**需求描述:**
集成多种数据源，提供灵活的数据获取方式。

**功能需求:**
1. **Yahoo Finance**: 免费股票数据
2. **Alpha Vantage**: 免费金融数据API
3. **本地数据**: CSV/JSON/Pandas DataFrame
4. **数据库支持**: SQLite/PostgreSQL
5. **数据缓存**: 自动缓存已获取数据
6. **数据清洗**: 自动处理缺失值和异常值

**非功能需求:**
1. 数据获取稳定可靠
2. 支持并发请求

### 6. 策略文档生成 (优先级: 低)

**需求描述:**
自动生成策略文档，便于策略管理和分享。

**功能需求:**
1. **参数说明**: 自动提取策略参数
2. **策略描述**: 生成策略说明文档
3. **代码示例**: 生成使用示例
4. **性能报告**: 生成回测性能报告
5. **Markdown导出**: 支持Markdown格式导出

---

## 设计文档

### 1. 统一策略基类设计

#### 1.1 策略基类架构

```
                    ┌─────────────────────────┐
                    │   bt.Strategy (原生)     │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │   StrategyBase (新增)   │
                    │  - can_buy()            │
                    │  - can_sell()           │
                    │  - buy_by_size()        │
                    │  - sell_by_size()       │
                    │  - risk management      │
                    └────────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │ StrategyForComparison   │
                    │  - compare mode         │
                    │  - benchmark support    │
                    └─────────────────────────┘
```

#### 1.2 StrategyBase基类实现

```python
# backtrader/strategy/base.py
from backtrader.strategy import Strategy as BaseStrategy
import backtrader as bt
from datetime import datetime
import logging

class StrategyBase(BaseStrategy):
    """
    统一策略基类，提供标准化策略编写接口
    """
    # 基础参数
    params = (
        # 风险管理参数
        ('stop_loss', 0),              # 止损百分比 (0表示不使用)
        ('take_profit', 0),            # 止盈百分比
        ('trail_percent', 0),          # 移动止损百分比
        ('trail_amount', 0),           # 移动止损金额

        # 仓位管理参数
        ('position_size', 0.95),       # 默认仓位比例
        ('use_bracket', False),        # 是否使用括号订单
        ('enable_trails', False),      # 是否启用移动止损

        # 交易控制参数
        ('max_positions', 1),          # 最大持仓数量
        ('fractional', True),          # 是否支持分数交易

        # 日志控制
        ('show_orders', False),        # 是否显示订单详情
        ('log_level', 'INFO'),         # 日志级别
    )

    def __init__(self):
        super().__init__()
        self._setup_logging()
        self._order = None  # 当前挂单
        self._stop_order = None  # 止损订单
        self._take_order = None  # 止盈订单
        self.trade_count = 0  # 交易次数

    def _setup_logging(self):
        """设置日志"""
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self.logger.setLevel(getattr(logging, self.p.log_level, logging.INFO))

    def start(self):
        """策略开始时调用"""
        self.logger.info(f"=== 策略开始: {self.__class__.__name__} ===")
        self.logger.info(f"策略参数: {self.params}")

    def stop(self):
        """策略结束时调用"""
        self.logger.info(f"=== 策略结束: {self.__class__.__name__} ===")
        self.logger.info(f"总交易次数: {self.trade_count}")

    def next(self):
        """
        主交易逻辑，模板方法
        子类通常不需要重写此方法
        """
        # 如果有待处理订单，跳过
        if self._order and self._order.status == bt.Order.Submitted:
            return

        # 检查是否已达到最大持仓
        if len(self._position_opposites) >= self.p.max_positions:
            return

        # 执行交易逻辑
        if not self.position:  # 无持仓
            if self.can_buy():
                self.buy_by_size()
        else:  # 有持仓
            if self.can_sell():
                self.sell_by_size()

    def can_buy(self):
        """
        买入条件判断，子类必须实现

        Returns:
            bool: 是否满足买入条件
        """
        raise NotImplementedError("子类必须实现 can_buy() 方法")

    def can_sell(self):
        """
        卖出条件判断，子类必须实现

        Returns:
            bool: 是否满足卖出条件
        """
        raise NotImplementedError("子类必须实现 can_sell() 方法")

    def buy_by_size(self, size=None):
        """
        执行买入

        Args:
            size: 买入数量，如果为None则使用默认计算
        """
        if size is None:
            size = self._calculate_position_size()

        # 创建订单参数
        order_args = {'size': size}

        # 处理括号订单
        if self.p.use_bracket and self.p.stop_loss > 0 and self.p.take_profit > 0:
            # 计算止损止盈价格
            stop_price = self.data.close[0] * (1 - self.p.stop_loss)
            limit_price = self.data.close[0] * (1 + self.p.take_profit)

            self._order = self.buy_bracket(
                size=size,
                stopprice=stop_price,
                limitprice=limit_price,
                valid=bt.Order.GTD  # 当日有效
            )

            if self.p.show_orders:
                self.logger.info(f"括号订单买入: size={size}, stop={stop_price:.2f}, "
                               f"limit={limit_price:.2f}")
        else:
            # 处理移动止损
            if self.p.enable_trails and self.p.trail_percent > 0:
                order_args['trailpercent'] = self.p.trail_percent

            self._order = self.buy(**order_args)

            if self.p.show_orders:
                self.logger.info(f"买入: size={size}, price={self.data.close[0]:.2f}")

        self.trade_count += 1
        return self._order

    def sell_by_size(self, size=None):
        """
        执行卖出

        Args:
            size: 卖出数量，如果为None则卖出全部持仓
        """
        if size is None:
            size = self.position.size

        order_args = {'size': size}

        if self.p.enable_trails and self.p.trail_percent > 0:
            order_args['trailpercent'] = self.p.trail_percent

        self._order = self.sell(**order_args)

        if self.p.show_orders:
            self.logger.info(f"卖出: size={size}, price={self.data.close[0]:.2f}")

        self.trade_count += 1
        return self._order

    def _calculate_position_size(self):
        """
        计算仓位大小

        Returns:
            float: 仓位大小
        """
        cash = self.broker.getcash()
        price = self.data.close[0]

        # 使用账户资金的指定比例
        available = cash * self.p.position_size

        if self.p.fractional:
            size = available / price
        else:
            size = int(available / price)

        # 至少交易1单位
        return max(size, 1)

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.logger.info(f"买入成交: price={order.executed.price:.2f}, "
                               f"size={order.executed.size}, "
                               f"comm={order.executed.comm:.2f}")
            else:
                self.logger.info(f"卖出成交: price={order.executed.price:.2f}, "
                               f"size={order.executed.size}, "
                               f"comm={order.executed.comm:.2f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.logger.warning(f"订单失败: status={order.getstatusname()}")

        self._order = None

    def notify_trade(self, trade):
        """交易完成通知"""
        if trade.isclosed:
            self.logger.info(f"交易利润: gross={trade.pnl:.2f}, net={trade.pnlcomm:.2f}")

    def __str__(self):
        """策略描述"""
        desc = f"{self.__class__.__name__}("
        desc += f"stop_loss={self.p.stop_loss}, "
        desc += f"take_profit={self.p.take_profit}, "
        desc += f"position_size={self.p.position_size})"
        return desc


class StrategyForComparison(StrategyBase):
    """
    用于策略对比的增强基类
    """
    params = (
        ('benchmark', False),        # 是否作为基准
        ('benchmark_symbol', 'SPY'),  # 基准标的
    )

    def get_metrics(self):
        """
        获取策略性能指标

        Returns:
            dict: 性能指标字典
        """
        return {
            'name': self.__class__.__name__,
            'trades': self.trade_count,
            'final_value': self.broker.getvalue(),
        }
```

#### 1.3 策略模板示例

```python
# backtrader/strategies/templates.py
from backtrader.strategy.base import StrategyBase
import backtrader as bt

class SimpleMovingAverageCross(StrategyBase):
    """
    简单移动平均线交叉策略模板

    策略逻辑:
    - 当短期MA上穿长期MA时买入
    - 当短期MA下穿长期MA时卖出
    """
    params = (
        ('fast_period', 10),      # 快速均线周期
        ('slow_period', 30),      # 慢速均线周期
    )

    def __init__(self):
        super().__init__()
        # 初始化指标
        self.fast_ma = bt.indicators.SMA(self.data.close, period=self.p.fast_period)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=self.p.slow_period)
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def can_buy(self):
        """买入条件: 快线上穿慢线"""
        return self.crossover > 0

    def can_sell(self):
        """卖出条件: 快线下穿慢线"""
        return self.crossover < 0


class BollingerBandsStrategy(StrategyBase):
    """
    布林带策略模板

    策略逻辑:
    - 价格跌破下轨时买入（超卖）
    - 价格突破上轨时卖出（超买）
    """
    params = (
        ('period', 20),           # 布林带周期
        ('devfactor', 2.0),       # 标准差倍数
        ('dip_threshold', 0.01),  # 下跌阈值
        ('jump_threshold', 0.01), # 上涨阈值
    )

    def __init__(self):
        super().__init__()
        # 初始化布林带指标
        self.bbands = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

    def can_buy(self):
        """买入条件: 价格跌破下轨"""
        lower_band = self.bbands.lines.bot[0]
        return self.data.close[0] <= (1 - self.p.dip_threshold) * lower_band

    def can_sell(self):
        """卖出条件: 价格突破上轨"""
        upper_band = self.bbands.lines.top[0]
        return self.data.close[0] >= (1 + self.p.jump_threshold) * upper_band


class RSIDivergenceStrategy(StrategyBase):
    """
    RSI背离策略模板

    策略逻辑:
    - RSI超卖且价格背离时买入
    - RSI超买且价格背离时卖出
    """
    params = (
        ('rsi_period', 14),       # RSI周期
        ('oversold', 30),         # 超卖阈值
        ('overbought', 70),       # 超买阈值
        ('lookback', 5),          # 背离检测回看周期
    )

    def __init__(self):
        super().__init__()
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)

    def can_buy(self):
        """买入条件: RSI超卖"""
        return self.rsi[0] < self.p.oversold

    def can_sell(self):
        """卖出条件: RSI超买"""
        return self.rsi[0] > self.p.overbought
```

### 2. 内置策略库设计

#### 2.1 策略分类体系

```python
# backtrader/strategies/__init__.py

"""
策略分类:

1. 趋势跟踪策略 (trend)
   - SuperTrend
   - EMA Cross
   - MACD
   - Ichimoku
   - ADX Trend

2. 均值回归策略 (mean_reversion)
   - Bollinger Bands
   - RSI Mean Reversion
   - Mean Reversion
   - Statistical Arbitrage

3. 动量策略 (momentum)
   - RSI
   - Stochastic
   - Momentum
   - Rate of Change

4. 成交量策略 (volume)
   - VWAP
   - Volume Breakout
   - On Balance Volume
   - Chaikin Money Flow

5. 形态策略 (pattern)
   - Candle Patterns
   - Support Resistance
   - Chart Patterns

6. 多时间框架策略 (multi_timeframe)
   - MTF Analysis
   - Triple Screen
   - Trend Resonance
"""

# 策略注册表
_STRATEGIES = {
    # 趋势跟踪
    'supertrend': 'strategies.trend.SuperTrend',
    'ema_cross': 'strategies.trend.EMACross',
    'macd': 'strategies.trend.MACDStrategy',
    'ichimoku': 'strategies.trend.IchimokuStrategy',

    # 均值回归
    'bbands': 'strategies.mean_reversion.BollingerBands',
    'rsi_mr': 'strategies.mean_reversion.RSIMeanReversion',
    'mean_reversion': 'strategies.mean_reversion.MeanReversion',

    # 动量
    'rsi': 'strategies.momentum.RSIStrategy',
    'stochastic': 'strategies.momentum.StochasticStrategy',
    'momentum': 'strategies.momentum.MomentumStrategy',

    # 成交量
    'vwap': 'strategies.volume.VWAPStrategy',
    'volume_breakout': 'strategies.volume.VolumeBreakout',

    # 形态
    'candle_pattern': 'strategies.pattern.CandlePatternStrategy',
    'support_resistance': 'strategies.pattern.SupportResistanceStrategy',
}

def get_strategy(name):
    """根据名称获取策略类"""
    if name not in _STRATEGIES:
        raise ValueError(f"Unknown strategy: {name}")
    module_path = _STRATEGIES[name]
    module_name, class_name = module_path.rsplit('.', 1)
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)

def list_strategies(category=None):
    """列出可用策略"""
    if category:
        return [k for k, v in _STRATEGIES.items()
                if v.startswith(f'strategies.{category}')]
    return list(_STRATEGIES.keys())
```

#### 2.2 趋势跟踪策略实现

```python
# backtrader/strategies/trend/supertrend.py
from backtrader.strategy.base import StrategyBase
import backtrader as bt

class SuperTrend(StrategyBase):
    """
    SuperTrend 趋势策略

    SuperTrend是一个基于ATR的趋势跟踪指标，
    能够很好地识别趋势方向并提供止损位。

    参数:
        period: ATR周期
        multiplier: ATR倍数
    """
    params = (
        ('period', 10),
        ('multiplier', 3.0),
    )

    def __init__(self):
        super().__init__()

        # 计算ATR
        self.atr = bt.indicators.ATR(self.data, period=self.p.period)

        # SuperTrend指标线
        self.supertrend = bt.indicators.ATR(
            self.data,
            period=self.p.period,
            plot=False
        )

        # 计算上下轨
        hl2 = (self.data.high + self.data.low) / 2
        self.upper_band = hl2 + self.p.multiplier * self.atr
        self.lower_band = hl2 - self.p.multiplier * self.atr

        # 趋势方向 (1=上升, -1=下降)
        self.trend = bt.indicators.If(
            self.data.close(-1) > self.upper_band(-1), 1, -1
        )

    def can_buy(self):
        """买入条件: 趋势转为上升"""
        if len(self.data) < 2:
            return False

        # 当前趋势上升，且之前趋势下降
        current_trend = 1 if self.data.close[0] > self.upper_band[0] else -1
        prev_trend = 1 if self.data.close[-1] > self.upper_band[-1] else -1

        return current_trend == 1 and prev_trend == -1

    def can_sell(self):
        """卖出条件: 趋势转为下降"""
        if len(self.data) < 2:
            return False

        current_trend = 1 if self.data.close[0] > self.upper_band[0] else -1
        prev_trend = 1 if self.data.close[-1] > self.upper_band[-1] else -1

        return current_trend == -1 and prev_trend == 1


class EMACross(StrategyBase):
    """
    EMA交叉策略

    使用双EMA金叉死叉信号

    参数:
        fast_period: 快速EMA周期
        slow_period: 慢速EMA周期
        use_filter: 是否使用趋势过滤
    """
    params = (
        ('fast_period', 9),
        ('slow_period', 21),
        ('use_filter', True),
        ('filter_period', 200),
    )

    def __init__(self):
        super().__init__()

        self.ema_fast = bt.indicators.EMA(
            self.data.close, period=self.p.fast_period
        )
        self.ema_slow = bt.indicators.EMA(
            self.data.close, period=self.p.slow_period
        )
        self.crossover = bt.indicators.CrossOver(self.ema_fast, self.ema_slow)

        # 趋势过滤器
        if self.p.use_filter:
            self.ema_filter = bt.indicators.EMA(
                self.data.close, period=self.p.filter_period
            )

    def can_buy(self):
        """买入条件: 快线上穿慢线"""
        if not self.crossover > 0:
            return False

        # 趋势过滤
        if self.p.use_filter:
            return self.data.close[0] > self.ema_filter[0]

        return True

    def can_sell(self):
        """卖出条件: 快线下穿慢线"""
        return self.crossover < 0
```

#### 2.3 均值回归策略实现

```python
# backtrader/strategies/mean_reversion/bollinger.py
from backtrader.strategy.base import StrategyBase
import backtrader as bt
import numpy as np

class BollingerBands(StrategyBase):
    """
    布林带均值回归策略

    价格偏离均值回归交易

    参数:
        period: 均线周期
        devfactor: 标准差倍数
        entry_zscore: 入场Z-score阈值
        exit_zscore: 出场Z-score阈值
    """
    params = (
        ('period', 20),
        ('devfactor', 2.0),
        ('entry_threshold', 0.02),   # 入场阈值
        ('exit_threshold', 0.0),     # 出场阈值(回归到中轨)
    )

    def __init__(self):
        super().__init__()

        self.bbands = bt.indicators.BollingerBands(
            self.data.close,
            period=self.p.period,
            devfactor=self.p.devfactor
        )

        # 计算价格位置（相对于带宽的百分比）
        self.bb_width = self.bbands.lines.top - self.bbands.lines.bot
        self.price_position = (self.data.close - self.bbands.lines.mid) / self.bb_width

    def can_buy(self):
        """买入条件: 价格触及下轨"""
        lower_band = self.bbands.lines.bot[0]
        threshold_price = lower_band * (1 - self.p.entry_threshold)
        return self.data.close[0] <= threshold_price

    def can_sell(self):
        """卖出条件: 价格回归到中轨或触及上轨"""
        mid_band = self.bbands.lines.mid[0]

        # 回归到中轨
        if self.p.exit_threshold == 0:
            return self.data.close[0] >= mid_band

        # 触及上轨
        upper_band = self.bbands.lines.top[0]
        threshold_price = upper_band * (1 + self.p.exit_threshold)
        return self.data.close[0] >= threshold_price


class RSIMeanReversion(StrategyBase):
    """
    RSI均值回归策略

    在RSI超买超卖区间进行反向交易

    参数:
        period: RSI周期
        oversold: 超卖阈值
        overbought: 超买阈值
        exit_os: 超卖出场阈值
        exit_ob: 超买出场阈值
    """
    params = (
        ('period', 14),
        ('oversold', 30),
        ('overbought', 70),
        ('exit_os', 50),
        ('exit_ob', 50),
    )

    def __init__(self):
        super().__init__()
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.period)

    def can_buy(self):
        """买入条件: RSI超卖"""
        return self.rsi[0] < self.p.oversold

    def can_sell(self):
        """卖出条件: RSI回归到正常区间"""
        return self.rsi[0] >= self.p.exit_os
```

### 3. 策略对比框架设计

```python
# backtrader/comparison/compare.py
import backtrader as bt
import pandas as pd
from typing import List, Dict, Any
import logging

class StrategyComparator:
    """
    策略对比器

    用于批量回测和对比多个策略
    """
    def __init__(self, cash=10000, commission=0.001):
        """
        Args:
            cash: 初始资金
            commission: 手续费率
        """
        self.cash = cash
        self.commission = commission
        self.results = []
        self.logger = logging.getLogger(__name__)

    def run_backtest(self, data, strategy_class, strategy_params=None):
        """
        运行单个策略回测

        Args:
            data: 数据源
            strategy_class: 策略类
            strategy_params: 策略参数

        Returns:
            dict: 回测结果
        """
        cerebro = bt.Cerebro()

        # 添加数据
        if isinstance(data, list):
            for d in data:
                cerebro.adddata(d)
        else:
            cerebro.adddata(data)

        # 添加策略
        params = strategy_params or {}
        cerebro.addstrategy(strategy_class, **params)

        # 设置初始资金和手续费
        cerebro.broker.setcash(self.cash)
        cerebro.broker.setcommission(commission=self.commission)

        # 添加分析器
        cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        cerebro.addanalyzer(bt.analyzers.SQN, _name='sqn')

        # 运行回测
        strats = cerebro.run()
        strat = strats[0]

        # 收集结果
        result = self._collect_results(strat, strategy_class, params)
        self.results.append(result)

        return result

    def run_comparison(self, data, strategies: List[tuple]):
        """
        运行策略对比

        Args:
            data: 数据源
            strategies: 策略列表 [(strategy_class, params), ...]

        Returns:
            DataFrame: 对比结果
        """
        self.results = []

        for strategy_class, params in strategies:
            self.logger.info(f"回测策略: {strategy_class.__name__}")
            try:
                self.run_backtest(data, strategy_class, params)
            except Exception as e:
                self.logger.error(f"策略 {strategy_class.__name__} 回测失败: {e}")

        return self.get_results_dataframe()

    def _collect_results(self, strat, strategy_class, params):
        """收集回测结果"""
        result = {
            'strategy': strategy_class.__name__,
            'params': str(params) if params else '',
            'final_value': strat.broker.getvalue(),
            'total_return': (strat.broker.getvalue() / self.cash - 1) * 100,
        }

        # 获取分析器结果
        # Sharpe Ratio
        sharpe = strat.analyzers.sharpe.get_analysis()
        if sharpe and 'sharperatio' in sharpe:
            result['sharpe_ratio'] = sharpe['sharperatio']
        else:
            result['sharpe_ratio'] = None

        # Drawdown
        drawdown = strat.analyzers.drawdown.get_analysis()
        if drawdown:
            result['max_drawdown'] = drawdown.get('max', {}).get('drawdown', 0)
            result['max_drawdown_money'] = drawdown.get('max', {}).get('moneydrawdown', 0)
        else:
            result['max_drawdown'] = 0
            result['max_drawdown_money'] = 0

        # Returns
        returns = strat.analyzers.returns.get_analysis()
        if returns:
            result['avg_return'] = returns.get('avg', 0)
            result['std_return'] = returns.get('std', 0)
        else:
            result['avg_return'] = 0
            result['std_return'] = 0

        # Trades
        trades = strat.analyzers.trades.get_analysis()
        if trades:
            result['total_trades'] = trades.get('total', {}).get('total', 0)
            result['won_trades'] = trades.get('won', {}).get('total', 0)
            result['lost_trades'] = trades.get('lost', {}).get('total', 0)
            result['win_rate'] = (
                result['won_trades'] / result['total_trades'] * 100
                if result['total_trades'] > 0 else 0
            )
        else:
            result['total_trades'] = 0
            result['won_trades'] = 0
            result['lost_trades'] = 0
            result['win_rate'] = 0

        # SQN
        sqn = strat.analyzers.sqn.get_analysis()
        if sqn:
            result['sqn'] = sqn.get('sqn', 0)
        else:
            result['sqn'] = 0

        return result

    def get_results_dataframe(self):
        """获取结果DataFrame"""
        return pd.DataFrame(self.results)

    def rank_by(self, column='sharpe_ratio', ascending=False):
        """按指标排名"""
        df = self.get_results_dataframe()
        return df.sort_values(by=column, ascending=ascending)

    def print_summary(self):
        """打印对比摘要"""
        df = self.get_results_dataframe()

        print("\n" + "="*80)
        print("策略对比结果")
        print("="*80)
        print(df.to_string(index=False))
        print("="*80)

        print("\n按夏普比率排名:")
        print("-"*80)
        sharpe_rank = self.rank_by('sharpe_ratio', ascending=False)
        print(sharpe_rank[['strategy', 'sharpe_ratio', 'total_return', 'max_drawdown']].to_string(index=False))

        print("\n按收益率排名:")
        print("-"*80)
        return_rank = self.rank_by('total_return', ascending=False)
        print(return_rank[['strategy', 'total_return', 'max_drawdown', 'win_rate']].to_string(index=False))

    def export_html(self, filename='comparison_report.html'):
        """导出HTML报告"""
        df = self.get_results_dataframe()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>策略对比报告</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #4CAF50; color: white; }}
                tr:nth-child(even) {{ background-color: #f2f2f2; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
            </style>
        </head>
        <body>
            <h1>策略对比报告</h1>
            <p>生成时间: {pd.Timestamp.now()}</p>
            <h2>对比结果</h2>
            {df.to_html(index=False, classes='comparison-table')}
        </body>
        </html>
        """

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)

        self.logger.info(f"报告已导出: {filename}")
```

### 4. 使用示例

#### 4.1 基础策略使用

```python
import backtrader as bt
from backtrader.strategies.trend import EMACross

# 创建Cerebro
cerebro = bt.Cerebro()

# 添加数据
data = bt.feeds.YahooFinanceData(
    dataname='AAPL',
    fromdate=datetime(2020, 1, 1),
    todate=datetime(2024, 12, 31)
)
cerebro.adddata(data)

# 添加策略
cerebro.addstrategy(EMACross,
                    fast_period=9,
                    slow_period=21,
                    stop_loss=0.05,
                    take_profit=0.1)

# 运行
result = cerebro.run()
```

#### 4.2 策略对比

```python
from backtrader.comparison import StrategyComparator
from backtrader.strategies.trend import EMACross, SuperTrend
from backtrader.strategies.mean_reversion import BollingerBands

# 创建对比器
comparator = StrategyComparator(cash=10000, commission=0.001)

# 定义策略列表
strategies = [
    (EMACross, {'fast_period': 9, 'slow_period': 21}),
    (EMACross, {'fast_period': 5, 'slow_period': 15}),
    (SuperTrend, {'period': 10, 'multiplier': 3.0}),
    (BollingerBands, {'period': 20, 'devfactor': 2.0}),
]

# 运行对比
results = comparator.run_comparison(data, strategies)

# 打印摘要
comparator.print_summary()

# 导出报告
comparator.export_html('strategy_comparison.html')
```

#### 4.3 自定义策略

```python
from backtrader.strategy.base import StrategyBase
import backtrader as bt

class MyCustomStrategy(StrategyBase):
    """
    自定义策略模板

    只需要实现can_buy()和can_sell()方法
    """
    params = (
        ('param1', 10),
        ('param2', 20),
    )

    def __init__(self):
        super().__init__()
        # 初始化指标
        self.indicator1 = bt.indicators.SMA(self.data.close, period=self.p.param1)
        self.indicator2 = bt.indicators.SMA(self.data.close, period=self.p.param2)

    def can_buy(self):
        """买入条件"""
        # 实现你的买入逻辑
        return self.indicator1[0] > self.indicator2[0]

    def can_sell(self):
        """卖出条件"""
        # 实现你的卖出逻辑
        return self.indicator1[0] < self.indicator2[0]
```

---

## 实施路线图

### 阶段1: 基础框架 (1-2周)
- [ ] 创建strategy包结构
- [ ] 实现StrategyBase基类
- [ ] 实现StrategyForComparison
- [ ] 编写基础模板策略
- [ ] 单元测试

### 阶段2: 趋势策略库 (2周)
- [ ] 实现SuperTrend策略
- [ ] 实现EMA Cross策略
- [ ] 实现MACD策略
- [ ] 实现Ichimoku策略
- [ ] 策略文档

### 阶段3: 均值回归策略库 (2周)
- [ ] 实现Bollinger Bands策略
- [ ] 实现RSI Mean Reversion策略
- [ ] 实现Mean Reversion策略
- [ ] 策略文档

### 阶段4: 动量和成交量策略 (2周)
- [ ] 实现RSI策略
- [ ] 实现Stochastic策略
- [ ] 实现VWAP策略
- [ ] 实现Volume Breakout策略

### 阶段5: 对比框架 (1-2周)
- [ ] 实现StrategyComparator
- [ ] 实现批量回测
- [ ] 实现结果排名
- [ ] 实现HTML报告导出

### 阶段6: 风险管理增强 (1周)
- [ ] 实现ATR止损
- [ ] 实现移动止损
- [ ] 实现括号订单
- [ ] 实现仓位管理

### 阶段7: 文档和测试 (1周)
- [ ] 编写使用文档
- [ ] 编写API文档
- [ ] 完善示例代码
- [ ] 集成测试

---

## 附录: 关键文件路径

### Backtrader关键文件
- `strategy.py`: 策略基类
- `cerebro.py`: 核心引擎
- `indicators/`: 指标库

### Backtrader-Strategies-Compendium关键文件
- `strategies/common.py`: StrategyForComparison基类
- `strategies/`: 30+策略实现
- `backtest.py`: 回测运行器
- `data_loader/`: 数据加载模块
- `indicators/`: 自定义指标
