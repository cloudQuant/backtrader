# 0772 Simple_FX

## 策略概述

该策略是对 MT5 EA `0772_Simple_FX` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 以短周期与长周期移动平均线的相对位置识别多空趋势
- 仅当趋势方向相对上一次已记录趋势发生切换时才发出新开仓信号
- 持仓期间若趋势反向，则先平掉原方向仓位
- 每笔持仓使用固定 `StopLoss / TakeProfit`

## 核心逻辑

1. 分别计算短周期 MA 与长周期 MA，默认参数为 `50/200 EMA`，价格类型为 `Median Price`。
2. 若最近两根柱上 `ShortMA > LongMA`，判定为多头趋势；若最近两根柱上 `ShortMA < LongMA`，判定为空头趋势。
3. 初始化阶段仅记录首个明确趋势方向，不立即开仓，这对应原 EA 中持久化的 `LastTrendDirection`。
4. 当没有持仓且趋势由空翻多时开多；当没有持仓且趋势由多翻空时开空。
5. 持仓后若柱内触发固定 `SL/TP`，则按 bar 级近似进行平仓；若趋势反向，则先平仓，等待下一次同方向确认后再重开。

## 主要参数

- `lots`
- `stop_loss`
- `take_profit`
- `short_ma_period`
- `long_ma_period`
- `short_ma_method`
- `long_ma_method`
- `short_ma_applied_price`
- `long_ma_applied_price`

## 对齐说明

- 原 EA 的 `TrendDetection()` 不是检测瞬时交叉，而是要求最近两根柱都满足 `ShortMA > LongMA` 或 `ShortMA < LongMA`；当前版本保留这一判定。
- 原 EA 使用文件保存 `LastTrendDirection`，以便在重新启动后避免重复开仓；当前版本在单次回测中用内存变量近似该状态机。
- 原 EA 通过服务器端 `SL/TP` 管理风控；当前版本在 Backtrader 中按柱高低点近似触发。
- 原 EA 限制最多只有一个方向仓位，当前版本同样保持单仓模式。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 由于本轮仍按无审批命令方式推进，尚未补做本地回测校验，因此建议台账先保留为 `实施中`，待后续补充结果后再改为 `已完成`。
