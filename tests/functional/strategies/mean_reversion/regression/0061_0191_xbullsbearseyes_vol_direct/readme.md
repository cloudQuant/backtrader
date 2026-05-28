# 0191 Exp_XBullsBearsEyes_Vol_Direct

## 策略概述

该样例是对 MT5 EA `0191_Exp_XBullsBearsEyes_Vol_Direct` 的 Backtrader 迁移版。
EA 不直接读取指标主值的绝对大小，而是使用自定义指标 `XBullsBearsEyes_Vol_Direct` 的方向颜色缓冲区：当方向颜色在相邻信号 bar 上发生翻转时，触发开仓并关闭反向持仓。

## 迁移思路

1. 从 `XAUUSD_M15.csv` 重采样到 `H2`，对应源码默认 `InpInd_Timeframe=PERIOD_H2`
2. 依据源码检索结果，近似重建 `BullsPower + BearsPower -> gamma 递推 -> result*100-50 -> 乘 volume -> SMA 平滑` 的指标主值
3. 重建指标 `buffer 7` 的方向颜色：
   - 主值上升记为 `0`
   - 主值下降记为 `1`
4. 当 `color[2] -> color[1]` 从 `0 -> 1` 时，触发买入并关闭空头
5. 当 `color[2] -> color[1]` 从 `1 -> 0` 时，触发卖出并关闭多头
6. 默认保留源码中的 `StopLoss=1000`、`TakeProfit=2000`

## 主要参数

- `lot`
- `stop_loss_points`
- `take_profit_points`
- `period`
- `gamma`
- `ma_length`
- `signal_bar`
- `volume_type`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- EA 源码里 `HighLevel1/2`、`LowLevel1/2` 传给指标时被固定为 `0`，但真正被 EA 使用的是方向颜色缓冲区，因此当前迁移版只重建最小必要信号链路
- 原 readme 提到测试时未使用 `SL/TP`，但 EA 源码默认输入仍为 `StopLoss_=1000`、`TakeProfit_=2000`；当前实现以源码活跃默认参数为准
- 当前回测结果：`69` 笔成交，净收益 `-2664.40`，胜率 `44.93%`，Profit Factor `0.70`，最大回撤 `5.49%`
