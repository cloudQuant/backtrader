# 1314 Morning Star / Evening Star + MFI

## 策略概述

该策略是对 MT5 EA `1314_基于_早晨之星_黄昏之星形态的交易信号_+_MFI` 的 backtrader 迁移版本。

- 早晨之星 / 黄昏之星（含十字星变体）反转形态识别
- MFI 作为入场确认
- MFI 穿越超买超卖区域离场

## 核心逻辑

1. 识别 Morning Star / Morning Doji 看涨反转形态
2. 识别 Evening Star / Evening Doji 看跌反转形态
3. 当出现 Morning Star 且 `MFI < 40` 时做多
4. 当出现 Evening Star 且 `MFI > 60` 时做空
5. 持仓后根据 MFI 穿越超买 / 超卖边界离场

## 运行方式

```bash
python run.py
python run.py --plot
```

## 当前回测结果

待验证后更新。
