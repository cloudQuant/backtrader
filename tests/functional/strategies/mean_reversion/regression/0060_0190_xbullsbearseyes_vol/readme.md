# 0190 Exp_XBullsBearsEyes_Vol

## 策略概述

该样例是对 MT5 EA `0190_Exp_XBullsBearsEyes_Vol` 的 Backtrader 迁移版。
EA 基于自定义指标 `XBullsBearsEyes_Vol` 的颜色等级变化进行交易。与 `0191` 的 `Vol_Direct` 版本不同，这里使用的是**超买/超卖分区颜色缓冲区**，并且分为普通信号与强信号两档，分别对应不同的仓位规模和魔术号。

## 迁移思路

1. 从 `XAUUSD_M15.csv` 重采样到 `H8`，对应源码默认 `InpInd_Timeframe=PERIOD_H8`
2. 近似重建 `BullsPower + BearsPower -> gamma 递推 -> result*100-50 -> 乘 volume -> SMA 平滑` 的指标主值
3. 根据源码的 5 档颜色等级重建 `buffer 3`：
   - `0`: 高于 `HighLevel2`
   - `1`: 高于 `HighLevel1`
   - `2`: 中性区间
   - `3`: 低于 `LowLevel1`
   - `4`: 低于 `LowLevel2`
4. 使用 `SignalBar=1` 对齐已收盘信号柱，按源码条件生成两档入场：
   - 普通买入：`1 -> >1`
   - 强买入：`0 -> >0`
   - 普通卖出：`3 -> <3`
   - 强卖出：`4 -> <4`
5. 反向信号先作为平仓条件处理；在 Backtrader 中使用**单净头寸**近似源码的双魔术号多仓/空仓结构
6. 默认保留源码输入中的 `StopLoss=1000`、`TakeProfit=2000`

## 主要参数

- `mm1`
- `mm2`
- `lot_or_risk`
- `stop_loss_points`
- `take_profit_points`
- `period`
- `gamma`
- `high_level_2`
- `high_level_1`
- `low_level_1`
- `low_level_2`
- `ma_length`
- `signal_bar`
- `volume_type`
- `point`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 原 EA 通过 `Magic1` 与 `Magic2` 分别管理普通信号和强信号仓位；当前迁移版用单净头寸近似表达仓位方向和大小
- 原 readme 提到测试中未使用 `SL/TP`，但 EA 源码默认输入仍为 `StopLoss_=1000`、`TakeProfit_=2000`；当前实现以源码活跃默认参数为准
- 当前回测结果：`19` 笔成交，净收益 `-4955.30`，胜率 `42.11%`，Profit Factor `0.50`，最大回撤 `5.49%`
