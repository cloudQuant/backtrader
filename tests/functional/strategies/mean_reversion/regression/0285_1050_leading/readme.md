# 1050 Exp_Leading

## 策略概述

该示例是对 MT5 EA `1050_Exp_Leading` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上读取 `Leading` 指标的两条线，并在交叉时执行开平仓。

## 原始信号逻辑

1. 指标包含 `NetLeadBuffer` 与 `EMABuffer`
2. 当上一根 `NetLeadBuffer > EMABuffer`、当前已完成柱变为下穿时触发做多
3. 当上一根 `NetLeadBuffer < EMABuffer`、当前已完成柱变为上穿时触发做空
4. 反向信号出现时允许平掉已有反向仓位

## 指标迁移说明

- 价格输入使用 `HL2`
- `Lead` 按 `Alpha1` 递推构造
- `NetLeadBuffer` 使用 `Alpha2` 平滑 `Lead`
- `EMABuffer` 使用固定 `0.5/0.5` 递推均值

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
