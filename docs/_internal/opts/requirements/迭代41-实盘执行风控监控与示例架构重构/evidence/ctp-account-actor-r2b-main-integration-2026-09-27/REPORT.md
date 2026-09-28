# BtApiStore Actor r2b 主树集成回归：拒绝合入

状态：`R2B_MAIN_MERGE_REJECTED / NO_WRITE / LIVE_NO_GO`。本记录只涉及本地测试；没有安排真实账户、provider 会话或交易验收，测试本身也不构成外部写入审计。

## 精确输入与操作

- 主树原 `backtrader/stores/btapistore.py` SHA-256：`DBA2989252DB76FE010FBEE7CAACDCDBA34A9B951E3702724156482B67FAE826`。
- [r2b 作者冻结补丁](../ctp-account-actor-main-store-wiring-r2b-2026-09-27/payload/patches/r2b-main-base-apply.patch) SHA-256：`1A16AADB94EDB99924553D6472BF72DCB02BD04C7F994276816D91991A729F37`。在主树执行 `git apply --check` 后精确应用；补丁后 Store SHA-256 为 `24F8199E199BBE84BBB113C3EDBBEE9E71D4736FDD8573297E24EAD3298F2518`。
- 测试命令：`python -m pytest -p no:asyncio tests/unit/stores tests/unit/runtime -q --tb=no --junitxml=...`。未以隔离候选中仅有的 55 个测试替代主树测试。
- 出现回归后执行同一补丁的 `git apply --reverse --check` 与 `git apply --reverse`；Store SHA-256 恢复原值。新 ActorPort 与候选专用测试由该补丁精确撤回；预先存在的 Store/test 改动没有用 `git restore` 或清理命令覆盖。

## 结果

| 工作树 | JUnit cases | 结果 | 原始记录 |
| --- | ---: | --- | --- |
| r2b 补丁应用后的主树 | 2706 | **258 failed**, 2403 passed, 43 skipped, 2 xfailed，1 条既有 pytest 配置 warning；81.95 秒 | [JUnit](patched-main-junit.xml) · [pytest](patched-main-pytest.txt) |
| 精确撤回后的主树 | 2681 | **2636 passed**, 43 skipped, 2 xfailed，1 条既有 pytest 配置 warning；90.02 秒 | [JUnit](reverted-main-junit.xml) · [pytest](reverted-main-pytest.txt) |

两个 JUnit 的 nodeid 集合比较：补丁版增加 46 个候选测试并替换 21 个旧测试，净增 25；46 个新增测试均通过，258 个失败均来自原有 nodeid。失败按文件分布：`test_btapistore_iteration22.py` 200、`test_ctp_managed_projection_bridge.py` 18、`test_btapistore.py` 14、`test_btapistore_normalized.py` 10、`test_btapistore_execution_evidence.py` 7、`test_btapistore_entry_approval_arm.py` 5、`test_credential_safety.py` 3、`test_iteration41_sa_ctp_replay_runtime.py` 1。[独立失败分组](../ctp-account-actor-main-store-wiring-r2b-independent-qa-2026-09-27/MAIN-TREE-AMENDMENT.md)确认其中至少 5 项通用 `btapi`/`outer` 路由、3 项非 CTP placeholder 异常合同和 1 项 013_3 零写回放属于直接兼容回归；其余大多被过早的 CTP 构造门截断。不能把 258 项笼统视为已授权的合同迁移。

## 裁决与下一步

隔离 55 项和路由变异负测支持 r2b 局部 fail-close 行为，却不能证明主树兼容。当前 **不合入 r2b**，不通过 skip/xfail、删旧测试或恢复 CTP 直达写入口消除回归。须逐类分清只读/回放/非 CTP 兼容行为与原先 CTP direct 写入正向断言；前者修复实现，后者在受信外部账户 Actor、同一账本和 per-action 授权可验前保持拒绝，并迁移为明确的拒绝合同/未来 Actor 验收项。重新申请合入时复跑完整 Store/Runtime，以及受影响集成与策略回归。

本结果撤销了仅基于隔离 55 项测试作出的 `SAFE_TO_MERGE_FAIL_CLOSED` 建议。它不改变默认 013_3 零写配置、普通 native `preflight` 的 fail-close、live unavailable 或 G6-P/F14 的关闭状态。

## 原始文件 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `patched-main-junit.xml` | `6500223FE55136907A178996E3F0D5BE6DA71DD758B501BFEB9E232949B0EFFE` |
| `patched-main-pytest.txt` | `08871BE79BE93FC5E77509070EB9E64CAA28A62650DF4591D0B5C355B02B8761` |
| `reverted-main-junit.xml` | `35D8D144E8788BA0314CAA4601077209F5F7EB55FB15CD0C49F3DE33595076FF` |
| `reverted-main-pytest.txt` | `FBEF36C0AA126DAE38D13BAB7CF0B67301FDB235E8374A044D93DBEBA15BBADE` |
