# 0395 Expotest — Backtrader 迁移

## 原始 EA
- 文件：`ea/0395_Expotest/expotest.mq5`
- 核心信号：`SAR`
- 交易框架：单仓开仓，入场即附带固定 `SL/TP`

## 策略逻辑
1. 在 `TimeFrames` 指定周期上计算 `SAR`
2. 若 `SAR <= Ask`，产生做多信号
3. 若 `SAR >= Ask`，产生做空信号
4. 仅当当前没有同 EA 持仓时才允许新开仓
5. 开仓后依赖固定 `SL/TP` 出场，不做反向强平
6. 若上一笔已平仓交易亏损，则下一次下单手数按上一笔成交量的 `2` 倍近似

## 参数映射

| MQL5 参数 | Backtrader 参数 | 默认值 | 说明 |
|-----------|----------------|--------|------|
| `TimeFrames` | `signal_timeframe` | `M15` | SAR 信号周期 |
| `SL` | `sl_points` | 150 | 止损点数 |
| `TP` | `tp_points` | 200 | 止盈点数 |
| `Volume` | `volume` | 0.10 | 固定手数；大于 0 时优先使用 |
| `Risk` | `risk` | 0.13 | `volume=0` 时的风险百分比近似 |
| `MAGIC` | `magic` | 7505 | 魔术号 |
| `Slippage` | `slippage_points` | 30 | 允许滑点，仅保留参数 |
| `step` | `sar_step` | 0.02 | SAR 加速因子 |
| `maximum` | `sar_maximum` | 0.2 | SAR 最大加速 |

## 当前简化
- MQL5 中历史成交遍历后仅以最后一次成交的 `profit/volume` 决定是否翻倍；当前版本保留这一语义，用最近一次已闭合交易的 `pnl/size` 近似
- 原版 `Risk` 依赖 `OrderCalcMargin` 与品种保证金参数；当前以 `margin_per_lot` 做近似换算
- 使用 Backtrader 柱内 `high/low` 触发固定 `SL/TP`

## 回测数据
- 品种：XAUUSD
- 执行周期：M15
- 信号周期：M15
- 数据文件：`examples/../../../datas/XAUUSD_M15.csv`

## 运行
```bash
cd examples/0395_expotest
python run.py
```
