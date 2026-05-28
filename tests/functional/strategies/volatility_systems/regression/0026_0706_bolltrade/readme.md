# 0706 BollTrade

## 策略概述

该策略是对 MT5 EA `0706_BollTrade` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 基于布林带上下轨的突破/极值入场
- 增加一个额外距离 `BDistance` 过滤
- 默认一次只保留一笔仓位
- 固定 `SL/TP`
- 可按账户增长放大基础手数

## 核心逻辑

1. 计算 `Bollinger Bands`。
2. 收盘价高于上轨并超过额外距离时做空。
3. 收盘价低于下轨并超过额外距离时做多。
4. 入场后按固定 `SL/TP` 管理。

## 迁移说明

- 原 EA 支持多仓统计和账户统计输出；迁移版聚焦交易逻辑本身。
- `LotIncrease` 在迁移版中保留为按当前净值相对初始净值缩放的近似实现。

## 主要参数

- `take_profit`
- `stop_loss`
- `bdistance`
- `bperiod`
- `deviation`
- `lot_increase`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
