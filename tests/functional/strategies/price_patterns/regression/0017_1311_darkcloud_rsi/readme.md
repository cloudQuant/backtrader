# 1311 Dark Cloud Cover / Piercing Line + RSI

## 策略概述

该策略是对 MT5 EA `1311_基于乌云盖顶_刺穿线和RSI的交易信号` 的 backtrader 迁移版本。

- 乌云盖顶 / 刺穿线反转形态识别
- RSI 作为入场确认
- RSI 穿越超买超卖区域离场

## 核心逻辑

1. 识别 `Dark Cloud Cover` 看跌反转形态
2. 识别 `Piercing Line` 看涨反转形态
3. 当出现 `Piercing Line` 且 `RSI < 40` 时做多
4. 当出现 `Dark Cloud Cover` 且 `RSI > 60` 时做空
5. 持仓后根据 RSI 穿越超买 / 超卖边界离场

## 运行方式

```bash
python run.py
python run.py --plot
```

## 当前回测结果

待验证后更新。
