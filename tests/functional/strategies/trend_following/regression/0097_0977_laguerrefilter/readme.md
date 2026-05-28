# 0977 LaguerreFilter

## 策略概述

该示例是 MT5 EA `Exp_LaguerreFilter` 的 Backtrader 迁移版本。

原 EA 基于 `LaguerreFilter` 指标中的 `FIR` 与 `Laguerre` 两条线交叉开平仓，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 使用中价 `HL2` 作为输入价格
- 递推保持原式：`L0/L1/L2/L3` 按 `Gamma` 更新
- `Laguerre` 输出为 `(L0 + 2*L1 + 2*L2 + L3) / 6`
- `FIR` 输出为最近 4 根 `HL2` 的 `1-2-2-1` 加权平均
- 默认使用 `H4` 信号周期

## 交易逻辑

- 若上一根 `FIR > Laguerre` 且当前 `FIR < Laguerre`，则做多并平空
- 若上一根 `FIR < Laguerre` 且当前 `FIR > Laguerre`，则做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_laguerrefilter.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
