# 0931 MFI_Histogram

## 策略概述

该示例是 MT5 EA `Exp_MFI_Histogram` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `MFI_Histogram` 指标，并依据柱体颜色进入极端区时开仓：

- `0 = 超买黄柱`
- `1 = 中性灰柱`
- `2 = 超卖蓝柱`

## 指标重建

`MFI_Histogram` 不依赖缺失外部库，核心逻辑为：

- 依据典型价格与成交量重建 `MFI(period=14)`
- 若 `MFI > HighLevel`，颜色索引为 `0`
- 若 `MFI < LowLevel`，颜色索引为 `2`
- 其余情况颜色索引为 `1`
- 直方图中轴固定为 `50`

## 交易逻辑

- 当上一根信号柱颜色 `> 0`，当前颜色为 `0` 时做多
- 当上一根信号柱颜色 `< 2`，当前颜色为 `2` 时做空
- 出现反向信号时按原 EA 语义平仓并允许反手
- 保留固定 `SL/TP`

## 文件

- `strategy_mfi_histogram.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
