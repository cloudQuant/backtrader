# 0905 WPRSIsignal

## 策略概述

该示例是 MT5 EA `Exp_WPRSIsignal` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `WPRSIsignal` 指标，并在箭头出现时交易。

## 指标重建

- `WPR(27)` 与 `RSI(27)` 同周期
- 买入：WPR 上穿 -20 且 RSI > 50，且 `filterUP` 回溯内无重复穿越
- 卖出：WPR 下穿 -80 且 RSI < 50，且 `filterDN` 回溯内无重复穿越

## 交易逻辑

- 箭头信号 + 历史回扫反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_wprsisignal.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
