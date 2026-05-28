# 1074 Exp_BlauSMStochastic

## 策略概述

该示例是 MT5 EA `1074_Exp_BlauSMStochastic` 的 Backtrader 迁移版本。
EA 基于 `BlauSMStochastic` 振荡器，支持三种入场模式：直方图过零、直方图拐头、以及信号云翻色。

## 原始信号逻辑

EA 暴露三种 `Mode`：

- `breakdown`：直方图 `Hist` 上穿/下破零轴时入场
- `twist`：直方图方向发生拐点时入场
- `cloudtwist`：主线 `Up` 与信号线 `Dn` 的云层颜色改变时入场

默认模式为 `twist`，即：

- 若 `Hist[1] < Hist[2]` 且 `Hist[0] > Hist[1]`，则开多并平空
- 若 `Hist[1] > Hist[2]` 且 `Hist[0] < Hist[1]`，则开空并平多

## 指标迁移说明

`BlauSMStochastic` 按原公式计算：

- 在 `XLength` 窗口上求最高/最低价
- 计算 `sm = price - 0.5 * (LL + HH)`
- 计算 `half = 0.5 * (HH - LL)`
- 对 `sm` 和 `half` 分别做三次平滑
- 主振荡值 `Hist = 100 * xxxsm / xxxhalf`
- 信号线 `Dn` 为 `Hist` 的再次平滑，`Up = Hist`

默认参数：

- `XMA_Method = MODE_EMA`
- `XLength = 5`
- `XLength1 = 20`
- `XLength2 = 5`
- `XLength3 = 3`
- `XLength4 = 3`
- `IPC = PRICE_CLOSE`
- `Mode = twist`
- 信号周期：`H4`

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H4`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 回测结果

- 样本区间：`2025-12-03 01:15:00` - `2026-03-10 09:00:00`
- 成交笔数：`26`
- 净收益：`-4304.40`
- 胜率：`46.15%`
- 最大回撤：`7.53%`
