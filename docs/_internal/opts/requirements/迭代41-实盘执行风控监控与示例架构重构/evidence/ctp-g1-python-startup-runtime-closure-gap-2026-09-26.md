# G1 启动前 Python 分发信任缺口（2026-09-26）

**本机 Anaconda 不能作为已接受的 guardian/worker runtime 根。** 只读检查确认 Python 3.11.5 的 base 为 `C:\anaconda3`；base、Lib/encodings、DLLs、Library/bin 及关键解释器文件有 BUILTIN\Users FullControl。这意味着固定 venv exe 的 hash 不能证明 base Python DLL、启动编码模块或 stdlib 字节不被用户修改。

本机 `-I -S -B` 在 bootstrap 之前已经加载 encodings；`-B` 不禁止读取存在的 pyc。sanitized PATH 也不会改变 venv 绑定的 base runtime。`python311.zip` 当前缺失，但启动搜索路径包含其位置；需要保护父目录并把缺失状态写入 manifest，不能允许运行时插入新 archive。

正在实现的闭合方式是：由外部受信的 guardian 在 CreateProcess 前核对固定 CPython 分发 manifest、必要 base/venv exe、Python DLL、stdlib/启动缓存、非系统 native 依赖和精确目录清单，保护所有可搜索路径及其祖先，并保留身份/权限句柄直到 Job empty。System32、KnownDLLs/SxS 属 Windows OS 信任边界，不扫描整个系统。静态 PE imports 或 suspended process 模块枚举只作交叉检查，无法单独证明未来动态 LoadLibrary。

DLL 搜索包含应用目录、系统目录及可能的 cwd/PATH，传递依赖也按模块名解析，因此固定受保护 cwd、受限环境与精确搜索目录清单是必要的部署条件。[Microsoft DLL 搜索顺序](https://learn.microsoft.com/en-us/windows/win32/dlls/dynamic-link-library-search-order)

这些仍是设计和本机只读事实；没有调整 ACL、安装服务、启用源码 pin、读取 ProgramData/私有配置或运行真实 SDK。service host 自身需要代码外受保护的安装信任根，不能以已运行 Python 的自校验替代。默认部署保持关闭。

## Registry 路径疑点的范围更正

Windows 通用文档关于 registry application paths 的描述不能直接当作本次 `-I` 存在漏洞的证明。根代理查阅精确 CPython 3.11.5 源码：registry 路径分支受 `use_environment` 条件限制，isolated 初始化将其设为 0。因此标准该版本的 `-I` 路径应跳过这一分支；固定 Anaconda binary 的对应实现仍需独立核对，不因一般文档增加未证实的 registry 绕过结论。[3.11.5 getpath.py](https://github.com/python/cpython/blob/v3.11.5/Modules/getpath.py#L602)、[3.11.5 initconfig.c](https://github.com/python/cpython/blob/v3.11.5/Python/initconfig.c#L2763)

随后根代理通过本机 `_testinternalcapi.get_getpath_codeobject()` 的只读反汇编确认：Anaconda frozen getpath 在 offset 4304/4308 读取 `use_environment` 并在 false 时跳过 registry 分支，之后另有 Conda 变量条件；实际 `-I -S -B` 的 `ignore_environment=1`、`isolated=1`。此疑点已收敛，不为这一路径增加注册表写入试验或新的部署规则。[本机 flags、DLL 哈希及 bytecode 回执](ctp-g1-frozen-getpath-registry-check-2026-09-26.json)

## 原始证据

[有限文件哈希与只读 ACL 回执](ctp-g1-python-startup-runtime-closure-gap-2026-09-26.json)，原始 SHA-256 `91af79b114400e1a7b4ab87d244a5fae36539be35cbb9b7543d5e28ef0a4b02e`。根代理核对 JSON 与摘要，未重复执行主机权限盘点。
