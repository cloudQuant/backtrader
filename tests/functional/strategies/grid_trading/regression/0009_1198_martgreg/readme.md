# 1198 MartGreg

## 策略概述

该策略是对 MT5 EA `1198_MartGreg` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心结构：

- 使用两组 MACD
- 第一组 MACD 识别局部拐点入场
- 第二组 MACD 用于趋势方向确认
- 单仓位运行
- 开仓后挂固定止损与止盈
- 按连续亏损次数做有限 martingale 加仓

## 核心逻辑

1. 计算两组基于 `PRICE_MEDIAN` 近似的 MACD 主线
2. 当第一组 MACD 形成局部低点，且第二组 MACD 走强时做多
3. 当第一组 MACD 形成局部高点，且第二组 MACD 走弱时做空
4. 开仓后设置固定止损 `stop_points` 与止盈 `take_points`
5. 若上一笔交易亏损，则下一笔按 `2^loss_streak` 放大手数，最高不超过 `doubling_count`

## 主要参数

- `dml`
- `doubling_count`
- `stop_points`
- `take_points`
- `macd1_fast`
- `macd1_slow`
- `macd2_fast`
- `macd2_slow`
- `base_lot_scale`
- `volume_min`
- `volume_step`
- `volume_max`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `687`
- Net P&L: `3,546.40`
- Win Rate: `35.66%`
- Profit Factor: `1.06`
- Max Drawdown: `5.14%`

## 对齐说明

- 原始 EA 依赖未随样例一并提供的 `Martingail.mqh` 与 `OnTesterFunctions.mqh`
- Backtrader 版本保留了双 MACD 信号、固定止损止盈和有限 martingale 的主要行为
- 由于缺少原始 `Martingail.mqh` 的实现细节，当前版本将 `DML` 映射为基于账户资金推导基础手数的可运行近似
- 因此该迁移版本更适合作为逻辑对齐与行为验证，不应视为与 MT5 逐笔完全一致
