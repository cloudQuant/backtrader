# 1039 Exp_ADXCrossing

## 策略概述

该示例是对 MT5 EA `1039_Exp_ADXCrossing` 的 Backtrader 迁移版本。
EA 在 `H1` 周期上读取 `ADXCrossing` 指标，当 `+DI` 与 `-DI` 发生方向交叉时，按箭头信号执行开平仓。

## 原始信号逻辑

1. 指标内部使用 `ADX(50)` 的 `+DI` 与 `-DI`
2. 当 `+DI` 上穿 `-DI` 时，在图表下方绘制买入圆点
3. 当 `+DI` 下穿 `-DI` 时，在图表上方绘制卖出圆点
4. EA 读取最近已完成信号柱的箭头，并按固定 `SL/TP` 进行交易

## 指标迁移说明

- 重建 `ADX` 方向分量 `+DI/-DI`
- 使用与源码一致的交叉判定：
  - `+DI > -DI` 且前一柱 `+DI <= -DI` 触发买入
  - `+DI < -DI` 且前一柱 `+DI >= -DI` 触发卖出
- 保留固定止损与止盈参数

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H1`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
