# 0694 10pipsOnceADayOppositeLastNHourTrend

## 策略概述

该策略是对 MT5 EA `0694_10pipsOnceADayOppositeLastNHourTrend` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主结构：

- 每天固定 `TRADINGHOUR` 只尝试开一次单
- 用“过去 `N` 小时方向”的**反向**作为当天入场方向
- 持仓超过 `POSMAXAGE` 自动平仓
- 最近连续亏损时按配置倍数放大下一笔手数

## 核心逻辑

1. 维护按小时更新的收盘价序列。
2. 到达设定 `TRADINGHOUR` 且当小时只触发一次时，比较 `N` 小时前收盘与上一小时收盘。
3. 若过去 `N` 小时整体下跌，则做多；若整体上涨，则做空。
4. 开仓后使用固定 `SL/TP`，并可选启用 trailing stop。
5. 若持仓存活时间超过 `POSMAXAGE` 秒，则主动平仓。
6. 若最近连续平仓为亏损，则按 `FIRST...FIFTH MULTIPLICATOR` 递增下一笔手数；遇到最近一次盈利则停止继续放大。

## 主要参数

- `fix_lot`
- `maximum_risk`
- `trading_hour`
- `hours_to_check_trend`
- `pos_max_age_seconds`
- `first_multiplicator` ~ `fifth_multiplicator`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`

## 对齐说明

- 原 EA 为 `hedging only`，但同一时间仅允许 `MAXPOS=1`，因此可以在 Backtrader 净头寸模型下做近似迁移。
- 原策略在小时开盘的第一个 tick 上才允许开仓；当前版本在 `M15` bar 级回测里以“整点 bar”近似该时序。
- 原 `GetLots()` 基于最近历史平仓结果做最多 5 层连续亏损倍数递增；当前版本用 Backtrader 已关闭交易的 `pnlcomm` 序列近似重建。
- 原 trailing stop 逻辑对空头分支存在明显可疑条件表达式；当前迁移版本按对称 trailing 语义进行稳定化处理。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
