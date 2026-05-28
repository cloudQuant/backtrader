# 0869 Volume_Weighted_MA_StDev

## 策略概述

该示例是 MT5 EA `Exp_Volume_Weighted_MA_StDev` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `Volume_Weighted_MA_StDev` 指标，通过 VWMA 一阶差分的标准差过滤器生成分级多空点信号。

## 指标重建

- 先计算 `Volume_Weighted_MA`
- 再对其一阶差分计算 `std_period` 标准差
- 根据 `dK1/dK2` 两级阈值输出 `Bears1/Bulls1/Bears2/Bulls2`

## 交易逻辑

- 支持 `POINT/DIRECT/WITHOUT` 信号模式
- 默认开仓使用点信号，平仓使用方向信号
- 保留固定 `SL/TP`

## 文件

- `strategy_volume_weighted_ma_stdev.py`
- `run.py`
- `config.yaml`

## 用法

```bash
python run.py
```
