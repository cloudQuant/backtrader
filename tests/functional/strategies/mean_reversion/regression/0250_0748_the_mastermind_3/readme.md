# 0748 大师观念 3

## 策略概述

该策略是对 MT5 EA `0748_大师观念_3` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主结构：

- 同时监控 4 组不同周期的 `Williams %R`
- 4 条 `%R` 全部处于极端超卖时做多
- 4 条 `%R` 全部处于极端超买时做空
- 反向极值信号平仓，并保留 `BreakEven / TrailingStop`

## 核心逻辑

1. 计算 `WPR(26/27/29/30)`。
2. 当四条 `%R` 全部 `< -99.99` 时产生买入信号。
3. 当四条 `%R` 全部 `> -0.01` 时产生卖出信号。
4. 若持有反向仓位，则在新反向信号下平仓。
5. 若开启 `BreakEven / TrailingStop`，则按原家族逻辑对止损进行移动。

## 主要参数

- `lots`
- `stop_loss`
- `take_profit`
- `trade_at_close_bar`
- `trailing_stop`
- `trailing_step`
- `break_even`

## 对齐说明

- 该 EA 和 `0750 大师观念` 属于同一风格，差别主要在入场信号源。
- 原实现把 `ExtTrailingStep` 直接赋成了 `InpTrailingStop`；当前迁移按参数语义保留 `trailing_step` 独立含义。
- 当前版本省略了图表文字、声音、日志等附属输出。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
