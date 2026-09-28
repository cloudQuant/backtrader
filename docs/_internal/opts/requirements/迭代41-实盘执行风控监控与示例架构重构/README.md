# 迭代 41：实盘执行、风控、监控与示例架构重构

**目标操作方式（2026-09-26）：** SimNow 和生产 CTP 共用同一受保护的 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`、同一 `ctp:` 字段和未来同一套受管 CTP 执行实现。SimNow 报撤单全链路验收后，操作者修改这个文件中的 mode/preset、账号认证、MD/TD 地址和合约范围，即通过同一入口请求生产运行；不创建第二份配置或第二套 production runner。生产模式仍须独立通过账号、制品、审批、风控、监控及 F14 准入。当前共享写入 runner 尚未登记，改配置不会启动真实报单；`NO_WRITE / LIVE_NO_GO` 保持不变。

**验收分支：** [ADR-41-16](ADR-41-16-simnow-f14-writer-fence-proposal.md)是唯一 F14 决策提案。它的 SimNow 有界操作性分支（G6-S/G7-S）尚未批准或接线；若将来通过，只能证明具名测试窗口的报撤单与本机控制，必须明确标记跨主机写者排他/共同快照未证实。严格 F14 和 production 另需 G6-P 外部账户级证据；SimNow 结果不能继承。开发与测试按[当前分支验收矩阵](ctp-current-acceptance-matrix.md)核对，二者目前均零写入。

开发接缝和测试矩阵见[CTP 同配置共享 runner 合同](CTP同配置共享Runner开发与验收.md)。

**当前验收状态（2026-09-27，覆盖下方旧快照）：** Store sdk_api=None r1 与 mechanical sdk_api=None fail-close 已集成；Store 文件 SHA-256 为 A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D，mechanical source SHA-256 为 549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F。guarded focus 为 38/38；Store/Runtime broad regression 为 2,725 passed / 43 skipped / 2 xfailed / 0 failed。[主树 evidence](evidence/iteration41-store-sdk-api-none-r1-main-integration-2026-09-27/README.md)明确这不是 SDK/provider trust、授权或交易准入。另一个 fake/offline 主树集成为 97 passed / 10 skipped；optional source-gated cases 未执行，CTP account/native-adjacent 与 deployment interop 被静态排除，见[独立 QA archive](evidence/iteration41-fake-offline-main-integration-qa-2026-09-27/README.md)。

当前 CTP write/live 仍为 NO_WRITE / LIVE_NO_GO。Store getter-only proxy r0 为 NO_MERGE；G4 pinned CTP wheel rebuild 未复现 exact CTP artifact；G5/V21 native-floor 仅 SAFE_LOCAL_FAKE / NO_MERGE，当前跨包绑定仍待复核；I22 11-node read-port replacement 为 NO_MERGE_AS_REPLACEMENT / FAKE_PORT_ONLY。R2 writer inventory 经新 collector 对比后 460 IDs、顺序与 locator 均未变化（363 writer、97 dynamic、355 files、六个 tombstones），verifier 460/460；全部 active rows 仍 REVIEW_REQUIRED / NOT_AVAILABLE，未产生新 inventory version。下文旧日期测试值均作为各自历史 checkpoint，不覆盖本段当前状态。

当前同一私有配置的 `doctor` 离线通过；[15:55 UTC 无凭据前置复查](evidence/ctp-configured-front-check-2026-09-25.md)的零基索引 3 双端各 3/3 次连接，按每端至少 2/3 的传输门槛选中。旧 15:40 UTC 无 pair 观察保留为历史。TCP 连通随时会变，不能推断账号或交易就绪。

新的离线证据：Agent/Skills/MCP 的私有 runtime 路径保护已完成定向与独立复核，Agent 完整 sweep 文件和 MCP 聚焦组合通过；它不提供任意 Python 的 OS 隔离。[执行 v9 版本化与 wheel 证据](evidence/ctp-execution-v9-unified-offline-review-2026-09-25.md)补齐公开 API 迁移标记。[CTP I9 队列租约版本化 wheel](evidence/ctp-i9-queue-lease-wheel-2026-09-25.md)满足总工程版本范围，双构建字节一致，隔离安装 I9 + execution `0.2.0` 的两项真实 `TraderClient` + fake API 桥接经独立复核通过；正式 pin 和默认路由尚无。[AI 边界证据](evidence/ai-private-runtime-guard-2026-09-25.md)与[MD 回调源码/native shim 复核](evidence/ctp-md-callback-source-audit-2026-09-25.md)均不改变 `NO_WRITE / LIVE_NO_GO`。

状态：`PARTIALLY_IMPLEMENTED / LOCAL_TARGETED_EVIDENCE_AVAILABLE / LOCAL_FAST_FUNCTIONAL_PASS / LOCAL_SLOW_STRATEGY_PASS / LOCAL_SERIAL_PERFORMANCE_PASS / LIVE_NO_GO`；当前验收基线：`2026-09-27`

I13 MD-only 与 I15 TD-only 的固定子进程和源码导入有离线测试，但当前已接线的候选父进程可能在验源前执行仓库缓存；原 I13 finder 还可加载清单外新增源码。未登记的外层 sealed-import helper 已接入 manifest/source loader 的 Windows file-ID lease，并拒绝未执行的伪缓存模块，尚未成为候选父进程入口。两者 pin 均未启用，新的真实诊断 marker、账号与 provider 均未触达。真实 SimNow 只读、下单及撤单尚未跑通；修复与 QA 负测见[当前验收矩阵](ctp-current-acceptance-matrix.md)。

开发和 QA 请先用[CTP 同配置当前验收矩阵](ctp-current-acceptance-matrix.md)查看依赖顺序、操作入口和每道门的通过/阻断证据；详细历史与完整合同仍以本目录的计划、验收文档和证据页为准。

**历史验收入口摘要（2026-09-25；当前结果见上段）：** 普通 CLI preflight、SimNow 报撤单和 live 路由仍关闭。后文所列 2026-09-25 runtime 与 integration 计数是各自历史快照，不是当前 Store/Runtime 结果。

**I12 历史诊断增量（2026-09-25）：** I12 TD-only supervised attempt 已在 `sdk_artifact` 以 `rejected / runtime_policy_rejected` 结束并消耗独立 marker；离线源码复核发现与旧 receipt 阶段吻合的 Mapping→`CtpConfiguredFrontPair` `_route` 缺陷候选；原始 child exception 未保留，不能称为真实运行唯一根因已证明。未观察 login、TD query 未验证、close 未尝试，不重试。详见[I12 脱敏诊断记录](evidence/ctp-i12-td-only-diagnostic-2026-09-25.md)。此前[I11 受监督 MD-only 一次性诊断](evidence/ctp-i11-md-diagnostic-2026-09-25.md)于 2026-09-25 结束为 `incomplete / native_join_pending`；subscription ACK 已观察，但 identity 未验证，tick/交易日及有序 native close 均未证实，I11 marker 已消耗且不重试。主仓完整 runtime 最新复跑为 `1558 passed, 26 skipped, 1 existing PytestConfigWarning in 67.04s`（`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p no:asyncio tests/unit/runtime -q`；仅离线单元测试）；`1536 passed, 26 skipped` 为历史结果。先前 `1465 passed, 24 skipped` 等计数属于历史 checkpoint；CTP/default live/write readiness 未通过，维持 `NO_WRITE / LIVE_NO_GO`。
创建日期：2026-09-21；本轮交叉复核完成：2026-09-24

**本轮同文件 CTP 与执行账本状态（2026-09-25）：** canonical `ctp:` 的同一受保护配置路径 production read-only 候选 focused suite 为 `104 passed, 1 skipped`，默认 live route 仍关闭；同一文件/schema 是须将 live-mode dispatch/admission 接入并独立验收同一 CTP runner 后才可用的未来目标，当前仅改配置仍不能运行 production。`doctor` 的 canonical `ctp`/`front_pairs` 展示修复为 `37 passed`；本机受保护配置的离线 doctor 仅确认 `diagnostic simulation/sandbox` 与 5 个 pair 条目，不记录任何私密字段。Backtrader handoff `27 passed`；CTP managed dispatch/adapter 与 MD request-ID audit 合并焦点集 `38 passed` 且 Ruff clean，但仍是 opt-in/unregistered 离线合同，无 provider acceptance；risk/monitor/execution production-scope checker `10 passed`，同为离线非授权结果，尚未接入真实 provider 或默认 route。`Store/Broker` handoff 四文件焦点集 `125 passed`，含一条既有 pytest 配置 warning，定向 Ruff clean；`bt_api_execution` package tests `57 passed`（含 13 个 command-outbox cases），`py_compile` 与适用 Ruff 检查通过。v5 command outbox 是本地离线候选（package suite `57 passed`），未接 SDK 或默认 runner；调用方提供的 seed proof 不授权。`UNKNOWN` 尚无可信 reconciliation/resolution 路径，会永久 fence 账户声明；跨交易日撤单不支持。因此 command channel 仍未验收。ADR-41-15 已更新 `MaxOrderRef`、旧映射和 command queue 阻断；旧 CTP 入口审计 focused `96 passed`，仅覆盖静态分析与测试，未发现审计范围内的可达绕路。未验收真实会话、报单或撤单。主仓完整 runtime 最新全套复跑为 `1558 passed, 26 skipped, 1 existing PytestConfigWarning in 67.04s`（exit 0）；`1447 passed, 24 skipped` 是历史 checkpoint；六个相关 Iter41 integration 文件复跑为 `7 passed, 1 existing PytestConfigWarning in 36.63s`。

**历史 I6 CTP 诊断 checkpoint（2026-09-25；后续见 I7）：** I6 隔离 SDK artifact verifier 通过；安装来源核验后的 CTP SDK 焦点集 `94 passed`，主仓 runtime 单元集 `1269 passed, 24 skipped, 1 warning in 59.84s`（exit 0；`python -m pytest tests/unit/runtime -q -p no:asyncio`），I6 + artifact-provenance 焦点集 `58 passed`，supervisor 离线集 `17 passed`。隔离环境中的合成 SWIG 登录字段 round-trip（BrokerID、UserID、TradingDay）通过，排除了合成对象上的简单 getter 映射错误，但未解释真实回调的空 ID。一次受监督的 MD-only 只读诊断在 market-data 阶段以 `market_client_stop_failed` 结束：只观察到一个登录回调；one-shot `ReqUserLogin` 使用 request ID 0，因此零 request-ID relation 是预期，不是 request-ID mismatch。SDK 将 identity 失败分类为 `broker_id_mismatch`，BrokerID/UserID getter 返回形状为空，TradingDay 字段形状有效；没有订阅 ACK 或匹配 tick，native Join pending，交易和结算写入为零。空 identity 来源仍未确定，该观察不能认定账号/配置错误或账号就绪；没有跑完整 SDK 套件，也没有写入验收。详见[I6 诊断证据](evidence/ctp-i6-md-diagnostic-2026-09-25.md)。当前唯一 CTP 配置仍为同一受保护、Git-ignored 的 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`，SimNow 与未来 CTP production 使用相同 canonical `ctp:` 字段结构；未来操作者在同一文件切换 mode/preset 并替换 account/front/contract 字段，不建立第二份 config，也不按 set 标签或时间选前置。`sealed_config` production scope-binding contract 仅派生非授权 scope identity；受信审批 verifier、production runner/admission 和所有 live write gates 尚未完成。默认 live route fail closed，保持 `NO_WRITE / LIVE_NO_GO`。

**I6 native shutdown probe（no provider/account）：** exact pinned I6 SDK 的 suspended-child Windows Job loopback probe 使用空身份、passive SPI、零登录请求与零 front callbacks。`stop_and_wait(0.75)` 返回 Join pending、native 未释放、线程仍活跃、超时且不完整；child process 后来正常退出，但这不是 native shutdown 证据。单独的 harmless Job-timeout smoke 验证了 kill 路径。没有尝试对活跃 Join 调用 `Release()`，所以此结果不证明其调用顺序不安全，也不构成 SDK readiness 或写入验收。完整脱敏观察见[I6 诊断证据](evidence/ctp-i6-md-diagnostic-2026-09-25.md)。

**当前 013_3 profile、测试与隔离状态（2026-09-25）：** 默认 registry 中的 013_3 CTP 是单一 zero-write `simulation/sandbox` `RuntimeProfile`；profile 的普通直接 CLI `preflight` 当前 fail-closed/不可操作，直到有总期限的 Windows Job supervisor 实现并独立验收；`doctor` 离线，`run`、live 和交易/结算写入关闭。当前普通 `bt-runtime preflight` CLI 已 fail-closed，暂不可作为日常 provider 命令：native SDK 的同步 start/stop/Join/Release 可能在普通 CLI 进程内无界等待；供应商生命周期合同与根因尚未证实。只有实现并独立验收有总期限的 Windows Job supervisor 后才能重新评估；I11 的独立受监督观察和 I12 的失败 TD-only 尝试均不解锁普通 preflight。见[ native Join 源码审查](evidence/ctp-native-join-source-review-2026-09-25.md)。SimNow 与未来 CTP production 共用同一受保护 `runtime-ctp-private/config.yaml` 和 canonical `ctp:` 字段；操作者改同一文件的 mode/preset 与 account/front/contract，不建第二份配置，不按 set 标签或时间选择。Profile focused suite 为 `230 passed, 14 skipped`；主仓完整 runtime 在 CLI gate、I12 helper 与 I13 更新后的最新全套复跑为 `1558 passed, 26 skipped, 1 existing PytestConfigWarning in 67.04s`（exit 0；`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -p no:asyncio tests/unit/runtime -q`）；`1536 passed, 26 skipped` 为历史结果；`1447 passed, 24 skipped` 是历史 checkpoint；六个相关 Iter41 integration 文件复跑为 `7 passed, 1 existing PytestConfigWarning in 36.63s`；MCP `--no-cov` boundary tests 为 `23 passed`。这些都是本地离线测试，不代表 provider/session readiness、default live route 或写入验收；后续代码或纯合同变更需重新完整复测。主仓 dual-field credential-scope bridge 已实现，focused 40 项通过且 Ruff 通过。parent 0.15.5 初版候选独立审阅因短 acct_<16> token 与 full 64-character scope 不匹配而 BLOCK；frozen dual-field candidate commit `af538469…` / wheel SHA `cfa83b1a…` 已通过独立 RECORD 与 151-source-member 审阅；本次仅证明离线 fake/replay bundle 集成，不构成 CTP/default-route 接入。 Parent SDK 测试隔离修复后，正常插件启用的 broad suite 为 999 passed, 2 skipped, 1 warning（test-only commit 3bec55d）；在该 test-only checkpoint，wheel SHA 81c9ee62… 未变；此历史结果早于 frozen candidate `af538469…`，不构成当前 CTP triwheel 验收。bt_api_risk 最新隔离 source suite 为 164 passed（test-only commit b809800；candidate dce2c84d 的 API/wheel 未变）。bt_api_execution submodule 已独立提交 4bf6da1…，exact wheel byte reproducibility 仍在验证。I8 SDK 候选此前离线 fake suites 分别 10、61、35 项通过；一次受监督 I8 MD-only 只读诊断已运行，但以 `incomplete / native_shutdown_uncertain` 结束，不构成完整 preflight/login/tick/write 验收。另有 I8 SDK 纯 fake shutdown-contract 焦点集 `63 passed`；它只证明条件式本地接口行为，不判定真实厂商语义。I8 wheel `f354…` 与 source commit `a7d9…` 已定位，但 `autocrlf=true`/`false` 下的独立 clean-clone builds 均未与保留 wheel 字节一致，原因是 source 含混合换行；需固定 EOL 策略与 build receipt 才能称可复现。I9 callback-deferral 的离线候选已更新：旧 commit `353e9d8…` 的 clean-clone 重建在固定 `SOURCE_DATE_EPOCH` 与 `LINK=/Brepro` 下产生相同 wheel SHA-256 `29f50faa37d145f9b82bdaf4e38b483eff898272925ac082e0d12eb8125cfaf3`，但 artifact metadata 仍标为 i8，不能据此 pin/deploy（receipt：`D:\temp\i9-artifact-repro-20260925\I9-offline-wheel-repro-receipt.md`）。最终离线候选版本为 `2.0.3+iteration41.i9`、commit `157d0c0cffa4c8a86e196159cdf227e9014e9118`；两次独立 clean-clone wheel 字节一致，SHA-256 `aa094c039788a41adf975cfeee839fa3baf1bcef3878ae53d10eefb44410a4a3`，embedded RECORD SHA-256 `d030ccf23d59a5f77230b490df52aa48c4cbecd67b2a78b7e782600126565841`（receipt：`D:\temp\i9-final-wheel-repro-20260925\I9-final-wheel-repro-receipt.md`）。两次安装各有 `95 passed` fake tests；主仓从已安装 wheel 运行 adapter 测试 `26 passed`；SDK 六文件 source suite `204 passed`；Ruff/diff clean。此前 review 发现的 submit-rejection race 已在本地修复并经 barrier test 覆盖。opt-in SDK `managed_outbox_pre_dispatch` fail-closed boundary 的既有焦点为 `9 passed`、combined 为 `47 passed`；无 fresh approval verifier、claim 或 native submit。以上仅为离线证据：主仓 pin/default route 与旧 I8 pin 未变；I9 已在本地处理 `on_login` 响应的 owned copy、callback deferral 及 submit 拒绝竞态；native Join/Release、真实 provider/session 及写入仍未验收，无真实诊断或写入；维持 `NO_WRITE / LIVE_NO_GO`。 I8 read-only wheel candidate 与 CTP triwheel 仍未登记，默认 route 仍关闭（见 [I8 证据](evidence/ctp-i8-md-diagnostic-2026-09-25.md)）。I7 fixed supervisor 最新 35 项合成测试通过。两次受监督只读 I7 MD-only diagnostic 均验证进程 containment（Job empty、无 descendant）；第二次在 market stage 以 `incomplete / market_client_stop_failed`、native Join pending；无 ACK/tick，交易和结算写入为零。首轮 native-shape null 源自主仓 I3 failure-diagnostics helper 漏复制 enum；修复后第二次受监督复测已明确观察到 native BrokerID/UserID 字段为空（TradingDay 字段形状有效），这排除了简单的 SWIG getter 丢失；官方 Mini API 手册未承诺这些字段必须非空或回显，因此空字段只表示 SDK strict identity 校验失败、身份未证实，不足以推断账号配置错误。68 项 I3/I7 焦点测试通过，但空身份原因仍未确定。它不是完整 preflight、账号 readiness 或写入验收，I7 route 仍未登记/接入。此前 overlay-backed 离线 fake/replay smoke 为 14 passed, 0 failed, 14 selected, 2 skipped，但它使用额外本地 bt_api_risk/bt_api_monitor 源码 overlay，不能作为仅 bt_api_execution clean wheel 的复现证据。此前单独 execution-only wheel（无 dirty source overlay）smoke 为 12 passed, 2 failed，两个失败均因缺少 bt_api_risk capability；socket/DNS network guard attempts 为 0。execution/risk/monitor 三个 clean candidate wheels 已构建。此前 no-system 60-wheel bundle 经 pip check、RECORD 和 import-origin 验证（57 wheel hashes unchanged、3 replaced）。该此前 60-wheel bundle 的 CLI fake/replay smoke 曾为 12 passed, 2 failed, 14 selected, 2 skipped（私有 CTP 与 public shadow），network guard attempts=0。两条 managed fake replay CLI 在 runner 内遇到旧 parent runtime_plugins 用 generic resolve_freeze 清除 dispatch-inflight latch 的调用；hardened bt_api_risk 按合同拒绝，随后无法重新确立 safety latch。诊断保守报告 provider_io_may_have_started=true、provider_preflight_started=false；该测试使用 fake provider、无真实 provider/network 触达，因此不是执行或写入验收。另一次 system-site-packages 14/0 试跑继承了 editable SDK sources/provider adapters，只作诊断，不是 clean-origin 证据。该结果仅为离线 fake/replay，不是 provider/account 证据。另，主仓 managed replay integration 为 2/2，但其 subprocess harness 将 dirty SDK base/execution/risk/monitor src 路径置于 PYTHONPATH 前；该结果不能证明 candidate execution wheel 联调。wheel 本身仅在 strict venv 中由 32 项包内测试覆盖。managed CTP `bt_api_py` parent 的 frozen candidate commit `af538469…` 已有独立审阅 wheel，并有 fake L2 离线 bundle smoke；旧 `D:/source_code/bt_api_py` wheel仍不完整，且此次证据不验收 CTP triwheel、provider 路由或写入。以上结果不代表订单或生产能力；保持 `NO_WRITE / LIVE_NO_GO`。

**Frozen-parent no-system wheel-only fake/replay smoke（官方 PyYAML 复跑，2026-09-25）：** 61-wheel 新 manifest（SHA-256 `4b189520d2a5b5b9b83a3d380096b75137beb1eb375937c916ab9a863f535289`）只将首轮本地重打包 PyYAML 替换为官方 PyPI PyYAML 6.0.1 `cp311-win_amd64` wheel；manifest 中 60 个其他 wheel hash 不变。官方文件 SHA-256 `bf07ee2fef7014951eeb99f56f39c9bb4af143d8aa3c21b1677805985307da34` 与 PyPI JSON digest 匹配，wheel RECORD 为 24 rows / 23 hashed / 0 invalid。短路径 no-system venv 的 `pip check`、9 项 SDK/PyYAML installed RECORD 与 SDK/YAML import-origin 检查通过。固定 parent candidate commit `af538469…` / wheel SHA 前缀 `cfa83b1a…` 的独立 RECORD 与 151-source-member 审阅通过。CLI smoke 为 `14/14 PASS, 0 failed, 2 skipped`（私有 CTP 与 public shadow），两个 managed fake L2 replay 均通过，socket/DNS guard attempts 为 0；provider/account I/O 为 none，网络只用于读取 PyPI 元数据和下载官方 wheel。此结果仅证明本地 fake/replay wheel 集成，CTP 路由被 skip，无 SimNow/provider/production write readiness 证据，维持 `NO_WRITE / LIVE_NO_GO`。首轮使用本地重打包 PyYAML（SHA 前缀 `c58d7fa7…`）的 smoke 与更早 60-wheel `12 passed, 2 failed` 均保留为历史快照；见[脱敏证据页](evidence/clean-wheel-bundle-fake-replay-2026-09-25.md)。

**I11 受监督 MD-only 诊断（2026-09-25）：** I11 是未注册、独立一次性候选，固定制品前检和父进程无凭据 pair 前检通过后才预留专用 marker；child 对应 `pair_3` 且 config digest 匹配。诊断 `incomplete / native_join_pending`：subscription ACK 为 true，但 `identity_unverified`，matching tick 与 same-trading-day 均为 null；marker 已消耗且不可重试。Windows Job containment verified 并已终止收拢，交易/结算写入为零。详见[I11 脱敏证据](evidence/ctp-i11-md-diagnostic-2026-09-25.md)。ACK 不证明身份、tick、关闭或账户就绪；默认 `NO_WRITE / LIVE_NO_GO`。

**I8 受监督 MD-only 诊断（2026-09-25）：** 约 01:27 UTC，使用固定 I8 wheel（标识前缀 `f354…`）的 no-system venv。时间顺序核对为：运行前 `bt-runtime doctor` exit 0，诊断 latch 当时为 absent；固定 supervisor 在启动 child 前原子创建 latch，诊断后状态为 present。未进行真实重试。Windows Job containment verified：子进程已创建、分配、恢复并退出，Job empty，无终止请求，exit 3。严格 child receipt 为 `incomplete / native_shutdown_uncertain / market_data`；`client_stop_returned=false`、`native_join_pending=false`、`identity_unverified=false`、`subscription_ack=false`、`tick=false`、`market_login_ready=false`、`order_submission_authorized=false`。失败时投影可能丢失部分 callback 状态，false ACK/tick 不能证明 callback 缺席，`identity_unverified=false` 不能证明 identity 已验证；`native_join_pending=false` 也不能证明 orderly close。历史 I8 receipt 中的 `client_stop_returned=false` 来自旧版投影，当时没有透传实际 client stop 返回值，因此不能证明 stop 未返回或返回失败。当前代码以 `true`/`false`/`null` tri-state 表达该字段；历史值不应覆盖当前实现，且该字段本身不证明 orderly native shutdown 或 vendor close contract。该次不是完整 preflight/login/tick/write 验收，无订单/撤单；I8 route 未登记；另有 I8 SDK 纯 fake shutdown-contract 焦点集 `63 passed`，仅证明条件式本地接口行为，不判定 vendor 行为，维持 `NO_WRITE / LIVE_NO_GO`。I8 记录时的工作树完整 `tests/unit/runtime` 回归为 `1406 passed, 24 skipped, 1 existing PytestConfigWarning in 61.89s`（exit 0）。另六个相关 Iter41 integration 文件 `8 passed, 1 warning in 31.89s`，MCP `--no-cov` boundary tests `23 passed`。这些均为离线测试，不代表 provider/session readiness、live route 或写入验收；后续代码变更仍需复测。详见[I8 value-free 证据](evidence/ctp-i8-md-diagnostic-2026-09-25.md)。
**历史 I2 checkpoint（2026-09-24）：** 当时 I2 TD retry 到达 native TD，七项只读 query 均完成，但 native Join 未完成，完整 preflight 仍拒绝；margin/commission 的 ExchangeID 为空，范围未验证。独立 MD-only 在 teardown grace 后仍因 login timeout 与 `request_id_mismatch` 拒绝：零 request ID 无法安全关联，native Join pending，无 ACK/tick、零交易或结算写入。I1 七项查询成功但 Join 未完成，以及较早 I2 前置失败，均为历史观察。I2 完整详情见[2026-09-24 验证汇总](evidence/validation-summary-2026-09-24.md)。

I2 本地离线历史验收为 runtime `1156 passed, 26 skipped`，SDK CTP `566 passed, 1 network test deselected`，Ruff 通过；front-pair 定向集 `28 passed`。这些检查未进行 provider I/O。制品 pin、查询明细和当时受保护诊断见[2026-09-24 验证汇总](evidence/validation-summary-2026-09-24.md)；runtime 日志见 [I2 full runtime suite](../../../../../artifacts/iteration41_runtime_suite_20260924_i2_front_parallel_cleanup.log)。

> **实施状态。** 基线仍不构成实盘批准；当前源码已有 config-first shell、11 个 nonmanaged replay runner（8 个普通策略、`examples/007_ctp` 与 `examples/010_live_examples` 两条 legacy no-action、以及 historical `sample.py` no-action migration profile）、两个进程内 fake-provider managed L2 runner、risk dispatch claim、受控 reconcile/cancel control、local ZMQ gateway，以及明确 NO-GO。Backtrader package fixture 的早期 direct-dispatch lane 仍是本地 fake-provider 证据：两个路径分别为 `LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS` 和 `LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS`，均为 0 external network/write；该旧 lane 使用 `D:/bt_api_py` 源码 capability 环境，不能替代下述 bundle。[capability-bundle-local-windows.json](evidence/capability-bundle-local-windows.json)（SHA256 `2ad986457abf776bea581a064fae4fa433d98d5db2343df01903dc9ce8e18225`）已在全新 venv 的 `python -I`、`--no-index` 本地 wheelhouse 中安装 Backtrader 与七个 `bt_api_*` project wheels；安装、`pip check` 和 probe 均 exit 0，模块与 dist-info origin 均在该 venv 的 `site-packages`，本地项目 RECORD 已验证。generic fake managed composition 为 `ACKED`（1 次 fake-provider call）；两个 packaged L2 fixture 分别为 `LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS` 与 `LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS`，每条均 `external_network_requests=0`、`external_write_requests=0`、`actual_fills=0`，`network_guard_attempts=0`。该 bundle 的结论严格为 `LOCAL_EVIDENCE_ONLY / NOT_RELEASE_ELIGIBLE`：仅证明 Windows 本机、离线 local-wheelhouse 的机械 consumer 行为；不证明已审阅/签名/发布制品、可信依赖 provenance、部署或 server admission、provider/account/credential/人工授权或 live。Backtrader 与各能力源树仍 dirty，且 OS network firewall 未验证。本页不把 capability bundle 或 L2 local evidence 写成部署 preflight、live runtime 或实盘准入；package-owned fixture 的 local backtest 结论也不外推为部署或 live。
> 当前默认 registry 共 16 条。013_3 CTP 是 zero-write `simulation/sandbox` profile；普通直接 CLI `preflight` 当前 fail-closed/不可操作，直到有总期限的 Windows Job supervisor 实现并独立验收；`doctor` 离线，`run`/live/write 关闭。I6 诊断见[I6 证据](evidence/ctp-i6-md-diagnostic-2026-09-25.md)，I7 首轮诊断见[I7 证据](evidence/ctp-i7-md-diagnostic-2026-09-25.md)，profile/I7 与测试增量见[证据索引](evidence/README.md)；I5/I2/I4、I1/H2 和旧配置保留为历史证据。

> 此前核心定向集已通过：`312 passed, 3 skipped, 1 warning in 106.64s`。并行 fast functional lane（排除 slow/performance）已通过：`5865 passed, 11 skipped, 35 warnings in 182.43s (0:03:02)`；策略 slow tier 也已在本地离线环境通过：`810 passed, 11 warnings in 272.80s (0:04:32)`；serial performance 的主集与隔离短压测均已在本机串行通过，分别为 `27 passed, 6687 deselected, 1 warning in 51.56s` 与 `1 passed, 1 warning in 0.73s`。旧 baseline-3 runtime 加 CTP 交易日/选档回归当时为 `705 passed, 19 skipped, 1 warning in 65.96s`，不能替代当前配置前置直连合同。较新的 runtime 单测已分两段覆盖：主集 `745 passed, 18 skipped, 2 deselected`，另 2 个回放用例单独 `2 passed`；新增 `doctor` 拒绝混配地址后，CTP MD/TD/配置路由四文件在 Python 3.11/3.8 各 `91 passed`。精确命令及边界见[2026-09-23 本地验证汇总](evidence/validation-summary-2026-09-23.md)。全部结果只覆盖本地、离线和 fake-provider 范围；SDK/bridge 的局部结果见[实施状态与验收快照](实施状态与验收快照.md)，不能由此作任何实盘准入结论。
>
> 上述 fast、slow、performance 的全套本地结果属于本轮 CTP 增量之前的基线；最新 CTP 增量已复跑完整 runtime 单元集和 CTP 焦点集，其他全套测试仍须由后续开发/QA 在相同交付 revision 重新执行并留存结果。

> **Windows 目录替换已加固；POSIX 仅有局部受管加固。** Windows config load、bootstrap 和 runner 调用持有拒绝 delete-share 的目录 lease；跨进程 bootstrap 父目录替换、同名 replacement runtime 创建和 runner pathname 替换均已被回归覆盖。POSIX 的 `bt-runtime run` 在取得登记目录 fd 后向 14 条 source/example opt-in runner（含公开 shadow，不含 package-owned `backtest/local_backtest` fixture）传入 `runtime_dir=None`、无路径 sealed effective/config/registration view、opaque registry token 和 opaque fd-backed capability；013_3 的旧 path-based evidence writer 使用 private workspace。实际 POSIX rename/symlink filesystem regressions 在本机 Windows 上为 `NOT_RUN`，portable contract/focus 只是 Windows 本地结果；公开 direct `run_runtime(..., effective=None)` 会在读取 `config.yaml` 或检查 runtime pathname 前以 `runner_dispatch_required` 拒绝，不能重新打开路径；`P1_POSIX_RUNNER_PATHNAME_DIRECTORY_REPLACEMENT_SIDE_EFFECT` 仍因真实 POSIX filesystem regressions 尚未执行，以及 path-free view/opaque token 不是 hostile in-process Python code 的隔离或沙箱而保持开放。Windows 结论只适用于普通 Win32 进程与当前本地文件系统，不覆盖特权、内核或文件系统实现绕过。外部 `bt_api_*` 的 CWD/未登记/子模块 meta-path import fence 已有本地回归。Windows 本机 CPython 3.8.20 已通过无 SDK config/operator harness（`75 passed, 3 skipped, 1 warning in 2.17s`，exit 0；见[原始 JSON](evidence/cpython38-core-runtime-local-windows.json)）；但 Ubuntu 22.04 GitHub CI job 尚未生成并上传对应 artifact，不能称跨平台或 CI 完成。`bt_api_py`/execution 要求 >=3.11，base/risk/monitor 要求 >=3.9，受管路径不支持 3.8。完整边界和 `LIVE_NO_GO` 见[实施状态与验收快照](实施状态与验收快照.md)。

本轮已结合四份评审及当前代码修订整套计划。开发先读[审阅裁决](审阅裁决记录.md)、
[设计](设计文档.md)、[工作包](迭代计划.md)；测试先读[追溯矩阵](追溯矩阵.md)、
[验收条件](验收文档.md)和[用例与基准](验收用例与基准.md)。原始评审保留，已采纳事项不再悬置。

本版关键决定：核心、gateway、AI 分阶段交付但保留总范围；所有 strategy runtime 强制使用本地 schema-v4
`config.yaml`，由其中的 `backtest`/`simulation`/`live` 模式和具名 preset 唯一决定有效能力。普通 profile 的密钥独立引用；CTP SimNow 私有 `simulation/sandbox` 扩展按用户要求在未跟踪的配置中填写成对 `md_front`/`td_front`、账号认证与合约范围；
日常操作收敛为首次 bootstrap、日常 run（内置配置和 preset 校验）及只读 doctor；validate 可单独用于离线检查，
CTP provider/account preflight 则是另一条需代码登记的显式命令。direct 映射代码不能再作为无配置启动旁路，AI 证据永不替代
账户授权或逐笔风险许可。
代码核查及当前包状态见[能力评估](能力评估与ADR索引.md)和[源码快照](evidence/plan-review-baseline.json)。

范围仓库：`backtrader`、`bt_api_py` superproject、base/contracts及 execution/risk/monitor/gateway 子仓、
拟建的 `bt_api_transport_zmq`，以及独立 AI 互操作阶段的
`D:/source_code/backtrader-agent`、`D:/source_code/backtrader-skills`、`D:/source_code/backtrader-mcp`。
[AI source inventory](evidence/ai-producer-source-inventory.json) 已记录这三个 checkout 的本轮 commit、
dirty manifest 与 source hash，状态仅为 `SOURCE_BASELINE_ONLY`；[AI wheel review vector](evidence/ai-wheel-review-interop.json)
对 supplied wheel 的隔离只读向量为 `LOCAL_WHEEL_REVIEW_INTEROP_PASS / review_only`。[external-ai-wheel-interop-local-windows.json](evidence/external-ai-wheel-interop-local-windows.json)（SHA256 `738e548ce649b6af9ae203b3f39d1ea179e236cfd5d72e3b2f8ecb4e9fcb1f30`）状态 `passed`，是 8-wheel 本地 source-to-wheel → fresh-venv `python -I -s` 的只读 review handoff：RECORD 与 module origin 为 `site-packages`，source checkout 与 provider modules 不在 probe 中，run root 为空。它明确是 `external_bt_api=false`（artifact 字段 `external_bt_api_capability_wheels_verified=false`）的 review-only 证据；`execution=false`、`provider_network=false`、`live_admission=false`。Agent→Skills 仅 valid/read_only、authorization=false、promotion 被拒绝；MCP 为 `REQUIRES_INDEPENDENT_REVIEW` 且 authority flags 均 false。该 AI 制品不证明 trusted release/deployment/server admission、provider/account/credential、human authorization 或 live；不能作为 capability package 或执行路径的准入证据。三条 source checkout 均 dirty，
所以这些本地结果不是 release provenance、可信部署/import origin、server-side admission 或 live 授权；三仓 deployment-evidence
测试与只读 interop 的具体计数、wheel hash 和 skills manifest/wheel 修复见[证据索引](evidence/README.md#ai-三仓-source-checkoutwheel-与配置证据)。
`baseline-2` 的 gateway/transport 状态是历史核查记录。当前 capability bundle 已替代此前将外部 capability wheel 全局标为 `NOT_PACKAGED` 的当前状态描述。[capability-bundle-local-windows.json](evidence/capability-bundle-local-windows.json)（SHA256 `2ad986457abf776bea581a064fae4fa433d98d5db2343df01903dc9ce8e18225`）已在全新 venv 的 `python -I`、`--no-index` 本地 wheelhouse 中安装 Backtrader 与七个 `bt_api_*` project wheels；安装、`pip check` 和 probe 均 exit 0，模块与 dist-info origin 均在该 venv 的 `site-packages`，本地项目 RECORD 已验证。generic fake managed composition 为 `ACKED`（1 次 fake-provider call）；两个 packaged L2 fixture 分别为 `LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS` 与 `LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS`，每条均 `external_network_requests=0`、`external_write_requests=0`、`actual_fills=0`，`network_guard_attempts=0`。该 bundle 的结论严格为 `LOCAL_EVIDENCE_ONLY / NOT_RELEASE_ELIGIBLE`：仅证明 Windows 本机、离线 local-wheelhouse 的机械 consumer 行为；不证明已审阅/签名/发布制品、可信依赖 provenance、部署或 server admission、provider/account/credential/人工授权或 live。Backtrader 与各能力源树仍 dirty，且 OS network firewall 未验证。所有源码仍为 `DIRTY_LOCAL_SOURCE`，Backtrader、`bt_api_py` 与 transport 无 superproject gitlink；ambient/PyPI fallback、发布、签名、provider 或 live 结论仍被禁止。现有 provider submodule 继续只是 provider 边界。
实施前提：每个 Git 身份（superproject、四个已挂载能力子仓、gateway、transport-zmq、Backtrader，以及被修改的 provider 子仓）必须在
独立、可归责的提交/工作树中执行。`bt_api_py` 只能通过明确的 optional dependency、版本约束和 integration
adapter 使用这五个包；不得把它们复制、vendor 或混入 `bt_api_py` 的单体源码包。本目录是跨仓契约，不授权
混合修改或真实交易写入。

`baseline-2` 记录的 `bt_api_execution` 是空仓 pin `2700cb5`。当前本机开发工作树已有未提交的
`pyproject.toml`、`src/` 和 tests；在完成可复现 pin、wheel/hash、隔离 consumer 与包级验收前，它仍是
`SOURCE_PRESENT_UNPINNED / NOT_ACCEPTED`，不得从 PyPI 或 ambient editable 安装回退。

本次登记的**历史子模块基线**为：`bt_api_execution` `2700cb5454ef4c3d1780eda28b6f33307a860998`、
`bt_api_risk` `d0c18a9d503a6792b582d0927244ceb55395032b`、`bt_api_monitor`
`d515a8209324d56742c095d70976593bb3ba3eff`；`bt_api_gateway` remote 为
`https://github.com/cloudQuant/bt_api_gateway`、已挂载 pin `44fd2fe26b51f1d8b573c84415a6cff660f33dea`，当前 `ATTACHED / NOT_PACKAGED`；`bt_api_transport_zmq` 当前为
`NOT_CREATED / NOT_PACKAGED`。这些是历史源码指针；当前 local implementation 仍须记录 pin、wheel/hash 与 consumer evidence，不能代表任何能力已获准实盘。

## 策略运行配置合同

`config.yaml` 是每个 inventory 注册 strategy runtime 的**强制启动合同**。它是本地、精确忽略的 schema-v4
文件；同目录受版本控制 `config.example.yaml` 提供可审阅的策略参数、`runtime.mode` 和 `runtime.preset` 模板。文件缺失、schema 旧、路径未登记或 mode/preset 非法时，启动器必须在连接
provider、导入运行时能力或创建策略之前拒绝，保证 0 网络、0 provider 写入。

普通 profile 的真实凭据放在受保护的 `secrets.yaml` 或操作系统 secret store，`config.yaml` 只保存
`secrets_ref`。**CTP SimNow `simulation/sandbox` 的私有例外**按使用者要求，在未被 Git 跟踪、权限受限的 runtime
`config.yaml` 中配置成对的 `md_front`/`td_front`、合约/交易所/HedgeFlag、账号和认证字段，并使用 `secrets_ref: config_yaml`。
允许单对字段 `md_front`/`td_front`，或可选的有序 `front_pairs` (1–8 组成对唯一映射；两种形式互斥)。不要求代码内静态官方前置 allowlist；sealed `config.yaml` 是端点的唯一来源。单对原样使用；多对只对配置中的候选做有界、重复、无凭据 TCP connect 采样，按 `max(MD median RTT, TD median RTT)` 选最低值，同分按配置顺序，单端失败的 pair 排除、全失败则拒绝。会话和回调固定获胜 pair，不按时间、日历、TradingDay、set 名称自动选档，不发现或回退到未配置 endpoint；受信 provider environment 固定为 `simnow`，不从地址推断 set1/set2。合约、交易所与 HedgeFlag 也由该密封配置提供，按支持的 CTP 规则校验后直接用于只读查询范围，不另行固定单一合约或交易所；旧 profile/selection/calendar 字段拒绝。SDK artifact provenance、凭据解析、认证账户/session 身份、TD/MD 查询及回调账户范围校验仍独立执行，当前写计数必须保持零。fake path 的 focused 合同不等于真实账号或行情验收。
官方 [SimNow 产品页](https://www.simnow.com.cn/product.action) 将 7x24 环境描述为 CTP API 测试用途，且不提供结算等服务。因而 TCP 可达或登录成功不能证明所选前置支持交易/结算；任何相关验收必须由该前置的实际业务回调与账户查询证据判定。
所有受版本控制模板、日志、报告、receipt、异常和公开指纹都不得携带凭据或可重放
capability。历史参数配置必须显式迁移到 v4；不能靠默认值、当前目录、环境变量或无配置 direct 路径继续运行。
当前受限凭据解析器仅在 POSIX 对 `secrets.yaml` 验证所有者和权限后读取；Windows 使用精确名称的 Credential Manager Generic 凭据，`runtime_secrets` 在 Windows 上拒绝。CTP 私有配置分支仍须通过 ACL、Git-index 卫生、SDK provenance、真实只读连接和账号验收。

I6 当前 MD 诊断以本页首段及[I6 证据](evidence/ctp-i6-md-diagnostic-2026-09-25.md)为准；I5/I2 的 TD 与历史 MD 结果见各自证据。SimNow 与未来 CTP production 的唯一运行配置是同一受保护、Git-ignored 的 `runtime-ctp-private/config.yaml`，两者使用相同 canonical `ctp:` 字段结构。未来操作目标是在该文件中改 `runtime.mode`/`runtime.preset` 并替换账号、前置和合约字段，但须先将 live-mode dispatch/admission 接入并独立验收同一 CTP runner；当前仅改字段仍不能运行 production。不得复制出第二份配置，也不得用 set 名称、日历、TradingDay 或时间选择前置。纯 `sealed_config` scope-binding 与 production approval-binding contract 已实现：approval helper 从同一已 seal 配置和所选精确 pair 内部派生 scope identity，只把 `(receipt_digest, scope_identity)` 交给注入的 verifier，避免由 receipt 自称 scope 造成自哈希循环；默认 verifier 拒绝，fake external mapping 的 stale scope/receipt 定向测试通过（与 execution-admission suite 合计 51 项）；另有逐动作 production scope/credential 纯离线合同，旧 SimNow binding type 拒绝，8 项定向合成测试与 Ruff 通过，但未接 SDK、真实 verifier 或默认 route。所有结果仍为非授权观察；维持 NO_WRITE / LIVE_NO_GO。真实受信 mapping/verifier、可信时钟与撤销、每次操作前的磁盘重读、同一 CTP runner 的 live-mode dispatch/admission 和写入 gates 均未验收；完成并独立验收前，生产入口继续拒绝且写入计数为零。

操作者只选择模式和具名预设，不能手动拼装五个插件开关。版本化 preset registry 将它们解析为只读的有效账户访问、
order route 和能力合同：

| 模式 | 示例预设 | 写入边界 |
| --- | --- | --- |
| `backtest` | `local_backtest` | 0 网络、0 外部 provider 写入 |
| `simulation` | `replay`、`shadow`、`paper`、`sandbox` | replay 为 0 网络；shadow/paper 为 0 provider 写入；sandbox 的 registry `write_policy=deny` 默认只做隔离环境私有只读，只有预登记 `receipt_required` profile 获批后才可受管写 demo/SimNow，且 production 写入始终为 0 |
| `live` | `managed_live_direct`、`managed_live_gateway` | 仅受管 execution + risk hard gate + monitor 控制面；必须匹配 live 审批、配置指纹和显式确认 |

上表是 sealed policy catalog，不是当前可启动清单；默认 registry 共 16 条：11 条 source nonmanaged `simulation/replay` runner（8 个普通策略、
`examples/007_ctp` 与 `examples/010_live_examples` 两条 legacy no-action，以及 `sample.py` no-action migration profile）、1 条 zero-write CTP SimNow `simulation/sandbox` RuntimeProfile（普通 CLI `preflight` 当前 fail-closed，等待有总期限的 Windows Job supervisor 与独立验收；`doctor` 离线，`run`/live/write 关闭）、2 条 source fake-provider managed L2 `simulation/replay` runner、1 条公开 OKX `simulation/shadow`，以及 1 条 package-owned `backtest/local_backtest` fixture。shadow 只读公开行情且零外部写；fixture 仅在本地以 Cerebro 跑 4 根 packaged CSV bars，0 network、0 external writes、0 orders/fills/provider submissions、`actual_pnl=NOT_APPLICABLE`；它不构成一般 backtest 或部署路线。`managed_live_gateway`
没有登记 runner；local gateway topology 只能在受信 runtime composition 中使用，不能被解读为 gateway 已可部署或已获 live 准入。

不存在 `live_direct` 或“无配置 direct”的用户启动方式。既有 `Strategy → BtApiBroker/BtApiStore → provider` 映射代码仍可
由某些预设在受限边界内使用，但不能绕过配置、审批和写入控制。命令行、环境变量、AI 产物或当前目录不得覆盖 mode、
preset、route、账户访问或额度；`--confirm-live` 只能确认已配置的 live 合同，不能把其他模式升级为 live。

日常操作收敛为：首次用 `bt-runtime bootstrap` 创建最小配置（已有文件时拒绝覆盖），随后用
`bt-runtime run` 重新校验 config/schema/preset policy 并调度该目录绑定的 runner；当前它不连接账户或执行
provider preflight。CTP 普通 CLI `preflight` 当前 fail-closed/不可运行，只有有总期限的 Windows Job supervisor 实现并独立验收后才可重新评估；`check-ctp-fronts` 仅提供无凭据 TCP 传输证据；

多个默认 replay 示例可通过审核 `iteration41-replay` runtime-set 预检目录与冲突后原子初始化。故障时用只读 `bt-runtime doctor` 查看字段、原因、
mode/目的地、写/PnL 边界和下一条安全命令。当前默认 inventory 的 `run` 只能调度 sealed 注册的 13 条
source/example `simulation/replay` runner（包括两条 fake-provider managed L2）、公开 OKX shadow runner
或 package-owned `backtest/local_backtest` fixture；CTP 配置只读 entry 没有 runner。它不是 live launcher。
完整字段、预设矩阵、迁移和负向合同以[配置与运行模式规格](配置与运行模式规格.md)为准；相关模板、实现和验收见
[模板](templates/config.example.yaml)、[设计文档](设计文档.md)、[迭代计划](迭代计划.md)和[验收文档](验收文档.md)。

## 一句话目标

建立一个由必需 `config.yaml` 驱动的受管执行中枢：策略参数与 `backtest`、`simulation`、`live` 模式在配置中
明确，preset 决定安全的有效 route/能力；`bt_api_execution` 负责受管聚合、拆单、路由与对账，`bt_api_risk` 在每个
允许写入合同的真实边界拦截，`bt_api_monitor` 提供独立监控/控制面。`bt_api_gateway` 可复用账户会话、行情和私有事件路由，
`bt_api_transport_zmq` 只实现其首个传输 adapter，不重定义执行或风控。每个具备写入能力的 example 都必须有 v4
配置和明确的模式/preset 分类；不存在无配置启动旁路。

这不是让现有候选立即获得下单权限的计划。研究未准入、缺少日历/凭据、未完成外部验证、
`RESEARCH_REJECTED`、`NOT_ADMITTED`、production CTP 未受管等状态继续有效。

## 实施承诺

本迭代是**代码实施迭代**，不以文档、接口草图或 mock 作为完成替代。后续实际交付包括：

| 仓库 | 必须实际实现的代码交付 |
| --- | --- |
| `D:/bt_api_py/bt_api/bt_api_execution`（Git submodule；初始仓为空） | 实现新的公开 execution/OMS 包；复用并兼容现有 SDK execution session/journal/lease，提供 parent/child/aggregation/恢复/capability/lifecycle contracts 与最终 provider dispatch gate。 |
| `D:/bt_api_py/bt_api/bt_api_risk`（Git submodule） | 修复现有 fail-open/频率/额度/halt 缺口，实现 durable account-level `RiskPermit`、reservation/settlement/freeze/drain；作为 execution 可选接入的 hard-gate。 |
| `D:/bt_api_py/bt_api/bt_api_monitor`（Git submodule） | 实现 execution outbox consumer、durable checkpoint、health read model、告警与带授权的控制命令；不取得普通开仓能力。 |
| [`cloudQuant/bt_api_gateway`](https://github.com/cloudQuant/bt_api_gateway)（已挂载，仅README，尚未package） | 实现中间件无关的 shared account/session、订阅并集/fan-out、strategy/order correlation、snapshot/replay 和 command-routing contracts；不实现第二个 OMS、风险账本或 provider 真相。 |
| `D:/bt_api_py/bt_api/bt_api_transport_zmq`（近期拟建可选子仓） | 实现 gateway 的首个 ZMQ adapter：socket/framing、认证/ACL、背压、事件转发和 command relay；不拥有 account/session、provider client、execution journal 或 risk ledger。 |
| `D:/bt_api_py` superproject | 维护能力包 pin、兼容版本矩阵、optional extras/dependency lock、严格的 `config.yaml` runtime-plugin loader、组装 integration adapter 和 provider adapter 边界；不复制领域源码。 |
| `D:/source_code/backtrader` | 保留并归责 `Strategy → BtApiBroker/BtApiStore → provider` 的 direct route；为已启用的 direct risk/monitor 提供真实 hook/control 接点，并实现 managed execution 薄适配、allocation 回灌与 TradeLogger bridge。 |

parent 0.15.5 初版候选因短 acct_<16> token 与 full 64-character scope 不匹配而 BLOCK；frozen dual-field candidate commit `af538469…` / wheel SHA `cfa83b1a…` 已通过独立 RECORD 与 151-source-member 审阅，但本次仅证明离线 fake/replay bundle 集成，尚未验收 CTP 路由或 CTP 订单。
每一项都必须包含源码提交、submodule pin、测试、隔离 consumer 验收和脱敏证据。只有这些代码交付与
[验收文档](验收文档.md)同时通过，才能称为 `ARCHITECTURE_ACCEPTED`；计划本身不构成完成声明。

## 为什么现在立项

迭代 27 的下列已登记事实是本迭代的直接输入：

| 迭代 27 记录 | 对迭代 41 的约束 |
| --- | --- |
| `I27-20260921-17`～`20` | 受控日历、研究准入、Windows CTP 运行时与 production CTP 不是 `.env` 可补齐项；新架构不得绕过它们。 |
| `I27-20260921-30` | CTP 的交易日边界与 crypto 7×24 生命周期必须分轨；3600 秒只能保留为工程观察/G3 证据边界。 |
| `I27-20260921-31` | 012 的短时 candidate runner 不能伪装成长期 watchdog；continuous shadow 必须是单独的零写入入口。 |
| `I27-20260921-32` | 账户级风险、策略局部风险、SDK budget 和 TradeLogger 告警当前重复且无统一写入权威。 |
| `I27-20260921-33` | 现有实盘 `parent/oco/transmit` 不具备 provider 级 bracket/OCO 语义；在能力协商完成前必须失败关闭。 |
| `I27-20260921-34`～`37` | `-34` forwarding router、`-35` base gateway 两条 runtime 的默认拒写门已有源码修复与定向回归；`-36` 补齐 risk/monitor 的直接依赖 metadata；`-37` 的双 protocol/runtime、懒导入/optional dependency、认证/ACL、恢复与 CTP gateway 收敛仍待完成。完整 isolated consumer 与本迭代 gateway/transport 验收也仍待完成。 |

完整原始证据见[迭代 27 执行记录](../迭代27-在途工作落库与遗留问题修复/执行记录.md:138)。

## 计划文档

| 文档 | 用途 |
| --- | --- |
| [初始需求](初始需求.md) | 保留用户立项诉求与不应被重构放宽的边界。 |
| [需求文档](需求文档.md) | FR41/NFR41、术语、外部模块基线和非范围。 |
| [配置与运行模式规格](配置与运行模式规格.md) | schema-v4 必需配置、三种模式、preset、秘密边界、统一命令与迁移合同。 |
| [设计文档](设计文档.md) | 模块边界、公共 contracts、状态机、不变量和兼容性决策。 |
| [插件、网关与传输架构](插件与ZMQ架构.md) | 运行时插件加载、direct hook、共享账户 gateway、首个 ZMQ adapter、可靠性与安全边界。 |
| [迭代计划](迭代计划.md) | 工作包、依赖、交付物、迁移顺序和 NO-GO 条件。 |
| [迁移矩阵](迁移矩阵.md) | 所有可写 examples 的盘点规则、分批迁移及 README 交付要求。 |
| [验收文档](验收文档.md) | 可执行验收门、负向合同、证据和最终裁决规则。 |
| [证据目录说明](evidence/README.md) | 后续脱敏 receipt、基线、fault 与迁移制品的命名和保留规则。 |
| [审阅裁决记录](审阅裁决记录.md) | 四份审阅统一裁决、分阶段范围、角色、冻结/变更规则、假设与外部依赖。 |
| [追溯矩阵](追溯矩阵.md) | 初始与更新需求→FR/NFR→WP→AC→证据，含全部81项AC索引。 |
| [能力评估与ADR索引](能力评估与ADR索引.md) | 实码基线、TradeLogger与monitor比较、现有execution复用/聚合层次决策、ADR-41-01～16索引（15、16为提案）。 |
| [验收用例与基准](验收用例与基准.md) | fixture、输入、步骤、预期、风险数值、崩溃恢复、平台性能与资源预算。 |
| [实施状态与验收快照](实施状态与验收快照.md) | 已进入源码的局部证明、当前 NO-GO 与可重放定向验证；不替代最终验收。 |
| [历史实盘策略配置/运行矩阵](evidence/live-strategy-config-matrix-2026-09-24.md) | 逐组确认已有配置、可运行入口、尚缺的真实账号/执行准入与独立验收。 |
| [开发与QA交接清单](开发与QA交接清单.md) | 开发与测试的最短安全操作、不可破坏边界、精确本地验证命令和仍存 LIVE_NO_GO。 |
| [量化交易员审阅意见](量化交易员审阅意见.md) | 原始评审，T01～20已逐条裁决；正式新增AC47～55。 |
| [技术经理审阅意见](技术经理审阅意见.md) | 原始评审，R1～11已逐条裁决；正式新增AC56～60。 |
| [高级需求分析师审阅意见](高级需求分析师审阅意见.md) | 原始评审，RA1～12已逐条裁决；正式新增AC61～66。 |
| [AI系统架构师审阅意见](AI系统架构师审阅意见.md) | 原始评审，AD-AI01～11/I1～7已逐条裁决；其AC47～55与交易员撞号，正式改为AC67～75。 |


## 完成定义

只有同时满足以下条件，迭代 41 才能标记为完成：

1. 每个可写 example/runtime 入口均进入机器可读 inventory，并被标记为 v4 `preset`、`MANAGED`、
   `LEGACY_ADAPTER`、`DISABLED` 或有证据的 `NOT_APPLICABLE`；所有可启动项均有已登记的 `config.yaml`，并且
   受管合同故障不能触发任何 direct 或无配置回退。
2. 每个 `MANAGED` 普通开仓、撤单、replace 和受控减仓均经 SDK 最终写入门、持久化 intent 与身份围栏；
   任一 unknown、持久化故障或围栏变化都冻结该 managed route 的新开仓。`LEGACY_ADAPTER` 保留既有 Broker/Store
   映射语义，但只能由允许的 preset 使用，且不能被表述为经过受管门。
3. managed 聚合执行保存 parent/child、策略归因、额度占用、部分成交和恢复证据；没有把多次普通写入称为
   原子 basket、OCO 或 bracket。
4. 在启用 `bt_api_risk` 的任一路由中，频率、每日次数、撤单、仓位、名义金额、损失、紧急额度和
   `freeze/drain` 均在真实写入/控制边界生效；两条risk-enabled路由共用durable risk reservation；managed route另有child绑定/journal/recovery。启用
   `bt_api_monitor` 时可从 durable event 或 direct runtime event 判断健康并经 账户owner control port（Broker为适配端） 执行
   freeze/drain；TradeLogger 不是其替代品。
5. CTP 与 crypto 分别满足其交易日/连续运行契约；现有研究、审批和生产隔离门不因迁移而放宽。
6. 每份已迁移 example 的 README 说明策略逻辑、参数、模式、preset、有效 route/access/能力、gateway role/transport、
   启动/停止/恢复、`bootstrap`/`run`/`doctor`、本地被忽略的 `config.yaml`、受版本控制的无秘密 `config.example.yaml`、普通 profile 的 `secrets.yaml` 或受限 OS secret store、CTP SimNow 私有 profile 的文件权限与 Git-index 边界、
   凭据脱敏边界、证据位置和当前准入状态；没有把 replay、shadow 或本地测试表述为真实交易通过。
7. `bt_api_execution`、`bt_api_risk`、`bt_api_monitor`、`bt_api_gateway`、`bt_api_transport_zmq` 与 Backtrader adapter 均有实际源码实现、
   各自可安装制品、submodule pin 和跨仓 consumer 回归；`bt_api_py` 通过明确的 optional integration
   使用它们。不得以文档、mock、vendor copy 或 example 内重复实现替代。
8. 每个已登记 strategy runtime 的 `config.yaml` 都通过严格 schema-v4/preset/秘密引用预检；缺失配置、旧 schema、
   非法 mode/preset、CLI override、内联秘密、能力包缺失、未知字段、空 execution 子仓或不兼容合同都在连接 provider
   前 fail-closed。配置变更会形成新的 identity/preflight，不能热加载后沿用旧 permit；backtest/replay/shadow/paper
   必须证明其写入边界，sandbox 必须证明 production 写入为零，live 还必须验证审批、指纹和确认。不得虚报 execution
   journal、aggregation 或 recovery。

9. 至少 013_3 与 P1-B mechanical rail 两个实际 runner 完成 managed L2（fake provider、0外部写入）；
   不能用全部DIRECT/DISABLED或只有包级mock达到完整迁移。
10. 两个参考 runtime 重复手工准备步骤相对基线至少减少 30%（向上取整）；每个历史参数配置均显式迁移到 v4 或记录
    禁用/不适用。日常操作只需 bootstrap（首次）、run（内置验证）和 doctor（排障），独立研究/审批不被合并删除。
11. 核心与gateway按平台完成存储、性能、容量、资源和强杀恢复验收；所有未测预算不能写成实际性能。
12. AI 互操作阶段在 `D:/source_code/backtrader-agent`、`D:/source_code/backtrader-skills`、
    `D:/source_code/backtrader-mcp` 各自仓库交付 schema/exporter/read-only consumer；研究证据、部署 receipt 和
    RiskPermit 严格分离，受信部署入口不能绕过 v4 配置，现有 P0 离线和审批边界保持。
13. 审阅裁决、配置规格、追溯、ADR、机器 inventory、证据索引和全部 81 项 AC 结果一致；外部 BLOCKED 有有效复审记录。

各阶段允许的具体结论以[验收文档§5](验收文档.md#5-最终裁决)为准。核心通过可独立标记
`CORE_ARCHITECTURE_ACCEPTED`；gateway通过标记`GATEWAY_ACCEPTED`；五包及约定AI阶段完整实现、全量适用AC通过才能标记
`ARCHITECTURE_ACCEPTED`；AI另外标记`AI_ASSISTED_MANAGED_DEPLOYMENT_INTEROP_ACCEPTED`。
全迭代范围完成需要所有约定阶段和迁移验收通过，任何阶段PASS不等于LIVE_TRADING_ADMITTED。
这是仍在执行中的开发/测试计划：config-first shell、11 个 nonmanaged replay runner（8 个普通策略、007/010 legacy no-action 和一个 historical sample no-action migration profile）、两个 local fake-provider managed L2、direct managed cancel/reconcile control、local gateway、离线 provider receipt/profile 绑定、CTP 注入式只读预检与 AI review-only interop 已有局部实现和定向测试；
其余跨仓发布、外部会话、完整迁移、性能和 live 验收仍待执行。每项当前边界以[实施状态与验收快照](实施状态与验收快照.md)为准。
