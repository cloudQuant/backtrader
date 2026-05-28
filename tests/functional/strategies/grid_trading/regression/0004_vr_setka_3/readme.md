# 0767 VR---SETKA---3

## 策略概述

该策略是对 MT5 EA `0767_VR---SETKA---3` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 按当日最高/最低价的百分比位置判断首单触发
- 逆势方向按 `Distanciya + StepDist * n` 距离继续做网格加仓
- 单仓使用固定 `TakeProfit`，多仓使用加权均价 `± Plus` 做篮子退出
- 可选 `Martin=true` 时按当前仓层数放大下一笔手数

## 核心逻辑

1. 维护当日内滚动 `day_high/day_low`。
2. 若当前价格距离 `day_high` 不超过 `Procent%`，且上一根 K 线为阳线，则触发 `sigup`。
3. 若当前价格距离 `day_low` 不超过 `Procent%`，且上一根 K 线为阴线，则触发 `sigdw`。
4. 空仓时按 `sigup/sigdw` 开第一笔。
5. 持有多单时，若当前价低于最低买入价 `Distanciya + StepDist * n`，则继续加多；持有空单时则对称加空。
6. 单笔仓位目标价为 `entry ± (spread + TakeProfit)`；多笔仓位目标价为加权均价 `± Plus`。

## 主要参数

- `plus_points`
- `take_profit_points`
- `distance_points`
- `step_distance_points`
- `lots`
- `percent`
- `martin`
- `proc`
- `procent`
- `spread_points`

## 对齐说明

- 原 EA 用实时报价里的 `Spread`、`OrderCalcMargin` 和账户可用保证金动态计算；当前版本把点差和单手保证金改为可配置近似参数。
- 原 EA 通过多笔独立仓位的 `TakeProfit` 实现整篮子退出；当前版本用 `layers` 账本在 Backtrader 净头寸框架下近似同样行为。
- 当前版本仍是单品种、同向单篮子实现，不支持 MT5 端的真实对冲持仓模式。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
