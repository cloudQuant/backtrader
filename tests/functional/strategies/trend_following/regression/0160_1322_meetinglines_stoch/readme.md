# 1322 Meeting Lines + Stochastic

## 策略概述

该策略是对 MT5 EA `1322_MQL5_向导_-_基于_牛市约会线_熊市约会线形态的交易信号_+_Stochastic` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心思路：

- 牛市 / 熊市约会线（Meeting Lines）反转形态识别
- Stochastic 信号线作为确认过滤
- 基于 Stochastic 超买超卖区域变化离场

## 核心逻辑

1. 检查两根 K 线是否构成 `Bullish Meeting Lines` 或 `Bearish Meeting Lines`
2. 当识别出牛市约会线，且 `Stochastic %D < 30` 时做多
3. 当识别出熊市约会线，且 `Stochastic %D > 70` 时做空
4. 持仓后根据 `%D` 在超卖 / 超买区域的反向穿越进行离场

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `stoch_k`
- `stoch_d`
- `stoch_slow`
- `ma_period`
- `stoch_entry_long`
- `stoch_entry_short`
- `stoch_exit_upper`
- `stoch_exit_lower`
- `lot`

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

- Trades: `0`
- Net P&L: `0.00`
- 说明：在当前 `XAUUSD M15` 数据区间内，该形态非常稀少，未触发交易

## 对齐说明

- 原 EA 属于 MQL5 Wizard 的蜡烛形态 + Stochastic 确认模块
- 当前 backtrader 版本保留了“Meeting Lines 形态 + Stochastic 过滤”的核心结构
- 该模式在当前数据上的出现频率很低，因此回测为 0 笔交易，但策略实现本身可运行
