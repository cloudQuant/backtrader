# G1 固定来源 receipt-writer bootstrap 局部复核（2026-09-27）

裁决：`LOCAL_BOOTSTRAP_SLICE_PASS / G1_NOT_PASSED / NO_WRITE / LIVE_NO_GO`。

独立 QA 的干净源码快照 `snapshot-manifest.json` SHA-256 为 `e0f4a0c62dd1e350451457b1ccf7946ecc4d5f77b483f4946d2369d82ea04dad`。root 逐项核验 121 份 `.py` 源码/测试的大小和 SHA-256，确认没有 `.pyc`/cache/config/native/provider 文件，并核验 QA 回执 SHA-256 `bc8b1b9910af581c4f370f72e2bc2763def5197e12a360cef7efaa397f74365a`、pytest 日志 `1a7c60949acf0e1e4239bdd0112ac18a5976cb28d597177fe2835d0d3b785f0e` 与 JUnit `ebfdb76c652b53932893b17c3b700bed01f3fee3b497f77cc1e72a4d4eefb56d`。125 项文件保存在[原始归档](ctp-g1-receipt-bootstrap-r3-independent-review-2026-09-27.raw.zip)，ZIP 完整性和内部摘要复核通过；归档 SHA-256 为 `23ae5c2a208cca0b594d6640f4cb999c7e5ee5bb89a923e1286cc46d49341b90`。

该快照的四文件焦点为 `63 passed / 0 skipped`；内存中重建的固定 bootstrap 为 254,385 bytes、SHA-256 `e65943ab418dfa1fd892f230a977e27ca69ba7ff4662d7c33676257c443112c4`，低于 256 KiB 上限。独立审查覆盖固定派生 receipt 路径、`CREATE_NEW`、关闭执行控制先于回执写入、重复写拒绝、deadline 检查及同源 role 代码按摘要读取。畸形嵌入长度前缀分支只做了静态检查，没有单独运行负探针；作者先前的 62 项报告已由此冻结快照的 63 项记录替代。

这只是 receipt-writer 局部切片。coordinator、两阶段 Job、外层受信宿主、完整 owner token 转移、SCM 部署与真实 CTP native close 均未因此验收；普通 `preflight` 继续 fail-closed。
