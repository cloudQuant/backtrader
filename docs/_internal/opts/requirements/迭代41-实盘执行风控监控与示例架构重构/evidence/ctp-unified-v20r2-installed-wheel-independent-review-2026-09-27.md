# v20r2 普通统一 wheel 消费：独立验收

在新建、无 system-site-packages 的隔离 venv，六个应用 wheel 与 43 个依赖 wheel 离线安装；`pip check` 通过，51 个 distribution、9,077 条带哈希的安装 RECORD、49 个 Processing wheel 与清单一致，六个顶层导入来源/版本落在该 venv。六个应用 wheel 原始字节收入归档。V20r2 第一版独立回执误把单一 venv `site-packages` 误记为启用 system-site；旧回执保留，新 v3 按 `pyvenv.cfg` 证实 `false`。

两版 Execution wheel 均标 `0.2.0`，但哈希不同；最终部署前必须有唯一版本/制品 pin。本项不证明 sealed G1 capsule、native `_ctp`、受保护部署、managed E2E 或真实账号。

[机器记录](ctp-unified-v20r2-installed-wheel-independent-review-2026-09-27.json)与[原始归档](ctp-unified-v20r2-installed-wheel-independent-review-2026-09-27.raw.zip) SHA-256 `a1a89f5ef96e1229eb4b98206c2ca1ced8c4ac17598642b118c159c6b23a4f81`，34 项。
