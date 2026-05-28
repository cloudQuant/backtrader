# 1200 Night EA

## 策略概述

该策略是对 MT5 EA `1200_Night_EA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心思路：

- 仅在夜间交易窗口 `21:00-06:00` 内寻找入场机会
- 使用 `Stochastic(5,3,3)` 的主线作为超买超卖触发条件
- 无持仓时，超卖做多、超买做空
- 入场后使用固定止损 `40` 点和固定止盈 `20` 点
- 仓位按可用资金动态放大，并限制在 `0.1-5.0` 手之间

## 核心逻辑

1. 计算 `Close/Close` 版本的随机指标，并用 `EMA` 进行 `3` 周期平滑
2. 当上一根柱的随机指标主线 `< 30`，且当前时间处于夜间窗口时开多
3. 当上一根柱的随机指标主线 `> 70`，且当前时间处于夜间窗口时开空
4. 每次开仓后设置固定止损与固定止盈价位
5. 持仓仅依赖止损 / 止盈退出，不做反向信号平仓

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `stoch_k_period`
- `stoch_d_period`
- `stoch_slowing`
- `stoch_oversold`
- `stoch_overbought`
- `stop_loss_points`
- `take_profit_points`
- `trade_start_hour`
- `trade_end_hour`
- `lot_divisor`
- `min_lot`
- `max_lot`
- `point`
- `price_digits`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

当前参数下的回测结果：

- Trades: `582`
- Net P&L: `-99,998.90`
- Win Rate: `50.00%`
- Profit Factor: `0.83`
- Max Drawdown: `100.00%`

## 对齐说明

- 原 EA 文档说明其主要测试目标是 `EURUSD M15` 的夜间交易，而当前统一验证环境是 `XAUUSD M15`
- 当前迁移版本保留了原始 EA 的夜间时间过滤、随机指标阈值、固定止盈止损与动态手数框架
- MQL5 原实现使用自由保证金驱动仓位放大；在 `XAUUSD M15` 上这会导致仓位激进、账户快速回撤，因此回测结果极差
- 当前 backtrader 版本重点是保留规则结构与仓位思想，而不是针对 `XAUUSD` 重新优化参数
