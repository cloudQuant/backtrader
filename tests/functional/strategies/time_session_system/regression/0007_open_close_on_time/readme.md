# 0796 Opening and Closing on Time

## 策略概述

该策略是对 MT5 EA `0796_按时建仓和平仓` 的 Backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，保留了原 EA 的核心结构：

- 按设定时间开仓
- 按设定时间平仓
- 仅持有单笔方向仓位
- 支持固定方向：只做多或只做空

## 核心逻辑

1. 解析 `open_time` 与 `close_time`
2. 当日到达开仓时间后的首根可用 bar 时开仓
3. 当日到达平仓时间后的首根可用 bar 时平仓
4. 每天最多开一次、平一次，避免重复触发

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `open_time`
- `close_time`
- `lots`
- `buy`

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

- Trades: `67`
- Net P&L: `497.00`
- Win Rate: `44.78%`
- Profit Factor: `1.03`
- Max Drawdown: `6.66%`

## 对齐说明

- 原 EA 使用实时 `HH:mm` 精确分钟触发；当前验证数据为 `M15`，因此采用“到达目标时间后的首根可用 bar”近似实现
- 原 EA 默认参数为 `13:00` 开仓、`13:01` 平仓；在 `M15` 数据上会映射到同一交易时段内的相邻可执行点
- 原 EA 包含 `symbol` 与保证金检查；当前单品种 Backtrader 验证环境下保留交易时序核心逻辑
