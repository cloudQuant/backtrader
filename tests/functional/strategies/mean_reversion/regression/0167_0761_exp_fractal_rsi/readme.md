# 0761 Exp_Fractal_RSI

## 策略概述

该策略是对 MT5 EA `0761_Exp_Fractal_RSI` 的 Backtrader 迁移版本。
当前实现保留了原 EA 的核心结构：

- 在高周期上计算 `Fractal_RSI`
- 当指标下穿超卖线时生成一组信号，当指标上穿超买线时生成另一组信号
- `Trend=DIRECT` 与 `Trend=AGAINST` 两种交易方向均保留
- 交易使用固定 `SL/TP`

## 核心逻辑

1. 将基础数据重采样到信号周期 `H4`。
2. 按本地 `Fractal_RSI.mq5` 的 `FDI -> Hurst -> trail_dim -> beta -> dynamic RSI period` 递推链计算指标值。
3. `DIRECT` 模式下：
   - `Fractal_RSI` 从上向下穿越 `LowLevel` 时做多
   - `Fractal_RSI` 从下向上穿越 `HighLevel` 时做空
4. `AGAINST` 模式下，上述方向对调。
5. 若开启对应 `BuyPosClose/SellPosClose`，则在反向信号出现时平掉现有持仓。

## 主要参数

- `signal_tf_minutes`
- `trend`
- `e_period`
- `normal_speed`
- `applied_price`
- `high_level`
- `low_level`
- `signal_bar`
- `stop_loss`
- `take_profit`

## 对齐说明

- 原 EA 使用 `TradeAlgorithms.mqh` 完成标准单仓开平仓；当前版本在 Backtrader 中按同样的单仓反手流程重建。
- 原指标文件含 null bytes，当前迁移依据已解析出的本地递推公式完成 Python 重写，而非简单调用外部编译指标。
- 当 `length<=0` 时，原指标注释说明倾向于沿用前值；当前实现也采用这一近似处理。

## 运行方式

```bash
python run.py
```

## 当前状态

- 示例目录与可运行脚手架已建立。
- 尚未补做本地回测校验，建议台账先标记为 `实施中`，后续再补齐样本结果。
