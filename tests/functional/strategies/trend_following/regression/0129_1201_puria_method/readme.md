# 1201 Puria Method

## 策略概述

该策略是对 MT5 EA `1201_一款_EA,_基于_Puria_方法_外汇交易策略` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心思路：

- 两条低价 LWMA 作为趋势带
- 一条收盘价 EMA 作为触发线
- MACD 零轴作为方向确认

## 核心逻辑

1. 计算两条低价加权均线：`LWMA(85)` 与 `LWMA(75)`
2. 计算一条收盘价指数均线：`EMA(5)`
3. 当 `EMA(5)` 同时上穿两条红色均线，且 `MACD > 0` 时做多
4. 当 `EMA(5)` 同时下穿两条红色均线，且 `MACD < 0` 时做空
5. 信号反向时平仓并可反手

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `lwma1_period`
- `lwma2_period`
- `ema_period`
- `macd_fast`
- `macd_slow`
- `macd_signal`
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

- Trades: `25`
- Net P&L: `-10,171.50`
- Win Rate: `24.00%`
- Profit Factor: `0.26`
- Max Drawdown: `12.58%`

## 对齐说明

- 原 EA 推荐的主要适用品种是若干外汇货币对与 `M30/H1`
- 当前迁移版本在 `XAUUSD M15` 上保持规则结构一致，但品种与周期不匹配，因此结果较差
- 当前 backtrader 版本重点是保留 `3MA + MACD` 的原始入场框架，而不是重新优化参数
