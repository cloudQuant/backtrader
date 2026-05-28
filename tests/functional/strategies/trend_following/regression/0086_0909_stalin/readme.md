# 0909 Stalin

## 策略概述

该示例是 MT5 EA `Exp_Stalin` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `Stalin` 指标，并在箭头出现时交易。

## 指标重建

- 使用 `Fast(14)` 和 `Slow(21)` 两条 EMA（支持 SMA/LWMA）
- 可选 `RSI(17)` 过滤：买入需 RSI > 50，卖出需 RSI < 50
- MA 交叉 + RSI 过滤 → 生成买入/卖出箭头
- `Confirm` 参数：延迟确认入场距离
- `Flat` 参数：最小价格变化距离过滤

## 交易逻辑

- 箭头信号 + 历史回扫反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_stalin.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
