# 0172 Exp_TimeZonePivotsOpenSystem

## 策略概述

该样例是对 MT5 EA `0172_Exp_TimeZonePivotsOpenSystem` 的 Backtrader 迁移版。
EA 基于 `TimeZonePivotsOpenSystem` 的日内固定通道突破信号交易，保留固定止损止盈和方向开平仓许可。

## 迁移思路

1. 将 `XAUUSD_M15.csv` 重采样为 `H1`，对应源码默认 `InpInd_Timeframe=PERIOD_H1`
2. 每个交易日 `start_hour` 对应信号柱的开盘价被记为 `Last_open`
3. 依据 `Last_open ± offset_points * point_size` 构造当日固定上下通道
4. 当收盘价突破上轨时生成多头颜色状态；跌破下轨时生成空头颜色状态
5. 颜色状态从非多头切换到多头时开多并平空；从非空头切换到空头时开空并平多

## 主要参数

- `mm`
- `mm_mode`
- `stoploss_points`
- `takeprofit_points`
- `buy_pos_open`
- `sell_pos_open`
- `buy_pos_close`
- `sell_pos_close`
- `start_hour`
- `offset_points`
- `signal_bar`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `144`
- Net P&L: `-1684.80`
- Win Rate: `31.94%`
- Profit Factor: `0.86`
- Max Drawdown: `3.18%`

## 对齐说明

- 当前实现按指标源码重建了 `StartH + Last_open ± Offset` 的日内固定通道，而不是使用简单高低点近似
- 与 `0178` 相比，本版本不包含固定持仓时间离场增强
- Backtrader 无法逐 tick 复刻 MT5 的订单服务器校验细节，因此结果应视为可运行的逻辑迁移样例
