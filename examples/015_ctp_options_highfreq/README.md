# 迭代 25：CTP 期权期货 tick 回放候选

这是一个独立的 C/P/F 三腿 tick-only 回放示例。它只依赖本目录、标准库和公开的
`backtrader` 接口；不会 import、读取或通过路径注入依赖其它 `examples/` 目录。

本例使用 `Cerebro.run(channel=...)`、`Event`、`TickEvent` 和 `TickBroker`。策略只有
`notify_tick` 能创建本地的普通候选 intent；`next`、`notify_bar` 和 `notify_idle` 只保留
兼容/安全观察行为。每个完整 cohort 先做经济方向和净边际筛选，只有连续两轮同方向合格
cohort 才能创建 intent；无边际、方向切换、重复载荷/序号、质量失败、scope 变化或过期都会
清除确认。默认配置为可直接运行的 `replay/formula`，它只读取本目录的冻结 fixture。

`timing` 配置固定 HF-T1 的本地时序投影边界：每腿 1 秒、未对冲 3 秒、最大持仓 60 秒和
idle 50ms。默认 `runtime_provider: unavailable`，所以普通 replay 仍明确为
`OFFLINE_SIGNAL_ONLY`；它不会把 cohort 接收时间重命名为 native send 或真实风险期限。
单元测试可注入带完整 environment/account/TradingDay/generation/subscription/rules/domain scope
的合成只读 snapshot。每个可信 tick（包括随后被 cohort 校验拒绝的报价）都会先推进保护
投影；只有完整合格 cohort 才能记录普通候选或零写 normal-exit proposal。它只能生成 immutable 的 `OBSERVE`、
`PROTECT` 或 `NORMAL_EXIT_PROPOSAL` 记录，所有 proposal 的 `native_write_eligible` 都是 `false`。
该路径不创建 SDK/CTP client、不调用下单/撤单，也不能成为执行批准、真实成交、平仓、HFT 或
收益证据。

## SimNow 环境选择（迭代 30）

`config.yaml` 的 `environment` 选择一个**冻结环境键**，默认 `simnow_first_group1`
（第一套，真实市场时段；迭代 25 的 G3 门要求第一套）。键到 SDK profile 的映射冻结在
`run.py::ENVIRONMENT_PROFILES`，前置地址由 `bt_api_ctp` 拥有，本目录不写任何端点：

| 冻结键 | 族 | SDK profile | 族内备选 |
| --- | --- | --- | --- |
| `simnow_first_group1` | set1 | `set1_group1` | `set1_group1_vpn` |
| `simnow_first_group2` | set1 | `set1_group2` | 无（本机不可达，必须失败关闭） |
| `simnow_second_7x24` | set2 | `set2_7x24_4000x` | 无 |

运行前用 `ITER30_SIMNOW_PROFILE` 覆盖（也可写在本地 `.env` 里）。标称对不可达时**只允许**
在同一族内回退到上表的备选；跨族、未知键、以及与所选冻结对不一致的
`CTP_TD_FRONT`/`CTP_MD_FRONT`/`CTP_ENV_PROFILE` 都会失败关闭，选路从不依据 IP 或地理。
`idle` 的无参回调在**没有任何可信时钟来源**时只计数跳过，不再 latch 成时钟违规；注入的
时钟来源失败或违规仍然 latch。

## live 只读观测（分层，不构成可交易证据）

`simnow_launcher.py` 是唯一的 live 入口：它先做制品前置检查（加载的 `backtrader` 必须是
本仓源码，否则以 `BACKTRADER_ARTIFACT_MISMATCH` 失败关闭；诊断用的
`ITER30_ALLOW_EXTERNAL_BACKTRADER=1` 产物不得作为 G3/G4 证据），再用只读
`market_data_only=True` 链路运行有界观测。报告按层给出独立结论：

| 层 | 含义 | CTP 上的当前状态 |
| --- | --- | --- |
| L0 | 连接只读：会话身份、只读就绪、执行门未武装、写入尝试为 0 | `PASS` |
| L1 | 订阅与 tick 到达：每腿计数、`idle_without_trusted_now_count`、`clock_violation_count` | `PASS` |
| L2 | quote 资格：时钟质量、freshness、`quality_flags` 为空、`execution_eligible` | `BLOCKED_BY_UPSTREAM_QUALIFICATION`（`UPSTREAM_EXECUTION_NOT_ISSUED`） |
| L3 | cohort 成立 | 随 L2 阻塞 |
| L4 | 经济 screen | 随 L2 阻塞 |

L2 的原因是结构性的：`bt_api_ctp` 的 managed receipt 刻意不签发执行资格
（`execution_qualified=False`），而 `CtpQuoteCohortValidator` 要求
`execution_eligible is True` 且 `quality_flags` 为空。因此在本机 CTP 链路上**无法**得到
合格 cohort 或经济 screen；`BLOCKED` 不等于 `NOT_RUN`，解除条件是上游提供可签发的原生
资格证据链（属 SDK 仓库工作项）。replay 路径的资格字段是示例自己写死的，只能作为公式
证据。迭代 25 的 G3 在此期间保持 `INCOMPLETE`，且不得以阻塞为理由放宽门限。

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

只读 live 观测（凭据只在本目录被忽略的 `.env`）：

```bash
cd examples/015_ctp_options_highfreq
PYTHONPATH=/Users/yunjinqi/Documents/new_projects/backtrader \
SIMNOW_LAUNCHER_RUN_SECONDS=60 \
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python simnow_launcher.py
```

`fixtures/three_leg_tick_cohorts_v1.json` 是合成输入：合约元数据绑定到记录的 CZCE
instrument 查询（`metadata_evidence`，含 `legs_sha256` 自校验，并纳入 bundle 身份哈希），
报价本身仍是合成的、与真实 970 平价自洽。它会产生两次三腿更新的有效 cohort，
因此可得到一个 `NOT_SUBMITTED_REPLAY` intent（conversion 净边际 40 CNY，reversal −160）。
它不表示真实 CTP 行情、排队位置、成交、
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

