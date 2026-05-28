# 1309 Bullish/Bearish Engulfing + Stochastic

## 策略概述

该策略是对 MT5 EA `1309_基于Bullish_Engulfing_Bearish_Engulfing和Stochastic的交易信号` 的 backtrader 迁移版本。

- 牛市吞烛 / 熊市吞烛反转形态识别
- Stochastic 作为入场确认
- Stochastic 穿越超买超卖区域离场

## 核心逻辑

1. 识别 Bullish Engulfing 看涨吞没形态
2. 识别 Bearish Engulfing 看跌吞没形态
3. 当出现 Bullish Engulfing 且 `Stoch %D < 30` 时做多
4. 当出现 Bearish Engulfing 且 `Stoch %D > 70` 时做空
5. 持仓后根据 `%D` 穿越超买 / 超卖边界离场

## 运行方式

```bash
python run.py
python run.py --plot
```

## 当前回测结果

待验证后更新。
