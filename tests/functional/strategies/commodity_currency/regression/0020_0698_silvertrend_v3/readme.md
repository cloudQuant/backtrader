# 0698 SilverTrend_v3

## 策略概述

该策略是对 MT5 EA `0698_SilverTrend_v3` 的 Backtrader 迁移版本。
当前版本保留了原 EA 的主干结构：

- 使用 `SilverTrend` 方向翻转作为主信号
- 使用 `J_TPO` 的正负号作为方向过滤
- 反向信号时平掉已有仓位
- 使用固定 `TakeProfit` 与可选初始止损、移动止损
- 保留周五晚间禁止开新仓的时间过滤

## 核心逻辑

1. 在 `M15` 数据上计算 `SilverTrend` 方向状态。
2. 仅当方向发生翻转且 `J_TPO` 符号一致时，才允许开新仓。
3. 当方向转为多头时，平掉空单；当方向转为空头时，平掉多单。
4. 新开仓使用固定 `TakeProfit`，并按价格推进维护 `TrailingStop`。
5. 周五超过 `FridayNightHour` 后不再开新仓。

## 主要参数

- `risk`
- `jtpo_period`
- `trailing_stop`
- `take_profit`
- `initial_stop_loss`
- `friday_night_hour`

## 对齐说明

- 原 EA 中 `SilverTrendSignal()` 与 `J_TPO(14)` 的组合负责给出方向翻转和过滤；当前版本分别以本地 `SilverTrend` 代理和趋势振荡代理复刻其 bar 级语义。
- 原 EA 使用 MT5 持仓接口逐笔修改止损；当前版本在 Backtrader 中用单净头寸和价格阈值近似移动止损逻辑。
- 当前实现按仓库统一示例约定固定 `size=0.1`，未复刻更复杂的经纪商成交细节。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
