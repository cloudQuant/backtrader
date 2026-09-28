# G5 V21 安装 wheel 假客户端链复核（2026-09-27）

裁决：`INSTALLED_WHEEL_OFFLINE_SLICE_PASS / G5_BLOCKED / NO_WRITE / LIVE_NO_GO`。

V21 Execution `0.2.0` 隔离 wheel SHA-256 为 `08743c4a1bf978c02c9391a787f692fef8a1d49d3ee34afc602b3c1393ff4f6e`。无系统包继承的 Windows CPython 3.11 venv 中，安装来源/RECORD 核验覆盖 Execution、CTP、parent、base、risk、monitor 及测试依赖；`pip check` 通过，假客户端集成 `45 passed`，仅一项既有 pytest 配置警告。root 独立复核最终回执与其中 30 项制品的大小/SHA-256，将其封存于[原始归档](ctp-g5-v21-installed-wheel-fake-e2e-2026-09-27.raw.zip)；ZIP 完整性和 31 项内部摘要通过，归档 SHA-256 为 `efc264aeed3425f9fd4fe2da6993333eba806591d9be208cab66f7c51c081a47`。最终回执 SHA-256 为 `7d26d498e181a86d5cdf806d4f2781641a9345b894fd31f6b0f342893c3219c0`。root 又在同一 venv 复核 `pip check` 退出 0 和 Execution `0.2.0` 模块来自该 venv 的 `site-packages`。

本机 fake 复现：同一 owner 在原生调用不确定后被 poison，原 CLAIMED/inflight 命令通过 V21 限定补记成为持久 UNKNOWN，重新打开后 family/session 均仍为 POISONED，SQLite integrity/FK 检查通过，假 Req 调用数为零。官方 PyPI 的 cryptography/cffi/pycparser 测试依赖 wheel 与其 JSON 摘要经核验后装入隔离 venv；最初缺 cryptography 的 `38 passed / 7 failed` 和借用全局 Python 的 45 项结果只保留作诊断，不计为最终严格消费结果。

另一个崩溃切点仍失败：在持久 CLAIMED/inflight 后、假 Req 前重启，账本仍是 CLAIMED/inflight、family/session ACTIVE，新 owner 被拒绝，既无可信 OS 进程死亡证明，也无 UNKNOWN 补记。这个 fail-closed 状态阻止重派，但 G5 没有完成。V21 wheel 与不同源码的 R3r2/R3r3 同标 `0.2.0`，只以哈希辨识隔离测试制品，不能作为统一发行。公共 BtApiStore 与默认 CTP 写入路由仍关闭；以上没有真实 SDK/native、provider 或账户写入验收。
