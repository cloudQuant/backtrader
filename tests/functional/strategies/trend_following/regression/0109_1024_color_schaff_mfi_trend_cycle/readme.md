# 1024 Exp_ColorSchaffMFITrendCycle

## 策略概述

该示例是对 MT5 EA `1024_Exp_ColorSchaffMFITrendCycle` 的 Backtrader 迁移版本。
EA 在 `H1` 周期上计算 `Schaff MFI Trend Cycle`，并依据颜色缓冲区从极强多头区或极强空头区回落时的状态变化来执行开平仓。

## 原始信号逻辑

1. 计算快慢两组 `MFI`
2. 用 `fastMFI - slowMFI` 构造内部 `MACD`
3. 对该序列进行两段 `Cycle` 窗口归一化与 `Factor=0.5` 递推平滑，得到 `STC`
4. 按 `HighLevel=60` 与 `LowLevel=-60` 以及当前斜率把颜色缓冲区映射到 `0..7`
5. EA 在柱线收盘时读取颜色缓冲区：
   - 上一颜色 `> 5` 且当前颜色 `< 6` 触发买入
   - 上一颜色 `< 2` 且当前颜色 `> 1` 触发卖出

## 指标迁移说明

- 指标仅依赖内置 `MFI` 与源码公开的 `Schaff Trend Cycle` 递推公式，可在 Python 中本地重建
- 保留默认 `H1` 信号周期与固定 `SL/TP`
- 保留颜色缓冲区的 8 档离散映射与 EA 对颜色码的触发判定

## 数据与运行

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 信号周期：`H1`
- 运行：`python run.py`
- 绘图：`python run.py --plot`
