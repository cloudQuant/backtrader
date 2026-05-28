# 1216 Beginner

## 策略概述

该策略是对 MT5 EA `1216_Exp_Beginner` 的 Backtrader 迁移版本。
原 EA 使用 `Beginner` 指标的买卖箭头作为开仓信号，并会向后扫描历史箭头来决定反向持仓平仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 计算 `Per` 区间最高/最低价
3. 计算 `Otstup` 触发带与平均波动范围
4. 生成 `BuyBuffer / SellBuffer`
5. 当前 bar 出现箭头则开仓；若当前无直接平仓信号，则向后搜索最近反向箭头决定平仓

## 主要参数

- `indicator_minutes`
- `otstup`
- `per`
- `atr_period`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

原指标源码明确标注 `Repaints`。
本迁移版按其当前 buffer 规则做等价实现，不额外修正该特性。
