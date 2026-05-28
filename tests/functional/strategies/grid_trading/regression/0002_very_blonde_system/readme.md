# 0745 Very Blonde System

## 策略概述

该策略是对 MT5 EA `0745_Very_Blonde_System` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 检查最近 `CountBars` 根的价格极值范围
- 出现足够大的单边变动后逆势首仓
- 再按 `Grid` 间距布设 4 层同向限价网格
- 当总浮盈达到 `Amount` 时平掉全部持仓并取消挂单
- 可选 `LockDown` 在达到一定盈利后把止损锁到开仓价附近

## 核心逻辑

1. 统计最近 `CountBars` 根的最高价和最低价。
2. 若 `highest - current_price > limit`，说明价格快速回落，逆势做多并向下布置加仓买限价单。
3. 若 `current_price - lowest > limit`，说明价格快速上冲，逆势做空并向上布置加仓卖限价单。
4. 网格层数固定 4 层，手数按 `1x/2x/4x/8x/16x` 递增。
5. 当总浮盈达到 `Amount` 时，执行篮子平仓并删除剩余挂单。

## 主要参数

- `count_bars`
- `limit_points`
- `grid_points`
- `amount`
- `lockdown`

## 对齐说明

- 原 EA 使用市价首仓 + 4 层 `BuyLimit/SellLimit` 网格；当前迁移保持同样结构。
- 原实现按账户余额粗略推导基础手数，当前版本保留同类近似。
- 原作者明确提示这是高风险思路；迁移版仅做结构复现，不表示策略有效性或实盘适用性。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
