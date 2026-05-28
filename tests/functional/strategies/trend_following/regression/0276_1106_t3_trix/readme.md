# 1106 T3 TRIX

## 策略概述

该示例是对 MT5 EA `1106_Exp_T3_TRIX` 的 Backtrader 迁移版本。
当前版本沿用仓库标准验证数据 `XAUUSD_M15.csv`，复刻原始 EA 的三种信号模式：`breakdown`、`twist`、`cloudtwist`。

## 核心逻辑

1. 使用两条不同周期的 `T3` 平滑序列构造快线与慢线
2. 将两条 T3 序列分别转换为单周期变化率，得到 `TRIX` 风格快线与慢线
3. `breakdown`：快线穿越零轴时触发反转信号
4. `twist`：快线方向发生拐点变化时触发反转信号
5. `cloudtwist`：快线与慢线交叉时触发反转信号
6. 下单后附加固定 `SL / TP`
7. 出现反向信号时先平仓，再按原始 EA 的双向逻辑反手

## 主要参数

- `mode`
- `signal_bar`
- `xlength1`
- `xlength2`
- `xphase`
- `stop_loss_points`
- `take_profit_points`
- `lot`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- 原始 MT5 版本依赖 `SmoothAlgorithms.mqh` 中的 `XMA`/`T3` 平滑算法，本示例在 Backtrader 中直接重写为标准 `Tillson T3` 形式
- 原始 `XPhase=70` 在本迁移中映射为 `T3 volume factor = 0.7`
- MT5 指标缓冲区中的 `UpBuffer / DnBuffer / IndBuffer`，在本实现中对应 `fast / slow / hist`
- 原 EA 的交易执行依赖 `TradeAlgorithms.mqh`，本示例按其公开信号路径复刻为 Backtrader 的开平仓流程
