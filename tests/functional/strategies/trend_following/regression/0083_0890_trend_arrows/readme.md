# 0890 trend_arrows

## 策略概述

该示例是 MT5 EA `Exp_trend_arrows` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `trend_arrows` 指标，在趋势箭头出现时入场。

## 指标重建

- 将 `iPeriod` 个子窗口内的最高价/最低价取平均，得到 AverageHigh (HH) 和 AverageLow (LL)
- `close > HH` → TrendUp = LL（上升趋势）
- `close < LL` → TrendDown = HH（下降趋势）
- 趋势从无到有时生成 SignUp/SignDown 箭头信号

## 交易逻辑

- SignUp 箭头 → 买入；SignDown 箭头 → 卖出
- TrendUp/TrendDown 持续时用于反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_trend_arrows.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
