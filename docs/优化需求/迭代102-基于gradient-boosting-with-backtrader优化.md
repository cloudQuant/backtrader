### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/gradient-boosting-with-backtrader
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### gradient-boosting-with-backtrader项目简介
gradient-boosting-with-backtrader是将梯度提升算法与backtrader结合的项目，具有以下核心特点：
- **梯度提升**: 使用XGBoost/LightGBM
- **特征工程**: 金融特征工程
- **模型集成**: ML模型与回测集成
- **预测信号**: ML预测生成信号
- **模型评估**: 模型性能评估
- **在线预测**: 实时预测支持

### 重点借鉴方向
1. **ML集成**: 机器学习模型集成
2. **特征工程**: 金融特征构建
3. **模型训练**: 模型训练流程
4. **信号生成**: ML信号生成
5. **模型更新**: 在线模型更新
6. **回测验证**: ML策略回测验证

---

# 分析与设计文档

## 一、框架对比分析

### 1.1 backtrader vs gradient-boosting-with-backtrader 对比

| 维度 | backtrader (原生) | gradient-boosting-with-backtrader |
|------|------------------|----------------------------------|
| **定位** | 回测框架 | ML驱动的量化交易系统 |
| **策略类型** | 规则型策略 | ML预测型策略 |
| **特征工程** | 手动计算技术指标 | 系统化特征工程流程 |
| **模型支持** | 无 | XGBoost/LightGBM/CatBoost |
| **信号生成** | 基于规则 | 基于ML预测 |
| **数据分割** | 无 | 时间序列交叉验证 |
| **模型评估** | 回测指标 | ML指标+回测指标 |
| **在线学习** | 无 | 滚动窗口预测 |
| **特征重要性** | 无 | 模型可解释性 |

### 1.2 可借鉴的核心优势

1. **ML策略模板**: 将ML模型与backtrader策略无缝集成
2. **特征工程管道**: 系统化的金融特征构建和选择
3. **时间序列验证**: 避免未来信息泄露的验证方法
4. **置信度交易**: 基于预测置信度的交易决策
5. **滚动预测**: 支持在线模型更新和滚动预测
6. **双重评估**: ML指标和回测指标的联合评估

---

## 二、需求规格文档

### 2.1 ML策略基类

**需求描述**: 创建一个通用的机器学习策略基类，简化ML模型与backtrader的集成。

**功能要求**:
- 接收预计算的预测结果
- 支持置信度阈值过滤
- 支持多分类信号处理
- 内置仓位管理逻辑

**接口定义**:
```python
class MLStrategy(bt.Strategy):
    params = (
        ('predictions', None),        # 预测序列
        ('probabilities', None),      # 概率序列
        ('threshold', 0.5),           # 信号阈值
        ('position_size', 0.95),      # 仓位比例
    )
```

### 2.2 金融特征工程模块

**需求描述**: 提供丰富的金融技术指标特征构建功能。

**功能要求**:
- 趋势类特征（MA、EMA、MACD）
- 动量类特征（RSI、ROC、动量）
- 波动性特征（ATR、布林带、标准差）
- 成交量特征（OBV、MFI、成交量MA）
- 交互特征（特征组合）
- 特征标准化和归一化

**特征类别**:
```python
# 趋势特征 (20+)
SMA, EMA, MACD, ADX, DMI

# 动量特征 (10+)
RSI, ROC, Stochastic, Williams %R

# 波动性特征 (8+)
ATR, Bollinger Bands, Keltner Channels

# 成交量特征 (6+)
OBV, MVI, Volume MA, Volume Profile
```

### 2.3 时间序列数据分割

**需求描述**: 提供专门针对时间序列数据的分割方法。

**功能要求**:
- 按时间顺序分割（避免数据泄露）
- 时间序列交叉验证（TimeSeriesSplit）
- 滚动窗口分割
- 纯样本外验证

**API设计**:
```python
def time_series_split(X, y, test_size=0.2, gap=0):
    """时间序列分割

    Args:
        X: 特征数据
        y: 目标变量
        test_size: 测试集比例
        gap: 训练集和测试集之间的间隔
    """
```

### 2.4 模型训练器

**需求描述**: 统一的模型训练和评估接口。

**功能要求**:
- 支持多种梯度提升模型
- 超参数调优
- 早停机制
- 特征重要性分析
- 模型持久化

**支持的模型**:
```python
MODELS = {
    'xgboost': XGBClassifier,
    'lightgbm': LGBMClassifier,
    'catboost': CatBoostClassifier,
    'sklearn_gb': GradientBoostingClassifier,
}
```

### 2.5 信号生成器

**需求描述**: 将ML预测转换为交易信号。

**功能要求**:
- 二分类信号（买入/卖出）
- 多分类信号（买入/持有/卖出）
- 置信度阈值
- 信号平滑处理

**信号类型**:
```python
SignalType = Enum('SignalType', [
    'BINARY',      # 0/1 二分类
    'TERNARY',     # -1/0/1 三分类
    'PROBABILITY', # 概率值
    'REGRESSION',  # 回归值
])
```

### 2.6 回测评估器

**需求描述**: 同时评估ML模型性能和回测性能。

**功能要求**:
- ML分类指标（准确率、AUC、F1）
- 回测性能指标（收益率、夏普比率、最大回撤）
- 特征重要性分析
- 混淆矩阵可视化

---

## 三、详细设计文档

### 3.1 ML策略基类实现

**设计思路**: 创建一个通用的ML策略基类，接收预计算的预测结果。

```python
# backtrader/strategies/ml_strategy.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import numpy as np
from .. import strategy

logger = logging.getLogger(__name__)


class MLSignalStrategy(strategy.Strategy):
    """机器学习信号策略基类

    使用预计算的ML预测结果生成交易信号

    使用方式:
        predictions = model.predict(X_test)
        probabilities = model.predict_proba(X_test)

        cerebro.addstrategy(MLSignalStrategy,
                          predictions=predictions,
                          probabilities=probabilities,
                          threshold=0.6)
    """

    params = (
        ('predictions', None),       # 预测序列 (N,) 数组
        ('probabilities', None),     # 概率序列 (N, 2) 数组
        ('threshold', 0.5),          # 交易阈值
        ('buy_threshold', None),     # 买入阈值（单独设置）
        ('sell_threshold', None),    # 卖出阈值（单独设置）
        ('position_size', 0.95),     # 仓位比例
        ('signal_type', 'binary'),   # 信号类型: binary, ternary, probability
        ('use_confidence', True),    # 是否使用置信度
        ('min_hold_bars', 0),        # 最小持有天数
        ('stop_loss_pct', None),     # 止损百分比
        ('take_profit_pct', None),   # 止盈百分比
    )

    def __init__(self):
        super(MLSignalStrategy, self).__init__()

        # 验证参数
        if self.p.predictions is None:
            raise ValueError("predictions参数不能为空")

        # 预测索引
        self._pred_idx = 0
        self._hold_count = 0

        # 信号记录
        self.signals = []
        self.confidence_history = []

    def next(self):
        """主交易逻辑"""
        # 检查是否还有预测数据
        if self._pred_idx >= len(self.p.predictions):
            return

        # 获取当前预测
        prediction = self.p.predictions[self._pred_idx]
        confidence = self._get_confidence()

        # 记录信号
        self.signals.append(prediction)
        self.confidence_history.append(confidence)

        # 根据信号类型执行交易
        if self.p.signal_type == 'binary':
            self._handle_binary_signal(prediction, confidence)
        elif self.p.signal_type == 'ternary':
            self._handle_ternary_signal(prediction, confidence)
        elif self.p.signal_type == 'probability':
            self._handle_probability_signal(prediction, confidence)

        # 更新索引
        self._pred_idx += 1

    def _get_confidence(self):
        """获取当前置信度"""
        if self.p.probabilities is not None:
            probs = self.p.probabilities[self._pred_idx]
            # 返回最大概率对应的置信度
            return np.max(probs)
        return 1.0

    def _handle_binary_signal(self, prediction, confidence):
        """处理二分类信号 (0/1)"""
        buy_threshold = self.p.buy_threshold or self.p.threshold
        sell_threshold = self.p.sell_threshold or self.p.threshold

        # 买入逻辑
        if prediction == 1 and confidence >= buy_threshold:
            if not self.position:
                # 开仓
                size = self.broker.getcash() * self.p.position_size / self.data.close[0]
                self.buy(size=size)
                self._hold_count = 0
                logger.info(f'买入信号 (confidence={confidence:.3f})')
            elif self._hold_count >= self.p.min_hold_bars:
                # 加仓
                size = self.broker.getcash() * self.p.position_size / self.data.close[0]
                self.buy(size=size)

        # 卖出逻辑
        elif prediction == 0:
            if self.position:
                if self._hold_count >= self.p.min_hold_bars:
                    self.close()
                    logger.info(f'卖出信号 (confidence={confidence:.3f})')

        # 持仓计数
        if self.position:
            self._hold_count += 1
            self._apply_stop_loss_take_profit()

    def _handle_ternary_signal(self, prediction, confidence):
        """处理三分类信号 (-1/0/1)"""
        # prediction: -1=卖出, 0=持有, 1=买入

        if prediction == 1:  # 买入
            if not self.position:
                size = self.broker.getcash() * self.p.position_size / self.data.close[0]
                self.buy(size=size)
                self._hold_count = 0
            elif self.position.size < 0:  # 空头持仓
                self.close()

        elif prediction == -1:  # 卖出
            if self.position and self.position.size > 0:  # 多头持仓
                if self._hold_count >= self.p.min_hold_bars:
                    self.close()

        # prediction == 0: 持有，不操作

        if self.position:
            self._hold_count += 1

    def _handle_probability_signal(self, prediction, confidence):
        """处理概率信号 (0-1连续值)"""
        # prediction 直接作为买入概率

        buy_threshold = self.p.buy_threshold or 0.6
        sell_threshold = self.p.sell_threshold or 0.4

        if prediction > buy_threshold:
            if not self.position:
                # 根据概率调整仓位
                size = self.broker.getcash() * prediction * self.p.position_size / self.data.close[0]
                self.buy(size=size)
                self._hold_count = 0

        elif prediction < sell_threshold:
            if self.position and self._hold_count >= self.p.min_hold_bars:
                self.close()

        if self.position:
            self._hold_count += 1

    def _apply_stop_loss_take_profit(self):
        """应用止损止盈"""
        if not self.position:
            return

        entry_price = self.position.price
        current_price = self.data.close[0]

        # 止损
        if self.p.stop_loss_pct:
            if self.position.size > 0:  # 多头
                stop_price = entry_price * (1 - self.p.stop_loss_pct)
            else:  # 空头
                stop_price = entry_price * (1 + self.p.stop_loss_pct)

            if current_price <= stop_price:
                self.close()
                logger.info(f'止损: {current_price:.2f} <= {stop_price:.2f}')
                return

        # 止盈
        if self.p.take_profit_pct:
            if self.position.size > 0:  # 多头
                target_price = entry_price * (1 + self.p.take_profit_pct)
            else:  # 空头
                target_price = entry_price * (1 - self.p.take_profit_pct)

            if current_price >= target_price:
                self.close()
                logger.info(f'止盈: {current_price:.2f} >= {target_price:.2f}')
```

### 3.2 金融特征工程模块

**设计思路**: 提供系统化的金融特征构建管道。

```python
# backtrader/ML/features.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """金融特征工程器

    提供:
    - 趋势类特征
    - 动量类特征
    - 波动性特征
    - 成交量特征
    - 交互特征
    """

    def __init__(self, price_cols: Dict[str, str] = None):
        """
        Args:
            price_cols: 价格列名映射
                {'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'}
        """
        self.price_cols = price_cols or {
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'volume': 'volume'
        }

    def fit(self, data: pd.DataFrame):
        """拟合特征工程器（计算统计量）"""
        self._feature_stats = {}
        return self

    def transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """转换数据，生成特征"""
        df = data.copy()

        # 生成各类特征
        df = self._add_trend_features(df)
        df = self._add_momentum_features(df)
        df = self._add_volatility_features(df)
        df = self._add_volume_features(df)
        df = self._add_interaction_features(df)

        return df

    def fit_transform(self, data: pd.DataFrame) -> pd.DataFrame:
        """拟合并转换"""
        return self.fit(data).transform(data)

    def _add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加趋势类特征"""
        c = self.price_cols['close']
        h = self.price_cols['high']
        l = self.price_cols['low']

        # 移动平均线
        for period in [5, 10, 20, 30, 60, 120]:
            df[f'sma_{period}'] = df[c].rolling(window=period).mean()
            df[f'ema_{period}'] = df[c].ewm(span=period, adjust=False).mean()

        # MACD
        ema_12 = df[c].ewm(span=12, adjust=False).mean()
        ema_26 = df[c].ewm(span=26, adjust=False).mean()
        df['macd'] = ema_12 - ema_26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # ADX和DMI
        df['adx'] = self._calculate_adx(df, period=14)
        df['pdi'] = self._calculate_pdi(df, period=14)
        df['mdi'] = self._calculate_mdi(df, period=14)

        # 价格相对位置
        for period in [5, 10, 20, 60]:
            df[f'price_rank_{period}'] = (
                df[c].rolling(window=period).apply(
                    lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) if x.max() != x.min() else 0.5
                )
            )

        return df

    def _add_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加动量类特征"""
        c = self.price_cols['close']

        # RSI
        for period in [6, 12, 14, 20]:
            df[f'rsi_{period}'] = self._calculate_rsi(df[c], period)

        # ROC (Rate of Change)
        for period in [1, 5, 10, 20]:
            df[f'roc_{period}'] = df[c].pct_change(period)

        # 动量
        for period in [5, 10, 20]:
            df[f'momentum_{period}'] = df[c] - df[c].shift(period)

        # 随机指标 (Stochastic Oscillator)
        df['stoch_k'] = self._calculate_stochastic_k(df, period=14)
        df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()

        # 威廉指标 %R
        df['williams_r'] = self._calculate_williams_r(df, period=14)

        # CCI (Commodity Channel Index)
        df['cci'] = self._calculate_cci(df, period=20)

        return df

    def _add_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加波动性特征"""
        c = self.price_cols['close']
        h = self.price_cols['high']
        l = self.price_cols['low']

        # ATR (Average True Range)
        for period in [7, 14, 20]:
            df[f'atr_{period}'] = self._calculate_atr(df, period)

        # 布林带
        for period in [10, 20, 30]:
            sma = df[c].rolling(window=period).mean()
            std = df[c].rolling(window=period).std()
            df[f'bb_upper_{period}'] = sma + 2 * std
            df[f'bb_lower_{period}'] = sma - 2 * std
            df[f'bb_width_{period}'] = (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}']) / sma
            df[f'bb_pct_{period}'] = (df[c] - df[f'bb_lower_{period}']) / (df[f'bb_upper_{period}'] - df[f'bb_lower_{period}'])

        # 历史波动率
        for period in [10, 20, 30]:
            returns = df[c].pct_change()
            df[f'hist_vol_{period}'] = returns.rolling(window=period).std() * np.sqrt(252)

        # Parkinson波动率
        df['parkinson_vol'] = np.sqrt(
            (np.log(h / l) ** 2).rolling(window=20).mean() / (4 * np.log(2))
        )

        return df

    def _add_volume_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加成交量特征"""
        v = self.price_cols['volume']
        c = self.price_cols['close']

        # 成交量移动平均
        for period in [5, 10, 20, 60]:
            df[f'volume_ma_{period}'] = df[v].rolling(window=period).mean()
            df[f'volume_ratio_{period}'] = df[v] / df[f'volume_ma_{period}']

        # OBV (On Balance Volume)
        df['obv'] = self._calculate_obv(df)

        # MFI (Money Flow Index)
        df['mfi'] = self._calculate_mfi(df, period=14)

        # VWAP (Volume Weighted Average Price)
        typical_price = (df[self.price_cols['high']] +
                        df[self.price_cols['low']] +
                        df[self.price_cols['close']]) / 3
        df['vwap'] = (typical_price * df[v]).cumsum() / df[v].cumsum()

        # 价量趋势
        df['price_volume_trend'] = df[c].pct_change() * df[v].pct_change()

        return df

    def _add_interaction_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加交互特征"""
        c = self.price_cols['close']

        # 趋势与动量交互
        if 'ema_20' in df.columns and 'rsi_14' in df.columns:
            df['inter_trend_momentum'] = df['ema_20'] * df['rsi_14'] / 100

        # 趋势与波动性交互
        if 'ema_20' in df.columns and 'atr_14' in df.columns:
            df['inter_trend_volatility'] = df['ema_20'] / (df['atr_14'] + 1e-6)

        # 价格与成交量交互
        if 'roc_5' in df.columns and 'volume_ratio_5' in df.columns:
            df['inter_price_volume'] = df['roc_5'] * df['volume_ratio_5']

        # 布林带位置与RSI组合
        if 'bb_pct_20' in df.columns and 'rsi_14' in df.columns:
            df['inter_bb_rsi'] = df['bb_pct_20'] * df['rsi_14'] / 100

        return df

    # === 技术指标计算辅助方法 ===

    @staticmethod
    def _calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
        """计算RSI"""
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / (loss + 1e-10)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ATR"""
        h = df[FeatureEngineer._price_col('high', df)]
        l = df[FeatureEngineer._price_col('low', df)]
        c = df[FeatureEngineer._price_col('close', df)]

        prev_close = c.shift(1)
        tr1 = h - l
        tr2 = (h - prev_close).abs()
        tr3 = (l - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        return tr.rolling(window=period).mean()

    @staticmethod
    def _calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算ADX"""
        # +DX和-DX
        pdi = FeatureEngineer._calculate_pdi(df, period)
        mdi = FeatureEngineer._calculate_mdi(df, period)

        # DX和ADX
        dx = (pdi - mdi).abs() / (pdi + mdi + 1e-10) * 100
        return dx.rolling(window=period).mean()

    @staticmethod
    def _calculate_pdi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算+DI"""
        h = df[FeatureEngineer._price_col('high', df)]
        l = df[FeatureEngineer._price_col('low', df)]
        prev_h = h.shift(1)
        prev_l = l.shift(1)

        plus_dm = h - prev_h
        minus_dm = prev_l - l
        plus_dm = plus_dm.where((plus_dm > 0) & (minus_dm <= 0), 0)
        minus_dm = minus_dm.where((minus_dm > 0) & (plus_dm <= 0), 0)

        atr = FeatureEngineer._calculate_atr(df, period)

        plus_di = 100 * (plus_dm.rolling(window=period).mean() / (atr + 1e-10))
        return plus_di

    @staticmethod
    def _calculate_mdi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算-DI"""
        h = df[FeatureEngineer._price_col('high', df)]
        l = df[FeatureEngineer._price_col('low', df)]
        prev_h = h.shift(1)
        prev_l = l.shift(1)

        plus_dm = h - prev_h
        minus_dm = prev_l - l
        plus_dm = plus_dm.where((plus_dm > 0) & (minus_dm <= 0), 0)
        minus_dm = minus_dm.where((minus_dm > 0) & (plus_dm <= 0), 0)

        atr = FeatureEngineer._calculate_atr(df, period)

        minus_di = 100 * (minus_dm.rolling(window=period).mean() / (atr + 1e-10))
        return minus_di

    @staticmethod
    def _calculate_stochastic_k(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算随机指标K值"""
        h = df[FeatureEngineer._price_col('high', df)]
        l = df[FeatureEngineer._price_col('low', df)]
        c = df[FeatureEngineer._price_col('close', df)]

        lowest_low = l.rolling(window=period).min()
        highest_high = h.rolling(window=period).max()

        k = 100 * (c - lowest_low) / (highest_high - lowest_low + 1e-10)
        return k

    @staticmethod
    def _calculate_williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算威廉指标%R"""
        h = df[FeatureEngineer._price_col('high', df)]
        l = df[FeatureEngineer._price_col('low', df)]
        c = df[FeatureEngineer._price_col('close', df)]

        highest_high = h.rolling(window=period).max()
        lowest_low = l.rolling(window=period).min()

        r = -100 * (highest_high - c) / (highest_high - lowest_low + 1e-10)
        return r

    @staticmethod
    def _calculate_cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
        """计算CCI"""
        h = df[FeatureEngineer._price_col('high', df)]
        l = df[FeatureEngineer._price_col('low', df)]
        c = df[FeatureEngineer._price_col('close', df)]

        typical_price = (h + l + c) / 3
        sma = typical_price.rolling(window=period).mean()
        mad = typical_price.rolling(window=period).apply(
            lambda x: np.abs(x - x.mean()).mean()
        )

        cci = (typical_price - sma) / (0.015 * mad + 1e-10)
        return cci

    @staticmethod
    def _calculate_obv(df: pd.DataFrame) -> pd.Series:
        """计算OBV"""
        v = df[FeatureEngineer._price_col('volume', df)]
        c = df[FeatureEngineer._price_col('close', df)]

        obv = (v * np.sign(c.diff())).cumsum()
        return obv

    @staticmethod
    def _calculate_mfi(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """计算MFI"""
        h = df[FeatureEngineer._price_col('high', df)]
        l = df[FeatureEngineer._price_col('low', df)]
        c = df[FeatureEngineer._price_col('close', df)]
        v = df[FeatureEngineer._price_col('volume', df)]

        typical_price = (h + l + c) / 3
        money_flow = typical_price * v

        # 涨跌判断
        positive_flow = money_flow.where(typical_price > typical_price.shift(1), 0)
        negative_flow = money_flow.where(typical_price < typical_price.shift(1), 0)

        positive_mf = positive_flow.rolling(window=period).sum()
        negative_mf = negative_flow.rolling(window=period).sum()

        mfi = 100 - (100 / (1 + positive_mf / (negative_mf + 1e-10)))
        return mfi

    @staticmethod
    def _price_col(name: str, df: pd.DataFrame) -> str:
        """获取价格列名"""
        # 尝试常见命名
        for col in [name, name.capitalize(), name.upper()]:
            if col in df.columns:
                return col
        return name


class FeatureSelector:
    """特征选择器

    提供:
    - VIF过滤（多重共线性）
    - 单变量特征选择
    - 递归特征消除（RFE）
    - 嵌入式特征选择
    """

    def __init__(self, threshold_vif=10.0, threshold_univariate=0.75,
                 n_features_rfe=0.67, n_features_embedded=0.8):
        """
        Args:
            threshold_vif: VIF阈值
            threshold_univariate: 单变量选择保留比例
            n_features_rfe: RFE保留特征数或比例
            n_features_embedded: 嵌入式选择保留特征数或比例
        """
        self.threshold_vif = threshold_vif
        self.threshold_univariate = threshold_univariate
        self.n_features_rfe = n_features_rfe
        self.n_features_embedded = n_features_embedded

        self.selected_features_ = None

    def fit_transform(self, X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
        """拟合并转换特征"""
        X_selected = X.copy()

        # 1. VIF过滤
        X_selected = self._remove_high_vif(X_selected)

        # 2. 单变量特征选择
        X_selected = self._univariate_selection(X_selected, y)

        # 3. RFE特征选择
        X_selected = self._rfe_selection(X_selected, y)

        # 4. 嵌入式特征选择
        X_selected = self._embedded_selection(X_selected, y)

        self.selected_features_ = X_selected.columns.tolist()
        return X_selected

    def _remove_high_vif(self, X: pd.DataFrame) -> pd.DataFrame:
        """移除高VIF特征"""
        from sklearn.linear_model import LinearRegression

        features = X.columns.tolist()
        while True:
            # 计算VIF
            vif_scores = {}
            for feature in features:
                # 跳过常数特征
                if X[feature].std() < 1e-10:
                    vif_scores[feature] = float('inf')
                    continue

                # 线性回归计算R²
                other_features = [f for f in features if f != feature]
                reg = LinearRegression()
                reg.fit(X[other_features], X[feature])
                r2 = reg.score(X[other_features], X[feature])
                vif = 1 / (1 - r2) if r2 < 1 else float('inf')
                vif_scores[feature] = vif

            # 检查最大VIF
            max_vif_feature = max(vif_scores, key=vif_scores.get)
            if vif_scores[max_vif_feature] > self.threshold_vif:
                features.remove(max_vif_feature)
                logger.info(f"移除高VIF特征: {max_vif_feature} (VIF={vif_scores[max_vif_feature]:.2f})")
            else:
                break

        return X[features]

    def _univariate_selection(self, X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
        """单变量特征选择"""
        from sklearn.feature_selection import SelectKBest, f_classif, mutual_info_classif

        n_features = int(len(X.columns) * self.threshold_univariate)
        if n_features >= len(X.columns):
            return X

        selector = SelectKBest(f_classif, k=n_features)
        selector.fit(X, y)

        selected = X.columns[selector.get_support()]
        logger.info(f"单变量选择保留特征: {len(selected)}/{len(X.columns)}")

        return X[selected]

    def _rfe_selection(self, X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
        """递归特征消除"""
        from sklearn.feature_selection import RFE
        from sklearn.ensemble import GradientBoostingClassifier

        n_features = int(len(X.columns) * self.n_features_rfe) if isinstance(self.n_features_rfe, float) else self.n_features_rfe

        estimator = GradientBoostingClassifier(
            n_estimators=50,
            max_depth=3,
            random_state=42
        )

        selector = RFE(estimator, n_features_to_select=n_features, step=0.25)
        selector.fit(X, y)

        selected = X.columns[selector.get_support()]
        logger.info(f"RFE保留特征: {len(selected)}/{len(X.columns)}")

        return X[selected]

    def _embedded_selection(self, X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
        """嵌入式特征选择"""
        from sklearn.ensemble import GradientBoostingClassifier

        model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=3,
            random_state=42
        )
        model.fit(X, y)

        # 选择重要的特征
        importances = pd.Series(model.feature_importances_, index=X.columns)
        n_features = int(len(X.columns) * self.n_features_embedded) if isinstance(self.n_features_embedded, float) else self.n_features_embedded

        selected = importances.nlargest(n_features).index.tolist()
        logger.info(f"嵌入式选择保留特征: {len(selected)}/{len(X.columns)}")

        return X[selected]
```

### 3.3 时间序列数据分割

**设计思路**: 专门针对时间序列数据的分割方法，避免未来信息泄露。

```python
# backtrader/ML/data_split.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import numpy as np
from typing import Tuple, Optional
from sklearn.model_selection import TimeSeriesSplit

logger = logging.getLogger(__name__)


def time_series_split(X, y, test_size: float = 0.2,
                      gap: int = 0) -> Tuple:
    """时间序列分割

    按时间顺序分割数据，确保训练集在测试集之前

    Args:
        X: 特征数据
        y: 目标变量
        test_size: 测试集比例
        gap: 训练集和测试集之间的间隔天数

    Returns:
        (X_train, X_test, y_train, y_test)
    """
    # 确保按时间排序
    if hasattr(X, 'index'):
        X_sorted = X.sort_index()
        y_sorted = y.loc[X_sorted.index]
    else:
        sort_idx = np.argsort(X.iloc[:, 0])  # 假设第一列是时间
        X_sorted = X.iloc[sort_idx]
        y_sorted = y.iloc[sort_idx]

    # 计算分割点
    n_samples = len(X_sorted)
    split_idx = int(n_samples * (1 - test_size))

    # 应用gap
    split_idx = split_idx - gap

    X_train = X_sorted.iloc[:split_idx]
    X_test = X_sorted.iloc[split_idx:]
    y_train = y_sorted.iloc[:split_idx]
    y_test = y_sorted.iloc[split_idx:]

    logger.info(f"时间序列分割: 训练集={len(X_train)}, 测试集={len(X_test)}, gap={gap}")

    return X_train, X_test, y_train, y_test


def time_series_cv_split(X, y, n_splits: int = 5,
                         test_size: Optional[float] = None) -> list:
    """时间序列交叉验证分割

    Args:
        X: 特征数据
        y: 目标变量
        n_splits: 分割数
        test_size: 测试集大小（每个fold）

    Returns:
        [(train_idx, test_idx), ...] 索引列表
    """
    tscv = TimeSeriesSplit(n_splits=n_splits, test_size=test_size)

    if hasattr(X, 'index'):
        # 使用索引位置
        splits = []
        for train_idx, test_idx in tscv.split(X):
            # 将位置索引转换为实际索引
            train_indices = X.index[train_idx]
            test_indices = X.index[test_idx]
            splits.append((train_indices, test_indices))
        return splits
    else:
        return list(tscv.split(X, y))


def rolling_window_split(X, y, train_size: int, test_size: int = 1,
                        step: int = 1) -> list:
    """滚动窗口分割

    用于滚动预测评估

    Args:
        X: 特征数据
        y: 目标变量
        train_size: 训练窗口大小
        test_size: 测试窗口大小
        step: 滚动步长

    Returns:
        [(train_start, train_end, test_start, test_end), ...] 切片列表
    """
    n_samples = len(X)
    splits = []

    for start in range(0, n_samples - train_size - test_size + 1, step):
        train_end = start + train_size
        test_end = train_end + test_size

        if test_end > n_samples:
            break

        splits.append((start, train_end, train_end, test_end))

    logger.info(f"滚动窗口分割: {len(splits)} windows, train_size={train_size}, test_size={test_size}")

    return splits


class PurgedKFold:
    """带gap的K-Fold交叉验证

    用于金融时间序列，避免数据泄露
    """

    def __init__(self, n_splits: int = 5, purge: int = 10, gap: int = 0):
        """
        Args:
            n_splits: 分割数
            purge: 每次分割前清除的数据量
            gap: 训练集和验证集之间的间隔
        """
        self.n_splits = n_splits
        self.purge = purge
        self.gap = gap

    def split(self, X, y=None, groups=None):
        """生成分割索引"""
        n_samples = len(X)
        k_fold_size = n_samples // self.n_splits

        indices = np.arange(n_samples)

        for k in range(self.n_splits):
            test_start = k * k_fold_size
            test_end = (k + 1) * k_fold_size if k < self.n_splits - 1 else n_samples

            # 训练集在测试集之前，且有gap
            train_end = test_start - self.gap
            train_start = max(0, train_end - k_fold_size * (self.n_splits - 1))

            # 应用purge
            train_start = max(train_start, 0) + self.purge
            if train_start >= train_end:
                continue

            train_indices = indices[train_start:train_end]
            test_indices = indices[test_start:test_end]

            yield train_indices, test_indices
```

### 3.4 模型训练器

**设计思路**: 统一的模型训练、评估和持久化接口。

```python
# backtrader/ML/model_trainer.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import pickle
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, List, Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelTrainer:
    """模型训练器

    支持:
    - 多种梯度提升模型
    - 超参数调优
    - 早停机制
    - 特征重要性分析
    - 模型持久化
    """

    # 支持的模型
    MODELS = {
        'xgboost': {
            'class': 'xgboost.XGBClassifier',
            'default_params': {
                'n_estimators': 100,
                'max_depth': 3,
                'learning_rate': 0.1,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'random_state': 42,
                'use_label_encoder': False,
                'eval_metric': 'logloss',
            }
        },
        'lightgbm': {
            'class': 'lightgbm.LGBMClassifier',
            'default_params': {
                'n_estimators': 100,
                'max_depth': 3,
                'learning_rate': 0.1,
                'subsample': 0.8,
                'colsample_bytree': 0.8,
                'random_state': 42,
                'verbose': -1,
            }
        },
        'catboost': {
            'class': 'catboost.CatBoostClassifier',
            'default_params': {
                'iterations': 100,
                'depth': 3,
                'learning_rate': 0.1,
                'random_state': 42,
                'verbose': False,
            }
        },
        'sklearn_gb': {
            'class': 'sklearn.ensemble.GradientBoostingClassifier',
            'default_params': {
                'n_estimators': 100,
                'max_depth': 3,
                'learning_rate': 0.1,
                'subsample': 0.8,
                'random_state': 42,
            }
        },
    }

    def __init__(self, model_type: str = 'xgboost',
                 model_params: Optional[Dict] = None,
                 early_stopping_rounds: int = 10):
        """
        Args:
            model_type: 模型类型
            model_params: 模型参数
            early_stopping_rounds: 早停轮数
        """
        self.model_type = model_type
        self.early_stopping_rounds = early_stopping_rounds

        # 合并默认参数和自定义参数
        default_params = self.MODELS[model_type]['default_params'].copy()
        if model_params:
            default_params.update(model_params)

        self.model_params = default_params
        self.model = None
        self.scaler = None

    def train(self, X_train, y_train, X_val=None, y_val=None):
        """训练模型

        Args:
            X_train: 训练特征
            y_train: 训练标签
            X_val: 验证特征（用于早停）
            y_val: 验证标签
        """
        from sklearn.preprocessing import StandardScaler

        # 数据标准化
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_val_scaled = self.scaler.transform(X_val) if X_val is not None else None

        # 创建模型
        self.model = self._create_model()

        # 训练
        if X_val is not None and self.early_stopping_rounds > 0:
            # 使用验证集进行早停
            self.model.fit(
                X_train_scaled, y_train,
                eval_set=[(X_val_scaled, y_val)],
                early_stopping_rounds=self.early_stopping_rounds,
                verbose=False
            )
        else:
            self.model.fit(X_train_scaled, y_train)

        logger.info(f"模型训练完成: {self.model_type}")

    def predict(self, X):
        """预测类别"""
        X_scaled = self.scaler.transform(X)
        return self.model.predict(X_scaled)

    def predict_proba(self, X):
        """预测概率"""
        X_scaled = self.scaler.transform(X)
        return self.model.predict_proba(X_scaled)

    def evaluate(self, X, y, metrics: List[str] = None) -> Dict[str, float]:
        """评估模型

        Args:
            X: 测试特征
            y: 测试标签
            metrics: 评估指标列表

        Returns:
            指标字典
        """
        from sklearn.metrics import (
            accuracy_score, precision_score, recall_score,
            f1_score, roc_auc_score, confusion_matrix
        )

        y_pred = self.predict(X)
        y_proba = self.predict_proba(X)

        results = {}

        if metrics is None:
            metrics = ['accuracy', 'precision', 'recall', 'f1', 'roc_auc']

        for metric in metrics:
            if metric == 'accuracy':
                results[metric] = accuracy_score(y, y_pred)
            elif metric == 'precision':
                results[metric] = precision_score(y, y_pred, zero_division=0)
            elif metric == 'recall':
                results[metric] = recall_score(y, y_pred, zero_division=0)
            elif metric == 'f1':
                results[metric] = f1_score(y, y_pred, zero_division=0)
            elif metric == 'roc_auc':
                if y_proba.shape[1] > 1:
                    results[metric] = roc_auc_score(y, y_proba[:, 1])
                else:
                    results[metric] = roc_auc_score(y, y_proba)

        return results

    def feature_importance(self, feature_names: List[str] = None,
                          top_n: int = 20) -> pd.DataFrame:
        """获取特征重要性

        Args:
            feature_names: 特征名称列表
            top_n: 显示前N个特征

        Returns:
            特征重要性DataFrame
        """
        if not hasattr(self.model, 'feature_importances_'):
            logger.warning("模型不支持特征重要性分析")
            return pd.DataFrame()

        importances = self.model.feature_importances_

        if feature_names is None:
            feature_names = [f'feature_{i}' for i in range(len(importances))]

        importance_df = pd.DataFrame({
            'feature': feature_names,
            'importance': importances
        }).sort_values('importance', ascending=False)

        return importance_df.head(top_n)

    def save(self, filepath: str):
        """保存模型"""
        model_data = {
            'model': self.model,
            'scaler': self.scaler,
            'model_type': self.model_type,
            'model_params': self.model_params,
        }

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"模型已保存: {filepath}")

    @classmethod
    def load(cls, filepath: str):
        """加载模型"""
        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        trainer = cls(
            model_type=model_data['model_type'],
            model_params=model_data['model_params']
        )
        trainer.model = model_data['model']
        trainer.scaler = model_data['scaler']

        logger.info(f"模型已加载: {filepath}")
        return trainer

    def _create_model(self):
        """创建模型实例"""
        model_config = self.MODELS[self.model_type]
        class_path = model_config['class'].split('.')

        # 动态导入类
        module = __import__(class_path[0])
        for attr in class_path[1:-1]:
            module = getattr(module, attr)
        model_class = getattr(module, class_path[-1])

        return model_class(**self.model_params)


class HyperparameterTuner:
    """超参数调优器

    支持网格搜索和随机搜索
    """

    def __init__(self, model_type: str = 'xgboost',
                 search_type: str = 'grid',
                 cv_splits: int = 3,
                 n_iter: int = 10):
        """
        Args:
            model_type: 模型类型
            search_type: 搜索类型 (grid/random)
            cv_splits: 交叉验证分割数
            n_iter: 随机搜索迭代次数
        """
        self.model_type = model_type
        self.search_type = search_type
        self.cv_splits = cv_splits
        self.n_iter = n_iter

    def tune(self, X_train, y_train, param_grid: Dict[str, List],
             scoring: str = 'roc_auc') -> Dict:
        """执行超参数调优

        Args:
            X_train: 训练特征
            y_train: 训练标签
            param_grid: 参数网格
            scoring: 评分指标

        Returns:
            最佳参数和最佳得分
        """
        from sklearn.model_selection import GridSearchCV, RandomizedSearchCV
        from sklearn.model_selection import TimeSeriesSplit

        # 创建基础模型
        trainer = ModelTrainer(model_type=self.model_type)
        base_model = trainer._create_model()

        # 时间序列交叉验证
        tscv = TimeSeriesSplit(n_splits=self.cv_splits)

        # 选择搜索方法
        if self.search_type == 'grid':
            search = GridSearchCV(
                estimator=base_model,
                param_grid=param_grid,
                cv=tscv,
                scoring=scoring,
                n_jobs=-1,
                verbose=1
            )
        else:
            search = RandomizedSearchCV(
                estimator=base_model,
                param_distributions=param_grid,
                n_iter=self.n_iter,
                cv=tscv,
                scoring=scoring,
                n_jobs=-1,
                verbose=1,
                random_state=42
            )

        # 执行搜索
        search.fit(X_train, y_train)

        logger.info(f"最佳参数: {search.best_params_}")
        logger.info(f"最佳得分: {search.best_score_:.4f}")

        return {
            'best_params': search.best_params_,
            'best_score': search.best_score_,
            'best_model': search.best_estimator_
        }
```

### 3.5 信号生成器

**设计思路**: 将ML预测转换为可配置的交易信号。

```python
# backtrader/ML/signals.py

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)
import logging
import numpy as np
import pandas as pd
from typing import Union, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """信号类型"""
    BINARY = 'binary'         # 二分类 (0/1)
    TERNARY = 'ternary'       # 三分类 (-1/0/1)
    PROBABILITY = 'probability'  # 概率值 (0-1)
    REGRESSION = 'regression'    # 回归值 (连续)


class SignalGenerator:
    """信号生成器

    将ML预测转换为交易信号
    """

    def __init__(self,
                 signal_type: SignalType = SignalType.BINARY,
                 buy_threshold: float = 0.5,
                 sell_threshold: float = 0.5,
                 confidence_threshold: float = 0.0,
                 neutral_range: float = 0.0):
        """
        Args:
            signal_type: 信号类型
            buy_threshold: 买入阈值
            sell_threshold: 卖出阈值
            confidence_threshold: 置信度阈值
            neutral_range: 中性区间（用于三分类）
        """
        self.signal_type = signal_type
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.confidence_threshold = confidence_threshold
        self.neutral_range = neutral_range

    def generate_signals(self, predictions: np.ndarray,
                        probabilities: Optional[np.ndarray] = None) -> np.ndarray:
        """生成交易信号

        Args:
            predictions: 模型预测
            probabilities: 预测概率

        Returns:
            交易信号数组 (-1: 卖出, 0: 持有, 1: 买入)
        """
        if self.signal_type == SignalType.BINARY:
            return self._binary_signals(predictions, probabilities)
        elif self.signal_type == SignalType.TERNARY:
            return self._ternary_signals(predictions, probabilities)
        elif self.signal_type == SignalType.PROBABILITY:
            return self._probability_signals(predictions, probabilities)
        elif self.signal_type == SignalType.REGRESSION:
            return self._regression_signals(predictions, probabilities)
        else:
            raise ValueError(f"未知信号类型: {self.signal_type}")

    def _binary_signals(self, predictions: np.ndarray,
                       probabilities: Optional[np.ndarray] = None) -> np.ndarray:
        """二分类信号"""
        signals = np.zeros(len(predictions))

        if probabilities is not None and self.confidence_threshold > 0:
            # 使用置信度过滤
            confidence = np.max(probabilities, axis=1) if probabilities.ndim > 1 else probabilities
            mask = confidence >= self.confidence_threshold

            # 只在高置信度时生成信号
            signals[mask & (predictions[mask] == 1)] = 1  # 买入
        else:
            signals[predictions == 1] = 1  # 买入
            signals[predictions == 0] = -1  # 卖出

        return signals

    def _ternary_signals(self, predictions: np.ndarray,
                        probabilities: Optional[np.ndarray] = None) -> np.ndarray:
        """三分类信号

        预测值: -1=卖出, 0=持有, 1=买入
        """
        signals = predictions.copy()

        if self.neutral_range > 0:
            # 将接近0的预测值设为持有
            signals[np.abs(signals) < self.neutral_range] = 0

        return signals

    def _probability_signals(self, predictions: np.ndarray,
                           probabilities: Optional[np.ndarray] = None) -> np.ndarray:
        """概率信号

        predictions 直接作为买入概率
        """
        signals = np.zeros(len(predictions))

        # 买入
        signals[predictions >= self.buy_threshold] = 1

        # 卖出
        signals[predictions <= self.sell_threshold] = -1

        # 持有
        signals[(predictions > self.sell_threshold) & (predictions < self.buy_threshold)] = 0

        return signals

    def _regression_signals(self, predictions: np.ndarray,
                           probabilities: Optional[np.ndarray] = None) -> np.ndarray:
        """回归信号

        预测值为目标价格或收益率
        """
        signals = np.zeros(len(predictions))

        # 计算预测值的百分位数
        q25 = np.percentile(predictions, 25)
        q75 = np.percentile(predictions, 75)

        # 高于75分位数买入
        signals[predictions >= q75] = 1

        # 低于25分位数卖出
        signals[predictions <= q25] = -1

        return signals


class TargetBuilder:
    """目标变量构建器

    用于创建ML预测的目标变量
    """

    def __init__(self):
        self.target_type = None

    def create_binary_target(self, data: pd.DataFrame,
                            price_col: str = 'close',
                            threshold: float = 0.0,
                            periods: int = 1) -> pd.Series:
        """创建二分类目标

        预测未来N期是否上涨

        Args:
            data: 价格数据
            price_col: 价格列名
            threshold: 涨跌阈值
            periods: 预测周期

        Returns:
            目标序列 (1=上涨, 0=下跌/持平)
        """
        future_return = data[price_col].pct_change(periods).shift(-periods)

        target = (future_return > threshold).astype(int)
        return target

    def create_ternary_target(self, data: pd.DataFrame,
                             price_col: str = 'close',
                             threshold: float = 0.01,
                             periods: int = 1) -> pd.Series:
        """创建三分类目标

        -1: 下跌
         0: 震荡
         1: 上涨

        Args:
            data: 价格数据
            price_col: 价格列名
            threshold: 分类阈值
            periods: 预测周期

        Returns:
            目标序列 (-1/0/1)
        """
        future_return = data[price_col].pct_change(periods).shift(-periods)

        target = np.where(
            future_return > threshold, 1,
            np.where(future_return < -threshold, -1, 0)
        )

        return pd.Series(target, index=data.index)

    def create_regression_target(self, data: pd.DataFrame,
                                price_col: str = 'close',
                                periods: int = 1) -> pd.Series:
        """创建回归目标

        预测未来收益率

        Args:
            data: 价格数据
            price_col: 价格列名
            periods: 预测周期

        Returns:
            目标序列 (连续值)
        """
        target = data[price_col].pct_change(periods).shift(-periods)
        return target
```

### 3.6 使用示例

**设计思路**: 完整的ML策略开发和使用流程示例。

```python
# 使用ML策略的完整示例

import backtrader as bt
from backtrader.ML import (
    FeatureEngineer, FeatureSelector, ModelTrainer,
    SignalGenerator, TargetBuilder, MLSignalStrategy,
    time_series_split
)
import pandas as pd

# === 1. 准备数据 ===
df = pd.read_csv('stock_data.csv', index_col='date', parse_dates=['date'])

# === 2. 特征工程 ===
feature_engineer = FeatureEngineer()
df_features = feature_engineer.fit_transform(df)

# === 3. 创建目标变量 ===
target_builder = TargetBuilder()
target = target_builder.create_binary_target(
    df_features,
    price_col='close',
    threshold=0.02,  # 2%涨幅为正类
    periods=5       # 预测5天后
)

# 移除包含NaN的行
df_clean = df_features.dropna()
target_clean = target.loc[df_clean.index]

# === 4. 数据分割 ===
X = df_clean.drop(columns=['close'])  # 移除目标列
y = target_clean

X_train, X_test, y_train, y_test = time_series_split(
    X, y, test_size=0.2, gap=5
)

# === 5. 特征选择 ===
selector = FeatureSelector(
    threshold_vif=10.0,
    threshold_univariate=0.75,
    n_features_rfe=0.67
)

X_train_selected = selector.fit_transform(X_train, y_train)
X_test_selected = X_test[X_train_selected.columns]

# === 6. 模型训练 ===
trainer = ModelTrainer(
    model_type='xgboost',
    model_params={
        'n_estimators': 100,
        'max_depth': 3,
        'learning_rate': 0.1
    },
    early_stopping_rounds=10
)

trainer.train(X_train_selected, y_train,
            X_val=X_test_selected, y_val=y_test)

# === 7. 评估模型 ===
metrics = trainer.evaluate(X_test_selected, y_test)
print("模型评估指标:")
for metric, value in metrics.items():
    print(f"  {metric}: {value:.4f}")

# 特征重要性
importance = trainer.feature_importance(
    X_train_selected.columns.tolist(),
    top_n=15
)
print("\n特征重要性 Top 15:")
print(importance)

# === 8. 生成预测 ===
predictions = trainer.predict(X_test_selected)
probabilities = trainer.predict_proba(X_test_selected)

# === 9. 转换为交易信号 ===
signal_gen = SignalGenerator(
    signal_type=SignalType.BINARY,
    buy_threshold=0.6,
    confidence_threshold=0.55
)

signals = signal_gen.generate_signals(predictions, probabilities)

# === 10. 回测 ===
cerebro = bt.Cerebro()

# 加载原始数据
data = bt.feeds.PandasData(dataname=df)

# 添加ML策略
# 注意: predictions需要与数据对齐
cerebro.addstrategy(
    MLSignalStrategy,
    predictions=signals,  # 或使用predictions和probabilities
    probabilities=probabilities,
    threshold=0.6,
    position_size=0.95,
    min_hold_bars=5,
    stop_loss_pct=0.05,
    take_profit_pct=0.10
)

# 设置初始资金和佣金
cerebro.broker.setcash(10000)
cerebro.broker.setcommission(commission=0.001)

# 添加分析器
cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')

# 运行回测
results = cerebro.run()

# === 11. 分析结果 ===
strat = results[0]
sharpe = strat.analyzers.sharpe.get_analysis()
drawdown = strat.analyzers.drawdown.get_analysis()
trades = strat.analyzers.trades.get_analysis()

print(f"\n夏普比率: {sharpe.get('sharperatio', 'N/A')}")
print(f"最大回撤: {drawdown.get('max', {}).get('drawdown', 'N/A'):.2f}%")
print(f"交易次数: {trades.get('total', {}).get('total', 'N/A')}")
print(f"胜率: {trades.get('won', {}).get('total', 0) / trades.get('total', {}).get('total', 1) * 100:.1f}%")

# 保存模型
trainer.save('models/xgboost_strategy.pkl')
```

---

## 四、目录结构

```
backtrader/
├── ML/                          # 机器学习模块
│   ├── __init__.py             # 模块导出
│   │
│   ├── strategies/             # ML策略
│   │   ├── __init__.py
│   │   ├── ml_strategy.py      # ML信号策略基类
│   │   └── ensemble_strategy.py # 集成策略
│   │
│   ├── features/               # 特征工程
│   │   ├── __init__.py
│   │   ├── engineer.py         # 特征工程器
│   │   ├── selector.py         # 特征选择器
│   │   └── technical.py        # 技术指标库
│   │
│   ├── models/                 # 模型相关
│   │   ├── __init__.py
│   │   ├── trainer.py          # 模型训练器
│   │   ├── tuner.py            # 超参数调优
│   │   └── ensemble.py         # 集成学习
│   │
│   ├── data/                   # 数据处理
│   │   ├── __init__.py
│   │   ├── split.py            # 数据分割
│   │   ├── target.py           # 目标构建
│   │   └── loader.py           # 数据加载
│   │
│   ├── signals/                # 信号生成
│   │   ├── __init__.py
│   │   ├── generator.py        # 信号生成器
│   │   └── filters.py          # 信号过滤器
│   │
│   └── evaluation/             # 评估工具
│       ├── __init__.py
│       ├── metrics.py          # 评估指标
│       └── backtest.py         # 回测评估
│
└── __init__.py
```

---

## 五、实施计划

### 第一阶段（高优先级）

1. **ML策略基类**
   - 实现`MLSignalStrategy`
   - 支持二分类信号
   - 基本仓位管理

2. **特征工程器**
   - 实现基础技术指标
   - 趋势、动量、波动性特征

3. **数据分割**
   - 时间序列分割
   - 避免数据泄露

### 第二阶段（中优先级）

4. **模型训练器**
   - 支持XGBoost/LightGBM
   - 模型保存和加载

5. **特征选择器**
   - VIF过滤
   - 单变量选择

6. **信号生成器**
   - 多种信号类型
   - 置信度过滤

### 第三阶段（可选）

7. **超参数调优**
   - 网格搜索
   - 贝叶斯优化

8. **高级功能**
   - 集成学习
   - 在线学习
   - 特征重要性可视化

---

## 六、向后兼容性

所有ML功能均为**完全可选的独立模块**：

1. ML模块通过`from backtrader.ML import ...`使用
2. 不影响现有策略的运行
3. 用户可以选择使用传统策略或ML策略
4. ML策略可以与传统指标结合使用

---

## 七、与现有功能对比

| 功能 | backtrader (原生) | ML扩展 |
|------|------------------|--------|
| 策略类型 | 规则型 | ML预测型 |
| 特征工程 | 手动计算 | 系统化管道 |
| 模型支持 | 无 | XGBoost/LightGBM等 |
| 信号生成 | 基于规则 | 基于ML预测 |
| 数据验证 | 无 | 时间序列CV |
| 模型评估 | 无 | ML指标+回测指标 |
| 特征重要性 | 无 | 支持 |
