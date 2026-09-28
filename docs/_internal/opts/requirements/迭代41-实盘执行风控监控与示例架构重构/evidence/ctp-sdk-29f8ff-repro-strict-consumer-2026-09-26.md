# SDK 29f8ff 可复现制品与严格安装复验

日期：2026-09-26。结论：**SDK 制品与已安装 fake 测试切片通过**。

本次包含 [MD/profile 构造绑定修复](ctp-sdk-md-profile-29f8ff-source-review-2026-09-26.md)。
SDK commit 为 `29f8ff171f61a71038328a7067e0909bf44774b2`，tree 为
`a7ebae409036aa69a18dc71e2063ad149b0f4741`。`D:\q\e` 及新 clone `ha/hb`
在构建后仍为同一提交且干净；root 已独立复核。

## 构建与安装

复用先前已验证的 CPython 3.11.5、setuptools 75.8、wheel 0.43、MSVC
19.42.34435 与 `LINK=/Brepro` 构建参数，两个输出各为 5,429,976 bytes。
root 独立比较两个 wheel 和全部 **90 个成员**，字节一致：

`dc0aaac0063262d38db27535ea7b7bf4d221a9938dea851198b71e690772571f`

全新 `D:\q\cv18` 禁止 system-site-packages，离线安装该 SDK、已接受的 base
`cfe3507e1324f675454c41c37cd09ff72c8947c5254e9496e97c373cb8f3b369` 和固定依赖；
`pip check` 通过。目录中的 `v18` 只是本轮输出标签，**没有安装 execution V18**。

作者与 root 分别运行 `python -I -S -B` RECORD/payload 核对：base 109、SDK 90、
PyYAML 24 个 RECORD 行，并核对每个非 RECORD wheel 成员与实际安装字节，共
**443 条检查**。同进程模块来源、direct_url wheel hash 均符合隔离 venv；
原生 CTP 叶被主动阻断，未加载。

## 测试及重试记录

作者执行 13 文件 fake 测试，最终 **308 passed / 0 failed / 0 skipped**，14.02 秒，
一个预期的原生导入阻断 warning。root 核对 JUnit 与日志，没有重跑该 308 项。
root 此前独立源码组合 63 项的证据另见上面的源码回执。

初次 consumer 为 307 passed / 1 failed，原因是一个 shutdown 测试需要主仓
`backtrader_runtime`。补入主仓源码路径后重新运行；SDK/base 来源仍经同进程断言
限定在 venv。初次失败与后续成功使用不同日志/XML，均保留，没有覆盖旧制品。

## 范围与材料

本次未加载原生 DLL、验证 ABI/生命周期、启动 provider 会话或使用账户凭据。
这不是 execution/parent/SDK 的统一安装组合，也没有更新默认 pin 或 live route。

机器记录：[JSON](ctp-sdk-29f8ff-repro-strict-consumer-2026-09-26.json)。
构建命令、环境、两次测试、443 条核对和 root verifier：[32 项原始材料](ctp-sdk-29f8ff-repro-strict-consumer-2026-09-26.raw.zip)，
SHA-256 `5deddb0bd64fa441e5b587da0168a6237d6b54eced01bc7e6e5562e3c76a6812`。
