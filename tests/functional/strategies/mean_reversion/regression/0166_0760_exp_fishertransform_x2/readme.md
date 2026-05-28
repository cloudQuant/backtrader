# 0760 Exp_FisherTransform_X2

## 策略概述

该策略是对 MT5 EA `0760_Exp_FisherTransform_X2` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的主流程：

- 慢周期 `FisherTransform` 主线与信号线决定趋势方向
- 快周期 `FisherTransform` 主线与信号线交叉决定入场时机
- 慢趋势和快信号方向一致时才触发交易
- 交易使用固定 `SL/TP`

## 核心逻辑

1. 将基础数据分别重采样到慢周期 `H6` 与快周期 `M30`。
2. 在两个周期上分别计算 `Fisher Transform` 主线与信号线。
3. 若慢周期 `main > signal`，视为多头趋势；若 `main < signal`，视为空头趋势。
4. 空头趋势下，仅当快周期从 `main < signal` 变为 `main >= signal` 时开空。
5. 多头趋势下，仅当快周期从 `main > signal` 变为 `main <= signal` 时开多。
6. 若开启对应离场许可，则在趋势反转或快线反向时平掉现有持仓。

## 主要参数

- `slow_tf_minutes`
- `fast_tf_minutes`
- `slow_length`
- `fast_length`
- `signal_bar`
- `signal_bar_fast`
- `stop_loss`
- `take_profit`

## 对齐说明

- 原 EA 使用本地 `FisherTransform.ex5` 与 `FisherTransform_HTF.ex5`；当前版本在 Python 中直接重建主线/信号线，不再依赖编译指标。
- 由于原始 `fishertransform.mq5` 文本存在编码/空字节问题，当前实现采用标准 Fisher Transform 公式近似本地逻辑。
- 交易流程仍保持原 EA 的 `X2` 结构：慢趋势过滤 + 快趋势翻转入场。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
