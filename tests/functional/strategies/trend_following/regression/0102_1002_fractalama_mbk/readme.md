# 1002 FractalAMA MBK

## 策略概述

该示例是 MT5 EA `Exp_FractalAMA_MBK` 的 Backtrader 迁移版本。

原 EA 读取 `FractalAMA_MBK` 指标的主线与触发线，在信号周期收盘时根据两线交叉生成交易信号。

## 交易逻辑

- 重建 `FractalAMA_MBK` 指标：
  - 先按原始 FRAMA 思路基于高低点范围估算分形维度
  - 再用 `multiplier` 生成自适应平滑系数得到 `frama`
  - 用 `signal_multiplier` 对 `frama` 再次平滑得到 `trigger`
- 若上一根 `frama > trigger` 且当前 `frama <= trigger`，则开多并平空
- 若上一根 `frama < trigger` 且当前 `frama >= trigger`，则开空并平多
- 默认使用 `H4` 信号周期

## 风控逻辑

- 固定 `stop_loss_points`
- 固定 `take_profit_points`
- 固定手数 `lot`
- 反向信号到来时先平仓再反手

## 文件

- `strategy_fractalama_mbk.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
