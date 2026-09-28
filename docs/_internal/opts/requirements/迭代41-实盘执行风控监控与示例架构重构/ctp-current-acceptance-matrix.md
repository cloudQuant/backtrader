# CTP 同配置当前开发与 QA 验收矩阵

## 2026-09-28 当前验收状态

当前 Iteration 41 inventory 有 17 个注册项，其中包括 007 suite 根零写 `simulation/sandbox` runtime/front-check 路由。suite 根 protected/ignored `config.yaml` 和目录 ACL 已与 013_3 对齐；离线 `doctor` exit 0（`provider_preflight_started=false`、5 pairs、`preflight_available=false`）。普通 `preflight` 仍 fail-closed，等待有界 Windows Job supervisor 和独立验收。2026-09-28 的一次显式 credential-free `check-ctp-fronts` TCP 检查 exit 0 并选中索引 3：该对 MD/TD 均为 3/3，其余索引 0/1/2/4 均为 0/3。它是本机当时的传输观察，不证明账号登录、行情订阅、结算、报单或撤单。Suite 根 `bt-runtime run` 以 `profile_dispatch_unavailable`/exit 2 拒绝，`provider_preflight_started=false`，因为该只读 registration 没有 runner。该路由没有认证 case runner、交易 runner 或写权限。

用户已取消“整条 CLI 命令必须在 0.8 秒内结束”的硬时限要求。历史 `G1_STRICT_WHOLE_COMMAND = NO_GO` 仍作为旧时限方案的审计证据保留；它不代表当前时限要求，也不构成 G1 通过。普通 `preflight` 仍关闭，直到 Windows Job 子进程终止与清理行为可验证并完成独立验收。当前 Gateway 源码与 parent SDK pins 已有提交候选，尚待独立来源与兼容性审查；候选提交不代表真实 provider 已通过。

007 的 33 个 SimNow 认证案例现有独立的 `config.yaml`、`<ID>_strategy.py` 与 `run.py` staging 目录；[本次验收记录](evidence/iteration41-007-simnow-33-case-staging-acceptance-2026-09-28.md)记载 33 个入口全部 `BLOCKED`/退出码 2、真实案例 `PASS=0`、真实 order/cancel writes 为 0。该早前检查点的完整 `tests/unit/live_certification` 为 351 passed / 1 个现存 pytest 配置 warning；同一检查点的完整 `tests/unit/runtime` 为 2,131 passed / 30 skipped / 2 xfailed。同一检查点的入口、案例封装和节点选择四文件焦点为 63 passed / 1 个现存 warning。离线 CI smoke 的 14 个可运行注册中 12 个通过，另 2 个因本机缺少 `bt_api_execution` capability 被拒绝。上述结果均不构成 TCP、真实 provider 或交易验收。策略文件仍是待接入的真实动作与证据计划，尚无 provider 执行。此项不改变 `NO_WRITE / LIVE_NO_GO`。

当前 Store 是 CTP API route-identity R2，SHA-256 `CE04ECBADDD3D3EA01C707313EA9B144650C47E322D0BDFC915000C0110094CA`。其[主树集成归档](evidence/iteration41-ac41-63-store-api-route-identity-r2-main-2026-09-28/README.md)记录 28 项 focus 通过；guarded Store 为 730 passed / 13 skipped / 18 个精确 CTP 可选 node ID deselected，Runtime 为 2,010 passed / 30 skipped / 14 个精确 CTP node ID deselected / 2 xfailed / 0 failures。首次无效 harness 结果已保留但不计入接受结果。当前 official inventory SHA-256 为 `A959A3BC6284232EA90191F13ADC71A6931F5DFCBA6DB16E7AC72B1476B9D142`，460/460 active dispositions 仍为 `REVIEW_REQUIRED / NOT_AVAILABLE`；相较 CE04 时点的 `0874A81A…`，仅四个 locator 行由 491 更新至 495，disposition 文件 SHA-256 `B55A054A8E53CEC27A7B20AD43A653CEE07082FEBE51844CCCB129C0ED365426` 未变，scanner contracts 15 项通过。条件 route-identity guard 仍有自定义 API 通过 `__getattribute__` 隐藏 CTP `exchange_kwargs` 并到达本地 fake sink 的残余，不构成 writer closure、provider authority 或写入许可。

G5 [V21 offline ActionRef ledger audit r0](evidence/iteration41-g5-v21-offline-actionref-ledger-audit-r0-2026-09-28/README.md) 是隔离的离线 projector，10 项 synthetic tests 及 independent QA 通过；它不建立 G5 authority、ledger cutover、native ActionRef floor、账户级 writer fence 或写入路由。Default CTP/SimNow writes、live dispatch 与 production admission 继续 `NO_WRITE / LIVE_NO_GO`。

此前的[干净 parent 三包候选](evidence/iteration41-g4-clean-parent-triplewheel-candidate-2026-09-28.md)完成了确定性构建与隔离安装静态检查，但该历史 `bt_api_py 0.15` 源码缺少当前受管 CTP 所需的 credential binding、execution authorization、runtime plugins、合同 DTO 与 reservation mirror 五组模块路径，请求构造器要求 0.15.5；后续隔离源码差异审计位于 `D:/temp/iteration41-g4-parent-compat-gap-analysis-20260928`，当时没有制作混合来源兼容补丁或 wheel。当前 Gateway 源码与 parent SDK pins 已有提交候选，但仍待独立来源/兼容性与真实 native/provider 验收；提交候选不构成 G4 接受，也不证明真实 provider 已通过。G6-S 的[订阅 ACK 源码审计](evidence/ctp-md-subscription-ack-correlation-source-audit-2026-09-28.md)确认原生订阅请求无调用方 request ID，当前高层回调也不保留可验证的订阅关联；行情 Feed 仍未接入。

G1 overlapped-I/O custody 的[主树归档](evidence/iteration41-g1-overlapped-io-custody-main-2026-09-28/README.md)只记录 local subgate：main guarded focus 33 passed、相邻 guarded I13/I15 suite 305 passed，independent QA 为 `GO_LOCAL_SUBGATE`。用户已取消整条 CLI 命令 0.8 秒硬时限；`G1_STRICT_WHOLE_COMMAND = NO_GO` 是旧要求下的历史结论，不代表当前时限要求或 G1 通过。普通 CTP preflight 仍关闭，直到 Windows Job 子进程终止与清理可验证并完成独立验收；该 subgate 不授权 live dispatch 或 writes。

AC41-63 的三个 007 示例 helper 均已在主树作窄范围 fail-close：`create_live_broker()`、`add_live_feeds()` 和 `run_cerebro_with_timeout()` 在检查各自输入或进入 legacy Store/Broker/Feed/Cerebro 路径前拒绝。[Broker archive](evidence/iteration41-ac41-63-007-broker-failclose-main-2026-09-28/README.md)记录 focus 5/5；[Feed archive](evidence/iteration41-ac41-63-007-live-feed-helper-failclose-main-2026-09-28/README.md)记录 focus 6/6，archive-final QA 20/20 payload、21/21 sums、18/18 links；[timeout-helper archive](evidence/iteration41-ac41-63-007-timeout-helper-failclose-main-2026-09-28/README.md)记录 guarded focus 7/7、empty guard，独立 QA 27/27 payload、28/28 sums、20/20 links。当前 007 support source SHA-256 `37536B9598E3EE2414DE2AF787EA1E15C8C52E42558E9679107DB4F3F34C273A`，timeout test SHA-256 `C5F88209C110CABB57F71003CFF9B56C0DA4D54DB43B3675ECB7414840DE5EF3`。这些只关闭具名 helper；一般 `Cerebro.run()`、generic Timer use 与 public Store/Broker/Feed constructors 仍可直接使用，不构成整体 writer closure。

013_1/013_2 的 `ctp_example_support` R4 已在主树集成八项 legacy helper fail-close。当前 source SHA-256 分别为 `560B5D60DF8BFDDDDABDCB8F6EB53468498328FA1E541B5323EBFFA4F968EBAC` 与 `675A5E3315559C90A1D7E39AC7D3E1ED2F9555E4A27F6C8A9F5DB0D8196D40A9`；新增 test `tests/unit/test_iteration41_legacy_ctp_support_inert_import.py` SHA-256 `3832B447E9606BC00D75316B0BCF29FAF87404969B9DAB520784BAE209D45069`。有效主树安全焦点为 32 passed / 1 个 private-config node deselected，独立 candidate guard 1 passed、guard empty；Ruff source 仍报告四项未改行的既有 `SIM112`。原 33-run 因读取两个未跟踪 config 而标为 `INVALID` 且不计入验收，原始 log/JUnit 不归档，不披露 private config 内容。首版 archive 因旧 candidate manifest 保留未限定的 33-pass 声明而被退回。新版[canonical R4 archive](evidence/ac41-63-013-legacy-ctp-support-r4-main-integration-2026-09-28/README.md)已通过独立终审：32/32 payload、33/33 sums、3 个本地链接、34-member ZIP CRC PASS；9 处 33-pass 声明均 `INVALID / EXCLUDED`，原始 33-run log/JUnit/config 不在归档中。README SHA-256 `71C09D95BB1C87446DBD4091A795F0D27FF06DBC4C4DB487EE195D3C9CBE9E07`，manifest SHA-256 `E7110B9D59925F553A13F2807983C193131D7C192D3C0946D1FD1CD8E21FB83D`，SHA256SUMS SHA-256 `6462C1E33946A8ABDF4BBDB5588C4A567815DFF3F3E28CC0D95E48A71CA50E83`。当前 inventory 仅四个 locator 行从 491 更新至 495，checklist `B55A054A…` 不变，verifier 460/460，scanner contracts 15 passed。以上不改变 `NO_WRITE / LIVE_NO_GO`。

## 2026-09-27 历史验收快照

Store sdk_api=None r1 与后续 CTP generic queue fail-close r4 在当时集成（历史 Store SHA-256 A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE）；mechanical fallback fail-close 已集成（source SHA-256 549276111279275BEB000D8104C4330A6D11B7C181AE66087079A555AF26D81F）。r4 的 Store/Runtime 加新增队列合同主树宽回归为 2,740 passed / 43 skipped / 2 xfailed / 0 failed。此前 r1 guarded Store/mechanical focus 为 38/38；这些结果都是本地回归证据，不构成真实 SDK/provider、账户授权或交易验收。

| 范围 | 当前裁决 | 证据边界 |
| --- | --- | --- |
| Store sdk_api=None 与 mechanical fail-close | 已集成；38/38 guarded focus | [Store r1 archive](evidence/iteration41-store-sdk-api-none-r1-main-integration-2026-09-27/README.md)；fake API 与离线测试 |
| Fake/offline main integration | 97 passed / 10 skipped | optional source-gated tests 未执行；CTP account/native-adjacent 与 deployment interop 被静态排除；不代表 live acceptance |
| Store getter proxy r0 | NO_MERGE | same-process reflection 可恢复 raw API；不是安全隔离边界 |
| G4 base/CTP pinned-wheel rebuild | CTP exact pinned wheel 未复现；G4 closed | 未进行 fresh install/native acceptance |
| G5/V21 current-source cross-package fake contract | PASS for LOCAL_FAKE_ONLY; NO_AUTHORITY / NO_WRITE / LIVE_NO_GO / NO_MERGE | [QA archive](evidence/iteration41-g5-v21-current-contract-independent-qa-2026-09-27/QA-INDEX.md)：current G5 verifier SHA 7CAED2A8… with V21 Store claim mapping gate; focus 4/4, full suite 275 passed / 2 optional SDK-import tests blocked+skipped. Missing mapping rejects before READY-to-CLAIMED and fake sender. Historical dual-ledger repro is only the old SDK allocator candidate SHA 8E7ABDD2…, not the active verifier; no trusted native floor or account-wide fence |
| I22 read-only port replacement | NO_MERGE_AS_REPLACEMENT / FAKE_PORT_ONLY | 11-node local semantic slice，未接入生产 Store；报告仍在 D:\temp |
| AC41-63 writer inventory | 2026-09-27 R2 scanner snapshot; later refreshed after CE04 R2 | At that snapshot: 363 writer + 97 dynamic / 355 files + six tombstones; 460/460 verifier; active rows REVIEW_REQUIRED / NOT_AVAILABLE. Current inventory and hash are in the 2026-09-28 section above |
| Store lazy-connect audit | NO_MERGE_PATCH / BLOCKED_BY_SHARED_I22_LIFECYCLE | [Report](evidence/ensure-api-ready-lazy-connect-audit-2026-09-27/report.md). Fake routes: get_balance(force=True), get_symbol_info(), direct/gateway/forwarding start(), example-shaped btapi/direct CTP flow; zero fake order/cancel writes. Fourteen I22-related bounded-probe test functions were statically identified in the I21 test file, not run; shared CTP deny would block typed read-only lifecycle |


Default CTP/SimNow writes, live dispatch, and production admission remain closed: NO_WRITE / LIVE_NO_GO. 下方较早的 r2b/r2c、Store R5 与 CTP 诊断段落为时间序列历史记录，不能覆盖本节当前裁决。
[Store r2b 主树集成回归](evidence/ctp-account-actor-r2b-main-integration-2026-09-27/REPORT.md)在精确补丁应用后跑完整 `tests/unit/stores tests/unit/runtime`：`258 failed / 2403 passed / 43 skipped / 2 xfailed`；撤回同一补丁后为 `2636 passed / 43 skipped / 2 xfailed`。隔离的 55 项正例不足以支持合入，r2b 已撤回且主树 Store SHA 恢复。旧 nodeid 的 258 项须逐类审查和迁移，不得通过 skip/xfail 或重开 CTP direct 写路由消除；`R2B_MAIN_MERGE_REJECTED / G6-P CLOSED / F14 CLOSED`。

[258 项独立只读失败分组](evidence/ctp-account-actor-r2b-failure-analysis-2026-09-27/README.md)指出 Iter22 的 200 项均在 CTP 构造门前截断；其余 58 项含 49 个 CTP、6 个模糊 route、3 个 unsupported provider 早拒绝。r2c 宽测分组为 249 项 external account actor unavailable、6 项 store route ambiguous、3 项 store provider unsupported；I22 的 158 个 query/evidence nodeid 仅迁移 1 个，余 157 项在构造门结束，没有执行 shared-session read-side query。013_3 零写回放仍构造 CTP Store，须改本地专用组合。该分析只解释失败，不证明后续原生调用安全；[独立主树修订 QA](evidence/ctp-account-actor-main-store-wiring-r2b-independent-qa-2026-09-27/MAIN-TREE-AMENDMENT.md)覆盖先前隔离合入建议。

[r2b route-test migration 独立复核](evidence/ctp-account-actor-r2b-route-test-migration-r2-2026-09-27/independent-qa/REPORT.md)为 `SAFE_LOCAL_TEST_MIGRATION / NO_WRITE`：隔离 fake-only 35/35，保留同步 `Store.start()/stop()` 生命周期断言；r1 已被 r2 supersede。此状态只接受测试迁移，不改变 r2b 主树 258 个旧 nodeid 失败的合入阻断，也不证明 Actor/provider 权威。

[纯 query/evidence seam r2](evidence/ctp-query-pure-seam-r2b-r2-2026-09-27/README.md)为 `PACKET_COMPLETE / LOCAL_TEST_CONTRACT_PASS / FAKE_LOCAL / OFFLINE`。19 项 focused logic pass 与三路由拒绝来自 r1 独立逻辑复核；r2 只完成自包含包装/15 项 payload 与 ZIP 校验，未重跑逻辑测试。Iteration22 原 158 个 query/evidence nodeid 仅迁移 1 个，余 157 项仍未解决；该纯接缝不是 query producer、外部 Actor 或 provider 证明。

截至本检查点，Store r2b 主树集成 258 项旧用例失败后已精确撤回；r2c 仍是隔离修复/逐例迁移工作，尚无可替代该主树回归结果的接受证据。r2b/r2c 均未合入；不得把 258 项失败归为 r2c 已完成修复，也不得把局部假测试迁移解释为 Actor 或 provider 权威。

[AC41-63 受控 writer 切片及独立复核](evidence/ac41-63-controlled-writer-slice-independent-qa-2026-09-27/reviewer/QA-REPORT.md)只覆盖 389 条静态候选中的 10 条：主树直接 Store/gateway 在假 delegate 中可达，默认 013_3 CLI preflight 在私有配置/provider 前拒绝；另 379 条未审。该结果确认了继续收敛 Store 写入口的必要性，不能视为账户隔离或全 writer closure；AC41-63 `NOT_ACCEPTED`。

[G6-S 结算 consumer r2 独立 QA](evidence/ctp-g6s-settlement-consumer-contract-independent-qa-r2-2026-09-27/REPORT.md)核验 92 项冻结 payload、39 项焦点与 34 项对抗，r1 的 bool 代次/零码反例在精确整数门下拒绝；ConfirmDate-only 仍只形成字段形状回执。注入 attestor 的属性可在两次读取间换成另一 callable，公开 receipt DTO 也可由调用方手工置 true；函数自身返回的来源可信/执行授权均为 false。模块尚未接主 runtime，无受信 provider/SDK/native 证据，仅 `FAKE_LOCAL_CONTRACT_ONLY / G6-S CLOSED / G7-S CLOSED`。

[G5 send-entry r2 独立 QA](evidence/iteration41-g5-worker-send-entry-r2-independent-qa-2026-09-27/REPORT.md)核验冻结 R1→R2 补丁、18 项候选测试、SDK 原源 57/57 对候选 53/57，并在独立 R1 副本重现 3 个红色反例。r2 移除调用方 `sender`，默认同步端口缺可信 pin/时间/代次时零 native 调用并拒绝；CANCEL 在 claim 后同库重读过期投影而拒绝，崩溃重开 UNKNOWN 不重派。但端口没有真实 SDK `Req*` 调用，故未证明真实发送直前时效；同进程代码替换私有 `_native_send_port` 仍可先执行假副作用。`COMPLETED` 只表示本地 `REJECTED` 回执持久化，G5 `NOT_ACCEPTED`。

[G6-S 结算 consumer r1 独立 QA](evidence/ctp-g6s-settlement-consumer-contract-independent-qa-2026-09-27/REPORT.md)核验冻结 24 项 payload、35 项原焦点与 21 项对抗；候选只消费注入的假 attestor 形状，未接主 readiness。负测发现代次 `True` 可与整数 `1` 相等、`False` 可被零错误码检查接纳，仍生成 `consumer_contract_satisfied=true`；回执的 `provider_source_trusted=false` 与 `execution_authorized=false` 保持正确。字段合同 r1 不完整，真实来源/SDK pin/回调和 G6-S/G7-S 均未验收。

[G6-S `.pyd` 加载边界独立 QA](evidence/ctp-g6s-pyd-loader-boundary-independent-qa-2026-09-27/QA-REPORT.md)核对 R2 的 191 项冻结 payload 和 3 项 Windows custody 测试，并用官方 CPython 3.11.5 源码确认扩展加载走 `ExtensionFileLoader(path)` → `_imp.create_dynamic` → `LoadLibraryExW(path, NULL, flags)`；保留句柄不会直接交给该加载器。假 `.pyd` 后缀文本文件的写入/替换被限制共享句柄挡住，只证明普通路径 custody，没有加载真实映像、观测 file ID 或封印依赖 DLL 链。仅 `PARTIAL_PATH_CUSTODY_ONLY / NO_G4 / NO_G6-S`。

[AC41-63 零写运行轨迹独立 QA](evidence/ac41-63-zero-write-independent-qa-2026-09-27/REPORT.md)在隔离副本复跑本地四根 K 线 fixture 与 4 项焦点，389 个静态候选只观察到 5 个调用点、0 个 writer 调用，384 项仍未执行，分布于 145 个路径组。负测证明 Python 审计钩子未计入对预先打开管道的 `os.write`，且缩窄的源码复扫发现不了从 `examples/` 清单删掉的 writer；这不是 OS 隔离或全路径闭包。候选明确 `writer_closure_established=false`，AC41-63 保持 `NOT_ACCEPTED`。

[G1 整命令截止惰性探针独立 QA](evidence/iteration41-g1-whole-command-feasibility-2026-09-27/independent-qa-2026-09-27/QA-REPORT.md)核对冻结脚本并在新 Win32 目录原样复跑两组 700 ms 试验：受控 `WaitForSingleObject(INFINITE)` 与 API 前 sleep 在 D 时均有 2 个 Job 成员，`UNKNOWN` **分类采样**分别晚 D 2.596/2.380 ms，清理后才见 Job=0。原 JSON 的 `bounded_function_return_qpc` 实为清理前分类采样，不能称函数返回；精确 Job-zero 时刻也未记录。用户态调用前 marker 不是 ETW/kernel 栈，T0 不含顶层启动，更未测 native/SCM/P14。仅 `FEASIBILITY_ONLY`，整命令硬截止及 G1/普通预检继续关闭。

[BtApiStore Actor 接线 r2a 独立 QA](evidence/ctp-account-actor-main-store-wiring-r2a-independent-qa-2026-09-27/REPORT.md)核验 679/679 冻结 payload、r2→r2a 两段补丁重放、4/18/25 项焦点；显式/嵌套 CTP 在环境、调用方对象、凭据、resolver 与 SDK 前固定拒绝，OKX raw-API 正例保留。旧 Store 30 项精确基线 `30/30`，候选仍 `9 passed / 21 failed`，逐项对应 8 个 fail-close 断言及 13 个未来外部 Actor 迁移。r2 的显式 CTP 环境读取顺序缺口已在隔离候选修正，但主仓 Store 未合入、Actor 未部署、写入未授权，G6-P/F14 不升级。

[统一离线 wheelhouse/结算探针独立 QA](evidence/unified-offline-wheelhouse-settlement-independent-qa-r1-2026-09-27/independent-qa/QA-REPORT.md)核验 150/150 冻结 payload、52/52 哈希锁定 wheel、隔离 CPython 3.11.5 无索引安装、四个根包 PEP 610 来源、13,147 条 RECORD 与 `pip check`；CTP 探针双构建字节一致，旧同版本碰撞未进入最终 lock。该检查没有加载 `_ctp`，`core-reference` 缺 `bt_api_binance` extra，结算 helper 比对回调 `ConfirmDate` 与独立查询来源 TradingDay，却未接入主 readiness。只接受 `FAKE_ONLY / NO_RELEASE` 的制品消费证据，G1–G5、结算准入及真实 SimNow/production 均不升级。

[G5 typed durable projection consumer 独立 QA](evidence/iteration41-g5-worker-projection-durable-independent-qa-2026-09-27/independent-qa-report.md)核验冻结输入/输出与补丁，复跑候选 26 项及对抗 8 项；冻结 SDK 原源 `57/57`，候选 `53/57`（3 个 schema-v5 旧预期、1 个缺 typed projection/ActionRef 的旧 CANCEL fixture）。同库行/哈希/一次性消费只证明本地字节；同步 wrapper 可先进入 sender 再返回 awaitable，事后 UNKNOWN 不能保证零发送；sender 内跨 TTL 仍可能报完成。无 native query 生产者、受信水位/时钟或兼容 V21 worker，G5 `BLOCKED / NOT_ACCEPTED`。

### AC41-63 direct MechanicalCycle / SimNowLiveRunner fail-close r1 main integration (2026-09-27)

[Canonical main integration archive](evidence/ac41-63-direct-mechanical-cycle-simnow-failclose-main-integration-2026-09-27/README.md) records only the five-file direct-dispatch fail-close slice. All five main-tree raw hashes match candidate r1. The exact three-file lane passed 52, skipped 1 optional L2 integration before child launch, and had zero failures; Ruff and py_compile passed. Supplemental broad Store/Runtime run after the MechanicalCycle and 013_1/013_2 support main patches and before Store r5: `2,641 passed / 43 skipped / 2 xfailed / 0 failed`, one existing warning, in 112.27s. This is a regression snapshot, not causal attribution to the narrow fail-close patch or CTP acceptance; raw JUnit/log/exit evidence is retained in the linked archive. Independent QA established candidate and exact-base copies both hit the same fake `UNKNOWN` assertion, with zero socket attempts. The requested positive `9 submits / 1 cancel / 0 external writes` remains unverified. This does not establish provider authority, writer closure, or a live route: `NO_WRITE / LIVE_NO_GO`.

### AC41-63 013_1/013_2 legacy CTP support import/helper r2 main integration (2026-09-27)

[Canonical archive](evidence/ac41-63-013-legacy-ctp-support-r2-main-integration-2026-09-27/README.md) records two main-tree support modules plus the persistent import test. The r2 modules match the exact candidate hashes and remove import-time dotenv loading while retaining the four legacy helper fail-close guards. Main focus passed 33/33; test-only Ruff, py_compile, and diffcheck passed. Source-wide Ruff still reports four unchanged SIM112 alias findings outside the patch. Independent fake QA also verified zero dotenv or `.env` access, SDK/native load, network, production Store/Broker construction, or write. The explicit `load_dotenv_if_available()` helper remains callable and custom broker composition remains outside the guard; official inventory dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`. `NO_WRITE / LIVE_NO_GO`.

[BtApiStore Actor 接线 r2 独立 QA](evidence/ctp-account-actor-main-store-wiring-r2-independent-qa-2026-09-27/REPORT.md)核验 649/649 冻结 payload、三文件补丁重放、`14/14` 与 `21/21` 焦点；旧 30 项在精确基线 `30/30`，r2 为 `9 passed / 21 failed`，21 项精确对应 8 个 fail-close 断言迁移、13 个未来外部 Actor 迁移。独立环境探针发现显式 CTP 构造在 actor-unavailable 拒绝前读 `BT_STORE_PROVIDER`/`BT_GATEWAY_EXCHANGE_TYPE`，环境值可改变拒绝错误；未触达 caller 对象、凭据、SDK 或 provider 网络，但违反先拒绝的字面顺序。r2 是隔离候选，按此差异阻断合入，G6-P/F14 不变。

[G1 P14/channel-close 惰性探针独立 QA](evidence/iteration41-g1-r10-p14-channel-faults-independent-qa-2026-09-27/INDEX.md)复现非法/受限 Win32 句柄返回错误 6/5、合法 Job 活跃进程 1→0 及重复关闭错误 6；两次约 100 ms 卡顿均发生在目标 API 前，`API_REACHED=false`，由外层测试 Job 清理。它不覆盖真实内核 API 挂起、生产 supervisor 故障传播或整命令硬截止，只记 `FEASIBILITY_DIAGNOSTIC_ONLY`，G1 仍关闭。

[G6-S artifact binder r2 独立 QA](evidence/ctp-g6s-artifact-first-sdk-binding-independent-qa-r2-2026-09-27/QA-REPORT.md)核验 191/191 冻结 payload，隔离复跑 52 项焦点及 5 项导入链对抗。r1 的 `ExtensionFileLoader` 替换 hook 与 `ModuleSpec`/`module_from_spec`/`PathFinder` 变异在 r2 均被提前拒绝；fake `.pyd` 路径替换也被保留句柄阻止。但 CPython 原生扩展仍按 pathname 载入，没有保留句柄映像身份、真实 SDK/native pin 或受信进程边界。仅 `PARTIAL_CUSTODY`，G4/G6-S 继续 `BLOCKED`。

[G1 R10-r1 Windows 惰性服务独立 QA](evidence/iteration41-g1-r10-r1-independent-qa-2026-09-27/independent-qa-receipt.md)从冻结二进制及精确源码重建各复跑 15/15；迟到受理不再产生票据或 worker，失败的 Job 控制复制也不发 READY。冻结二进制的 P05 票据在 D+12.878 ms 才变 UNKNOWN，调用方在 D+28.725 ms 才观察到；启动期 Job API、channel-close、P14/SCM、真实内核挂起与整命令截止仍未证明，G1/普通 `preflight` 保持关闭。

[G6-S artifact-first binder r1 独立 QA](evidence/ctp-g6s-artifact-first-sdk-binding-independent-qa-r1-2026-09-27/qa-report.md)核验 141/141 冻结文件，复跑 47 项焦点及 8 项对抗测试。保留句柄挡住 fake `.pyd` 覆写/重命名，但 gate 后同进程替换 `ExtensionFileLoader` 可令惰性 hook 执行；没有真实 SDK/native pin 或受信导入边界。只接受局部 Windows 文件 custody，G4/G6-S 仍 `BLOCKED`。

[G5 worker handoff 独立 QA](evidence/iteration41-g5-order-authority-independent-qa-2026-09-27/INDEX.md)核验冻结候选 50 项输入、91 项输出，复跑候选 21 项、冻结 SDK 57 项及 3 项对抗探针。正向撤单路径依赖测试注入的内存目标投影；冻结 Store 没有持久 target-projection producer/readback，实际路径在生成 command/handoff 前拒绝。仅接受 consumer 侧局部检查，G5 与默认 CTP 写入仍关闭。

[G5/V21 投影与 worker 预审](evidence/iteration41-g5-v21-handoff-prereview-independent-2026-09-27/independent-pre-review.md)确认目标字段可映射，但 V21 worker 不接受新 `action_identity=`，且当时的候选 Store/G5 authority 各自分配 ActionRef；默认 native query verifier 拒绝、无真实生产者。该双分配结论限定于历史候选快照：独立 current-source QA 后来确认旧 G5 SDK allocator（SHA 8E7ABDD2…）不是 active G5 verifier（SHA 7CAED2A8…）。投影 session generation 不是 OS process/Job generation，异步 sender 后还须在实际 SDK send 前复核 TTL。该预审仍是历史接口设计证据，不是 G5 通过。

[BM58 双客户端诊断独立 QA](evidence/bm58-two-client-capacity-independent-qa-2026-09-27/independent-qa-report.md)核验作者 16/16 文件与 4 项测试；默认 fake smoke 完成 20/20，两次 40/s×1s、100ms 假延迟、队列界限 1 的压力运行均完成 40/40、零丢失，但各延至约 4.7–5.0 秒且累计背压等待为 7.218/8.375 秒。该 SQLite harness 未连接 Actor/Store/CTP，30 分钟 50/s profile 未运行，AC41-58 保持 `NOT_ACCEPTED`。

[AC41-63 writer 静态候选扩扫](evidence/ac41-63-writer-inventory-2026-09-27/REPORT.md)与[独立 QA](evidence/ac41-63-writer-inventory-independent-qa-2026-09-27/README.md)以受控目录基线覆盖 349 个 Python 文件、327 个 writer 候选、62 个 dynamic 候选、0 个解析错误；389 项仍全部 `REVIEW_REQUIRED / NOT_AVAILABLE`。独立复跑 12 项测试，合成新路径被标未分类，私有路径读取陷阱为零打开。该结果只证明静态候选发现，不证明 writer closure、运行时可达性或路由授权，AC41-63 不升级。

[V23 Execution + parent R4/R3r3 双 wheel 独立 QA](evidence/coordinated-v23-r4-r3r3-wheel-probe-independent-qa-2026-09-27/independent-qa-review.md)从封存的 1,015 项 payload 与自索引重建两个唯一临时版本；各自双构建字节一致，私有 venv 安装来源、17/143 个 wheel payload 与全部 RECORD 行、PEP 610 哈希及 `pip check` 通过。四组离线焦点 `73+20+6+44` 全部通过，共 143 次执行/123 个唯一节点；`bt_api_base` 仍为源码映射，`_ctp` 未加载。只接受可复现的假客户端制品消费，不是最终统一发行版、OS native-owner 或 G1/G4/G5 验收。

[BtApiStore Actor 接线 r1 独立 QA](evidence/ctp-account-actor-main-store-wiring-r1-independent-qa-2026-09-27/independent-qa-report.md)核验 629/629 冻结文件、三文件补丁逐字节重放、新边界 `14 passed` 与含旧 managed adapter 的焦点 `21 passed`。明确 OKX `api_cls` 注入正例恢复，模糊 `btapi` 只允许无本地派发的惰性投影；route 变异、CTP/unknown/forwarding 在读取 API/凭据前拒绝。旧 30 项在精确基线 30/30、r1 仅 9/30：其余 21 项预期直连本地 CTP SDK，与现有 fail-close 政策冲突。r1 仍仅隔离候选，未合入主仓或授予外部 Actor 权威，G6-P/F14 保持关闭。

[BtApiStore Actor 接线 r0 独立 QA](evidence/ctp-account-actor-main-store-wiring-r0-2026-09-27/ctp-account-actor-main-store-wiring-r0-independent-qa-2026-09-27.md)核验候选 613/613 文件与新增焦点 `11 passed`，但同一 30 项既有 Store 测试在精确主仓基线 `30 passed`、候选仅 `2 passed / 28 failed`；其中六个无实际 API 写入的 `btapi` adapter 投影正例在构造期被错误挡住。宽测 `386 failed / 68 passed / 145 skipped` 含旧 CTP fake 合同差异，不能全归为普通非 CTP 回归。r0 不合入；后续仅可保留未知路由的惰性 adapter 投影，实际 client/legacy 派发仍须重判并拒绝。G6-P/F14 不变。

[G6-S artifact-first SDK binder r0 独立 QA](evidence/ctp-g6s-artifact-first-sdk-binding-independent-qa-2026-09-27/REPORT.md)核验 139/139 冻结 payload、36 项原测试及 9 项对抗测试。哈希扫描后、模块导入前替换可写安装树的源码，替换代码先执行，随后哈希复核才拒绝；缓存 verifier 复用时也未重查 `sys.path`/`sys.meta_path`/`sys.path_hooks`。默认 pin 缺失时拒绝且不导入 SDK，但 r0 没有受保护路径/保留句柄、真实 wheel 或客户端构造绑定，不能接入交易 gate，G4/G6-S 继续 `BLOCKED`。

[G5 OrderRef/ActionRef 同库 authority 独立 QA](evidence/iteration41-g5-orderref-actionref-independent-qa-2026-09-27.md)核验冻结输入/输出 `50/50`、`87/87`，隔离候选 14 项、SDK 27 项通过；主仓四文件在禁用不兼容的 `pytest-asyncio` 插件后为 `49 passed / 47 skipped`，作者的 `54/47` 因缺原始 selector/JUnit 尚未独立复现。八进程假测试的 ActionRef 43–50 唯一且重开可读，UNKNOWN 不可重领；当前 worker 不接受 `action_identity=`，在调用体前抛 `TypeError`、零发送。水位为调用方提供、SDK 快照未清洁钉住，G5 仍关闭。

[AccountActorPort r4 独立 QA](evidence/ctp-account-actor-port-r4-independent-review-2026-09-27.md)核验 9/9 冻结 payload、原 34 项和补测后 41 项 fake 测试，仅接受局部收据/意图绑定。新进程可重新领取同一内存 intent；非 CTP 路由构造后若共享配置变为 CTP，缓存分类仍进入 legacy 提交。主仓尚未接线，外部主体与共同账户快照仍缺，G6-P 继续阻断。[G4-r2 结算查询来源验证器独立 QA](evidence/ctp-g4r2-settlement-query-evidence-independent-review-2026-09-27.md)在隔离源码通过 48 项 fake 测试、原生导入被拦截；它只生成内存摘要，尚未被主 runtime 消费或形成可信 provider 回执，G2/G4/G6-S 不升级。

[G6-P 本地 Actor 服务核心 r1 作者候选](evidence/g6-p-account-actor-server-core-r1-2026-09-27/INDEX.md)及[独立 QA](evidence/g6-p-account-actor-server-core-r1-independent-qa-2026-09-27.md)核验 11/11 冻结文件与 50 项 fake 测试；双进程/SQLite 账本、四域快照和最终版本重核仅是本地合同。独立负测复现快照 v77 授权后发布 v78，再次调用仍返回旧 `AUTHORIZED_LOCAL_OUTBOX`；内存假 HMAC 和同权限数据库写者也可伪造本地权威。没有 provider 派发、跨主机唯一写者或 CTP 同版本快照，G6-P 继续 `BLOCKED`，r1 不可接入。

[Actor 服务核心 r6 作者冻结](evidence/g6-p-account-actor-server-core-r6-2026-09-27/INDEX.md)与[独立 QA](evidence/g6-p-account-actor-server-core-r6-independent-qa-2026-09-27.md)核验 42/42 payload、56 项测试及 7 项生命周期焦点：v77 旧授权在 v78 后撤销，v1 行迁为 REVOKED，最终本地 claim 一次消费。CLAIMED 后崩溃无可信 finish/recovery，永久冻结；同权限 SQLite 写者仍可改回 AVAILABLE 并重领同一 dispatch，fake HMAC 仍可签合成快照。没有外部身份、provider 最终派发或共同账户版本，r6 仍仅是本地 fake 修复，G6-P 保持 `BLOCKED`。

[G6-S 主 runtime 结算消费端独立 QA](evidence/ctp-g6s-main-td-settlement-independent-review-2026-09-27.md)核验 117/117 冻结文件，隔离 22 项候选测试与 7 项 QA 负例通过，失败均零结算确认/报单/撤单。候选通过注入 verifier 的自报 manifest 字符串与可仿冒的类名检查，尚未核实际安装来源、RECORD、源码及原生扩展哈希；主仓生产文件未接线，G2/G4/G6-S 仍关闭。

[Actor r4 主仓调用面静态审计](evidence/ctp-account-actor-port-r4-main-integration-qa-2026-09-27.md)确认 `BtApiStore` 尚无 actor 接线；`forwarding` 后端的 CTP 判定提前返回 false，环境 provider 改写、注入 API 属性读取、legacy submit/cancel、SDK 队列、gateway 和原始 `ReqOrder*` 回退均需在构造或派发前封闭。审计没有实例化 Store 或执行 CTP 请求，仅界定需覆盖的旁路；不能将其当成已发生的交易或主仓动态利用。

[parent R4+Execution R3r3 源码合流 QA 归档](evidence/parent-r4-r3r3-composite-qa-2026-09-27/README.md)核验 118 项证据文件；隔离 focus 分别为 parent 44、主桥接 3、五文件 73、补充撤单 20 项通过。测试夹具改动与早期 4 项路径 setup 失败保留；parent 仍声明已占用的 `0.15.5`，无唯一 wheel/pin 或受信 monitor 单写者，因此不能把撤单控制升级为发行或真实交易 PASS。

[parent R4+R3r3 第二组独立 QA](evidence/parent-r4-r3r3-composite-independent-qa-2026-09-27/README.md)再次核验四组 `44/3/73/20` 离线焦点及原始失败、guard 与测试适配差异；77 份归档 payload 和 ZIP 完整性通过。`0.15.5` 仍对应不同源码，R3r3 原始文件保留；结论仍仅限 fake 本地合同，不授予真实撤单或安装制品身份。

[V23 唯一版本安装探针独立 QA](evidence/ctp-v23-disposable-installed-wheel-independent-qa-2026-09-27.md)从 44 份冻结文件重建出两份字节相同的临时 wheel；隔离安装的焦点/全包分别为 `186 passed / 2 skipped`、`322 passed / 2 skipped`，来源与 RECORD 核验通过。原始 guard 把本机 loopback 误挡导致 12 项 setup/teardown 错误，修正后原始失败日志仍保留。仅接受本地 wheel 与假模型消费；G1/G5 和默认 CTP 写入不变。[R9 Windows 惰性服务独立重放](evidence/iteration41-g1-r9-windows-inert-custodian-independent-qa-2026-09-27.md)确认 caller 死亡后 broker 完成 pending I/O 取消及两个 Job 清空，但三项同步截止仍晚 3–4 ms；P14 未测，G1 与普通预检仍关闭。

[G6-S 结算确认假候选独立 QA](evidence/ctp-g6s-settlement-attestation-independent-review-2026-09-27/review.md)复跑冻结 `75 passed`，隔离补测 ConfirmDate-only 行形状后 `77 passed`，缺失请求来源时保持零写入。干净 G4-r2 SDK 已有请求 filter 读回参数；旧缺失结论只适用于另一份脏源码。[冻结清单路径更正](evidence/ctp-g6s-settlement-attestation-author-candidate-2026-09-27.md)确认 r1 中文矩阵路径有效、无 U+FFFD；旧哈希只是矩阵后续编辑前的内容记录。SDK 来源封印、真实回调及主 runtime 准入尚未验，G6-S/G7-S 继续关闭。

**2026-09-27 独立负测补记：** [parent 撤单控制端 r3 独立 QA](evidence/ctp-parent-cancel-control-r3-independent-review-2026-09-27.md)核验冻结 payload/evidence `154/154`、`112/112`，独立副本 `15 passed`，但有 monitor DB 写权限的另一进程可在精确读回后、最终清锁前删除事件；首次 release 与 RELEASED replay 仍返回成功，两个风险锁被清除。[r4 离线桥接复核](evidence/ctp-parent-cancel-control-r4-independent-review-2026-09-27.md)在三原节点与五文件焦点分别 `3/3`、`73/73` 通过，普通 SQLite DELETE 被挡，但同用户可删除 trigger 后删行；CTP UNKNOWN 冻结仍不可解除。G1 双阶段 [r3](evidence/ctp-g1-two-stage-r3-independent-review-2026-09-27.md) 的 `83+4+1` 项 fake 检查修正了 exit-2 错误分类；[r4](evidence/ctp-g1-two-stage-r4-independent-review-2026-09-27.md) 独立核验 bootstrap 静态大小与摘要门。真实 Windows R7 和 teardown-r2 各重放 9 个 inert 场景，同步准入仍超过 1800 ms 截止，overlapped 取消无持久 I/O reaper，G1 继续关闭。[SimNow 与 production 最短关键路径独立审阅](evidence/ctp-simnow-production-shortest-path-independent-review-2026-09-27.md)整理了仍需外部主体证明的门槛。上述检查不含 provider 或真实账号。

[G4 typed lifecycle receipt r1 独立审查](evidence/ctp-native-lifecycle-receipt-r1-independent-rejection-2026-09-27.md)在作者三文件 `65 passed` 后发现 Trader receipt 的原生 API generation、epoch、source ID 与同一 API/SPI 当前代次不一致，fake 终态仍报 `clean=True`；r1 拒绝。[r2 独立源码 QA](evidence/ctp-native-lifecycle-receipt-r2-independent-review-2026-09-27.md)三文件 `66 passed`，blocked-Init exact-object 与异常负例验证同代次标签。此候选源不同于 e75 wheel，不提供受监督的真实 native close，G4 继续 `BLOCKED`。

[G4 r2 唯一探针 wheel 独立复核](evidence/ctp-g4-r2-disposable-wheel-independent-review-2026-09-27.md)确认干净 29f8 基线加两项冻结覆盖、两次隔离构建 wheel 字节相同、RECORD/无系统包安装来源正确，安装后 66 项 fake 测试通过。`_ctp` 导入被刻意拦截，真实 DLL 未加载；中间 OBJ 不同、诊断 `cl /Bv` 退出 2 与两类测试警告均保留。仅接受探针制品/离线消费，原生 Join/Release、监督链和默认 SDK pin 仍未通过。

[V23 G1 native-owner 进程绑定源码候选](evidence/ctp-execution-v23-g1-native-owner-process-binding-author-candidate-2026-09-27.md)及[独立 QA](evidence/ctp-execution-v23-g1-owner-binding-independent-review-2026-09-27.md)核验 44/44 冻结 payload、`20 passed` 焦点与 `322 passed / 2 skipped` 全包。旧无进程绑定的 CLAIMED 行迁至 UNKNOWN/POISONED；未配 native-owner adapter 的 READY 行也持久冻结且不触发通用 sender。测试只用假 attestor，未证明 OS 进程/Job 所有权；发行 metadata 仍为与旧包冲突的 `bt_api_execution 0.2.0`。[版本与 pin 迁移映射](evidence/ctp-v23-composite-version-pin-migration-map-2026-09-27.md)仍是只读清单，未形成最终合流 wheel。G5、安装发布及真实 CTP 写入继续关闭。

[G1 R8 独立 Windows 惰性重放](evidence/ctp-g1-r8-independent-review-2026-09-27.md)核验冻结 10/10 payload，并复跑 13/13 个候选预期断言。同步 2 MiB admission 的决定分别在 D=1200 ms 后的 1218 ms（冻结）和 1234 ms（独立）才出现；overlapped reaper 仍属于 caller PID，caller 死亡时 pending I/O 未验。整命令启动及 Job handle 转移在 request D 外，G1 与普通 native `preflight` 保持关闭。

[G1 R9 预启动服务拓扑](evidence/g1-r9-design-index-2026-09-27.md)已归档为只读设计：caller 只提交有界 ticket，独立 I/O broker 与常驻 reaper 分别持有 OVERLAPPED 和 Job/进程句柄，Job1 empty 后才允许 Job2，全部使用同一截止。若唯一 reaper 卡在终止、查询或关闭调用，仍无 Job-empty 证明；此设计未部署、未运行完整 Windows 负测，不改变 G1 关闭裁决。

[G1 R10 异步票据作者探针](evidence/iteration41-g1-r10-async-ticket-author-2026-09-27/AUTHOR_R10_EVIDENCE.md)在惰性测试中票据提交约 0.1 µs，但不可逆 UNKNOWN 在 D+3 ms 才观察到，故不能满足整命令硬截止。[R11 只读边界审计](evidence/iteration41-g1-r11-design-only-author-2026-09-27/R11_G1_HARD_DEADLINE_AUDIT.md)把外层启动、回执、I/O completion 与每个 Job-empty 均纳入同一 D，指出一般 Windows 用户态无法保证最外层 watchdog 按时获调度或同步调用返回；请求级已就绪服务口径是另一个需明确批准的需求变更，尚未采用。G1/普通预检维持关闭。

[R9 原生边界补件与 R10 独立 QA 索引](evidence/iteration41-g1-r9-r10-independent-evidence-index-2026-09-27.md)核验作者输入与隔离重建；R9 先前重放应描述为源码等价 EXE 而非字节相同 EXE。R10 23/23 冻结输入、9/9 惰性重放通过，但 QA-only 延迟提交在 D+65 ms 仍返回 `ACCEPTED`，D+81 ms 才变 `UNKNOWN`；broker 取消后还存在 `WaitForSingleObject(writer, INFINITE)` 路径。P14、真正 CreateProcessW 挂起及整命令服务启动均未证明，G1 保持关闭。

[G6-P 外部账户 actor 调用图审计](evidence/ctp-g6p-account-actor-architecture-audit-2026-09-27.md)以冻结源码列出 Store legacy submit/cancel 回退、旧 gateway 默认同进程 CTP runtime、SDK direct Req 三类旁路；新 gateway/ZMQ 只有本地路由/静态 peer ACL，没有跨主机 epoch 或共同账户快照。严格 F14 与 production 因此仍 `BLOCKED / LIVE_NO_GO`，该只读审计不构成服务实现或部署验收。

[AccountActorPort r2 独立负测](evidence/ctp-account-actor-port-r2-independent-rejection-2026-09-27.md)在 9/9 冻结 payload、15 项 fake 正例后拒绝接入：未知 provider 可在候选 harness 中回退本地客户端，嵌套 CTP 路由漏判，注入对象在拒绝前被读取；其收据只核 command ID，不能拒绝旧 epoch、错账户和重复 intent。主仓 Store 的 legacy 路由仅经静态审阅，未执行真实报撤单。G6-P 外部主体和共同账户快照仍缺，严格 F14 与 production 保持关闭。

[AccountActorPort r3-r1 独立 QA](evidence/ctp-account-actor-port-r3-r1-independent-review-2026-09-27.md)在 9/9 冻结文件及 24 项 fake 测试下修正未知 provider、原始 API 注入及两层嵌套 CTP 路由分类，拒绝前不再读取注入对象属性；只接受隔离 classifier/harness 合同。收据仍只核 command ID，旧 epoch、错账户和重放仍可进入假端口；主仓尚未接入此门，G6-P 不变。

[G6-P 外部 actor 独立威胁模型与验收路径](evidence/ctp-g6p-account-actor-independent-review-2026-09-27.md)核验 r2 候选与主仓调用面，要求服务端唯一凭据/网络出口、跨主机单调 epoch 与撤销、同一权威版本的资金/全账户委托/成交/持仓快照、服务内最终派发。公开 CTP 的独立查询终包无法提供共同版本；这份只读设计与 15 项 fake 检查均不构成部署证据，G6-P 保持阻断。

**2026-09-27 最新局部证据，裁决不变：** [R3r3+V21 合流源码独立 QA](evidence/ctp-r3r3-v21-composite-source-independent-review-2026-09-27.md)为 `290 passed / 2 SDK-import skipped`，仍未解决 CLAIMED 后进程崩溃的 G5 证明。[parent 撤单控制端 r2](evidence/ctp-parent-cancel-control-r2-independent-review-2026-09-27.md)独立 `23 passed`，后续首次释放回调/读回审计发现缺口，主桥接原有三项正例尚未复跑通过。[G1 双阶段 handler r1](evidence/ctp-g1-two-stage-handler-r1-independent-review-2026-09-27.md)仅 fake 编排通过，[r5 同步创建反例](evidence/ctp-g1-r5-prestarted-host-feasibility-rejection-2026-09-27.md)及[r6 同步入列反例](evidence/ctp-g1-r6-warmed-worker-custodian-rejection-2026-09-27.md)否定整命令 hard deadline。[G6-P/G8-P 实盘路径审计及合成已验签负测](evidence/ctp-g6p-g8p-production-path-audit-2026-09-27.md)保持零 dispatch，外部账户 actor 仍缺。因此普通 `preflight`、SimNow 写入与 production live 均保持关闭。

[主仓 runtime 测试模块隔离修复及全量复跑](evidence/ctp-runtime-yaml-test-isolation-2026-09-27.md)由 root 验证 `1957 passed / 30 skipped / 2 xfailed`，一项既有 pytest 配置警告；该结果只覆盖当前主树的离线单元测试，不替代上述各门证据。

**最新阻断：** [V20 r2 单账户绑定](evidence/ctp-execution-v20-r2-account-binding-independent-review-2026-09-27.md)仅局部独立通过，永久 owner 尚不能安全 clean-close 交接。[Execution R3r2 撤单 claim](evidence/ctp-execution-r3r2-cancel-claim-independent-review-2026-09-27.md)独立接受精确回执和整数 0 的 fail-closed 行为；主桥接 offline 撤单必须先取得 risk dispatch claim，ACKED 后的风险 latch 只能用专用可信终态证明解除。G1 output-channel [r3 伪造 Job-empty 反例](evidence/ctp-g1-output-channel-r3-independent-rejection-2026-09-27.md)由 [r4 本地 helper](evidence/ctp-g1-output-channel-r4-independent-review-2026-09-27.md)限定修复，[r6 post-resume](evidence/ctp-g1-output-channel-r6-post-resume-independent-review-2026-09-27.md)独立 56 项通过；完整双 Job 服务监督链仍待验收。真实交易门均未通过。

**当前增量裁决：** [V20 r0 结构反例和安全重启审计](evidence/ctp-v20-schema-counterexample-and-clean-handoff-audit-2026-09-26.md)已归档，Execution r1 仍被拒绝；r2 独立接受单账户实例绑定。[主仓共享工厂 r1](evidence/ctp-v20-shared-account-runtime-r1-independent-review-2026-09-27.md)独立 84 passed / 2 expected xfailed，只接受未注册 source bundle。[Guardian 编排前切片](evidence/ctp-g1-guardian-preorchestration-independent-review-2026-09-26.md)独立 41 项服务测试与 1 项 parent gate 通过；整命令监督、Session0 token 转换与受保护部署未通过。[G6 r4a](evidence/ctp-claimed-authority-r4a-expiry-independent-review-2026-09-27.md)独立 100 项接受离线有界时差修复，不构成真实写入许可。所有真实交易门保持原状态。

**状态快照：2026-09-27。** 本页把现行 CTP 配置、只读会话与 F14 写入门整理成可执行的开发/QA 顺序。[迭代计划](迭代计划.md)定义准入与政策，本矩阵记录逐门操作状态，[正式验收文档](验收文档.md)列出测试标准；证据更新后须同步这三处，冲突时不得自行将任一状态升级为 PASS。

本次并行实施的本地测试和阻断项另见[2026-09-26 检查点](evidence/iteration41-parallel-checkpoint-2026-09-26.md)；其中标为待复跑、待 hosted CI 或待真实账号的项目不得计入本矩阵的 PASS。

**后续源码切片：** [G6 v2 字段绑定与 READY 延后重试](evidence/ctp-g6-v2-bound-fields-defer-independent-review-2026-09-26.md)独立通过 75 项，八个具有有效签名但不匹配 sealed config 的请求/session 均在真实 V18 Store claim 前拒绝；最后原生调用时的许可时效、撤销及外部 fence 尚在后续开发。V19 r0 的账户 UNKNOWN 撤单 gate 已在 live-bridge 接管用例通过，但独立 QA 随后复现正常释放后租约编号复用的 ABA；r1 修复待独立验收。共享候选的[唯一历史账本路径切换合同](evidence/ctp-v19-account-ledger-cutover-design-2026-09-26.md)已明确，尚不提供自动历史迁移或真实写入。下面各历史制品和测试数字仅适用于其记录的源码时点。

当前裁决为 `LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`。离线合同、TCP 可达、受监督进程 containment、一个查询流的终包或本地 outbox 回执，都不能单独记作真实 CTP 会话、F14、SimNow 写入或 production PASS。F14 继续执行严格门槛。ADR-41-16 的 SimNow 操作性声明例外仍为 `PROPOSED`、未批准、未实施、未登记；不得按豁免处理。

[V19 r1 独立 Store 核心复验](evidence/ctp-execution-v19-r1-independent-review-2026-09-26.md)随后接受了上述租约 ABA 的限定修复，包含真实 close/reopen 及旧租约 mutation/release 拒绝；固定账本工厂和 clean-close owner handoff 不在该验收内。主仓扩大桥接回归为 63 passed / 4 failed，正在处理；[G1 anchor/Guardian 后续审查](evidence/ctp-g1-anchor-r5-guardian-r1-r2-independent-review-2026-09-26.md)也未关闭部署门。

**目标操作合同：** SimNow 写入验收后，生产账号沿用同一个受保护 `config.yaml`、同一个 `ctp:` 字段结构和同一个受管 CTP 执行 runner。操作者先结束旧 session，再编辑该文件的 `runtime.mode/preset`、账号认证、MD/TD 候选及合约范围，并以同一 runtime identity 和 runner 实现重新启动新 session；活动 session 不热切换。后端不因 set 名称或时间另选环境，也不要求创建生产专用 runner 或第二份配置。QA 须用同一 runner identity 与同一路径证明 stop/edit/restart 后两模式分别解析、封存和准入；旧 SimNow 审批、会话及账本范围不得跨账号/模式复用。当前默认 runner/write admission 尚未实现，此段是验收目标，不是已可下单的说明。

共享 runner 的具体代码接缝、实施顺序与两模式 QA 用例见[CTP 同配置共享 runner 开发与验收合同](CTP同配置共享Runner开发与验收.md)。

## 当前边界

| 能力 | 当前可证明的状态 | QA 记录标签 |
| --- | --- | --- |
| 单一配置与模式解析 | SimNow 与未来 production 共用 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 及 canonical `ctp:` 字段。共享 parser 和 fail-closed 负测有离线合同；共享 CTP runner 的 live-mode dispatch/admission 尚不存在。 | `LOCAL_CONTRACT_ONLY` |
| 通用 profile dispatch / CTP managed selector | 通用 dispatch 只接受无 secrets、网络、外部写、managed capability 和审批的 replay/backtest；独立审核及 synthetic CLI run 已通过。新非授权 mode scope 可从同一 canonical `ctp:` 路径将 synthetic simulation/live 两 profile 绑定到同一 runner identity，但不授予 session。合成 SimNow `receipt_required` profile 可在显式 fake 依赖下进入 session，逐动作重封 config；默认 013_3 sandbox 的 `deny`/no runner 与 live unavailable 仍拒绝。最后检查到 native 调用的并发 config mutation 是 P2 上线门。 | `LOCAL_FAKE_ONLY / NO_WRITE` |
| 配置前置选择 | 单对按配置原样使用；多对只在 sealed `ctp.front_pairs` 的 1–8 组成对候选内做有界、无凭据 TCP 探测。MD 与 TD 各须达到重复采样的严格多数（当前三次采样为各至少 2/3）才参与比较，分数为两端成功样本中位延迟的较大值；最低分胜出，平分按配置顺序。诊断入口复核分数和最快候选。无可达整对则拒绝。不得发现配置外地址，也不得按 set、时钟、日历、TradingDay 或服务时段切换。 | `TRANSPORT_ONLY` |
| 最近记录的前置观察 | [2026-09-25 前置复查](evidence/ctp-configured-front-check-2026-09-25.md)：15:55 UTC 的五组显式候选中，零基索引 3 双端各 3/3，按两端各至少 2/3 的新传输门槛被选中；其余四组均 0/3。15:40 UTC 旧门槛的无 pair 结果保留为历史证据。传输结果须运行前重新检查，不能据此宣称账号就绪。 | `TRANSPORT_ONLY / PAIR_3` |
| SimNow TD/MD 会话 | I11 MD-only 身份未验证、matching tick/TradingDay 未确认、Join pending；I12 TD-only 在 SDK artifact 阶段拒绝，未观察 login，queries 未验证，close 未尝试。两次 one-shot marker 都已消耗且不可重试；I14 同配置 TD→MD 方案仍是待实现设计。 | `NOT_ACCEPTED` |
| Native close | `Join` pending 曾在真实受监督观察中出现；供应商对精确 Windows 6.7.7 的退出/回调静止合同未确认。进程退出、Job empty、Python `stop()` 返回都不证明 native `Join`/`Release` 完成。 | `BLOCKED` |
| F14 写入账本、writer fence 与 outbox | 有非授权的离线合同和 fake 候选；`2.0.4+iteration41.i9` CTP 队列租约 wheel 满足总工程版本范围、双构建一致，隔离安装后 10 项队列 fake 和 2 项真实 `TraderClient` + fake API 桥接通过，但未进入默认 pin。默认 CTP Store 仍绑定 fail-closed placeholder。唯一 active authority/cutover、可信回调来源、跨用户/主机账户 fence、共同账户快照、真实逐动作审批与 provider ACK 尚未验收。 | `BLOCKED / NO_WRITE` |
| Production | 目标是未来在同一受保护配置中结束旧 session 后改 mode/preset 和账户、前置、合约字段，再以同一 runtime identity/受管 CTP runner 实现重启新 session；不支持活动 session 热切换，不维护第二份 production config 或 production 专用 runner。当前没有注册共享写入 runner，配置变化和重启本身都不会授权网络、下单或撤单。 | `NOT_RUN / LIVE_NO_GO` |

[Native Join/Release fail-closed 源码候选](evidence/ctp-native-join-fail-closed-source-candidate-2026-09-26.md)的 MD/TD 纯 fake 测试各经独立复核，总计 31 项通过：并发 observer 只允许一次 Join，Release 异常后保留退休对象与 pending 栅栏，重复调用不再次 Release。隔离 CTP 子模块另把 Feed Ref guard 与 Join 完整祖先链无冲突合成，受影响 fake 测试 255 项通过；父 SDK Gitlink 和默认 pin 未指向此合成源码。候选尚未构建或经真实前置观察；供应商生命周期语义与有序 native close 仍未证实，G4 继续 `BLOCKED`。

[G4 假阻塞 Job containment 独立复核](evidence/ctp-g4-fake-stop-job-containment-independent-review-2026-09-27.md)证明在本机假 `RegisterSpi(None)`/`Release()` 阻塞子进程里，外层 Windows Job 可终止并观察 Job 清空；这不是 clean native close。当前 SDK 的 `stop_and_wait(timeout)` 在开始计时 Join 前同步进入这些关闭调用，不能单靠它约束整次关闭。更宽的 SDK 焦点保留一项并发 cleanup 断言失败；没有真实 mapped DLL、同代次原生 Join/Release 或已接线服务回执，G4 仍 `BLOCKED`。

[G4 fake cleanup 测试同步修复](evidence/ctp-g4-cleanup-test-sync-independent-review-2026-09-27.md)随后用假 API 完成事件等待关闭旧并发测试竞态，root 独立复跑 56 项通过。该修复仅修改隔离测试，未修改 e75 生产 SDK；早先失败日志仍归档，G4 原生正面证据仍缺。

**新增离线实现边界（2026-09-26）：** `ctp_shared_managed_runner.py` 为两种模式实现同一路径的非授权准备层，复验两个 profile 的同一 runner identity、模式专属配置/审批摘要和精确所选 pair；对象完整性与从当前文件重封的 freshness 分开检查，后者仍有最终检查至原生调用的竞态。`ctp_shared_managed_runtime.py` 在同一入口按配置模式分派：合成 SimNow 可以注入 fake opener；live 因缺真实生产 session/账本 authority 在探测和读取凭据前拒绝。共享公开 context 不绑定密码/AuthCode 的私密轮换，真实动作必须由底层逐动作凭据绑定校验。

`ctp_f14_external_admission.py` 只定义外部账户写者栅栏与共同快照的逐动作接口，没有受信 authority 或调用接线；`ctp_simnow_operational_window.py` 只定义未获批准的 G6-S 有界窗口、逐动作许可与单流查询观察，固定不声明账户级排他、共同快照或写授权。`backtrader/stores/ctp_managed_projection_bridge.py` 只定义单一 outbox 投影桥，当前 SimNow session 缺匹配端口并在构造时拒绝。Store 的 `_sdk_order_request()` 与独立执行库的 reservation 仍有两个 `OrderRef` 来源，尚无共同事务/可信 reservation port；managed submit/cancel 因此在二次分配和派发前硬拒绝。Store managed 队列已经能在 worker 可见前落同一 typed receipt；但没有可信 caller 接入，v1 bridge 仍先 dispatch 后记 receipt，不能解除 hard reject。

Windows `ctp_config_action_linearization.py` 仍是未集成的本机诊断候选，现把公开名称改为 `ConfigPathReadLease` / `acquire_config_path_read_lease`，避免误称动作线性化。常规写/替换/重命名及非固定驱动器/硬链接的定向负测通过；另一个 `FILE_WRITE_ATTRIBUTES` 句柄在 fake native-action 窗口成功给被租约持有的配置文件设置自定义 reparse tag，证明单靠该共享租约不足以线性化最后重封与原生调用。新增 Python fake race 负测在两种动作的最后重封返回后改写合成配置，确认当前 submit/cancel 仍能进入 native adapter；预期结果为 `2 xfailed`，只记录当前 TOCTOU，不声称跨平台文件系统行为或通过验收，详见[配置动作租约及 Python dispatch 负测](evidence/ctp-config-action-lease-negative-2026-09-26.md)。未来须由受信执行边界同时控制配置/路径变更和唯一原生动作；目前只有类型合同，没有 broker 或 route。以上均不改变默认 `NO_WRITE / LIVE_NO_GO`。本轮主仓 runtime 回归 `1804 passed, 27 skipped, 1 existing warning`，Store 广域回归 `667 passed`，相关 Broker/集成 `23 passed`；SimNow 有界许可/strict F14 合同 `74 passed`，共享入口/配置候选 `26 passed, 1 skipped`。这些均属离线检查，不替代真实 provider 或写入验收。

[独立执行库单 worker 候选证据](evidence/ctp-execution-single-worker-candidate-2026-09-25.md)的后续 source-only commit 为 `b676fe6`：同一 SQLite 行的 queue receipt→claim→一次 sender 合同有 fake 测试；任何 claim 后裸 `REJECTED` 均转为 `UNKNOWN`，不相信 sender 自称无发送。它没有解决跨包 `OrderRef` 双来源，也没有 wheel 或真实发送，不能单独关闭 G5/G6。

Store/outbox 接口复核：新 `CtpManagedDispatchBinding` 已把稳定 `command_id`、OrderRef、审批使用、会话代次、RequestID/ActionRef、精确撤单目标和本地 receipt ID 定为完整 typed DTO；`BtApiStore` 的 managed queue 能在 worker 可见前持久化回执，并拒绝缺失 dispatcher 的旧通用发送。它仍未与独立执行库 SQLite 同一分配器、claim→native send→receipt/UNKNOWN worker 接通；现有 v1 adapter 仍先调用 `sdk_dispatch` 再记 queue receipt，因此受管下单/撤单硬拒绝不得解除。开发须先建立唯一持久派单权威、改用 v2 handoff 并淘汰 v1 顺序，再把 Store/Broker 投影接入；不得在现有队列外另写一份 outbox 记录充当“恢复证明”。

三 wheel [I9 artifact-set 离线候选](evidence/ctp-i9-execution-artifact-set-2026-09-26.md)在无 system-site 的隔离 venv 校验了 base、CTP I9、execution 0.2.0 的本地 wheel 与安装来源；其 Join 修改仍只是另一个源码候选，没有进入该 wheel。I13/I15 父级信任根仍缺独立 source pin/manifest 与外部 review receipt，现有预检显式拒绝 unset pin；不得以本地自签 pin 替代。

后续隔离的 `bt_api_ctp-2.0.4+iteration41.i9.join1` 把 I9 与 Join/Feed Ref 源码合成，Windows CPython 3.11 两个独立根构建为相同 wheel SHA-256 `8d2d845501f43939704c9e6c61610ec1747d613a4e07485245bbb006c8242fbe`。离线 fake 焦点 `254 passed, 1 deselected`；新建无 system-site 的三轮子环境核对 base/CTP/execution 来源和全部依赖 RECORD，补齐已缓存依赖闭包后 `pip check` 通过，未加载 `_ctp`。**此 wheel 与 G5 query-target 源码候选不兼容**：缺 `bt_api_ctp.order_action` 的 `CtpOrderActionEvidence`/回调历史，以及 `_QuerySource.request_filters`；不能用它运行该观察或接通撤单。I13 相关 API 仍只在另一候选源码中，统一来源、受信 pin、真实 native close 和默认路由都没有通过。

I13 ancestry 与 join1 的只读三路合并在 `client.py` 有 14 处原生生命周期/回调来源冲突；`get_order_action_evidence` 需要这些回调历史，不能只复制 DTO。后续在隔离源码候选中已人工合成 Join、managed cancel 和 query getter 回读并通过 fake 焦点；certificate/login observation、bounded stop、credential scope 和队列生命周期接口仍在逐片合成与独立审查。没有统一 wheel/pin，也未解除实际调用门；[本轮检查点](evidence/iteration41-parallel-checkpoint-2026-09-26.md)保留精确来源与测试范围。

[I13 MD 值脱敏源码候选](evidence/ctp-i13-md-value-free-source-review-2026-09-26.md)的 14 条目在独立 Windows clean checkout 与 Git blob 字节核验一致；它是范围有限的 SDK 源码审阅清单，不是父启动器需要的完整运行时 manifest，且无候选 `_ctp.pyd`、wheel、源码 pin 或真实诊断。不能用历史另一份扩展的 fake 测试替它报告通过，更不能据此推断真实账号错误或登录就绪。

**Windows inert guardian 增量（2026-09-26）：** 当前未登记的 `request_inert_guardian` 向预启动 AF_PIPE 服务发送固定 sleep probe，descriptor 绑定源码、解释器和固定回执目录；它不是普通 CTP preflight 启动器。历史五模块 `77 passed` 已由七模块外层 supervisor 的 `84 passed` 检查点补充：owner 死亡后独立 supervisor 按同一 monotonic deadline 请求终止 Job，观察 service/child 退出，但回执可能晚于 deadline。最新 pipe 服务加入 protected 当前用户 DACL 与 handle 回读、远程客户端拒绝、两实例上限、HMAC 和请求消息各自 SID 检查，最终 service 文件作者与根代理独立复跑均 `11 passed`。完整 launcher/setup 仍未置于受监督 Job，descriptor 外部信任、回执目录 ACL/完整发布、全命令硬截止、native close 和普通 preflight 接线仍未验收；G1/G4 不通过。详见[本轮检查点](evidence/iteration41-parallel-checkpoint-2026-09-26.md)。

[G1 服务端截止假负例](evidence/ctp-g1-service-deadline-fake-counterexample-2026-09-27.md)进一步复现：worker Job 已空后同步 `create_receipt` 可超过请求 deadline 和外部 250 ms 等待仍阻塞 handler，放行后返回 `observed`；未写迟到响应。root 用源副本独立复跑。该 fake seam 不证明真实 SCM 进程行为，但足以拒绝当前整命令硬截止声明；独立 host supervisor、两阶段 Job 和真实部署仍待实现。

**新增离线审查边界（2026-09-25）：** I13 MD-only 与 I15 TD-only 候选的受监督子进程已增加 `-I -S -B`、固定虚拟环境安装根和从已校验源码直接编译的导入方式；这些改动只处理子进程。当前调用它们的父进程会在源码核验前普通导入 runtime 模块，可能先执行同版本有效缓存。未登记的 stdlib-only sealed-import 离线切片现在将 Windows file-ID lease 接入 manifest seal 与 source loader；loader 编译经句柄身份和 hash 核验的同一份 bytes，且 checked import 拒绝伪造合法 spec 但未执行的缓存模块。9 项 fake 测试通过；外部 launcher、完整依赖闭包和来源 pin 未完成，因此真实一次性诊断仍列为 P1 阻断。两候选的源码 pin 均未启用，真实 marker、凭据和 provider 未使用；须完成完整父信任根与独立复核。执行侧另有隔离的 OrderRef 持久水位、源回调队列租约与桥接候选；它们不解决 F14 的账户级 writer fence、共同快照、正式三制品 pin 或真实逐动作审批，不能上升为报撤单准入。

日常允许的离线入口是 `bt-runtime doctor --strategy-dir examples/013_3_sa_midfreq_simnow/runtime-ctp-private`。013_3 的 doctor 以兼容性追加的 `operator_actions` 列出离线检查、TCP-only 前置检查、禁用的原生预检、不可用的 run/live；同一文件改为 live 时明确标为配置请求且 `authorization: not_granted`，旧 `next_actions` 保持兼容。`bt-runtime check-ctp-fronts --strategy-dir ...` 只提供配置候选的传输证据；它校验配置文件，但不调用凭据 resolver、不导入 CTP SDK、不登录。普通 `bt-runtime preflight --strategy-dir ...` 当前 fail-closed/不可作为 provider 命令；须先实现并独立验收覆盖父级探测、setup、child、native close 和清理的有界 Windows Job supervisor。I11/I12 监督尝试不解锁该 CLI。

[G5 I9 OrderRef/Store/SDK 离线复核](evidence/ctp-i9-orderref-bridge-audit-2026-09-26.md)将只读 reservation 镜像、当前架构 CTP Feed 源码候选与 Store 的精确类型/同 Store 检查分开记录。Store 负测、8 元组 guard 与真实 I9 源码的 fake stage/queue smoke 共 4 项通过；当前 pinned parent 的无会话旧入口经真实 DirectBackend→Feed 拼接，在 capability 门前拒绝且原生计数为零。子模块 `0609b05` 的 12 位 Ref 必填与原样透传经离线复核；隔离父仓 `7fe53a0` 仅更新 Gitlink，但没有受信 wheel 或默认 pin。独立审计确认 managed fake transport 仍可不用 I9 mirror 接受合法 Ref，普通 Python import 也会优先加载 site-packages CTP；源码路径测试不能代替安装来源验证。隔离 SDK `decd7600` 已在源码中让 managed 请求与镜像字段精确匹配，相关 fake 合同 403 passed、2 skipped；该提交的镜像来源可通过类名/模块名伪造；隔离后续 `5744d3c` 已改用 exact I9 0.2.0 类对象并通过 29 项独立负测，但版本元数据和导入文件尚无受信 wheel/RECORD/origin 证明。已安装受信 I9 wheel 的同一 worker、唯一 OrderRef 权威、forwarding/wire 身份传递、原生请求绑定及取消目标来源仍无完整证明，G5 为 `NOT_PASSED`。

转发层的历史 P1 负测依次发现空白 CTP venue 可绕客户端、`UNKNOWN___FUTURE` 等可跨 venue 送入 CTP adapter，以及直接构造 `OrderRouter` 时无 scope 仍放行。隔离源码 `c33ce478`、`e6cd73b`、`2fec245` 分别修补客户端、ZMQ 服务端和直接 Router/嵌入式入口；最新 exact-commit 独立 fake 复核 132 项通过，规范声明为 CTP 的 adapter 在三类命令、别名、直接 wire、跨账号和无 scope 情形下均为零 adapter 调用。该修复**仍只信 adapter 自报的静态 venue/account**：能把 CTP 实现伪装成 SIM 的同进程自定义 adapter 仍可被写入；ZMQ peer/token 认证缺失，客户端能力查询对部分别名也会误报。QA 应继续要求代码受信的 adapter/账号绑定或该 CTP 转发端固定零写；这些 source-only 负测不关闭 G5。详见上链证据。

隔离父 SDK 合成 `da228691` 已把上述转发补丁与 CTP 子模块 `9976bcbb` 的 Feed Ref 必填和 Join 源码链放在同一棵源码树；精确路径下父仓 fake 469 passed/21 async skipped、子模块 255 passed，独立 reviewer 又复跑 Feed/callback 18、Router scope 107、I9 consumer 29 项。原转发提交在该分支中为补丁等价 cherry-pick，并非精确祖先。`bt_api_execution` Gitlink 仍指向无包源码的初始提交；此合成没有 wheel、真实 native close、受信 I9 权威或默认写路由，G5 继续未通过。

另一条隔离父仓 `c4407b09` 仅把 execution Gitlink 快进到 I9 `b676fe6` 源码，保留 `installable=false` 和默认拒写。I9 子包 fake 133 passed/2 skipped、CTP 255 passed；父仓扩展测试 640 passed/2 skipped/19 failed，其中 5 个旧 arming fixture 未建立 I9 identity binding、14 个当前 risk pin 不含 `AccountScope`，两组失败在更新 execution Gitlink 前已复现。I9 全包另有 38 项 Ruff finding。该候选没有安装元数据、受信 wheel/RECORD/origin 或写入权威；不得因 Gitlink 指向 `0.2.0` 源码而将 G5 升级。

Risk 子包不能只选最早带 `AccountScope` 的 `7343430`：它缺当前 dispatch evidence/authority/resolution API，且旧 generic resolver 可清派发中的冻结状态。独立源码审查找到首个同时具备 typed proof 与禁止 generic 清 `dispatch-inflight` 的后继 `dce2c84d`；即便更新此 pin，父 runtime_plugins 仍须改为提交精确 journal proof 给 `resolve_dispatch_freeze`，不得以更新依赖掩盖旧通用调用。当前 14 个 fake-dispatch 失败继续保持未通过。

后续独立父仓 source-only 集成候选 `5de97235` 已将 I9 child 指向仅作质量整理的 `5579807`、risk 指向 `dce2c84`、monitor 指向干净的 `8498ca7`，并在父层增加 typed proof/authority fence 解析；五个旧 arming fixture 已改为先消费 fake I9 reservation，未放宽生产 guard。用上述精确干净源码路径（base=`3de0fa4`、CTP=`9976bcbb`）重跑父仓非网络 contract 加 fake journal：`1039 passed, 7 skipped, 7 warnings`；risk 子包 `159 passed`、monitor `40 passed`、I9 `133 passed, 2 skipped`。此前 `c4407b09` 的 19 项失败是旧候选历史结果，并未追溯修改。独立 risk 代码审查未找到绕过 journal authority 清除 `dispatch-inflight` 的路径；monitor 后继的独立源码审查确认其 durable outbox 对本地 fake 事实有提交/回读合同，但 control ledger 信任调用方自报的 issuer/authorization，不能当生产鉴权边界，consumer 也须按 event ID 去重。该组合仍无受信 wheel/RECORD/import-origin、共享远端可获取的全部 Gitlink、原生会话或可信撤单目标 issuer；execution 子模块的 `installable=false` 也未改变。以上只更新离线开发证据，**G5 仍未通过，默认 `NO_WRITE / LIVE_NO_GO`**；详情见 [G5 I9 源码审计](evidence/ctp-i9-orderref-bridge-audit-2026-09-26.md)。

G5 新的独立执行子包 `c10ccf5f` 增加持久撤单目标投影与单次消费合同，并把 stage/claim 新鲜度复核移至事务锁内、authority verifier 返回后及 stage 返回前；本地完整子包 `141 passed, 2 skipped`，父仓 source-only 集成 `097a98a7` 的非网络合同与 fake journal `1039 passed, 7 skipped`。独立审查确认其 verifier 仍为注入信任边界，原生查询证据尚不能独立绑定同 Store I9 reservation 与一条 OPEN/PARTIAL 订单，因此没有可信 pre-cancel issuer，也未接默认路由。**G5 继续 NOT_PASSED、NO_WRITE / LIVE_NO_GO。**详见 [G5 I9 源码审计](evidence/ctp-i9-orderref-bridge-audit-2026-09-26.md)。

[R3r2 安装 wheel G5 假链反例](evidence/ctp-g5-r3r2-poisoned-claim-independent-rejection-2026-09-27.md)进一步确认：合成最终准入拒绝时零原生 Req，family owner 已 POISONED 并在重启后拒绝新 owner，但旧命令仍 CLAIMED/inflight，无法写显式 UNKNOWN 回执。独立新 SQLite 与安装 CTP RECORD 核验通过；更宽组合仍有 18 项失败。原作者 JSON 中 Execution wheel SHA 多写一字符，v2 勘误核对了原统一消费者与当前字节。V21 专用终态化和全套复测未完成，G5 仍未通过。

[I13 完整运行时 Python 清单候选](evidence/ctp-i13-runtime-source-manifest-candidate-2026-09-26.md)涵盖当前脏工作树的 91 个源码文件并通过父 launcher 的格式解析；父启动器的离线 seam 现也核对 seal 返回的源码根与有序标准库路径，关闭失败明确拒绝，三组相关 fake 测试 42 项通过。但受信 manifest 路径仍不存在、代码 pin 全零，外部 descriptor、真实 Windows Job、SDK wheel/native 扩展和外部 review 均未绑定；它不能解除 G1 或用于真实只读重试。

[隔离 I13/I15 源码快照候选](evidence/ctp-i13-i15-source-snapshot-candidate-2026-09-26.md)把当时的 91 个源码文件逐字节固定于本机干净提交 `64c271bf`，post-G5 两种 schema 的 manifest 正验通过、单文件破坏负验拒绝；零差异结论仅对应该快照时点，后续主仓 managed allocation reader 等修改不在其中。它仅在本机，runtime manifest 路径仍缺、I13/I15 pin stub 均按设计拒绝，且没有 wheel/origin、受验完整 guardian 链、原生生命周期或外部审查；**G1 继续 NOT_PASSED**。

[I13/I15 outer watchdog 合同](evidence/ctp-i13-i15-outer-watchdog-contract-2026-09-26.md)与[独立 Windows Job 后端候选](evidence/ctp-i13-i15-windows-job-backend-2026-09-26.md)合计 28 项本地测试通过，其中一项仅启动无网络 Python 子进程；异常/超时结果要在长生命周期 custodian 确认接管句柄后才标记 `controls_retained=true`。即使 CreateProcessW 只返回非零线程句柄，也必须托管该线程句柄、Job 与 attribute backing，并保持 UNKNOWN，不能宣称子进程已退出。后端仍未接入受信源码清单、外部 descriptor、隔离解释器、marker、普通 CLI 或 CTP SDK；Python/native 调用自身也没有独立宿主提供的硬性整条命令截止保证。它是开发候选，**G1 仍未通过**，不得据此启动真实账号诊断。

[进程外 supervisor 缺口与验收合同](evidence/ctp-i13-i15-out-of-process-supervisor-gap-2026-09-26.md)明确当前 custodian 仅存在于调用它的进程内，无法在该进程挂死或退出后独立维持和核验控制句柄。后续必须由受信 guardian、长生命周期 Job 宿主和完整 parent launcher 三层共同使用一个绝对截止；本地 wrapper/fake 测试不能替代该宿主验收。

写入口静态清单初始扫描 349 个 Python 文件、327 个 writer 候选和 62 个动态调用点，零解析错误；受控基线覆盖 180 个普通 `examples/` 子目录和 2 个仓库根 Python 脚本。另将 27 个 `__pycache__` 目录、`examples/logs` 输出目录分类为生成物，并以一个摘要项标记私有 CTP runtime state（不枚举或扫描其内容）；共发现并分类 211 条路径，当前 `UNCLASSIFIED` 路径为 0。初始 389 项处置当时全部为 `REVIEW_REQUIRED / NOT_AVAILABLE`。后续 r2c2 将清单扩展为 445 项，当前覆盖与处置状态见文末 Scanner disposition rebaseline R2 记录。路径分类与 AST 命中均不证明运行时可达性或 writer 关闭，也不授予路由。见[初始候选清单](evidence/live-execution-inventory-candidates.json)和[初始处置清单](evidence/live-execution-writer-dispositions.json)。

## 依赖顺序与验收矩阵

依赖按分支关闭：G0–G5 是共同前置；SimNow 有界操作性验收走 G6-S→G7-S，strict F14/production 另须 G6-P，严格 SimNow 声明才可走 G7-P，生产走 G8-P。任一所需门失败、未知或缺证据时停止该分支，不得用后阶段 fake 或配置结果倒推通过。G7-S 的有限结果不关闭 G6-P，也不解锁生产。

| 门 | 开发/QA 步骤 | PASS 所需证据 | 失败 / 当前状态 |
| --- | --- | --- | --- |
| G0 配置与传输 | 使用合成文件测试 schema、seal、单对/多对互斥、候选上限/去重、坏字段拒绝、Git 忽略与权限检查。需要查看现场传输时，只运行 `doctor` 和 `check-ctp-fronts`，保存脱敏候选索引、采样结果、配置摘要和交易/结算两个写计数。 | 只有配置中显式列出的整对参与选择；选择规则符合上表；私密值不出现在 stdout、日志、receipt、CI 或 Git index。TCP 结果明确标 `TRANSPORT_ONLY`、`provider_login_started=false`、SDK 未导入、交易/结算写入为 0。 | 配置外回退、set/time 规则、单端点可达仍选中、原值泄漏或将 TCP 写成登录 PASS，均拒绝。现场索引 3 的可达性是历史时点结果。 |
| G1 固定制品与有界监督 | 在新、独立的一次性只读尝试前，核验精确 SDK wheel、installed RECORD/import origin、隔离解释器和代码 pin；验证整条命令总预算确实覆盖父级探测、setup、child、close 与 Job 清理。每个尝试用新 ID/marker；已消耗 marker 不重置。 | 可复现的制品身份和 supervisor receipt；预算超时或 close 不确定时 Job containment 证据与 fail-closed 结果；前置 TCP socket 仅在凭据前使用且仅触达配置候选，凭据 resolver/SDK 只在全部适用的来源、制品、配置门通过后调用。 | 普通 CLI preflight 仍不可用。I11/I12 marker 已消耗；未登记的 inert guardian 与独立外层 Job supervisor 在 owner 死亡后验证了 deadline 时请求终止和 child 清理；最新[完整七模块复验](evidence/ctp-inert-supervisor-95-review-2026-09-26.md)为 `95 passed`，保留此前 `93/2` 等失败记录，且回执仍可能晚于 deadline。同步进程/Win32 创建、supervisor 自身卡住、受信 descriptor/ACL、来源 pin、native close 和普通命令整链仍缺，不能保证硬性总截止。 |
| G2 SimNow TD 只读 | 仅在 G1 关闭后，用独立受监督 TD child 重封同一 sealed config，并核对 config/registration digest、候选索引及精确 MD/TD pair。先确认身份，再执行合同要求的七类终态只读查询；不构造 MD client。 | 脱敏回执证明同一账户、TradingDay、连接代次和精确过滤范围；每条请求都有匹配的原生终态证据；scope 字段不完整或不一致时标 `unverified` 并失败；写入与结算计数为 0；TD native close 完整通过后才可开始 MD。 | I12 结果为 `sdk_artifact/runtime_policy_rejected`，login 未观察、查询均 unverified、close 未尝试，marker 已消耗。历史七项查询的终包不替代当前尝试，也不证明共同账户快照。 |
| G3 SimNow MD 只读 | 仅在 TD 查询和 close 均通过后，用另一受监督 child 重封并复核同一配置摘要与 pair，不重新选路。核验 login 原生提交返回、身份字段、精确合约订阅提交与匹配 ACK、首个匹配 tick 和同交易日证据。 | 各同步提交返回精确 `int 0` 后才能公布成功；登录回调身份与配置/会话精确匹配；订阅 ACK 对应所选合约和请求；首 tick 与同交易日正面观察均存在。ACK 单独不够。 | I11 虽观察到订阅 ACK，但身份仍 `identity_unverified`，tick/TradingDay 为 null，Join pending；不得记 MD 或 TD→MD 完整会话通过。I11 marker 已消耗。 |
| G4 MD/TD 原生关闭 | 分别验收 TD、MD close receipt 与创建时相同的 session generation；先确认 SDK/native API 生命周期与供应商对精确 DLL/header 的合同一致，再接入受管运行时。 | receipt 正面证明要求的 `Join` 返回、`Release` 完成和观察线程退出；没有活动 callback；父 Job 也正常清空。所有事实均匹配同一个会话代次。 | 任一 Join pending、Release 未证实、receipt 缺失/矛盾、异常或超时均为失败，保留账户 lease 并停止后续阶段。Job empty、进程退出或 `client_stop_returned=true` 均不替代 native close。 |
| G5 唯一账本与 OrderRef | 先按 D41-01/D41-19 用 ADR 冻结一个 active order authority 和 cutover；目标为独立 `bt_api_execution` SQLite。以 fake client 验证稳定 runtime intent/order/action identity、登录 `MaxOrderRef` 导入、持久 reservation-before-intent、12 位 `OrderRef` 分配、cancel action 到目标订单映射、HedgeFlag 原样传递及损坏 journal 拒绝。逐项核对 Store 命令、SDK outbox、原生请求及回调是否共用同一个持久 command ID。 | 所有 submit/cancel ID 均在同一权威账本中唯一、持久、可重启读回；旧映射导入无冲突且有审计；reservation 不复用；runtime ID 不截断构造 `OrderRef`/`OrderActionRef`；未确认账本/映射前 native dispatch 计数为 0。Store 不另持有可独立发送的第二队列权威。 | ADR 未冻结或出现两个 journal authority、Backtrader `OrderBase.ref` 被用作恢复主键、MaxOrderRef 未核验、映射/文件持久性未证实，均阻断。单独 resolver 测试不等于此门 PASS。 |
| G6-S SimNow 本机执行门 | 仅在 G0–G5 通过后，以 fake/隔离环境验证同一 OrderRef/command 权威、worker 回执栅栏、第二本机 writer 拒绝、逐动作操作窗口许可、当前账户/交易日结算查询、真实来源查询合同、重复/迟到/错账户回调、崩溃切点与 UNKNOWN 不重派。 | `CtpSimNowOperationalWindowPermit`（或经审查的等价类型）与 strict 外部 fence 不可互换；一行账本在发送前持久化 reservation/claim/queue receipt；本机 lease 连续持有；所有不明状态冻结；只报告单流查询和 `UNVERSIONED_QUIESCENCE_CHECK`，跨主机/手动写者排他与共同快照明确 `UNPROVEN`。 | 当前 S permit/真实 callback/唯一 OrderRef 接线未实现，`LOCAL_FAKE_ONLY / NO_WRITE`。不得用 fake strict fence、CTP `bIsLast`、两轮相等或配置字段伪造通过。 |
| G6-P 外部账户控制 | 对拟声明 strict F14 或 production 写入的精确账户/动作，由独立认证服务提供账户级跨主机 writer fence、撤销/转移语义，以及资金、全账户委托、成交、持仓同版本完整快照；测试旁路客户端、旧 epoch、断线与接管。 | 信任根/服务身份、签名或等效认证、共同版本和覆盖范围、逐动作 claim 及最后 dispatch 栅栏均可复核；本地租约和 SimNow S receipt 不能替代。 | 已审公开 CTP 查询接口不提供这些原语；当前无受信 authority 或网关，`F14_STRICT_BLOCKED / LIVE_NO_GO`。 |
| G7-S 真实 SimNow 最小报撤单 | 仅在 G0–G5、G6-S、实际 TD/MD/Join 和当前账户/TradingDay 结算就绪均通过后，在同一受保护 config 的固定合约范围内执行一笔风险受限、仍有可撤余量的限价单：报单→原生订单确认→精确撤单→剩余量终态及订单/成交/持仓/资金回查。先做取消正例；成交正例须待独立平仓路径完成后另做。真实强杀不作为最小真测前置；离线故障注入仍必须覆盖。 | 脱敏证据能对应每次请求、OrderRef、ActionRef、session、callback、查询及数量守恒；审批和本机 lease 始终有效；无未知状态、外来订单或不明敞口；native Join/Release 干净完成。结果只能记 `SIMNOW_OPERATIONAL_ATTESTATION_TESTED`，并注明跨主机写者排他/共同快照未证实。 | 当前 `NOT_RUN / NO_WRITE`；官方 7×24 不提供结算，若配置选中而无真实结算查询则零写结束，不按时间/set 自动切换。全成订单不能充当成功撤单；未知结果不得自动重试。 |
| G7-P strict SimNow F14（可选） | 仅在 G6-P 的外部账户级 fence 与同版本完整快照也对同一 SimNow 账户成立时，重做 G7-S 的逐动作验收并由独立 QA 审核严格外部证据。 | 可单独标 `F14_SIMNOW_ACCEPTED`，范围仅限该 SimNow 账户/窗口，不向 production 继承。 | 当前没有外部 authority；G7-S 结果不能升级成 G7-P。 |
| G8-P 同文件 production | 只用临时目录与合成字段证明 canonical `ctp:` 文件从 `simulation/sandbox` 切至 `live/managed_live_direct` 后仍由同一个受管 CTP runner 解析；旧 SimNow 许可、审批、会话、账本范围全失效。真实生产仅在独立生产制品/账号/session/风控/监控、G5、G6-P、真实权限与恢复验收后开放。 | 操作者届时只改同一受保护 config 的 mode/preset、账号认证、前置和合约；代码复用同一实现但重新办理生产准入，不能复用 SimNow 收据；每步有脱敏审计与失败零写证据。 | 当前默认 live route unavailable，缺生产 session、统一持久账本及外部控制；配置变化在凭据、SDK、网络和写入前拒绝，`NOT_RUN / LIVE_NO_GO`。 |

[G6-P/G8-P 外部账户控制服务合同审计](evidence/ctp-g6p-g8p-external-account-control-service-contract-review-2026-09-26.md)列出可复用的本地接口、服务端最终 dispatch 栅栏、同版本全账户快照和跨主机/旁路验收计划；它是设计审查，没有外部服务或 production 正验，不改变上表状态。

2026-09-26 新增的 `backtrader_runtime/ctp_f14_signed_receipt_contract.py` 是离线、非授权的
canonical receipt 合同验证候选；它要求调用方注入 issuer/key/audience pins，并提供可用注入
公钥与 SHA-256 pin 校验真实 Ed25519 签名的本地 verifier，只返回 receipt-shape observation。
它没有受信生产服务 pin、服务端 actor、跨主机或服务端 replay/epoch ledger、admission handle 或
executor/native dispatch；验签不能证明真实账户排他或快照来源。此项不改变
G6-P `BLOCKED / LIVE_NO_GO`、G8-P `NOT_RUN / LIVE_NO_GO` 或默认 `NO_WRITE`。
显式注入的本机 SQLite observation fence 可跨进程和重启拒绝重放，但 ACL/owner 未验收且不是服务端 fence。
此离线 slice 的 focused fake 与临时 Ed25519 密钥测试 `25 passed`，兼容 venv 复跑无 warning；Ruff 检查通过。

G5/G6-S 的新增负测必须区分三个状态：发送前已持久化 `queued=false` 才是本地拒绝；发送 claim 之后任何裸 `REJECTED` 或未知异常都须落 `UNKNOWN` 并停止重派；`QUEUED` 只表示本地队列接纳。受管 CTP 的公开裸 `enqueue_cancel` 在 recovery armed/unarmed 两种状态都须于请求构造和 worker 启动前拒绝，heap、SDK cancel、原生写入计数均为 0。真实 Store worker 只有在同一 SQLite 行已持久化确切 queue receipt 后才可看见命令；写入失败不能通知 worker。重复 worker、重启和多连接均须保持同一 OrderRef 与至多一次 native send，不得凭任意 sender payload 自称“无发送”而解除冻结。

G7-S 先验收成功撤单，成交另作需具备平仓/归零路径的正例；依据是 [SimNow 官方 CTP Mini API 手册](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.0.pdf)把“已成交或已撤单”“报单全部成交”列为撤单失败的常见原因。两类正例均须受相同逐动作风控和账户对账门约束，不能为了取得撤单回执扩大订单量或敞口。[SimNow 官方产品说明](https://www.simnow.com.cn/product.action)明确第二套 7×24 环境仅提供 API 测试而不提供结算等服务；当前运行时仍只按配置前置和连通性选路，G7-S 的结算/资金验收必须以该次账户的实际正面证据为准，不能由端点名称或 TCP 连接推断通过。

[7×24 与结算就绪门槛审查](evidence/ctp-settlement-readiness-gate-audit-2026-09-25.md)确认：当前 managed TD readiness 要求当前账户/TradingDay 的真实结算确认查询记录，7×24 官方产品能力未承诺该记录。即使配置中的 7×24 pair 因 TCP 延迟最低而被选中，也只能继续做连接/只读 API 诊断；缺少该真实记录时写入门必须保持关闭。完整 G7 应由操作者在同一受保护 `config.yaml` 显式配置具备结算服务的正常环境，并重新完成全部会话和账户门；代码不根据地址、set 标签或时间自动切换。

[MD 回调源码复核](evidence/ctp-md-callback-source-audit-2026-09-25.md)已把 I2 的请求 ID 不匹配与 I4/I6 后续身份未验证分开；目前没有足以确认账号错误的证据。G3 下一轮先用隔离 C++/SWIG director fake 验证 borrowed-pointer 与字段形状，再考虑任何新的受监督只读观察。此源码审计不改变 G1～G4 的阻断状态。

**Windows MD ABI/制品归属（2026-09-26）：** I2/I4/I6/I7 已审计源码与 wheel payload 均指向 full CTP v6.7.7 MD DLL/header/SWIG 组合，哈希一致，未见 Mini 1.7.0 混入；这只排除已审计 payload 内的混装可能。四次 child 的 `thostmduserapi_se.dll` 实际 mapped-module receipt、官方归档及官方 SHA-256 均缺失，因此不能证明运行时实际 DLL，也不能解释 request ID、空身份字段或 Join pending。根因未定，G1–G4 阻断不变。详见 [I2/I4/I6/I7 Windows MD ABI/制品归属离线核对](evidence/ctp-i2-i4-i6-i7-windows-abi-artifact-audit-2026-09-26.md)。

[已映射模块身份回执候选](evidence/ctp-mapped-module-identity-candidate-2026-09-26.md)在隔离本地提交 `a3b3fd89` 中提供当前进程模块表的 pathless/文件身份接缝，16 项 fake 测试通过；尚未在真实受监督 child 内调用 Windows API，也不能排除路径重解析到网络、并发改写、映射后文件替换或内存中字节差异。G1 通过前不接诊断入口，MD 根因仍未定。

候选代码变更后的本地最低复测集只使用合成配置和 fake dependency；在仓库根目录运行并保存精确 revision、完整命令、退出码及脱敏日志。该结果只能记 `LOCAL_CONTRACT_PASS`：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
python -m pytest -q -p no:asyncio --tb=short `
  tests/unit/runtime/test_runtime_config.py `
  tests/unit/runtime/test_ctp_private_config_setup.py `
  tests/unit/runtime/test_ctp_private_runtime_git_hygiene.py `
  tests/unit/runtime/test_ctp_front_pair_probe.py `
  tests/unit/runtime/test_ctp_configured_front_check.py `
  tests/unit/runtime/test_ctp_simnow_readonly_runtime.py `
  tests/unit/runtime/test_ctp_simnow_native_readiness.py `
  tests/unit/runtime/test_ctp_managed_reconciliation.py `
  tests/unit/runtime/test_ctp_queue_receipt.py `
  tests/unit/runtime/test_ctp_simulation_execution.py `
  tests/unit/stores/test_managed_ctp_store_adapter.py
```

若涉及 `bt_api_execution`，还须在其冻结候选及隔离环境上单独复跑 SDK 的账本、callback/outbox 与崩溃恢复焦点集，并记录独立制品来源；不要把另一个工作树或旧 wheel 的数字并入主仓结果。此处列出的本地集不包含 provider/真实账号步骤，也不解锁任何已消耗的一次性 marker。

## 可接受的状态跃迁

| 标签 | 可写入条件 |
| --- | --- |
| `LOCAL_CONTRACT_PASS` | 精确 revision 的 fake/schema 测试通过；明确注明未访问 provider，不能抬升为会话或写入结果。 |
| `TRANSPORT_ONLY` | 配置候选中有完整 MD/TD TCP reachability；明确注明时点、候选索引、采样和零认证/SDK/写入。 |
| `SIMNOW_READ_ONLY_ACCEPTED` | G1–G4 每项均有同一代码/制品/配置摘要/pair 的正面原生证据；未知与历史回执不计入。 |
| `SIMNOW_OPERATIONAL_ATTESTATION_TESTED` | 仅当 [ADR-41-16 option B](ADR-41-16-simnow-f14-writer-fence-proposal.md) 获正式批准、G0–G5/G6-S/G7-S 对具名 SimNow 账户和窗口逐项验收通过，才可记录一次有界操作性结果；账户级跨主机排他与共同快照仍为 `UNPROVEN`，不等于 F14 或生产 PASS。当前 `NOT_RUN`。 |
| `F14_SIMNOW_WRITE_ACCEPTED` | 只有严格 F14、G5/G6-P/G7-P 全部完成，且服务端账户覆盖/共同快照/账户级 writer fence 经独立 QA 验证后，才能申请裁决；不能由 S 级结果、自签收据或本文件宣布通过。 |
| `PRODUCTION_ACCEPTED` | 另一个独立生产阶段完成同文件 fail-closed 与正向 route、账户/制品/会话、审批、risk/monitor、服务端 fence、恢复及真实证据验收；不得由 SimNow PASS 自动继承。 |

发现任何配置/账户/候选/制品变化、原生状态未知、回调无法同源关联、账本冲突、超时、进程异常退出、非预期写入或日志脱敏失败，立即标记当前门失败/未知、停止后续门并保留冻结；不得复位已消耗的一次性 marker。S 与 strict F14 状态分别依据[唯一决策 ADR](ADR-41-16-simnow-f14-writer-fence-proposal.md)、[计划中的 F14 顺序和外部依赖](迭代计划.md)、[验收门槛](验收文档.md)及本目录的增量证据更新。

## 相关证据与操作文档

- [I13/I15 外层父进程信任根设计与离线切片](evidence/ctp-i13-i15-parent-launcher-trust-root-design-2026-09-25.md)：pre-import stdlib launcher、stdlib pycache 旁路、PyYAML origin pin、volume/file-ID source lease 与 no-system venv 的设计；manifest/source loader lease 与 inert launcher 已有未登记的离线切片，受信生产入口和完整制品 pin 仍未验收，不授权真实只读尝试。
- [I13/I15 惰性进程独立截止监督切片](evidence/ctp-i13-i15-inert-deadline-supervisor-process-slice-2026-09-26.md)：owner 死亡后的 outer Job 终止请求与回执时点分离，只是 inert Windows 进程证据，G1 未通过。
- [配置与运行模式规格](配置与运行模式规格.md)：唯一配置路径、canonical `ctp:` 和 front-pair 规则。
- [实施状态与验收快照](实施状态与验收快照.md)：当前 `NO_WRITE / LIVE_NO_GO`、普通 `preflight` fail-closed 状态。
- [开发与 QA 交接清单](开发与QA交接清单.md)：F14、Store/CTP typed handoff 与真实账号阶段证据要求。
- [前置传输复查](evidence/ctp-configured-front-check-2026-09-25.md)：同一配置的脱敏 TCP 观察。
- [I11 MD-only 诊断](evidence/ctp-i11-md-diagnostic-2026-09-25.md)及[I12 TD-only 诊断](evidence/ctp-i12-td-only-diagnostic-2026-09-25.md)：已消耗的一次性只读尝试结果。
- [I14 TD→MD 设计](evidence/ctp-i14-combined-readonly-plan-2026-09-25.md)：当前仍待实现的只读验收候选。
- [Native Join 源码审查](evidence/ctp-native-join-source-review-2026-09-25.md)：已证实源码顺序、未证实根因和待厂商确认问题。
- [离线写入边界增量证据](evidence/ctp-offline-write-boundary-progress-2026-09-25.md)：当前 managed handoff、outbox、回调、账户 fence 与账本边界。
- [ADR-41-16 F14 writer-fence 提案](ADR-41-16-simnow-f14-writer-fence-proposal.md)：`PROPOSED` 的未批准选项；严格 F14 仍是当前决定。

### 迭代41 r2b credential/projection 测试迁移独立复核（2026-09-27）

[独立 QA 归档](evidence/ctp-account-actor-r2b-test-migrations-independent-qa-2026-09-27/README.md)：credential safety 为 `SAFE_LOCAL_TEST_MIGRATION`（隔离 8/8）；projection bridge 为 `SAFE_LOCAL_TEST_MIGRATION_WITH_COVERAGE_LIMIT`（逆补丁 18 failed/14 passed，迁移后 32/32）。projection 测试仍覆盖 adapter projection/replay 与 NON_CTP private-queue 原语，但正向 submit/cancel 不再覆盖 Store→adapter wiring，旧 raw CTP cancel queue/worker side-effect 断言改成 constructor early-reject。不得把 18 个旧失败 nodeid 的映射称为完整业务/Store 验收。r2b/r2c 仍未合主树；Store 258 项旧用例失败的集成阻断不变，Actor/provider 权威与写入路线未获接受。

### 013_3 local replay r2 主树验收（2026-09-27）

[冻结结果与独立 QA 收据](evidence/iteration41-0133-local-replay-r2-main-integration-2026-09-27/README.md)接受 `LOCAL_REPLAY_ONLY_ACCEPTED / NO_WRITE / LIVE_NO_GO`：主树焦点 `28/28`；完整 `tests/unit/stores tests/unit/runtime` 为 `2638 passed / 43 skipped / 2 xfailed / 0 failed`。相同测试范围应用前 `2636 passed / 43 skipped / 2 xfailed`，本次净增两项测试、没有旧 nodeid 失败。此结果仅覆盖 013_3 合成本地回放组合结构，不能作为 SimNow、CTP 原生会话/报撤单或 production 准入。主树 CTP Store SHA 与 Actor r2b/r2c 状态未改变。同源 patches 1–4 broad 候选仍被拒绝：14 个基线失败、252 个候选失败，其中 238 个为新增失败。正式 patch 5（013_3 r2）在该 broad run 后才应用，并单独通过 guarded 3/3 focus；patch 5 后未重跑 broad suite。


## 2026-09-27 supplemental local QA status

- [I22 stable runtime-ID r1/r2 QA](evidence/i22-stable-runtime-id-independent-qa-2026-09-27/README.md): r1 is `PARTIAL / NEEDS_REVISION` because the candidate test removed actual `_sdk_order_request` assertions for zero binding lookups, zero reservations, and unchanged `order.info`. R2 independently passes the focused local fake test and restores these actual-method checks. This narrow PASS is not external Actor/provider authority, G6-P, or production acceptance.
- [AccountActorPort r5 QA](evidence/ctp-account-actor-port-r5-independent-qa-2026-09-27/README.md): author reported 40/40, but independent QA found a constructor-time route TOCTOU: an injected resolver changes a shared descriptor from NON_CTP to CTP after classification and before the fake gateway factory, which is called once; later submission rejection does not undo construction. Status `PARTIAL / NEEDS_REVISION`; G6-P/G6-S/G7-S stay closed.
- [Store r2c independent QA](evidence/ctp-account-actor-store-r2c-independent-qa-2026-09-27/REPORT.md): `LOCAL_SAFETY_INCREMENT_ONLY / MAIN_MERGE_REJECTED`. Guarded full Store/Runtime run: 2,460 passed, 258 failed, 28 skipped, 2 xfailed (30 skipped records in JUnit); the failed node-ID set exactly matches the r2b set. Failure classes: 249 external account actor unavailable, 6 store route ambiguous, and 3 store provider unsupported, exactly matching r2b. Of 158 I22 query/evidence nodeids, one was migrated and 157 still stop at Store construction; shared-session read-side query behavior is untested. The separate 44 route-focus, 7 query-evidence-focus, and 22 optional cases passed, but do not clear the broad regression or establish an external Actor. Store r2b/r2c remain unmerged.
- [Real-account acceptance gap plan](evidence/iteration41-real-account-acceptance-gap-plan-2026-09-27.md) is a read-only dependency/acceptance plan only, not a G0–G8 or real-trading pass.


## AccountActorPort r6 independent QA — local contract only (2026-09-27)

[Author candidate and independent QA archive](evidence/ctp-account-actor-port-r6-independent-qa-2026-09-27/README.md) is `LOCAL_FAKE_CONTRACT_PASS_WITH_LIMITS`. Author manifest SHA-256 `c410b68aa39f476818afe517a0974bbbf428497236c20174d1d61a0830440d59`; independent QA manifest `360812153de614f9bd6df5c1e82c36cec6ba64eaf75376c3a44ed048a6bd798f`; independent receipt `f1c14a6978b51dd5b78829abfcec31e8343b37535359435a3a320250fc8d0dea`. The prior stable synchronous resolver mutation is rejected before gateway/API factory calls. This does not establish callback confinement: a transient route mutation restored before callback return is accepted, and a gateway factory may be called once before a post-callback check rejects construction and withholds publication. No external Actor/provider, durable cross-process authority, Store integration, G6-P/F14, or real-account acceptance is established.

AC41-63 raw-fallback-removal slice: [main integration archive](evidence/ac41-63-raw-fallback-removal-main-integration-2026-09-27/README.md) records RAW_FALLBACK_REMOVAL_LOCAL_ACCEPTED / NO_WRITE / LIVE_NO_GO and independent SAFE_TO_APPLY_RAW_FALLBACK_REMOVAL_ONLY. Main-tree focus passed 138/138; root-reported Store/Runtime broad run passed 2,641, skipped 43, xfailed 2, failed 0; Ruff, py_compile, and diff check were clean. This accepts only the raw-fallback-removal slice, not AC41-63 writer closure, CTP writes, or live operation.

G4 parent SDK status: [canonical QA archive](evidence/iteration41-g4-parent-sdk-status-qa-2026-09-27/README.md) is DISPOSABLE_PARENT_ARTIFACT_INTEGRITY_ONLY / THREE_PACKAGE_PIN_NOT_AVAILABLE / G4_CLOSED / NO_WRITE. The disposable parent wheel and installed RECORD reproduction across two venvs establish artifact-integrity evidence only. The bt_api_py code pin and matching base 0.15.5 + CTP I2 + parent three-package wheel install/origin chain are unavailable; the embedded digest is not an accepted pin. G4, native lifecycle acceptance, and the default CTP route remain closed.

AC41-63 controlled-writer slice 3: [independent static review archive](evidence/ac41-63-writer-slice3-independent-static-review-2026-09-27/README.md) records `PASS_STATIC_AUDIT_SCOPE_ONLY` for 21 new IDs, bringing cumulative reviewed coverage to 43/389 with 346 residual. All official dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`. The direct registered-simulation arm path is a conditional static source finding only; no provider/native/account/write execution occurred. `NO_WRITE / LIVE_NO_GO` remains in force, and AC41-63 writer closure is not accepted.

### AC41-63 scanner expansion r2c2 main integration (2026-09-27; historical snapshot)

[Historical canonical archive](evidence/ac41-63-scanner-expansion-r2c2-main-integration-2026-09-27-final/README.md) records the earlier 445-row snapshot (344 writer, 101 dynamic). Its counts are superseded by the R2 rebaseline below; archive hashes and historical test results remain preserved. Both are scanner/checklist integrity only, not writer closure or route authorization.

### AC41-63 scanner disposition rebaseline R2 (2026-09-27)

[Canonical R2 archive](evidence/ac41-63-scanner-disposition-rebaseline-r2-main-integration-2026-09-27/README.md) records `SCANNER_COVERAGE_LOCAL_ACCEPTED / NO_WRITE / LIVE_NO_GO`. The frozen patch's four exact main target hashes match. The current verifier reports 460 discovered / 460 checklist entries, six historical tombstones, all 460 active entries `REVIEW_REQUIRED / NOT_AVAILABLE`, and `reason_codes: []`; boundary `STATIC_DISPOSITION_INTEGRITY_ONLY_NOT_LIVE_ADMISSION`. Inventory: 363 writer and 97 dynamic candidates across 355 files, zero parse errors and unclassified paths. Main focus: 6 passed; Ruff, py_compile and diffcheck passed. This is static inventory/disposition integrity only; it is bound to the 2026-09-27 source snapshot, so later accepted source changes require a fresh rebaseline. No writer closure, route admission, provider authority or write permission follows.

### AC41-63 full 460-candidate writer review (2026-09-27; historical snapshot)

[Canonical review archive](evidence/iteration41-ac41-63-writer-review-460-2026-09-27/README.md) maps all 460 inventory positions to source reviews and independent checks against prior A039-era inventory SHA-256 `03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456` (363 writer, 97 dynamic, 355 files). Coverage found 460 unique positions with no gaps or overlap; 20/20 checksums and 14/14 links verified. Findings are limited to the mutable wrapper flag reaching a fake sink after deliberate same-process mutation, `create_live_broker` accepting a caller-supplied Store, and `RuntimeRegistry(trusted=True)` not being code-enforced. The archive also records 31 stale line-only checklist locators across eight files; verification still passes and all official dispositions remain `REVIEW_REQUIRED / NOT_AVAILABLE`, with six tombstones. This is a historical static review: at the CE04 refresh checkpoint the inventory was `0874A81A…`, later superseded by the official `A959A3BC…` inventory; ordered candidate identities remain unchanged. It does not establish current-source writer closure, provider authority, or write permission (`NO_WRITE / LIVE_NO_GO`).

### Store AccountActor r2d and I22 read-port r2d (2026-09-27)

- [Store AccountActor r2d independent QA](evidence/iteration41-store-account-actor-r2d-independent-qa-2026-09-27/README.md) is `LOCAL_COMPATIBILITY_CANDIDATE_PASS / CTP_WRITE_NO_GO`; its six focused candidate tests pass for unsupported placeholder-provider compatibility. The r2c broad integration still has 258 failures, and r2d has not been applied to the main Store.
- [I22 shared-session read-only port r2d QA](evidence/iteration41-i22-shared-session-readonly-port-r2d-independent-qa-2026-09-27/README.md) is `FAKE_READ_PORT_CONTRACT_ONLY / NO_WRITE / LIVE_NO_GO`: 3/200 original nodeids migrated and 197 untouched; seven focused QA tests passed. It depends on unmerged r2c and establishes no account/session authority, common snapshot, settlement authority, or production read source. Neither archive changes the main tree or accepts a CTP route.

AC41-63 007 certification-helper fail-close integration: [canonical evidence report](evidence/ac41-63-certification-helper-fail-close-main-integration-2026-09-27/README.md) records only the narrow SimNow/Hongyuan helper behavior and local tests. The two main source files match their reviewed candidate hashes; `tests/unit/live_certification` passed 92 tests with one existing warning, against a 90-pass baseline. Independent AST-helper checks passed 5 SimNow fakes and 3 Hongyuan scenarios, with caller reviews 17/17 and 24/24. This is not SDK, account, or provider authority. It does not prove direct runtime-module imports avoid `.env`/credential access; the 013_1/013_2 helper r1 remains held because `load_dotenv_if_available()` runs at import. `NO_WRITE / LIVE_NO_GO` remains.

### G5 dual ActionRef collision — independent fake-only QA (2026-09-27)

[归档记录](evidence/iteration41-g5-dual-actionref-collision-proof-2026-09-27/README.md)保存作者和独立 QA 的两次 fake-only SQLite 重放：同一合成账户下 G5 identity authority 与 V21 Store allocator 分别发出 `native_action_ref=1`，输出字节一致。独立 QA 核对冻结哈希并复跑两次。探针只调用 V21 内部分配 primitive，没有 stage 完整 cancel，V21 mapping row 为空，也没有 provider 重复报单证据。这是账户级共同分配器缺失的结构性阻断证据，不构成 G5 通过。`G5 NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`。

### G5/V21 ActionRef unification design blocker (2026-09-27)

[Canonical archive](evidence/iteration41-g5-v21-actionref-unification-design-blocker-2026-09-27/README.md) records the source/AST-only design review and independent static QA. It confirms separate G5 and V21 allocator namespaces, incompatible worker/Store call contracts, schema 5 versus 21, and no migration bridge for the G5 reservation tables. No patch was produced; a safe candidate needs one account-keyed allocator, coordinated migration with stale-writer fencing, and a separately trusted native ActionRef floor/cutover. The earlier collision is synthetic-only and did not stage a full V21 cancel or mapping row, so it does not show provider receipt or acceptance of a duplicate. `DESIGN_ONLY / BLOCKED_FOR_PATCH / G5 NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`.



### Store R5、Gateway wrapper R2 与 normalized-test R3（2026-09-27）

- [Store R5 main regression archive](evidence/iteration41-store-r5-main-integration-2026-09-27/README.md)：main `btapistore.py` SHA-256 `B9E1BCD3EFA6CF57BF8D3029D60AE89A7158D5332B313EE8DFE12A4A0CA557FF`；Store focus 143/143。Store/Runtime broad 回归的第一次运行有一项顺序相关失败（pytest 全局 `sys.modules` 检查），修正测试隔离后为 2,716 passed / 43 skipped / 2 xfailed / 0 failed，110.01s，一个既有 pytest 配置警告。两个原始 JUnit/log/exit 均保留；broad 是 Store/Runtime 回归快照，不归因单一 patch，也不构成 CTP/Actor 验收。状态 `LOCAL_STORE_GUARD_REGRESSION_ONLY / NO_WRITE / LIVE_NO_GO`。
- [Gateway wrapper R2 main integration evidence](evidence/iteration41-ctp-gateway-wrapper-r2-main-integration-2026-09-27/README.md)：候选基于上述 Store SHA，独立 AST/fake focus 6/6 与四个精确非 CTP allowlist fake probe 通过。范围只含 wrapper 公共方法的 CTP default-deny；raw `_client`、直接 GatewayClient、custom API injection、同进程 mutation 和 CTP read/connect 不受该 gate 完整覆盖。`LOCAL_DEFAULT_DENY_WRAPPER_GUARD_ONLY / NO_WRITE / LIVE_NO_GO`。
- [Normalized Store test migration R3](evidence/iteration41-store-normalized-test-migration-r3-2026-09-27/README.md)：7/7 fake cases independently pass，R3 恢复 `poll_broker_update()` 公共事件轮询及原事件/费用断言，CTP fake submit/cancel 仍零 dispatch。main test snapshot另有等价 `dict.fromkeys` lint cleanup；仅接受测试迁移，不代表 Store/SDK 行为或 writer closure。

### Local fake AccountActor main-tree snapshot（2026-09-27）

Scanner R2 已完成静态 inventory/disposition rebaseline，460 个活动条目仍全部为 REVIEW_REQUIRED；这不扩大 fake 的权限。

### G1、G4 最新独立复核与测试树恢复（2026-09-27）

- [G1 整条命令监督审查](evidence/iteration41-g1-whole-command-supervisor-no-go-2026-09-27/README.md)：独立 inert/fake 测试为 65/65 supervisor 与 1/1 普通 CLI 拒绝；证据 ZIP 的 29 个声明 payload 和归档内 40 个文件复核通过。ZIP 缺两个测试直接使用的 helper，复跑借用了当时主树的 105 个支持文件；两次中间运行各有五个原因未定的超时。父进程创建及同步清理没有可证的整条命令硬时限，预启动服务的 request-only SLA 属于需求变更。结论 `NO_GO_IMPLEMENTATION_FOR_CURRENT_G1_WORDING`，普通 013_3 `preflight` 仍关闭。
- [G4 MSVC/PE timestamp 审查](evidence/g4-msvc-pe-timestamp-author-review-2026-09-27/README.md)：严格隔离 C 构建与 pin 的原生镜像同长，只在两个 PE timestamp 字段的六个字节不同；`/Brepro` A/B 彼此相同但原生镜像比 pin 大 512 字节。更正后的 author archive 与独立复核、后续惰性 linker 输入研究均已归档；最终 49 项 checksum 核对通过。本机受审的 `LINK /?` 与构建命令没有可控时间戳赋值参数，本轮未重建或加载 native。没有精确 pin、受信三包安装链或原生验收；结论 `NO_EXACT_PIN_REBUILD / NO_G4`。
- [测试树 Ruff 事故恢复记录](evidence/iteration41-test-tree-formatter-incident-recovery-2026-09-27.md)：保留事故后 1,736 个 Python 文件快照；已恢复 1,267 个原干净 tracked、24 个原带修改 tracked 和 67 个 untracked 测试，移除三个事故新增路径。各恢复源的隔离 Ruff 输出与事故快照字节吻合，原先 31 个 tracked 测试 diff 路径仍是 31；Ruff 无唯一逆变换，未归档的 style-only 修改不能从格式化输出重建。恢复后 scanner/inert-import 焦点 16/16，Store/Runtime 基线复跑 `2725 passed / 43 skipped / 2 xfailed / 0 failed`。

CTP generic SDK queue fail-close r3 是**被拒绝的主树候选**：独立 fake-only 焦点通过，但当时主树 Store/Runtime 加新增测试的 broad 结果为 `2724 passed / 43 skipped / 2 xfailed / 13 failed`。失败集中在 typed managed cancel、direct `_invoke_sdk_command` 预算能力合同和 recovery-exit 早拒清理。补丁及新增测试当时从主树撤回，Store 恢复至 SHA-256 `A028A68DF87ABE84A1D38F4020D81AF56E0DFB860DED43D36C3830933106696D`。另有独立负测证明，若 `_sdk_exchanges` 快照与注入 API 的实际 CTP 路由不一致，r3 的通用 sink 仍可能触发 fake dispatch；它本来也未覆盖 `_execute_sdk_command` 的 managed typed 分支。后续 r4 的接受范围见下方当前记录。

[Store 条件写入路径窄审计](evidence/iteration41-store-write-narrow-fake-bypass-audit-2026-09-27/README.md)又用隔离 r3 源码复现两类注入身份不一致：`provider=binance` 但注入 API 标为 CTP 时，公开 submit/cancel 可到四次 fake sink；`provider=btapi` 的 API 在构造后由 BINANCE 改为 CTP 时，公开方法产生队列回执、手工执行到两次 fake async sink。正确标记 `provider=ctp` 的对照为零调用。它们是同进程注入/变异条件反例，不证明默认受信路由或真实 provider 写入；r4 未解决该身份快照残余，AC41-63 writer closure 未通过。

[G5/V21 ActionRef 离线 cutover validator r1](evidence/iteration41-g5-v21-offline-cutover-validator-r1-2026-09-27/README.md)是未接运行时的纯内存候选。独立 exact replay 及 28/28 测试、五项状态/边界/恶意回调负测通过；它要求两份快照的调用方提供 boundary label 与每条 action state 精确一致，拒绝 UNKNOWN。历史 manifest 的错误 r0 commit 指针已更正并经独立复核，代码与测试字节不变。调用方提供的边界、摘要和完整性声明均未认证，没有已部署 exporter、原生 ActionRef floor、账户级 writer fence 或迁移过程。结论仅 `LOCAL_TYPED_CONTRACT_ONLY / NO_AUTHORITY / NOT_A_MIGRATION_TOOL / NO_WRITE / LIVE_NO_GO`。

[G6-P external AccountActor 本地资源审计](evidence/g6p-account-actor-resource-discovery-2026-09-27/README.md)为只读源码审查：旧 `D:/source_code/bt_api_py` Gateway 有真实 CTP client 代码，但命令入口没有账户级认证/逐动作授权，identity map 仅内存，默认 client 可同进程起 runtime；脏的 `D:/bt_api_py` 有 Curve/ZAP、durable router/risk/writer 组件，但缺已部署受信的唯一凭据持有者、原生写适配、跨 host/手工终端 writer fence 和同版本完整账户快照。未找到可直接使用的已部署外部 Actor。结论 `NO_TRUSTED_EXTERNAL_ACCOUNT_ACTOR_FOUND / G6-P BLOCKED / SIMNOW_STRICT_NO_GO / PRODUCTION_LIVE_NO_GO`；没有服务或 provider 测试。

### AC41-63 CTP generic SDK queue fail-close r4 主树集成（2026-09-27；历史快照）

[r4 证据归档](evidence/iteration41-ac41-63-ctp-generic-queue-failclose-r4-2026-09-27/README.md)记录从精确 A028 Store 和两个既有测试文件、一个不存在的新测试路径重放的四文件补丁；该历史 Store SHA-256 为 `A0393FC4F0B7212C6EE4B4F32DE2AA9E6E9A0ECFC5FE976F72160E2EC11F6ABE`，现由上方 CE04 R2 current snapshot supersede。独立 fake-only QA 的 12 项新合同、四种 recovery_exit、三项预算/零 writer lookup、十项 managed-cancel/forwarding 兼容均通过；`_cancel_managed` 与 A028 逐字节相同。主树 `tests/unit/stores tests/unit/runtime tests/test_ctp_generic_sdk_queue_failclose.py` 为 `2740 passed / 43 skipped / 2 xfailed / 0 failed`，仅一条既有 pytest 配置警告；Ruff、py_compile 与补丁精确哈希核对通过。该快照 [静态 inventory](evidence/live-execution-inventory-candidates.json) SHA-256 为 `03658257D97E31C2D8F8BFD48685441533552B32674F5D63810141E3038AB456`；verifier 460/460，scanner 15/15，所有活动条目仍 `REVIEW_REQUIRED / NOT_AVAILABLE`。r4 只封堵通用队列和 `_invoke_sdk_command` CTP fallback；已知注入 API/Store 路由快照不一致与更早的 typed `_execute_sdk_command` 分支仍是残余。结论 `LOCAL_FAIL_CLOSE_REGRESSION_ONLY / NO_WRITE / LIVE_NO_GO`，不构成 writer closure 或模拟盘/实盘验收。

上述主树宽回归包含 18 项既有 `optional_sdk("bt_api_ctp.ctp.client")` 测试；安装分发存在时该 helper 导入 SDK 模块。独立 fake-only QA 使用导入拦截，但主树宽回归未记录受信 native 映像身份或 provider 会话，因此不能据其声称 SDK/native 验收。

以上均未打开 CTP 写路由或真实 SimNow/production 会话；`NO_WRITE / LIVE_NO_GO` 不变。

### 007 SimNow C01 r3、G1 故障注入与 G4 来源复核（2026-09-28）

- **C01 r3：source-only 集成已通过；案例仍 `INCOMPLETE`。** 17 个目标应用后的内容与冻结候选在 CRLF 归一化后完全一致；17 目标 Ruff 通过，`git diff --check` clean。候选完整套件 482 passed；集成后主树 `tests/unit/live_certification` 为 **488 passed、1 个既有 warning**。独立 schema QA 对精确 patch 给出 `GO for source-only integration`；alias/session 独立复核 197 passed。可信 SDK issuer ledger verifier 与 baseline/final query receipt path 仍未接通，也没有 native callback 来源认证、受信账号 owner 或 provider 证据。逐目录复查的 33 个入口均为 `BLOCKED` / exit 2 / `managed_ctp_certification_not_registered`，network/order_write 均为 0，真实 `PASS` 为 0。八 ID ledger（auth/login + baseline/final 三类查询）16 项 fake-only 测试只证明本地相关性。详情见[007 staging acceptance 证据](evidence/iteration41-007-simnow-33-case-staging-acceptance-2026-09-28.md)。
- **G1 strict whole-command：`NO_GO`。** 2026-09-28 独立审查对 backend 创建、launcher resume、Job termination、handle release、control escrow 与回执 `fsync` 做六项 fake 同步故障注入，6 passed；注入调用在配置 deadline 后才返回，显示当前同步链无法中断这些调用。没有测试真实 CTP/Win32 卡顿或 provider 行为，也未开放普通 `preflight`。
- **G4 managed SDK 来源：`HOLD_PROVENANCE`。** 来源审计和独立 QA 指出，兼容 gateway 实现来自本地未跟踪源码快照，上游记录的 gitlink 树不含该实现。候选 wheel/installed RECORD/fake consumer 的内部一致性不能把临时快照提升为受信来源 pin，也不能验收 native 生命周期或写入路线。

主树回归和独立 source-only schema QA 已完成；以上结果限于离线/source-only 范围。C01 仍为 `INCOMPLETE`，保持 `NO_WRITE / LIVE_NO_GO`。
