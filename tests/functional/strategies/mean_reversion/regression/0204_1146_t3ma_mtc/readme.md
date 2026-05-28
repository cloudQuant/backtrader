# 1146 T3MA(MTC)

## 策略概述

该策略是对 MT5 EA `T3MA(MTC)` 的 Backtrader 迁移版本。

原 EA 使用 `T3MA-ALARM` 指标信号交易。该指标先对选定价格序列做一次均线，再做第二次同参数平滑；当双重平滑均线方向由跌转升时给出买箭头，由升转跌时给出卖箭头。

## 交易逻辑

- 计算指定 `ma_price`、`ma_method`、`ma_period` 的双重平滑均线
- 当方向从 `-1` 翻到 `1` 时触发买信号
- 当方向从 `1` 翻到 `-1` 时触发卖信号
- 若 `rev_close=true`，则用反向信号平掉现有持仓

## 风控逻辑

- 支持固定 `stop_loss`
- 支持固定 `take_profit`
- 使用固定手数 `lots`

## 文件

- `strategy_t3ma_mtc.py` - 数据加载、T3MA Alarm 信号与交易逻辑实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

- 数据：`XAUUSD_M15.csv`
- 区间：`2025-12-03 01:15:00` 到 `2026-03-10 09:00:00`
- 参数：`lots=0.1`、`stop_loss=0`、`take_profit=300`、`shift=1`、`rev_close=true`、`ma_period=19`、`ma_shift=0`、`ma_method=ema`、`ma_price=close`
- 信号次数：`0`
- 已平仓交易：`0`
- TradeAnalyzer 统计交易：`0`
- 胜率：`0.00%`
- 期初资金：`100000.00`
- 期末现金：`100000.00`
- 期末权益：`100000.00`
- 净收益：`0.00`
- 最大回撤：`0.00%`
- SQN：`0.00`

说明：本样本区间内未触发有效 `T3MA-ALARM` 反转入场信号，样本结束时无未平仓头寸，`open_position_size=0.0`、`open_position_price=0.0`。
