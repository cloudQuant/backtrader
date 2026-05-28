# 0696 Kijun_Sen_Robot

## 策略概述

该策略是对 MT5 EA `0696_Kijun_Sen_Robot` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 以 `Ichimoku Kijun-sen` 穿越作为候选触发
- 用 `EMA20` 方向与 `Kijun` 相对均线的距离做过滤
- 仅允许单仓位运行，并在盈利后推进 `BreakEven` 与 `Trailing Stop`

## 核心逻辑

1. 计算 `Ichimoku(6, 12, 24)` 的 `Kijun-sen` 线。
2. 当当前 bar 从下向上穿越 `Kijun`，且 `Kijun` 不低于两根前的值，同时 `EMA20` 低于 `Kijun - MAFilter` 时，记录多头候选交叉。
3. 当当前 bar 从上向下穿越 `Kijun`，且 `Kijun` 不高于两根前的值，同时 `EMA20` 高于 `Kijun + MAFilter` 时，记录空头候选交叉。
4. 只有在 `EMA20` 当前斜率与候选方向一致时才真正入场；原 EA 的 `limit / market` 分流在当前版本中按 bar 级成交做近似。
5. 持仓后使用固定 `SL/TP`，盈利达到 `BreakEven` 后将止损推到开仓价附近，并继续按 `Trailing Stop` 推进；若新 bar 上 `EMA20` 反向且尚未到保本，则提前平仓。

## 主要参数

- `tenkan`
- `kijun`
- `senkou`
- `ma_period`
- `take_profit_pips`
- `stop_loss_pips`
- `break_even_pips`
- `trailing_stop_pips`
- `ma_filter_pips`
- `day_start_hour`
- `day_end_hour`

## 对齐说明

- 原 EA 仅依赖平台内建 `iIchimoku / iMA / iSAR`，不需要额外 `.ex5` 指标，因此适合直接迁移到 Backtrader。
- 原 EA 会根据当前价相对目标 `Kijun` 入场位的偏离，决定使用 `BUY_LIMIT/SELL_LIMIT` 或市价单；当前版本在 bar 级回测中将其近似为统一即时成交，并在日志中保留 `limit_approx` 标记。
- 原源码中 `PSAR` 句柄被创建但实验性退出逻辑未真正启用；当前迁移版本同样仅保留 `EMA` 反向提前平仓、`BreakEven` 与 trailing 管理。
- 原源码中 `UseOptimizedValues` 只给 `GBPUSD/EURUSD` 写死了一组优化参数；当前 `XAUUSD` 样例默认关闭该分支，优先使用配置文件参数。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
