# G1 anchor r5 与 Guardian r1/r2 独立审查

**结论：局部测试通过，G1 未通过。** 根代理重新核对 44 项清单哈希和三份独立 JUnit，保留各冻结源码及上下文输入；未重跑这三组测试。

| 冻结切片 | 独立结果 | 接受范围 |
| --- | --- | --- |
| anchor r5 | 68 passed | 固定 cache 前缀推导、保留句柄目录枚举、关闭后拒绝 |
| Guardian r1 | 38 passed | 既有 OS-token 假服务组合；发现两项阻断 |
| Guardian r2 | 39 passed | 新只读 route 的 RevertToSelf 失败后进程终止分支；其他阻断仍在 |

测试均为本机离线/fake 或临时目录机制检查，有已记录的 pytest 配置 warning。r1/r2 的独立运行重建了测试需要的 project layout，服务源码和测试字节与冻结版本一致；初始 flat-layout 调用失败不能算产品失败或通过。归档中的其他脚本是单独记录的测试上下文，不代表已验收完整 runtime 制品。

## Anchor r5

源码 SHA `19fc85e9bc0d82a991efd0f7bfa15cc5bb3388a22c0931b4f2b857a7d4fc9db4`。`pycache_prefix` 只能由验证过的 base root 与固定 `disabled-bytecode-cache` 名称派生；关闭执行 leases 后相关接口拒绝。Windows 临时目录实测先观察该叶路径不存在，再通过同一保留目录句柄观察到它被创建。

该 Windows 测试 stub 了 ACL 检查，未更改 DACL。默认 pins 仍为零；不能由此证明受保护 ProgramData/CPython 分发、runtime manifest-to-worker 整合或真实部署。

## Guardian r1 的阻断与 r2 的限定修复

1. r1/r2 从交互客户端复制 primary token，却用继承的 stdout/NUL 句柄启动 Session 0 服务之外的 worker。Windows 不支持跨 Session 句柄继承，因此普通服务部署不能依赖该路径。[CreateProcessAsUserW 官方合同](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessasuserw)支持这一结论；当前没有执行真实跨 Session 试验。无继承句柄的有界命名管道后续实现仍在开发。
2. r1 把 RevertToSelf 失败作为普通异常捕获后继续处理回执。官方要求失败时关闭进程。[RevertToSelf 官方合同](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-reverttoself)明确了该失败语义。r2 的新 primary-token 路径发出 fatal marker，handler 调用 TerminateProcess，并以 os._exit 作兜底；fake 集成负测证明没有业务 close_execution、receipt 或 response。原生终止 API 未在独立 pytest 进程中执行。

r2 源码 SHA `0307c26a0f88819ff18c5dd82bc26146bb7868318b89691ac643865473d5fdf4`。该修复仍有明确限制：token helper 在抛出 fatal marker 前会关闭其 token 句柄；旧 `_impersonated_pipe_client_sid` 仍抛普通异常，legacy inert 路径可以捕获并返回。因此不能把 r2 记为整个模块的身份恢复处理已关闭。

## 尚未通过的整链条件

服务的同步 anchor/setup 与 receipt I/O 仍未全部纳入外部进程截止控制。客户端等待超时不证明服务已结束或 Job 已清空。独立服务监督每个新请求进程树、受保护 runtime/安装、完整依赖与来源 pin、真实原生关闭均需后续证据。未安装/启动真实 SCM 服务，未访问私有配置、native provider 或交易账户。

[机器可读记录](ctp-g1-anchor-r5-guardian-r1-r2-independent-review-2026-09-26.json)与[原始归档](ctp-g1-anchor-r5-guardian-r1-r2-independent-review-2026-09-26.raw.zip)保存作者/独立日志、JUnit、源码/测试和 review。归档共 63 个条目，SHA-256 `b092e01596cebc9ffcf4b4fd607328796ac761c85b5c9e2ca439bf7e6bbd8fef`。`NO_WRITE / LIVE_NO_GO` 不变。
