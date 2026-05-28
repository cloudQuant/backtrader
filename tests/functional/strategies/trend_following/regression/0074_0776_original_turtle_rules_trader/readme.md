# 0776 Original_Turtle_Rules_Trader

## 策略概述

该策略是对 MT5 EA `0776_Original_Turtle_Rules_Trader` 的 Backtrader 迁移版本。
当前版本保留了原 EA 的核心结构：

- 以 `Donchian channel` 突破作为系统 1 / 系统 2 入场依据
- 以 `ATR` 估算波动并控制单位仓位
- 按 `AddingInterval * ATR` 分批加仓
- 以 `NExit` 通道的反向突破退出
- 可选 `Parabolic SAR` trailing stop

## 核心逻辑

1. 计算 `ATR(20)` 作为单位波动
2. 计算 `NExit / NST / NLT` 三组 Donchian 通道
3. 无持仓时优先寻找 `NST` 突破；若前次 breakout 被视为成功，则跳过下一次 system-1 信号并等待 `NLT` 同向突破或 `NExit` 反向重置
4. 持仓后当价格按 `AddingInterval * ATR` 向有利方向推进时继续加仓
5. 当价格反向突破 `NExit` 通道，或命中 `SL/TP`，或启用 `SAR` trailing 后命中跟踪止损时离场

## 主要参数

- `n_exit`
- `n_st`
- `n_lt`
- `atr_period`
- `max_risk`
- `volume_limit`
- `adding_interval`
- `stop_loss`
- `take_profit`
- `sar_flag`

## 对齐说明

- 原 EA 使用账户权益、tick value 与 ATR 估算 `Unit`；当前版本在 Backtrader 中按 `风险预算 / (ATR * StopLoss * multiplier)` 近似单位手数
- 原码关于“成功 breakout 后跳过下一次 system-1 breakout”的状态流转存在一定实现耦合；当前版本按 Turtle 规则意图实现该语义
- 原版图形化通道绘制未迁移，仅保留交易决策核心

## 运行方式

```bash
python run.py
```

## 当前回测结果

已完成一次可运行验证，结果如下：

- 数据区间：`2025-12-03 01:15:00` ~ `2026-03-10 09:00:00`
- K线数量：`6129`
- 最终权益：`125074.34`
- 净收益：`25074.34`
- 总收益率：`25.07%`
- 总交易数：`345`
- 胜率：`49.57%`
- 盈利因子：`1.13`
- 最大回撤：`23.00%`
- Sharpe：`7.49`
- SQN：`0.90`

当前 Backtrader 版本已能够复现海龟规则中的 Donchian 突破、ATR 单位仓位、分批加仓与退出通道等核心行为，并在给定 `XAUUSD_M15` 数据区间内完成整段回测。
