# 0911 Sidus

## 策略概述

该示例是 MT5 EA `Exp_Sidus` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `Sidus` 指标，并在箭头出现时交易。

## 指标重建

- 4 条均线：`FastEMA(18)`、`SlowEMA(28)`、`FastLWMA(5)`、`SlowLWMA(8)`
- 买入条件：FastLWMA 上穿 SlowLWMA，或 SlowLWMA 上穿 SlowEMA
- 卖出条件：FastLWMA 下穿 SlowLWMA，或 SlowLWMA 下穿 SlowEMA
- 箭头偏移量 = ATR(15) * 3

## 交易逻辑

- 箭头信号 + 历史回扫反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_sidus.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
