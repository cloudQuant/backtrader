# 0676 ExpPricePosition

## 策略概述

该策略是对 MT5 EA `0676_ExpPricePosition` 的 Backtrader 首版迁移。
原 EA 基于 `PricePosition` 与 `StepUpDown` 两段内嵌逻辑产生方向信号，并结合 H1 K 线形态与相对日线收盘位置过滤入场。

## 核心逻辑

1. 在目标交易周期上计算：
   - `PricePosition`：`SMMA(26, median)` 与 `SMA(20, median)` 的中间信号线，以及最近一次穿越产生的方向价位。
   - `StepUpDown`：`SMA(2, typical)` 与 `SMMA(30, median)` 的相对结构判断趋势方向。
2. 同时读取上一根日线收盘价，构造 `pwr0 / pwr1` 过滤条件。
3. 当 `PricePosition`、`StepUpDown`、当前 H1 K 线实体方向、均线方向和 `pwr` 过滤一致时开仓。
4. 按风险百分比或固定手数确定仓位，并基于风险金额推导初始 `SL/TP`。
5. 若启用 trailing，则按固定 pips 推进 `SL/TP`；否则在已有盈利且 `StepUpDown` 反向时平仓。
6. 若启用 `close_by_opposite_signal`，收到反向信号时先平旧仓，再反向开仓。

## 主要参数

- `risk_percentage`
- `tp_vs_sl_ratio`
- `money_management_type`
- `trade_lot_size`
- `close_by_opposite_signal`
- `use_trailing_stop`
- `trailing_fixed_pips_sl`

## 对齐说明

- 原 EA 使用 H1 作为主交易周期，并同时读取日线收盘价做强弱过滤；当前版本通过从 M15 数据重采样得到 `H1` 与 `D1` 数据源来保持同类结构。
- 原 EA 的 `PricePosition` 和 `StepUpDown` 逻辑已按源码内嵌实现迁移，而不是用外部 `.ex5` 指标替代。
- 原 EA 带动态仓位、反向信号平仓与 trailing 止盈推进；当前版本保留同类语义，但仍需后续本地回测进一步校验数值贴合度。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`。
