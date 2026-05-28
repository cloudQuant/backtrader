# 1243 Bezier

## 策略概述

该策略是对 MT5 EA `1243_Exp_Bezier` 的 Backtrader 迁移版本。
原 EA 基于 `Bezier` 平滑曲线在指标周期上的方向反转进行开平仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 使用原指标中的 Bezier 权重公式对选定价格序列进行平滑
3. 当最近三个已完成指标值满足 `old > mid < recent` 时，判定为向上拐点并做多
4. 当最近三个已完成指标值满足 `old < mid > recent` 时，判定为向下拐点并做空
5. 保留固定止损止盈接口，与现有示例结构保持一致

## 主要参数

- `indicator_minutes`
- `bperiod`
- `t`
- `ipc`
- `price_shift_points`
- `signal_bar`
- `stop_loss_points`
- `take_profit_points`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

MQL5 指标通过 `BPeriod` 阶组合权重与参数 `T` 对价格序列做 Bezier 平滑，并用曲线斜率变化染色。
EA 本身只读取该曲线数值，在上一段下降后当前转升时做多，在上一段上升后当前转降时做空。
