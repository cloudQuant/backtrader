# 0296 Exp_CandleStop_System_Tm_Plus

## 策略来源

- MT5 源码：`ea/0296_Exp_CandleStop_System_Tm_Plus/exp_candlestop_system_tm_plus.mq5`

## 策略逻辑

- 使用 `CandleStop_System` 指标颜色状态作为信号来源。
- `2/3` 区域视为上轨突破颜色，`0/1` 区域视为下轨突破颜色。
- 保留多空开仓开关、多空平仓开关。
- 可启用 `hold_minutes` 固定持仓时间离场。
- 当前实现使用 `H8` 信号数据在 `M15` 执行数据上近似原 MT5 多时间框架逻辑。

## 与源码一致/差异说明

- 保留了通道颜色切换与固定持仓时间离场主流程。
- 原指标为自定义 `CandleStop_System`；当前版本使用本地最高高点/最低低点通道代理颜色缓冲。
- 原说明示例为 `EURJPY H8`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_exp_candlestop_system_tm_plus.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
