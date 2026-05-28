# 1191 ProMart

## 策略概述

该策略是对 MT5 EA `1191_ProMart` 的 backtrader 迁移版本。
当前版本保留了原 EA 的核心结构：

- 使用两组 MACD
- 第一组 MACD 识别局部拐点入场
- 第二组 MACD 用于趋势方向确认
- 单仓位运行
- 开仓后挂固定止损与止盈
- 有限 martingale 加仓
- 当上一笔交易亏损时，下一笔优先执行反向开仓

## 核心逻辑

1. 首笔交易由双 MACD 信号决定方向
2. 若上一笔交易盈利，则继续根据双 MACD 信号择时开仓
3. 若上一笔交易亏损，则下一笔直接按上一笔方向的反方向开仓
4. 开仓后设置固定止损 `stop_points` 与止盈 `take_points`
5. 若连续亏损，则下一笔按 `2^loss_streak` 放大手数，最高不超过 `doubling_count`

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

- Trades: `1059`
- Net P&L: `5,216.90`
- Win Rate: `35.79%`
- Profit Factor: `1.06`
- Max Drawdown: `6.21%`

## 对齐说明

- 原始 EA 依赖未随样例一并提供的 `Martingail.mqh` 与 `OnTesterFunctions.mqh`
- Backtrader 版本保留了双 MACD 信号、固定止损止盈、有限 martingale 与亏损后反向开仓的核心行为
- 由于缺少原始 `Martingail.mqh` 的实现细节，当前版本将 `DML` 映射为基于账户资金推导基础手数的可运行近似
- 因此该迁移版本更适合作为逻辑对齐与行为验证，不应视为与 MT5 逐笔完全一致
