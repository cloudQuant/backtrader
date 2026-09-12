# 迭代 25：CTP 期权期货 tick 回放候选

这是一个独立的 C/P/F 三腿 tick-only 回放示例。它只依赖本目录、标准库和公开的
`backtrader` 接口；不会 import、读取或通过路径注入依赖其它 `examples/` 目录。

本例使用 `Cerebro.run(channel=...)`、`Event`、`TickEvent` 和 `TickBroker`。策略只有
`notify_tick` 能创建本地的普通候选 intent；`next`、`notify_bar` 和 `notify_idle` 只保留
兼容/安全观察行为。每个完整 cohort 先做经济方向和净边际筛选，只有连续两轮同方向合格
cohort 才能创建 intent；无边际、方向切换、重复载荷/序号、质量失败、scope 变化或过期都会
清除确认。默认配置为可直接运行的 `replay/formula`，它只读取本目录的冻结 fixture。
本例没有网络适配器，因此显式请求 shadow、SimNow 或 production 都会在建立会话前失败关闭。

运行前需要安装包含公开 cohort API 的当前 `backtrader` 包：
`backtrader.feeds.CtpQuoteCohortValidator` 和 `CtpCohortNow`。在源码检出中可执行：

```bash
cd examples/015_ctp_options_highfreq
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pip install -e ../..
```

这是本例唯一的运行时库依赖；它不读取、不导入或通过路径注入依赖其它 `examples/` 目录。

直接运行本地零写回放：

```bash
cd examples/015_ctp_options_highfreq
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python run.py
```

可选 `--scenario valid_cohort --output-dir /tmp/iter25-options-replay` 生成本地报告；显式的
`--mode replay --purpose formula` 与默认值相同。

`fixtures/three_leg_tick_cohorts_v1.json` 是合成输入。它会产生两次三腿更新的有效 cohort，
因此可得到一个 `NOT_SUBMITTED_REPLAY` intent。它不表示真实 CTP 行情、排队位置、成交、
费用、保证金、收益或 HFT 资格。输出始终记录：

- `external_network_requests: 0` 与 `external_write_requests: 0`；
- `actual_fills: 0`、`execution_basis: none` 和 `pnl_fields_emitted: false`；
- `hft_status: NOT_ADMITTED`。

可用的本地场景是 `valid_cohort`、`insufficient_cohort`、`duplicate_payload`、`stale_source`、
`mixed_trading_day` 和 `bar_only`。这些场景覆盖重复载荷不能充当第二次更新、来源时间不新鲜、
混合 TradingDay 不能组成 cohort，以及 bar 回调不能创建普通 intent。`notify_idle` 只有在收到
显式的同域可信时钟时才重验缓存，不能使用最后一条 tick 的时间或凭缓存 edge 创建 intent；本地
只输出 1s/3s/60s 的离线期限投影，不生成撤单、减险或第二账本。`config.yaml` 和 fixture 均不含
凭据；若未来需要本地秘密，只能保存在本目录已忽略的 `.env` 中。
