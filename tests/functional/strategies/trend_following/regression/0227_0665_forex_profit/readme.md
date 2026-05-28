# 0665 Forex Profit

## 策略概述

该策略是对 MT5 EA `0665_Forex_Profit(外汇交易利润)` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- `EMA10 / EMA25 / EMA50`
- `Parabolic SAR` 方向过滤
- 买卖使用不同 `SL/TP`
- `EMA10` 拐头且已有最小利润时平仓
- trailing stop

## 核心逻辑

1. 使用 `PRICE_MEDIAN` 计算 `EMA10 / EMA25 / EMA50`。
2. 买入条件：
   - `EMA10 > EMA25`
   - `EMA10 > EMA50`
   - 前一根 `EMA10 <= EMA50`
   - `SAR < 前一根收盘价`
3. 卖出条件与之对称。
4. 多单若 `EMA10` 开始下拐且浮盈超过阈值，则平仓。
5. 空单若 `EMA10` 开始上拐且浮盈超过阈值，则平仓。
6. 买卖分别使用不同 `SL/TP` 与 trailing 参数。

## 迁移说明

- 原 EA 要求对冲账户，但实际交易逻辑是单仓风格；迁移版按单净仓实现。
- 原源码里 `ExtTrailingStop` 被赋值为 `InpTrailingStop1`，迁移版按买卖分离参数显式表达，避免原实现中的参数歧义。
- 示例使用 `XAUUSD_M15.csv` 并按 `H1` 压缩运行，以适配当前工作区可用数据文件。

## 主要参数

- `take_profit_buy`
- `take_profit_sell`
- `stop_loss_buy`
- `stop_loss_sell`
- `trailing_stop_buy`
- `trailing_stop_sell`
- `trailing_step`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与首版可运行脚手架已建立。
- 待后续补做本地回测校验，再同步台账中的验证结果。
