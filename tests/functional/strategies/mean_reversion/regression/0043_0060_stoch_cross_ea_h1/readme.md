# 0060 Stoch Cross EA H1

## 策略来源

- MT5 源码：`scripts/0060_Stoch_Cross_EA_-_在_20_点以下买入，在_80_点以上卖出（H1）/stochasticfrizt1810update.mq5`
- 源目录名称包含“在 20 点以下买入，在 80 点以上卖出”，但实际提供的 `mq5` 源码并未加入 `20/80` 区域过滤，执行条件是单纯的 `%K/%D` 交叉。

## 策略逻辑

- 使用 `H1` 周期的随机指标交叉作为方向信号。
- 参数映射遵循 MT5 `iStochastic(K, D, Slowing)`：在 backtrader 中使用慢速随机指标，令 `period=K`、`period_dfast=Slowing`、`period_dslow=D`。
- 当 `%K` 从下向上穿越 `%D` 时开多。
- 当 `%K` 从上向下穿越 `%D` 时开空。
- 若持有多单且出现空头交叉，则先平多再反手开空。
- 若持有空单且出现多头交叉，则先平空再反手开多。
- 每次成交后进入 `CooldownMinutes` 冷却期，冷却结束前不再发起新交易。
- 每笔交易使用固定 `0.1` 手、固定 `300 point` 止损和固定 `300 point` 止盈。

## 与源码一致/差异说明

- 保留了 `H1` 随机交叉、固定手数、固定 `SL/TP`、冷却时间和反向信号平仓再入场的核心语义。
- MT5 源码中的 `RiskPercent` 实际未参与手数计算，源码内部始终使用固定 `0.1` 手；backtrader 版本保持这一行为。
- 原始目录位于 `scripts/`，但源码本体是 `OnTick()` 自动交易 EA 逻辑，因此按可迁移策略处理。
- 当前 examples 仅有 `XAUUSD_M1.csv`，因此这里通过重采样生成 `H1` 数据来完成回测。

## 运行方式

```bash
python run.py
```

## 配置文件

- `config.yaml`：数据区间、回测参数和策略参数。
- `run.py`：读取 `XAUUSD_M1.csv` 并重采样到 `H1` 后执行回测。
- `strategy_stoch_cross_ea_h1.py`：策略实现。
