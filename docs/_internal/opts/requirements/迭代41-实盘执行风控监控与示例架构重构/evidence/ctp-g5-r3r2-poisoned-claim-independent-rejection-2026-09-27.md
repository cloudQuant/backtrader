# G5 R3r2 POISONED 后 CLAIMED 未写 UNKNOWN 的独立反例

**拒绝当前 G5 显式终态账本验收：**普通统一 wheel 下，五项定向元数据/假 Store→SDK 用例通过；更宽组合保留 `27 passed / 18 failed`。独立新库复现了 claim 后的合成最终准入拒绝：零原生 Req，回开后同一命令仍是 `CLAIMED / native_call_inflight=1 / unknown_reason=NULL`；callback owner 与 account-family owner 均 POISONED，新 owner 被拒绝。SQLite 完整性正常。

旧命令仍不可重派，缺口是显式持久 UNKNOWN 与审计回执；V21 专用 poisoned finalizer 尚待实现和复测。原作者 JSON 的 Execution wheel 摘要末尾多一字符；保留原件并以 v2 勘误和统一消费者归档核对正确字节。所有操作为假客户端、原生扩展阻断，不能据此升级 G5 或真实交易。默认 `NO_WRITE / LIVE_NO_GO` 不变。

[机器记录](ctp-g5-r3r2-poisoned-claim-independent-rejection-2026-09-27.json)与[原始归档](ctp-g5-r3r2-poisoned-claim-independent-rejection-2026-09-27.raw.zip)含安装 wheel、源码、两次 SQLite、日志和独立核验；归档 SHA-256 `b5c086833dcbf2bb717b8dff6122dc88de1f3c35bef30bbe2b861061ca182fbb`，共 24 项。
