# 0022 YY Cross 2 MA

## 策略概述

该策略是对 MT5 EA `0022_YY_Cross_2_Ma/yy_cross_ma.mq5` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 做可运行回测样例，保留了原 EA 的单周期双均线交叉结构。

需要特别注意：

- **源码中的买卖方向与常见双均线教材描述相反**
- 当前迁移版本按源码行为实现，而不是按文档描述改写

## 核心逻辑

1. 计算两条 SMA：
   - `fast_ma_period = 72`
   - `slow_ma_period = 150`
2. 当源码条件满足时发出信号：
   - 若 `fast` 从上一根高于 `slow`，到当前跌破 `slow`，则返回 `BUY`
   - 若 `fast` 从上一根低于 `slow`，到当前上穿 `slow`，则返回 `SELL`
3. 信号出现时按固定手数开仓
4. 开仓后使用固定 `TP/SL`（其中默认 `SL=0`，即不设置止损）
5. 反向信号出现时，当前 backtrader 版本会先平旧仓，再按新方向开仓

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `lot_start`
- `lot_max`
- `ext_profit_ptk`
- `ext_sl_ptk`
- `fast_ma_period`
- `slow_ma_period`
- `point`
- `volume_min`
- `volume_max`
- `volume_step`

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

- 原 EA 使用当前图表周期；当前迁移版本先采用现有可用的 `M15` 数据验证
- 当前版本保留源码中的反向交叉方向、固定手数和固定 `TP/SL` 主流程
- 若后续你希望按文档语义而不是按源码语义实现，我可以再单独做一个“标准双均线交叉版”对照策略
