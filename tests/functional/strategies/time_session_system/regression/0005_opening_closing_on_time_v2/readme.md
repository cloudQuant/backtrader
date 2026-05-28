# 0770 Opening and Closing on Time v2

## 策略概述

该策略是对 MT5 EA `0770_根据时间建仓和平仓，版本2` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 在指定 `HH:mm` 时间触发当日开仓逻辑
- 使用前一根已完成柱上的 `Fast MA / Slow MA` 相对位置决定开仓方向
- 在指定时间触发当日平仓逻辑
- 支持固定 `SL/TP`，并保持“一天只尝试一次开仓”的节奏

## 核心逻辑

1. 解析 `open_time` 与 `close_time`，在到达目标时间后的首根可用 bar 上触发。
2. 开仓时读取前一根已完成柱上的 `Fast MA` 与 `Slow MA`：若 `Fast > Slow` 则满足做多条件，若 `Fast < Slow` 则满足做空条件。
3. `trade_mode=buy` 时只允许做多，`trade_mode=sell` 时只允许做空，`trade_mode=buy_and_sell` 时按均线方向择边。
4. 当天一旦执行过开仓时刻判断，即使仓位随后被 `SL/TP` 提前平掉，也不会在同一天再次开仓，这对应原 EA 中的 `IF_POSITION_ALREADY_OPEN` 节奏控制。
5. 到达平仓时间后，若仍有持仓则全部平掉，并结束当日交易周期。

## 主要参数

- `open_time`
- `close_time`
- `lots`
- `stop_loss`
- `take_profit`
- `trade_mode`
- `fast_ma_period`
- `slow_ma_period`
- `fast_ma_method`
- `slow_ma_method`

## 对齐说明

- 原 EA 在 `OnTick()` 中用 `iMAGet(handle, 1)` 检查前一根柱的均线关系；当前版本保持使用前一根已完成 bar 的均线值。
- 原 EA 的 `buy_and_sell` 并不是同时双向开仓，而是在开仓时刻按均线方向择边；当前版本保留这一语义。
- 原 EA 使用服务器端 `SL/TP`；当前版本在 Backtrader 中按柱高低点近似触发。
- 原 EA 的 `IF_POSITION_ALREADY_OPEN` 更像“当日交易周期已进入”开关，而不仅是“当前确有持仓”；当前版本按相同节奏处理。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 由于本轮仍按无审批命令方式推进，尚未补做本地回测校验，因此建议台账先保留为 `实施中`，待后续补充结果后再改为 `已完成`。
