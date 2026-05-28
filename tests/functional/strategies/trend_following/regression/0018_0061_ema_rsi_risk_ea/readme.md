# 0061 EMA RSI Risk EA

## 策略来源

- MT5 源码：`ea/0061_EMA_RSI_RISK-EA/ema_rsi_risk_ea.mq5`

## 策略逻辑

- 使用快速 `EMA` 与慢速 `EMA` 的交叉判定趋势切换。
- 当前 backtrader 实现使用 `M15` 作为执行与持仓管理周期，并使用重采样得到的 `H1` 数据计算 `EMA/RSI` 信号，以更接近源码在更细粒度行情上管理止损的行为。
- 仅当 `EMA` 金叉且 `RSI >= RSI_Buy_Thresh` 时开多。
- 仅当 `EMA` 死叉且 `RSI <= RSI_Sell_Thresh` 时开空。
- 按 `RiskPercent` 与固定 `SL_Pips` 估算每笔交易手数。
- 交易前检查点差是否不超过 `MaxSpread_Points`。
- 可通过 `StartHour / EndHour` 限制交易时段。
- 入场后使用固定 `SL/TP`，并在盈利达到 `Breakeven_Pips` 后把止损推到开仓价，在盈利超过 `Trailing_Pips` 后继续按 trailing 方式抬高或压低止损。

## 与源码一致/差异说明

- 保留了 `EMA` 交叉、`RSI` 阈值过滤、风险百分比动态仓位、时间窗、点差过滤、保本和 trailing stop 等主要逻辑。
- MT5 源码使用当前品种的 `tick value / tick size` 估算每手 pip 价值；backtrader 版本改为使用 `pip_size * contract_multiplier` 近似每手风险现金值，便于在已有 `XAUUSD` 数据上稳定回测。
- 原源码推荐 `EURUSD H1`，当前仓库仅现成提供 `XAUUSD_M15.csv`，因此这里通过重采样生成 `H1` 数据进行迁移验证。
- 最终运行结构为 `M15` 执行 + `H1` 信号，而不是纯 `H1` 单周期执行；这样 `SL / breakeven / trailing stop` 至少能在 `M15` 粒度上推进。
- `OneTradePerBar` 在 backtrader 的 bar 驱动模型下天然近似成立，因为策略本身只在每根新 bar 评估一次。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ema_rsi_risk_ea.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv`，保留 `M15` 执行数据，并额外重采样出 `H1` 信号数据后执行回测。
- `config.yaml`：策略参数、数据区间和回测配置。
