# Iteration 41：G6-S / G6-P 最短剩余关键路径独立审阅

- 审阅时间：2026-09-27（只读）
- 裁决：`DOCUMENT_REVIEW_ONLY / NO_WRITE / SIMNOW_WRITE_NO_GO / PRODUCTION_LIVE_NO_GO`
- 范围：主仓 Iteration 41 当前 CTP 验收矩阵、迭代计划、验收文档、唯一 F14 ADR、截至 2026-09-27 的并行检查点与 G1/G5/G6-P 证据。没有运行测试，没有读取私有配置、凭据或账号数据，没有访问 provider、SDK 会话或网络，也未改主仓。

## 当前状态（按最新证据，不按过期测试数字推断）

1. 当前状态矩阵的分支顺序明确为：共同 G0–G5 后，获批的 SimNow 操作性分支走 G6-S→G7-S；strict F14/production 另需 G6-P，strict SimNow 才走 G7-P，生产走 G8-P。S 的结果不能升格为 P 或生产。矩阵当前裁决仍为 `LOCAL_OFFLINE_CONTRACTS / NO_WRITE / LIVE_NO_GO`。
2. G1 仍关闭。9/27 检查点记载：Windows 惰性 R7/teardown-r2 的 9 场景复放可证明部分 Job containment，但同步 pipe 准入约 1812–1813 ms 越过 1800 ms 上限；overlapped 取消未完成且没有持久 I/O reaper。普通 preflight 仍 fail-closed。不能把 Job empty、父进程/协调器退出或 `stop()` 返回当成原生 `Join/Release` 完成。
3. G4 仍阻断：fake 的阻塞关闭可以被 Job 终止，但这不是同代 native `Join/Release` 正面回执；SDK 关闭调用的同步部分不受既有 timeout 完整约束，供应商生命周期合同未确认。
4. G5 有重要进展，但仍不通过：R3r3+V21 与 V22 均有独立源码 QA；V22 独立 source QA 为 313 passed / 2 native skipped，V20/V21 迁移、UNKNOWN/POISONED 原子性与不重派检查通过。它仍是 `0.2.0` source-only/fake-verifier 候选，V22 UUID 未绑定真实 native-owner 的 Windows process handle/Job、SID 与制品封存；尚无受信外部退出验证器。安装 wheel 探针用的是临时 `0.2.2.dev0+v22...` 身份；未经 native guard 过滤的包测试为 309 passed / 2 failed（两项要求真实 Trader 登录），排除该两项后 309 passed / 2 deselected，不能写成完整未过滤安装验收 PASS。
5. G5/G6 还缺一个共同账本/OrderRef handoff：Store 与独立 execution SQLite 仍存在两个 OrderRef 来源；目前 v1 bridge 先 SDK dispatch 再记 receipt，顺序不满足发送前持久 claim/receipt。受管 submit/cancel 因而仍在分配或派发前硬拒绝。撤单终态风险锁也仍有同权限写者边界：冻结的 parent cancel-control r3 复现另一同用户 SQLite writer 在 monitor 事件精确 readback 后、最终清 risk latch 前删行，释放仍返回成功且双锁清除。root 本轮补报 r4 的 `BEGIN IMMEDIATE`+append-only trigger 可阻普通 DML，但同用户 DDL/数据库文件替换仍绕过；trigger 不是生产写者排他证明。G5/G6 实接线前须以受信单写进程和可核 ACL/文件所有权阻断同权限替换，或把 monitor/risk/ledger 清理纳入同一权威事务；需加入同用户 DDL/替换攻击负测。
6. SimNow 只读门未验收：I11 MD 身份未证实、matching tick/TradingDay 为空且 Join pending；I12 TD 尝试在 artifact/policy 门前拒绝，未观察登录、查询或 close。相关 one-shot markers 已消耗，不能复用或重置；修复后若允许新尝试须新 ID/marker 和独立受监督边界。最近五对 TCP 结果仅为历史传输可达性，不等于账号、会话或交易 readiness。
7. 默认 013_3 仍只有 zero-write `simulation/sandbox`；live profile unavailable。9/27 G6-P/G8-P 路径审计发现外部准入协议/签名收据没有接入共享 runner、Store 或最终 native dispatch；合成有效签名仍在所有副作用之前拒绝，zero dispatch。当前没有受信账户 actor/网关、受信服务 pin、真实生产 session 或 write route。

## 最短剩余关键路径：真实 SimNow 模拟盘（仅操作性例外分支）

此为在账户 owner 愿意接受残余风险、且正式批准 ADR-41-16 option B 的条件下，最短的单笔限量“报一笔仍有可撤余量的限价单→原生确认→精确撤单”路径。它的最终标签最多是 `SIMNOW_OPERATIONAL_ATTESTATION_TESTED`；不通过 strict F14，不解锁 production。

1. **先做正式政策裁决。** ADR-41-16 目前 `PROPOSED`，option A strict F14 是现行 governing decision；option B 未批准、未实现、未登记、不是写授权。账户 owner、execution maintainer、risk owner、独立 QA 须书面批准具名专用模拟账户、主机/用户、窗口、范围/额度、有效期、撤销办法和接受的跨主机/手动写者残余风险；先修改计划、AC 与结果标签，再实现/使用 S 路径。若不批准 B，SimNow 写入也只能走 strict G6-P，不能用 S receipt 代替。
2. **共同前置（本地可以做，但不等同外部证明）。** 关闭 G0 的本地配置/制品/隐私/传输合同；实现、固定来源并独立验收 G1 的整命令 Windows bounded supervisor（一个绝对 deadline 覆盖同步创建/入列、setup、child、receipt、close 和 Job teardown；使用被保留句柄的直接 native-owner 子进程，而非仅由 coordinator 代述）。R7 表明当前同步 IPC 和 overlapped 路径均不满足门槛。
3. **并行完成 G5 与真实只读会话链。** G1 稳定后，一路将 G1 服务创建并持有的 native-owner process/Job 句柄绑定到 Store 的 V22 `process_generation_id`，加服务认证、受信部署 pin、真实 process-exit/Job-empty/control-release 证明；冻结唯一 order authority/cutover，把 Broker、Store、execution ledger、SDK worker、回调与一个持久 command/OrderRef 串起来，实现发送前 reservation/claim/receipt 与 UNKNOWN no-resend，淘汰 dispatch-first v1。单元/fake/隔离 Windows inert 证明不替代 G5 的真实 OS 绑定；不得将 fake verifier 当 Windows 退出证据。
   另一路在 fresh marker 下依次取得实际账号的 G2 TD 七类终态查询/身份/TradingDay/结算确认及 clean close；再取得 G3 MD 登录与身份、精确订阅 ACK、匹配 tick/同交易日证据；G4 对同一 session generation 给出 vendor/API 相符的 Join、Release、callback 静止和 Job 收尾。G3 依赖 G2 成功 close；各阶段要实际 SimNow 账号、凭据、正确 pin 的 SDK 与真实原生会话。
4. **接好独立的 G6-S。** 实现与 strict `CtpF14ExternalAdmissionClaim` 不可互换的操作窗口许可、one-use/expiry/撤销和逐动作审批；在 client 创建至 worker drain、native clean-close、账本关闭期间持续持有本机合作进程 lease；核验真实来源的单流查询、账户/交易日/结算查询；做到同一 OrderRef/command、精准回调关联、风险上限和任何 UNKNOWN 均冻结、不重派。先关闭撤单 control r3/r4 的跨库 readback→清锁竞态：触发器只能防普通 DML，须由受信单写者/可核 ACL 与防同用户文件替换边界保护，或将最终事件记录、risk latch 与 ledger 变更纳入同一权威事务；负测覆盖同权限 DDL/替换。只声明 `UNVERSIONED_QUIESCENCE_CHECK`，明确跨主机 writer 排他与同版本共同快照 `UNPROVEN`。fake/隔离用例和静态无旁路检查先通过，默认 route 仍关闭。
5. **G7-S 单次受控实测。** 上述 G0–G6-S 全部闭合后，在批准的专用账户窗口由具名操作者做一笔不超限、可撤余量订单；精确原生 insert response/order callback 后只撤精确目标，再验证订单终态和资金/全账户订单/成交/持仓变化。无未解释订单/敞口，clean close 后独立 QA 出脱敏回执。任何部分成交须计量并对账；若产生无法由既有受审归零路径处理的持仓，冻结并停止，不能将全成订单伪报为撤单成功。

**S 的外部依赖边界：** 这里不要求一个能证明跨主机排他的 G6-P 服务，但需要真实具名 SimNow 账户、owner 的专用窗口/无“已知”并行写者承诺、实际 TD/MD 会话与 provider/native 回调、可证明的结算/账户查询来源。官方 7x24 API 测试环境被文档记为不提供清算/结算；如果本次配置命中的实际前置也不能返回要求的结算确认，则 G6-S/G7-S 无法按当前条款通过，按 ADR 立即停止零写。不能用 TCP、登录或同值重复 query 补齐。

## 最短剩余关键路径：production 实盘（strict P）

1. **先验证外部可行性，否则立即停止 strict 写入口设计。** 向期货公司/柜台/清算服务或等效受审网关取得正式合同与可部署实现，证明唯一账户写入入口、服务身份/信任根、跨主机 epoch fence、撤销/接管、旁路/人工/旧 credential 拒绝，以及资金/全账户委托/成交/持仓的共同 snapshot revision/完整分页和可信时间。当前审过的公开 CTP API 没有给出这些原语。外部服务如只签 token 而 BT 继续持有 CTP 凭据并直接调用 `ReqOrderInsert/ReqOrderAction`，无法满足 G6-P：claim/fence 检查到 native call 间仍有 TOCTOU，旧 writer 可绕行。
2. **采用真正的单一 account actor。** 外部服务/网关必须独占生产 CTP credentials 与 session，把 BT client 变成经认证 transport 的调用方；服务端在同一串行 dispatch boundary 原子检查 epoch、单次 action、快照 revision、approval、风险额度和 session，然后执行唯一 native call、记录回调并 reconcile UNKNOWN。接入统一持久账本与 G5，并把撤单终态事件读回、风险锁释放和账本 finalization 置于同一可信写者边界/同一权威事务；`BEGIN IMMEDIATE`+append-only trigger 只挡普通 DML，不能抵御同用户 DDL/文件替换，故须有外部 actor/ACL/file custody 与相应负测。配置文件或本地 adapter 不可持有绕过 actor 的另一条 native 写路径。
3. **先闭合共同 G0–G5 及真实会话/关闭。** 建立唯一代码/制品/依赖 pin（包括 Base/CTP/execution/风险/监控以及外部 actor build/source）、安装来源/RECORD、受信 G1 服务和 direct native-owner 进程绑定、G4 clean close、Store/SDK/BT 单一 command/OrderRef、回调认证、崩溃 UNKNOWN 冻结/不重派；用精确生产账户 scope 完成只读身份、TD/MD、TradingDay/结算和 native lifecycle 验收。S 历史/receipt/风险限额/模拟制品均不继承。
4. **完成 G6-P 的部署内证据。** 用两个真实隔离 host/身份、真实账号服务与独立审计日志做同一 epoch 同时 acquire、过期/撤销/epoch 转移、claim→final-dispatch race、快照后的外部 mutation、crash/timeout/callback 丢失、跨主机/旧凭据/手工旁路拒绝。服务需保留最终 dispatch 与 writer 清点事实；签名 observation 或两个本机 fake clients 不够。通过后才可记 G6-P strict。
5. **按当前计划执行 G8-P 与独立生产准入。** 先按外部服务合同完成 G8-P 合成同一受保护 `config.yaml`、同一 runtime/runner identity 的 stop/edit/restart：旧 SimNow permits/claim/session/approval/fence/OrderRef scope 全部在 credentials/SDK/socket/native dispatch 前拒绝，live 新 scope 重新封存。随后独立接受生产制品、真正账号/凭据 custody、session、trusted approval/clock/revocation、risk/monitor、恢复/事故程序与生产 QA；任何一项缺失，live 仍 unavailable/zero-write。

**生产外部依赖边界：** G6-P 的账户服务、服务签名/证书信任根、broker/clearing snapshot 来源、账号全 writer 清点与技术旁路排除不能由主仓本地单测制造，需外部可信主体、实际服务部署/账号/隔离主机提供并经独立核验。主仓可实现 DTO/验证、gateway/BT/Store 接线、默认 fail-closed、fake 负测、合成 G8-P 模式隔离、打包 pin 与报告；不能自证签名者真实、账户快照真实/完整或别的 host 无法写。

## 条款循环与不可同时满足之处

- **验收 DAG 本身无逻辑循环。** 两条可执行路径是 `G0–G1 → (G2→G3→G4 与 G5 并行完成) → G6-S → G7-S`，以及 `G0–G1 → (真实只读 G2→G3→G4 与 G5) → G6-P → G8-P → 独立 production acceptance`。S/P 的分叉和先决关系在 matrix、AC41-37-S/P、F14 计划和 ADR 中一致。
- **政策上有一个未完成的选择，不是隐式豁免。** strict F14 是现状；S 要先批准 option B 并改 AC/标签。未获批不能一边保留 strict F14 条款、一边把 G6-S 当通行证。G7-S 即使成功也不关闭 G6-P。
- **endpoint 条件性不可满足：** 仅官方 7x24 前置且无结算/结算确认能力时，与“真实当前账户/TradingDay settlement confirmation”验收条款不能同时满足；须换到经证实具备该业务的配置前置/服务，或重新正式裁决验收范围。当前 evidence 没有证明任何候选同时具备真实可达、TD/MD、Join/Release 和结算能力。
- **strict P 与“本地直接持有凭据并 native dispatch”组合不可满足。** 仅外部 `assert_active()`/租约/签名收据与本地下一行调用不可能关掉 revocation TOCTOU；须由外部单一 writer actor 实际持有 CTP 凭据/session 并执行 native dispatch，或由外部控制技术性封死一切旁路且在最后调用处原子把关。
- **V22 不是 G5 完成与写入解锁。** source QA 通过、探针 wheel identity、fake verifier 正例均不能同时满足“G1 保留真实 OS 句柄 + G5 一次性可信崩溃证明 + 账户 action 可重派/不可重派”生产要求；旧 CLAIMED/UNKNOWN 仍冻结，实际进程死亡与 provider outcome 分开证明。

## 文档新鲜度与需要同步处

`ctp-current-acceptance-matrix.md` 的状态标题为 2026-09-27，但正文前段仍以 R3r3+V21、G1 r6 为最新；同日较新的 `iteration41-parallel-checkpoint-2026-09-27.md` 已加入 V22 的 313/2、R7/teardown-r2 deadline 拒绝与 G1/G4/G5 更精确阻断。它们不改变 NO-GO，却改变了 G1/G5 当前阻断事实，宜把矩阵相应段落同步到 9/27 checkpoint、V22 独立 source QA 和 V22↔G1 绑定审计。`实施状态与验收快照.md` 标记快照日期 2026-09-25，不能称为 9/27 最新状态。G6-S 源文件/接口合同已存在不等于 ADR option B 已批准或完整 G6-S 接线/真实准入；措辞应保持“非授权候选/未准入”。本回执同时纳入 root 2026-09-27 同轮补充：parent r4 的 `BEGIN IMMEDIATE`+append-only trigger 当前只确认可拦普通 DML；本主仓未发现对应 r4 冻结独立 evidence 文件/摘要，故按提供方补充记载，不伪称本次 hash 独立复核。r3 独立复核文件摘要已列于表。

## 审阅输入及冻结摘要

本回执依据下列只读输入；SHA-256 用于固定本次文档版本，不表示这些文档的每项声明均被我复测。

| 文件 | SHA-256 |
| --- | --- |
| `ctp-current-acceptance-matrix.md` | `f2482383f83ab80c9de530d32c3ca96db858d609ba15f742aa8bb0840390f07f` |
| `迭代计划.md` | `ff671343193f812349d99eb81ec168f91a2a8e3f184be4bbeb8191df4a0c4e94` |
| `验收文档.md` | `16b574cdb825ec8b167b9dabab7e71915dd8ffdfaf3580eec0e23bc071c63614` |
| `实施状态与验收快照.md` | `3fbadb502d1963c2a98695d8763c75e2fc05717a54a8306f459265b177545238` |
| `ADR-41-16-simnow-f14-writer-fence-proposal.md` | `376e299ea9939a904eb5c9b725bc03880b0058ce35153e0a12e972916ebed08d` |
| `evidence/iteration41-parallel-checkpoint-2026-09-27.md` | `2cdf5b019c4fe9dbfc5764cc5e771f8e2efa94f74f29a4a509fe98583b8a8e1d` |
| `evidence/ctp-f14-two-level-acceptance-review-2026-09-25.md` | `80bdaa0c5886f34f8739a32a4b4f0f47e99d24b30fc02e140319130154640f70` |
| `evidence/ctp-g6p-g8p-external-account-control-service-contract-review-2026-09-26.md` | `400d067c79dba35f1f7030f5b71ee8611429ee417171c1631edf7e3852d01c11` |
| `evidence/ctp-g6p-g8p-production-path-audit-2026-09-27.md` | `b8a112df25b90a3fb6b562b0324484c878fa6559b6edfc552bd5c8c376979f33` |
| `evidence/ctp-g5-v22-independent-source-qa-2026-09-27.md` | `ad9d9944f5d89e38355357ae745d6685126b8a6cc0fd3d14fa98b7f10b88c31c` |
| `evidence/ctp-g5-v22-installed-wheel-independent-review-2026-09-27.md` | `b3f768088820f17a308040ebd23750b1b1e5726470cd0ae9402784efd73efac3` |
| `evidence/ctp-g5-v22-g1-process-binding-design-audit-2026-09-27.md` | `9f61488fc82e5d6ab2902df8bb459c1a0f701f9dc3b348d54ab1a1b279f19219` |
| `evidence/ctp-g1-r7-windows-inert-independent-qa-2026-09-27.md` | `d9e547de5920c4fca3e55f4b3e83da6ad518d6bfd048d030b00fdf07e0718d5e` |
| `evidence/ctp-parent-cancel-control-r3-independent-review-2026-09-27.md` | `d863e85608d60131b34e7baa18eb68a6a142974f85e0358cb858c89e70e1bcc3` |

最短结论：**SimNow 先拿到 ADR-41-16 B 的正式决定；然后并行收敛 G1/G5 与真实 G2→G3→G4，之后 G6-S、G7-S。production 必须先取得真正 G6-P 外部单一账户 actor 与同版本完整快照，再完成共同 G0–G5、G6-P、G8-P 和独立生产准入。两条路线当前都在 G1/G4/G5 前置阻断；P 另有尚未发现/接入的外部账户服务；官方 7x24 条件下 settlement 条款可能使 S/G7-S 无法完成。默认继续零写，绝不推定可下单。**

