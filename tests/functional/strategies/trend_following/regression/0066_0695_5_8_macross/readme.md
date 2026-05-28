# 0695 5_8_MACross

## 策略概述

该策略是对 MT5 EA `0695_5_8_MACross` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 使用 `5/8` 双均线交叉作为做多/做空触发
- 反向信号出现时先平掉旧方向仓位
- 开仓后使用固定 `SL/TP`，并可选对净头寸启用 trailing stop

## 核心逻辑

1. 计算快线 `EMA(5)` 与慢线 `EMA(8)`，分别保留原源码中的 `shift` 与 `applied price` 参数位。
2. 若上一根完成 bar 上快线从下向上穿越慢线，则先平空，再开多。
3. 若上一根完成 bar 上快线从上向下穿越慢线，则先平多，再开空。
4. 开仓时按原 EA 参数设置固定 `SL/TP`。
5. 若启用 `TrailingStop`，则对当前净头寸持续抬升/下压保护止损。

## 主要参数

- `ma_fast_period`
- `ma_fast_shift`
- `ma_fast_method`
- `ma_fast_price`
- `ma_slow_period`
- `ma_slow_shift`
- `ma_slow_method`
- `ma_slow_price`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `lot`

## 对齐说明

- 原 EA 仅依赖平台内建 `iMA`，没有额外外部指标依赖，因此适合直接迁移。
- 原源码为 `hedging only`，并在反向交叉时先调用 `ClosePositions()` 再下新单；当前版本在 Backtrader 中通过“先平仓，再在下一次 `next()` 执行挂起的新信号”近似还原该时序。
- 原 trailing stop 会遍历同 magic 的全部持仓逐个修改；当前版本基于 Backtrader 净头寸模型，对聚合后的单一仓位做近似保护。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
