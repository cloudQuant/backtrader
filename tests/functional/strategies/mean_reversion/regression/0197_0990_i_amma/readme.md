# 0990 i-AMMA

## 策略概述

该示例是 MT5 EA `Exp_i-AMMA` 的 Backtrader 迁移版本。

原 EA 基于 `i-AMMA` 均线方向反转，在已完成柱上触发开平仓信号，并配合固定 `SL/TP` 管理持仓。

## 指标重建

- 指标源码本体为单线递推均线，无外部缺失依赖
- 初始化时首个有效值取价格本身
- 后续递推：`AMMA = ((period - 1) * (prev - price_shift) + price) / period`
- 输出值为 `AMMA + price_shift`
- 默认使用 `H4` 信号周期

## 交易逻辑

- 若最近三根已完成指标值呈 `下降后拐头上升`，则做多并平空
- 若最近三根已完成指标值呈 `上升后拐头下降`，则做空并平多
- 使用固定 `SL/TP`

## 文件

- `strategy_i_amma.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
