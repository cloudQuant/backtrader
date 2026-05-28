# 0953 Laguerre ROC

## 策略概述

该示例是 MT5 EA `Exp_Laguerre_ROC` 的 Backtrader 迁移版本。

原 EA 基于 `Laguerre_ROC` 柱形颜色在超买/超卖区突破时开仓，并在零轴一侧切换时平仓，配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码完整，不依赖缺失外部平滑库
- 使用 `ROC` 输入驱动四阶 `Laguerre` 递推
- 按源码重建 `LROC = CU / (CU + CD)` 与颜色索引 `0/1/2/3/4`
- 默认使用 `H8` 信号周期

## 交易逻辑

- 颜色切换到 `4` 时做多并平空
- 颜色切换到 `0` 时做空并平多
- 颜色大于 `2` 时平空，颜色小于 `2` 时平多
- 使用固定 `SL/TP`

## 文件

- `strategy_laguerre_roc.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
