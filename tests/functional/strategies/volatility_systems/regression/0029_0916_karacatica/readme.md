# 0916 Karacatica

## 策略概述

该示例是 MT5 EA `Exp_Karacatica` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `Karacatica` 指标，并在箭头出现时交易。

## 指标重建

- 使用 `ATR(iPeriod)` 和 `ADX(iPeriod)` 的 `+DI/-DI`
- 买入条件：`close > close[-iPeriod]` 且 `+DI > -DI` 且上一个信号非买入
- 卖出条件：`close < close[-iPeriod]` 且 `+DI < -DI` 且上一个信号非卖出
- 方向锁存防止连续同方向重复信号

## 交易逻辑

- 箭头信号 + 历史回扫反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_karacatica.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
