# 0639 Exp_CGOscillator_X2

## 策略概述

该策略是对 MT5 EA `0639_Exp_CGOscillator_X2` 的 Backtrader 迁移版本。

- 双时间框架 `CG Oscillator` 过滤与触发
- 慢周期 `CG/main` 与 `Trigger` 的相对位置决定趋势方向
- 快周期交叉负责入场，可选按快/慢信号平仓
- 固定 `SL/TP`，单净仓

## 核心逻辑

1. 在慢周期上，`CG main > Trigger` 视为多头趋势，`CG main < Trigger` 视为空头趋势。
2. 在快周期上，若空头趋势中 `CG main` 自上向下穿越 `Trigger`，则做空。
3. 在快周期上，若多头趋势中 `CG main` 自下向上穿越 `Trigger`，则做多。
4. 若启用相应关闭选项，则可按快周期反向状态或慢周期趋势翻转平仓。
5. 若持有反向仓位且出现新信号，则先平掉旧仓再按新方向重入。

## 迁移说明

- 原 EA 依赖 `TradeAlgorithms.mqh` 与 `Money Management` 头寸规模计算；迁移版简化为固定 `lots`。
- 原 EA 使用 `CGOscillator` 自定义指标；迁移版在 Python 中按源码公式实现：
  `CG = -sum((1+i)*median_price[i]) / sum(median_price[i]) + (Length+1)/2`，`Trigger = CG[-1]`。
- 示例直接从 `M15` 源数据重采样出快周期 `M30` 与慢周期 `H6`，与原 EA 的双时间框架结构保持一致。

## 主要参数

- `length_slow` / `length_fast`
- `signal_bar` / `signal_bar_fast`
- `buy_pos_open` / `sell_pos_open`
- `buy_pos_close` / `sell_pos_close`
- `buy_pos_close_fast` / `sell_pos_close_fast`
- `stop_loss` / `take_profit`
- `lots`

## 运行方式

```bash
python run.py
```
