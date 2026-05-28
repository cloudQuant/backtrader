# 1119 MA Delta

## 策略概述

该策略是对 MT5 `madelta_ea` 的 Backtrader 迁移版本。

原 EA 观察快慢均线差值的发散/收敛，将差值通过三次方非线性函数放大，再用高低阈值判别趋势翻转并执行开仓或反向。

## 交易逻辑

- 计算快慢均线差值 `fast_ma - slow_ma`
- 计算放大值 `px = (m * diff)^3`
- 当 `px` 创出新的高阈值时，交易方向切换为多
- 当 `px` 跌破新的低阈值时，交易方向切换为空
- 若已有反向持仓，则直接翻转至新目标仓位

## 参数映射

- `delta` 对应原 EA 的 `Delta`
- `multiplier` 对应原 EA 的 `M`
- `fast_period` / `slow_period` 对应快慢均线周期
- 快线使用加权价格上的 `SMA`
- 慢线使用中位价格上的 `EMA`

## 文件

- `strategy_ma_delta.py` - 数据加载、均线差值放大与阈值交易实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`delta=195`、`multiplier=392`、`fast_period=26`、`slow_period=51`、`lot_divisor=2000.0`、`max_lot=15.0`
- 信号次数：`2947`
- 已平仓交易：`42`
- TradeAnalyzer 统计交易：`43`
- 胜率：`27.91%`
- 期初资金：`100000.00`
- 期末现金：`-9693.30`
- 期末权益：`-9668.30`
- 净收益：`-109668.30`
- 最大回撤：`109.93%`
- SQN：`-2.72`

说明：当前参数下后段出现大量 `Margin` 拒单，导致 `signal_count` 与实际成交/平仓笔数严重背离。样本结束时仍保留 `1` 笔空单未平仓，`open_position_size=-0.10`、`open_position_price=4198.81`。
