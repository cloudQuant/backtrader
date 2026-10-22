# 迭代42 R1/R2 进度与现场记录（2026-10-10）

状态（2026-10-10 更新）：R1 实现轮已提交（`eb3da84f3`），真实成交往返待周一 CZCE 时段；
R2 实现轮已提交（`7cfad68bc`），Demo 成交往返证据化 BLOCKED（资格工件窗口过期，翻转路径见 r2 记录）；
R3（012_2）已提交（`90cf8914a`），结构性 BLOCKED（HFT 未准入，见 r3 记录）；
R4（013_1）已提交（`0150641a3`），实现+离线验收完成（见 r4 记录）；
R5（013_2）实现+离线验收完成（见 r5 记录）；R1/R4/R5 真实成交往返均待周一 DCE/CZCE/SHFE 时段。
本文件为现场进度备忘。

## 提交

- R1（013_3 四件套+SimNow registered-sim 管线）：`eb3da84f3`（18 文件）。
- R2（012_1 四件套+双所 Demo 门）：`7cfad68bc`（17 文件）。
- 工作树保留无关既有修改（backtrader_runtime/*、tests/unit/runtime 某测试、`0` 删除等），未提交。

## R0 决定（已完成，写入计划 §5.1）

SimNow 执行采用**直连 registered-sim 窄口径准入**（eval：Store/managed/facade 写路线保持关闭）。
源码级核验：`btapistore.py:7796/8137` 硬关闭、facade `_reject_simnow_native_execution`、
SDK `arm_execution_for_registered_sim`（client.py:7055，返回 capability）。

## R1 实现要点（013_3 四件套化）

- 文件布局：`run.py`（新标准入口）/ `config.yaml`（扁平冻结段 + 迭代42 新段）/
  `sa_midfreq_strategy.py`（原 strategy.py）/ `README.md`；内部模块 `simnow_direct.py`、
  `legacy_runner.py`（原 run.py 内容 + 迁移性修正）、其余冻结模块保留。
- `simnow_direct.py`：前端选择（TCP 探测=候选筛选；SDK 白名单一致性；
  **时段感知**：CZCE 日盘时段优先 standard、时段外优先 7x24；延迟排序）；
  `RegisteredSimWrapper`（仅覆写被关闭 3 入口）+ `RegisteredSimStore`
  （armed 才放开写；`sdk_api` 保持 None；disarm/freeze）。
- run.py live 流程：dev SDK 路径引导（BT_API_PY_ROOT=D:/bt_api_py；**不含 facade 目录**，
  否则其 backtrader shim 遮蔽真包）+ 来源强校验（strict）；前端逐对尝试准入
  （全新会话、任何写入之前）；预检（登录/交易日/生成代次、账户清空校验、合约元数据、
  费率读回）；`DailyRiskStore.load_or_create`（`acct_` 指纹来自 broker+user 哈希）；
  arm（preflight_sha/strategy_identity_sha 自证）；BtApiBroker + Store feed + Cerebro；
  watchdog（stop→drain→硬 runstop 兜底）；跑后权威回读 + 残余敞口 UNKNOWN 冻结 + 证据 JSON；
  退出码 0/1/2/3；drill（engineering 触发、显式标记、DRILL_SESSIONS、warmup 可缩）。
- 已修阻断（全部真实验证）：
  1) MD 登录：账号所用 SimNow MD 前置以请求编号 0 回应 → **btapistore 增量透传
     `allow_zero_login_response`**（默认 False；config live_market_data 打开）；
  2) broker 能力：store config 声明 `supports_dual_side: True`（CTP 双向账本）；
  3) 旧校验器凭据键扫描：`validate_config` 入口对迭代42 段做净化视图（负例仍拒绝）；
  4) run.py argparse 不回显未知参数值（redaction）。
- 关键实证：**首个经 Store/Broker 链路的 SimNow registered-sim 准入武装成功**
  （env=set1_*；instrument=CZCE.SA701；trading_day=20261012）。
- 时段/数据事实：周六凌晨标准前置 TCP 可达但无行情；选择器已改为时段外优先 7x24。

## 测试状态（本次切片）

- `tests/unit/test_ctp_sa_midfreq_example.py` / `..._admission_receipt_tool.py` /
  `..._pilot_supervisor.py`：**195 passed / 1 failed**。
- 唯一失败 `test_receipt_rejects_critical_runtime_identity_drift`：环境依赖
  （bt_api_py 深层子模块在本机 anaconda 无完整依赖，identity found=False），
  与本次迁移无关，记录为基线环境项。
- 基线既有失败（工作树未改动的文件亦失败，非本轮引入）：
  `test_examples_self_contained.py` 的 000/013_1/013_2 vendored-copy 字节比对（CRLF 漂移）、
  `test_example_folder_is_self_contained[000_live_certification]` → 留待 R9 统一处置。

## 验收 run（在途）

命令：`python run.py --live --allow-write --drill --drill-side long --run-seconds 2700
--drill-delay-seconds 1200 --drill-window-seconds 1500 --drill-warmup-bars 8`
（约 50 分钟；EMA20/ATR14 minperiod ≈ 20 根 1 分钟 bar 决定最早进场时间）。
PASS 判据：entry 成交>0 且 close 成交>0、终态 flat、无活动单、无 UNKNOWN、
对账通过（§2 成交往返）。证据：`evidence/live-*/run.json`。

### v1 试运行（live-20261009T174934Z-03c599b2，已终止）暴露的启动契约缺陷

策略启动 1 分钟后 `RECOVERING → MANUAL_INTERVENTION`
（`durable_intent_evidence_incomplete`）。根因：策略要求 broker
`get_execution_summary()` 返回健康持久摘要（session_enabled=True/trading_blocked=False/
evidence_errors=[]/unknown_ids/active_orders），而直连执行层未提供 → broker 兜底占位
（trading_blocked=True）被判为 UNKNOWN。修复（示例内、按 §5.3 语义）：
`RegisteredSimStore.get_execution_summary`（armed 且未冻结=session_enabled；
frozen 映射 trading_blocked+稳定 unknown_id）+ wrapper 订单状态跟踪
（`_order_state` 覆盖 active/terminal，经 `_handle_order` 更新——stock 包装器从不清理
pending 表）。v1 为诊断轮，无订单发生；已终止，不作为验收证据。

### v2 验收 run（live-20261009T175637Z-a5eaef61，在途）

启动即进入 **WARMING**（`warmup_not_complete`）✓；准入 front=set2_7x24_4000x。
drill 窗口 ~18:16:37–18:41:37 UTC；run 截止 18:41:37。

## R1 提交草稿（终态后补验收数值）

`feat(iteration42): standardize 013_3 four-file entry with SimNow registered-sim acceptance`

- 013_3：标准四件套（run.py dry/--replay/--live；config.yaml；sa_midfreq_strategy.py；
  README.md）+ 示例内直连 registered-sim 执行层 simnow_direct.py；旧 run.py → legacy_runner.py。
- 首个经 Store/Broker 链路的 SimNow 写准入（arm_execution_for_registered_sim；白名单整对
  逐对尝试、只读预检、空仓前置、typed 执行摘要、UNKNOWN 冻结）。
- `backtrader/stores/btapistore.py`：附加式 `allow_zero_login_response` 透传（默认关）。
- 测试：013_3 模块改名与 CLI 语义更新；docs：迭代42 计划 + R0/R1 证据。
- 验收：dry/replay PASS；live drill 成交往返 = <待填>；未触碰 Store/managed/facade 的
  SimNow 写路线；无 SDK 侧提交（本轮无 SDK 代码改动）。

R2 环境核查：checkout 根 `.env` 中 OKX/Binance Demo 五个凭据名齐全 ✓；
`_load_demo_credentials` 依赖 `OKX_DEMO_*`/`BINANCE_DEMO_*`（os.environ 或 .env）。

## 下一步（R1 收尾）

周一执行计划（命令/窗口/判据/收尾步骤）见同目录 `monday-live-run-plan-2026-10-12.md`；
逐示例 tracker 由 `scripts/generate_iteration42_tracker.py` 生成（JSON+MD）。

1. ~~读取验收 run 证据~~ → 已完成：实现轮提交 **eb3da84f3**（dev）；真实成交往返验收待周一 CZCE 时段
   （2026-10-12 09:00 北京）用标准前置重跑 drill；当日补记验收结果。
2. 提交白名单（backtrader dev）：已完成（18 文件）；保留工作树中既有无关修改不提交。
3. 进入 R2（012_1 双所 Demo）。**进行中（2026-10-10）**：
   - 已改名：`strategy.py` → `cross_exchange_strategy.py`（导入修正）；`run.py` → `legacy_runner.py`
     （旧引擎；`load_config` 允许新 `entry` 段）；新标准 `run.py` 待写；
   - 已侦查：`_run_network_impl(mode="demo", demo_execution_smoke=True, allow_rejected_demo_simulation=True,
     manifest_path=REPO_CANONICAL_MANIFEST)` 为验收通道；报告状态 `MECHANICAL_DEMO_SMOKE_PASS/INCOMPLETE`；
     demo 依赖 `operator_override` 与 canonical manifest 路径；
   - 待办：新 run.py（dry/replay/live+证据+退出码）、config.yaml 加 `entry` 段、
     canonical/local manifest 刷新（strategy_module/hashes/candidate_sha256）、
     `.gitattributes` 改路径、测试更新、demo 真实验收。

## R2 设计要点（侦查已完成，待 R1 提交后执行）

- 012_1 现状：`run.py`（2400 行，含 replay/shadow/paper-live/demo 模式与 demo 审批校验）、
  `strategy.py`（`CrossExchangeArbitrageStrategy`）、`strategy-candidate-manifest.json`
  （status=`RESEARCH_REJECTED_OPERATOR_DEMO_SIMULATION_ONLY`，含 operator-acknowledgement
  `OPERATOR_DEMO_CONDITION`/`allow_rejected_demo_simulation` 路径）、`qualification-v3.json`、
  vendored `strategy_candidate_approval.py` + `demo-approval-trust-root.pem`。
- 目标形态：新 `run.py`（dry/`--replay`/`--live --allow-write`）、config.yaml（新增
  schema/venue/credentials(OKX+BINANCE demo env 名)/policy(有界)/timeouts 段；保留原策略参数段）、
  `012_1_strategy.py`（迁移 strategy.py；同步 manifest `strategy_module` 与
  `scripts/refresh_cross_exchange_local_manifests.py --check`）、README 重写；旧 run.py →
  `legacy_runner.py`（保留内部引擎；R9 再收敛）。
- live（demo）路径：复用旧内部引擎（Store/Feed/Broker + 审批凭证校验），
  以"技术验收登记"更新 manifest/operator 条件（记录为技术贯通，非盈利结论），
  有界 policy（max_actions/名义上限/单轮往返），证据写 `evidence/<run_id>/`。
- 双所 demo 写与幂等：按迭代42 §5.3（OKX 50013 同 clOrdId；超时先查询）。
- 清单/字节绑定：manifest 刷新 + `.gitattributes` 六路径 LF 规则核对（012_1/012_2 各
  run/strategy/config 三文件）。

## 7x24 夜跑"零下单"根因（2026-10-10 复核，非缺陷）

013_3 历史夜间 live 运行（12 次）全部 `session_order_refs=0`、`no_fill_round_trip`。源码复核
根因：`_engineering_trigger_direction` 以 **`quote.event_time`** 对 trigger 的墙钟窗口
（`not_before_utc`/`not_after_utc`）比较；7x24 环境报价事件钟陈旧 ~47.9h → 永不落入窗口 →
`engineering_trigger_not_reached` 持续阻断，drill 从未发出订单。**在时段内标准前置上
quote.event_time ≈ 墙钟**，窗口按设计生效——周一 09:00 drill 不受此影响。今晚以周一逐字命令
复跑 013_3 彩排（编辑后首跑）预期同样零单，仅用于验证编辑后入口与武装链路的真实可用性。

## 013_3 编辑后首跑与封存 bar 链修复（2026-10-10 07:27–07:47 北京，7x24）

以周一同一条命令首跑编辑后的入口：选择→7x24 武装→运行 2856s 有界→drain→干净退出
（run_error=null）。诊断暴露关键缺口：`invalid_completed_bar:bar_schema_missing:
connection_generation ×9`、`closed_bars=0`——**run.py 从未调用
`configure_live_tick_provenance`**，live tick 无打标 → bar 缺 `connection_generation`
（schema 18 项中唯此缺）→ 每根 bar 被拒 → `last_minute=None` → drill 在**标准前置同样
永远到不了触发**（R1 只验收过"行情(quote)入策略"，bar 链从未真正被真实运行验证）。
修复：入场后、feed 构建前接入运行域打标（域/会话段/登录代次/身份哈希，写入
`summary["live_tick_provenance"]`），回归测试断言接线与顺序。

修证彩排（`--run-seconds 1500 --drill-delay-seconds 600 --drill-window-seconds 600`）：
运行 1655s 有界、干净退出；**`bar_schema_missing` 阻断完全消失（0）**，打标在
run.json 中实证据生效（`iter42-sa-live-3c1a3add734f / czce-sa-live:20261008 / gen=1`）。
`closed_bars=0` 仅因 7x24 极端封存环境下 25 分钟不足一根 bar 事件（非 schema/接线问题）；
`quote:invalid_lower_limit:1553` 仍旧为 7x24 无涨跌停价的环境事实。零单、终态 flat。
周一标准前置（新鲜钟、正常封存）为 bar 链与 drill 的正式验收路径。

## 追加：drain 永驻 RECOVERING 的接线缺口与修复（2026-10-10 午后，`71089e7c6`）

复盘两处 live 证据（`0940fd55` 修复前 / `fd775f5b` 修复后）发现**两次都以
`RECOVERING / drain_reconciliation_required` 收尾**：SA 策略的监督环
（对账重试、对账超时、以及把 drain 推进到 `STOPPED_FLAT` 的完成转移）全部位于
`notify_idle`，而 live feed 持续有 tick 时引擎**从不隐式调用** `notify_idle`——
013_3 的 run.py 是唯一没有 idle 泵的写入口（014_1/015 在各自轮次已带该泵）。
`fd775f5b` 的 system.log 实录：23:44:03（deadline 时刻）仅排队一轮
`sdk_command_queued ctp_reconcile`（receipt 7d1d…，queue_depth 1），随后 150s
宽限内该轮未完成/未交付，无重试（重试在 notify_idle）→ 硬停 → RECOVERING。

修复（镜像 014_1 已验证模式）：run.py 增加 `_idle_pump` 线程（每秒
`strategy.notify_idle()`）；与 014_1 不同的关键点——泵**故意不理会
`control.stop_reason`**（duration stop 会先 latch 该字段，而 drain 宽限期恰恰
需要泵持续运行），退出条件=引擎自身 stop 事件或与 watchdog 相同的 hard deadline。
回归测试锁定接线与 drain-grace 语义；SA 套件 179 通过（仅既有环境基线 1 项失败）；
ruff 干净；CLI dry/replay 绿。周一 013_3 若完成完整往返，drain 应可达
`STOPPED_FLAT`（若对账轮本身仍无法完成，将按其有界超时进入明确的
`MANUAL_INTERVENTION`，不再是无定义的 RECOVERING 滞留）。

### 遗留开放风险：对账轮在 registered-sim store 上的未实证性（2026-10-10 午后审计，当日晚间静态收敛）

- 事实链：drain 对账经 `broker.request_ctp_reconciliation` → `store.enqueue_ctp_reconciliation`
  → worker 执行 `get_ctp_reconciliation_snapshot` → **`_build_ctp_query_snapshot`（框架查询快照
  机）**；而 013_3 预检用的是 store 自有的 `registered_sim_query`。**静态收敛结论（同日晚间）**：
  两者**调用同一客户端方法与同族命名**——`registered_sim_query(family)` 执行
  `api.query_<family>`，run.py 预检族为 `account_result/positions_result`；框架快照机的
  query_specs 恰为 `query_account_result/query_positions_result/query_orders_result/
  query_trades_result`（同 api 对象、同签名）。四条族的实证面比初判更广：预检已用
  account/positions/orders 三族（run.py 351-353）、运行时 orders 持续同步
  （`open_orders_sync_completed` ×656）、且 run.py 自身收尾对账块（967-970）在真实运行中
  使用全部四族（`final_account/positions/orders/trades`）。剩余不确定性仅为：
  四族在 5s 轮超时内串行完成的时延表现、以及框架侧关联逻辑对该客户端返回字段（request_id/
  is_last_seen）的接受度。
- 处理策略（不改代码，先测后修）：watcher v3 的 013_3 有界彩排带新泵跑完整 drain——
  若对账轮能完成 → `STOPPED_FLAT`（风险消除）；若仍失败 → 证据将显示具体错误，再按
  `registered_sim_query` 口径补 store 级对账快照（离线开发 + 单测，真实验证留待标准前置
  时段）。**不盲改**：星期日前无真实前置可验证，且静态上该方法族已被大规模实证。
