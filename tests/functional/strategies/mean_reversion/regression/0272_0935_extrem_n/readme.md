# 0935 Extrem_N

## 策略概述

该示例是 MT5 EA `Exp_Extrem_N` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `Extrem_N` 指标：
- 当上一根信号柱只有一侧极值标记，且当前信号柱切换到另一侧极值标记时触发反向开仓
- 同时允许基于反向信号平仓
- 保留固定 `SL/TP` 管理

## 指标重建

`Extrem_N` 本身不依赖外部缺失库，逻辑非常直接：

- 若 `high[bar] > high[bar - period]`，则上侧缓冲区输出当前 `high`
- 若 `low[bar] < low[bar - period]`，则下侧缓冲区输出当前 `low`
- 否则对应缓冲区输出 `0`

策略按原 EA 的双缓冲区切换条件重建信号，不依赖额外 `.ex5` 文件。

## 文件

- `strategy_extrem_n.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
