# 0157 Bago_EA

## 策略概述

该样例是对 MT5 EA `0157_Bago_EA` 的 Backtrader 迁移版。
原 EA 基于 `EMA 5 / EMA 12` 交叉与 `RSI 21 / 50` 交叉生成原始趋势信号，再叠加 Vegas 通道位置过滤、交易时段过滤，以及分层止损推进与部分减仓逻辑。

## 迁移思路

1. 使用 `H1` 执行层重建 `EMA5`、`EMA12`、`RSI21`
2. 额外构建 Vegas 通道 `EMA144 / EMA169`
3. 复刻交叉状态在 `CrossEffectiveTime` 柱内有效的状态机
4. 保留原版的时段过滤：`London / NewYork / Tokyo` 开关
5. 当 `EMA` 与 `RSI` 同向交叉且满足 Vegas 通道过滤时入场
6. 按 Vegas 通道位置、分层推进和反向交叉信号管理仓位

## 主要参数

- `fixed_lot`
- `stoploss_pips`
- `stoploss_to_fibo_pips`
- `trailing_stop_pips`
- `trailing_step1_pips`
- `trailing_step2_pips`
- `trailing_step3_pips`
- `lots_close_partial1`
- `lots_close_partial2`
- `cross_effective_time`
- `tunnel_bandwidth_pips`
- `tunnel_safe_zone_pips`
- `ema_fast_period`
- `ema_slow_period`
- `rsi_period`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`./run.py`
- 绘图：`./run.py --plot`

## 当前回测结果

- Trades: `29`
- Net P&L: `-28017.96`
- Win Rate: `20.69%`
- Profit Factor: `0.45`
- Max Drawdown: `43.92%`

## 对齐说明

- 原版在 MT5 中直接按图表周期执行，当前样例用 `M15` 源数据重采样到 `H1` 来贴近原说明中的典型运行方式
- 当前版本保留了 EMA/RSI 交叉时效、Vegas 通道过滤与阶段性止损推进主流程
- 部分减仓逻辑在 Backtrader 中以分次平仓近似实现，结果应视为可运行的逻辑迁移样例
