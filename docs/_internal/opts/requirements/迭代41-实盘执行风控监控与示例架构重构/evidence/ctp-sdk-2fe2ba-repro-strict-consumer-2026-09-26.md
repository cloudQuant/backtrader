# SDK 2fe2ba 双构建与严格安装检查点

日期：2026-09-26。结论：**本地可复现构建与已安装 fake 测试切片通过**。
本记录对应历史源码 `2fe2ba9d78bab6477aa4e232795aad35a14f2313`，
tree `4d87dc1feb2aa1c38383ddce061c11bd6640f6b1`。

## 制品与核对

两个干净短路径 checkout 在 CPython 3.11.5、setuptools 75.8、wheel 0.43、
MSVC 19.42.34435 / linker 14.42 下构建。显式固定构建时间、时区、hash seed，
使用 `cmd /d` 排除 AutoRun，并经本机编译/链接试验验证 `LINK=/Brepro`。
该选项的支持来自实际本机执行，不声称 linker 帮助文本记载了它。

| 项目 | SHA-256 / 结果 |
| --- | --- |
| 两个 SDK wheel | `b88b846b8961a318f820cfded4e1201fd531dafa9b149cb92d88c55a2cd74bfb` |
| 原生扩展，11,889,664 bytes | `e6d4e32740646962c35d96223682f4db0f1b8082398055a88f58ed45ec1ecd78` |
| 复用的已接受 base wheel | `cfe3507e1324f675454c41c37cd09ff72c8947c5254e9496e97c373cb8f3b369` |
| root 独立字节核对 | 两个 wheel 及全部 90 个成员一致 |
| 原始材料归档 | `cde3ab3954026bab7eaeb3e31aeaa17d88b4b2268933fb4f7d710b8cdd7b5aab` |

较早长路径、AutoRun 和未固定链接时间的失败均保留在归档中。另一次 scratch base
构建只用于差异诊断；本 consumer 复用上表已接受 base，没有更新 base pin。

## Consumer 范围

最终环境为 `D:\q\strict-consumer`，`include-system-site-packages = false`，
离线安装固定依赖后 `pip check` 通过。作者的 `python -I -S -B` 核对脚本仅加入
解释器对应的固定 venv site-packages，检查模块来源、direct_url、RECORD 和 wheel bytes：
base 109 项、SDK 90 项、PyYAML 24 项。原生 CTP 叶被主动阻断。

- 作者焦点测试：44 passed，保留日志。
- 作者 13 文件安装测试：296 passed、0 failed、0 skipped，12.604 秒。
- 作者主仓组合检查：7 passed / 25 source-layout skips，不能作为安装后 E2E 通过。
- root 独立核对环境声明、JUnit、安装核对日志及双 wheel 成员；未重跑上述 44/296 项。

早期带 system-site-packages 的环境存在依赖冲突，结果仅作诊断。作者严格复跑时复用了
`consumer-wide-accepted-base.xml`，覆盖了较早全局叠加环境的 XML；旧日志与记录的
旧 hash 仍保留，旧 XML 原字节无法提供。本归档中的该 XML 是最终严格环境的 296 项结果。

## 仍需分别验收

该源码缺少现有运行时依赖的 `md_front` / `ctp_env_profile` 构造绑定；后续
`29f8ff171f61a71038328a7067e0909bf44774b2` 窄修复已由 root 独立通过 63 项源码测试，
但不属于本 wheel。不能将本制品证据自动套用于后续版本。

本检查没有加载原生扩展、验证 ABI、启动真实会话、验证原生关闭、访问账户或发送交易请求。
统一 execution/parent/SDK 安装组合、G1 依赖安全加载和实际 SimNow/实盘验收均另行进行；
没有更新默认 pin 或注册 live 路由。

机器记录：[JSON](ctp-sdk-2fe2ba-repro-strict-consumer-2026-09-26.json)。
原始脚本、日志、JUnit、成员差异与环境材料：[45 项归档](ctp-sdk-2fe2ba-repro-strict-consumer-2026-09-26.raw.zip)。
