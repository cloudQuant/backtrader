# 0703 TDSGlobal

## 策略概述

该策略是对 MT5 EA `0703_TDSGlobal` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 日线 `MACD + OsMA` 判断方向
- `WPR` 判断触发区间
- 按前一根 bar 高低点放置突破挂单
- 成交后使用固定 `TP` 与可选 trailing

## 核心逻辑

1. 用日线 `MACD` 与 `OsMA` 的变化方向确定多空倾向。
2. 当 `WPR` 进入超卖/超买区域时允许触发。
3. 在前一根 bar 高点上方或低点下方放置突破触发位。
4. 挂单成交后按 `TP` 与 trailing 管理。

## 迁移说明

- 原 EA 使用真实 `BuyStop/SellStop` 挂单；迁移版使用内部触发价近似模拟。
- 重点保留其 Triple Screen 风格的多周期方向过滤与突破执行路径。

## 主要参数

- `take_profit`
- `stoploss`
- `trailing_stop`
- `williams_l`
- `williams_h`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
