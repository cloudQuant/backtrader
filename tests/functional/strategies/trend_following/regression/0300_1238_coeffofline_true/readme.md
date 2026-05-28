# 1238 CoeffofLine_true

## 策略概述

该策略是对 MT5 EA `1238_Exp_CoeffofLine_true` 的 Backtrader 迁移版本。
原 EA 调用 `CoeffofLine_true` 指标，并依据直方图穿越零轴来执行反手交易。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `PRICE_MEDIAN` 上的 `SMMA(period, shift=3)`
3. 对最近 `period` 根中价与 `SMMA` 做加权线性系数运算
4. 计算 `value = ±1000 * log(AY / AIndicator)`
5. 当该值从负转正时做多；从正转负时做空

## 主要参数

- `indicator_minutes`
- `smma_period`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原始指标对部分外汇品种会反转符号方向；
本迁移版保留该符号翻转规则，以便与原 MQL 输出方向保持一致。
