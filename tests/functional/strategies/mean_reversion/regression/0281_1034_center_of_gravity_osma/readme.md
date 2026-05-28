# 1034 Exp_CenterOfGravityOSMA

## 策略概述

该示例是对 MT5 EA `1034_Exp_CenterOfGravityOSMA` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `CenterOfGravityOSMA` 直方图，当最近已完成柱的方向从下降转上升或从上升转下降时执行开平仓。

## 原始信号逻辑

1. 先以所选价格序列计算 `SMA(period)` 与 `LWMA(period)`
2. 组合得到 `res1 = SMA * LWMA / Point`
3. 对 `res1` 做第一次平滑得到 `res2`
4. 计算 `res3 = res1 - res2`
5. 再对 `res3` 做第二次平滑得到最终直方图 `ExtBuffer`
6. EA 在柱线收盘时读取最近 3 个已完成信号值：
   - `macd[1] < macd[2]` 且 `macd[0] > macd[1]` 触发买入
   - `macd[1] > macd[2]` 且 `macd[0] < macd[1]` 触发卖出

## 指标迁移说明

- 虽然原指标包含 `SmoothAlgorithms.mqh`，但源码暴露出的核心计算仅使用标准 `SMA/LWMA/MA` 组合，可在 Python 中本地重建
- 默认保留 `period=10`、两段 `smooth_period=3`、`PRICE_CLOSE`、`H4` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
