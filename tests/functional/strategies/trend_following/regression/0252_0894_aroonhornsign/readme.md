# 0894 AroonHornSign

## 策略概述

该示例是 MT5 EA `Exp_AroonHornSign` 的 Backtrader 迁移版本。

原 EA 在 `H4` 信号周期上调用 `AroonHornSign` 指标，并在趋势翻转信号出现时交易。

## 指标重建

- Aroon 上/下通道：`AroonPeriod` 窗口内最高点/最低点距当前 bar 的归一化距离
- `BULLS > BEARS && BULLS >= 50` → 上升趋势
- `BULLS < BEARS && BEARS >= 50` → 下降趋势
- 趋势翻转时：买入箭头 = `low - ATR*3/8`，卖出箭头 = `high + ATR*3/8`

## 交易逻辑

- 买入/卖出箭头信号入场 + 历史回扫反向平仓
- 保留固定 `SL/TP`

## 文件

- `strategy_aroonhornsign.py` - 数据加载、指标重建与策略实现
- `run.py` - 回测入口
- `config.yaml` - 参数配置

## 用法

```bash
python run.py
```
