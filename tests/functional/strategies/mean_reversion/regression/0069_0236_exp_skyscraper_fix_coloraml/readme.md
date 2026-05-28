# 0236 Exp Skyscraper Fix ColorAML

## 策略来源

- MT5 源码：`ea/0236_Exp_Skyscraper_Fix_ColorAML/exp_skyscraper_fix_coloraml.mq5`
- 指标源码：`ea/0236_Exp_Skyscraper_Fix_ColorAML/skyscraper_fix.mq5`
- 指标源码：`ea/0236_Exp_Skyscraper_Fix_ColorAML/coloraml.mq5`

## 策略逻辑

- EA 由两个子系统组成：
  - `A = Skyscraper_Fix`
  - `B = ColorAML`
- `A` 系统在 `Skyscraper_Fix` 方向切换时开仓，并关闭相反方向仓位。
- `B` 系统在 `ColorAML` 颜色切换到 `2/0` 时分别开多/开空，并关闭相反方向仓位。
- 两个子系统都使用固定 `MM`、固定 `SL/TP`。
- 当前实现用 `M15` 作为执行周期，并重采样得到 `H4` 信号周期。

## 与源码一致/差异说明

- 保留了 `Skyscraper_Fix + ColorAML` 双系统、固定 `SL/TP` 和信号反手主流程。
- `ColorAML` 使用源码中的分形维度自适应平滑公式转写为 Python。
- MT5 原版通过不同 `magic` 支持两个子系统各自独立持仓；当前 backtrader 版本仍采用单净头寸近似，因此同一时刻只保留一笔激活子系统仓位。
- 当前仓库没有 `GBPJPY H4` 数据，因此这里使用 `XAUUSD_M15.csv` 并重采样 `H4` 进行可运行验证。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_skyscraper_fix_coloraml.py`：指标与策略实现。
- `run.py`：读取 `XAUUSD_M15.csv` 并重采样 `H4` 后回测。
- `config.yaml`：策略参数、数据区间和回测配置。
