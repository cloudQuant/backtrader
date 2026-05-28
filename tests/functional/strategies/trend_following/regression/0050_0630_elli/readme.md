# 0630 Elli

## 策略概述

该策略是对 MT5 EA `0630_Elli` 的 Backtrader 迁移版本。

- ADX Wilder 方向突变 + Ichimoku 多层趋势确认
- 固定 SL/TP，单仓

## 核心逻辑

1. Ichimoku 条件：`ts > ks > sa > sb` 且 `close > ks` → 看多排列。
2. ADX +DI 从 `convert_low` 以下跳至 `convert_high` 以上 → 动能突变。
3. `|ts - ks|` > `po` 点 → 趋势强度足够。
4. 三者同时满足 → 做多。做空为完全镜像条件。

## 迁移说明

- 原 EA 使用 `CMoneyFixedRisk` 手数管理；迁移版简化为固定手数。
- 原 EA ADX 使用 M1 时段，Ichimoku 使用 H1 时段；迁移版在同一数据流上运行。

## 主要参数

- `tenkan` / `kijun` / `senkou_b` / `po`
- `adx_period` / `convert_high` / `convert_low`
- `stop_loss` / `take_profit`

## 运行方式

```bash
python run.py
```
