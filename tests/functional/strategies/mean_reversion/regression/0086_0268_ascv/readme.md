# 0268 ASCV

## 策略来源

- MT5 源码：`ea/0268_ASCV/ascv.mq5`

## 策略逻辑

- EA 基于 `BrainTrend1Sig` 指标的买卖缓冲信号。
- 仅在新柱线上读取上一根信号。
- `Reverse=false` 时：买缓冲非零开多，卖缓冲非零开空。
- `Reverse=true` 时：买卖信号对调。
- 开仓附带固定 `SL/TP`，并可选执行 trailing stop。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了 `BrainTrend1Sig` 信号驱动、`Reverse` 开关与 trailing 主流程。
- `braintrend1sig` 当前使用本地代理信号近似实现，不是逐缓冲复刻原自定义指标。
- 原说明示例为 `EURUSD H1`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_ascv.py`：策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
