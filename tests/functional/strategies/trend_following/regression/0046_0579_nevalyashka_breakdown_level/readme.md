# 0579 Nevalyashka_BreakdownLevel

## 策略概述

该策略是对 MT5 EA `0579_Nevalyashka_BreakdownLevel` 的 Backtrader 迁移版本。

- 在指定时间窗口统计区间高低点
- 区间突破后入场
- 止损后按相反方向和 `K martingale` 放大手数再入场
- 可选在利润达到一半时移动到保本

## 核心逻辑

1. 在 `time_start ~ time_end` 之间统计当日最高价和最低价。
2. `time_end` 后若价格向上突破区间高点则做多，向下跌破区间低点则做空。
3. 初始止损放在区间另一侧，止盈按区间宽度投射。
4. 若止损离场，则按反方向和 `k_martin` 放大手数再次入场。
5. `no_loss=true` 时，在走到半程目标后把止损推进到保本附近。

## 迁移说明

- 原版依赖 `OnTradeTransaction` 精确识别 `tp/sl` 出场；迁移版在 Backtrader 中通过 bar 内价格触发近似模拟。

## 运行方式

```bash
python run.py
```
