# 0234 Exp X2MACandle MMRec

## 策略来源

- MT5 源码：`ea/0234_Exp_X2MACandle_MMRec/Exp_X2MACandle_MMRec.mq5`
- 指标源码：`ea/0234_Exp_X2MACandle_MMRec/X2MACandle.mq5`
- 指标源码：`ea/0234_Exp_X2MACandle_MMRec/X2MA.mq5`

## 策略逻辑

- EA 读取 `X2MACandle` 的颜色缓冲区：`2` 视为多头蜡烛，`0` 视为空头蜡烛。
- 颜色切换到多头时开多并关闭空头；切换到空头时开空并关闭多头。
- 使用 `MMRec` 逻辑：同方向连续亏损达到阈值后，将下一笔手数从 `MM` 切换到 `SmallMM_`；盈利后恢复。
- 使用固定 `SL/TP`。
- 当前实现用 `M15` 作为执行周期，并重采样得到 `H6` 信号周期。

## 与源码一致/差异说明

- 保留了 `X2MACandle` 颜色翻转、`MMRec`、固定 `SL/TP` 和反手主流程。
- 原版 `X2MA` 对每个价格序列做两次平滑：默认第一层为 `SMA`，第二层为 `JJMA`。
- 当前 backtrader 版本忠实覆盖源码默认的第一层 `SMA` 路径，并用本地递推式低滞后平滑近似第二层 `JJMA`，因此这是一个近似迁移版本，而非逐公式完全复刻。
- 原版 `X2MACandle` 还会按 `Gap` 参数抹平小缺口；当前实现保留了这一行为的近似处理。
- 当前仓库没有原说明对应的 `USDJPY H6` 数据，因此这里使用 `XAUUSD_M15.csv` 并重采样 `H6` 进行可运行验证。
- MT5 原版通过不同 `magic` 分离多空统计；当前 backtrader 版本采用单净头寸近似，但仍保留按方向分开的 `MMRec` 亏损计数。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_x2macandle_mmrec.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H6` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
