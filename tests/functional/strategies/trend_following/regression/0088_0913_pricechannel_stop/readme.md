# 0913 PriceChannel_Stop

## 策略概述

该示例是 MT5 EA `Exp_PriceChannel_Stop` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `PriceChannel_Stop` 指标，并在趋势翻转信号出现时交易。

## 指标重建

- 计算 `ChannelPeriod` 根 K 线的最高价和最低价
- `bsmax = High - (High-Low)*Risk`，`bsmin = Low + (High-Low)*Risk`
- 趋势判断：`close > bsmax[prev]` → 上升，`close < bsmin[prev]` → 下降
- 棘轮效应：上升趋势中 `bsmin` 只能上移，下降趋势中 `bsmax` 只能下移
- 6 条输出线：DownTrendSignal/Buffer/Line、UpTrendSignal/Buffer/Line

## 交易逻辑

- UpTrendSignal 出现 → 做多
- DownTrendSignal 出现 → 做空
- UpTrendBuffer/DownTrendBuffer 持续时的反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_pricechannel_stop.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
