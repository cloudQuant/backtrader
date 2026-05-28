# 1222 ColorStochNR

## 策略概述

该策略是对 MT5 EA `1222_Exp_ColorStochNR` 的 Backtrader 迁移版本。
原 EA 使用 `ColorStochNR` 振荡器，并依据 `mode` 在 5 种信号生成方式之间切换。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 重建降噪随机振荡器主线
3. 计算 `SIGN` 信号线以及主线/信号线颜色状态
4. 按 `mode` 执行 50 轴突破、振荡器方向扭转、信号线扭转、主线对信号线相对位置、信号线突破 50 轴 等交易规则

## 主要参数

- `mode`
- `indicator_minutes`
- `kperiod`
- `dperiod`
- `slowing`
- `dmethod`
- `price_field`
- `sens_points`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

本迁移版优先对齐原 EA 默认配置 `mode=OscDisposition`，
并保留其余四种模式的等价判定逻辑。
