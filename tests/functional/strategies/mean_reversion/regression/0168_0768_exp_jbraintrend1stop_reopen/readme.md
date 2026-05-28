# 0768 Exp_JBrainTrend1Stop_ReOpen

## 策略概述

该策略是对 MT5 EA `0768_Exp_JBrainTrend1Stop_ReOpen` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的两个核心层次：

- 使用 `JBrainTrend1Stop` 指标颜色/方向翻转作为首单反手信号
- 在已有同向仓位盈利达到固定 `PriceStep` 后继续顺势加仓

## 核心逻辑

1. 将 `M15` 数据重采样到信号周期 `H4`，按本地 `jma.mq5 + jbraintrend1stop.mq5` 源码重建 `BuyStop / SellStop` 信号缓冲区。
2. 若当前 `UpTrend(BuyStop)` 有值且前一根 `DnTrend(SellStop)` 有值，则判定为做多翻转。
3. 若当前 `DnTrend(SellStop)` 有值且前一根 `UpTrend(BuyStop)` 有值，则判定为做空翻转。
4. 若已有多头层，且当前价格相对最近一层入场价盈利超过 `PriceStep * point * digits_adjust`，则继续加多。
5. 若已有空头层，且当前价格相对最近一层入场价盈利超过同样阈值，则继续加空。
6. 每一层用自身入场价维护固定 `SL/TP`，在 bar 级回测中按柱高低点近似触发减仓/平仓。

## 主要参数

- `signal_tf_minutes`
- `signal_bar`
- `price_step`
- `pos_total`
- `stop_loss`
- `take_profit`
- `atr_period`
- `sto_period`
- `ma_method`
- `length_`

## 对齐说明

- 原 EA 要求把 `JMA.ex5` 与 `JBrainTrend1Stop.ex5` 放到指标目录；当前版本直接依据仓库中的 `jma.mq5` 与 `jbraintrend1stop.mq5` 源码重建。
- 原 EA 通过注释字符串保存“加仓次数/最近价格/最近手数”；当前版本使用 `layers` 账本保存等价分层状态。
- 原 EA 使用 `TradeAlgorithms.mqh` 完成顺势加仓与反向平仓；当前版本在 Backtrader 中用分层净头寸近似。
- 当前实现固定使用 `size=0.1` 近似默认 `LOT` 语义，尚未复刻其更完整资金管理分支。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
