# G4 CTP Windows wheel 双构建与安装来源复核（2026-09-27）

裁决：`OFFLINE_ARTIFACT_PASS / G4_NATIVE_CLOSE_NOT_ACCEPTED / NO_WRITE / LIVE_NO_GO`。

两个干净的独立 worktree 均位于 SDK commit `9976bcbbbe331ee77e2d90e05da08472259a625a`，root 再查两者 tracked/untracked 状态为空。双构建 wheel 各 5,553,848 bytes、SHA-256 均为 `36e82015c96d11caa9b2c8eb0c1903ac3f4f36405bab5fed46d9a20d2b6fe5da`；root 复核完整字节相等。独立 QA 又核对 86 个成员、两个新建无系统包 venv 中的 88 个带哈希 RECORD 条目、85 个 wheel payload 安装字节、扩展模块及已映射 MD/Trader DLL 路径和摘要；未构造高层客户端或调用 API。独立 QA 回执 SHA-256 为 `236e0f8f2d3865ee692d468d4decea5bc0b704320a24db17e59c90f74ec70f95`，作者回执为 `8d87f4507ff18fe3f7eac0a6eacf5573f759fc6ae6315f3c5cf1484419e81abb`。

root 将两个 wheel、所核对的关键源码、构建日志和独立 QA 证据共 38 项封存于[原始归档](ctp-g4-dual-build-installed-wheel-independent-review-2026-09-27.raw.zip)，ZIP 完整性与内部逐项摘要通过；归档 SHA-256 为 `70d3beb9d143533f734719c49f9bc24d22ec2030a6a36b642211f6f41d98d899`。独立 QA 的最小 venv 用 `--no-deps` 安装，因未补 base 的 17 项依赖而 `pip check` 不通过；作者在另一隔离 venv 以固定本地 wheel 补齐后 `pip check` 通过。两类消费环境的范围分别保留，不能把后者写成独立最小 venv 的结果。

VS 启动脚本报告 `vsdevcmd\ext\Failed` 缺失；追查发现 `vswhere` 先报 Conda 临时目录创建失败，随后仍找到 VS 17.12.3，核心 vcvars、MSVC/SDK、实际编译链接和双 wheel 相同均有记录。该构建可追溯到所记录工具链，但不能称 VS 初始化完全干净。setuptools 另警告 `Py_DEBUG` 未设置；所产 `cp311-cp311-win_amd64` wheel 在测试的 CPython 3.11.5 release 解释器可导入，未推广至 debug 或其他解释器。

这是离线源码、构建与加载来源证据，没有真实 CTP API 对象、登录、Join/Release、线程退出或 provider 会话。G4 仍阻断，普通 preflight/写入/live 继续关闭。
