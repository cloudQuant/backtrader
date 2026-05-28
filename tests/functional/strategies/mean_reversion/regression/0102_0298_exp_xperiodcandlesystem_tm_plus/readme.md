# 0298 Exp_XPeriodCandleSystem_Tm_Plus

## 策略来源

- MT5 源码：`ea/0298_Exp_XPeriodCandleSystem_Tm_Plus/Exp_XPeriodCandleSystem_Tm_Plus.mq5`

## 策略逻辑

- 使用 `XPeriodCandleSystem` 的颜色状态作为信号来源。
- `0` 视为阳线突破上轨色，`4` 视为阴线跌破下轨色。
- `1/3/2` 视为非突破状态，EA 在突破色结束后触发入场。
- 保留多空开仓开关、多空平仓开关。
- 可启用 `hold_minutes` 固定持仓时间离场。
- 当前实现使用 `H4` 信号数据在 `M15` 执行数据上近似原 MT5 多时间框架逻辑。

## 与源码一致/差异说明

- 保留了基于突破色结束的开仓、基于颜色区间的平仓和固定持仓时间离场主流程。
- 原指标为自定义 `XPeriodCandleSystem`；当前版本以平滑 OHLC + Bollinger 通道代理颜色状态。
- 原说明示例为 `USDJPY H4`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_exp_xperiodcandlesystem_tm_plus.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
