# 0766 Expert NEWS

## 策略概述

该策略是对 MT5 EA `0766_Expert_NEWS` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的三层核心行为：

- 在当前价格上下固定距离维护 `BuyStop / SellStop` 双向挂单
- 挂单触发后按固定 `SL/TP` 入场
- 持仓过程中根据盈利距离执行 `breakeven` 与 `trailing stop`

## 核心逻辑

1. 若当前没有多头持仓，则在现价上方 `InpStep` 处维护一个虚拟 `buy_stop`；若没有空头持仓，则在现价下方维护 `sell_stop`。
2. 当价格穿越对应 stop 位时，挂单转为市价单入场。
3. 若持仓盈利达到 `InpNoLoss`，则把止损推到开仓价附近的 `MinProfitNoLoss` 位置。
4. 若盈利达到 `InpTrailingStart`，则按 `InpTrailingStop` 和 `InpStepTrall` 递推移动止损。
5. 挂单价格仅在距离发生足够变化且经过 `TimeModify` 后才更新，近似原 EA 的“禁止过于频繁修改订单”约束。

## 主要参数

- `stoploss`
- `takeprofit`
- `trailing_stop`
- `trailing_start`
- `step_trail`
- `no_loss`
- `min_profit_no_loss`
- `step`
- `time_modify_seconds`

## 对齐说明

- 原 EA 实际使用 MT5 服务器端挂单与修改挂单；当前版本在 Backtrader 中用“虚拟挂单状态 + 价格穿越触发”近似。
- 原 EA 可同时存在反向挂单与当前持仓；当前版本在净头寸框架下做单向持仓近似，反向触发时先平后反手。
- 原 EA 的 `STOPLEVEL` 与实时报价 `Bid/Ask` 约束在 bar 级环境中无法逐 tick 等价复现，因此这里采用参数化近似。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
