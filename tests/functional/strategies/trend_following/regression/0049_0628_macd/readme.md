# 0628 MACD

## 策略概述

该策略是对 MT5 EA `0628_MACD` 的 Backtrader 迁移版本。

- MACD 柱状图"趋势延续"形态
- 固定 SL/TP，单仓

## 核心逻辑

1. **买入**: MACD 柱状图峰值超过 `+peak_threshold` → 回落至 `+dip_threshold` 以下 → 反弹出现局部谷底越过 `+dip_threshold` 且保持在零线以上 → 做多。
2. **卖出**: 镜像逻辑，柱状图在零线以下完成相同模式 → 做空。
3. 柱状图穿越零线时重置对应方向的状态机。

## 迁移说明

- 原 EA 固定 0.1 手；迁移版保持可配置。
- 原 EA 阈值针对 EURUSD H1 的典型 MACD 值设计；应用于 XAUUSD M15 时需调整阈值。

## 主要参数

- `macd_fast` / `macd_slow` / `macd_signal`
- `peak_threshold` / `dip_threshold`
- `stop_loss` / `take_profit`

## 运行方式

```bash
python run.py
```
