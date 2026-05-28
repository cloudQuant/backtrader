# 0774 Exp_Fishing

## 策略概述

该策略是对 MT5 EA `0774_Exp_Fishing` 的 Backtrader 迁移版本。
当前版本保留了原 EA 的核心结构：

- 以当前 K 线实体方向和实体长度阈值触发首笔开仓
- 仅在已有同向仓位存在时，按固定盈利间距递增加仓
- 每一层都带固定 `StopLoss / TakeProfit`
- 使用 `PosTotal` 限制最大加仓层数

## 核心逻辑

1. 当没有持仓时，若当前柱 `close - open` 大于 `PriceStep * point`，开多。
2. 当没有持仓时，若当前柱 `open - close` 大于 `PriceStep * point`，开空。
3. 当已有多头层时，若当前收盘价相对最近一层入场价盈利超过 `PriceStep * point`，继续加多。
4. 当已有空头层时，若当前收盘价相对最近一层入场价盈利超过 `PriceStep * point`，继续加空。
5. 每一层使用其自身入场价计算固定 `SL/TP`，在 bar 级回测中按当前柱高低点触发减仓/平仓。

## 主要参数

- `price_step`
- `pos_total`
- `stop_loss`
- `take_profit`
- `size`
- `point`

## 对齐说明

- 原 EA 的首单判定直接比较当前柱 `Close-Open` 与 `PriceStep*_Point`，当前版本保留这一语义。
- 原 EA 用注释字符串保存“加仓次数/最近成交价/最近手数”，并以最近一层价格作为下一次加仓的比较基准；当前版本用内存中的 `layers` 结构保存同等信息。
- 原 EA 在 MT5 净持仓模型上通过 `TradeAlgorithms.mqh` 管理多层同向仓位；当前版本在 Backtrader 中用分层账本近似，并按每层各自的 `SL/TP` 做部分减仓。
- 当前实现固定使用 `size=0.1` 近似 `MMMode=LOT` 的默认语义，尚未复刻动态资金管理分支。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录和可运行脚手架已建立。
- 尚未在本地完成一次无审批命令的回测校验，因此台账当前保留为 `实施中`。
- 待后续完成回测后，将把结果补入本说明并同步 `examples/readme_reverse.md` 为 `已完成`。
