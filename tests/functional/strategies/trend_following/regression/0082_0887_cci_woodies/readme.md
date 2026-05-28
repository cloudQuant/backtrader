# 0887 CCI_Woodies

## 策略概述

该示例是 MT5 EA `Exp_CCI_Woodies` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `CCI_Woodies` 指标，在 Fast/Slow CCI 云图颜色翻转时交易。

## 指标重建

- Fast CCI：`FastPeriod=6`，应用于 `PRICE_MEDIAN`
- Slow CCI：`SlowPeriod=14`，应用于 `PRICE_MEDIAN`
- DRAW_FILLING：Fast > Slow → Lime（多头）；Fast < Slow → Plum（空头）

## 交易逻辑

- 云图从空头翻转为多头 → 买入
- 云图从多头翻转为空头 → 卖出
- 支持 `Invert` 反向交易模式
- 保留固定 `SL/TP`

## 文件

- `strategy_cci_woodies.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
