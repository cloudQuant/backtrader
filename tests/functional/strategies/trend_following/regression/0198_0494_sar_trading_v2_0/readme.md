# 0494 SAR_trading_v2.0

## 策略概述

该策略是对 MT5 EA `0494_SAR_trading_v2.0` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑为比较 `Parabolic SAR` 与移动平均线位置，并在空仓时建立单向仓位，持仓阶段只进行尾随管理。

## 核心逻辑

1. 计算 `SAR` 与移动平均线
2. 若当前存在持仓，则不再寻找新信号，只执行尾随止损管理
3. 若 `SAR < MA` 或 `close[ma_shift] < MA`，则开多
4. 若 `SAR > MA` 或 `close[ma_shift] > MA`，则开空
5. 持仓使用固定 `SL/TP` 与传统 trailing stop 管理

## 主要参数

- `lot`
- `stop_loss_pips`
- `take_profit_pips`
- `trailing_stop_pips`
- `trailing_step_pips`
- `ma_period`
- `ma_shift`
- `ma_method`
- `sar_step`
- `sar_maximum`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

 ## 当前回测结果

 - Trades: `3049`
 - Net P&L: `-6,357.60`
 - Win Rate: `50.51%`
 - Profit Factor: `0.93`
 - Max Drawdown: `9.82%`

## 对齐说明

- 原 EA 允许通过指标参数选择不同时间帧；当前迁移示例按默认配置仅使用当前数据时间帧
- 原 EA 在持仓期间完全停止寻找新入场，仅做 trailing；当前版本保持相同约束
- 原 EA 的信号条件在源码中使用 `or` 连接 `SAR/MA` 与 `close/MA` 比较；当前版本按源码字面逻辑迁移，而非额外猜测为 `and`
