# 1105 RSIOMA V2

## 策略概述

该示例是对 MT5 EA `1105_Exp_RSIOMA_V2` 的 Backtrader 迁移版本。
当前版本沿用仓库标准验证数据 `XAUUSD_M15.csv`，复刻原始 EA 的三种信号模式：`breakdown`、`twist`、`cloudtwist`。

## 核心逻辑

1. 先对价格做一次 `EMA` 平滑，得到 `RSIOMA` 的基础序列
2. 基于平滑后序列计算 `RSIOMA` 主线
3. 再对主线做一次 `EMA` 平滑，得到信号线
4. `breakdown`：`RSIOMA` 上穿 `60` 触发做多，下穿 `40` 触发做空
5. `twist`：`RSIOMA` 方向由跌转升/由升转跌时触发反转信号
6. `cloudtwist`：`RSIOMA` 在多头区与空头区之间切换时触发信号
7. 下单后附加固定 `SL / TP`，反向信号先平仓再反手

## 主要参数

- `mode`
- `signal_bar`
- `rsioma_period`
- `ma_rsioma_period`
- `mom_period`
- `main_trend_long`
- `main_trend_short`
- `stop_loss_points`
- `take_profit_points`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- 原始 MT5 指标支持多种 `Smooth_Method`，当前迁移版本优先复刻默认参数下的 `EMA` 路径
- EA 实际交易逻辑主要依赖 `RSIOMA` 主线的阈值突破、方向拐点和区间切换，这三条路径已在 Backtrader 中保留
- 若后续需要进一步贴近 `SmoothAlgorithms.mqh` 的全部平滑方法，可以在当前实现上继续扩展
