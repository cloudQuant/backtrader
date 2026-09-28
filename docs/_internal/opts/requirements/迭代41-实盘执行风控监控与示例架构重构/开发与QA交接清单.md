# 迭代 41 开发与 QA 交接清单

当前裁决：`PARTIALLY_IMPLEMENTED / LOCAL_TARGETED_EVIDENCE_AVAILABLE / LOCAL_FAST_FUNCTIONAL_PASS / LOCAL_SLOW_STRATEGY_PASS / LOCAL_SERIAL_PERFORMANCE_PASS / LIVE_NO_GO`。

本清单指导本地实现和验收，不授予 provider、账户、CTP、SimNow 或生产交易权限。任何结果都以[实施状态与验收快照](实施状态与验收快照.md)和[验收文档](验收文档.md)的 NO-GO 为边界。

**当前顺序（2026-09-24）：先完成 SimNow。** SimNow 与未来 production CTP 共用同一物理文件 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 和 canonical `ctp:` 字段结构。未来用户操作的目标是仅编辑这一个文件：切 `runtime.mode` 为 `live`、`runtime.preset` 为 `managed_live_direct`，并替换账号/前置/合约参数；该 config-only 操作目标须待同一 CTP runner 的 live-mode dispatch 与 default live write admission 完成并独立验收后才可用。当前代码尚不具备共享 CTP runner 的 live dispatch/默认 live 写入准入，因此今天仅改字段不能交易。当前保护文件保持 SimNow 值；不预填生产账号或前置地址，也不索取生产资料。独立 `runtime-production/`、`ctp_production` parser 和 production prepare helper 均为 legacy/deferred 迁移证据，不是当前操作流程。

**本轮同文件 CTP 与执行账本状态（2026-09-25）：** canonical `ctp:` 的同一受保护配置路径 production read-only 候选 focused suite 为 `104 passed, 1 skipped`，默认 live route 仍关闭；同文件切换是同一 CTP runner 的 live-mode dispatch/admission 实现并独立验收后的未来操作目标，当前仅改配置不能启动 production。`doctor` 的 canonical `ctp`/`front_pairs` 展示修复为 `37 passed`；本机受保护配置的离线 doctor 仅确认 `diagnostic simulation/sandbox` 与 5 个 pair 条目，不记录任何私密字段。Backtrader handoff `27 passed`；CTP managed dispatch/adapter 与 MD request-ID audit 合并焦点集 `38 passed` 且 Ruff clean，但仍是 opt-in/unregistered 离线合同，无 provider acceptance；risk/monitor/execution production-scope checker `10 passed`，同为离线非授权结果，尚未接入真实 provider 或默认 route。`Store/Broker` handoff 四文件焦点集 `125 passed`，含一条既有 pytest 配置 warning，定向 Ruff clean；`bt_api_execution` package tests `57 passed`（含 13 个 command-outbox cases），`py_compile` 与适用 Ruff 检查通过。v5 command outbox 是本地离线候选（package suite `57 passed`），未接 SDK 或默认 runner；调用方提供的 seed proof 不授权。`UNKNOWN` 尚无可信 reconciliation/resolution 路径，会永久 fence 账户声明；跨交易日撤单不支持。因此 command channel 仍未验收。ADR-41-15 已更新 `MaxOrderRef`、旧映射和 command queue 阻断；旧 CTP 入口审计 focused `96 passed`，仅覆盖静态分析与测试，未发现审计范围内的可达绕路。未验收真实会话、报单或撤单。主仓完整 runtime 在本轮更新后的全套复跑为 `1447 passed, 24 skipped, 1 existing PytestConfigWarning in 65.64s`（exit 0）；六个相关 Iter41 integration 文件复跑为 `7 passed, 1 existing PytestConfigWarning in 36.63s`。

**当前 CTP QA 交接（I9 离线候选、I8 真实诊断，2026-09-25）：** 主仓完整 `tests/unit/runtime` 的 I8-era checkpoint（本轮新增合同前）为 `1406 passed, 24 skipped, 1 existing PytestConfigWarning in 61.89s`（exit 0；`python -m pytest -p no:asyncio tests/unit/runtime -q`），保留为历史结果。当前最新完整 runtime 复跑为 `1447 passed, 24 skipped, 1 existing PytestConfigWarning in 65.64s`；六个相关 Iter41 integration 文件复跑为 `7 passed, 1 existing PytestConfigWarning in 36.63s`，MCP `--no-cov` boundary tests 为 `23 passed`。这些均为离线测试，不代表 provider/session readiness 或写入验收；后续代码变更需要复跑。一次真实、受 Windows Job Object 监督的 I8 MD-only 只读诊断以 `incomplete / native_shutdown_uncertain` 结束；父进程确认 child 退出且 Job 为空，但不能据此证明 SDK 原生正常关闭。失败 receipt 的布尔字段不能证明 callback 缺席或交易就绪，诊断 latch 已消耗，不得重置后重试。I8 wheel `f354…` 与 source commit `a7d9…` 已定位，但 `autocrlf=true`/`false` 下的独立 clean-clone builds 均未与保留 wheel 字节一致，原因是 source 含混合换行；需固定 EOL 策略与 build receipt 才能称可复现。I9 callback-deferral 的离线候选已更新：旧 commit `353e9d8…` 的 clean-clone 重建在固定 `SOURCE_DATE_EPOCH` 与 `LINK=/Brepro` 下产生相同 wheel SHA-256 `29f50faa37d145f9b82bdaf4e38b483eff898272925ac082e0d12eb8125cfaf3`，但 artifact metadata 仍标为 i8，不能据此 pin/deploy（receipt：`D:\temp\i9-artifact-repro-20260925\I9-offline-wheel-repro-receipt.md`）。最终离线候选版本为 `2.0.3+iteration41.i9`、commit `157d0c0cffa4c8a86e196159cdf227e9014e9118`；两次独立 clean-clone wheel 字节一致，SHA-256 `aa094c039788a41adf975cfeee839fa3baf1bcef3878ae53d10eefb44410a4a3`，embedded RECORD SHA-256 `d030ccf23d59a5f77230b490df52aa48c4cbecd67b2a78b7e782600126565841`（receipt：`D:\temp\i9-final-wheel-repro-20260925\I9-final-wheel-repro-receipt.md`）。两次安装各有 `95 passed` fake tests；主仓从已安装 wheel 运行 adapter 测试 `26 passed`；SDK 六文件 source suite `204 passed`；Ruff/diff clean。此前 review 发现的 submit-rejection race 已在本地修复并经 barrier test 覆盖。opt-in SDK `managed_outbox_pre_dispatch` fail-closed boundary 的既有焦点为 `9 passed`、combined 为 `47 passed`；无 fresh approval verifier、claim 或 native submit。以上仅为离线证据：主仓 pin/default route 与旧 I8 pin 未变；I9 已在本地处理 `on_login` 响应的 owned copy、callback deferral 及 submit 拒绝竞态；native Join/Release、真实 provider/session 及写入仍未验收，无真实诊断或写入；维持 `NO_WRITE / LIVE_NO_GO`。 未取得完整登录、订阅、tick 或 TD/MD 联合 preflight 证据，也没有报单、撤单。详见[I8 证据](evidence/ctp-i8-md-diagnostic-2026-09-25.md)。I5 及更早诊断均为历史记录。默认 CTP registration 仍只读，保持 `NO_WRITE / LIVE_NO_GO`。

## 1. 开发不可破坏规则

1. 每个登记 runtime 必须从自身唯一 `config.yaml` 启动；只接受 schema-v4 和已登记的 mode/preset。缺配置、旧 schema、重复键、未登记目录、普通 profile 的 inline secret、CLI/环境/CWD 覆盖均必须在导入策略、SDK 或 provider 前失败。当前 SimNow 私有 `simulation/sandbox` 配置以共同 CTP 字段结构 sealed 前置/账户/合约范围。未来 production 开发完成后，将在同一运行配置路径中更改 `runtime.mode`/preset 为 live，并替换 account/front/instrument 参数；当前同一 CTP runner 的 live-mode dispatch/default live write admission 与 SDK pin 尚未实现或接入；pure same-path admission contracts 存在但不在默认 route。现存分立 `runtime-production/config.yaml`、`ctp_production` parser、prepare helper 与未登记 selector 为 legacy/deferred migration 证据，不能作为默认 operator route 或 production readiness；当前 QA 不索取、不填生产字段。无论未来模式如何变化，SDK artifact、真实 account/session、独立 approval 与逐请求写 gate 仍须另行审核，mode 切换本身不赋予权限。
2. 只允许 `backtest`、`simulation`、`live` 作为配置值；当前默认 registry 共 16 条：11 条 source nonmanaged `simulation/replay`、2 条 source fake-provider managed L2 `simulation/replay`、1 条 config-bound CTP SimNow `simulation/sandbox` 私有只读注册（无 runner、能力模块或执行能力，`sandbox_write_policy=deny`）、1 条 public OKX `simulation/shadow` 只读运行时，以及 1 条 package-owned `backtest/local_backtest` fixture；没有 live runner。fixture 仅证明本地 Cerebro 的零外部 I/O；不能通过模板、AI 输出、legacy helper 或默认值添加 live 路径。
3. config loader 必须保持 leaf 的文件身份检查和 descriptor read；runner 必须消费 sealed in-memory effective config，禁止第二次读配置。Windows 未支持 `O_NOFOLLOW` 不是放宽其他检查的理由：config load、bootstrap 和 runner 全程必须保持拒绝 delete-share 的目录 lease，并用 handle `fstat` 重验登记 identity。POSIX 的受管 `bt-runtime run` 在取得登记目录 fd 后必须向 opt-in runner 传入 `runtime_dir=None`、无路径 sealed effective/config/registration view、opaque registry token 和 opaque fd-backed capability；14 条 source/example runner（含公开 shadow，不含 package-owned `backtest/local_backtest` fixture）均已 opt-in，013_3 的旧 path-based evidence writer 只能使用 private workspace，不能重建被隐藏的 runtime pathname。
4. managed execution 必须根据实际 Backtrader order 重算并校验 instrument、LIMIT、side、quantity/unit、price、offset、reduce-only、metadata digest；禁止信任可伪造的 `order.info` 或走 legacy fallback。
5. cancel ACK/UNKNOWN 仅能进入 pending/reconciliation/freeze；未取得终态不得本地取消、删除映射、解冻或重派。
6. AI 三仓只生成或校验 review evidence，不能进入 execution、cancel、control、账户或凭据面。source inventory、local wheel hash 或 review interop 的通过也不能成为 deployment receipt、人工签发、RiskPermit 或 provider 权限；三个 checkout 任一 dirty-state 改变后必须重新采集并复审。

## 2. 推荐的最短操作路径

```powershell
bt-runtime bootstrap --strategy-dir <registered-runtime-dir>
bt-runtime doctor --strategy-dir <registered-runtime-dir>
bt-runtime run --strategy-dir <registered-runtime-dir>
```

`bootstrap` 不覆盖已有配置；`doctor` 是只读离线诊断且不导入 runner；runner 只在 `run` dispatch 时懒加载。`run` 不支持 `--mode`、`--preset`、`--config` 或同义环境变量。两条 managed L2 仅用于 local fake-provider 工程验证，不能作为 CTP/SimNow/live 操作手册。

## 3. QA 准入门和失败判定

| 门 | 必须检查 | 失败判定 |
| --- | --- | --- |
| G1 配置封闭 | 缺失/替换/旧 schema/secret/override 都零 I/O 拒绝；013_3 direct entry 同样受门保护 | 任一后续 import、文件重读、mode 升级或秘密泄露为 `FAIL`。 |
| G2 managed intent | 实际 order 与 admitted intent 的全字段 canonical binding；mutation 在 dispatch 前拒绝 | provider 调用发生、quantity unit 未绑定、或 fallback 发生为 `FAIL`。 |
| G3 cancel/unknown | ACK/UNKNOWN 保留挂单与映射；freeze、reconcile、restart 均不重派 | 本地 terminal cancel、自动 release 或新开仓为 `FAIL`。 |
| G3a v5 command-outbox CANCEL-as-Modify shape gate | 验证 `operation=CANCEL` 只有在原生 `ActionFlag="0"` 且 `LimitPrice`/`VolumeChange` 为零或省略时才可调用 native；分别用 `ActionFlag="3"`、非零 `LimitPrice`、非零 `VolumeChange` 断言调用前拒绝且 native-call counter 为 0。用 realistic v4 schema/data migration fixture 升级，确认所有既有 v4 rows/values 原样保留且新增 v5 command structures。 | v5 本地 package suite 为 57 passed；仅离线候选，不接 SDK/default runner，非授权、非 provider 证据；seed proof 不证明外部 writer fence，`UNKNOWN` 缺可信 reconcile/resolution 路径且跨交易日撤单不支持，保持 `NOT_ACCEPTED / NO_WRITE`。 |
| G4 SDK durable recovery | permit settlement proof、fencing、DISPATCHING crash 点、sealed metadata snapshot 的 fault injection | 任一没有证明则 `NOT_RUN`/`FAIL`；不可写为 full recovery PASS。 |
| G5 framework projection | 验证 SDK fill 后、Backtrader projection 前崩溃的跨进程恢复 | `LOCAL_TARGETED_PASS`：SQLite receipt 可在 fresh framework session 恰好一次重建 order、position、commission、TradeLogger 且零 provider dispatch；真实账户 position/cash 对账、强杀、gateway 和跨存储/observer 原子恢复仍为 `BLOCKED`。 |
| G6 最终回归 | 核心定向集、SDK targeted、并行 fast functional lane、策略 slow tier、serial performance、writer inventory 与机器可读处置清单均已有本轮本地结果 | fast functional lane 排除 slow/performance；slow tier 仅为本地离线策略回归。serial performance 主集与隔离短压测均为 `LOCAL_SERIAL_PERFORMANCE_PASS`（`27 passed, 6687 deselected, 1 warning in 51.56s`；`1 passed, 1 warning in 0.73s`），只覆盖本机串行范围，不覆盖平台、容量、长稳、HFT、真实 provider 或 live。inventory 为 181 files、137 writer candidates、24 dynamic candidates、0 parse errors 的 `CANDIDATE_DISCOVERY_ONLY`；161 项处置记录均为 `REVIEW_REQUIRED / NOT_AVAILABLE / UNRESOLVED_POTENTIAL_LIVE_WRITE`，包含责任角色、保守 route、测试节点和静态 trace/evidence disposition。不能以它替代真实写入或 live 验收。 |
| G7 外部准入 | provider/account/CTP/SimNow、身份与审批、强杀/平台/性能、真实 cancel/fill race | 未逐项完成时保持 `LIVE_NO_GO`。 |
| G7a shared CTP config migration (implemented; default live integration pending) | Confirm SimNow and future CTP use the same registered runtime `config.yaml` path and canonical `ctp:` block; no second production config. Current SimNow config is protected/ignored and has five ordered pairs, including the official 7x24-hour pair; both endpoints of that pair are currently TCP-unreachable. Offline `doctor` passes; older four-pair digests are historical. Verify same field shape, seal/redaction, duplicate/malformed-field rejection, ACL/identity/index hygiene, and future live-mode mutation remains fail-closed before SDK/network/write while runner/admission is absent. | Shared parser/helper/private-config migration landed; follow-up must verify same-path sealing and default live fail-closed behavior. No production values are requested or prefilled. |
| G7b legacy/deferred production parser evidence | Keep old independent `ctp_production` parser/selector results only as historical code-snapshot evidence (`60 passed, 1 warning`; earlier `137 passed, 4 skipped`). Do not create the second config or treat these tests as current operator flow. | These records do not prove the shared schema implementation, shared CTP runner live-mode dispatch/admission integration, or production readiness; no production fields or credentials are requested in this phase. |
| G7c SimNow 真实报撤单 | 在唯一受保护 `config.yaml` 的 `simulation/sandbox` 范围，按已配置整组 MD/TD 前置完成可复核的原生登录、订阅、目标 tick、结算查询和正常关闭；写入前证明账户级独占、同源持久 OrderRef、可信逐动作审批、execution+risk+monitor 及账户敞口。用最小受控订单逐项核对 native 报单/撤单请求、回调、订单/成交/持仓/资金终态、UNKNOWN 冻结与重启恢复；保留脱敏原始证据、制品哈希、失败停止条件。 | 当前 `NOT_RUN / NO_WRITE`。TCP 可达、离线 fake、SDK 队列返回 0、局部 callback、进程退出或 read-only preflight 任一单项均不能判 PASS；原生关闭仍不确定时不得进入下一组前置或写入。 |
| G7d 同文件切换生产账号 | 在 G7c 及独立生产制品/账户/审批/风险验收之后，只修改同一 `config.yaml` 的 `runtime.mode/preset` 与 `ctp:` 账号、前置和合约参数；重新 `doctor`、独立生产 preflight、审批绑定及最小实盘报撤单验收。QA 必须验证 SimNow seal/receipt/approval 在 live 下失效、候选 MD/TD 不混搭、配置外地址不访问、任何失败在 SDK 写调用前拒绝且不自动切回 SimNow。 | 当前 `NOT_RUN / LIVE_NO_GO`。同字段结构与 parser PASS 不等于共享 CTP runner 的 live dispatch、账户或交易准入；不得另建常规生产配置，也不得复用 SimNow 审批证据。 |
| G8 AI review 边界 | [source inventory](evidence/ai-producer-source-inventory.json) 的根路径、commit、dirty manifest 与 source hash；[wheel vector](evidence/ai-wheel-review-interop.json) 的 supplied wheel hash、`review_only` authority 及本地向量结果 | 任一 checkout 身份/dirty manifest 与 artifact 不一致、把 local wheel vector 写成发布/部署/import-origin 证明，或据此给予 AI account/control/deployment 权限，均为 `FAIL`；AI AC 不得标 `PASS`。 |

### 完整 runtime 回归与后续复验

receipt 与 SDK artifact-origin 改动后，较早完整 `tests/unit/runtime` 结果为 `1035 passed, 26 skipped, 1 warning in 55.97s`，exit 0；[日志](../../../../../artifacts/iteration41_runtime_suite_20260924_after_receipts.log)和[退出码](../../../../../artifacts/iteration41_runtime_suite_20260924_after_receipts.exit)已保存在 artifacts。本地运行命令为 `python -m pytest tests/unit/runtime -q --tb=short`，并设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。Warning 是 pytest 配置中的 `asyncio_default_fixture_loop_scope` 未被当前插件集识别。该全套结果早于 query-evidence verifier 与后续 source changes，之后曾由 `1078 passed, 27 skipped`、`1085 passed, 27 skipped`、`1094 passed, 27 skipped`、`1114 passed, 26 skipped`、`1116 passed, 26 skipped`、I2 的 `1156 passed, 26 skipped` 及 I5 的 `1225 passed, 24 skipped` 等运行取代；这些数字都属于历史工作树快照，详见[I5 证据](evidence/ctp-i5-md-diagnostic-2026-09-25.md)。I8 `1406 passed, 24 skipped, 1 existing PytestConfigWarning in 61.89s` 是历史 checkpoint，已由本页开头记录的 `1447 passed, 24 skipped, 1 existing PytestConfigWarning in 65.64s` 全套复跑取代；后续代码变更仍须重新复跑。旧 baseline-6 的 `1126/27` 结果也是历史快照。

更早的 `1029 passed, 26 skipped, 1 warning in 64.43s` 快照在 dispatch-receipt 改动之前，仍保留在[原始日志](../../../../../artifacts/iteration41_runtime_suite_20260924.log)、[退出码](../../../../../artifacts/iteration41_runtime_suite_20260924.exit)和[复跑脚本](../../../../../artifacts/iteration41_runtime_suite_20260924.ps1)中，不能代表 receipt 后的结果。新加 `ctp_simulation_query_evidence.py` verifier 的精确测试为 `4 passed, 1 warning`；测试会通过本机 `bt_api_ctp`/`bt_api_base` source `PYTHONPATH` 启用，未提供 SDK source path 时模块跳过。这个 verifier 不授予 authority，也不证明跨查询原子账户快照、外部 writer fence 或 durable cancel history。因它已进入工作树，应对交付 revision 重跑完整 runtime 集并存入独立、带时间戳的 artifacts：

```powershell
Set-Location D:\source_code\backtrader
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$runTag = Get-Date -Format 'yyyyMMdd_HHmmss'
$suiteLogPath = "artifacts/iteration41_runtime_suite_after_receipt_$runTag.log"
$suiteExitPath = "artifacts/iteration41_runtime_suite_after_receipt_$runTag.exit"
& python -m pytest tests/unit/runtime -q --tb=short *> $suiteLogPath
$suiteExitCode = $LASTEXITCODE
Set-Content -LiteralPath $suiteExitPath -Value $suiteExitCode -NoNewline -Encoding ascii
exit $suiteExitCode
```

新增 query-evidence verifier 的焦点复现（需要可用的 task-local SDK source；无此 `PYTHONPATH` 时测试模块会跳过）：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONPATH='D:\bt_api_py\bt_api\bt_api_ctp\src;D:\bt_api_py\bt_api\bt_api_base\src'
python -m pytest tests/unit/runtime/test_ctp_simulation_query_evidence.py -q --tb=short
```

QA 记录本次 `git rev-parse HEAD`、工作树是否 dirty、Python 版本、开始时间、完整 pytest summary、warning/skip 原因、exit code 与新 artifact 路径。仅当测试对应的代码 revision 与工作树一致时，才将其标为该 revision 的本地 runtime 回归。另一次 receipt 后 integration 定向合跑见[本地验证汇总](evidence/validation-summary-2026-09-24.md)：5 passed、1 warning、exit 0，未产生 provider I/O。真实 CTP 账号、provider 与 live 验收仍为 `NOT_RUN / LIVE_NO_GO`。

**Historical QA checkpoint (I1, 2026-09-24; superseded by later I2/I5 evidence):** I1 offline CTP guard reported 913 passed, 1 skipped; Backtrader focused tests 95 passed; I1 runtime reported 1153 passed, 26 skipped, 1 warning. These suites made no provider I/O. I1 TD completed seven queries but Join shutdown failed; independent MD-only observed request_id_mismatch, login timeout, no ACK/tick, and zero writes. I1 artifact pin covered only registered SimNow sandbox read-only. This history is not current provider evidence.

## 4. 可复制的本地命令

### 配置 core

```powershell
C:\anaconda3\python.exe -m pytest -q -p no:asyncio `
  tests/unit/runtime/test_runtime_config.py `
  tests/unit/runtime/test_runtime_batch_bootstrap.py `
  tests/unit/runtime/test_runtime_runner.py `
  tests/unit/runtime/test_runtime_operator_flow.py `
  tests/unit/runtime/test_iteration41_legacy_013_3_gate.py `
  tests/unit/runtime/test_iteration41_static_runtime_inventory.py
```

本节小范围命令用于快速诊断，不再以旧的局部计数作为本轮结论。覆盖本节及后续 managed/inventory 范围的核心定向集结果为 `312 passed, 3 skipped, 1 warning in 106.64s`；其范围和边界见[本地验证汇总](evidence/validation-summary-2026-09-22.md)。

Windows directory lease 的三条跨进程回归为 `test_windows_directory_lease_closes_if_the_post_acquire_identity_check_fails`、`test_windows_bootstrap_directory_lease_blocks_parent_replacement_before_write` 与 `test_windows_runner_directory_lease_blocks_path_swap_before_runner_side_effect`；本机结果为 `3 passed, 1 warning in 0.83s`。它们必须在 Windows 本地文件系统重跑，不能用 POSIX、特权或内核级文件系统行为替代。

POSIX runtime-directory capability 的 runner suite 为 `32 passed, 2 skipped`，runner + static inventory 为 `38 passed, 2 skipped`；这些是 Windows 本机的 portable contract/focus 结果。`test_posix_runner_capability_keeps_local_output_off_a_replacement_path` 与 `test_posix_runner_capability_rejects_a_symlinked_child_component` 在此 Windows host 为 `NOT_RUN`，必须在真实 POSIX 文件系统重跑。公开 direct `run_runtime(..., effective=None)` 会在读取 `config.yaml` 或检查 runtime pathname 前以 `runner_dispatch_required` 拒绝；开放 P1 是实际 POSIX filesystem regressions 尚未执行，以及 path-free view/opaque token 并非 hostile in-process Python 隔离或沙箱。

### Backtrader managed targeted

```powershell
$env:BT_API_PY_LIGHT_IMPORT='1'
$env:PYTHONPATH='D:\bt_api_py;D:\bt_api_py\bt_api\bt_api_base\src;D:\bt_api_py\bt_api\bt_api_execution\src;D:\bt_api_py\bt_api\bt_api_risk\src;D:\bt_api_py\bt_api\bt_api_monitor\src;D:\bt_api_py\bt_api\bt_api_gateway\src;D:\bt_api_py\bt_api\bt_api_transport_zmq\src'
C:\anaconda3\python.exe -m pytest -q -p no:asyncio -n 0 `
  tests/unit/runtime `
  tests/unit/stores/test_managed_execution_store_adapter.py `
  tests/unit/brokers/test_btapibroker_managed_execution_projection.py `
  tests/unit/live_certification/test_simnow_investor_id_redaction.py `
  tests/integration/test_iteration41_managed_replay_l2.py `
  tests/integration/test_iteration41_ctp_mechanical_managed_replay_l2.py `
  tests/integration/test_iteration41_managed_execution_composition.py `
  tests/integration/test_iteration41_managed_cancellation_composition.py `
  tests/integration/test_iteration41_framework_projection_recovery.py `
  tests/integration/test_iteration41_gateway_store_composition.py `
  tests/integration/test_iteration41_deployment_evidence_interop.py `
  tests/unit/scripts/test_collect_iteration41_writer_inventory.py
```

该完整核心定向集已有 `312 passed, 3 skipped, 1 warning in 106.64s` 的历史本地结果；本次新增的 framework projection/bridge focused 集为 root `74 passed`。其中仅离线/fake-provider 范围可标 `LOCAL_PASS`；它不替代真实 provider 或 live 验收。独立 bridge 焦点集为 `84 passed, 1 warning in 46.79s`。

### SDK final targeted

```powershell
Set-Location D:\bt_api_py
C:\anaconda3\python.exe -m pytest -q -p no:asyncio tests\runtime_plugins
```

该命令的 runtime plugin 组已得到 `80 passed, 1 warning` 的本地结果。execution、risk、recovery、environment verifier 与 CTP client 的其他 SDK 焦点组也已执行；精确计数见[本地验证汇总](evidence/validation-summary-2026-09-22.md)。这些均为离线/fixture 验证，不能写成真实 provider 或 live PASS。

本次 framework projection 还要求执行 `D:\bt_api_py\bt_api\bt_api_execution` 全套（`31 passed`）和
`D:\bt_api_py\tests\runtime_plugins\test_capability_composition.py`（`25 passed`）。runner capability
origin fence 的完整本仓回归为 `tests/unit/runtime/test_runtime_runner.py`（`32 passed, 2 skipped`）；它覆盖
CWD shadow、预加载未登记模块和 allowlisted 子模块的 meta-path fallback，但不构成受信部署/发布证明。

### 并行 fast functional lane（排除 slow/performance）

```powershell
Set-Location D:\source_code\backtrader
$env:BT_API_PY_LIGHT_IMPORT='1'
$env:PYTHONPATH='D:\bt_api_py;D:\bt_api_py\bt_api\bt_api_base\src;D:\bt_api_py\bt_api\bt_api_execution\src;D:\bt_api_py\bt_api\bt_api_risk\src;D:\bt_api_py\bt_api\bt_api_monitor\src;D:\bt_api_py\bt_api\bt_api_gateway\src;D:\bt_api_py\bt_api\bt_api_transport_zmq\src'
C:\anaconda3\python.exe -m pytest tests -m "not slow and not performance" -n 8 -q -p no:asyncio
```

并行 fast functional lane 已在最终工作树通过：`5865 passed, 11 skipped, 35 warnings in 182.43s (0:03:02)`，状态为 `LOCAL_FAST_FUNCTIONAL_PASS`。该命令排除 slow/performance，不能当作 `make test-fast` 或 serial performance 的 PASS；它仍只是本地质量门，不会解除任何 live NO-GO。

### 策略 slow tier（本地离线）

```powershell
Set-Location D:\source_code\backtrader
$env:BT_API_PY_LIGHT_IMPORT='1'
$env:PYTHONPATH='D:\bt_api_py;D:\bt_api_py\bt_api\bt_api_base\src;D:\bt_api_py\bt_api\bt_api_execution\src;D:\bt_api_py\bt_api\bt_api_risk\src;D:\bt_api_py\bt_api\bt_api_monitor\src;D:\bt_api_py\bt_api\bt_api_gateway\src;D:\bt_api_py\bt_api\bt_api_transport_zmq\src'
C:\anaconda3\python.exe -m pytest tests -m slow -n 8 -q -p no:asyncio
```

本机记录为 `810 passed, 11 warnings in 272.80s (0:04:32)`，exit 0，状态为 `LOCAL_SLOW_STRATEGY_PASS`。这只覆盖本地、离线的 marker-selected strategy tier；它不覆盖跨平台、容量、长稳、HFT、真实 provider 或 live 验收。

### Serial performance（本机串行）

```powershell
C:\anaconda3\python.exe -m pytest tests -m performance -n 0 -q --deselect=tests/unit/test_iteration22_ctp_benchmarks.py::test_short_stress_profile_waits_for_deadline_and_is_incomplete -p no:asyncio
C:\anaconda3\python.exe -m pytest -q -n 0 -p no:asyncio tests/unit/test_iteration22_ctp_benchmarks.py::test_short_stress_profile_waits_for_deadline_and_is_incomplete
```

两条命令均已在本机串行通过：主集为 `27 passed, 6687 deselected, 1 warning in 51.56s`，隔离短压测为 `1 passed, 1 warning in 0.73s`，状态为 `LOCAL_SERIAL_PERFORMANCE_PASS`。结果关闭的是本轮这两条本机 serial 命令，不覆盖 Windows/Linux 性能矩阵、容量、长稳、HFT、真实 provider 或 live 验收。

### Package fixture 与本机 capability bundle（仅 offline local wheelhouse）

早期 package fixture direct-dispatch 仍保留为 source-lane 回归：`1 passed, 1 warning in 8.82s`，两条路径分别为 `LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS` 与 `LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS`，且均断言 fixture 未经 source wrapper、`external_network_requests=0`、`external_write_requests=0`。该 lane 使用 `D:/bt_api_py` 源码 capability 环境，不能用于判断 fresh-wheel consumer。

[capability-bundle-local-windows.json](evidence/capability-bundle-local-windows.json)（SHA256 `2ad986457abf776bea581a064fae4fa433d98d5db2343df01903dc9ce8e18225`）已在全新 venv 的 `python -I`、`--no-index` 本地 wheelhouse 中安装 Backtrader 与七个 `bt_api_*` project wheels；安装、`pip check` 和 probe 均 exit 0，模块与 dist-info origin 均在该 venv 的 `site-packages`，本地项目 RECORD 已验证。generic fake managed composition 为 `ACKED`（1 次 fake-provider call）；两个 packaged L2 fixture 分别为 `LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS` 与 `LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS`，每条均 `external_network_requests=0`、`external_write_requests=0`、`actual_fills=0`，`network_guard_attempts=0`。

开发与 QA 对该本地 bundle 的可操作验收条件：

1. 重新计算 [原始 JSON](evidence/capability-bundle-local-windows.json) 的 SHA256，必须等于 `2ad986457abf776bea581a064fae4fa433d98d5db2343df01903dc9ce8e18225`；解析后 `local_validation=PASSED`、`result=LOCAL_EVIDENCE_ONLY`、`release_status=NOT_RELEASE_ELIGIBLE`。
2. `consumer.local_wheelhouse_only=true`，`install`、`dependency_check`、`probe` 的 exit code 均为 0；安装命令必须保留 `--no-index --find-links`，probe 必须保留 fresh-venv `python -I`。
3. 全部 `local_install_bindings.*.installed_record_validated=true`，每个 module 与 dist-info metadata path 均在 consumer venv 的 `site-packages`；不得从 source checkout、`PYTHONPATH`、user-site 或 PyPI 补齐。
4. `probe_payload.execution_state=ACKED`、`fake_provider_calls=1`；两个 `l2_fixture_reports` 的状态必须精确匹配上述两值，且每条 `external_network_requests`、`external_write_requests`、`actual_fills` 均为 0，`network_guard_attempts=[]`。
5. 任一断言不满足即拒绝这条本地证据，不得降级解释为 release 或 live PASS；即使全部满足也必须保留 `该 bundle 的结论严格为 `LOCAL_EVIDENCE_ONLY / NOT_RELEASE_ELIGIBLE`：仅证明 Windows 本机、离线 local-wheelhouse 的机械 consumer 行为；不证明已审阅/签名/发布制品、可信依赖 provenance、部署或 server admission、provider/account/credential/人工授权或 live。Backtrader 与各能力源树仍 dirty，且 OS network firewall 未验证。`

### CPython 3.8 无 SDK core config/operator

Windows 本机 CPython 3.8.20 已实际执行 harness 并通过：`75 passed, 3 skipped, 1 warning in 2.17s`，exit 0；[原始 JSON](evidence/cpython38-core-runtime-local-windows.json)保存解释器、平台、命令和 no-SDK scope。QA 仍须取得 `.github/workflows/test.yml` 的 Ubuntu 22.04 `iteration41-cpython38-core-runtime` GitHub CI artifact；Windows 本地结果不能写成跨平台或 CI PASS。

### AI 三仓 review evidence（仅 source/local wheel）

```powershell
Set-Location D:\source_code\backtrader-agent
C:\anaconda3\python.exe -m pytest -q -p no:asyncio tests\test_deployment_evidence.py

Set-Location D:\source_code\backtrader-skills
C:\anaconda3\python.exe -m pytest -q -p no:asyncio tests\test_deployment_evidence.py
C:\anaconda3\python.exe scripts\build_manifest.py
C:\anaconda3\python.exe scripts\build_manifest.py --check

Set-Location D:\source_code\backtrader-mcp
$env:PYTHONPATH='src'
C:\anaconda3\python.exe -m pytest -q --no-cov tests\test_deployment_evidence.py

Set-Location D:\source_code\backtrader
C:\anaconda3\python.exe -m pytest -q -p no:asyncio `
  tests\integration\test_iteration41_deployment_evidence_interop.py `
  tests\unit\runtime\test_iteration41_review_evidence.py
C:\anaconda3\python.exe scripts\collect_iteration41_ai_producer_inventory.py `
  --agent-root D:\source_code\backtrader-agent `
  --skills-root D:\source_code\backtrader-skills `
  --mcp-root D:\source_code\backtrader-mcp `
  --output docs\_internal\opts\requirements\迭代41-实盘执行风控监控与示例架构重构\evidence\ai-producer-source-inventory.json
```

本轮记录分别为 agent `23 passed`、skills `15 passed`、MCP `57 passed in 0.55s`、Backtrader 跨产品
review tests `12 passed, 1 warning`；skills manifest 为
`cb78d74dcaf043151e2298e1320ffe141da723e5bf2864ad6533805efe8580fe`（76 files）。这些命令和
source inventory 只复验本地源代码边界。wheel artifact 只能以独立审阅过的三份 supplied wheel 运行
`scripts/run_iteration41_ai_wheel_interop.py` 复现，并须将新 hash 写入 artifact；不允许从 PyPI、ambient
editable 或 source checkout 推导其 isolation。详细 hash、`-I -S` 向量和限制见[证据索引](evidence/README.md#ai-三仓-source-checkoutwheel-与配置证据)。

[external-ai-wheel-interop-local-windows.json](evidence/external-ai-wheel-interop-local-windows.json)（SHA256 `738e548ce649b6af9ae203b3f39d1ea179e236cfd5d72e3b2f8ecb4e9fcb1f30`）状态 `passed`，是 8-wheel 本地 source-to-wheel → fresh-venv `python -I -s` 的只读 review handoff：RECORD 与 module origin 为 `site-packages`，source checkout 与 provider modules 不在 probe 中，run root 为空。它明确是 `external_bt_api=false`（artifact 字段 `external_bt_api_capability_wheels_verified=false`）的 review-only 证据；`execution=false`、`provider_network=false`、`live_admission=false`。Agent→Skills 仅 valid/read_only、authorization=false、promotion 被拒绝；MCP 为 `REQUIRES_INDEPENDENT_REVIEW` 且 authority flags 均 false。

该 AI 制品不证明 trusted release/deployment/server admission、provider/account/credential、human authorization 或 live；不能作为 capability package 或执行路径的准入证据。

## 5. CTP 私有路径与真实账号验收闸门

SimNow 与未来 production CTP 的配置目标是同一物理 `runtime-ctp-private/config.yaml` 和 canonical `ctp:` 字段。当前文件有五组成对候选；新增官方 7x24 小时 pair 的 MD/TD TCP 检查均不可达。**共用文件不等于已共用可执行路由**：默认 inventory 在同一 registration 内允许 `simulation/sandbox` 私有只读，并将 `live/managed_live_direct` 明确声明为 unavailable；后者在凭据解析、SDK、网络或 runner 前以 `managed_live_direct_profile_unavailable` 拒绝。registry 仍拒绝同一规范化目录的第二条 registration。当前先完成 SimNow 只读验收；未来 production 只有在 reviewed live route/authority、审批和独立准入实现并验收后，才可把 operator 操作收敛为编辑同一文件的 mode/preset 与 CTP 参数。不得复制配置目录或放宽当前只读 registration。此前 digest 与四候选结果均属历史。

**Historical SDK / runtime QA boundary (I1; superseded by later evidence):** I1 installed-wheel CTP guard was 913 passed, 1 skipped; focused Backtrader tests 95 passed; full I1 tests/unit/runtime 1153 passed, 26 skipped, 1 warning. No provider I/O occurred in these suites. I1 official preflight failed at Join shutdown after seven TD queries; MD-only received one request-ID mismatch callback and ended login timeout / stop failure / Join pending with no ACK, tick, or write. I2 full-preflight history is in the [2026-09-24 validation summary](evidence/validation-summary-2026-09-24.md); I5's later independent MD-only diagnosis and post-pin runtime result are in the [I5 evidence](evidence/ctp-i5-md-diagnostic-2026-09-25.md). Managed third parent pin/account-wide writer exclusivity remain open; live preset/default registry fail closed, LIVE_NO_GO.

### P0：AI/MCP 与私有 CTP 配置隔离（阻断）

跨仓审计发现三条 P0 风险：`backtrader-agent` 可能把私有 runtime `config.yaml` 的原文返回给 AI；`backtrader-mcp` validator 曾漏掉 `bt.stores.BtApiStore`，使 draft 可能直接构造 Store/provider 绕过 Iter41 `config.yaml` sealed candidate membership；`ChangeService` 在重叠目标根下可能替换私有 config。修复代理报告已加入 `protected_paths`、Store 引用校验、ChangeService 写前 hash/恢复保护及 JobService 私有路径重叠拒绝，定向 `12 passed`、静态合跑 `47 passed / 7 deselected`。这些只是局部本地结果：worker 尚无 OS 级网络隔离，静态校验不能证明任意动态 Python 零网络；Windows 旧套件仍被 `os.fchmod`、目录 fsync 与 SIGKILL 测试限制，尚无部署隔离或外部验收。OS 隔离可行性、提案后端与验收条件见[AI worker 网络隔离证据](evidence/ai-worker-network-isolation-feasibility.md)；后端仅为提案，OS 级验证 `NOT_RUN`，provider-capable AI worker 仍为 `LIVE_NO_GO`。AC41-84 仍为 `P0_BLOCKED / NOT_RUN`；任何可能触达 CTP/provider 的 AI runtime 候选一律 `NO_GO`，直到部署级隔离与独立外部验收完成。

交接验收需分别证明：AI/tool 输出与日志不含私有 config 原文、password、AuthCode 或可重建摘要；AI 无法读、写、移动或替换私有 config；validator 覆盖 `BtApiStore` 直接、别名和间接构造；相邻/重叠目录、别名路径与文件替换竞争被拒绝。provider/SDK/network/write 在拒绝路径应为 0，配置内容及文件身份保持不变，外部写计数为 0；对允许执行的任何 AI 生成/动态 Python，另需部署级 OS 网络隔离和独立外部验收，静态 AST/validator 结果不能替代。上述局部修复与测试不解除 P0，也不授权 AI/MCP 触达 CTP/provider。

### 私有目录的单配置操作

当前 SimNow 操作只编辑已登记目录中受保护且被 Git 精确忽略的 `config.yaml`，使用 `runtime.mode: simulation`、`runtime.preset: sandbox`。`ctp.md_front` 与 `ctp.td_front` 必须成对配置，或提供 1–8 组成对、唯一的 `front_pairs` 明确候选；单对原样使用，多对只在该列表内做有界、无凭据 TCP RTT 选择。相同文件填写当前合约、交易所、HedgeFlag、BrokerID、UserID、密码及终端认证字段；不要另传切档参数、日历或账号文件。旧选择/日历字段不允许出现。可从[私有模板](templates/config.ctp.example.yaml)核对键名；模板的合约和本地账号/密码占位符不能直接运行。canonical `ctp:` parser 可接受 live schema；默认 registry 只标记该 profile 为 unavailable，没有 live runner 或写入 route。

统一配置准备入口为 `bt-runtime prepare-ctp-config`；它只生成当前 `simulation/sandbox` 配置，不提升 mode 或 route。旧 `prepare-ctp-production-config` CLI 已退休并必须拒绝；`runtime-production/` 与 `ctp_production:` parser 仅保留 legacy/deferred 迁移或兼容测试语义；旧内部生成函数也已退役，在读取来源或创建目标前拒绝，不能创建第二套 operator 配置。配置变更后 `doctor` 是可选离线检查，`preflight` 才是显式 CTP 只读 provider 命令。I2 pin 仅限登记的 SimNow sandbox read-only route。I2 TD retry 七 query 完成但 Join 关闭不完整；独立 MD-only 在 one-second teardown grace 后仍因 zero request ID strict reject，无 ACK/tick/写入；这些是 I2 历史结果。I1/H2 与四对配置均为历史。CTP SDK I3 one-shot MD zero-ID 诊断候选（不同于 WP41-I3 AI 工作包）位于隔离 clean worktree commit `f314792a`；独立源码审阅已对 callback stop 与 Join/Release handshake sign-off，focused fake `94 passed`，扩展 source CTP `417 passed, 1 deselected`。该扩展集排除两个旧失败文件；I2/I3 对它们均有相同的 32 个 failure names/messages。候选尚未 build wheel、pin、provider 验收或合入。I4/I5 后续独立候选的真实 MD 诊断仍未接受登录、订阅或 tick，且 native Join 未完成；I5 的空 getter 观察不能证明账号错误。G1 parent OrderRef adapter 仅为 branch `9bb788c2` 的隔离源码候选/测试，尚无基于该 commit 构建并受审的 wheel，也未 pin/merge；源码候选涉及可持久化并重启读回的 OrderRef 映射，Backtrader port adapter 仍未接线：首次 submit 在 parent `build_order_request`/reservation 前解析 ID，direct `TraderClient` cancel 不建立 parent `unresolved` 状态，resolver 为 set1-only。Backtrader direct-runtime SQLite 与 parent BtApi JSONL 都含状态，不能拼成两个 authority。按 D41-01/D41-19，F14 前须用 ADR 冻结唯一 active authority/cutover；目标是独立 `bt_api_execution` SQLite，其他方案需独立 ADR 变更；Backtrader SQLite 原型不是最终 authority。此项不构成 F14 端到端验收、默认写 route 或缺失的第三 `bt_api_py` pin。Native Join、真实 MD login/subscription/matching tick、account-wide writer fence 与可靠异步回执仍是前置项。候选严格按 config，不按 set/time 自动切换。未来 production 修改同一受保护 `config.yaml` 是代码和 route contract 完成后的目标；当前 `NO_WRITE / LIVE_NO_GO`。

### 同目录 mode/preset 路由与权限合同（P0，当前阻断）

I4 SDK 是新的**离线制品已核验、真实 provider 诊断未通过**的候选：`CtpNativeStopReceipt` 仅在外层 `client.stop()` 实际正常返回后才标记 `client_stop_returned=true`；虚拟 stop 抛错或仍在执行时，即使原生 Join/Release 已完成，`complete` 也必须为 false。I4 源码固定在隔离 clean commit `809239fdc0b7982d3512f4289e3e8dbcbd43a523`，两名独立复核者批准了该精确提交；源码焦点 85 项、离线 CTP 623 项通过，1 项网络测试未运行。wheel、fresh-venv 安装来源、I4 独立 base/CTP pin 和安装后 85 项假客户端焦点均已按[离线制品证据](evidence/ctp-i4-offline-artifact-2026-09-25.md)核验；最新主仓完整 runtime 为 `1190 passed, 24 skipped`，修复了可选 SDK 缺失时的 replay 来源识别。主仓一枪式 MD 适配器把 stop 字段纳入精确回执校验，缺字段、false、unknown、Join pending 或 callback 活跃均保留账户 lease 并拒绝成功。[两次真实 SimNow 诊断](evidence/ctp-i4-md-real-diagnostic-2026-09-25.md)均因 native Join pending 而未通过；第二次固定回调分类为 `broker_id_mismatch`，无 ACK/tick、零写入。须核对字段转换及候选前置的同账户范围，并解决原生关闭；I4 仍不进入默认 registry/CLI，也不得提升为报撤单授权。

原生 `Join`/`Release` 的安全顺序在当前精确 Windows DLL 文档中未定义；[待厂商确认的问题清单](CTP原生关闭厂商确认问题.md)已准备，但尚未发送或获得答复。开发不得用并发释放 API 指针、强杀诊断进程或 fake event 代替真实 managed 会话的完整关闭验收。

当前 `RuntimeRegistry` 不允许同一个规范化运行目录出现两条 `RegisteredRuntime`。因此同一目录需要经审阅的单一 registration/dispatcher 合同：dispatcher 只依据已验证 config seal 中的 mode/preset 选取明确绑定的 route，随后还须分别验证各 route 的 code-owned authority。它不得让用户 YAML 选择 capabilities、继承另一环境 receipt，或把 sandbox readonly registration 改成多用途写入口。SimNow 与 production 的 approval/pin、account scope、风险边界和会话/凭据必须相互隔离；两个模式由同一个共享 runner 按封存的 mode/preset 选择各自的 code-owned admission 分支。不能通过复制 runtime 目录规避该限制。

### Store 与 CTP 会话订单身份交接（P0，当前阻断）

Store 的 `CtpManagedOrderDispatch` / `CtpManagedCancelDispatch` 已携带 managed intent、runtime order/cancel ID，其队列回执只能区分本地拒绝与未知排队结果。`CtpSimulationExecutionSession` 则要求审批绑定的 `client_order_id`/`CtpSimulationWriteRequest` 和经核验的原生会话回执；两套合同目前没有共同的 durable 身份映射或 approval 所有权。开发人员须先冻结唯一 active journal authority 和 typed handoff：定义 managed intent/runtime order ID 到 12 位 CTP client order ID 的持久映射、撤单 action ID、审批签发/验证责任，以及排队 `UNKNOWN` 的冻结与恢复；不得把 Store queue code 0 当作 provider ACK，也不得在两个 journal 中各自生成可冲突的 OrderRef。QA 用 fake client 覆盖首次下单、部分成交后撤单、未知回执、进程重启、重复 intent、审批失效与 identity 冲突；任一情形不得盲目重派。该合同完成前，现有 Store placeholder 必须继续拒绝真实 submit/cancel。

[ADR-41-15 Store–CTP 会话交接提案](ADR-41-15-ctp-store-session-handoff-proposal.md)把唯一 active authority、单一原生 dispatch owner、审批责任、outbox/worker crash cut 和可复测的假客户端矩阵写成候选合同。其状态是 `PROPOSED`；outbox 到 SDK worker 的完成回执与崩溃投递规则、审批签发者及受保护密钥保管未冻结，不能据此打开写入 route。

本地 QA 的 fail-closed 样例应全部用临时目录和合成账号值，不接触私有配置或 provider：

1. 用当前单目录只读 registration 加载一份 schema-valid synthetic `ctp:` 文件；`simulation/sandbox` 基线只能得到只读合同。只把 YAML 改成 `live/managed_live_direct` 后运行 validate/doctor/run/preflight，默认 inventory 应以 `managed_live_direct_profile_unavailable` 稳定拒绝；未声明 unavailable profile 的其他纯 sandbox 测试 registration 可继续返回 `preset_not_registered`。断言 credential resolver、artifact/SDK import、socket connector、runner factory 和 order/cancel dispatcher 计数都为 0，原配置字节未被改写。
2. 尝试把同一规范化目录分别注册为 SimNow sandbox 与 production live 两条 `RegisteredRuntime`；registry 构造必须因重复目录拒绝，不能挑一条继续运行。也要覆盖路径别名/大小写规范化等价的重复项；拒绝时凭据、SDK、网络、runner、写入计数为 0。
3. 验证当前 013_3 default registration 仍为 sandbox read-only；缺失 writer/receipt/pin 时不得因 config 中出现 live mode、receipt 文件或可达前置而升级权限。`runtime-production/` 与 `ctp_production:` 旧路径继续只作 legacy/deferred negative case。
4. 未来 route contract 实现后，在同一 synthetic config 路径和同一共享 runner identity 下分别验证 sealed `simulation/sandbox` 与 `live/managed_live_direct` 由 mode/preset 选择各自 code-owned admission 分支。缺失、过期或错绑的 production approval、账户/front-set/合约/制品 pin、risk/monitor capability、writer fence 或共享 runner 任一项都必须在 secret/SDK/socket/runner 前拒绝；只有完整合成 pin/approval 与 fake provider 下可验证 live composition 分支，任何 real production I/O 另走独立外部验收。此正向 synthetic case 不能替代真实账户授权。

### 本地离线合同检查

从仓库根目录运行以下焦点集；它覆盖 seal/receipt/profile 绑定、假会话拒绝与关闭、身份/交易日/连接代次稳定性、七类查询完整性、SDK 写请求计数、凭据脱敏、legacy CTP 入口门，以及默认 inventory 已登记私有 CTP sandbox 只读 binding、缺配置时返回 `CONFIG_REQUIRED` / `missing_config`（原生子进程返回码 2）：

```powershell
Set-Location D:\source_code\backtrader
C:\anaconda3\python.exe -m pytest -q -p no:asyncio `
  tests\unit\runtime\test_provider_deployment.py `
  tests\unit\runtime\test_provider_preflight.py `
  tests\unit\runtime\test_test_execution_profile.py `
  tests\unit\runtime\test_ctp_preflight.py `
  tests\unit\runtime\test_ctp_sandbox_readonly_admission.py `
  tests\unit\runtime\test_ctp_sdk_readonly.py `
  tests\unit\runtime\test_ctp_sdk_market_readonly.py `
  tests\unit\runtime\test_ctp_simnow_readonly_runtime.py `
  tests\unit\runtime\test_ctp_simnow_config_operator_route.py `
  tests\unit\runtime\test_runtime_operator_guidance.py `
  tests\unit\runtime\test_iteration41_legacy_ctp_007_010_gate.py
```

上方十一文件扩展命令在 2026-09-23 当前 Windows 工作树上由 `C:\anaconda3\python.exe` 执行，结果为 `273 passed, 1 warning in 35.07s`、exit 0；warning 是当前 pytest 未识别 `asyncio_default_fixture_loop_scope` 配置项。最终交付 revision 仍须重跑。旧版九文件焦点集当时为 `203 passed`，新增 operator route 的七组定向测试当时为 `120 passed, 3 skipped`，二者与当前范围重叠且不相加。这里只可记作 `LOCAL_CONTRACT_PASS`。该 2026-09-23 测试时点确认默认 registry 尚无私有 CTP sandbox binding（后续已登记）；正向操作入口仅用 test-only binding 和 fake secret store/SDK，不触达 CTP 网络。不得将此结果写成 SimNow 连通、真实私有查询、模拟账号报撤单或实盘验收；不得通过历史 `examples/007_ctp` 直连脚本绕过 inventory。

当前主解释器安装的 CTP 2.0.2 制品尚无新增 `CtpNativeQueryCertificateBuilder`；不能仅凭版本号判定 SDK 能力。实际部署前须将 `bt_api_base` 与 `bt_api_ctp` 的受审制品一同固定、安装到隔离解释器，并复现安装根内三组件导入与依赖校验。本地临时 venv 的导入成功只算 `LOCAL_IMPORT_ONLY`，不触发真实账号阶段。

验收地址对仍须复核 [SimNow 官方产品与服务页](https://www.simnow.com.cn/product.action)：Group 1/Group 2 与 7×24 的地址对按用户本地 `config.yaml` 明确配置；官方 7×24 名称不表示全天持续可连接，页面列出交易日 16:00 至次日 09:00、非交易日 16:00 至次日 12:00，并说明第二套不提供结算等服务、资金和持仓沿用第一套环境上一交易日的数据。因此第二套可以承担受限的连接/查询合同验证，不能单独证明结算、完整资金对账或模拟交易全链路验收；地址对可用性需用当次真实只读连接验证，连接失败直接报错。模拟账号报撤单及结算相关验收应以经账户所有者确认的第一套环境为主。

### 外部账号阶段与所需证据

CTP 快照准入仍为 `ACCOUNT_WIDE_OPEN_ORDERS_NOT_PROVEN`：`bIsLast` 只表示单次请求到达终包，七类查询全部 terminal/native certificate 也不能证明全账户覆盖或同一时点快照。真实写入前须独立核验 broker/server 覆盖 attestation、orders/trades/positions 共同 snapshot/version，以及账户级 writer fence。源码依据与负向测试要求见[CTP 6.7.7 账户快照完整性审计](evidence/ctp-account-snapshot-completeness-audit-2026-09-23.md)；当前仍 `NOT_RUN / LIVE_NO_GO`。

| 阶段 | 进入前必须具备 | 验收时必须留存的脱敏证据 | 当前判定 |
| --- | --- | --- | --- |
| CTP SimNow 只读会话 | 账户所有者审阅私有 config.yaml 中显式设置的地址对、账户、合约/交易所/HedgeFlag 与短时验收窗口；地址只来自 sealed config，registry 固定只读能力，SDK 制品独立审阅。 | 记录代码 revision、artifact、sealed candidates、选中 pair、脱敏账户指纹、交易日与 generation；保留七类 native query 的终态与摘要，不能宣称全账户共同快照；order_insert/order_action/settlement_confirm 必须为 0。原始账号、密码、token、成交明细不得进入交接文档或普通日志。 | I5 最新独立 MD-only 诊断 FAIL：未接受 login、无 ACK/tick，native Join pending/uncertain，零写入；BrokerID getter 空，但 native 来源未定。I2 full preflight 的 TD 七项 query、scope unverified 与 Join incomplete 是历史观察；I2 MD-only zero-ID strict reject 也是历史结果（I5 的 request ID 0 是有意值且回调匹配）。账户级完整性仍 UNPROVEN；离线与真实诊断细节见[I5 evidence](evidence/ctp-i5-md-diagnostic-2026-09-25.md)。 |
| SimNow 模拟账号真实报撤单 | 上一阶段通过并由账户所有者复核；新增独立的、有期限的写入 admission/approval，精确绑定代码制品、明确配置的 SimNow sandbox 账户/环境、合约、方向、数量上限、价格规则和报撤单范围；只使用确认的模拟账号。只读 receipt/profile 不能提升为执行授权。最终 gated write 必须逐笔复核私有凭据绑定、generation/TradingDay；必须先由独立 verifier 核验 broker/server attestation，证明 orders、trades、positions 全账户范围及同一 snapshot/version/coverage，并有覆盖其他主机、进程及其他用户的账户级 writer fence/freeze。`bIsLast`、七类查询均 terminal、native certificate digest 或本地 lease 单独均不足；本地 fake 状态机不足。 | 订单/撤单请求与 CTP 返回的 request/order/system IDs、ACK/reject/partial/fill/cancel terminal 状态、成交/持仓/资金变化以及 Backtrader 投影逐项对账；撤单请求 `accepted` 不等于订单已撤，UNKNOWN 必须冻结和查询恢复而不盲目重派。证明只有批准范围内的写请求、无生产 endpoint/生产账号；保存经核验的实际写入计数和脱敏关联 ID，不保存可重放审批或原始凭据。 | `NOT_RUN / SDK_READ_FIRST_ADAPTER_WRITE_DISABLED`。旧 set-scoped 状态机、CTP 原生撤单证据、SDK adapter 与稳定 managed intent ID 已有本地合同；仍缺 broker/server 账户覆盖与共同快照 attestation、账户级 writer fence、私有凭据逐笔写入门、真实跨进程/强杀的意图恢复验收、默认 CLI arm 路径及真实模拟账号报单、撤单或成交证据；同一 SDK journal 内的持久 OrderRef/runtime ID 映射已通过本地 fake 合同，但不能代替这些真实验收。 |
| CTP production live (future phase; no current operator flow) | SimNow and future production use the same registered runtime `config.yaml` path and canonical `ctp:` field shape. Production phase, when explicitly started later, changes that file to reviewed live mode/preset and replaces account/front/instrument parameters; no second `runtime-production/config.yaml` is maintained. Current production account/front values are not prefilled and are not requested. | After implementation begins, verify the implemented shared parser/schema and live-mode negative tests; implement/register the shared CTP runner's mode/preset dispatch and wire its fail-closed live admission; review exact SDK artifact/pin and deployment origin; establish separate production account/front/session identity and human approval; isolate credentials/client from strategy code; prove account-wide writer fencing, complete order/trade/position evidence, risk/freeze/reconcile/restart behavior, per-request authorization, zero-write failure cases, and independently reviewed real-session/order evidence. Until all gates pass, live config changes reject before provider I/O and status remains `NOT_RUN / LIVE_NO_GO`. |

`native_certificate_sha256`、receipt/profile digest 和本地校验通过只是绑定摘要，不自证其来源可信、账户属于授权人或 provider 已执行查询。收到每阶段外部材料后，先核验源系统、账户所有者、环境和时间窗口，再更新证据状态；缺任何一项记 `NOT_RUN`/`BLOCKED`，不能用下一阶段结果倒推补齐。

## 6. 证据记录模板

每条记录保存：源代码 revision/dirty state、解释器、平台、命令、环境变量、开始与结束时间、exit code、JUnit/日志位置、脱敏 config digest、预期和实际 counters。不得保存 secret、账户完整标识、token 或可重放 approval。对 fake-provider 用例必须显式记录 `network=0` 和 `external_write=0`。

## 7. 交付前仍未关闭的事项

- Framework fill projection 的本地 fake-provider fresh-session receipt recovery 已实现并有覆盖：SDK durable fill 后、框架投影前崩溃可在 fresh session 恰好一次重建 Backtrader order、position、commission 与 TradeLogger，且零 provider dispatch；但真实账户 cash/position 对账、强杀、gateway 与跨存储/observer 原子性仍未验证。
- 没有真实 provider/账户/CTP/SimNow、分布式原子性、强杀、平台或性能证据。
- 没有真实 cancel/fill race、replace、gateway cancel/control 验收。
- AI 只有 source baseline 与 local wheel 的 review evidence：三个 source checkout 在采集时均 dirty，wheel hash 不是 release pin；未取得部署、人工授权、账户或控制地位。
- Windows 普通跨进程目录替换已由 directory lease 覆盖：bootstrap writer 内父目录替换和同名 runtime 创建、runner 内 pathname 替换均在输出前被拒绝，且 identity-failure 路径会释放 lease。该结论不覆盖特权、内核或文件系统实现绕过，也不是 handle-relative 文件 API 的证明。
- `P1_POSIX_RUNNER_PATHNAME_DIRECTORY_REPLACEMENT_SIDE_EFFECT` 仍开放：经 `bt-runtime run` 的受管 POSIX dispatch 已以 `runtime_dir=None`、无路径 sealed effective/config/registration view、opaque registry token 和 opaque fd-backed capability 调用 14 条 source/example opt-in runner（含公开 shadow，不含 package-owned `backtest/local_backtest` fixture）；013_3 的旧 path-based evidence writer 在 private workspace 下运行。公开 direct `run_runtime(..., effective=None)` 会在读取 `config.yaml` 或检查 runtime pathname 前以 `runner_dispatch_required` 拒绝，不能重新打开路径。实际 POSIX rename/symlink filesystem regressions 在本机 Windows 上为 `NOT_RUN`；当前 portable contract/focus 不能证明完整 POSIX filesystem 副作用防护，未来 POSIX live 不得继承。该 path-free view/opaque token 是受审 runner 的接口收缩，不是 hostile in-process Python code 的隔离或沙箱。
- 外部 `bt_api_py`、execution/risk/monitor 等 capability 的本地 source-origin fence 已实现并有回归：登记 allowlist 将 `bt_api_*` 及子模块固定到非 CWD concrete path，并拒绝 CWD shadow、未登记/预加载模块、namespace/link/reparse 和子模块 meta-path fallback；但 deployment provenance 仍是 P1，non-CWD mapping、wheel/release/signature、isolation 与 hostile process TOCTOU 未验证。
- `P1_CPYTHON38_UBUNTU22_CI_ARTIFACT_NOT_EXECUTED`：CPython 3.8 只承诺无 SDK 的 core config/operator 路径。Windows 本机 CPython 3.8.20 已运行 `python scripts/ci/run_iteration41_cpython38_core_runtime.py --output <artifact.json>` 所封装的 harness，结果为 `75 passed, 3 skipped, 1 warning in 2.17s`，exit 0，且[原始 JSON](evidence/cpython38-core-runtime-local-windows.json)已保存。仍须在 `.github/workflows/test.yml` 的 Ubuntu 22.04 `iteration41-cpython38-core-runtime` job 运行并上传 GitHub CI artifact；该 harness 会拒绝错误解释器并绝不把 `--print-command` 标为 PASS。Windows 本地制品不能代替 Linux CI，故此项仍为 P1。`bt_api_py`/`bt_api_execution` 的 Python >=3.11 与 base/risk/monitor 的 >=3.9 元数据意味着 managed SDK 路径不支持 CPython 3.8，不能被此核心合同或通用 matrix 表述为兼容。

任何一个未关闭时都保持 `LIVE_NO_GO`。
