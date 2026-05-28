# 1310 Morning / Evening Star + Stochastic

## 策略概述

该策略是对 MT5 EA `1310_基于早晨之星_黄昏之星形态和_Stochastic_的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心思路：

- 早晨之星 / 黄昏之星三根 K 线反转形态识别
- Morning Doji / Evening Doji 的近似支持
- Stochastic 作为入场确认与离场辅助

## 核心逻辑

1. 识别 `Morning Star` / `Morning Doji` 看涨反转结构
2. 识别 `Evening Star` / `Evening Doji` 看跌反转结构
3. 当出现看涨结构且 `Stochastic %D < 30` 时做多
4. 当出现看跌结构且 `Stochastic %D > 70` 时做空
5. 持仓后根据 `%D` 在超买 / 超卖边界的反向穿越离场

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `stoch_k`
- `stoch_d`
- `stoch_slow`
- `ma_period`
- `stoch_entry_long`
- `stoch_entry_short`
- `stoch_exit_upper`
- `stoch_exit_lower`
- `lot`

## 当前数据与运行方式

当前使用数据：

- `../../../datas/XAUUSD_M15.csv`

运行命令：

```bash
python run.py
```

如果需要绘图：

```bash
python run.py --plot
```

## 当前回测结果

当前参数下的回测结果：

- Trades: `43`
- Net P&L: `+3,783.80`
- Win Rate: `51.16%`
- Profit Factor: `1.61`
- Max Drawdown: `3.89%`

## 对齐说明

- 原 EA 基于 MQL5 标准蜡烛形态类检测 Morning/Evening Star
- 当前 backtrader 版本保留了三 K 线反转结构与 Stochastic 确认主流程
- 在当前样本上，该策略比其他蜡烛形态组合更活跃，已有较稳定的交易样本
