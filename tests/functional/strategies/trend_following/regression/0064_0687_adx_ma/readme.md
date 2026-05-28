# 0687 ADX_&_MA

## 策略概述

该策略是对 MT5 EA `0687_ADX_&_MA` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主结构：

- `SMMA(Median Price)` 作为趋势基准线
- `ADX` 强度过滤
- 价格上穿/下穿均线时开仓
- 持仓后若再次跌破/升破均线则平仓
- 多空独立的 `SL/TP/TrailingStop`

## 核心逻辑

1. 计算 `SMMA(PRICE_MEDIAN, per_MA)`。
2. 计算 `ADX(per_ADX)`。
3. 若 `close[1] > MA[1]` 且 `close[2] < MA[2]` 且 `ADX[1] > porog_adx`，则开多。
4. 若 `close[1] < MA[1]` 且 `close[2] > MA[2]` 且 `ADX[1] > porog_adx`，则开空。
5. 多单在 `close[1] < MA[1]` 时平仓；空单在 `close[1] > MA[1]` 时平仓。
6. 其余风险管理按多空各自参数执行。

## 主要参数

- `per_ma`
- `per_adx`
- `porog_adx`
- `take_profit_buy`
- `stop_loss_buy`
- `trailing_stop_buy`
- `take_profit_sell`
- `stop_loss_sell`
- `trailing_stop_sell`
- `lots`

## 对齐说明

- 原 EA 仅依赖 MT5 内建 `MA` 与 `ADX` 指标，没有外部依赖，因此适合直接迁移。
- 原源码虽声明 `hedging only`，但策略本体是标准单方向独立持仓管理；当前 Backtrader 版本以净头寸方式做稳定近似。
- 原卖出分支源码实际仍使用了 `StopLoss_Buy/TakeProfit_Buy` 参数下单；当前迁移版本按参数命名语义使用独立的 `sell` 风控参数，以避免把明显的源码笔误继续带入 Python 版本。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
