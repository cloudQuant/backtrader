# 0592 两个iMA的交叉

## 策略概述

该策略是对 MT5 EA `0592_两个iMA的交叉` 的 Backtrader 迁移版本。

- 双均线交叉为主信号
- 第三条均线可选作方向过滤
- 支持市场单、止损挂单、限价挂单三种入场模式
- 固定 `SL/TP` 与 trailing stop

## 核心逻辑

1. 第一条均线向上穿越第二条均线时做多，向下穿越时做空。
2. 也保留原 EA 的“2-bar 回看交叉”补充检测。
3. `filter_ma=true` 时，买入要求 `MA3 < MA1`，卖出要求 `MA3 > MA1`。
4. `price_level`:
   - `0`：市场单
   - `<0`：Stop 挂单
   - `>0`：Limit 挂单
5. 持仓后按固定 `SL/TP` 和 trailing stop 管理。

## 迁移说明

- 原 EA 通过 `iCustom("Custom Moving Average Input Color")` 计算三条均线；迁移版直接映射到 Backtrader 原生 MA 指标。
- 原版支持按风险自动算手数；迁移版简化为固定手数。

## 运行方式

```bash
python run.py
```
