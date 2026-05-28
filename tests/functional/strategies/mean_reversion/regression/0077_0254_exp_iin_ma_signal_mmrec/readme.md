# 0254 Exp Iin MA Signal MMRec

## 策略来源

- MT5 源码：`ea/0254_Exp_Iin_MA_Signal_MMRec/exp_iin_ma_signal_mmrec.mq5`
- 指标源码：`ea/0254_Exp_Iin_MA_Signal_MMRec/iin_ma_signal.mq5`

## 策略逻辑

- EA 基于 `Iin_MA_Signal` 箭头信号交易。
- 出现买入箭头时开多并平空，出现卖出箭头时开空并平多。
- 开仓附带固定 `SL/TP`。
- 在 `0245` 基础上增加 `MMRec` 逻辑：按最近若干笔同方向已闭合交易结果，决定本次使用 `MM` 还是 `SmallMM_`。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样得到 `H1` 信号周期。

## 与源码一致/差异说明

- 保留了 `Iin_MA_Signal` 的快慢均线交叉箭头、方向反手和固定 `SL/TP` 主流程。
- `MMRec` 当前按最近同方向闭合交易结果做单净头寸近似：若最近 `TotalTrigger` 笔中亏损笔数达到 `LossTrigger`，则下一次该方向信号使用 `SmallMM_`，否则使用 `MM`。
- 原版通过买卖不同 magic 统计同向历史结果；当前版本在单净头寸框架下分别维护多头和空头历史结果队列来近似实现。
- 原说明示例为 `GBPJPY H1`，仓库当前没有对应数据，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H1` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_iin_ma_signal_mmrec.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H1` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
