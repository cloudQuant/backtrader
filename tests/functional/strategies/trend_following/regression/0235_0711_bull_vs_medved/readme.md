# 0711 Bull vs Medved

## 策略概述

该策略是对 MT5 EA `0711_Bull_vs_Medved` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 在固定 GMT 时点检查最近 K 线组合
- 满足形态后挂一笔 `BuyLimit` 或 `SellLimit`
- 挂单有效期 4 小时
- 成交后按固定 `SL/TP` 管理

## 核心逻辑

1. 到达设定时点时，检测最近几根 K 线组合。
2. `Bull / CoolBull` 命中时放置 `BuyLimit`。
3. `Bear` 命中时放置 `SellLimit`。
4. 若挂单在有效期内被价格触发，则进入持仓；过期则自动丢弃。

## 迁移说明

- 原 EA 使用真实限价挂单；迁移版以内部“挂单触发价 + 过期时间”模拟。
- 这能保留其主要的定时形态交易路径，同时保持 Backtrader 示例简洁可运行。

## 主要参数

- `candle_size`
- `stop_loss`
- `take_profit`
- `indent_up`
- `indent_down`
- `start_times`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
