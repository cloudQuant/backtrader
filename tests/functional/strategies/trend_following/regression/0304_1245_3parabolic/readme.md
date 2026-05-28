# 1245 3Parabolic

## 策略概述

该策略是对 MT5 EA `1245_Exp_3Parabolic` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，并在内部构造 `H6/H3/H1` 三个周期的 Parabolic SAR 趋势确认。

## 核心逻辑

1. 在 `H6` 与 `H3` 上分别计算 `Parabolic SAR`，作为大级别趋势过滤器
2. 在 `H1` 上同样计算 `Parabolic SAR`，用于检测当前柱是否发生多空翻转
3. 当 `H6/H3` 同时处于多头，且 `H1` 从空头翻转为多头时开多
4. 当 `H6/H3` 同时处于空头，且 `H1` 从多头翻转为空头时开空
5. 任一高周期或 `H1` 当前趋势反向时可平仓，同时保留固定止损止盈

## 主要参数

- `timeframe1_minutes`
- `timeframe2_minutes`
- `timeframe3_minutes`
- `sar_step`
- `sar_maximum`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原 MT5 EA 使用三个不同周期的 `iSAR` 句柄，其中第三周期柱线收盘时，若其 `SAR/Close` 关系翻转且另外两个周期方向一致，则触发入场。
本迁移版用 Backtrader 自带 `ParabolicSAR` 指标在三套重采样数据上重建等价逻辑。
