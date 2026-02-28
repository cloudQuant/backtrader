---
title: 指标
description: 内置技术指标
---

# 指标

Backtrader 包含 60+ 内置技术指标。本指南介绍如何有效使用它们。

## 基本用法

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # 创建指标
        self.sma = bt.indicators.SMA(self.data.close, period=20)

    def next(self):
        # 访问当前值
        current_value = self.sma[0]
```

## 指标分类

### 移动平均线

```python
# 简单移动平均线
sma = bt.indicators.SMA(self.data.close, period=20)

# 指数移动平均线
ema = bt.indicators.EMA(self.data.close, period=20)

# 加权移动平均线
wma = bt.indicators.WMA(self.data.close, period=20)

# 双指数移动平均线
dema = bt.indicators.DEMA(self.data.close, period=20)

# 三重指数移动平均线
tema = bt.indicators.TEMA(self.data.close, period=20)

# Hull 移动平均线
hma = bt.indicators.HMA(self.data.close, period=20)
```

### 动量指标

```python
# 相对强弱指数
rsi = bt.indicators.RSI(self.data.close, period=14)

# 随机指标
stoch = bt.indicators.Stochastic(self.data, period=14)

# MACD
macd = bt.indicators.MACD(self.data.close)

# 变化率
roc = bt.indicators.ROC(self.data.close, period=10)

# 动量
momentum = bt.indicators.Momentum(self.data.close, period=10)

# 佳庆指标
ao = bt.indicators.AwesomeOscillator(self.data)
```

### 波动率指标

```python
# 平均真实波幅
atr = bt.indicators.ATR(self.data, period=14)

# 布林带
bollinger = bt.indicators.BollingerBands(self.data.close, period=20)

# 标准差
stdev = bt.indicators.StdDev(self.data.close, period=20)
```

### 成交量指标

```python
# 能量潮
obv = bt.indicators.OBV(self.data)

# 资金流量指数
mfi = bt.indicators.MFI(self.data, period=14)
```

### 振荡器

```python
# 商品通道指数
cci = bt.indicators.CCI(self.data, period=14)

# 方向性运动
plus_dm = bt.indicators.PlusDM(self.data, period=14)
minus_dm = bt.indicators.MinusDM(self.data, period=14)

# 平均方向指数
adx = bt.indicators.ADX(self.data, period=14)

# 阿隆指标
aroon = bt.indicators.Aroon(self.data, period=14)
```

## 交叉指标

检测一个指标何时穿越另一个指标。

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        self.fast_ma = bt.indicators.SMA(self.data.close, period=10)
        self.slow_ma = bt.indicators.SMA(self.data.close, period=30)

        # 交叉指标
        self.crossover = bt.indicators.CrossOver(self.fast_ma, self.slow_ma)

    def next(self):
        if self.crossover > 0:  # 快线上穿慢线
            self.buy()
        elif self.crossover < 0:  # 快线下穿慢线
            self.sell()
```

## 指标参数

```python
# 使用策略参数定义指标
class MyStrategy(bt.Strategy):
    params = (
        ('ma_period', 20),
        ('rsi_period', 14),
    )

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.ma_period)
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.rsi_period)
```

## 指标的指标

指标可以基于其他指标计算。

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # SMA 的 SMA (平滑移动平均线)
        self.sma = bt.indicators.SMA(self.data.close, period=10)
        self.sma_sma = bt.indicators.SMA(self.sma, period=5)

        # 收盘价的 RSI
        self.rsi = bt.indicators.RSI(self.data.close, period=14)

        # RSI 的 SMA (RSI 平滑)
        self.rsi_sma = bt.indicators.SMA(self.rsi, period=5)
```

## 访问指标线

某些指标有多个输出线。

```python
# MACD 有多个线
macd = bt.indicators.MACD(self.data.close)

# 访问各个线
macd_line = macd.macd[0]        # MACD 线
signal_line = macd.signal[0]    # 信号线
histogram = macd.histo[0]      # 柱状图

# 布林带
bollinger = bt.indicators.BollingerBands(self.data.close)

mid = bollinger.mid[0]          # 中轨 (SMA)
top = bollinger.top[0]          # 上轨
bot = bollinger.bot[0]          # 下轨
```

## 绘制指标

```python
class MyStrategy(bt.Strategy):
    def __init__(self):
        # 指标自动绘制
        self.sma = bt.indicators.SMA(self.data.close, period=20)

        # 禁用绘制
        self.rsi = bt.indicators.RSI(self.data.close, period=14)
        self.rsi.plotinfo.plot = False  # 不绘制 RSI
```

## 可用指标参考

| 指标 | 描述 | 参数 |
|-----------|-------------|------------|
| SMA | 简单移动平均线 | period |
| EMA | 指数移动平均线 | period |
| WMA | 加权移动平均线 | period |
| RSI | 相对强弱指数 | period, upper, lower |
| MACD | MACD | period_me1, period_me2, signal |
| BollingerBands | 布林带 | period, devfactor |
| ATR | 平均真实波幅 | period |
| Stochastic | 随机振荡器 | period, period_dfast, period_dslow |
| CCI | 商品通道指数 | period, upper, lower |
| ADX | 平均方向指数 | period |
| Aroon | 阿隆指标 | period |
| CrossOver | 交叉检测 | period |
| Oscillator | 振荡器 (快-慢) | p1, p2 |

## 下一步学习

- [策略](strategies_zh.md) - 在策略中使用指标
- [分析器](analyzers_zh.md) - 分析策略性能
