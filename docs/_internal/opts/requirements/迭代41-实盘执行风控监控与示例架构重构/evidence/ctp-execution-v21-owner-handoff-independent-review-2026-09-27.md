# Execution V21 单账户交接与 POISONED UNKNOWN 补记独立复核（2026-09-27）

裁决：`LOCAL_OFFLINE_CONTRACT_PASS / G5_BLOCKED / NO_WRITE / LIVE_NO_GO`。

V21 冻结 `SOURCE-MANIFEST.json` SHA-256 为 `b3a614d62b2a4cf1b0dbdfefee463015157dee38bf4c9c5119c64ef2d71d6d24`。独立 QA 对 32 份源码/测试逐项复核哈希，确认冻结与 QA 副本一致且无 `.pyc`；QA JSON 回执 SHA-256 为 `4f788226e2f47c91b076c6a507ec4f4604f58bfdb94e4051289a89c9d3d26b51`。root 又按冻结 manifest 核验 32 项，并将源码、QA-only 测试、回执、日志、JUnit 与数据库摘要收据共 45 项封存于[原始归档](ctp-execution-v21-owner-handoff-independent-review-2026-09-27.raw.zip)。ZIP 完整性与内部逐项摘要通过；归档 SHA-256 为 `e5e80cc3c9cc9ea7f66a3a7b090b51e15928ea41c1881c179d41d5ba08893847`。

独立 QA 聚焦 10 项通过，完整包 `271 passed / 2 skipped`；root 在 QA 副本重新运行相同三文件聚焦集，`10 passed in 1.48s`。负测覆盖丢失交接返回后的精确幂等读回、旧代次写入拒绝、错误 family/lease/session/目标拒绝，以及注入 SQLite 中断后仍保持 CLAIMED/inflight、仅原 owner 的精确 UNKNOWN 回执可一次性补记。重新打开账本后 UNKNOWN 和账户 poison 仍阻止新 owner/保留号。

QA JSON/Markdown 中新增测试的 SHA-256 抄录有误：文件在聚焦测试前已固定，root 两次计算其实际 SHA-256 为 `7cabf2cb3e0c76239fcdfe7a6436debec045e24409a4db38c4ca770bf2be2b4d`；归档用此实际值，原回执按原字节保留。[独立勘误](ctp-execution-v21-owner-handoff-independent-review-2026-09-27-correction.json)的 SHA-256 为 `bf9e0f6bb087901d38fc8f8bd7faacda9afea53d0c4cff11ba346660802861db`，它是哈希绑定说明，不是密码学签名。该文字错误不改变 32 份产品 payload 的 manifest 复核或 root 聚焦结果。

本证据只覆盖合成 SQLite 和 fake close/drain verifier。没有真实 native Join/Release、OS 进程死亡证明、受信 callback drain、provider 会话或交易。V21 `0.2.0` 仍是隔离源码候选；与 R3r3 同标不同源，不能直接发行同版本 wheel。崩溃时的 ACTIVE/CLAIMED 恢复仍受[源码映射审计](ctp-g5-v21-process-recovery-mapping-audit-2026-09-27.md)阻断。
