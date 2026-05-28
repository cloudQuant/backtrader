# 0915 LeManSignal

## 策略概述

该示例是 MT5 EA `Exp_LeManSignal` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `LeManSignal` 指标，并在箭头出现时交易。

## 指标重建

- 计算两组连续的 `LPeriod` 周期最高价/最低价窗口
- 买入条件：前一组最高价突破后一组（`H3<=H4 && H1>H2`）
- 卖出条件：前一组最低价下破后一组（`L3>=L4 && L1<L2`）
- 箭头价格为前一柱的 `high+Point`（买入）或 `low-Point`（卖出）

## 交易逻辑

- 箭头信号 + 历史回扫反向平仓（需同时检查对面信号为空）
- 保留固定 `SL/TP`

## 文件

- `strategy_lemansignal.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
