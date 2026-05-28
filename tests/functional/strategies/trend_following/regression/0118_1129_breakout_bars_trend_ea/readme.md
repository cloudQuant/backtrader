# 1129 突破柱趋势_EA

## 策略概述

该策略是对 MT5 `BreakoutBarsTrend_EA` 的 Backtrader 迁移版本。

原 EA 依赖自定义指标 `BreakoutBarsTrend_v2` 判断趋势突破与反转。当前示例已根据仓库中的指标源码 `indicators/4044_突破柱趋势_v2/breakoutbarstrend_v2.mq5` 在 Backtrader 中重建其核心趋势值逻辑，并在此基础上实现原 EA 的开平仓规则。

## 交易逻辑

- 当 `BreakoutBarsTrend_v2` 趋势值发生符号翻转时，视为趋势反转
- 无持仓时：
  - 若 `negatives = 0`，每次反转直接开仓
  - 若 `negatives > 0`，仅在最近一段趋势历史满足“连续负信号序列”过滤后开仓
- 有持仓时：
  - 若趋势反向翻转，则平掉当前仓位
- 同一根 bar 内，优先处理已有持仓的退出，不在平仓当根立即反手

## 风控逻辑

- 固定 `SL/TP`
- `reversal_mode` 支持 `PIPS` 与 `PERCENT`
- 当使用 `PERCENT` 时，`delta`、`stop_loss`、`take_profit` 都按价格百分比解释
- 当使用 `PIPS` 时，上述距离按 `point` 换算为价格距离
- 手数按参数 `lot` 下单，并按 `min_lot/max_lot/volume_step` 进行约束

## 文件

- `strategy_breakout_bars_trend_ea.py` - 指标重建、信号判断与交易实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 说明

- 原始 MT5 EA 使用 `Ask/Bid` 与交易服务器止损最小距离约束；Backtrader 版本采用 bar 价格近似与手动 `SL/TP` 判断
- “连续负信号序列”过滤已按源码结构迁移，但仍属于基于 bar 的近似复现

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`reversal_mode=PERCENT`、`delta=1.0`、`negatives=1`、`stop_loss=1.0`、`take_profit=4.0`、`lot=1.0`
- 信号次数：`52`
- 已平仓交易：`51`
- TradeAnalyzer 统计交易：`52`
- 胜率：`40.38%`
- 期初资金：`100000.00`
- 期末现金：`161458.00`
- 期末权益：`161708.00`
- 净收益：`61708.00`
- 最大回撤：`24.21%`
- SQN：未提供（runner 当前未接入 SQN 分析器）

说明：当前样本内共有 `52` 次趋势翻转入场信号，其中 `51` 笔已平仓，样本结束时仍保留 `1` 笔多单未平仓，`open_position_size=1.0`、`open_position_price=5112.49`。
