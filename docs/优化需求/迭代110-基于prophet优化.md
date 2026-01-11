### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/prophet
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### prophet项目简介
prophet是Facebook开源的时间序列预测库，具有以下核心特点：
- **时序预测**: 时间序列预测
- **趋势分解**: 趋势和季节性分解
- **异常检测**: 异常点检测
- **节假日效应**: 节假日效应建模
- **自动调参**: 自动参数调优
- **可解释性**: 模型可解释性

### 重点借鉴方向
1. **时序预测**: 时序预测集成
2. **趋势分析**: 趋势分解方法
3. **季节性**: 季节性建模
4. **异常检测**: 异常检测方法
5. **预测区间**: 预测不确定性
6. **可解释性**: 模型可解释性

---

# 分析与设计文档

## 一、框架对比分析

### 1.1 backtrader vs Prophet 对比

| 维度 | backtrader (原生) | Prophet |
|------|------------------|---------|
| **定位** | 回测框架 | 时间序列预测库 |
| **预测能力** | 无 | 时序预测核心功能 |
| **趋势分析** | 手动计算指标 | 自动趋势分解 |
| **季节性** | 需手动实现 | 内置季节性建模 |
| **节假日效应** | 无 | 内置国家节假日 |
| **异常检测** | 无 | 基于残差/区间检测 |
| **不确定性量化** | 无 | 预测区间(置信度) |
| **可解释性** | 指标可解释 | 完整分量分解 |
| **参数调优** | 手动优化 | 交叉验证自动调参 |
| **可视化** | 基础绘图 | 预测图/分量图 |

### 1.2 可借鉴的核心优势

1. **时序预测引擎**: 基于加性模型的时序分解和预测
2. **趋势自动识别**: 线性/Logistic/平坦趋势自动检测
3. **季节性建模**: 傅里叶级数建模多周期季节性
4. **变点检测**: 自动检测趋势变化点
5. **不确定性量化**: 预测区间支持风险评估
6. **插件式扩展**: 易于添加自定义季节性和回归量
7. **交叉验证**: 时间序列交叉验证(rolling forecast)

---

## 二、需求规格文档

### 2.1 时序预测策略基类

**需求描述**: 创建集成Prophet预测能力的策略基类。

**功能要求**:
- 自动预测未来价格走势
- 支持趋势、季节性、节假日多分量分解
- 基于预测结果生成交易信号
- 支持预测区间过滤低置信度信号
- 支持在线模型更新

**接口定义**:
```python
class ProphetStrategy(bt.Strategy):
    params = (
        ('prediction_horizon', 5),      # 预测周期
        ('train_window', 252),          # 训练窗口
        ('retrain_freq', 20),           # 重训频率
        ('signal_threshold', 0.02),     # 信号阈值
        ('use_uncertainty', True),      # 使用不确定性过滤
        ('confidence_level', 0.8),      # 置信水平
    )
```

### 2.2 趋势分析模块

**需求描述**: 提供趋势分析和识别功能。

**功能要求**:
- 趋势方向识别(上升/下降/横盘)
- 趋势强度计算
- 趋势变化点检测
- 趋势持续性评估

**接口定义**:
```python
class TrendAnalyzer:
    def detect_trend(self, prices) -> str  # 'up', 'down', 'flat'
    def trend_strength(self, prices) -> float  # 0-1
    def find_changepoints(self, prices) -> List[int]
    def trend_persistence(self, prices) -> float
```

### 2.3 季节性分析模块

**需求描述**: 提供季节性模式识别功能。

**功能要求**:
- 年季节性检测
- 周季节性检测
- 日季节性检测
- 自定义周期季节性
- 季节性强度评估

**接口定义**:
```python
class SeasonalityAnalyzer:
    def yearly_seasonality(self, prices, dates) -> np.ndarray
    def weekly_seasonality(self, prices, dates) -> np.ndarray
    def daily_seasonality(self, prices, dates) -> np.ndarray
    def add_custom_seasonality(self, period, fourier_order)
    def seasonality_strength(self) -> Dict[str, float]
```

### 2.4 异常检测模块

**需求描述**: 提供价格异常检测功能。

**功能要求**:
- 基于预测残差的异常检测
- 基于预测区间的异常检测
- 实时异常识别
- 异常事件记录

**接口定义**:
```python
class AnomalyDetector:
    def detect_residual_anomaly(self, actual, predicted, threshold=3.0) -> bool
    def detect_interval_anomaly(self, actual, lower, upper) -> bool
    def anomaly_score(self, actual, predicted, uncertainty) -> float
    def get_anomaly_events(self) -> List[Dict]
```

### 2.5 不确定性量化模块

**需求描述**: 提供预测不确定性量化功能。

**功能要求**:
- 预测区间计算
- 置信度评估
- 风险度量
- 仓位调整建议

**接口定义**:
```python
class UncertaintyQuantifier:
    def prediction_interval(self, forecast, confidence=0.8) -> Tuple[float, float]
    def confidence_score(self, actual, predicted, interval) -> float
    def risk_measure(self, uncertainty) -> float
    def position_sizing(self, confidence, base_size) -> float
```

### 2.6 交叉验证模块

**需求描述**: 提供时序交叉验证功能。

**功能要求**:
- 滚动预测验证
- 性能指标计算(MAPE, MAE, RMSE)
- 参数网格搜索
- 最优参数选择

**接口定义**:
```python
class TimeSeriesCV:
    def rolling_forecast(self, data, horizon, period) -> DataFrame
    def calculate_metrics(self, actual, predicted) -> Dict[str, float]
    def grid_search(self, param_grid) -> Dict[str, Any]
    def best_params(self) -> Dict[str, Any]
```

---

## 三、详细设计文档

### 3.1 时序预测策略基类

```python
"""
backtrader/forecasting/strategies.py

时序预测策略基类实现
"""

import backtrader as bt
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any, List
from collections import deque
from datetime import datetime, timedelta


class ProphetIndicator(bt.Indicator):
    """Prophet预测指标

    基于历史价格预测未来走势
    """

    lines = ('predicted', 'trend', 'lower', 'upper', 'seasonality')
    params = (
        ('period', 30),              # 训练周期
        ('horizon', 5),              # 预测周期
        ('confidence', 0.8),         # 置信水平
        ('growth', 'linear'),        # 趋势类型
        ('seasonality_mode', 'additive'),
    )

    plotinfo = dict(
        plot=True,
        subplot=False,
    )

    def __init__(self):
        # 延迟足够的数据才开始计算
        self.minperiod = self.p.period + self.p.horizon

    def next(self):
        # 只在有足够数据时计算
        if len(self) < self.minperiod:
            return

        # 获取历史价格数据
        prices = pd.Series([
            self.data.close[-i]
            for i in range(self.p.period, 0, -1)
        ])

        # 计算预测
        forecast = self._fit_predict(prices)

        # 输出预测值(未来第horizon期)
        if forecast is not None and len(forecast) > self.p.horizon:
            self.lines.predicted[0] = forecast['yhat'].iloc[self.p.horizon]
            self.lines.trend[0] = forecast['trend'].iloc[self.p.horizon]
            self.lines.lower[0] = forecast['yhat_lower'].iloc[self.p.horizon]
            self.lines.upper[0] = forecast['yhat_upper'].iloc[self.p.horizon]

            # 季节性分量
            seasonal_cols = [c for c in forecast.columns
                           if c.startswith('seasonal') or
                           c in ['weekly', 'yearly', 'daily']]
            if seasonal_cols:
                self.lines.seasonality[0] = sum(
                    forecast[c].iloc[self.p.horizon]
                    for c in seasonal_cols if c in forecast.columns
                )

    def _fit_predict(self, prices: pd.Series) -> Optional[pd.DataFrame]:
        """拟合模型并预测"""
        try:
            from prophet import Prophet

            # 准备数据
            dates = pd.date_range(
                end=datetime.now(),
                periods=self.p.period,
                freq='D'
            )
            df = pd.DataFrame({'ds': dates, 'y': prices.values})

            # 创建并拟合模型
            model = Prophet(
                growth=self.p.growth,
                seasonality_mode=self.p.seasonality_mode,
                interval_width=self.p.confidence,
                daily_seasonality=False,
                weekly_seasonality=True,
                yearly_seasonality=True,
            )

            model.fit(df)

            # 预测
            future = model.make_future_dataframe(
                periods=self.p.horizon,
                include_history=False
            )
            forecast = model.predict(future)

            return forecast

        except Exception as e:
            # 降级到简单趋势预测
            return self._simple_trend(prices)

    def _simple_trend(self, prices: pd.Series) -> pd.DataFrame:
        """简单趋势预测(降级方案)"""
        # 线性趋势
        x = np.arange(len(prices))
        coef = np.polyfit(x, prices.values, 1)
        trend = coef[0] * (len(prices) + self.p.horizon) + coef[1]

        # 标准差作为不确定性
        std = prices.std()

        forecast = pd.DataFrame({
            'yhat': [trend] * self.p.horizon,
            'yhat_lower': [trend - std] * self.p.horizon,
            'yhat_upper': [trend + std] * self.p.horizon,
            'trend': [trend] * self.p.horizon,
        })

        return forecast


class ProphetSignal(bt.Indicator):
    """Prophet信号指标

    基于预测结果生成交易信号
    """

    lines = ('signal', 'confidence', 'return_potential')
    params = (
        ('threshold', 0.02),         # 信号阈值
        ('use_uncertainty', True),   # 使用不确定性过滤
        ('min_confidence', 0.6),     # 最小置信度
    )

    plotinfo = dict(
        plot=True,
        subplot=True,
    )

    def __init__(self):
        self.prophet = ProphetIndicator(
            self.data,
            period=self.p.period,
            horizon=self.p.horizon,
        )

    def next(self):
        if len(self.prophet.predicted) == 0:
            self.lines.signal[0] = 0
            self.lines.confidence[0] = 0
            self.lines.return_potential[0] = 0
            return

        current_price = self.data.close[0]
        predicted = self.prophet.predicted[0]
        lower = self.prophet.lower[0]
        upper = self.prophet.upper[0]

        # 计算预测收益率
        return_up = (upper - current_price) / current_price
        return_down = (lower - current_price) / current_price
        return_potential = (predicted - current_price) / current_price

        # 计算置信度(基于预测区间宽度)
        interval_width = (upper - lower) / current_price
        confidence = max(0, 1 - interval_width * 10)  # 简单转换

        # 生成信号
        signal = 0
        if self.p.use_uncertainty:
            # 使用不确定性过滤
            if confidence >= self.p.min_confidence:
                if return_potential > self.p.threshold:
                    signal = 1
                elif return_potential < -self.p.threshold:
                    signal = -1
        else:
            # 不使用不确定性过滤
            if return_potential > self.p.threshold:
                signal = 1
            elif return_potential < -self.p.threshold:
                signal = -1

        self.lines.signal[0] = signal
        self.lines.confidence[0] = confidence
        self.lines.return_potential[0] = return_potential


class ProphetStrategy(bt.Strategy):
    """Prophet预测策略

    基于Prophet时序预测的交易策略
    """

    params = (
        # Prophet参数
        ('train_period', 252),        # 训练周期
        ('prediction_horizon', 5),    # 预测周期
        ('retrain_freq', 20),         # 重训频率

        # 信号参数
        ('signal_threshold', 0.02),   # 信号阈值(%)
        ('use_uncertainty', True),    # 使用不确定性过滤
        ('min_confidence', 0.6),      # 最小置信度

        # 仓位管理
        ('position_size', 0.95),      # 基础仓位
        ('scale_by_confidence', True), # 按置信度调整仓位

        # 风险控制
        ('stop_loss', None),          # 止损(%)
        ('take_profit', None),        # 止盈(%)

        # 趋势过滤
        ('trend_filter', True),       # 使用趋势过滤
        ('min_trend_strength', 0.3),  # 最小趋势强度

        # 输出
        ('verbose', False),
    )

    def __init__(self):
        # Prophet信号指标
        self.signal = ProphetSignal(
            self.data,
            period=self.p.train_period,
            horizon=self.p.prediction_horizon,
            threshold=self.p.signal_threshold,
            use_uncertainty=self.p.use_uncertainty,
            min_confidence=self.p.min_confidence,
        )

        # 趋势指标(用于过滤)
        if self.p.trend_filter:
            self.sma_fast = bt.indicators.SMA(self.data.close, period=20)
            self.sma_slow = bt.indicators.SMA(self.data.close, period=60)
            self.trend_strength = (self.sma_fast - self.sma_slow) / self.sma_slow

        # 记录上次信号和价格
        self.last_signal = 0
        self.entry_price = None

        # 交易计数
        self.trades = 0
        self.wins = 0

    def _get_position_size(self) -> float:
        """计算仓位大小"""
        size = self.p.position_size

        # 按置信度调整
        if self.p.scale_by_confidence:
            confidence = self.signal.confidence[0]
            size = size * confidence

        # 按趋势强度调整
        if self.p.trend_filter and self.trend_strength[0] is not None:
            strength = abs(self.trend_strength[0])
            if strength > self.p.min_trend_strength:
                size = size * min(1.5, strength / self.p.min_trend_strength)
            else:
                size = 0

        return min(1.0, max(0, size))

    def _check_risk_management(self) -> bool:
        """检查风险控制"""
        if self.entry_price is None:
            return False

        current_price = self.data.close[0]
        pnl_pct = (current_price - self.entry_price) / self.entry_price

        # 止损
        if self.p.stop_loss and pnl_pct < -self.p.stop_loss:
            if self.p.verbose:
                print(f'{self.datetime.date()} Stop Loss triggered: {pnl_pct:.2%}')
            return True

        # 止盈
        if self.p.take_profit and pnl_pct > self.p.take_profit:
            if self.p.verbose:
                print(f'{self.datetime.date()} Take Profit triggered: {pnl_pct:.2%}')
            return True

        return False

    def next(self):
        current_signal = int(self.signal.signal[0])
        current_price = self.data.close[0]

        # 风险控制检查
        if self._check_risk_management():
            self.close()
            self.last_signal = 0
            self.entry_price = None
            return

        # 信号变化时执行交易
        if current_signal != self.last_signal:
            # 平仓
            if self.last_signal != 0:
                self.close()
                if self.p.verbose:
                    pnl = (current_price - self.entry_price) / self.entry_price
                    print(f'{self.datetime.date()} Close: {pnl:.2%}')
                    if pnl > 0:
                        self.wins += 1

            # 开仓
            if current_signal != 0:
                size = self._get_position_size()

                if current_signal > 0:
                    self.buy(size=size)
                    if self.p.verbose:
                        print(f'{self.datetime.date()} BUY: '
                              f'price={current_price:.2f}, '
                              f'size={size:.2f}, '
                              f'conf={self.signal.confidence[0]:.2f}')
                else:
                    self.sell(size=size)
                    if self.p.verbose:
                        print(f'{self.datetime.date()} SELL: '
                              f'price={current_price:.2f}, '
                              f'size={size:.2f}, '
                              f'conf={self.signal.confidence[0]:.2f}')

                self.entry_price = current_price
                self.trades += 1

            self.last_signal = current_signal

    def stop(self):
        """策略结束时输出统计"""
        self.close()

        if self.p.verbose:
            print(f'\n=== Prophet Strategy Results ===')
            print(f'Total Trades: {self.trades}')
            print(f'Winning Trades: {self.wins}')
            if self.trades > 0:
                print(f'Win Rate: {self.wins/self.trades:.2%}')
            print(f'Starting Cash: {self.broker.startingcash:.2f}')
            print(f'Final Value: {self.broker.getvalue():.2f}')
            print(f'Return: {(self.broker.getvalue()/self.broker.startingcash - 1)*100:.2f}%')
```

### 3.2 趋势分析模块

```python
"""
backtrader/forecasting/trend.py

趋势分析模块
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict, Optional
from scipy import stats
from scipy.signal import find_peaks
from ruptures import Pelt, Binseg  # 需要安装ruptures库


class TrendAnalyzer:
    """趋势分析器

    提供多种趋势分析方法
    """

    def __init__(self, min_period: int = 20):
        """
        Args:
            min_period: 最小分析周期
        """
        self.min_period = min_period

    def detect_trend(self, prices: pd.Series) -> str:
        """检测趋势方向

        Args:
            prices: 价格序列

        Returns:
            'up', 'down', 'flat'
        """
        if len(prices) < self.min_period:
            return 'flat'

        # 方法1: 线性回归斜率
        x = np.arange(len(prices))
        slope, _, _, p_value, _ = stats.linregress(x, prices)

        # 方法2: 移动平均比较
        ma_short = prices.iloc[-20:].mean() if len(prices) >= 20 else prices.mean()
        ma_long = prices.iloc[-60:].mean() if len(prices) >= 60 else prices.mean()
        ma_diff = (ma_short - ma_long) / ma_long

        # 综合判断
        if p_value < 0.05:  # 显著性检验
            if slope > 0 and ma_diff > 0.01:
                return 'up'
            elif slope < 0 and ma_diff < -0.01:
                return 'down'

        return 'flat'

    def trend_strength(self, prices: pd.Series) -> float:
        """计算趋势强度

        Args:
            prices: 价格序列

        Returns:
            趋势强度 0-1
        """
        if len(prices) < self.min_period:
            return 0.0

        # 计算R²
        x = np.arange(len(prices))
        slope, intercept, r_value, p_value, _ = stats.linregress(x, prices)

        # R²作为趋势强度
        strength = r_value ** 2

        # 根据显著性调整
        if p_value < 0.01:
            strength = min(1.0, strength * 1.2)
        elif p_value > 0.1:
            strength = strength * 0.5

        return float(np.clip(strength, 0, 1))

    def find_changepoints(
        self,
        prices: pd.Series,
        method: str = 'pelt',
        max_n_changepoints: int = 10
    ) -> List[int]:
        """寻找趋势变化点

        Args:
            prices: 价格序列
            method: 'pelt' or 'binseg'
            max_n_changepoints: 最大变化点数量

        Returns:
            变化点索引列表
        """
        if len(prices) < self.min_period * 2:
            return []

        try:
            # 转换为对数收益率
            returns = np.log(prices / prices.shift(1)).dropna().values

            # 使用ruptures库检测变点
            if method == 'pelt':
                algo = Pelt(model='rbf').fit(returns)
            else:
                algo = Binseg(model='rbf').fit(returns)

            # 预测变化点
            n_changepoints = min(max_n_changepoints, len(returns) // 20)
            changepoints = algo.predict(n_changepoints)

            # 转换为索引(最后一个点是序列结尾)
            changepoints = [c for c in changepoints if c < len(prices)]

            return changepoints

        except Exception:
            # 降级到简单方法
            return self._simple_changepoints(prices)

    def _simple_changepoints(self, prices: pd.Series) -> List[int]:
        """简单的变化点检测(降级方案)"""
        changepoints = []

        # 计算移动平均斜率变化
        window = self.min_period
        slopes = []

        for i in range(window, len(prices) - window):
            segment = prices.iloc[i-window:i+window]
            x = np.arange(len(segment))
            slope, _, _, _, _ = stats.linregress(x, segment)
            slopes.append(slope)

        # 斜率符号变化点
        for i in range(1, len(slopes)):
            if slopes[i] * slopes[i-1] < 0:  # 符号变化
                changepoints.append(i + window)

        return changepoints

    def trend_persistence(self, prices: pd.Series) -> float:
        """评估趋势持续性

        使用Hurst指数评估趋势持续性

        Args:
            prices: 价格序列

        Returns:
            持续性分数 (0-1)
        """
        if len(prices) < 50:
            return 0.5

        # 计算Hurst指数
        hurst = self._hurst_exponent(prices.values)

        # Hurst > 0.5 表示趋势持续
        # Hurst < 0.5 表示均值回归
        # Hurst = 0.5 表示随机游走

        if hurst > 0.5:
            persistence = (hurst - 0.5) * 2  # 映射到0-1
        else:
            persistence = 0

        return float(np.clip(persistence, 0, 1))

    def _hurst_exponent(self, prices: np.ndarray) -> float:
        """计算Hurst指数"""
        min_lag = 2
        max_lag = len(prices) // 2

        lags = range(min_lag, max_lag)
        tau = [np.std(np.subtract(prices[lag:], prices[:-lag])) for lag in lags]

        # 对数回归
        reg = np.polyfit(np.log(lags), np.log(tau), 1)
        hurst = reg[0]

        return hurst

    def trend_segments(
        self,
        prices: pd.Series,
        changepoints: Optional[List[int]] = None
    ) -> List[Dict]:
        """将序列分割为趋势段

        Args:
            prices: 价格序列
            changepoints: 变化点列表

        Returns:
            趋势段列表
        """
        if changepoints is None:
            changepoints = self.find_changepoints(prices)

        segments = []
        start = 0

        for cp in changepoints + [len(prices)]:
            segment_prices = prices.iloc[start:cp]

            if len(segment_prices) > 0:
                x = np.arange(len(segment_prices))
                slope, _, r_value, _, _ = stats.linregress(x, segment_prices)

                segments.append({
                    'start': start,
                    'end': cp,
                    'trend': 'up' if slope > 0 else 'down',
                    'slope': slope,
                    'strength': r_value ** 2,
                    'start_price': segment_prices.iloc[0],
                    'end_price': segment_prices.iloc[-1],
                    'return': (segment_prices.iloc[-1] - segment_prices.iloc[0]) / segment_prices.iloc[0],
                })

            start = cp

        return segments


class TrendIndicator(bt.Indicator):
    """Backtrader趋势指标"""

    lines = ('trend_direction', 'trend_strength', 'trend_persistence')
    params = (
        ('period', 60),
        ('method', 'regression'),  # 'regression', 'ma', 'combined'
    )

    plotinfo = dict(
        plot=True,
        subplot=True,
    )

    def __init__(self):
        self.analyzer = TrendAnalyzer(min_period=20)

    def next(self):
        if len(self) < self.p.period:
            return

        prices = pd.Series([
            self.data.close[-i]
            for i in range(self.p.period, 0, -1)
        ])

        # 趋势方向
        direction = self.analyzer.detect_trend(prices)
        self.lines.trend_direction[0] = {'up': 1, 'flat': 0, 'down': -1}.get(direction, 0)

        # 趋势强度
        self.lines.trend_strength[0] = self.analyzer.trend_strength(prices)

        # 趋势持续性
        self.lines.trend_persistence[0] = self.analyzer.trend_persistence(prices)
```

### 3.3 季节性分析模块

```python
"""
backtrader/forecasting/seasonality.py

季节性分析模块
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable
from datetime import datetime
from scipy.fft import fft, ifft
from scipy import stats


class SeasonalityAnalyzer:
    """季节性分析器

    检测和分析时间序列中的季节性模式
    """

    def __init__(self):
        self.custom_seasonalities = {}

    def yearly_seasonality(
        self,
        prices: pd.Series,
        dates: pd.Series,
        fourier_order: int = 10
    ) -> pd.DataFrame:
        """提取年季节性

        Args:
            prices: 价格序列
            dates: 日期序列
            fourier_order: 傅里叶阶数

        Returns:
            包含年季节性的DataFrame
        """
        if len(prices) < 365:
            return pd.DataFrame()

        # 创建时间特征
        df = pd.DataFrame({'ds': dates, 'y': prices.values})
        df['day_of_year'] = df['ds'].dt.dayofyear

        # 归一化到[0, 2π]
        t = df['day_of_year'] * 2 * np.pi / 365

        # 傅里叶变换
        seasonality = np.zeros(len(df))
        for i in range(fourier_order):
            seasonality += (
                np.sin(t * (i + 1)) * 2 * np.pi / 365 +
                np.cos(t * (i + 1)) * 2 * np.pi / 365
            )

        # 归一化
        seasonality = (seasonality - seasonality.mean()) / seasonality.std()

        return pd.DataFrame({
            'ds': dates,
            'yearly': seasonality,
        })

    def weekly_seasonality(
        self,
        prices: pd.Series,
        dates: pd.Series,
        fourier_order: int = 3
    ) -> pd.DataFrame:
        """提取周季节性

        Args:
            prices: 价格序列
            dates: 日期序列
            fourier_order: 傅里叶阶数

        Returns:
            包含周季节性的DataFrame
        """
        if len(prices) < 7:
            return pd.DataFrame()

        df = pd.DataFrame({'ds': dates, 'y': prices.values})
        df['day_of_week'] = df['ds'].dt.dayofweek

        # 按星期分组计算平均
        weekly_pattern = df.groupby('day_of_week')['y'].mean()
        weekly_pattern = (weekly_pattern - weekly_pattern.mean()) / weekly_pattern.std()

        # 映射到完整序列
        seasonality = df['day_of_week'].map(weekly_pattern).values

        return pd.DataFrame({
            'ds': dates,
            'weekly': seasonality,
        })

    def daily_seasonality(
        self,
        prices: pd.Series,
        timestamps: pd.Series,
        fourier_order: int = 4
    ) -> pd.DataFrame:
        """提取日季节性(日内)

        Args:
            prices: 价格序列
            timestamps: 时间戳序列
            fourier_order: 傅里叶阶数

        Returns:
            包含日季节性的DataFrame
        """
        if len(prices) < 24:
            return pd.DataFrame()

        df = pd.DataFrame({'ds': timestamps, 'y': prices.values})
        df['hour'] = df['ds'].dt.hour

        # 按小时分组计算平均
        hourly_pattern = df.groupby('hour')['y'].mean()
        hourly_pattern = (hourly_pattern - hourly_pattern.mean()) / hourly_pattern.std()

        # 映射到完整序列
        seasonality = df['hour'].map(hourly_pattern).values

        return pd.DataFrame({
            'ds': timestamps,
            'daily': seasonality,
        })

    def add_custom_seasonality(
        self,
        name: str,
        period: float,
        fourier_order: int,
        prior_scale: float = 10.0
    ):
        """添加自定义季节性

        Args:
            name: 季节性名称
            period: 周期(天数)
            fourier_order: 傅里叶阶数
            prior_scale: 先验尺度
        """
        self.custom_seasonalities[name] = {
            'period': period,
            'fourier_order': fourier_order,
            'prior_scale': prior_scale,
        }

    def custom_seasonality(
        self,
        prices: pd.Series,
        dates: pd.Series,
        name: str
    ) -> pd.Series:
        """计算自定义季节性

        Args:
            prices: 价格序列
            dates: 日期序列
            name: 季节性名称

        Returns:
            季节性序列
        """
        if name not in self.custom_seasonalities:
            raise ValueError(f'Unknown seasonality: {name}')

        config = self.custom_seasonalities[name]
        period = config['period']
        order = config['fourier_order']

        # 创建时间特征
        t = pd.Series(range(len(dates))) * 2 * np.pi / period

        # 傅里叶级数
        seasonality = np.zeros(len(dates))
        for i in range(order):
            seasonality += (
                np.sin(t * (i + 1)) +
                np.cos(t * (i + 1))
            )

        # 归一化
        seasonality = (seasonality - seasonality.mean()) / (seasonality.std() + 1e-10)

        return pd.Series(seasonality, index=dates.index)

    def seasonality_strength(
        self,
        prices: pd.Series,
        dates: pd.Series
    ) -> Dict[str, float]:
        """计算各季节性的强度

        Args:
            prices: 价格序列
            dates: 日期序列

        Returns:
            季节性强度字典
        """
        strengths = {}

        # 去趋势
        trend = prices.rolling(window=30, min_periods=1).mean()
        detrended = prices - trend

        # 年季节性强度
        if len(prices) >= 365:
            yearly = self.yearly_seasonality(detrended, dates)
            if 'yearly' in yearly.columns:
                var_total = detrended.var()
                var_seasonal = yearly['yearly'].var()
                strengths['yearly'] = var_seasonal / (var_total + 1e-10)

        # 周季节性强度
        if len(prices) >= 7:
            weekly = self.weekly_seasonality(detrended, dates)
            if 'weekly' in weekly.columns:
                var_total = detrended.var()
                var_seasonal = weekly['weekly'].var()
                strengths['weekly'] = var_seasonal / (var_total + 1e-10)

        # 日季节性强度
        if len(prices) >= 24:
            daily = self.daily_seasonality(detrended, dates)
            if 'daily' in daily.columns:
                var_total = detrended.var()
                var_seasonal = daily['daily'].var()
                strengths['daily'] = var_seasonal / (var_total + 1e-10)

        return strengths

    def detect_seasonality_period(
        self,
        prices: pd.Series,
        min_period: int = 2,
        max_period: Optional[int] = None
    ) -> List[Tuple[int, float]]:
        """检测季节性周期

        使用FFT检测主要周期

        Args:
            prices: 价格序列
            min_period: 最小周期
            max_period: 最大周期

        Returns:
            [(周期, 强度), ...] 按强度排序
        """
        if max_period is None:
            max_period = len(prices) // 2

        # 去趋势
        trend = prices.rolling(window=min_period * 2, min_periods=1).mean()
        detrended = prices - trend
        detrended = detrended.fillna(0)

        # FFT
        fft_values = fft(detrended.values)
        power = np.abs(fft_values) ** 2

        # 频率转换为周期
        n = len(prices)
        freqs = np.fft.fftfreq(n)
        periods = 1 / np.abs(freqs[1:n//2])  # 去除直流分量

        # 过滤有效周期
        valid_mask = (periods >= min_period) & (periods <= max_period)
        valid_periods = periods[valid_mask]
        valid_power = power[1:n//2][valid_mask]

        # 按功率排序
        sorted_indices = np.argsort(valid_power)[::-1]
        result = [
            (int(valid_periods[i]), float(valid_power[i]))
            for i in sorted_indices[:10]
        ]

        return result


class SeasonalityIndicator(bt.Indicator):
    """Backtrader季节性指标"""

    lines = ('seasonal', 'seasonal_strength',)
    params = (
        ('period_type', 'weekly'),  # 'daily', 'weekly', 'yearly'
        ('lookback', 252),
    )

    plotinfo = dict(
        plot=True,
        subplot=True,
    )

    def __init__(self):
        self.analyzer = SeasonalityAnalyzer()

    def next(self):
        if len(self) < self.p.lookback:
            return

        # 需要日期信息(从数据中获取)
        if hasattr(self.data, 'datetime'):
            dates = pd.Series([
                self.data.datetime.date(-i)
                for i in range(self.p.lookback, 0, -1)
            ])
        else:
            dates = pd.date_range(end=datetime.now(), periods=self.p.lookback)

        prices = pd.Series([
            self.data.close[-i]
            for i in range(self.p.lookback, 0, -1)
        ])

        # 计算季节性
        try:
            if self.p.period_type == 'weekly':
                seasonal = self.analyzer.weekly_seasonality(prices, dates)
                if 'weekly' in seasonal.columns:
                    self.lines.seasonal[0] = seasonal['weekly'].iloc[-1]
            elif self.p.period_type == 'yearly':
                seasonal = self.analyzer.yearly_seasonality(prices, dates)
                if 'yearly' in seasonal.columns:
                    self.lines.seasonal[0] = seasonal['yearly'].iloc[-1]
            elif self.p.period_type == 'daily':
                timestamps = pd.Series([
                    self.data.datetime.datetime(-i)
                    for i in range(self.p.lookback, 0, -1)
                ])
                seasonal = self.analyzer.daily_seasonality(prices, timestamps)
                if 'daily' in seasonal.columns:
                    self.lines.seasonal[0] = seasonal['daily'].iloc[-1]

            # 季节性强度
            strengths = self.analyzer.seasonality_strength(prices, dates)
            self.lines.seasonal_strength[0] = strengths.get(self.p.period_type, 0)

        except Exception:
            self.lines.seasonal[0] = 0
            self.lines.seasonal_strength[0] = 0
```

### 3.4 异常检测模块

```python
"""
backtrader/forecasting/anomaly.py

异常检测模块
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Tuple, Optional
from scipy import stats


class AnomalyDetector:
    """异常检测器

    基于预测残差和统计方法检测异常
    """

    def __init__(
        self,
        method: str = 'residual',
        threshold: float = 3.0,
        window: int = 20
    ):
        """
        Args:
            method: 检测方法 ('residual', 'interval', 'isolation', 'zscore')
            threshold: 异常阈值(标准差倍数)
            window: 滚动窗口大小
        """
        self.method = method
        self.threshold = threshold
        self.window = window
        self.anomaly_events = []

    def detect_residual_anomaly(
        self,
        actual: pd.Series,
        predicted: pd.Series,
        threshold: Optional[float] = None
    ) -> pd.Series:
        """基于预测残差检测异常

        Args:
            actual: 实际值
            predicted: 预测值
            threshold: 阈值(标准差倍数)

        Returns:
            布尔序列，True表示异常
        """
        if threshold is None:
            threshold = self.threshold

        # 计算残差
        residuals = actual - predicted

        # 计算滚动统计
        rolling_std = residuals.rolling(window=self.window, min_periods=1).std()
        rolling_mean = residuals.rolling(window=self.window, min_periods=1).mean()

        # 标准化残差
        std_residuals = (residuals - rolling_mean) / (rolling_std + 1e-10)

        # 检测异常
        anomalies = std_residuals.abs() > threshold

        # 记录异常事件
        for idx in anomalies[anomalies].index:
            self.anomaly_events.append({
                'timestamp': idx,
                'type': 'residual',
                'actual': actual[idx],
                'predicted': predicted[idx],
                'residual': residuals[idx],
                'z_score': std_residuals[idx],
            })

        return anomalies

    def detect_interval_anomaly(
        self,
        actual: pd.Series,
        lower: pd.Series,
        upper: pd.Series
    ) -> pd.Series:
        """基于预测区间检测异常

        Args:
            actual: 实际值
            lower: 预测下界
            upper: 预测上界

        Returns:
            布尔序列，True表示异常
        """
        # 检测超出区间的值
        anomalies = (actual < lower) | (actual > upper)

        # 记录异常事件
        for idx in anomalies[anomalies].index:
            self.anomaly_events.append({
                'timestamp': idx,
                'type': 'interval',
                'actual': actual[idx],
                'lower': lower[idx],
                'upper': upper[idx],
                'deviation': min(
                    abs(actual[idx] - lower[idx]) / (lower[idx] + 1e-10),
                    abs(actual[idx] - upper[idx]) / (upper[idx] + 1e-10)
                ),
            })

        return anomalies

    def anomaly_score(
        self,
        actual: float,
        predicted: float,
        uncertainty: Optional[float] = None
    ) -> float:
        """计算异常得分

        Args:
            actual: 实际值
            predicted: 预测值
            uncertainty: 预测不确定性

        Returns:
            异常得分 (0-1, 越高越异常)
        """
        residual = abs(actual - predicted)
        relative_error = residual / (abs(predicted) + 1e-10)

        if uncertainty is not None:
            # 基于不确定性的标准化
            score = min(1.0, residual / (uncertainty + 1e-10))
        else:
            # 基于相对误差
            score = min(1.0, relative_error * 10)

        return float(score)

    def detect_zscore(
        self,
        values: pd.Series,
        threshold: Optional[float] = None
    ) -> pd.Series:
        """基于Z-score检测异常

        Args:
            values: 值序列
            threshold: Z-score阈值

        Returns:
            布尔序列
        """
        if threshold is None:
            threshold = self.threshold

        # 计算滚动Z-score
        rolling_mean = values.rolling(window=self.window, min_periods=1).mean()
        rolling_std = values.rolling(window=self.window, min_periods=1).std()
        z_scores = (values - rolling_mean) / (rolling_std + 1e-10)

        anomalies = z_scores.abs() > threshold

        return anomalies

    def detect_iqr(
        self,
        values: pd.Series,
        multiplier: float = 1.5
    ) -> pd.Series:
        """基于IQR(四分位距)检测异常

        Args:
            values: 值序列
            multiplier: IQR倍数

        Returns:
            布尔序列
        """
        # 计算滚动分位数
        q1 = values.rolling(window=self.window, min_periods=1).quantile(0.25)
        q3 = values.rolling(window=self.window, min_periods=1).quantile(0.75)
        iqr = q3 - q1

        # 定义异常边界
        lower_bound = q1 - multiplier * iqr
        upper_bound = q3 + multiplier * iqr

        anomalies = (values < lower_bound) | (values > upper_bound)

        return anomalies

    def get_anomaly_events(
        self,
        event_type: Optional[str] = None
    ) -> List[Dict]:
        """获取异常事件记录

        Args:
            event_type: 事件类型过滤

        Returns:
            异常事件列表
        """
        if event_type:
            return [e for e in self.anomaly_events if e['type'] == event_type]
        return self.anomaly_events

    def clear_events(self):
        """清除事件记录"""
        self.anomaly_events = []

    def anomaly_rate(self, anomalies: pd.Series) -> float:
        """计算异常率

        Args:
            anomalies: 布尔序列

        Returns:
            异常率 (0-1)
        """
        if len(anomalies) == 0:
            return 0.0
        return anomalies.sum() / len(anomalies)


class AnomalyIndicator(bt.Indicator):
    """Backtrader异常检测指标"""

    lines = ('is_anomaly', 'anomaly_score', 'deviation')
    params = (
        ('method', 'residual'),
        ('threshold', 3.0),
        ('window', 20),
    )

    plotinfo = dict(
        plot=True,
        subplot=True,
    )

    def __init__(self):
        self.detector = AnomalyDetector(
            method=self.p.method,
            threshold=self.p.threshold,
            window=self.p.window,
        )

        # 存储历史值
        self.actuals = deque(maxlen=self.p.window * 2)
        self.predicteds = deque(maxlen=self.p.window * 2)

    def next(self):
        current = self.data.close[0]
        self.actuals.append(current)

        if len(self.actuals) < self.p.window:
            self.lines.is_anomaly[0] = False
            self.lines.anomaly_score[0] = 0
            self.lines.deviation[0] = 0
            return

        # 计算预测(简单使用移动平均)
        actual_series = pd.Series(list(self.actuals))
        predicted = actual_series.rolling(self.p.window).mean().iloc[-1]

        # 检测异常
        if self.p.method == 'residual':
            anomalies = self.detector.detect_residual_anomaly(
                actual_series[-self.p.window:],
                pd.Series([predicted] * len(actual_series[-self.p.window:])),
                threshold=self.p.threshold,
            )
            is_anomaly = anomalies.iloc[-1] if len(anomalies) > 0 else False
        else:
            # Z-score方法
            z_score = abs(current - predicted) / (actual_series.std() + 1e-10)
            is_anomaly = z_score > self.p.threshold

        # 计算异常得分
        anomaly_score = self.detector.anomaly_score(current, predicted)

        # 计算偏差
        deviation = (current - predicted) / (predicted + 1e-10)

        self.lines.is_anomaly[0] = int(is_anomaly)
        self.lines.anomaly_score[0] = anomaly_score
        self.lines.deviation[0] = deviation
```

### 3.5 不确定性量化模块

```python
"""
backtrader/forecasting/uncertainty.py

不确定性量化模块
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, Optional
from scipy import stats


class UncertaintyQuantifier:
    """不确定性量化器

    量化预测的不确定性并用于风险管理
    """

    def __init__(self, confidence_level: float = 0.8):
        """
        Args:
            confidence_level: 默认置信水平
        """
        self.confidence_level = confidence_level

    def prediction_interval(
        self,
        forecast: pd.Series,
        std_error: Optional[pd.Series] = None,
        confidence: Optional[float] = None
    ) -> Tuple[pd.Series, pd.Series]:
        """计算预测区间

        Args:
            forecast: 预测值序列
            std_error: 标准误序列
            confidence: 置信水平

        Returns:
            (下界, 上界)
        """
        if confidence is None:
            confidence = self.confidence_level

        # 计算Z值
        z_value = stats.norm.ppf((1 + confidence) / 2)

        if std_error is None:
            # 使用历史波动率估计
            std_error = forecast.rolling(window=20, min_periods=1).std()

        # 计算区间
        margin = z_value * std_error
        lower = forecast - margin
        upper = forecast + margin

        return lower, upper

    def confidence_score(
        self,
        actual: float,
        predicted: float,
        lower: float,
        upper: float
    ) -> float:
        """计算置信度得分

        基于实际值是否在预测区间内

        Args:
            actual: 实际值
            predicted: 预测值
            lower: 预测下界
            upper: 预测上界

        Returns:
            置信度得分 (0-1)
        """
        if lower <= actual <= upper:
            # 在区间内，计算相对位置
            if upper > lower:
                position = (actual - lower) / (upper - lower)
                # 越接近中心，得分越高
                return 1 - 2 * abs(position - 0.5)
            else:
                return 1.0
        else:
            # 在区间外，计算距离
            if actual < lower:
                distance = (lower - actual) / (abs(predicted) + 1e-10)
            else:
                distance = (actual - upper) / (abs(predicted) + 1e-10)

            # 距离越远，得分越低
            return max(0, 1 - distance * 2)

    def risk_measure(
        self,
        uncertainty: float,
        predicted: float,
        method: str = 'relative'
    ) -> float:
        """计算风险度量

        Args:
            uncertainty: 不确定性(标准差)
            predicted: 预测值
            method: 风险度量方法

        Returns:
            风险值
        """
        if method == 'relative':
            # 相对不确定性
            return uncertainty / (abs(predicted) + 1e-10)
        elif method == 'absolute':
            # 绝对不确定性
            return uncertainty
        elif method == 'coeff_var':
            # 变异系数
            return uncertainty / (abs(predicted) + 1e-10) * 100
        else:
            return uncertainty

    def position_sizing(
        self,
        confidence: float,
        base_size: float = 1.0,
        min_size: float = 0.1,
        max_size: float = 1.0
    ) -> float:
        """根据置信度调整仓位

        Args:
            confidence: 置信度 (0-1)
            base_size: 基础仓位
            min_size: 最小仓位
            max_size: 最大仓位

        Returns:
            调整后的仓位
        """
        # 线性调整
        adjusted_size = base_size * confidence

        # 限制范围
        return max(min_size, min(max_size, adjusted_size))

    def value_at_risk(
        self,
        returns: pd.Series,
        confidence: float = 0.95
    ) -> float:
        """计算VaR(风险价值)

        Args:
            returns: 收益序列
            confidence: 置信水平

        Returns:
            VaR值
        """
        return np.percentile(returns, (1 - confidence) * 100)

    def conditional_var(
        self,
        returns: pd.Series,
        confidence: float = 0.95
    ) -> float:
        """计算CVaR(条件风险价值)

        超过VaR的平均损失

        Args:
            returns: 收益序列
            confidence: 置信水平

        Returns:
            CVaR值
        """
        var = self.value_at_risk(returns, confidence)
        return returns[returns <= var].mean()

    def ensemble_uncertainty(
        self,
        predictions: np.ndarray
    ) -> Tuple[float, float]:
        """集成预测的不确定性

        Args:
            predictions: 多个模型的预测 (n_samples, n_predictions)

        Returns:
            (均值, 标准差)
        """
        mean = np.mean(predictions, axis=0)
        std = np.std(predictions, axis=0)
        return mean, std


class UncertaintyIndicator(bt.Indicator):
    """Backtrader不确定性指标"""

    lines = ('uncertainty', 'confidence', 'position_size',)
    params = (
        ('window', 20),
        ('base_position', 0.95),
        ('min_position', 0.1),
    )

    plotinfo = dict(
        plot=True,
        subplot=True,
    )

    def __init__(self):
        self.quantifier = UncertaintyQuantifier()
        self.predictions = deque(maxlen=self.p.window)
        self.actuals = deque(maxlen=self.p.window)

    def next(self):
        current = self.data.close[0]
        self.actuals.append(current)

        if len(self.actuals) < self.p.window:
            self.lines.uncertainty[0] = 0
            self.lines.confidence[0] = 0.5
            self.lines.position_size[0] = self.p.min_position
            return

        # 计算历史波动率作为不确定性
        returns = pd.Series(list(self.actuals)).pct_change().dropna()
        uncertainty = returns.rolling(min(len(returns), self.p.window)).std().iloc[-1]

        # 基于波动率计算置信度
        # 波动率越低，置信度越高
        confidence = 1 / (1 + uncertainty * 10)
        confidence = max(0, min(1, confidence))

        # 调整仓位
        position_size = self.quantifier.position_sizing(
            confidence,
            base_size=self.p.base_position,
            min_size=self.p.min_position,
            max_size=1.0,
        )

        self.lines.uncertainty[0] = uncertainty
        self.lines.confidence[0] = confidence
        self.lines.position_size[0] = position_size
```

### 3.6 交叉验证模块

```python
"""
backtrader/forecasting/validation.py

时序交叉验证模块
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Callable
from sklearn.model_selection import ParameterGrid
from datetime import datetime, timedelta


class TimeSeriesCV:
    """时间序列交叉验证

    使用滚动预测方法进行模型验证
    """

    def __init__(
        self,
        horizon: int = 5,
        period: int = 5,
        initial: Optional[int] = None,
    ):
        """
        Args:
            horizon: 预测步长
            period: 滚动周期
            initial: 初始训练窗口大小
        """
        self.horizon = horizon
        self.period = period
        self.initial = initial
        self.results = []

    def rolling_forecast(
        self,
        data: pd.DataFrame,
        model_fn: Callable,
        **model_params
    ) -> pd.DataFrame:
        """执行滚动预测验证

        Args:
            data: 包含'ds'和'y'列的数据
            model_fn: 模型训练函数
            **model_params: 模型参数

        Returns:
            预测结果DataFrame
        """
        if 'ds' not in data.columns or 'y' not in data.columns:
            raise ValueError("Data must contain 'ds' and 'y' columns")

        if self.initial is None:
            self.initial = len(data) // 2

        predictions = []
        actuals = []
        cutoffs = []

        # 滚动预测
        for start in range(self.initial, len(data) - self.horizon + 1, self.period):
            train = data.iloc[:start]
            test = data.iloc[start:start + self.horizon]

            # 训练模型
            model = model_fn(**model_params)
            model.fit(train)

            # 预测
            forecast = model.predict(test[['ds']])

            predictions.extend(forecast['yhat'].values)
            actuals.extend(test['y'].values)
            cutoffs.extend([train['ds'].iloc[-1]] * len(test))

        return pd.DataFrame({
            'ds': cutoffs,
            'yhat': predictions,
            'y': actuals,
        })

    def calculate_metrics(
        self,
        actual: pd.Series,
        predicted: pd.Series
    ) -> Dict[str, float]:
        """计算预测性能指标

        Args:
            actual: 实际值
            predicted: 预测值

        Returns:
            指标字典
        """
        # 移除NaN
        mask = ~(actual.isna() | predicted.isna())
        actual = actual[mask]
        predicted = predicted[mask]

        if len(actual) == 0:
            return {}

        # 计算各种误差
        errors = actual - predicted
        abs_errors = errors.abs()
        pct_errors = (errors / actual).abs()
        squared_errors = errors ** 2

        metrics = {
            'mse': squared_errors.mean(),
            'rmse': np.sqrt(squared_errors.mean()),
            'mae': abs_errors.mean(),
            'mape': pct_errors.mean() * 100,
            'mdape': (pct_errors * 100).median(),
        }

        # 对称MAPE
        sape = (errors.abs() / ((actual.abs() + predicted.abs()) / 2))
        metrics['smape'] = sape.mean() * 100

        # 覆盖率(如果预测包含区间)
        if 'lower' in predicted and 'upper' in predicted:
            coverage = ((actual >= predicted['lower']) & (actual <= predicted['upper'])).mean()
            metrics['coverage'] = coverage

        return metrics

    def grid_search(
        self,
        data: pd.DataFrame,
        model_fn: Callable,
        param_grid: Dict[str, List[Any]],
        metric: str = 'mape',
        lower_is_better: bool = True,
    ) -> Dict[str, Any]:
        """参数网格搜索

        Args:
            data: 训练数据
            model_fn: 模型函数
            param_grid: 参数网格
            metric: 优化指标
            lower_is_better: 是否越小越好

        Returns:
            最佳参数和结果
        """
        best_score = float('inf') if lower_is_better else float('-inf')
        best_params = None
        all_results = []

        for params in ParameterGrid(param_grid):
            # 执行交叉验证
            cv_results = self.rolling_forecast(data, model_fn, **params)

            # 计算指标
            metrics = self.calculate_metrics(cv_results['y'], cv_results['yhat'])

            if metric in metrics:
                score = metrics[metric]

                # 更新最佳参数
                is_better = (score < best_score) if lower_is_better else (score > best_score)
                if is_better:
                    best_score = score
                    best_params = params.copy()

                all_results.append({
                    'params': params,
                    'score': score,
                    'metrics': metrics,
                })

        return {
            'best_params': best_params,
            'best_score': best_score,
            'all_results': all_results,
        }

    def cross_validate(
        self,
        data: pd.DataFrame,
        model_fn: Callable,
        n_folds: int = 5,
        **model_params
    ) -> Dict[str, float]:
        """K折交叉验证(时序版本)

        Args:
            data: 数据
            model_fn: 模型函数
            n_folds: 折数
            **model_params: 模型参数

        Returns:
            各折的平均指标
        """
        fold_size = len(data) // n_folds
        all_metrics = []

        for i in range(1, n_folds + 1):
            train_size = i * fold_size
            if train_size + self.horizon > len(data):
                break

            train = data.iloc[:train_size]
            test = data.iloc[train_size:train_size + self.horizon]

            # 训练和预测
            model = model_fn(**model_params)
            model.fit(train)
            forecast = model.predict(test[['ds']])

            # 计算指标
            metrics = self.calculate_metrics(test['y'], forecast['yhat'])
            all_metrics.append(metrics)

        # 平均指标
        avg_metrics = {}
        for key in all_metrics[0].keys():
            values = [m[key] for m in all_metrics if not np.isnan(m[key])]
            if values:
                avg_metrics[key] = np.mean(values)

        return avg_metrics

    def best_params(self) -> Dict[str, Any]:
        """获取最佳参数"""
        return getattr(self, '_best_params', {})


class BacktestValidator:
    """回测验证器

    将Prophet预测与backtrader回测结合
    """

    def __init__(self, cerebro, strategy_class):
        """
        Args:
            cerebro: backtrader Cerebro实例
            strategy_class: 策略类
        """
        self.cerebro = cerebro
        self.strategy_class = strategy_class

    def validate(
        self,
        data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
        metrics: List[str] = None
    ) -> pd.DataFrame:
        """回测验证

        Args:
            data: 价格数据
            param_grid: 参数网格
            metrics: 评估指标

        Returns:
            验证结果DataFrame
        """
        if metrics is None:
            metrics = ['sharpe', 'return', 'max_drawdown']

        results = []

        for params in ParameterGrid(param_grid):
            # 创建策略实例
            strat = self.strategy_class(**params)

            # 运行回测
            cerebro = bt.Cerebro()
            cerebro.adddata(bt.feeds.PandasData(dataname=data))
            cerebro.addstrategy(strat)
            cerebro.broker.setcash(100000)

            results_list = cerebro.run()
            strat = results_list[0]

            # 提取指标
            result = {'params': params}

            if hasattr(strat, 'analyzers'):
                for analyzer in strat.analyzers:
                    result.update(analyzer.get_analysis())

            results.append(result)

        return pd.DataFrame(results)


class ModelComparator:
    """模型比较器

    比较不同预测模型的性能
    """

    def __init__(self):
        self.models = {}
        self.results = {}

    def add_model(self, name: str, model_fn: Callable, params: Dict):
        """添加模型"""
        self.models[name] = {
            'fn': model_fn,
            'params': params,
        }

    def compare(
        self,
        data: pd.DataFrame,
        cv: TimeSeriesCV,
    ) -> pd.DataFrame:
        """比较模型

        Args:
            data: 测试数据
            cv: 交叉验证器

        Returns:
            比较结果DataFrame
        """
        comparison = []

        for name, model_info in self.models.items():
            # 执行交叉验证
            cv_results = cv.rolling_forecast(
                data,
                model_info['fn'],
                **model_info['params']
            )

            # 计算指标
            metrics = cv.calculate_metrics(cv_results['y'], cv_results['yhat'])
            metrics['model'] = name

            comparison.append(metrics)

        df = pd.DataFrame(comparison)
        df = df.set_index('model')

        return df

    def ensemble(
        self,
        data: pd.DataFrame,
        weights: Optional[Dict[str, float]] = None
    ) -> np.ndarray:
        """集成预测

        Args:
            data: 输入数据
            weights: 模型权重

        Returns:
            集成预测结果
        """
        predictions = []

        for name, model_info in self.models.items():
            model = model_info['fn'](**model_info['params'])
            model.fit(data)
            pred = model.predict(data[['ds']])
            predictions.append(pred['yhat'].values)

        predictions = np.array(predictions)

        if weights is None:
            # 等权重平均
            return predictions.mean(axis=0)
        else:
            # 加权平均
            weight_array = np.array([weights.get(name, 1.0) for name in self.models.keys()])
            weight_array = weight_array / weight_array.sum()
            return (predictions * weight_array[:, None]).sum(axis=0)
```

---

## 四、使用示例

### 4.1 基础Prophet策略使用

```python
"""
基础Prophet策略使用示例
"""

import backtrader as bt
import pandas as pd
from backtrader.forecasting.strategies import ProphetStrategy

# 1. 准备数据
df = pd.read_csv('price_data.csv')
df['date'] = pd.to_datetime(df['date'])
df = df.set_index('date')

# 2. 创建Cerebro引擎
cerebro = bt.Cerebro()

# 3. 添加数据
data = bt.feeds.PandasData(dataname=df)
cerebro.adddata(data)

# 4. 添加Prophet策略
cerebro.addstrategy(
    ProphetStrategy,
    train_period=252,
    prediction_horizon=5,
    signal_threshold=0.02,
    use_uncertainty=True,
    min_confidence=0.6,
    position_size=0.95,
)

# 5. 设置初始资金和佣金
cerebro.broker.setcash(100000)
cerebro.broker.setcommission(commission=0.001)

# 6. 运行回测
results = cerebro.run()
print(f'最终净值: {cerebro.broker.getvalue():.2f}')
```

### 4.2 趋势分析使用

```python
"""
趋势分析使用示例
"""

from backtrader.forecasting.trend import TrendAnalyzer

analyzer = TrendAnalyzer(min_period=20)

# 检测趋势
prices = pd.Series(...)  # 价格数据
trend = analyzer.detect_trend(prices)
print(f"趋势方向: {trend}")

# 趋势强度
strength = analyzer.trend_strength(prices)
print(f"趋势强度: {strength:.2f}")

# 变化点检测
changepoints = analyzer.find_changepoints(prices)
print(f"趋势变化点: {changepoints}")

# 趋势段分解
segments = analyzer.trend_segments(prices, changepoints)
for seg in segments:
    print(f"段 {seg['start']}-{seg['end']}: {seg['trend']}, "
          f"收益率: {seg['return']:.2%}")
```

### 4.3 交叉验证和参数优化

```python
"""
交叉验证和参数优化示例
"""

from backtrader.forecasting.validation import TimeSeriesCV

# 准备Prophet格式的数据
data = pd.DataFrame({
    'ds': pd.date_range(start='2020-01-01', periods=1000),
    'y': np.random.randn(1000).cumsum() + 100
})

# 创建交叉验证器
cv = TimeSeriesCV(
    horizon=5,    # 预测5步
    period=5,     # 每5步滚动一次
    initial=500,  # 初始训练500步
)

# 参数网格
param_grid = {
    'growth': ['linear', 'flat'],
    'seasonality_mode': ['additive', 'multiplicative'],
    'yearly_seasonality': [True, False],
    'weekly_seasonality': [True, False],
}

# 网格搜索
from prophet import Prophet

best = cv.grid_search(
    data,
    Prophet,
    param_grid,
    metric='mape',
    lower_is_better=True,
)

print(f"最佳参数: {best['best_params']}")
print(f"最佳MAPE: {best['best_score']:.2f}%")
```

### 4.4 异常检测使用

```python
"""
异常检测使用示例
"""

from backtrader.forecasting.anomaly import AnomalyDetector

detector = AnomalyDetector(
    method='residual',
    threshold=3.0,
    window=20,
)

# 基于预测残差检测异常
actual = pd.Series(...)  # 实际价格
predicted = pd.Series(...)  # 预测价格

anomalies = detector.detect_residual_anomaly(actual, predicted)
print(f"检测到 {anomalies.sum()} 个异常点")

# 获取异常事件
events = detector.get_anomaly_events()
for event in events[:5]:
    print(f"时间: {event['timestamp']}, "
          f"实际值: {event['actual']:.2f}, "
          f"预测值: {event['predicted']:.2f}")
```

---

## 五、目录结构

```
backtrader/
├── forecasting/               # 时序预测模块
│   ├── __init__.py
│   ├── strategies.py          # 预测策略
│   ├── trend.py               # 趋势分析
│   ├── seasonality.py         # 季节性分析
│   ├── anomaly.py             # 异常检测
│   ├── uncertainty.py         # 不确定性量化
│   └── validation.py          # 交叉验证
│
├── indicators/
│   └── prophet.py             # Prophet指标
│
└── utils/
    ├── date_utils.py          # 日期工具
    └── math_utils.py          # 数学工具
```

---

## 六、实施计划

### 第一阶段（高优先级）

1. **Prophet预测策略** (~500行)
   - ProphetIndicator指标
   - ProphetSignal信号指标
   - ProphetStrategy策略基类

2. **趋势分析模块** (~300行)
   - 趋势方向检测
   - 趋势强度计算
   - 变化点检测

3. **不确定性量化** (~200行)
   - 预测区间计算
   - 置信度评估
   - 基于置信度的仓位调整

### 第二阶段（中优先级）

4. **季节性分析模块** (~300行)
   - 年/周/日季节性
   - 自定义季节性
   - 季节性强度评估

5. **异常检测模块** (~250行)
   - 残差异常检测
   - 区间异常检测
   - 异常事件记录

6. **交叉验证模块** (~300行)
   - 滚动预测验证
   - 性能指标计算
   - 参数网格搜索

### 第三阶段（可选）

7. **高级功能**
   - 多模型集成
   - 在线学习
   - 自动特征工程
   - 模型可解释性增强

---

## 七、与现有功能对比

| 功能 | backtrader (原生) | 预测扩展 |
|------|------------------|----------|
| 时序预测 | 无 | Prophet集成 |
| 趋势分析 | 手动计算指标 | 自动检测+强度评估 |
| 季节性 | 需手动实现 | 多周期季节性建模 |
| 节假日效应 | 无 | 内置国家节假日 |
| 异常检测 | 无 | 多方法异常检测 |
| 不确定性量化 | 无 | 预测区间+置信度 |
| 参数优化 | 手动 | 交叉验证自动调优 |
| 可解释性 | 指标可解释 | 完整分量分解 |

---

## 八、向后兼容性

所有预测功能均为**完全可选的独立模块**：

1. 预测功能通过`from backtrader.forecasting import ...`使用
2. 不影响现有策略的运行
3. 用户可以选择使用传统策略或预测策略
4. 预测指标可以与传统指标结合使用
5. Prophet为可选依赖，未安装时自动降级到简单方法
