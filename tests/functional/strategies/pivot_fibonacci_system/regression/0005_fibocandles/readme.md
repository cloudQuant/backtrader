# 0919 FiboCandles

## 策略概述

该示例是 MT5 EA `Exp_FiboCandles` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `FiboCandles` 指标，并在指标蜡烛颜色翻转时交易。

## 指标重建

- 计算 `period` 周期内的最高价与最低价，得到 `range`
- 使用 Fibonacci 比率（默认 `0.236`）乘以 `range` 作为趋势翻转阈值
- 阴线时：若非 `(trend<0 && range*level < close-minLow)` 则趋势翻多
- 阳线时：若非 `(trend>0 && range*level < maxHigh-close)` 则趋势翻空
- 颜色 `0` = 多头，`1` = 空头

## 交易逻辑

- 颜色从 `0→1`（多翻空）→ 做空
- 颜色从 `1→0`（空翻多）→ 做多
- 趋势持续时的反向平仓 + 历史回扫
- 保留固定 `SL/TP`

## 文件

- `strategy_fibocandles.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
