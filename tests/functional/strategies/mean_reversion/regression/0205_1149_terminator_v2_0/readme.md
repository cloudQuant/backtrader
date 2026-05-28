# 1149 Terminator_v2.0

## 策略概述

该策略是对 MT5 EA `Terminator_v2.0` 的 Backtrader 迁移版本。

本示例聚焦于源码默认参数路径，即 `OPEN_POS_BASED_ON=MACD`。原 EA 还支持 Pivot、Support/Resistance、`i_Trend` 组合等多种信号模式，但这些模式依赖额外指标源码，本示例未一并复刻。

## 交易逻辑

- 使用 `MACD` 主线比较 `Shift` 与 `Shift+1` 的值
- `MACD` 主线上升时允许做多，下降时允许做空
- 若已有同方向仓位，且价格相对最近一次入场继续逆向推进 `Pips` 点，则按同方向继续加仓
- `ReverseCondition=true` 时交换买卖信号

## 仓位与风控逻辑

- 初始仓位使用固定 `lots`，或在 `lots=0` 时按 `cash * maximum_risk / 1000` 估算
- 加仓手数按源码规则分段放大：前 `double_count` 笔按 `2x` 递增，之后按 `1.5x` 递增
- 初始仓位使用 `take_profit`
- 加仓后按净持仓均价重算统一 `take_profit2`
- 仅当最后一笔达到 `max_count` 时，为该次加仓设置 `stop_loss`
- `trailing > 0` 时对当前净持仓止损执行简单尾随

## 说明

- 该示例仅实现默认 `MACD` 信号路径
- 由于 Backtrader 是净头寸模型，本示例将 MT5 的同向多次成交抽象为单净仓位上的逐次加仓

## 文件

- `strategy_terminator_v2_0.py` - 数据加载、默认 MACD 信号、同向加仓与风控实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```

## 回测结果

Pending validation.
