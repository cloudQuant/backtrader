# 0676 ExpPricePosition

## 策略概述

该策略是对 MT5 EA `0676_ExpPricePosition` 的 Backtrader 迁移版本。
当前实现重建了 EA 内部的两部分核心判定：

- `PricePosition`
- `StepUpDown`

并保留了其多周期结构：

- 基础执行周期使用样例 `M15`
- 在 Backtrader 中重采样出 `H1` 与 `D1`
- 交易信号主要按 `H1 + D1` 条件组合决定
- 仓位按固定 `SL/TP` 或 trailing stop 管理

## 核心逻辑

1. 在 `H1` 上计算 `PricePosition`：
   - `SMMA(26, median)`
   - `SMA(20, median)`
   - 取两者均值形成信号中线
   - 搜索最近一次 K 线穿越该中线的位置，并据此判定当前价格方位
2. 在 `H1` 上计算 `StepUpDown`：
   - `SMA(2, typical)`
   - `SMMA(30, median)`
   - 根据局部高低点顺序及快慢线差值变化判断方向
3. 结合 `D1` 前一日收盘与 `H1` 当前/前一根收盘，构造 `power` 条件。
4. 若满足原 EA 的买入或卖出组合条件，则开仓。
5. 若启用 `close_by_opposite_signal`，遇到反向信号先平再反向开仓。
6. 若启用 `use_trailing_stop`，则按固定距离推移保护止损并同步扩展目标位。

## 迁移说明

- 原 EA 通过 `OnTimer()` 每分钟轮询，且允许在 `CloseByOppositeSignal=No` 时保留对向仓位；迁移版在 Backtrader 净头寸框架下只保留单净仓行为。
- 原 EA 的 `H1`/`D1` 数据是运行时按 MT5 时间序列函数抓取；迁移版改为从基础样例数据重采样得到。
- 原始风控距离与动态手数强依赖 MT5 合约参数；迁移版保留公式结构，但默认配置使用固定手数，便于在当前工作区稳定运行。

## 主要参数

- `risk_percentage`
- `tp_vs_sl_ratio`
- `money_management_type`
- `trade_lot_size`
- `close_by_opposite_signal`
- `use_trailing_stop`
- `trailing_fixed_pips_sl`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
