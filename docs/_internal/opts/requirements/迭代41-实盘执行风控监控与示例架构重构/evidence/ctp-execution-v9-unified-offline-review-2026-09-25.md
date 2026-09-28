# CTP execution v9 离线合流复核（2026-09-25）

状态：`LOCAL_OFFLINE_CANDIDATE / CTP_SDK_INTEGRATION_BLOCKED / NO_WRITE`。本记录只覆盖本地 fake、SQLite 和制品来源，不是 SimNow/生产报撤单验收。

`bt_api_execution` 隔离候选位于 `D:/bt_api_execution_codex_v9_unified_offline_20260925`，commit `f4285e7`。它合流 v9 账本、CTP 源回调桥、队列 consumer lease 合同和 OrderRef 持久水位。包级离线测试为 `124 passed, 2 skipped`；定向覆盖 v8→v9 fail-closed 迁移、OrderRef A→B→A 及跨日回退、callback sequence、持久投影、`UNKNOWN`，并以 fake source 测试等待 poll 被 close 唤醒、事件出队后 close 获胜。两个 skipped 用例是需要已安装 `bt_api_ctp.TraderClient` queue-consumer lease 的真实 SDK + fake API 集成探针；当前安装制品不具备该 API，fake bridge 测试不能替代它。

两次从最终候选构建的 wheel 字节相同，SHA-256 为 `a34a3df09cc46a5578ca4ed6eebdfef7632e8f897c790fa41ed7ed1a44782a11`；内嵌 RECORD SHA-256 为 `c469eac4…`，16 行记录覆盖全部 15 个 payload，hash/size 核验通过。11 个 `.py`/`py.typed` 成员与 `f4285e7` 源码逐字节一致。构建产物在 `D:/bt_api_execution_codex_v9_unified_artifacts_20260925`；这些值只可用于离线候选识别，主仓 managed CTP pin/default route 未更新。

独立复核确认两个 P2 仍需在正式集成/发布前处理：桥接既需要 CTP SDK commit `69098921025ceaba57ca4c7cdb660e97bdf94217` 的 callback source event，也需要后续 `232a14dc6e055523a8bb5968238eb0e93126ff94` 的 queue consumer lease。当前 i8 CTP wheel `f354327f…` 不含这些接口，因此不得与本执行 wheel 拼成“已验收三制品”。另，公开的 `CtpOrderRefSeedProof` 从 4 个必填字段收紧到 12 个，旧构造调用将失败；安全合同不能放松，但发布前必须明确迁移/版本决定。

下一门是从精确 queue-lease CTP 源 commit 构建可复现的 cp311 native wheel，核验安装后 RECORD、来源及真实 `TraderClient` + fake API 两项跳过测试。其后仍需主仓桥接、真实回调同源、完整 native close、账户级 writer fence、共同快照、逐动作审批、风险/监控和真实 SimNow 端到端证据。任何本地 queue receipt 都不是 provider ACK；结果不确定时维持 `UNKNOWN` 与停止重派。

**公开 API 版本化后续候选（仍是离线证据）：** 为解决上述 4→12 字段的破坏性构造器变化，从冻结的 `f4285e7` 单独派生 `D:/bt_api_execution_codex_v9_api_compat_20260925` commit `60102bfc493ecc4aa889982d5d8b3a1228e02c92`，把包版本升为 `0.2.0`，增加迁移说明和旧四字段拒绝测试，未放宽 cutover proof。fake package suite 为 `125 passed, 2 skipped`，两个 skip 仍等待 CTP queue-lease wheel。两份 clean archive 独立构建的 `0.2.0` wheel SHA-256 均为 `352c26db7636868710dbe28ea0583f49db619dd06e3b9c1f258b69fe68e51787`；16 行 RECORD 全部通过 hash/size 校验，包源码成员与该 commit 的 archive 逐字节匹配。制品在 `D:/bt_api_execution_codex_v9_api_compat_artifacts_20260925/build-a/` 和 `build-b/`，审计脚本同目录。此版本未发布、未安装到默认 runtime，也没有受审 managed CTP pin；正式消费者仍须同步精确版本和 digest，并补跑两项 SDK 桥接测试。

**队列租约 CTP I9 版本化 wheel（后续离线候选）：** [独立证据页](ctp-i9-queue-lease-wheel-2026-09-25.md)记录 commit `19349b8…` 的 `2.0.4+iteration41.i9` wheel，两份 clean build 字节一致（SHA-256 `7148c4cecc8438426f2ddbe1ee0da0e06d6eb5aa0c699ab901f4cf3e42dc6502`），满足 SDK 总工程 `>=2.0.3,<3.0`。no-system venv 中安装 I9 和冻结 execution `0.1.0` 后，安装来源的队列/回调源 fake 为 `10 passed`，两项真实 `TraderClient` + fake API 桥接为 `2 passed`、无 skip。另经第二人复核 I9 native 输入/RECORD 和 execution `0.2.0` clean wheel；在独立 fresh no-system venv 离线安装 I9 + execution `0.2.0` + base `0.15.5`，`pip check` 与 installed origins 通过，两项真实 `TraderClient` + fake API 桥接 nodeid 均 PASSED、无 skip。此前 `2.0.2` 版本不满足版本门槛的问题在这个**独立候选**中已修正，但 I9 未进入主仓 pin/default route。没有真实 provider callback、完整 native close、账号级 writer fence 或 SimNow 报撤单证据，仍为 `NO_WRITE / LIVE_NO_GO`。
