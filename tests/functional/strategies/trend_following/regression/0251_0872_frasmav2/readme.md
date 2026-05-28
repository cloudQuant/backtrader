# 0872 FRASMAv2

## 策略概述

该示例是 MT5 EA `Exp_FRASMAv2` 的 Backtrader 迁移版本。

原 EA 在 `H12` 信号周期上调用 `FRASMAv2` 指标，在自适应均线颜色切换时交易。

## 指标重建

- 依据价格路径长度估计分形维数 `FDI`
- 将 `normal_speed` 按 `FDI` 映射为自适应平滑速度
- 对最近 `speed` 根价格取均值得到自适应均线
- 根据均线斜率输出颜色状态

## 交易逻辑

- 按原 EA 的颜色缓冲区变化条件触发多空开平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_frasmav2.py`
- `run.py`
- `config.yaml`

## 用法

```bash
python run.py
```
