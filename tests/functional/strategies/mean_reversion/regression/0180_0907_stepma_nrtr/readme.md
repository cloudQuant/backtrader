# 0907 StepMA_NRTR

## 策略概述

该示例是 MT5 EA `Exp_StepMA_NRTR` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `StepMA_NRTR` 指标，并在趋势翻转信号出现时交易。

## 指标重建

- Volty 计算步长：`Length` 周期高低差平均 × `Kv` 灵敏度
- StepMA 趋势跟踪 MA + NRTR 棘轮
- 4 条输出线：TrendUp/TrendDown + BuySignal/SellSignal
- 趋势翻转时生成买入/卖出箭头

## 交易逻辑

- BuySignal/SellSignal 信号入场
- TrendUp/TrendDown 持续时的反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_stepma_nrtr.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
