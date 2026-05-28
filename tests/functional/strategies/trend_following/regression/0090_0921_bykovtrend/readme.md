# 0921 BykovTrend

## 策略概述

该示例是 MT5 EA `Exp_BykovTrend` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `BykovTrend` 指标，并在指标箭头翻转时交易。

## 指标重建

- 使用 `WPR(SSP=9)` 和 `ATR(15)`
- `K = 33 - RISK`
- 当 WPR < -(100-K) 时趋势转空；当 WPR > -K 时趋势转多
- 趋势翻转时输出箭头信号，箭头价格为 `low - ATR*3/8`（买入）或 `high + ATR*3/8`（卖出）

## 交易逻辑

- 买入箭头出现 → 做多，同时平掉空头
- 卖出箭头出现 → 做空，同时平掉多头
- 若当前柱无信号但持有仓位，回扫历史寻找最近反向箭头来决定平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_bykovtrend.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
