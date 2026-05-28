# 1237 2pbIdealMA

## 策略概述

该策略是对 MT5 EA `1237_Exp_2pbIdealMA` 的 Backtrader 迁移版本。
原 EA 同时调用 `2pbIdeal1MA` 与 `2pbIdeal3MA` 两条平滑均线，并依据二者在柱线收盘时的交叉来执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 使用 `GetIdealMASmooth` 公式重建快速 `2pbIdeal1MA`
3. 使用三级串联的 `GetIdealMASmooth` 公式重建慢速 `2pbIdeal3MA`
4. 当快速线从下向上穿越慢速线时做多
5. 当快速线从上向下穿越慢速线时做空

## 主要参数

- `indicator_minutes`
- `period1`
- `period2`
- `periodx1`
- `periodx2`
- `periody1`
- `periody2`
- `periodz1`
- `periodz2`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

仓内 `1294_2pb_ideal_xosma` 已包含同源 `GetIdealMASmooth` 实现，
本迁移版在保留原始平滑公式的前提下，按 EA 的双线交叉规则独立执行交易。
