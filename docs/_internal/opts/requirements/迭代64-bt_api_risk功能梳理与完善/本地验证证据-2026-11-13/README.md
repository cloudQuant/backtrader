# 迭代 64 本地验证证据（2026-11-13）

本目录保存七份合成测试原始日志的逐字节副本。PASS 与 FAIL 仅适用于所列测试范围，不证明生产、真实账户、可信来源或整期验收；整期仍为 **IN_PROGRESS / NO-GO**。WIP 文件清单只固定所列文件，不能推断未列依赖或未记录的 commit。

详细上下文见[开发验收状态矩阵](../开发验收状态矩阵.md)及 [Audit 与 Policy 证据快照](../Audit与Policy修复证据快照-2026-11-13.md)。

下列 SHA-256 为复制前来源与复制后本地文件分别计算并一致的值。源日志及指定文件 hash 清单均位于 `/tmp`，可能被清理；本目录仅复制七份日志，未复制清单。清单不是完整构建或依赖清单。

## [bt-postsave-280-passed.log](bt-postsave-280-passed.log)

- 状态：**PASS（UNIT/FAKE / WIP）**。280 passed / 1 warning；BT 真实 Broker + 临时 host、指定 fake 写端口；不证明真实重启、任意写端口或账户。SDK/BT/host 为当时未提交 WIP，日志未完整固定仓库 commit。
- 原始来源：`/tmp/iter64-bt-postsave-writes.LA7Mrv/pytest.log`
- 来源与本地副本 SHA-256：`350230a4f8313a55f641c8140b1da76e01c1ce6b8d1ebb07ba65f759a84a5b48`
- 运行时选定文件哈希清单来源：`/tmp/iter64-bt-postsave-writes.LA7Mrv/before.sha256、after.sha256（36 个选定文件）`

## [unknown-bounded-385-passed.log](unknown-bounded-385-passed.log)

- 状态：**PASS（UNIT/FAKE / WIP）**。385 passed / 1 warning；修订后当时 SDK/Risk UNKNOWN 有界读取跨组件 fake 快照，代码未提交；不证明真实账户、来源或完整生产传输。日志未完整固定仓库 commit。
- 原始来源：`/tmp/iter64-unknown-pinned.I0YDuY/pytest.log`
- 来源与本地副本 SHA-256：`a0a77607722941b2364cda106ca5590c173259c5cc7863b40d28b2f4954ba8be`
- 运行时选定文件哈希清单来源：`/tmp/iter64-unknown-pinned.I0YDuY/before.sha256、after.sha256（14 个选定文件）`

## [sdk-regression-277-pass-11-fail.log](sdk-regression-277-pass-11-fail.log)

- 状态：**FAIL（UNIT/FAKE / WIP）**。277 passed / 11 failed / 2 deselected / 1 warning，rc 1；SDK 当时未提交 WIP、本地 fake 和临时 SQLite。两项随后单独补跑，不能把本批次改为通过；首错之外后续逻辑未证明。日志未完整固定仓库 commit。
- 原始来源：`/tmp/iter64-sdk-regression.BqPcnAWD/pytest.log`
- 来源与本地副本 SHA-256：`a617302546fb13328e4f06fc7dddefba5fb2f6bd71696836ee6f8c7f15e235f7`
- 运行时选定文件哈希清单来源：`/tmp/iter64-sdk-regression.BqPcnAWD/before.sha256、after.sha256（33 个选定文件）；命令 run.zsh`

## [sdk-concurrency-two-nodes-passed.log](sdk-concurrency-two-nodes-passed.log)

- 状态：**PASS（UNIT/FAKE / WIP）**。先前 deselected 的 dispatch / release 两参数独立补跑 2 passed / 1 warning；只同步开始，不能证明所有锁交错、真实来源或账户。进程清理核查限原 PGID 和记录 PID，非整个 SID。日志未完整固定仓库 commit。
- 原始来源：`/tmp/iter64-concurrency-bounded.sjamW829/pytest.log`
- 来源与本地副本 SHA-256：`90a693b703a74bcbc3e7ee78f6f197a2d250db245ba69542c090fe847501487c`
- 运行时选定文件哈希清单来源：`/tmp/iter64-concurrency-bounded.sjamW829/before.sha256、after.sha256（36 个选定文件）；原 proof.json 保留 INCOMPLETE，事后 verified-proof.json 修正节点解析`

## [web-clean-admin-passed.log](web-clean-admin-passed.log)

- 状态：**PASS（INTEGRATION_SIM）**。1 passed / 3 warnings；提交前 clean SDK adef9b4a / Risk fa2243a archive 的本地 HTTP、CURVE、Registry、Risk 和 fake Gateway 通用运营切片；非真实浏览器、账户或 provider，未断言拒绝审计。
- 原始来源：`/tmp/iter64-web-split.Vt6fcD/clean-admin.log`
- 来源与本地副本 SHA-256：`0d383fae55f4f9c01af776ec2531dcacb0f58ffdb40716855f83bfdc060f9025`
- 运行时选定文件哈希清单来源：`/tmp/iter64-web-split.Vt6fcD/clean-before.sha256、clean-after.sha256（11 个选定文件）`

## [web-clean-source-gate-failed.log](web-clean-source-gate-failed.log)

- 状态：**FAIL（INTEGRATION_SIM）**。1 failed / 1 warning；同一提交前 clean SDK adef9b4a / Risk fa2243a archive 的严格来源测试，available 实际 true 与预期 false 不符；后续步骤未运行。仅为本地 fake 环境。
- 原始来源：`/tmp/iter64-web-split.Vt6fcD/clean-gate.log`
- 来源与本地副本 SHA-256：`f5d4d5822c7f1c08bda177d65ffb5e7688289843e4103b31b8b7676ed979f419`
- 运行时选定文件哈希清单来源：`/tmp/iter64-web-split.Vt6fcD/clean-before.sha256、clean-after.sha256（11 个选定文件）`

## [sdk-lock-contention-two-passed.log](sdk-lock-contention-two-passed.log)

- 状态：**PASS（UNIT/FAKE / WIP）**。2 passed / 1 warning；当时未提交 SDK WIP 的原锁竞争观察，B 在 _check 处非阻塞探测失败，不证明 B 已进入 blocking acquire 或全部调度。清理范围限原 PGID 和记录 PID；其他平台、异常路径未验。日志未完整固定仓库 commit。
- 原始来源：`/tmp/iter64-lock-portable.FqnVhZyO/pytest.log`
- 来源与本地副本 SHA-256：`ce7bc142657487aea005dd1caacf133fe74051283452cc7bc54212b1a091a505`
- 运行时选定文件哈希清单来源：`/tmp/iter64-lock-portable.FqnVhZyO/before.sha256、after.sha256（37 个选定文件）`

## 验证限制

- 七份副本均与本次读取的源字节一致；复制前对常见私密密钥格式进行了有限模式扫描，未发现匹配。此扫描不能证明不存在所有敏感内容。
- 未重跑这些测试；其他平台和 Windows PowerShell 5.1 默认读取为 **NOT_RUN**。本 README 使用 UTF-8 BOM、严格 UTF-8 解码且无替换符。
