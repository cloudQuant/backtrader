# 0673 ExpBuySellSide

## 策略概述

该策略是对 MT5 EA `0673_ExpBuySellSide` 的 Backtrader 迁移版本。
当前实现重建了 EA 内部两部分核心判定：

- `ATRStops`
- `StepUpDown`

并保留其多周期组织方式：

- 基础执行周期使用样例 `M15`
- 在 Backtrader 中重采样出 `H1`
- 交易方向由 `ATRStops + StepUpDown` 共振决定
- 持仓按动态计算的 `SL/TP` 管理，可选 trailing stop

## 核心逻辑

1. 在 `H1` 上计算 `StepUpDown`：
   - `SMA(2, typical)`
   - `SMMA(30, median)`
   - 根据局部高低点顺序与快慢线差值变化判断方向
2. 在 `H1` 上计算 `ATRStops`：
   - 使用 `ATR(5)`
   - 在 `length=10` 的窗口内生成上下轨
   - 根据收盘价越过轨道后的状态翻转得到多空切换信号
3. 若 `ATRStops=1` 且 `StepUpDown=1`，则做多。
4. 若 `ATRStops=-1` 且 `StepUpDown=-1`，则做空。
5. 若启用 `close_by_opposite_signal`，遇到反向信号先平后反手。
6. 若未启用 trailing stop，则在 `StepUpDown` 反向且当前浮盈时主动平仓。

## 迁移说明

- 原 EA 通过 `OnTimer()` 每分钟轮询，并允许在 `CloseByOppositeSignal=No` 时保留对向仓位；迁移版在 Backtrader 净头寸框架下只保留单净仓行为。
- 原版风险距离依赖 MT5 合约参数与杠杆；迁移版保留计算结构，但默认配置使用固定手数，以便当前工作区稳定运行。
- `ATRStops` 与 `StepUpDown` 的核心判定均已在策略内直接重建，无外部指标依赖。

## 主要参数

- `risk_percentage`
- `tp_vs_sl_ratio`
- `money_management_type`
- `trade_lot_size`
- `close_by_opposite_signal`
- `use_trailing_stop`
- `atr_period`
- `atr_length`
- `atr_multiplier`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
