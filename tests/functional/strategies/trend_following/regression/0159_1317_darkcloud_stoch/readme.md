# 1317 Dark Cloud Cover / Piercing Line + Stochastic

## 策略概述

该策略是对 MT5 EA `1317_基于Dark_Cloud_Cover_Piercing_Line_和_Stochastic_的交易信号` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心思路：

- 乌云盖顶 / 刺穿线反转形态识别
- Stochastic 作为入场确认
- 超买超卖区域反向穿越离场

## 核心逻辑

1. 识别 `Dark Cloud Cover` 看跌反转形态
2. 识别 `Piercing Line` 看涨反转形态
3. 当出现 `Piercing Line` 且 `Stochastic %D < 30` 时做多
4. 当出现 `Dark Cloud Cover` 且 `Stochastic %D > 70` 时做空
5. 持仓后根据 `%D` 穿越超买 / 超卖边界离场

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

- Trades: `2`
- Net P&L: `-69.30`
- Win Rate: `0.00%`
- Profit Factor: `0.00`
- Max Drawdown: `0.09%`

## 对齐说明

- 原 EA 基于标准 `CCandlePattern` 类识别乌云盖顶 / 刺穿线
- 当前版本对形态规则做了可运行近似实现，并保留 Stochastic 过滤框架
- 由于该形态在当前 `XAUUSD M15` 数据中较少出现，因此交易次数较少
