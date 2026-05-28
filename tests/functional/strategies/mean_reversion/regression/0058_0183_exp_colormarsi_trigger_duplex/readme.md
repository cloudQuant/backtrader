# 0183 Exp_ColorMaRsi-Trigger_Duplex

## 策略概述

该样例是对 MT5 EA `0183_Exp_ColorMaRsi-Trigger_Duplex` 的 Backtrader 迁移版。
EA 基于 `ColorMaRsi-Trigger` 的三态趋势输出管理多空两套子系统。当前迁移版保留 long / short 的独立开平仓许可、止损止盈和仓位参数，并用单净头寸近似原 EA 的双魔术号结构。

## 迁移思路

1. 将 `XAUUSD_M15.csv` 重采样为 `H4`，对应源码默认 `InpInd_Timeframe=PERIOD_H4`
2. 按指标源码重建快慢 `MA + RSI` 组合趋势值
3. 多头开仓：当前非零趋势为 `+1`，且最近历史非零趋势为 `-1`
4. 空头开仓：当前非零趋势为 `-1`，且最近历史非零趋势为 `+1`
5. 当前趋势转为反向时，先关闭已有净头寸，再按许可条件反手
6. 默认保留源码中的 `1000 / 2000` 点止损止盈

## 主要参数

- `indicator_minutes`
- `n_period_rsi`
- `n_rsi_price`
- `n_period_rsi_long`
- `n_rsi_price_long`
- `n_period_ma`
- `n_ma_type`
- `n_ma_price`
- `n_period_ma_long`
- `n_ma_type_long`
- `n_ma_price_long`
- `l_signal_bar`
- `s_signal_bar`
- `l_stop_loss_points`
- `l_take_profit_points`
- `s_stop_loss_points`
- `s_take_profit_points`
- `l_mm`
- `s_mm`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 当前回测结果

- Trades: `32`
- Net P&L: `-1165.60`
- Win Rate: `25.00%`
- Profit Factor: `0.68`
- Max Drawdown: `1.67%`

## 对齐说明

- 原 EA 的 long / short 子系统可以配置不同参数并分别启停；当前 Backtrader 版本保留独立参数入口，但在仓位层面使用单净头寸近似
- 当前实现遵循 EA 源码的“当前趋势 + 最近非零历史趋势”触发逻辑，而不是直接按彩色显示状态机械下单
- Backtrader 无法逐 tick 复刻 MT5 的成交和订单校验细节，因此结果应视为可运行的逻辑迁移样例
