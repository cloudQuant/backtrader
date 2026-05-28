# 1242 BullsBearsEyes

## 策略概述

该策略是对 MT5 EA `1242_Exp_BullsBearsEyes` 的 Backtrader 迁移版本。
原 EA 直接读取 `ColorBullsBearsEyes` 指标的 `SignBuffer`，并依据 `±1/±2` 信号执行平仓或反手开仓。

## 核心逻辑

1. 将 `M15` 数据重采样到指标周期 `H4`
2. 基于 `EMA(period)` 计算 `BullsPower = high - EMA` 与 `BearsPower = low - EMA`
3. 按原指标中的四级递推滤波公式生成 `BullsBearsEyes` 数值
4. 依据 `mode` 与 `high/middle/low` 水平生成颜色状态
5. 再按原始 `SignBuffer` 规则编码成 `-2/-1/+1/+2`
6. EA 规则中 `+2/-2` 表示开仓反转，`+1/-1` 表示仅维持方向并触发对向平仓

## 主要参数

- `indicator_minutes`
- `period`
- `gamma`
- `mode`
- `high_level`
- `middle_level`
- `low_level`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 说明

默认配置对应原 EA 的 `Mode=breakdown2`。
如果后续要复刻其它模式，可直接在 `config.yaml` 中修改 `mode` 为 `0/1/2/3`。
