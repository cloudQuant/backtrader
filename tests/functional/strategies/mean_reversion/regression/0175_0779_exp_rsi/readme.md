# 0779 Exp_RSI

## 策略概述

该策略是对 MT5 EA `0779_Exp_RSI` 的 Backtrader 迁移版本。
当前版本保留了原 EA 的核心结构：

- 在高一级信号周期上计算 `RSI`
- 监控 RSI 与超买/超卖水平的交叉
- 支持 `DIRECT` 与 `AGAINST` 两种方向解释
- 支持开多/开空/平多/平空开关
- 使用固定 `StopLoss / TakeProfit`

## 核心逻辑

1. 从 `M15` 数据重采样出 `H4` 信号周期
2. 在 `H4` 上计算 `RSI(14)`
3. 当 RSI 下穿超卖线时生成买入或反向卖出信号
4. 当 RSI 上穿超买线时生成卖出或反向买入信号
5. 根据信号执行开平仓，并用固定 `SL/TP` 管理仓位

## 主要参数

- `trend`
- `rsi_period`
- `high_level`
- `low_level`
- `signal_bar`
- `buy_pos_open`
- `sell_pos_open`
- `buy_pos_close`
- `sell_pos_close`
- `stop_loss`
- `take_profit`

## 对齐说明

- 原 EA 默认在 `H4` RSI 上生成信号，当前版本保留该设计
- 原码使用 `TradeAlgorithms.mqh` 执行开平仓；当前版本以 Backtrader 的标准订单接口实现等价行为
- 当前采用固定下单量 `0.1` 手来近似默认 `MMMode=LOT` 的最直接语义

## 运行方式

```bash
python run.py
```

## 当前回测结果

已完成一次可运行验证，结果如下：

- 数据区间：`2025-12-03 01:15:00` ~ `2026-03-10 09:00:00`
- K线数量：`M15=6129`，`H4=405`
- 最终权益：`104214.40`
- 净收益：`4214.40`
- 总收益率：`4.21%`
- 总交易数：`14`
- 胜率：`42.86%`
- 盈利因子：`1.46`
- 最大回撤：`2.51%`
- Sharpe：`7.41`
- SQN：`0.66`

在当前 `XAUUSD_M15` 数据窗口下，`H4 RSI` 交叉信号能够稳定触发并完成回测，验证了该策略在 Backtrader 中的可运行性。
