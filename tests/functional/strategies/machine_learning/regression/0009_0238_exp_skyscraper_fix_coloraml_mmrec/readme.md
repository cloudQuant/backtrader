# 0238 Exp Skyscraper Fix ColorAML MMRec

## 策略来源

- MT5 源码：`ea/0238_Exp_Skyscraper_Fix_ColorAML_MMRec/exp_skyscraper_fix_coloraml_mmrec.mq5`
- 指标源码：`ea/0238_Exp_Skyscraper_Fix_ColorAML_MMRec/skyscraper_fix.mq5`
- 指标源码：`ea/0238_Exp_Skyscraper_Fix_ColorAML_MMRec/coloraml.mq5`

## 策略逻辑

- EA 由两个子系统组成：
  - `A = Skyscraper_Fix`
  - `B = ColorAML`
- 任一子系统在其信号周期发生方向切换时，都可以触发对应方向开仓。
- `A` 系统在 `Skyscraper_Fix` 颜色切到多头时开多并平空，切到空头时开空并平多。
- `B` 系统在 `ColorAML` 颜色切到 `2` 时开多并平空，切到 `0` 时开空并平多。
- 两个子系统分别维护自己的 `MMRec` 参数：当最近同方向连续亏损达到阈值后，下一笔仓位从常规 `MM` 切到 `SmallMM`。
- 当前 backtrader 实现使用 `M15` 执行周期，并重采样得到 `H4` 信号周期。

## 与源码一致/差异说明

- 保留了 `Skyscraper_Fix` 与 `ColorAML` 双系统、固定 `SL/TP` 和 `MMRec` 主流程。
- `ColorAML` 已按源码中的分形维度自适应平滑公式直接转写为 Python。
- MT5 原版通过不同 `magic` 允许 `A/B` 子系统各自独立持仓；当前 backtrader 迁移框架仍是单净头寸模型，因此这里采用“同一时刻只保留一笔当前激活子系统仓位”的近似实现。
- `MMRec` 的底层 `TradeAlgorithms.mqh` 细节仓库中未提供，当前版本按“同方向连续亏损计数达到阈值时切换到 `SmallMM`，盈利后恢复 `MM`”进行近似还原。
- 原 readme 示例数据为 `GBPJPY H4`，当前仓库没有对应 CSV，因此这里使用 `XAUUSD_M15.csv` 并重采样为 `H4` 做可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_skyscraper_fix_coloraml_mmrec.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H4` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
