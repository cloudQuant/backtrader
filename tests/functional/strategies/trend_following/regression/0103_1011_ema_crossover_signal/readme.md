# 1011 Exp_EMA-Crossover_Signal

## 策略概述

该示例是对 MT5 EA `1011_Exp_EMA-Crossover_Signal` 的 Backtrader 迁移版本。
EA 在 `H4` 周期上计算 `EMA-Crossover_Signal` 指标，并在出现新的买卖菱形时执行开平仓。

## 原始信号逻辑

1. 对指定价格计算一条快均线和一条慢均线
2. 当 `bar+2` 与 `bar+1` 已确认发生穿越，且当前柱继续保持穿越后的方向时，在当前柱画出箭头信号
3. EA 在柱线收盘时读取买卖箭头缓冲区：
   - 出现买入箭头则做多并可平空
   - 出现卖出箭头则做空并可平多

## 指标迁移说明

- 指标核心完全基于两条标准均线和公开箭头条件，可直接重建
- 保留默认 `FasterMA=5 / SlowerMA=6 / MODE_LWMA / PRICE_CLOSE`
- 保留默认 `H4` 信号周期与固定 `SL/TP`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
