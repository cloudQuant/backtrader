# 0540 HarVesteR

## 策略概述

该策略是对 MT5 EA `0540_HarVesteR` 的 Backtrader 迁移版本。

- 使用 `MACD + 双 SMA + ADX` 做方向过滤
- 用最近若干柱高低点设置初始止损
- 达到 `SL * half_ratio` 后先平半仓，再把止损移到 breakeven

## 核心逻辑

1. 价格相对两条均线的位置、`MACD` 当前方向以及过去若干柱中是否出现过反向 `MACD` 区域，共同决定开仓。
2. 买入时用最近 `number_bars_sl` 根的最低点做止损；卖出时用最高点做止损。
3. 持仓盈利达到 `half_ratio * 初始风险` 时，先平半仓，再把剩余仓位止损推到开仓价。

## 迁移说明

- 原版使用 MT5 的部分平仓接口；迁移版用 Backtrader 的 `close(size=...)` 做近似实现。
- 原版 `ADX` 关闭分支里存在代码级瑕疵；迁移版按 readme 意图使用常量 `60` 作为替代阈值。

## 运行方式

```bash
python run.py
```
