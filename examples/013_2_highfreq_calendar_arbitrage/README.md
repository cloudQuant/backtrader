# 013_2 高频跨期套利（螺纹钢 rb 主力 / 次主力）

三件套结构：`strategy.py` + `config.yaml` + `run.py`（与 013_1 同构，参数更激进）。
信号与接线同样复用框架：`bt.indicators.SpreadZScore` 与
`examples/007_ctp/ctp_example_support.py`。

- 标的：rb 最近两个满足到期保护的季月（如 `rb2701`/`rb2705`；`--symbols` 可覆盖）
- 信号：价差 z-score 突破 ±1.5σ 开仓（单次确认、间隔 0.1s），回归 0.3σ/超时 120s 平仓
- 执行：同 013_1 的逐腿限价 IOC 纪律；rb 为上期所品种，平仓用 `close_today`

> "高频"指事件驱动 + 激进参数；CTP 下单为 TCP 往返，并非微秒级 HFT。

```bash
python examples/013_2_highfreq_calendar_arbitrage/run.py --replay --scenario profitable
python examples/013_2_highfreq_calendar_arbitrage/run.py --config config.yaml
```
