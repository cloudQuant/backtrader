# 0244 Gordago EA

## 策略来源

- MT5 源码：`ea/0244_Gordago_EA/gordago_ea.mq5`

## 策略逻辑

- EA 在 `Work timeframe` 的新柱上判断一次入场信号，并在每个执行 bar 上维护 trailing stop。
- 买入条件：`MACD[0] > MACD[1]`、`MACD[1] < 0`、`Stochastic[0] < Sto_level_buy`、`Stochastic[0] > Stochastic[1]`。
- 卖出条件：`MACD[0] < MACD[1]`、`MACD[1] > 0`、`Stochastic[0] > Sto_level_sell`、`Stochastic[0] < Stochastic[1]`。
- 每次只在没有持仓时开一笔仓位，开仓即带入方向相关的固定 `SL/TP`。
- trailing stop 持续工作。
- 当前 backtrader 实现使用 `M1` 执行周期，并重采样得到 `M3` 工作周期、`M12` 的 MACD 周期和 `H1` 的 Stochastic 周期。

## 与源码一致/差异说明

- 保留了 `MACD + Stochastic` 的组合入场、分方向 `SL/TP` 和持续 trailing stop 主流程。
- 原版依赖 MT5 原生 `iMACD` 和 `iStochastic`；当前版本使用 backtrader 内置对应指标在重采样后的多时间框架数据上近似还原。
- 原说明没有仓库内可直接对齐的 `USDJPY` 数据，因此这里使用 `XAUUSD_M1.csv` 作为可运行样例，并重采样出 `M3 / M12 / H1`。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_gordago_ea.py`：策略实现。
- `run.py`：读取 `XAUUSD_M1.csv` 并重采样多时间框架后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
