# 0691 抛光层

## 策略概述

该策略是对 MT5 EA `0691_抛光层` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主结构：

- 用 `EMA(9/45)` 和 `RSI` 判定当前方向
- 仅在方向成立时，等待 `Stochastic / DeMarker / WPR` 三个振荡器同步越过阈值再入场
- 单仓位运行，入场后使用固定 `SL/TP`

## 核心逻辑

1. 若 `EMA(9) > EMA(45)` 且 `RSI[1] > RSI[2]`，视为多头方向。
2. 若 `EMA(9) < EMA(45)` 且 `RSI[1] < RSI[2]`，视为空头方向。
3. 多头方向下，仅当 `Stochastic %K` 上穿 `19`、`DeMarker` 上穿 `0.35`、`WPR` 上穿 `-81` 时开多。
4. 空头方向下，仅当 `Stochastic %K` 下穿 `81`、`DeMarker` 下穿 `0.63`、`WPR` 下穿 `-19` 时开空。
5. 持仓使用固定 `SL/TP` 管理，不做加仓。

## 主要参数

- `ma_period_short`
- `ma_period_long`
- `ma_period_rsi`
- `k_period_stoch`
- `d_period_stoch`
- `slowing_stoch`
- `calc_period_wpr`
- `ma_period_demarker`
- `take_profit_pips`
- `stop_loss_pips`
- `lot`

## 对齐说明

- 原 EA 仅依赖平台内建 `EMA / RSI / Stochastic / WPR / DeMarker`，没有外部指标依赖，因此适合直接迁移。
- 原源码使用 `total==0` 限制同 magic 同品种只有一笔仓位；当前 Backtrader 版本与该单仓位语义一致。
- 原注释里曾保留 `Stochastic main/signal` 交叉判定的备选实现，但实际启用的是固定阈值越线；当前迁移版本按实际执行分支复刻。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
