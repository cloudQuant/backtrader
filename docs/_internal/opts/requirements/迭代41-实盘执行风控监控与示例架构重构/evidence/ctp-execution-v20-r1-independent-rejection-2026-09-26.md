# V20 r1：独立验收拒绝

**V20 r1 未接受。** 独立三文件焦点 39 项通过，但公开 Store API 的单账户绑定缺口仍可复现。作者全包 256 passed / 2 skipped 仅为该修订作者结果。

## 阻断反例

真实 `open_ctp_account_store(path, scope_A)` 创建绑定账户 A 的临时 SQLite Store。`read_ctp_account_store_identity(scope_B)` 拒绝，但同一返回实例继续接受 B 的 family owner、writer lease、callback session owner 和 submit claim。B 的指令变为 `DISPATCHING`，A 的持久 identity 仍可读。provider/native 调用数均为零。

这是普通公开 API 接线错误即可到达的状态，不能以不防御敌意 Python 为理由排除。修复须在持久事务内把所有相关 scope-bearing 操作约束到已绑定账户，且打开旧的 V20 混合历史时拒绝。r1 不改，r2 另行开发和复验。

## 已通过的限定检查

独立复核覆盖同名错误 trigger/index、增加 identity column、准确的空 orders-only legacy 兼容、畸形/非空 legacy 拒绝、真实 V18 数据库在 DDL 前拒绝。根代理另对先前 r0 错误 trigger 库执行 r1 inspect/open，两者均拒绝，数据库 SHA 保持 `b49a5807768f7b808e7dc0b1ed0141a87e8d66ae0378b8cc53f42b8b80e57181`。

WAL-mode 只读检查可能创建空 WAL/SHM；本证据不声称完全零文件系统写，也不提供恶意文件替换或 clone 的隔离证明。clean-close/restart、主仓公开工厂、统一 wheel 及真实交易均不在此通过范围。

根代理重新核对 29 份源码/test 和 68 份 QA 材料；[机器记录](ctp-execution-v20-r1-independent-rejection-2026-09-26.json)与[原始归档](ctp-execution-v20-r1-independent-rejection-2026-09-26.raw.zip)保存冻结源码、脚本、合成库、日志和报告。归档 SHA-256 `43bc25d47c4611876597fed9c0b8f72c042743e2e96f58b1b6519addaf125ff5`，共 101 项。`NO_WRITE / LIVE_NO_GO` 不变。
