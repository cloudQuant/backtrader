# SDK MD/profile 构造绑定源码复验

日期：2026-09-26。结论：**窄范围源码 fake 测试通过**。

现有运行时调用 `TraderClient` 时传入 `md_front` 与 `ctp_env_profile`，而干净
`2fe2ba` SDK 没有这两个参数。这是实际接口缺失，七个查询证据测试因而失败。
修复提交 `29f8ff171f61a71038328a7067e0909bf44774b2`，tree
`a7ebae409036aa69a18dc71e2063ad149b0f4741`，仅改 SDK client 与对应测试。

改动新增成对 keyword-only 参数、显式 MD/TD 地址规范校验及构造时绑定的只读
MD/profile 属性。原七个位置参数的调用方式保持兼容。修改公开 `md_front`
不会改变已绑定地址；这属于普通接口约束，不隔离恶意同进程 Python。

## 独立检查

root 审查提交 diff 后，在 no-system `D:\q\strict-consumer` 中运行独立
`python -I -B` harness：SDK 源码显式来自 `D:\q\e\src`，base 来自
该 venv 的 site-packages。两个测试文件合并 **63 passed / 0 skipped / 0 failed**，
0.95 秒，保留一个 pytest 配置 warning；native 导入被阻断时另有预期的扩展不可用提示。

| 文件 | SHA-256 |
| --- | --- |
| SDK client | `bf915128c41da83efdff517e3ea711c43d7555406bd831a0dfcd775b64840d1c` |
| SDK fake test | `2950f29a32b8fff49f293554fc3765d8c0a8e566eea0207a7444380fd9251bcd` |
| 主仓 query verifier | `17a5711a598c17052ac9a4496127eba406e0d2dc365111885ea4787733fb590b` |
| 主仓 query test | `f54ce3af74f624b723bc1bcbf4163ccb6556aa995f9dab0a936365c23b5b0c41` |

四文件首尾哈希一致；归档时再次核对 SDK HEAD、干净状态和四文件 bytes。
独立 harness 拒绝网络与真实私有配置访问，精确阻断原生 CTP module leaf，
两次预期 native import 尝试被记录；最终原生模块未加载。

## 范围

该结果不是 SDK 安装 wheel 验收、原生 ABI/关闭测试、真实 TD/MD 会话或交易准入。
后续双构建与严格安装将使用新输出，不覆盖 `2fe2ba` 的历史制品证据。
作者的 56 项 SDK focus 和七项 query 日志亦保存，独立 63 项没有借用它们的计数。

机器记录：[JSON](ctp-sdk-md-profile-29f8ff-source-review-2026-09-26.json)。
原始脚本、四个源文件、JUnit 和日志：[11 项归档](ctp-sdk-md-profile-29f8ff-source-review-2026-09-26.raw.zip)，
SHA-256 `ed09e7358784c20b86377b1bf4279111446aa6f84a10ff9d0a1fa93ef35120e2`。
