# 0688 模糊逻辑

## 策略概述

该策略是对 MT5 EA `0688_模糊逻辑` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主要结构：

- 对 `Gator / WPR / AC / DeMarker / RSI` 五个因子做模糊分类
- 把模糊分类结果加权聚合成 `decision`
- `decision > 0.75` 做空，`decision < 0.25` 做多
- 单仓位运行，入场后使用固定 `SL/TP` 与可选 trailing stop

## 核心逻辑

1. 计算 `Gator` 双柱和、`WPR(14)`、`AC`、`DeMarker(14)`、`RSI(14)`。
2. 按原源码阈值表把每个因子映射到 5 档模糊隶属度。
3. 对前 4 档进行加权聚合，得到 `decision`。
4. 若 `decision > 0.75`，则开空。
5. 若 `decision < 0.25`，则开多。
6. 开仓手数按固定手或 `PercentMM/DeltaMM/InitialBalance` 近似计算。

## 主要参数

- `trailing_stop`
- `percent_mm`
- `delta_mm`
- `initial_balance`
- `take_profit_pips`
- `stop_loss_pips`
- `fixed_lots`
- `use_mm`

## 对齐说明

- 原 EA 的模糊推理函数完全在本地源码内，因此可以做首版等价迁移。
- 当前版本用 `pandas` 预计算 `decision` 线，再交由 Backtrader 负责交易与风控，这是为了更稳定地复刻原 EA 的分段隶属度与聚合过程。
- 原 `AC`、`Gator` 的平台内部实现与 Backtrader 不完全一致，因此当前版本属于近似迁移，仍需后续回测对齐验证。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
