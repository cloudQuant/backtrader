# 0029 Simple Yet Effective Breakout Strategy

## 策略概述

该策略是对 MT5 EA `0029_Simple_Yet_Effective_Breakout_Strategy/breakoutstrategy.mq5` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 作为基础数据，并在回测中重采样为 `H1`，以贴近原 EA 默认的 `TRADING_TIMEFRAME = PERIOD_H1`。

## 核心逻辑

1. 在交易周期上计算入场区间：
   - `trigger_long = ENTRY_PERIOD` 根历史 K 线最高价 + 1 个最小跳动
   - `trigger_short = ENTRY_PERIOD` 根历史 K 线最低价 - 1 个最小跳动
2. 每个新交易周期开始时：
   - 删除旧的挂单
   - 管理已有仓位
   - 若当前无对应方向持仓，则重新挂突破单
3. 仓位管理：
   - 根据 `RISK_PER_TRADE` 按权益风险计算下单手数
   - 止损基于 `EXIT_PERIOD` 区间边界，或可选中线
4. 持仓退出：
   - 多头跌破 `trail_long` 时离场
   - 空头突破 `trail_short` 时离场
   - 若轨道向有利方向推进，则上移/下移保护止损

## 主要参数

主要参数定义在 `config.yaml`：

- `entry_period`
- `entry_shift`
- `exit_period`
- `exit_shift`
- `exit_middle_line`
- `risk_per_trade`
- `atr_period`
- `tick_size`
- `lot_step`
- `volume_min`
- `volume_max`
- `value_per_price_unit`

## 当前数据与运行方式

当前验证方式：

- 基础数据：`../../../datas/XAUUSD_M15.csv`
- 策略交易周期：回测内重采样为 `H1`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 原 EA 使用 MT5 `BuyStop` / `SellStop` 挂突破单；当前迁移版本在 backtrader 中保留 stop entry 语义
- 原 EA 使用 `H1` 周期；当前版本用 `M15 -> H1` 重采样近似
- 当前版本保留了区间突破、风险仓位、可选中线退出与移动止损主流程
