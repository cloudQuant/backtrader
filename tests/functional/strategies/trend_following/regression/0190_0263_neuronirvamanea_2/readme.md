# 0263 NeuroNirvamanEA 2

## 策略来源

- MT5 源码：`ea/0263_NeuroNirvamanEA_2/neuronirvamanea_2.mq5`
- 指标源码：`ea/0263_NeuroNirvamanEA_2/laguerre_plusdi.mq5`
- 指标源码：`ea/0263_NeuroNirvamanEA_2/silvertrend_signal.mq5`

## 策略逻辑

- EA 基于三个感知机分支组合信号交易。
- 最终运行态按 readme 固定为 `pass=3`。
- `Perceptron3 > 0` 且 `Perceptron2 > 0` 时开多，使用 `tp2/sl2`。
- `Perceptron3 <= 0` 且 `Perceptron1 < 0` 时开空，使用 `tp1/sl1`。
- 单次仅保留一笔仓位。
- 超出允许交易时间窗口时，若有持仓则立即平仓。
- 当前 backtrader 实现直接使用 `M15` 数据回测。

## 与源码一致/差异说明

- 保留了时间窗口、单仓位、`Supervisor()` 决策和 `pass=3` 最终运行态主流程。
- `Laguerre_PlusDi` 与 `SilverTrend_Signal` 当前使用本地可运行近似实现来生成 perceptron 输入，因此这是结构近似而非逐像素指标复刻。
- 原 readme 强调需要三阶段优化；这里不复现优化流程，而是按最终运行态直接验证固定参数版本是否可运行。

## 运行方式

```bash
python run.py
```

## 文件说明

- `strategy_neuronirvamanea_2.py`：策略与代理指标实现。
- `run.py`：读取 `XAUUSD_M15.csv` 后回测。
- `config.yaml`：策略参数、时间窗口和回测配置。
