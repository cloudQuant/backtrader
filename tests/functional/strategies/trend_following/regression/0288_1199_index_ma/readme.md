# 1199 Indexed Moving Average

## 策略概述

该策略是对 MT5 EA `1199_一个EA交易_-_索引移动平均` 的 backtrader 迁移版本。
当前版本使用 `XAUUSD_M15.csv` 回测，复现了原 EA 的核心思路：

- 自定义 `IMA` 指标：`IMA = close / SMA(close, n) - 1`
- 用相邻两根 IMA 的相对变化率作为入场信号
- 根据信号阈值做多或做空
- 使用盈利追踪止损与亏损阈值平仓管理持仓
- 手数由资金风险参数控制，并受最大手数限制

## 核心逻辑

1. 计算 `IMA(period=n)` 指标
2. 计算 `k1 = (ima0 - ima1) / |ima1|`
3. 当 `k1 >= 0.5` 时开多
4. 当 `k1 <= -0.5` 时开空
5. 持仓盈利超过 `take` 点后启动追踪止损
6. 持仓亏损超过 `drop` 点时直接平仓
7. 开仓手数按 `cash * risk / drop` 近似计算，并限制在最小 / 最大手数区间内

## 主要参数

参数定义在 `config.yaml` 中，主要包括：

- `ma_period`
- `take`
- `drop`
- `signal_level`
- `risk`
- `max_lots`
- `volume_min`
- `volume_step`
- `volume_max`
- `margin_per_lot`
- `point`
- `price_digits`

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

- Trades: `1315`
- Net P&L: `11,373.90`
- Win Rate: `51.79%`
- Profit Factor: `1.02`
- Max Drawdown: `49.82%`

## 对齐说明

- 原 EA 说明中建议以日线柱做信号检查，而当前统一验证环境是 `XAUUSD M15`
- 当前迁移版本保留了自定义 IMA 指标、`k1` 阈值开仓、追踪止损、亏损阈值平仓和风险驱动手数框架
- Backtrader 版本对 MT5 的保证金检查与 `SYMBOL_TRADE_TICK_VALUE` 做了可运行近似映射，因此收益数值不应视为与原 MT5 完全逐笔一致
- 在 `XAUUSD M15` 数据上，这套规则交易频率明显高于日线设定，回撤也显著放大
