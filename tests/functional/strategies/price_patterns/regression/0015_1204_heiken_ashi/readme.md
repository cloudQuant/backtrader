# 1204 Heiken Ashi

## 策略概述

该策略是对 MT5 EA `1204_Heiken_Ashi_为基础的_EA` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心思路：

- 计算 Heiken Ashi 开盘价与收盘价
- 使用 Heiken Ashi K 线颜色切换作为趋势反转信号
- 多空切换时进行反手或平仓

## 核心逻辑

1. 根据原始 OHLC 计算 `HA Close`
2. 使用递推方式计算 `HA Open`
3. 当 Heiken Ashi 从空头颜色切换为多头颜色时做多
4. 当 Heiken Ashi 从多头颜色切换为空头颜色时做空
5. 策略不依赖额外震荡器过滤，完全由 HA 颜色变化驱动

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `lot`
- `point`
- `price_digits`

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

- Trades: `1520`
- Net P&L: `-582.70`
- Win Rate: `34.14%`
- Profit Factor: `0.99`
- Max Drawdown: `7.99%`

## 对齐说明

- 原 EA 文档较简略，核心依赖 Heiken Ashi 指标方向
- 当前 backtrader 版本保留了“HA 颜色切换驱动多空切换”的主体逻辑
- 在 `XAUUSD M15` 上该信号过于频繁，因此交易笔数很多，结果偏弱
