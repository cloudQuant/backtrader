### 背景
backtrader已经比较完善了，我想要借鉴量化投资框架中其他项目的优势，继续改进优化backtrader。
### 任务
1. 阅读研究分析backtrader这个项目的源代码，了解这个项目。
2. 阅读研究分析/Users/yunjinqi/Documents/量化交易框架/AI-Strategies-StockMarket
3. 借鉴这个新项目的优点和功能，给backtrader优化改进提供新的建议
4. 写需规文档和设计文档放到这个文档的最下面，方便后续借鉴

### AI-Strategies-StockMarket项目简介
AI-Strategies-StockMarket是一个结合AI和机器学习的股票交易策略项目，具有以下核心特点：
- **机器学习**: 使用机器学习预测
- **深度学习**: 神经网络模型集成
- **特征工程**: 金融特征工程
- **模型训练**: 模型训练和评估
- **策略集成**: AI模型与交易策略集成
- **回测验证**: 策略回测验证

### 重点借鉴方向
1. **ML集成**: 机器学习模型集成
2. **特征工程**: 金融特征提取
3. **模型训练**: 模型训练流程
4. **预测系统**: 预测系统设计
5. **策略融合**: AI与传统策略融合
6. **模型评估**: 模型性能评估

---

## 研究分析

### AI-Strategies-StockMarket架构特点总结

经过深入研究，AI-Strategies-StockMarket项目是一个结合传统技术分析和机器学习的量化交易框架。

#### 1. 核心AI策略

**神经网络策略**:
- 6层MLP架构 (36-128-64-16-8-1)
- ReLU隐藏层激活，tanh输出激活
- L2正则化 (λ=0.001)
- SGD + Nesterov动量优化
- 在线学习：每10天用最新15个样本重新训练

**PSO组合信号策略**:
- 54个移动平均交叉信号组合
- 粒子群优化动态权重分配
- 每90天重新优化（使用最近100天数据）
- 支持指数归一化和L1归一化

#### 2. 特征工程

**50+技术指标**:
- 价格数据：OHLCV
- 动量指标：5/10/15日动量
- 均线指标：7/14/21日SMA和EMA
- 波动率：7/14/21日标准差
- 振荡器：RSI (9/14/21), Stochastic (7/14/21)
- 趋势指标：MACD (12,26)
- 变化率：ROC (13,21)

**智能标签生成**:
- 基于未来价格模拟
- 考虑交易成本
- 可配置止盈/止损阈值

#### 3. 在线学习架构

```
┌─────────────────────────────────────────────────┐
│              在线学习循环                        │
├─────────────────────────────────────────────────┤
│  预测 → 执行 → 收集新数据 → 更新记忆 → 重新训练  │
│                                              │
│  FIFO Replay Memory (最后15个样本)             │
└─────────────────────────────────────────────────┘
```

#### 4. 集成模式

- 模型作为策略类属性传递
- 策略直接调用model.predict()
- 周期性重新训练
- 阈值过滤低置信度预测

### Backtrader当前ML能力分析

#### 优势
- **灵活的架构**: 可通过自定义指标集成ML模型
- **SignalStrategy**: 支持外部信号输入
- **统计指标**: OLS回归、Hurst指数等
- **Analyzer框架**: 可扩展自定义分析器

#### 局限性（针对ML）
1. **无内置ML库**: 不包含TensorFlow、PyTorch、scikit-learn
2. **无特征工程工具**: 缺少金融特征提取模块
3. **无模型管理**: 无模型训练、保存、加载机制
4. **无在线学习支持**: 策略中无增量学习机制
5. **无ML专用分析器**: 缺少模型评估指标

---

## 需求规格文档

### 1. ML模型集成框架

#### 1.1 功能描述
提供统一的机器学习模型集成接口，支持多种ML框架。

#### 1.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| ML-001 | 定义ML模型抽象接口 | P0 |
| ML-002 | 支持scikit-learn模型集成 | P0 |
| ML-003 | 支持TensorFlow/Keras模型集成 | P0 |
| ML-004 | 支持PyTorch模型集成 | P1 |
| ML-005 | 支持XGBoost/LightGBM模型集成 | P1 |
| ML-006 | 支持模型序列化和加载 | P1 |

#### 1.3 接口设计
```python
class MLModel(ABC):
    """机器学习模型抽象接口"""

    @abstractmethod
    def fit(self, X, y): pass

    @abstractmethod
    def predict(self, X): pass

    @abstractmethod
    def predict_proba(self, X): pass

    @abstractmethod
    def save(self, path): pass

    @abstractmethod
    def load(self, path): pass


class MLIndicator(bt.Indicator):
    """ML预测指标"""

    lines = ('prediction', 'probability',)

    params = (
        ('model', None),
        ('features', None),
        ('retrain_interval', 0),  # 0表示不重新训练
    )
```

### 2. 金融特征工程

#### 2.1 功能描述
提供丰富的金融技术指标和特征提取工具。

#### 2.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| FE-001 | 基础价格特征提取 | P0 |
| FE-002 | 动量指标特征 | P0 |
| FE-003 | 均线指标特征 | P0 |
| FE-004 | 波动率指标特征 | P0 |
| FE-005 | 振荡器指标特征 | P1 |
| FE-006 | 趋势指标特征 | P1 |
| FE-007 | 特征标准化工具 | P1 |
| FE-008 | 特征选择工具 | P2 |

#### 2.3 接口设计
```python
class FeatureEngineer:
    """金融特征工程器"""

    def __init__(self):
        self.features = {}

    def add_price_features(self, df):
        """添加基础价格特征"""

    def add_momentum_features(self, df, periods=[5, 10, 15]):
        """添加动量特征"""

    def add_ma_features(self, df, periods=[7, 14, 21]):
        """添加均线特征"""

    def add_volatility_features(self, df, periods=[7, 14, 21]):
        """添加波动率特征"""

    def add_oscillator_features(self, df):
        """添加振荡器特征 (RSI, Stochastic)"""

    def add_trend_features(self, df):
        """添加趋势特征 (MACD)"""

    def get_feature_matrix(self, df):
        """获取特征矩阵"""
```

### 3. 模型训练流程

#### 3.1 功能描述
提供完整的模型训练、验证和评估流程。

#### 3.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| TRAIN-001 | 定义训练数据集类 | P0 |
| TRAIN-002 | 实现时间序列交叉验证 | P0 |
| TRAIN-003 | 实现标签生成器 | P0 |
| TRAIN-004 | 实现训练Pipeline | P1 |
| TRAIN-005 | 支持超参数优化 | P1 |
| TRAIN-006 | 支持早停机制 | P2 |

#### 3.3 接口设计
```python
class LabelGenerator:
    """交易标签生成器"""

    def __init__(self, gain_threshold=0.02,
                 loss_threshold=-0.02,
                 holding_period=5,
                 commission=0.001):
        self.gain_threshold = gain_threshold
        self.loss_threshold = loss_threshold
        self.holding_period = holding_period
        self.commission = commission

    def generate_labels(self, df):
        """
        生成交易标签

        Returns:
            labels: 1 (买入), 0 (卖出)
        """
        pass


class TimeSeriesCV:
    """时间序列交叉验证"""

    def split(self, X, y, n_splits=5):
        """生成时间序列分割"""
        pass


class TrainingPipeline:
    """模型训练Pipeline"""

    def __init__(self, model, feature_engineer, label_generator):
        self.model = model
        self.feature_engineer = feature_engineer
        self.label_generator = label_generator

    def train(self, df, start_date, end_date):
        """训练模型"""
        pass

    def evaluate(self, X_test, y_test):
        """评估模型"""
        pass
```

### 4. 在线学习系统

#### 4.1 功能描述
支持策略运行时的增量学习和模型更新。

#### 4.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| OL-001 | 实现Replay Memory | P0 |
| OL-002 | 支持增量训练 | P0 |
| OL-003 | 实现周期性重训练 | P1 |
| OL-004 | 支持模型版本管理 | P2 |

#### 4.3 接口设计
```python
class ReplayMemory:
    """经验回放缓冲区"""

    def __init__(self, max_size=100):
        self.max_size = max_size
        self.memory = []

    def add(self, experience):
        """添加经验"""

    def sample(self, batch_size):
        """采样经验"""

    def get_all(self):
        """获取所有经验"""


class OnlineLearningStrategy(bt.Strategy):
    """在线学习策略"""

    params = (
        ('model', None),
        ('retrain_interval', 10),  # 每N天重新训练
        ('memory_size', 15),
    )

    def __init__(self):
        self.memory = ReplayMemory(self.p.memory_size)

    def retrain(self):
        """重新训练模型"""
        pass
```

### 5. 模型评估指标

#### 5.1 功能描述
提供专门的ML模型性能评估分析器。

#### 5.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| EVAL-001 | 预测准确率分析 | P0 |
| EVAL-002 | 混淆矩阵分析 | P0 |
| EVAL-003 | ROC/AUC分析 | P1 |
| EVAL-004 | 特征重要性分析 | P1 |
| EVAL-005 | 预测置信度分布 | P2 |

#### 5.3 接口设计
```python
class MLAnalyzer(bt.Analyzer):
    """ML模型性能分析器"""

    def __init__(self):
        self.predictions = []
        self.actuals = []
        self.confidences = []

    def notify_order(self, order):
        """记录预测结果"""

    def get_accuracy(self):
        """计算准确率"""

    def get_confusion_matrix(self):
        """获取混淆矩阵"""

    def get_roc_auc(self):
        """计算ROC/AUC"""
```

### 6. 策略融合

#### 6.1 功能描述
支持AI信号与传统技术指标的融合。

#### 6.2 需求规格

| 需求ID | 需求描述 | 优先级 |
|--------|----------|--------|
| FUSION-001 | 实现信号加权融合 | P0 |
| FUSION-002 | 支持动态权重调整 | P1 |
| FUSION-003 | 实现置信度过滤 | P1 |
| FUSION-004 | 支持多模型集成 | P2 |

#### 6.3 接口设计
```python
class SignalFusionStrategy(bt.Strategy):
    """信号融合策略"""

    params = (
        ('ml_model', None),
        ('ml_weight', 0.5),
        ('ta_weight', 0.5),
        ('confidence_threshold', 0.6),
    )

    def get_combined_signal(self):
        """获取融合信号"""
        ml_signal = self.p.ml_model.predict_proba(self.features)
        ta_signal = self.ta_indicator[0]

        # 置信度过滤
        if ml_signal < self.p.confidence_threshold:
            return 0

        # 加权融合
        return (ml_signal * self.p.ml_weight +
                ta_signal * self.p.ta_weight)
```

---

## 设计文档

### 整体架构设计

#### 1. 目录结构
```
backtrader/
├── ml/                        # 机器学习模块
│   ├── __init__.py
│   ├── base.py                # ML模型抽象基类
│   ├── models/                # 模型包装器
│   │   ├── __init__.py
│   │   ├── sklearn.py         # scikit-learn包装
│   │   ├── keras.py           # Keras包装
│   │   ├── pytorch.py         # PyTorch包装
│   │   └── xgboost.py         # XGBoost/LightGBM包装
│   ├── indicators/            # ML指标
│   │   ├── __init__.py
│   │   ├── prediction.py      # 预测指标
│   │   └── signal.py          # 信号指标
│   └── utils.py               # ML工具函数
│
├── features/                  # 特征工程模块
│   ├── __init__.py
│   ├── engineer.py            # 特征工程器
│   ├── price.py               # 价格特征
│   ├── momentum.py            # 动量特征
│   ├── trend.py               # 趋势特征
│   ├── volatility.py          # 波动率特征
│   ├── oscillator.py          # 振荡器特征
│   └── normalization.py       # 标准化工具
│
├── training/                  # 训练模块
│   ├── __init__.py
│   ├── pipeline.py            # 训练流程
│   ├── label.py               # 标签生成
│   ├── cv.py                  # 交叉验证
│   └── optimization.py        # 超参数优化
│
├── online/                    # 在线学习模块
│   ├── __init__.py
│   ├── memory.py              # Replay Memory
│   ├── strategy.py            # 在线学习策略基类
│   └── updater.py             # 模型更新器
│
└── analyzers/                 # 分析器
    ├── __init__.py
    ├── ml_metrics.py          # ML指标分析器
    └── feature_importance.py  # 特征重要性分析器
```

### 详细设计

#### 1. ML模型抽象接口

```python
# ml/base.py
from abc import ABC, abstractmethod
from typing import Any, Union
import numpy as np

class MLModel(ABC):
    """机器学习模型抽象接口"""

    def __init__(self, model=None):
        self.model = model
        self.is_fitted = False

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> 'MLModel':
        """训练模型

        Args:
            X: 特征矩阵 (n_samples, n_features)
            y: 标签 (n_samples,)

        Returns:
            self
        """
        pass

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """预测

        Args:
            X: 特征矩阵

        Returns:
            预测结果
        """
        pass

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """预测概率

        Args:
            X: 特征矩阵

        Returns:
            预测概率
        """
        raise NotImplementedError("predict_proba not implemented")

    @abstractmethod
    def save(self, path: str):
        """保存模型"""
        pass

    @abstractmethod
    def load(self, path: str) -> 'MLModel':
        """加载模型"""
        pass


class ScikitLearnModel(MLModel):
    """scikit-learn模型包装器"""

    def __init__(self, model):
        super().__init__(model)

    def fit(self, X, y):
        self.model.fit(X, y)
        self.is_fitted = True
        return self

    def predict(self, X):
        return self.model.predict(X)

    def predict_proba(self, X):
        if hasattr(self.model, 'predict_proba'):
            return self.model.predict_proba(X)
        return self.model.predict(X)

    def save(self, path):
        import joblib
        joblib.dump(self.model, path)

    def load(self, path):
        import joblib
        self.model = joblib.load(path)
        self.is_fitted = True
        return self


class KerasModel(MLModel):
    """Keras模型包装器"""

    def __init__(self, model=None, input_shape=None):
        super().__init__(model)
        self.input_shape = input_shape

    def fit(self, X, y, epochs=100, batch_size=32, verbose=0):
        import tensorflow as tf
        from tensorflow import keras

        if self.model is None:
            self.model = self._build_model(X.shape[1])

        history = self.model.fit(
            X, y,
            epochs=epochs,
            batch_size=batch_size,
            verbose=verbose
        )
        self.is_fitted = True
        return self

    def _build_model(self, input_dim):
        """构建默认神经网络"""
        from tensorflow import keras
        from tensorflow.keras import layers

        model = keras.Sequential([
            layers.Dense(128, activation='relu',
                        input_dim=input_dim,
                        kernel_regularizer=keras.regularizers.l2(0.001)),
            layers.Dense(64, activation='relu',
                        kernel_regularizer=keras.regularizers.l2(0.001)),
            layers.Dense(16, activation='relu'),
            layers.Dense(8, activation='relu'),
            layers.Dense(1, activation='tanh')
        ])

        model.compile(
            optimizer=keras.optimizers.SGD(lr=0.001, momentum=0.5),
            loss='mse'
        )
        return model

    def predict(self, X):
        return self.model.predict(X)

    def predict_proba(self, X):
        pred = self.predict(X)
        # 将tanh输出转换为概率
        return (pred + 1) / 2

    def save(self, path):
        self.model.save(path)

    def load(self, path):
        from tensorflow import keras
        self.model = keras.models.load_model(path)
        self.is_fitted = True
        return self
```

#### 2. 特征工程器

```python
# features/engineer.py
import pandas as pd
import numpy as np
from typing import List, Dict

class FeatureEngineer:
    """金融特征工程器"""

    def __init__(self):
        self.feature_names = []

    def add_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加基础价格特征

        Features:
        - Returns: 日收益率
        - Log Returns: 对数收益率
        - Gap: 跳空幅度
        """
        df = df.copy()
        df['returns'] = df['Close'].pct_change()
        df['log_returns'] = np.log(df['Close'] / df['Close'].shift(1))
        df['gap'] = (df['Open'] - df['Close'].shift(1)) / df['Close'].shift(1)

        self._add_feature_names(['returns', 'log_returns', 'gap'])
        return df

    def add_momentum_features(self, df: pd.DataFrame,
                             periods: List[int] = [5, 10, 15]) -> pd.DataFrame:
        """添加动量特征

        Features:
        - Momentum: 价格变化率
        - ROC: 变化率
        """
        df = df.copy()
        for p in periods:
            df[f'momentum_{p}'] = df['Close'] - df['Close'].shift(p)
            df[f'roc_{p}'] = (df['Close'] - df['Close'].shift(p)) / df['Close'].shift(p)

        self._add_feature_names([f'momentum_{p}' for p in periods])
        self._add_feature_names([f'roc_{p}' for p in periods])
        return df

    def add_ma_features(self, df: pd.DataFrame,
                       periods: List[int] = [7, 14, 21]) -> pd.DataFrame:
        """添加均线特征

        Features:
        - SMA: 简单移动平均
        - EMA: 指数移动平均
        - Price vs MA: 价格相对于均线的位置
        """
        df = df.copy()
        for p in periods:
            df[f'sma_{p}'] = df['Close'].rolling(p).mean()
            df[f'ema_{p}'] = df['Close'].ewm(span=p).mean()
            df[f'price_vs_sma_{p}'] = (df['Close'] - df[f'sma_{p}']) / df[f'sma_{p}']
            df[f'price_vs_ema_{p}'] = (df['Close'] - df[f'ema_{p}']) / df[f'ema_{p}']

        self._add_feature_names([f'sma_{p}' for p in periods])
        self._add_feature_names([f'ema_{p}' for p in periods])
        return df

    def add_volatility_features(self, df: pd.DataFrame,
                                periods: List[int] = [7, 14, 21]) -> pd.DataFrame:
        """添加波动率特征

        Features:
        - StdDev: 滚动标准差
        - ATR: 平均真实波幅
        - Bollinger Bands: 布林带
        """
        df = df.copy()
        for p in periods:
            df[f'std_{p}'] = df['Close'].rolling(p).std()
            df[f'cv_{p}'] = df[f'std_{p}'] / df['Close'].rolling(p).mean()  # 变异系数

        # ATR
        df['tr'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                abs(df['High'] - df['Close'].shift(1)),
                abs(df['Low'] - df['Close'].shift(1))
            )
        )
        df['atr_14'] = df['tr'].rolling(14).mean()

        # Bollinger Bands
        df['bb_middle'] = df['Close'].rolling(20).mean()
        df['bb_std'] = df['Close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_middle'] - 2 * df['bb_std']
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        df['bb_position'] = (df['Close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        self._add_feature_names([f'std_{p}' for p in periods])
        self._add_feature_names(['atr_14', 'bb_width', 'bb_position'])
        return df

    def add_oscillator_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加振荡器特征

        Features:
        - RSI: 相对强弱指标
        - Stochastic: 随机振荡器
        """
        df = df.copy()

        # RSI
        for p in [9, 14, 21]:
            delta = df['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(p).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(p).mean()
            rs = gain / loss
            df[f'rsi_{p}'] = 100 - (100 / (1 + rs))

        # Stochastic
        for p in [7, 14, 21]:
            low_min = df['Low'].rolling(p).min()
            high_max = df['High'].rolling(p).max()
            df[f'stoch_k_{p}'] = 100 * (df['Close'] - low_min) / (high_max - low_min)
            df[f'stoch_d_{p}'] = df[f'stoch_k_{p}'].rolling(3).mean()

        self._add_feature_names([f'rsi_{p}' for p in [9, 14, 21]])
        self._add_feature_names([f'stoch_k_{p}' for p in [7, 14, 21]])
        return df

    def add_trend_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加趋势特征

        Features:
        - MACD: 指数平滑移动平均
        - MACD Signal
        - MACD Histogram
        - ADX: 平均趋向指标
        """
        df = df.copy()

        # MACD
        df['ema_12'] = df['Close'].ewm(span=12).mean()
        df['ema_26'] = df['Close'].ewm(span=26).mean()
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_hist'] = df['macd'] - df['macd_signal']

        # +DI/-DI
        df['tr'] = np.maximum(
            df['High'] - df['Low'],
            np.maximum(
                abs(df['High'] - df['Close'].shift(1)),
                abs(df['Low'] - df['Close'].shift(1))
            )
        )
        df['plus_dm'] = np.where(df['High'] - df['High'].shift(1) > df['Low'].shift(1) - df['Low'],
                                 np.maximum(df['High'] - df['High'].shift(1), 0), 0)
        df['minus_dm'] = np.where(df['Low'].shift(1) - df['Low'] > df['High'] - df['High'].shift(1),
                                  np.maximum(df['Low'].shift(1) - df['Low'], 0), 0)

        for p in [14]:
            df[f'plus_di_{p}'] = 100 * (df['plus_dm'].rolling(p).mean() / df['tr'].rolling(p).mean())
            df[f'minus_di_{p}'] = 100 * (df['minus_dm'].rolling(p).mean() / df['tr'].rolling(p).mean())

        self._add_feature_names(['macd', 'macd_signal', 'macd_hist', 'plus_di_14', 'minus_di_14'])
        return df

    def add_all_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """添加所有特征"""
        df = self.add_price_features(df)
        df = self.add_momentum_features(df)
        df = self.add_ma_features(df)
        df = self.add_volatility_features(df)
        df = self.add_oscillator_features(df)
        df = self.add_trend_features(df)
        return df

    def get_feature_matrix(self, df: pd.DataFrame) -> np.ndarray:
        """获取特征矩阵

        排除OHLCV列，只返回特征列
        """
        base_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
        feature_cols = [c for c in df.columns if c not in base_cols]
        self.feature_names = feature_cols
        return df[feature_cols].values

    def _add_feature_names(self, names: List[str]):
        for name in names:
            if name not in self.feature_names:
                self.feature_names.append(name)
```

#### 3. 标签生成器

```python
# training/label.py
import pandas as pd
import numpy as np

class LabelGenerator:
    """交易标签生成器

    基于未来价格模拟生成交易标签
    """

    def __init__(self,
                 gain_threshold: float = 0.02,
                 loss_threshold: float = -0.02,
                 holding_period: int = 5,
                 commission: float = 0.001):
        """
        Args:
            gain_threshold: 止盈阈值（涨幅）
            loss_threshold: 止损阈值（跌幅）
            holding_period: 持有天数
            commission: 交易手续费率
        """
        self.gain_threshold = gain_threshold
        self.loss_threshold = loss_threshold
        self.holding_period = holding_period
        self.commission = commission

    def generate_labels(self, df: pd.DataFrame) -> np.ndarray:
        """生成交易标签

        策略:
        1. 模拟未来n天的价格变化
        2. 如果涨幅超过gain_threshold，标记为买入(1)
        3. 如果跌幅超过loss_threshold，标记为卖出(0)
        4. 考虑交易成本

        Args:
            df: 包含OHLCV数据的DataFrame

        Returns:
            labels: 1D数组，1=买入，0=卖出
        """
        n = len(df)
        labels = np.zeros(n, dtype=int)

        for i in range(n - self.holding_period):
            current_price = df['Close'].iloc[i]
            future_prices = df['Close'].iloc[i+1:i+1+self.holding_period]

            # 计算未来收益（考虑买入成本）
            buy_cost = current_price * (1 + self.commission)

            # 检查是否达到止盈
            max_gain = (future_prices.max() - buy_cost) / buy_cost
            if max_gain >= self.gain_threshold:
                labels[i] = 1
                continue

            # 检查是否达到止损
            max_loss = (future_prices.min() - buy_cost) / buy_cost
            if max_loss <= self.loss_threshold:
                labels[i] = 0
                continue

            # 如果没有达到阈值，根据最终收益判断
            final_return = (future_prices.iloc[-1] * (1 - self.commission) - buy_cost) / buy_cost
            labels[i] = 1 if final_return > 0 else 0

        # 最后holding_period天没有未来数据，标记为卖出
        labels[-self.holding_period:] = 0

        return labels

    def generate_regression_labels(self, df: pd.DataFrame) -> np.ndarray:
        """生成回归标签（未来收益率）"""
        n = len(df)
        labels = np.zeros(n)

        for i in range(n - self.holding_period):
            current_price = df['Close'].iloc[i]
            future_price = df['Close'].iloc[i + self.holding_period]
            labels[i] = (future_price - current_price) / current_price

        labels[-self.holding_period:] = 0
        return labels
```

#### 4. 在线学习策略

```python
# online/strategy.py
import backtrader as bt
import numpy as np
from typing import List
from collections import deque

class ReplayMemory:
    """经验回放缓冲区"""

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self.experiences: deque = deque(maxlen=max_size)

    def add(self, features: np.ndarray, label: int):
        """添加经验"""
        self.experiences.append((features, label))

    def sample(self, batch_size: int):
        """随机采样"""
        import random
        return random.sample(list(self.experiences), min(batch_size, len(self.experiences)))

    def get_all(self):
        """获取所有经验"""
        features = np.array([e[0] for e in self.experiences])
        labels = np.array([e[1] for e in self.experiences])
        return features, labels

    def __len__(self):
        return len(self.experiences)


class OnlineLearningStrategy(bt.Strategy):
    """在线学习策略基类

    支持策略运行时的增量学习和模型更新
    """

    params = (
        ('model', None),                # ML模型
        ('feature_cols', None),         # 特征列名
        ('retrain_interval', 10),       # 重新训练间隔（天）
        ('memory_size', 15),            # Replay Memory大小
        ('buy_threshold', 0.55),        # 买入阈值
        ('sell_threshold', 0.45),       # 卖出阈值
        ('confidence_filter', True),    # 是否过滤低置信度预测
    )

    def __init__(self):
        self.memory = ReplayMemory(self.p.memory_size)
        self.days_since_retrain = 0
        self.last_features = None

    def next(self):
        """主策略逻辑"""
        # 1. 获取当前特征
        features = self._get_features()

        if features is None:
            return

        self.last_features = features

        # 2. 模型预测
        if hasattr(self.p.model, 'predict_proba'):
            proba = self.p.model.predict_proba(features.reshape(1, -1))[0]
            prediction = proba[1]  # 正类概率
        else:
            prediction = self.p.model.predict(features.reshape(1, -1))[0]
            proba = [1-prediction, prediction]

        # 3. 置信度过滤
        if self.p.confidence_filter:
            if prediction < 0.45 or prediction > 0.55:  # 高置信度
                # 4. 根据预测进行交易
                if prediction >= self.p.buy_threshold and not self.position:
                    self.buy()
                elif prediction <= self.p.sell_threshold and self.position:
                    self.sell()

        # 5. 收集经验（用于未来训练）
        # 使用未来价格作为标签（延迟标签）
        if len(self) >= self.p.retrain_interval:
            future_return = self._get_future_return()
            if future_return is not None:
                label = 1 if future_return > 0 else 0
                self.memory.add(self.last_features, label)

        # 6. 周期性重新训练
        self.days_since_retrain += 1
        if self.days_since_retrain >= self.p.retrain_interval:
            self._retrain()
            self.days_since_retrain = 0

    def _get_features(self) -> np.ndarray:
        """获取当前特征向量

        需要在子类中实现，根据self.p.feature_cols
        从数据中提取特征
        """
        if self.p.feature_cols is None:
            return None

        features = []
        for col in self.p.feature_cols:
            if hasattr(self.data, col):
                features.append(getattr(self.data, col)[0])

        return np.array(features) if features else None

    def _get_future_return(self) -> float:
        """获取未来收益率

        用于延迟标签
        """
        if len(self.data) < self.p.retrain_interval + 1:
            return None

        current_price = self.data.close[0]
        future_price = self.data.close[-self.p.retrain_interval]
        return (future_price - current_price) / current_price

    def _retrain(self):
        """重新训练模型"""
        if len(self.memory) < 5:  # 至少需要5个样本
            return

        X, y = self.memory.get_all()
        self.p.model.fit(X, y)
        print(f"[{self.datetime.date()}] Model retrained with {len(X)} samples")


class MLPredictionIndicator(bt.Indicator):
    """ML预测指标

    将ML模型的预测结果作为指标输出
    """

    lines = ('prediction', 'probability', 'signal',)

    params = (
        ('model', None),
        ('features', None),  # 特征数据源列表
        ('buy_threshold', 0.55),
        ('sell_threshold', 0.45),
    )

    def __init__(self):
        self.model = self.p.model

    def next(self):
        """计算预测"""
        # 获取特征
        features = self._get_features()
        if features is None:
            self.lines.prediction[0] = 0
            self.lines.probability[0] = 0.5
            self.lines.signal[0] = 0
            return

        # 预测
        if hasattr(self.model, 'predict_proba'):
            proba = self.model.predict_proba(features.reshape(1, -1))[0]
            prediction = proba[1]
        else:
            prediction = self.model.predict(features.reshape(1, -1))[0]
            proba = [1 - prediction, prediction]

        self.lines.probability[0] = prediction

        # 生成交易信号
        if prediction >= self.p.buy_threshold:
            self.lines.signal[0] = 1
        elif prediction <= self.p.sell_threshold:
            self.lines.signal[0] = -1
        else:
            self.lines.signal[0] = 0

        self.lines.prediction[0] = 1 if prediction > 0.5 else 0

    def _get_features(self):
        """获取特征向量"""
        if self.p.features is None:
            return None

        features = []
        for data_feed in self.p.features:
            if hasattr(data_feed, 'close'):
                features.append(data_feed.close[0])
            elif hasattr(data_feed, 'prediction'):
                features.append(data_feed.prediction[0])

        return np.array(features) if features else None
```

#### 5. ML分析器

```python
# analyzers/ml_metrics.py
import backtrader as bt
import numpy as np
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, confusion_matrix
)

class MLAnalyzer(bt.Analyzer):
    """ML模型性能分析器

    分析ML预测的准确性和交易表现
    """

    def __init__(self):
        self.predictions = []
        self.actuals = []
        self.confidences = []
        self.trade_results = []

    def notify_order(self, order):
        """记录订单结果"""
        if order.status in [order.Completed]:
            # 记录交易结果
            pass

    def add_prediction(self, prediction, actual, confidence=None):
        """添加预测记录"""
        self.predictions.append(prediction)
        self.actuals.append(actual)
        if confidence is not None:
            self.confidences.append(confidence)

    def get_accuracy(self):
        """计算准确率"""
        if not self.predictions:
            return None
        return accuracy_score(self.actuals, self.predictions)

    def get_precision(self):
        """计算精确率"""
        if not self.predictions:
            return None
        return precision_score(self.actuals, self.predictions, zero_division=0)

    def get_recall(self):
        """计算召回率"""
        if not self.predictions:
            return None
        return recall_score(self.actuals, self.predictions, zero_division=0)

    def get_f1_score(self):
        """计算F1分数"""
        if not self.predictions:
            return None
        return f1_score(self.actuals, self.predictions, zero_division=0)

    def get_roc_auc(self):
        """计算ROC AUC"""
        if not self.confidences:
            return None
        return roc_auc_score(self.actuals, self.confidences)

    def get_confusion_matrix(self):
        """获取混淆矩阵"""
        if not self.predictions:
            return None
        return confusion_matrix(self.actuals, self.predictions)

    def get_analysis(self):
        """获取完整分析结果"""
        return {
            'accuracy': self.get_accuracy(),
            'precision': self.get_precision(),
            'recall': self.get_recall(),
            'f1_score': self.get_f1_score(),
            'roc_auc': self.get_roc_auc(),
            'confusion_matrix': self.get_confusion_matrix(),
            'total_predictions': len(self.predictions),
        }
```

### 使用示例

#### 示例1: 使用scikit-learn模型

```python
import backtrader as bt
from backtrader.ml import ScikitLearnModel
from backtrader.features import FeatureEngineer, LabelGenerator
from backtrader.training import TrainingPipeline
from sklearn.ensemble import RandomForestClassifier

# 1. 准备数据
df = pd.read_csv('stock_data.csv')
df['Date'] = pd.to_datetime(df['Date'])
df.set_index('Date', inplace=True)

# 2. 特征工程
fe = FeatureEngineer()
df = fe.add_all_features(df)

# 3. 生成标签
label_gen = LabelGenerator(gain_threshold=0.02, loss_threshold=-0.02)
labels = label_gen.generate_labels(df)

# 4. 训练模型
model = ScikitLearnModel(RandomForestClassifier(n_estimators=100))
train_size = int(len(df) * 0.7)
X_train = df.iloc[:train_size]
y_train = labels[:train_size]

model.fit(fe.get_feature_matrix(X_train), y_train)

# 5. 回测
cerebro = bt.Cerebro()

# 添加数据
data = bt.feeds.PandasData(dataname=df)
cerebro.adddata(data)

# 添加ML策略
cerebro.addstrategy(
    OnlineLearningStrategy,
    model=model,
    feature_cols=fe.feature_names,
    retrain_interval=10,
    buy_threshold=0.6,
    sell_threshold=0.4
)

# 运行
result = cerebro.run()
```

#### 示例2: 使用Keras神经网络

```python
from backtrader.ml import KerasModel
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import Dense, Dropout

# 构建自定义Keras模型
def build_model(input_dim):
    model = Sequential([
        Dense(128, activation='relu', input_dim=input_dim),
        Dropout(0.2),
        Dense(64, activation='relu'),
        Dropout(0.2),
        Dense(32, activation='relu'),
        Dense(1, activation='sigmoid')
    ])
    model.compile(
        optimizer='adam',
        loss='binary_crossentropy',
        metrics=['accuracy']
    )
    return model

# 创建包装器
ml_model = KerasModel(input_shape=(50,))  # 根据特征数量调整

# 训练
ml_model.fit(X_train, y_train, epochs=100, batch_size=32)

# 在策略中使用
cerebro.addstrategy(
    OnlineLearningStrategy,
    model=ml_model,
    feature_cols=fe.feature_names,
    retrain_interval=5
)
```

#### 示例3: 信号融合

```python
class FusionStrategy(bt.Strategy):
    """融合ML信号和技术指标的策略"""

    def __init__(self):
        # ML预测指标
        self.ml_pred = MLPredictionIndicator(
            model=self.p.model,
            features=[self.data],
            buy_threshold=0.6,
            sell_threshold=0.4
        )

        # 技术指标
        self.sma_short = bt.indicators.SMA(self.data.close, period=20)
        self.sma_long = bt.indicators.SMA(self.data.close, period=50)
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

    def next(self):
        # ML信号
        ml_signal = self.ml_pred.signal[0]

        # 技术分析信号
        ta_signal = 0
        if self.sma_short[0] > self.sma_long[0]:
            ta_signal += 1
        if self.rsi[0] < 30:  # 超卖
            ta_signal += 1
        elif self.rsi[0] > 70:  # 超买
            ta_signal -= 1

        # 融合信号
        combined = ml_signal * 0.6 + ta_signal * 0.4

        if combined > 0.5 and not self.position:
            self.buy()
        elif combined < -0.5 and self.position:
            self.sell()
```

### 实施计划

#### 第一阶段 (P0功能)
1. ML模型抽象接口
2. scikit-learn模型包装
3. Keras/TensorFlow模型包装
4. 基础特征工程器
5. 标签生成器
6. ML预测指标

#### 第二阶段 (P1功能)
1. PyTorch模型包装
2. XGBoost/LightGBM包装
3. 在线学习策略
4. Replay Memory
5. ML分析器
6. 时间序列交叉验证

#### 第三阶段 (P2功能)
1. 特征选择工具
2. 超参数优化
3. 多模型集成
4. 模型版本管理
5. 高级评估指标

---

## 总结

通过借鉴AI-Strategies-StockMarket项目的设计理念，Backtrader可以扩展以下能力：

1. **统一的ML接口**: 支持多种ML框架的无缝集成
2. **丰富的特征工程**: 50+金融技术指标的自动提取
3. **智能标签生成**: 基于交易成本和风险阈值的标签系统
4. **在线学习**: 策略运行时的增量学习和模型更新
5. **信号融合**: ML预测与传统技术指标的有机结合
6. **完整评估**: 模型性能和交易表现的综合分析

这些增强功能将使Backtrader能够支持AI驱动的量化策略开发，从传统的技术分析扩展到机器学习、深度学习领域，为用户提供更强大的策略研发工具。
