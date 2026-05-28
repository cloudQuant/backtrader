# 0002 Price Action Intraday Trading

## 策略概述

该策略是对 MT5 EA `0002_Price_Action_Intraday_Trading_-_Expert_for_MT5` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，保留了原 EA 的日内价格行为交易框架：

- 双 EMA 趋势过滤
- Pin Bar / Engulfing / Inside Bar 形态识别
- 固定止损/止盈
- Break-even 与 trailing stop 管理

## 核心逻辑

1. 使用快慢 EMA 判断当前趋势方向
2. 在趋势方向上寻找价格行为信号：
   - Pin Bar
   - 吞没形态
   - Inside Bar 突破
3. 信号成立时按固定风险参数开仓
4. 仓位建立后进行动态管理：
   - 固定 SL / TP
   - 盈利达到阈值后移动到保本
   - 盈利继续扩展后启动追踪止损
5. 订单关闭后等待下一次有效结构

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `fast_ema_period`
- `slow_ema_period`
- `stop_loss_points`
- `take_profit_points`
- `breakeven_points`
- `trailing_start_points`
- `trailing_distance_points`
- `point`
- `price_digits`

具体数值以当前 `config.yaml` 为准。

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python3 run.py
```

如果需要绘图：

```bash
python3 run.py --plot
```

## 对齐说明

- 原 EA 推荐 `M15/H1/H4`，当前仓库中最匹配的是 `XAUUSD_M15.csv`
- 迁移版本重点保留趋势过滤、形态识别与仓位管理流程
- 当前版本适合作为 backtrader 中的可运行价格行为策略样例
