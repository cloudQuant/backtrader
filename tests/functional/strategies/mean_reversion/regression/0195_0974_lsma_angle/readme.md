# 0974 LSMA_Angle

## 策略概述

该示例是 MT5 EA `Exp_LSMA_Angle` 的 Backtrader 迁移版本。

原 EA 基于 `LSMA_Angle` 颜色区间变化做突破开平仓：离开强上行区开多，离开强下行区开空，回到零轴附近时平仓。

## 指标重建

- 指标源码完整，不依赖缺失的 `SmoothAlgorithms.mqh`
- 使用原始 `LSMA` 线性回归末值计算
- 角度近似值保持 `mFactor * (end_ma - start_ma) / 2` 语义
- 颜色索引保持源码定义：`0/1` 为负区，`2` 为零轴附近，`3/4` 为正区
- 默认使用 `H1` 信号周期

## 交易逻辑

- 上一根颜色为 `4` 且当前颜色小于 `4` 时做多
- 上一根颜色为 `0` 且当前颜色大于 `0` 时做空
- 空头在上一根颜色大于 `1` 时平仓
- 多头在上一根颜色小于 `2` 时平仓
- 使用固定 `SL/TP`

## 文件

- `strategy_lsma_angle.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
