# 0260 Exp TrendManager Tm Plus

## 策略来源

- MT5 源码：`ea/0260_Exp_TrendManager_Tm_Plus/Exp_TrendManager_Tm_Plus.mq5`
- 指标源码：`ea/0260_Exp_TrendManager_Tm_Plus/TrendManager.mq5`

## 策略逻辑

- EA 基于 `TrendManager` 颜色翻转交易。
- 当指标颜色由空转多时开多；由多转空时开空。
- 出现反向颜色翻转时，先平当前仓位，再按新方向入场。
- 开仓附带固定 `SL/TP`。
- 可选启用按持仓时间强制平仓。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样得到 `H4` 信号周期。

## 与源码一致/差异说明

- 保留了颜色翻转反手、固定 `SL/TP` 与时间到期平仓主流程。
- `TrendManager` 当前按两条平滑均线的相对位置生成颜色状态做可运行近似。
- 原说明示例为 `GBPJPY H4`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H4` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_trendmanager_tm_plus.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H4` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
