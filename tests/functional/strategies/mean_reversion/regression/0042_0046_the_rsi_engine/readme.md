# 0046 The RSI Engine

## 策略概述

该策略迁移自 `ea/0046_The_RSI_Engine/The_RSI_Engine_v2.1.mq5`。

源码是一个多信号 RSI 交易系统，核心包含：

- RSI 背离入场
- RSI 超买/超卖反转入场
- 可选 50 中轴确认
- 固定止损止盈
- 可选 RSI 反向极值退出
- 可选 trailing stop
- 可选日内利润/亏损限制
- 可选新闻窗口过滤
- 可选交易时段过滤

## 核心逻辑

1. 每根新K线检查一次信号
2. 若当前已有仓位，则只处理：
   - RSI 极值退出
   - trailing stop
3. 若当前无仓位，则按顺序检查：
   - 日内限额
   - 交易时段过滤
   - 新闻时间过滤
   - RSI 背离或 OB/OS 反转
   - 可选 50 中轴确认
4. 满足条件后按固定手数或风险模式开仓，并附带固定 `SL/TP`

## 参数

主要参数位于 `config.yaml`：

- `use_risk_management`
- `risk_percent`
- `lots`
- `stop_loss_points`
- `take_profit_points`
- `use_trailing_stop`
- `trailing_stop_trigger`
- `trailing_stop_step`
- `rsi_period`
- `rsi_overbought`
- `rsi_oversold`
- `rsi_centerline`
- `use_divergence_signal`
- `use_overbought_oversold_reversal`
- `use_centerline_confirmation`
- `use_rsi_level_exit`
- `divergence_lookback_bars`
- `enable_daily_limits`
- `daily_profit_target`
- `daily_loss_limit`
- `use_news_filter`
- `enable_time_filter`
- `close_at_end_time`

## 数据与运行方式

当前验证方式：

- 数据：`../../../datas/XAUUSD_M15.csv`
- 周期：`M15`

运行命令：

```bash
python3 run.py
```

如需绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 迁移版本保留了源码的 RSI 信号组合思路与主要过滤器
- 交易时段字符串、新闻窗口、日内限额与 trailing stop 均已在 backtrader 版本中实现
- 当前版本使用单净头寸方式复现该 EA 的单仓管理流程
