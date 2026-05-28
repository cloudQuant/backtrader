# 0879 iRSISign

## 策略概述

该示例是 MT5 EA `Exp_iRSISign` 的 Backtrader 迁移版本。

原 EA 在 `H1` 信号周期上调用 `iRSISign` 指标，在 RSI 穿越超卖/超买阈值时绘制箭头并开平仓。

## 指标重建

- 使用内建 RSI 与 ATR
- RSI 自下向上穿越 `DnLevel` 时生成买入箭头
- RSI 自上向下穿越 `UpLevel` 时生成卖出箭头
- 箭头位置按 `ATR * 3 / 8` 偏移

## 交易逻辑

- 买入箭头 → 开多，并触发空头平仓
- 卖出箭头 → 开空，并触发多头平仓
- 保留原 EA 的历史回扫关闭语义与固定 `SL/TP`

## 文件

- `strategy_irsisign.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
