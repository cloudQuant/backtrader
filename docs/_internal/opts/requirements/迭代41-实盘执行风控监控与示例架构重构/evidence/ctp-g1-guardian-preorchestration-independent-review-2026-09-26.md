# Guardian 编排前切片：独立复验

**局部 helper 通过，G1 未通过。** 冻结 manifest 为 `9e85f5d9e28f402144251167dd82f350d2a6e75fc827636bdebc5621fb96c06b`。

独立服务测试 **41 passed**，其中 Revert/fail-stop 子集再跑 **7 passed**；parent manifest gate **1 passed**。7 项是 41 项的子集，不能相加为 49 项独立覆盖。根代理核对 16 份源/test/context 文件与 JUnit/日志；未重复运行该组测试。

两个 impersonation helper 现在共用立即终止处理：RevertToSelf 失败后尝试 TerminateProcess，并无条件以 os._exit 兜底；普通 Python catcher 无法继续回执流程。测试以替换的 fatal sink 验证无 cleanup/receipt/response，不在 pytest 中执行真实进程终止。parent 验证固定 worker/bootstrap/dependency helper 清单，旧的 worker-only 兼容形式不被当作新 bootstrap 完整清单。

Ruff check 通过；whole-file format check 仍报告 parent_launcher 和 manifest test 的既有格式差异，原始日志保留。12 份 context 文件单独标记，不宣称它们构成完整统一冻结 runtime。

该快照早于逐请求 Job、coordinator、receipt writer、token-bootstrap 和新的无继承句柄输出通道。没有 SCM 安装、DACL 修改、私有配置访问或 native/provider 请求，也没有 TokenSessionId/SeTcb 的真实部署证据。普通 preflight 和写路由继续关闭。

[机器记录](ctp-g1-guardian-preorchestration-independent-review-2026-09-26.json)与[原始归档](ctp-g1-guardian-preorchestration-independent-review-2026-09-26.raw.zip)保存完整材料。归档 SHA-256 `8dcb2cd084af7cbcb494a583bab4468bfca7dbe23dab9473f96b0813c6158766`，28 项。
