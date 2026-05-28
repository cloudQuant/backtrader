# 0736 Exp_RSIOMA

## 策略概述

该策略是对 MT5 EA `0736_Exp_RSIOMA` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 在更高时间框架上重建 `RSIOMA`
- 同时生成 `RSIOMA` 主线与 `Trigger` 线
- 按 `Mode` 选择不同信号解释方式
- 反向信号平仓，配合固定 `SL/TP`

## 支持的信号模式

- `breakdown`
- `histtwist`
- `signaltwist`
- `histdisposition`

## 指标重建说明

- 先对价格序列做平滑
- 对平滑序列计算动量
- 对正负动量分别做平滑与递推聚合
- 得到 `RSIOMA` 主线
- 再对主线做一次平滑得到 `Trigger`

## 默认交易逻辑

默认使用 `histdisposition`：

- `RSIOMA` 上穿 `Trigger` 做多
- `RSIOMA` 下穿 `Trigger` 做空
- 反向事件同时作为持仓退出信号

## 主要参数

- `mode`
- `rsioma_method`
- `rsioma`
- `marsioma_method`
- `marsioma`
- `mom_period`
- `high_level`
- `low_level`

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
