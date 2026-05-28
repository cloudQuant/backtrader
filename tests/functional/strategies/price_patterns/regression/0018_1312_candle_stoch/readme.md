# 1312 Candlestick Patterns + Stochastic

## 策略概述

该策略是对 MT5 EA `1312_基于_K_线形态的交易信号_+_Stochastic` 的 backtrader 迁移版本。

- 综合 K 线形态识别（吞噬、乌云盖顶/刺穿线、早晨之星/黄昏之星）
- Stochastic 作为入场确认
- Stochastic 穿越超买超卖区域离场

## 核心逻辑

1. 检测 Bullish Engulfing / Piercing Line / Morning Star 看涨信号
2. 检测 Bearish Engulfing / Dark Cloud Cover / Evening Star 看跌信号
3. 当出现看涨信号且 `Stoch %D < 30` 时做多
4. 当出现看跌信号且 `Stoch %D > 70` 时做空
5. 持仓后根据 `%D` 穿越超买 / 超卖边界离场

## 运行方式

```bash
python run.py
python run.py --plot
```

## 当前回测结果

待验证后更新。
