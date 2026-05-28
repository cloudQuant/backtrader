# 1347 Reversal Candlestick Patterns

## 策略概述

该策略是对 MT5 EA `1347_MQL5向导_-_基于反转_K_线形态的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，核心逻辑基于一组基础反转 K 线形态与固定止盈止损管理。

## 核心逻辑

1. 根据 `candle_range / minimum / shadow_big / shadow_small` 识别反转蜡烛结构
2. 当识别到看涨反转形态时做多
3. 当识别到看跌反转形态时做空
4. 使用固定止损与止盈管理仓位

## 主要参数

- `candle_range`
- `minimum`
- `shadow_big`
- `shadow_small`
- `stop_loss`
- `take_profit`
- `lot`

## 当前数据与运行方式

- 数据：`../../../datas/XAUUSD_M15.csv`
- 运行：`python run.py`
- 绘图：`python run.py --plot`

## 对齐说明

- 当前版本保留了“反转蜡烛检测 + 固定风控”的主流程
- 该策略属于纯价格行为信号，不依赖额外振荡器确认
