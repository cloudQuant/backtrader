# 0231 OHLC Stochastic

## 策略来源

- MT5 源码：`ea/0231_OHLC_随机振荡/ohlc_stochastic.mq5`

## 策略逻辑

- 使用 `iStochastic` 的主线和信号线判断超买超卖区内的交叉。
- 当前 backtrader 实现使用 `M1` 作为执行与持仓管理周期，并将同一份数据重采样为 `H12` 作为信号周期。
- 当 `Stochastic Main > Signal` 且两者至少有一条低于 `STO level DOWN` 时，若当前空仓则开多。
- 当 `Stochastic Main < Signal` 且两者至少有一条高于 `STO level UP` 时，若当前空仓则开空。
- 持有多单时，若出现卖出条件，则先平多再反手开空；持有空单时逻辑相反。
- 入场时不设置固定 `SL/TP`，仓位盈利超过 `Trailing Stop + Trailing Step` 后开始挂出并逐步抬升/压低 trailing stop。
- 手数支持固定值和风险百分比两种模式；当前默认保留源码的 `Risk=15` 思路，用账户净值的一定比例近似换算名义仓位。

## 与源码一致/差异说明

- 保留了 `Stochastic` 超买超卖区交叉、单仓反手、无固定 `SL/TP`、以及 trailing stop 的主流程。
- MT5 原码说明中提到 EA 在工作周期柱内运行，并直接读取 `bar 0` 的指标值；backtrader 版本使用 `M1` 执行数据并重采样出 `H12` 信号，以尽量逼近该行为，但仍然是对 MT5 未完成高周期 bar 内部更新的一种近似。
- 原码通过 `MoneyFixedMargin` 类在 `Risk > 0` 时计算可开手数；当前 backtrader 版本改为使用 `risk_percent * equity / (price * contract_multiplier)` 的近似公式做名义仓位换算，以便在现有样例数据上稳定回测。
- 原文示例品种为 `EURUSD H12`，当前仓库未提供对应数据，因此这里使用 `XAUUSD_M1.csv` 并重采样为 `H12` 验证可运行性。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ohlc_stochastic.py`：策略实现、数据加载和自定义数据源。
- `run.py`：读取 `XAUUSD_M1.csv`，保留 `M1` 执行数据并重采样 `H12` 信号后执行回测。
- `config.yaml`：策略参数、数据区间和回测配置。
