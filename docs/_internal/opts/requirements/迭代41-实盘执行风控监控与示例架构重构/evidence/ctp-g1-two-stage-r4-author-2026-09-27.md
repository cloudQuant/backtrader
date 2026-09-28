# G1 two-stage r4 候选说明（作者摘要）

日期：2026-09-27  
冻结候选 manifest SHA-256：`805d066b74ec7eee0519993395d2078605ef46fbe2b1a2e63ff11aafd82dc4a1`。本页概述冻结候选的作者 README，不修改冻结目录。

R4 以 R3 的冻结清单为基础。构建器对六个固定嵌入式 Python support 文件执行 `ast.parse(type_comments=True)` 与 `ast.unparse`，重新解析并要求 AST（含 type comments）相等，再编译变换后的源码。产物嵌入源文本，不嵌入 code object 或 bytecode。schema-3 support header 记录原始源文件和变换后执行文本的尺寸与 SHA；child startup 会将原始摘要与 sealed source manifest 比较，并在 compile/exec 前核验变换文本摘要。作者候选称相较 R3 减少 4,802 bytes，保持 256 KiB 上限。

作者记录：CPython 3.11.5、`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 下相关集 85 项通过，py_compile/import-sort 检查通过；全量 Ruff 有 10 项继承问题，format check 受既有整文件格式漂移影响。独立复核的精确结果、逐项哈希与 AST 篡改负例见[R4 独立审查页](ctp-g1-two-stage-r4-independent-review-2026-09-27.md)及其中引用的原始证据 ZIP。

**裁决：G1 CLOSED。** 此候选不是 G1 acceptance：服务/Job 事实是 fake，不能证明 OS containment；prewarm/setup 和同步 watchdog hard-deadline 缺口仍未解决。未涉及 SCM/deployment、ACL、私有配置、SDK/native/provider、网络、凭据或 token session mutation。普通 preflight/default route 保持关闭。
