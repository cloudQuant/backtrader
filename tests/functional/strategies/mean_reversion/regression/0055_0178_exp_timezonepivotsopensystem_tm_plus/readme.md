# 0178 Exp_TimeZonePivotsOpenSystem_Tm_Plus

## 策略概述

该样例是对 MT5 EA `0178_Exp_TimeZonePivotsOpenSystem_Tm_Plus` 的 Backtrader 迁移版。
EA 基于 `TimeZonePivotsOpenSystem` 通道突破信号交易，并在原版基础上增加固定持仓时间到期离场。当前迁移版保留了固定止损止盈、方向开平仓许可和时间离场逻辑。

## 迁移思路

1. 将 `XAUUSD_M15.csv` 重采样为 `H1`，对应源码默认 `InpInd_Timeframe=PERIOD_H1`
2. 每个交易日 `start_hour` 对应的信号柱开盘价被记为 `Last_open`
3. 依据 `Last_open ± offset_points * point_size` 构造当日固定上下通道
4. 当收盘价突破上轨时生成多头颜色状态；跌破下轨时生成空头颜色状态
5. 颜色状态从非多头切换到多头时开多并平空；从非空头切换到空头时开空并平多
6. 若 `time_trade=true` 且持仓时间超过 `hold_minutes`，则立即平仓

## 主要参数

- `mm`
- `mm_mode`
- `stoploss_points`
- `takeprofit_points`
- `buy_pos_open`
- `sell_pos_open`
- `buy_pos_close`
- `sell_pos_close`
- `time_trade`
- `hold_minutes`
- `start_hour`
- `offset_points`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `141`
- Net P&L: `-1196.10`
- Win Rate: `34.04%`
- Profit Factor: `0.91`
- Max Drawdown: `3.34%`

## 对齐说明

- 当前实现按指标源码重建了 `StartH + Last_open ± Offset` 的日内固定通道，而不是使用简单高低点近似
- EA 源码的额外增强主要是“固定持仓时间离场”；当前版本已保留该逻辑
- Backtrader 无法逐 tick 复刻 MT5 的订单服务器校验细节，因此结果应视为可运行的逻辑迁移样例
