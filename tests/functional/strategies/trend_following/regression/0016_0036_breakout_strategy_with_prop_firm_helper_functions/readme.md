# 0036 Breakout Strategy with Prop Firm Helper Functions

## 策略概述

该策略是对 MT5 EA `0036_Breakout_Strategy_with_Prop_Firm_Helper_Functions/propfirmhelper.mq5` 的 backtrader 迁移版本。
它是 `0029` 突破策略的扩展版：保留 `H1` 区间突破、风险仓位和通道追踪退出，同时增加 prop firm challenge 的账户级辅助风控。

## 核心逻辑

1. 在交易周期上计算入场区间：
   - `trigger_long = ENTRY_PERIOD` 根历史 K 线最高价 + 1 个最小跳动
   - `trigger_short = ENTRY_PERIOD` 根历史 K 线最低价 - 1 个最小跳动
2. 每个新交易周期开始时：
   - 先检查 prop firm 规则
   - 删除旧挂单
   - 管理已有持仓的 trailing stop
   - 若当前无对应方向持仓，则重新挂突破单
3. 仓位管理：
   - 根据 `RISK_PER_TRADE` 按权益百分比计算下单手数
   - 多头退出参考 `EXIT_PERIOD` 最低点
   - 空头退出参考 `EXIT_PERIOD` 最高点
4. Prop firm 辅助风控：
   - `PASS_CRITERIA` 达成时清空全部仓位和挂单
   - `DAILY_LOSS_LIMIT` 触发时清空全部仓位和挂单

## 主要参数

主要参数定义在 `config.yaml`：

- `entry_period`
- `entry_shift`
- `exit_period`
- `exit_shift`
- `is_challenge`
- `pass_criteria`
- `daily_loss_limit`
- `risk_per_trade`
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

- 原 EA 使用 `BuyStop` / `SellStop` 挂突破单；当前迁移版本保留 stop entry 语义
- 原 EA 使用 `H1` 周期；当前版本用 `M15 -> H1` 重采样近似
- 当前版本补上了 prop firm challenge 的账户级辅助规则，并在触发时清空挂单与持仓
