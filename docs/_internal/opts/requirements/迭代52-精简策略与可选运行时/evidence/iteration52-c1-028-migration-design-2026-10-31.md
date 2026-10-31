# 迭代52 C1：028 Alpha003 SimNow 分钟示例迁移设计（职责拆分、四文件骨架与可行性）

- 日期：2026-10-31
- 类型：设计/静态研究。**未修改 028 任何文件，未运行 provider/账户操作，未读取 `.env`/私有配置，未提交。**
- 任务基线：任务书给出的 Backtrader `dev` `89d8e8bd5`。实际只读检查时 checkout 已前进到 `5328f36bd`（仅新增 052 的 production-bound live boundary 模板与测试；`89d8e8bd5..5328f36bd` 对 `examples/unified/028_alpha003_simnow_minute/` 和本设计引用的 Backtrader 框架模块无改动）。
- 相关输入：`I52-C-策略与示例迁移.md`、`A0-028实盘示例调用链.md`、`A0-总清单与验收索引.md`（EX-10/DF-05/RT-*）、`迭代52-开发交接说明.md`、`迭代52-验收矩阵-2026-10-31.md`，以及 028/052 当前公开源码。
- 028 `config.yaml` 是 tracked 的公开 fail-closed 模板（README 明确说明），可作为公开配置审查对象；`simnow_profile.py` 是 untracked 文件，本设计不依赖其内容，也不把它计入新入口。

## 0. 结论摘要

1. 028 当前 `--mode live` 实际是 SimNow direct CTP **外部模拟账户**，按 I52 语义属于 `paper`；生产 `live` 在 028 中没有任何 endpoint/账户/执行路径。迁移后应只保留 `paper` 可执行配置和 `live` 安全拒绝配置，不再把 `live` 当作 SimNow 别名。
2. 028 的规模是迁移的主要障碍：`run.py` 11,948 行（11,339 非空），`alpha003_strategy.py` 7,853 行（7,463 非空），其中 `plan_alpha003_orders` 862 行、`Alpha003TargetStrategy` 约 4,141 行。**不可能在 800 非空行内原样搬运**，必须按职责裁剪：保留策略政策与最小风控，把 journal/tape/restart/query-refresh/epoch/replay/shadow 明确延期并留在旧目录。
3. 当前已接受的 `DirectBacktraderSession`（052 使用）**不能直接运行 028**：它的 `_build_cerebro()` 固定用 `store.getdata(dataname=symbol, timeframe=..., orderbook_as_ticks=...)` 创建单周期 Feed，没有 feed/cohort 注入点；028 的 `LiveFactorSet.bind()` 要求每个 Feed 都是被同一个 `LiveBarCohort` 激活的精确 `BtApiFeed`。这是第一阻塞项。
4. 推荐的最小迁移路径：给 `DirectBacktraderSession` 增加三个**加法式**公共钩子（`data_factory`、`cerebro_setup`、`session_clock`），再加一个 028 文件夹内的多目标 SimNow support 模块；本轮先通过 source/fake（同一策略源码 + paper/live 两份 ResolvedPlan + fake provider leaf），真实 SimNow paper 运行需要外部交易时段与账户条件，且仍受 OrderRef/撤单身份缺口约束。
5. 新策略文件可以控制在约 720-790 非空行：只保留 Alpha003 选标、tie-break、5-grid 调仓、多空目标、基础 notional/loss/stop/intents 与 run-end 平仓；dated close、fee reserve、margin、journal/restart、query-refresh 全部延期。

## 1. 028 现状与职责规模

### 1.1 文件与行数（当前 checkout 实测）

| 文件 | 总行 | 非空行 | 当前角色 |
| --- | ---: | ---: | --- |
| `run.py` | 11,948 | 11,339 | CLI/tier、配置 v1、选择/日历/cohort、Feed/Broker/Store 装配、query refresh、decision tape、journal、epoch/restart、replay/research、shutdown |
| `alpha003_strategy.py` | 7,853 | 7,463 | 事实 dataclass、订单规划器、策略政策、replay/live 分支、journal/fee-pair/tape、shutdown |
| `protected_simnow.py` | 213 | 185 | 旧 `backtrader_runtime` 的 013_3 protected handoff；**`run.py` 未 import 它** |
| `discovery_lifecycle.py` | 682 | 603 | 只读发现 Store 的正常关闭 helper；**`run.py` 未 import 它** |
| `entry_tier.py` | 124 | 98 | 迭代 43 判层副本；新 schema-v2 入口不再需要 |
| `README.md` | 312 | 274 | 旧入口说明 |
| `config.yaml` | 124 | 114 | 公开 fail-closed v1 模板 |

### 1.2 `run.py` 主要区段

| 行范围 | 职责 | 迁移判断 |
| --- | --- | --- |
| L1-192 | 常量、`RunnerError`、CTP 诊断码 | 少量保留；诊断码可删/移 |
| L193-371 | 基础校验 | 少量保留 |
| L372-539 | v1 配置读取、golden targets、mode/tier | 由 schema-v2 + 新 `run.py` 替换 |
| L540-624 | target id、session docs、selection bundle 读取 | 选择/日历编排保留；bundle 仅离线 |
| L625-936 | CTP query 选择：catalog/depth、主力合约、expected calendar、common grid | 迁到 run.py/support 或公共 helper；复用框架模块 |
| L937-1531 | query 诊断脱敏、golden subset | 诊断保留有限；golden subset 属 shadow/兼容，延期 |
| L1532-1808 | minute tape、factor 参数、research | research/tape 延期 |
| L1809-2072 | calendar/cohort/risk/commission/loss guard/replay budgets | calendar/cohort/risk 保留；commission/loss guard 延期 |
| L2073-2401 | quote tape、replay instrument、replay clock、wall clock、strategy kwargs | quote/instrument/replay clock 延期；wall clock 保留 |
| L2402-5941 | `DecisionTapeWriter` + fee-pair tape/readback | **整体延期**（约 3,500 行） |
| L5942-6306 | tape fee-pair helper、iterator、new tape | 延期 |
| L6307-7347 | restart identity、saved history 载入/校验/readback | 延期（restart 不在 C1） |
| L7348-7560 | `run_replay` + replay 订单摘要 | **replay-only，延期并留在旧目录** |
| L7561-8853 | `QueryRefreshLoop`（account/order/trade/instrument/quote/margin 串行刷新） | **延期**（约 1,293 行） |
| L8854-9330 | cleanup/shutdown 证据、live epoch 失败投影 | 最小子集保留；epoch 部分延期 |
| L9330-9560 | SimNow profile、写门槛、arm templates、signal handler | SimNow 部分迁 support；写门槛进 session/config |
| L9563-9973 | selector policy projection、selection evidence | 选标证据最小子集保留；旧 projection 延期 |
| L9974-10281 | query history projection、shutdown path、live capacity | 延期 |
| L10282-11278 | `run_live` 装配与主循环 | 拆成 session + run.py；仅保留最小路径 |
| L11279-11790 | epoch 切换、`run_live_epochs` | 延期（单 session 足够 C1） |
| L11791-11948 | CLI `run()` | 重写为 schema-v2 CLI |

### 1.3 `alpha003_strategy.py` 主要区段

| 行范围 | 职责 | 迁移判断 |
| --- | --- | --- |
| L1-89 | 常量、类型 | 少量保留 |
| L90-1137 | cohort/factor/account/position/order/quote/instrument/planning input/action/plan dataclass | 约 1,050 行；新策略只保留必要子集 |
| L1138-1753 | dated close、exit intent reserve、风险算术、tick/quote helper | 风险算术部分保留；dated/fee 延期 |
| L1754-2616 | `plan_alpha003_orders`（862 行） | 新策略重写最小版；dated/fee/margin 延期 |
| L2617-2712 | validator、factor spec、live plan | 保留（约 50 行） |
| L2714-3000 | snapshot→policy projection、target selection、preselection gate | **保留并简化**（核心策略政策） |
| L3001-3215 | product key、risk policy、replay quote/session close | risk policy 保留；replay/session close 延期 |
| L3216-3410 | `_live_planning_input`（account/position/working order/quote/instrument → planner） | 最小子集保留；完整 account facts 延期 |
| L3411-3712 | execution evidence payload | 延期/证据子集 |
| L3713-7853 | `Alpha003TargetStrategy`（约 4,141 行） | 重写为约 700 行普通 Strategy |
| L3758-3978 | `__init__`、LiveFactorSet.bind | 保留并简化（约 120 行） |
| L3979-4025 | routes、`_validate_live_execution_binding` | **删除**；绑定校验迁 adapter/admission |
| L4025-4148 | clock/batch/session facts | 保留最小 |
| L4149-4588 | live facts / replay instruments / active orders | 最小 live facts 保留；replay 延期 |
| L4589-5136 | replay planning/dispatch/shutdown | **replay-only，延期** |
| L5137-6177 | live shutdown/fee-pair/tape/source receipt | 延期 |
| L6178-6650 | live grid/risk decision | 简化保留 |
| L6650-7252 | dispatch/live run | 简化保留 |
| L7253-7532 | shutdown 状态机 | 最小 run-end 保留；完整 post-join 延期 |
| L7533-7853 | `prenext`/`next`/`stop`/`notify_*` | 重写最小版 |

## 2. 职责拆分

### 2.1 策略政策（新 `alpha003_pair_strategy.py`）

| 政策点 | 028 现有实现 | 新策略合同 |
| --- | --- | --- |
| Alpha003 字段声明 | `make_alpha003_factor_spec`（`alpha003_strategy.py:2664-2681`）声明 `get_alpha(3)`、`open`/`volume`、direction、mode | 同一份 `FactorSpec`；新文件只保留约 15 行声明，不复制公式 |
| 因子就绪门槛 | `_preselection_block_reason`（L2957-3000）：必须是 `LIVE_READY`、batch complete、receipt 身份一致 | 保留：`readiness is LIVE_READY` + `batch_complete` + `batch_id` 变化才处理 |
| 授权目标 | `authorized_targets` 只影响可交易集合；完整池仍参与横截面 | 保留：`authorized_targets` 参数；缺省为全部 target |
| 选标 | `select_alpha003_targets`（L2860-2956）：过滤 `OUTPUT_AVAILABLE`/finite/product_key；按 `score = value * direction` 取最大/最小；要求至少 2 个且 `high > low`；ties 用 `(product_key, target_id)` 最小 | 保留；目标 `target_position = +1/-1`，这是目标仓位而非订单 |
| 调仓频率 | `eligible_grid_index == 0` 不计数；`index % rebalance_every`；默认 `DEFAULT_REBALANCE_GRIDS = 5`（L4061-4123） | 保留；参数 `rebalance_every`，默认 5 |
| 多空目标 | 只选一多一空；每腿 1 手（`plan_alpha003_orders` 的 `held_quantity + remaining_quantity > 1`，L2269-2270） | 保留一多一空、默认每腿 1 手；`quantity` 显式配置 |
| 风险预算 | `Alpha003RiskPolicy`（L297-359）15 个字段；`plan_alpha003_orders` 检查 hold age、preclose、run-end、stop loss、notional/margin/loss、per-grid/per-run intents、fee reserve | 最小版保留 hold age、run-end/preclose（由 session 传入 close 时间）、stop loss、notional/loss、per-grid/per-run intents；margin/fee/dated 延期 |
| 订单顺序 | `plan_alpha003_orders`：先 cancel/close 减风险，再 open；target 改变先平旧腿 | 保留：先 cancel 未成交、再 close 非目标/到期/止损腿，最后 open 新多空 |
| 订单价格 | 028 用 account/quote facts、tick 对齐、limit price；replay 有独立 quote tape | 最小版用 `self.data.close[0] ± offset_ticks * tick_size` 的 marketable GFD limit；不使用 depth quote；语义变化在 README 明示 |
| 权限 | `_validate_live_execution_binding`（L4001-4024）硬校验 `BtApiBroker`/`RegisteredSimStore`/`simnow-registered-v1`；`run.py:_write_requested`（L9484-9494） | **删除策略内权限/类型校验**；写权限归 schema-v2 capability + grant + session/adapter；策略不判断 mode/provider |
| 交易生命周期 | `prenext`/`next`/`notify_idle`（L7461-7678）、`notify_order`/`notify_trade`（L7756-7853） | 普通 `bt.Strategy`：`nextstart`/`next`/`notify_idle` 驱动 `_on_batch`；`notify_order` 记录状态；`stop` 只做证据/收尾，不承诺平仓 |

**明确禁止**进入新策略的内容：`isinstance(BtApiBroker)`、`RegisteredSimStore`、route id、`replay_mode`、`execution_enabled`、`venue`、`SIMNOW`、`CausalReplayBroker`、`ExecutionDecisionJournal`、`backtrader_runtime`、私有配置/凭据、HTTP/SDK 调用。

### 2.2 可复用机制（复用不变）

| 机制 | 现有 owner | 用法 |
| --- | --- | --- |
| Alpha003 公式/注册 | `backtrader/research/alpha101/alpha003.py:14-44`；`alpha101/__init__.py:220` `get_alpha(3)` | 原样复用；新策略只声明 `FactorSpec` |
| 因子图/调度 | `backtrader/research/live.py:121` `LiveFactorPlan`；`:412` `LiveFactorSet`；`:447` `bind`；`:742` `snapshot` | 原样复用；Strategy 是 owner |
| 因子输入/横截面算子 | `backtrader/research/factor_indicator.py`、`operators.py` | 原样复用 |
| Cohort/日历 | `backtrader/research/live_cohort.py:791` `LiveCohortCalendar`；`:1461` `LiveBarCohort`；`:1667` `register_member`；`:1722` `seal`；`:3639` `current_batch` | 原样复用；由 session/run.py 组装 |
| CTP tick→cohort 源 | `backtrader/feeds/ctp_factor_source.py:58` `CtpFactorSourceCalendar`；`:321` `CtpFactorSourceBinding` | 原样复用；adapter 绑定 |
| 分钟 Feed/cohort 激活 | `backtrader/feeds/btapifeed.py`（`cohort_source_mode`、`bar_watermark_ms`、`live_bar_cohort`） | 原样复用 |
| Cerebro cohort API | `backtrader/cerebro.py:554` `add_live_bar_cohort`；`_cerebro/lifecycle.py:199` `wake_live_bar_cohort` | 原样复用；session 调用 |
| Broker/Store | `backtrader/brokers/btapibroker.py:239` `BtApiBroker`；`backtrader/stores/registered_sim.py:2587` `RegisteredSimStore` | 原样复用；adapter 只补 readiness/arm/stop |
| 多腿 arm | `registered_sim.py:1322` `configure_registered_sim_arm_templates`；`:1679` `ensure_registered_sim_arm_for`；`:1736` `arm_history` | 原样复用；028 两腿切换 |
| CTP 因子源/查询 | `backtrader/stores/btapistore.py:4527` `enable_ctp_factor_tick_source`；`:4699` `registered_sim_collect_futures_snapshot` | 原样复用 |
| 选择/日历框架 | `futures_main_contract.py:2992` `select_main_contracts`；`:739` `MainContractQuerySnapshot`；`futures_expected_calendar.py:385`；`futures_sessions.py:308/752` | 原样复用；run.py/support 编排 |
| 本地 replay | `backtrader/brokers/factor_replay.py` `CausalReplayBroker` | **延期，不运行** |

### 2.3 Provider/CTP 规则（迁 adapter/support 或 run.py）

| 规则 | 028 位置 | 新 owner |
| --- | --- | --- |
| CTP catalog/depth 快照与完整性 | `run.py:625-936`、`_sanitize_ctp_query_diagnostics` L937-1425 | run.py 选择编排或公共 helper；复用 `futures_ctp_snapshot` |
| 主力合约选择（`0.5*OI + 0.5*volume`） | `run.py:625-936`；`futures_main_contract.select_main_contracts` | 复用框架；run.py 调用 |
| 交易日/预期日历/公共分钟网格 | `run.py:625-936, 1890-1954`；`futures_expected_calendar`、`futures_sessions` | 复用框架；run.py 组装 |
| 标准/7x24 前置、front pair 选择 | `run.py:9330-9483`；052 `simnow_runner.py:218-244`；013_3 `simnow_direct.select_front_pair` | SimNow support |
| 官方 SimNow profile 校验 | `run.py:9438-9483`；`protected_simnow._official_profile` | SimNow support |
| 凭据引用/私密 `ctp:` 块 | 052 `simnow_runner._load_private_ctp_block` / `paper_common.load_credentials` | SimNow support；**不读 `.env` 除非 `--live` paper 分支** |
| 每合约 arm/disarm、arm templates | `run.py:9495-9528`；`registered_sim.py:1322-1736` | SimNow support + 框架 Store |
| position_side/offset/hedge flag | `alpha003_strategy.py:6650-6711` | 新策略传通用 `position_side`/`offset`；adapter 只做透传/校验 |
| 订单号/撤单身份 | `run.py` Store 链；052 证据显示会话内 OrderRef 与交易所历史冲突 | **provider gap**，见 §5 |

### 2.4 Backtrader 生命周期

| 生命周期点 | 028 位置 | 新设计 |
| --- | --- | --- |
| Strategy 构造/参数校验 | L3713-3978 | 新 Strategy `__init__`：校验 params、绑定 `LiveFactorSet`；不校验 broker 类型 |
| 每 batch 回调 | L7533-7678（`prenext`/`next`） | `nextstart`/`next` → `_on_batch()`；cohort 无新 batch 时 no-op |
| 空闲驱动 | L7461-7532（`notify_idle`） | `notify_idle` → `_on_batch()` + 维护/超时 |
| 订单/成交通知 | L7756-7853 | `notify_order`/`notify_trade` 记录有限事件；不做 provider 查询 |
| run-end/停机 | L7253-7460、L7734-7755 | 策略在 `session_close_at`/`hard_deadline` 前主动 cancel/close；`stop` 只报告事实 |
| Cerebro 配置 | `run.py:10620-10880` | session 内 `Cerebro(stdstats=False, exactbars=1, runonce=False, preload=False)`；`cerebro_factory` 可提供 |
| Feed 安装/cohort 激活 | `run.py:10690-10820` | session `data_factory` + `cerebro_setup`；Strategy 不碰 Cerebro |

### 2.5 配置/资源编排

| 职责 | 028 位置 | 新设计 |
| --- | --- | --- |
| 配置 schema | `load_config` L372-447（v1） | schema-v2 `bt_api_run_contract.parse_config` |
| mode/tier | `resolve_mode` L521-539；`entry_tier.py` | `plan.mode` 权威；`--dry` 只校验；`--live` 选择执行，不提升 mode |
| 写权限 | `_write_requested` L9484-9494；arm templates | schema capability + `DirectWriteGrant` + adapter arm；策略无权限分支 |
| risk 解析 | `_risk_policy` L1955-1993 | run.py 从 `strategy_parameters` 读取并传给 Strategy |
| Strategy kwargs | `_make_strategy_kwargs` L2333-2401 | run.py 构造最小 kwargs（cohort/params/session close/deadline） |
| Store/Broker/Feed/Cerebro 装配 | `run_live` L10282-11278 | session + support module |
| journal/tape/query refresh/epochs | L2402-5941、L6307-7347、L7561-8853、L11279-11790 | **延期**；旧目录保留 |
| 证据/退出码 | `run()` L11791-11948 | 新 run.py：0/1/2/3；有限证据 JSON |

## 3. 目标布局与公开入口

### 3.1 四文件（加必要 support）布局

用户后续指令允许“必要辅助脚本”，每个文件分别 ≤800 非空行（`迭代52-开发交接说明.md:13`）。因此推荐：

| 文件 | 预算（非空行） | 职责 |
| --- | ---: | --- |
| `README.md` | 120-180 | 用途、paper/live 边界、配置、运行命令、证据/退出码、语义变化与延期项 |
| `config.yaml` | 110-150 | schema-v2 `paper` 模板（SimNow） |
| `config.live.yaml` | 80-110 | schema-v2 `live` 安全拒绝模板（独立 references/credential/scope） |
| `alpha003_pair_strategy.py` | 700-790 | 普通 `bt.Strategy`；Alpha003 选标/调仓/多空/最小风控/run-end；无 provider/mode 分支 |
| `run.py` | 420-560 | CLI、schema-v2 解析、dry、live 拒绝、SimNow paper 分支、session 调用、证据 |
| `simnow_paper_support.py` | 650-790 | 多目标 `RegisteredSimStore` 适配：front/credential/readiness/instrument/reconcile/arm/stop/facts |
| `alpha003_policy.py`（可选 fallback） | 0-280 | 仅当策略文件超过 800 时，把纯选标/规划函数移出；不得放 provider/mode 逻辑 |
| `tests/unit/test_iteration52_alpha003_pair_strategy.py` | 350-550 | 选标/tie-break/调仓/风控/run-end 的 source/fake |
| `tests/unit/test_iteration52_simnow_multi_paper.py` | 300-500 | 多目标 adapter fake：front/arm/readiness/stop |
| `tests/unit/test_iteration52_cohort_session_hooks.py` | 200-300 | `DirectBacktraderSession` 新钩子的 fake 合同 |
| `tests/unit/test_iteration52_alpha003_live_boundary.py` | 120-220 | 两份 ResolvedPlan、同一策略源码、live 拒绝 |

`entry_tier.py` 不进入新 leaf：schema-v2 的 `mode`/`environment` 已表达通道，CLI 只允许 `--dry` 或执行已声明 mode，不再需要 tier 判层。`protected_simnow.py`/`discovery_lifecycle.py` 保留在旧 028 目录（或旧 runtime 归档），不作为新入口依赖。

052 的 `config.live.yaml` 与 `tests/unit/test_iteration52_live_boundary.py` 是当前已提交的 live 边界范式（HEAD `5328f36bd` 新增）：live 模板的 provider/endpoint/account/credential/scope 与 paper 完全不相交，`--live` 无写授权先 `write_not_authorized`，有授权后由 session 在 provider 传输前拒绝 `live_write_not_authorized`。028 复用该范式，只把 references/credential/scope 换成 CTP 生产占位，`references.strategy` 保持与 paper 相同。

### 3.2 公开入口调用（当前 + 拟议钩子）

当前 052 已接受的调用：

```python
from bt_api_runtime.direct_backtrader import (
    DirectBacktraderSession, DirectCredentials, DirectProviderProfile, DirectWriteGrant,
)
session = DirectBacktraderSession(
    plan=plan, profile=profile, run_id=run_id,
    credentials=DirectCredentials(credential_values),
    strategy_id="iteration52-alpha003-pair",
    grant=grant,
    store_factory=..., broker_factory=...,
)
report = session.run(Alpha003PairStrategy, strategy_params=..., seconds=session_seconds)
```

028 需要但当前 `direct_backtrader.py` **没有**的加法式钩子（拟议，需在 B/runtime 接受）：

```python
session = DirectBacktraderSession(
    plan=plan, profile=profile, run_id=run_id,
    credentials=DirectCredentials(credential_values),
    strategy_id="iteration52-alpha003-pair",
    grant=grant,
    store_factory=...,                 # 已有
    broker_factory=...,                # 已有
    cerebro_factory=...,               # 已有；返回 exactbars=1/runonce=False/preload=False 的 Cerebro
    data_factory=...,                  # 拟议：data_factory(store, symbol, profile) -> BtApiFeed
    cerebro_setup=...,                 # 拟议：cerebro_setup(cerebro, context) 在 adddata 后、addstrategy 前
    session_clock=wall_clock,          # 拟议：utc_now()/monotonic_ns()/wait_interruptibly
)
```

调用顺序必须是：

1. `preflight()` → Store 启动/login/readiness；support Store 在此后 `enable_ctp_factor_tick_source()`。
2. `_build_broker()` → `BtApiBroker(require_complete_ctp_evidence=True, flatten_on_stop=False, contract_metadata=...)`。
3. `_build_cerebro()` → 对每个 target 调 `data_factory(store, target, profile)`，`cerebro.adddata(data, name=target)`。
4. `cerebro_setup(cerebro, context)` → 逐 target `cohort.register_member(...)`；`cohort.seal()`；`cerebro.add_live_bar_cohort(cohort, clock=session_clock, winddown_timeout_seconds=...)`。
5. `cerebro.addstrategy(Alpha003PairStrategy, **strategy_params)`；`strategy_params` 至少含 `cohort`、`session_close_at`、`hard_deadline_monotonic`、risk/factor 参数。
6. `cerebro.run(runonce=False, preload=False)`；`_shutdown()` → broker.stop → store.stop；support Store 对残仓/活单 freeze。

如果 runtime 不接受上述钩子，则 028 只能走一个**新高层入口**（例如 `DirectFactorSession`），其内部必须完成同样的 1-6；不能靠自定义 `cerebro_factory` 在 `adddata` 后再补 cohort（当前 `_build_cerebro` 会重复添加固定 Feed，且 strategy 在 `addstrategy` 时已需要 cohort 参数）。

### 3.3 新策略骨架（无 provider/mode 分支）

```python
class Alpha003PairStrategy(bt.Strategy):
    params = (
        ("cohort", None), ("factor_mode", "native"), ("direction", 1),
        ("rebalance_every", 5), ("preheat_bars", 30),
        ("authorized_targets", ()), ("quantity", 1),
        ("offset_ticks", 1), ("risk", None),
        ("session_close_at", None), ("hard_deadline_monotonic", None),
    )

    def __init__(self):
        self.live_factors = LiveFactorSet.bind(
            make_alpha003_live_plan(...), {d._name: d for d in self.datas},
            cohort=self.p.cohort,
        )
        self._last_batch_id = None
        self._eligible = 0
        self._targets = ()

    def nextstart(self): self._on_batch()
    def next(self): self._on_batch()
    def notify_idle(self): self._on_batch(); self._maintain()

    def _on_batch(self):
        snap = self.live_factors.snapshot()
        if snap.readiness is not LiveFactorReadiness.LIVE_READY or not snap.batch_complete:
            return
        if snap.batch_id == self._last_batch_id:
            return
        self._last_batch_id = snap.batch_id
        self._eligible += 1
        if self._eligible % int(self.p.rebalance_every):
            return
        decision = select_pair(snap, self.p.authorized_targets, self.p.direction)
        self._dispatch(plan_orders(self, decision, self.p.risk))
```

策略只使用：`LiveFactorSet.snapshot()`、`self.data.close[0]`、`self.broker.getposition(data, side=...)`、`self.buy/sell/cancel`、`self.p.*`。不 import `Backtrader` 之外的 provider/runtime 模块。

## 4. 依赖迁移清单

### 4.1 `run.py` 导入的模块

| 模块 | 角色 | 迁移 |
| --- | --- | --- |
| `entry_tier`（本地） | dry/replay/live 判层 | 新 leaf 删除 |
| `yaml` | v1 配置 | schema-v2 parser 不直接需要；support 读私有 `ctp:` 块需要 |
| `backtrader.feeds.futures_sessions` | session calendar、common minute grid、PlannedCommonMinute | 保留；复用 |
| `backtrader.feeds.futures_selection_io` | 保存的 selection bundle | 保留；离线/source-fake 可用，paper CTP query 不用 |
| `backtrader.feeds.futures_expected_calendar` | 规则推导日历 | 保留；paper 选择用 |
| `backtrader.feeds.futures_main_contract` | 主力合约选择/快照 | 保留；复用 |
| `backtrader.feeds.futures_ctp_snapshot` | CTP catalog/depth 快照错误 | 保留；复用 |
| `backtrader.research.specs` | `ResearchSpec` | research-only，延期 |
| `backtrader.research` `FactorStrategy`/`align_to_grid` | 离线研究 | **延期** |
| `backtrader.research.live_cohort` | `LiveBarCohort`/`LiveCohortCalendar`/`LiveSourceOrigin`/restart | cohort 复用；restart 延期 |
| `backtrader.research.live_capacity` | 容量快照 | **延期** |
| `backtrader.stores.execution_decision_journal` | journal/restart/run-loss | **延期（C1）**；后续复用 |
| `backtrader.stores.factor_execution` | coordinator | **延期（C1）** |
| `backtrader.stores.factor_execution_facts` | typed account/quote facts | 最小子集后续；C1 不依赖 |
| `backtrader.brokers.factor_replay` | `CausalReplayBroker`/`ReplayBarTiming` | **replay-only，延期** |
| `backtrader.feeds.btapifeed` | Feed 类型 | 保留；support 使用 |
| `backtrader.utils.dateintern` | replay 时间转换 | replay-only，延期 |
| `backtrader.brokers.btapibroker` | Broker | 保留；复用 |
| `backtrader.stores.registered_sim` | SimNow Store | 保留；support 子类/工厂 |
| `alpha003_strategy` | 旧策略/risk/replay fact | 新 strategy 替代；旧文件保留 |
| `bt_api_ctp.ctp_env_selector` | 官方 SimNow profile | 保留；support |
| `psutil` | 可选容量 | 延期 |
| `ctypes`/`msvcrt`/`fcntl` | decision tape generation lease | 延期 |

### 4.2 `alpha003_strategy.py` 导入的模块

| 模块 | 角色 | 迁移 |
| --- | --- | --- |
| `backtrader` | Strategy/Order | 保留 |
| `backtrader.research.alpha101.get_alpha` | 公式注册 | 保留 |
| `backtrader.research.specs.FactorSpec` | 因子声明 | 保留 |
| `backtrader.research.live` | LiveFactorPlan/Set | 保留 |
| `backtrader.feeds.futures_main_contract.ProductKey` | target product key | 保留（或从 target id 解析） |
| `backtrader.feeds.futures_sessions.ExchangeSessionCalendar` | session close | 最小保留 |
| `backtrader.brokers.factor_replay.CausalReplayBroker` | replay 校验 | **延期** |
| `backtrader.brokers.btapibroker.BtApiBroker` | 旧 live 绑定校验 | **新增策略不 import** |
| `backtrader.stores.registered_sim.RegisteredSimStore` | 旧 live 绑定校验 | **新增策略不 import** |
| `backtrader.stores.execution_decision_journal` | journal keys/errors/restart | **延期** |
| `backtrader.stores.factor_execution.FactorExecutionError` | coordinator 错误 | **延期** |
| `backtrader.stores.factor_execution_facts` | live facts | 最小子集或延期 |

### 4.3 其他 028 本地模块

| 文件 | 角色 | 迁移 |
| --- | --- | --- |
| `protected_simnow.py` | 旧 runtime protected handoff；`run.py` 未用 | 由 052 风格 private `ctp:` + env names 替代；旧文件留在旧目录/归档 |
| `discovery_lifecycle.py` | 只读发现 Store 关闭；`run.py` 未用 | 留在旧目录；不作为新入口依赖 |
| `entry_tier.py` | 判层副本 | 新 leaf 删除 |
| `simnow_profile.py` | untracked；`run.py` 未 import | **迁移前决定纳入/删除**（A0-OPEN-14）；本设计不使用 |

### 4.4 测试依赖与延期归属

直接引用 028 目录的测试共 27 个文件（`grep -l 028_alpha003_simnow_minute`）；其中 `tests/unit/test_alpha003_simnow_runner.py` 6,789 行、`tests/unit/test_alpha003_simnow_strategy.py` 6,359 行，不能整体迁入 800 行预算的新 leaf。迁移策略是：只把选标/tie-break/调仓/risk/cohort 装配的**有效用例**重写为新测试；runner/tape/restart/epoch/replay/shadow 用例留在旧目录，标记 `DEFERRED`。

| 测试（代表） | 覆盖 | 迁移/保留 |
| --- | --- | --- |
| `tests/unit/test_alpha003_simnow_strategy.py` | 选标/tie-break/调仓/risk/live decision | 子集迁到新策略测试；其余保留旧目录 |
| `tests/unit/test_alpha003_simnow_runner.py` | runner/tape/refresh/epoch | 大部分延期；cohort/calendar 子集可迁 |
| `tests/unit/test_alpha003_simnow_profile.py` | SimNow profile | 迁到 support 测试 |
| `tests/unit/test_alpha003_simnow_profile_runner_integration.py` | profile+runner | 延期/替换 |
| `tests/unit/test_alpha003_protected_simnow.py` | 旧 runtime handoff | **延期/退役候选** |
| `tests/unit/test_alpha003_discovery_lifecycle.py` | discovery close | 保留（support helper） |
| `tests/unit/test_alpha003_simnow_shadow_subset.py` | shadow/golden subset | **shadow，延期** |
| `tests/unit/test_alpha003_simnow_staged_query_runner.py` | CTP query 选择 | 保留/迁到选择 helper 测试 |
| `tests/unit/test_alpha003_simnow_store_config_override.py` | 旧 runner 配置 | 延期/替换 |
| `tests/integration/test_live_alpha003_parity.py` | 因子/cohort 对照 | 框架测试保留 |
| `tests/integration/test_live_alpha003_cohort_scenarios.py` | cohort 场景 | 框架测试保留 |
| `tests/integration/test_alpha003_registered_sim_order_chain.py` | registered-sim 订单链 | 框架/provider 测试保留 |
| `tests/integration/test_registered_sim_factor_risk_rejections.py` | 风险拒绝 | 保留 |
| `tests/integration/test_alpha003_fee_pair_*`、`test_alpha003_decision_tape_capacity.py` | fee-pair/tape | **延期** |
| `tests/integration/test_live_alpha003_history_*` | restart/history | **延期** |
| `tests/integration/test_factor_decision_replay_economics.py` | replay | **replay-only，延期** |
| `tests/integration/test_alpha003_main_contract_rollover_execution.py` | epoch/rollover | **延期** |
| `tests/integration/test_alpha003_md_readonly_write_gate.py` | 旧 write gate | 延期/替换 |
| `tests/integration/test_alpha003_source_receipt_trading_day.py` | source receipt | 延期 |
| `tests/integration/test_ctp_snapshot_query_diagnostics.py` | CTP 查询诊断 | 保留 |
| `tests/unit/research/test_live_capacity.py` | 容量 | **延期** |
| `tests/unit/stores/test_factor_execution_authorized_scope.py` | coordinator scope | **延期（C1）** |
| `tests/unit/test_alpha003_commission_*`、`test_alpha003_loss_trip_shutdown.py` | commission/run-loss | **延期** |
| `tests/unit/test_ctp_factor_source_shutdown.py` | CTP source shutdown | 保留（support） |
| `tests/unit/scripts/test_iteration51_*` | 旧脚本 | 不属于 028 leaf |

## 5. 缺口清单与最小合同

### 5.1 MUST-HAVE（C1 source/fake 或真实 paper 必需）

| ID | 缺口 | 最小合同 | 理由 |
| --- | --- | --- | --- |
| C1-G1 | `DirectBacktraderSession` 无 feed/cohort 钩子 | 增加 `data_factory(store, symbol, profile)`、`cerebro_setup(cerebro, context)`、`session_clock`；在 `_build_cerebro` adddata 后、addstrategy 前调用 setup | 否则 `LiveFactorSet.bind` 无法通过 `BtApiFeed.live_bar_cohort` 校验；028 无法运行 |
| C1-G2 | 052 SimNow adapter 是单合约/单 arm，且拒绝任何持仓/活动单 | 新 `simnow_paper_support.py`：多 target `RegisteredSimStore` 子类/工厂；`contract_metadata` 全 target；`get_environment_info/get_account_config/get_order_readiness/get_instrument_spec/get_reconcile_snapshot/get_execution_summary/stop` | 028 是多 target、双方向；052 的 `SimNowPaperPlan` 单 `instrument` 不能复用 |
| C1-G3 | 多腿 arm 切换未在新示例接线 | 调用 `configure_registered_sim_arm_templates({(instrument, exchange): template})`；每笔写前 `ensure_registered_sim_arm_for` 由 Store 自动执行；记录 `arm_history` | 一个 SDK admission 只授权一个 instrument；028 两腿必须切换 |
| C1-G4 | CTP 选择/主力/日历编排在 028 `run.py` 内 | run.py 或公共 helper 调用 `registered_sim_collect_futures_snapshot` + `select_main_contracts` + `build_expected_daytime_calendars` + `build_common_minute_grid`；source/fake 可用 saved bundle 替代 query | 真实 paper 必须从当前 CTP 会话选择，不能把旧 bundle 当当前账户 |
| C1-G5 | 策略文件需 ≤800 非空行 | 新 `alpha003_pair_strategy.py` 只保留 §2.1；其余延期；必要时拆 `alpha003_policy.py` | 原策略 7,463 非空行，无法原样迁移 |
| C1-G6 | schema-v2 无 inputs/resources 区 | 用 `strategy_parameters` 嵌套 `factor/selection/cohort/risk/session`；target 数 >64 时由 run.py 注入 Python 对象，不写进 config | parser 限 64 params/512 items；028 目标池可到 256 |
| C1-G7 | live 边界模板 | `config.live.yaml`：`mode: live`、独立 provider/endpoint/account/credential/scope、`orders.live.write`；run.py 在凭据/网络前拒绝 `live_write_not_authorized`/`live_provider_unavailable` | C1 要求同一策略源码的 paper/live 两份 ResolvedPlan 与错配拒绝 |
| C1-G8 | OrderRef/撤单身份（052 已观察） | 真实 paper 仅 open/close，尽量不依赖 cancel；若需 cancel，需唯一 OrderRef 或 typed OrderSysID/Front/Session target | 052 证据：会话内 OrderRef 1 与交易所历史冲突，legacy cancel 可能本地 Canceled 而交易所仍活动 |
| C1-G9 | 账户起始 flat | session `preflight` 的 `_reconcile` 要求无持仓/无活动单/无 unknown；028 必须在 flat 账户上开始，run-end 平仓后再 disarm | 当前 session 不支持带仓启动；restart 延期 |
| C1-G10 | `simnow_profile.py` untracked 归属 | 迁移前决定纳入或删除（A0-OPEN-14）；不读内容做普通审查 | 可移植性与 028 迁移依赖未证 |

### 5.2 DEFERRED（本轮不做，保留旧目录/测试）

| ID | 项 | 延期理由 |
| --- | --- | --- |
| C1-D1 | `ExecutionDecisionJournal` + `DecisionTapeWriter` + fee-pair/tape/restart | 约 3,500+ 行；C1 最小 paper 不需要 durable 因子决策；后续按 A0/C2 单独迁 |
| C1-D2 | `QueryRefreshLoop`（account/order/trade/instrument/quote/margin） | 约 1,293 行；最小 paper 用 Broker 持仓/现金与策略本地状态即可；完整账户权威风控后续 |
| C1-D3 | epoch/daily rollover/query history/saved history | 单 session 足够 C1；多 epoch 需要完整 shutdown/restart 证明 |
| C1-D4 | replay（`CausalReplayBroker`、quote/instrument tape、replay clock） | I52 明确不运行/不验收 replay；源码和测试留在旧目录 |
| C1-D5 | research（`FactorStrategy`/`align_to_grid`/pandas/ResearchSpec） | 非 paper/live；保留旧入口 |
| C1-D6 | shadow / golden subset | I52 不做 shadow；旧 `_apply_golden_target_subset` 与测试保留 |
| C1-D7 | fee reserve/fee projection/run-loss guard/dated close legs | 需要 provider fee/account facts 与 journal；C1 最小版不含 |
| C1-D8 | margin budgets / depth quote execution | 需要 per-instrument margin/quote facts；C1 用 notional + close±tick marketable limit |
| C1-D9 | `protected_simnow.py` 旧 runtime handoff | 由 052 风格 private `ctp:` + env names 替代；旧文件保留归档 |
| C1-D10 | 生产 live adapter / real live write | 无生产 endpoint/账户/授权；只保留安全拒绝 |
| C1-D11 | 99 案 / Optional16 / 007-015 迁移 | C2 范围，不在 C1 |
| C1-D12 | `discovery_lifecycle.py` | `run.py` 未用；保留为 support/reference |

## 6. 验收路径（建议）

### 6.1 本轮可接受的 source/fake（不触达 provider/账户）

1. **Runtime 钩子合同**：fake Store/Broker/Cerebro/Feed，验证 `data_factory` 返回的 Feed 被 `adddata(name=target)`；`cerebro_setup` 在 `addstrategy` 前注册成员/seal/`add_live_bar_cohort`；`session_clock` 被 grant/cohort 共用。
2. **策略政策**：用合成 `LiveFactorSet`/cohort 快照，验证：只处理 `LIVE_READY`+complete；第 0 个 eligible grid 不交易；每 5 个 grid 调仓；authorized subset 不缩小因子池；top/bottom + tie-break `(product_key, target_id)`；direction 只乘一次；`high == low`/不足 2 个不产生目标；run-end 先平仓。
3. **SimNow 多目标 adapter**：fake front selector、fake Store readiness、fake account/instrument/position/order rows；验证：多 target `contract_metadata`、每腿 arm 切换、flat 前置、残仓 freeze、stop 证据、凭据只按 env name。
4. **两份 ResolvedPlan**：`config.yaml`（paper）与 `config.live.yaml`（live）解析；策略引用相同、源码 SHA 相同；references/credential/scope 不相交；paper+production profile → `paper_provider_environment_mismatch`；live+simulation profile → `live_provider_environment_mismatch`；live grant 无 `allow_live_write` → `live_write_not_authorized`；全程无凭据/网络/Store 启动。
5. **dry**：`python run.py` exit 0，不读凭据/私有配置；`python run.py --config config.live.yaml --live` → BLOCKED `write_not_authorized`（exit 2）；`--allow-write` → `live_write_not_authorized`/`live_provider_unavailable`（exit 2/1，取决于实现），在 provider 传输前。
6. **行数/形态**：新 leaf 每个文件 ≤800 非空行；普通 Strategy/Cerebro；无 `bt_api_gateway/risk/monitor/execution` import；无 `backtrader_runtime` import。

**本轮状态应记为 `SOURCE_FAKE` / 028 迁移 `PARTIAL`，不是 paper PASS。**

### 6.2 需要真实账户/外部条件（不能由 source/fake 替代）

1. SimNow 标准前置在交易时段可达；账户 flat；私有 `ctp:` 块 1-8 组完整 MD/TD pair；凭据在 `.env`/私有配置（真实运行才读）。
2. 1-minute cohort 预热（≥30 bars）；选择当前 CTP 可见 catalog/depth 的主力合约；构建 common minute grid。
3. 开多/开空各 1 手，marketable GFD limit；等待 N 个 grid 或 `session_close_at`；平多/平空；最终 provider 查询 positions/orders 为空；`disarm`/`freeze` 证据。
4. 若任一腿未成交/未平仓：返回 `BLOCKED`/`UNKNOWN`，不得以进程退出冒充 flat。
5. 真实结果只能记 `PAPER`；生产 `live` 仍 `NOT_AUTHORIZED`。

### 6.3 真实 paper 前必须解决的外部/工程条件

- C1-G1 钩子已接受并发布（否则 028 无法组合）。
- C1-G2/G3 多目标 adapter/arm 已通过 fake 与真实 preflight。
- C1-G8 OrderRef/撤单身份：至少 open/close 不依赖 cancel；若要 run-end cancel，需唯一 Ref/typed target。
- 账户 flat、无历史活动单；否则 `reconcile_exposure_present` 拒绝。
- SimNow front 选择与交易时段；7x24 的 stale event clock 不能用于本策略的 minute cohort（028 README 已记录该环境问题）。

## 7. 风险与未决

1. **语义变化**：新策略用 close±tick marketable limit，不再使用 depth quote；没有 fee/margin/date close；没有 durable 因子 journal。必须在 README 明确写出，不得声称与旧 028 行为等价。
2. **策略行数**：700-790 是紧预算；若选标/规划超限，按 §3.1 拆 `alpha003_policy.py`，但不得把 provider/mode 逻辑塞进策略。
3. **重复实现**：052 `simnow_paper.py` 的 readiness/stop 逻辑与 028 多目标版会重复；本轮先独立，后续在 C2 抽公共 support，避免改动已验收的 052。
4. **OrderRef/撤单**：052 未提交的 cancel 修复（`cancel_order` verified target）正在开发；不能把未提交/未验收代码当作 028 的 cancel 依据。
5. **旧 runtime**：`protected_simnow.py` 依赖 `backtrader_runtime`；新 leaf 不使用它，但旧文件仍在树中，R10 退役前必须保留/归档，不能删除。
6. **untracked `simnow_profile.py`**：A0-OPEN-14 未决；迁移前必须决定纳入或删除；本设计未使用其内容。
7. **当前 checkout 前进**：`5328f36bd` 新增 052 live boundary；本设计引用该模式，但不把 052 的 Binance references 当作 028 的 CTP 生产路由。

## 8. 引用索引（关键行号）

- 028 `run.py`：config L372-447；selection L540-936；calendar/cohort/risk L1809-2072；strategy kwargs L2333-2401；tape L2402-5941；restart L6307-7347；replay L7348-7560；query refresh L7561-8853；cleanup L8854-9330；SimNow profile/arm L9330-9528；selection evidence L9563-9973；run_live L10282-11278；epochs L11279-11790；CLI L11791-11948。
- 028 `alpha003_strategy.py`：risk policy L297-359；plan L1754-2616；factor spec/live plan L2664-2712；policy input/target L2714-3000；live planning L3216-3410；strategy L3713-7853；live binding L4001-4024；replay L4589-5136；fee-pair/tape L5137-6177；live decision L6178-6650；dispatch/run L6650-7252；shutdown L7253-7532；lifecycle L7533-7853。
- 框架：`backtrader/research/live.py:121/412/447/742`；`live_cohort.py:791/903/1461/1667/1722/3639`；`feeds/ctp_factor_source.py:58/321`；`feeds/futures_sessions.py:308/752`；`feeds/futures_main_contract.py:739/2992`；`feeds/futures_expected_calendar.py:385`；`stores/registered_sim.py:1322/1679/1736/2587/4028/4042/4646`；`stores/btapistore.py:4527/4699`；`brokers/btapibroker.py:239/3495`；`brokers/factor_replay.py`；`research/alpha101/alpha003.py:14-44`；`alpha101/__init__.py:220`。
- Runtime：`D:/bt_api_py/bt_api/bt_api_runtime/runtime/src/bt_api_runtime/direct_backtrader.py:365-480`（session 构造）、`:542-560`（preflight）、`:591-706`（run）、`:688-730`（broker/cerebro）、`:762-790`（shutdown）。
- 052 参考：`run.py` 350 非空行、`provider_demo_roundtrip_strategy.py` 240、`simnow_runner.py` 429、`simnow_paper.py` 786、`config.simnow.yaml` 69；`README.md:31-44` 说明 SimNow checkout-bound 与撤单缺口。
- 证据：`iteration52-c2-simnow-paper-2026-10-31.md`（SimNow 1 手开/平 PASS、撤单 BLOCKED/OrderRef 根因）；`iteration52-c1-two-provider-paper-2026-10-31.md`（同一策略双 provider）；`iteration52-b2-installed-and-journal-durability-2026-10-31.md`（journal 持久化）。
