# CTP 单一 worker / outbox 离线候选（2026-09-25）

**2026-09-26 后续修正：** 隔离候选在原提交基础上产生 source-only commit `b676fe666de5373c58ff59bc0b856b7f6d4ce7fd`。没有可信的原生 no-send/no-callback verifier，因此任何 claim 后 sender 返回 `REJECTED`（即使 payload 自称无发送/无回调）都持久化为固定脱敏 `UNKNOWN`，再次调用只读回原投影、不重发。只有 sender 调用前已经落盘的 `queued=false` 本地队列拒绝可记 `LOCAL_REJECTED`。完整 SDK suite `133 passed, 2 skipped`，Ruff、格式、编译和差异检查通过；没有 wheel、pin、provider 或默认路由。下述 `4f9fdd4` 与 `131/2` 为初版历史证据。

`bt_api_execution` 的隔离 source-only 候选位于 `D:\bt_api_execution_codex_i9_single_worker_20260926`，分支 `codex/ctp-i9-single-worker-projection`，提交 `4f9fdd4125c4e0b3485338f2d501d0b88ea06a44`，以 `60102bfc493ecc4aa889982d5d8b3a1228e02c92` 为基点。提交仅涉及 `store.py`、新增 `ctp_single_worker_candidate.py` 和两份 fake 测试；工作树提交后干净。没有 wheel、制品 pin、默认路由、native sender 或 provider 调用。

候选在独立执行库的同一个 SQLite `ctp_dispatch_commands` 行内新增版本 10 的 `local_queue_receipt_id` 和一次性队列状态。`stage_prepared_dispatch` 必须从该库已提交的 OrderRef reservation 读回完整、相同的请求范围；队列回执在 claim 前精确持久化；`dispatch_managed_command` 仅在同一行完成 READY→CLAIMED 后调用一次注入的 fake sender。重放、并发重复、伪造 reservation/request/ref、队列拒绝和 sender 异常分别保留零重派或 `UNKNOWN` 结果。该合同不把本地 `QUEUED` 当作 CTP ACK。

候选聚焦测试 `73 passed`；同一工作树全 SDK 测试 `131 passed, 2 skipped`。`compileall`/`py_compile`、适用 Ruff、格式检查和 `git diff --check` 通过。共享 Python 环境的 `pip check` 有已存在的无关依赖冲突；本候选项目声明运行时依赖为空，且没有构建/安装新的 wheel，因此这里不作隔离安装验收结论。

**跨包硬阻断：** 当前 Backtrader Store 的 `_sdk_order_request()` 通过 `bt_api_py` 另一套持久来源分配/核验 12 位 OrderRef，而本候选要求 `bt_api_execution` 同一 SQLite 中的已提交 reservation。两者没有共同 reservation port、原子事务或可验证的外部预约证明。把一个库的 ref 导入另一个库会造成第二权威；另行分配则可能发送与账本不同的 ref。主仓在统一预约来源之前必须于 Store/SDK allocator 和队列/native sender 前拒绝 managed CTP 写入。此候选仅缩小 [G5/G6](../ctp-current-acceptance-matrix.md) 的本地合同缺口，不证明真实报单、撤单、账户 fence、回调来源或生产准入。
