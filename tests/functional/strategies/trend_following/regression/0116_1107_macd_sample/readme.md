# 1107 MACD Sample

## 策略概述

该策略是对 MT5 EA `1107_MACD_样本` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为 `MACD` 交叉结合 `EMA(26)` 趋势过滤。

## 核心逻辑

1. 计算 `MACD(12, 26, 9)` 主线与信号线
2. 计算 `EMA(26)` 作为趋势过滤
3. 做多条件：`MACD` 在零轴下方向上穿越信号线，且 `EMA` 向上
4. 做空条件：`MACD` 在零轴上方向下穿越信号线，且 `EMA` 向下
5. 平仓条件：出现满足阈值的反向 `MACD` 交叉
6. 持仓保护：固定 `TP` + 动态 trailing stop

## 主要参数

- `lots`
- `take_profit_pips`
- `trailing_stop_pips`
- `macd_open_level_pips`
- `macd_close_level_pips`
- `ma_trend_period`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 迁移说明

- MT5 原版使用标准 `MACD` 与 `EMA` 指标，无需依赖外部自定义 `.ex5`
- Backtrader 版本保留了原始 EA 的入场阈值、平仓阈值、固定止盈与 trailing stop 主流程
- MT5 中 `pips` 通过 `digits_adjust` 换算，本版本使用 `point` 与 `price_digits` 进行等价映射
