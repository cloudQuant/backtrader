# G5 崩溃后 CLAIMED 补记：独立模型审查（2026-09-27）

裁决：`LOCAL_MODEL_PASS / G5_BLOCKED / NO_WRITE / LIVE_NO_GO`。

本次仅审查单独的 Python/SQLite 假模型。候选 r1 的 `manifest.json` SHA-256 为 `f6f3afa6454150e92be116f499d088be6e68789d832f70c26f525eb98c58d971`；独立 QA 回执 SHA-256 为 `bf00efe6bce03034825bd992be8a4ad45cf05e0c1741cb5438ec330b01b163f3`。root 逐份核验候选 manifest 和 QA 回执后，将 14 个源、测试、反例和回执文件封存于 [原始归档](ctp-g5-crash-recovery-model-r1-independent-review-2026-09-27.raw.zip)，归档 SHA-256 为 `c1c73c1f9694fb70c41e4ce6f9c8a0a2b68a5d72b97d26fe94d902d425d69884`，ZIP 完整性和内部逐项哈希复核通过。

r0 被独立负测拒绝：持久 session 的 `process_generation_id` 与 family 代次不同时，旧模型仍将 `CLAIMED/native_call_inflight=1` 改为 `UNKNOWN/0`，并 poison 两个 owner；r0 拒绝回执 SHA-256 为 `ad162c861a034428e722d61516c6175b891fb5284d70859b5f37c6daa43be75d`。r1 在同一变异上抛出 `RecoveryBlocked`，command、owner 与 recovery 行均未变化；其 9 项模型测试和 Ruff 通过。两次结果及 r0 源/测试哈希都在归档中。

该模型要求外部受信进程退出、绑定同一 family/session/process generation 的 Job 清空和控制权释放证明，才允许在一个 SQLite 事务中把确切 in-flight CLAIMED 改为 UNKNOWN 并 poison owner。真实监督器证明、Execution Store 接线、SCM/Windows Job、原生 SDK 与 provider 行为均未实现或验收。旧 fake 记录中 `native_order_calls=[]` 只证明该测试客户端未发送，不能推断真实进程在崩溃前没有调用 Req。因此不得重派，不得据此打开 SimNow 或 production 写入。
