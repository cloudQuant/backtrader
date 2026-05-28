# 0759 CrossMA

## 策略概述

该策略是对 MT5 EA `0759_CrossMA` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心行为：

- 用两条 `SMA` 的交叉作为开平仓触发
- 使用 `ATR` 作为动态止损距离
- 通过账户资金比例估算下单手数
- 连续亏损时按 `DecreaseFactor` 递减手数

## 核心逻辑

1. 计算慢均线 `MA1_Period=12` 与快均线 `MA2_Period=4`。
2. 当快线从上向下穿越慢线时开空，并把止损放在 `close + ATR`。
3. 当快线从下向上穿越慢线时开多，并把止损放在 `close - ATR`。
4. 若持有多单时出现做空交叉，则平掉多单；持有空单时出现做多交叉，则平掉空单。
5. 下单手数按 `free_margin * MaximumRisk / 1000` 估算；若连续亏损大于 1 次，则按 `DecreaseFactor` 递减。

## 主要参数

- `maximum_risk`
- `decrease_factor`
- `ma1_period`
- `ma2_period`
- `atr_period`

## 对齐说明

- 原 EA 会发送邮件通知；当前 Backtrader 迁移不包含邮件发送。
- 原 EA 用 `iTickVolume(0)>1` 限制为新 bar 才触发；当前实现天然在 `next()` 的 bar 级节奏下运行。
- 原代码中的 `InpLots` 更像兜底参数，主要手数仍由 `LotsOptimized()` 决定；当前实现保留这一主逻辑。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
