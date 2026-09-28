# 三包可复现构建与严格安装环境验收（2026-09-26）

裁决：`LOCAL_ARTIFACT_CONTRACT_PASS / NOT_RELEASE_ELIGIBLE / LIVE_NO_GO`。

## 精确输入与制品

本次只构建 base、risk、monitor 三个纯 Python 包。每包从精确 Git commit
创建两个独立 detached clean checkout，构建前后均干净；使用相同
`SOURCE_DATE_EPOCH=1790000000`，两个目录产出的整个 wheel 字节一致。

| 包 | 源 commit | wheel SHA-256 | 大小（字节） |
| --- | --- | --- | ---: |
| `bt_api_base==0.15.4` | `3de0fa4f6cfe8d1973e9f4b9b47b01254259524f` | `cfe3507e1324f675454c41c37cd09ff72c8947c5254e9496e97c373cb8f3b369` | 149476 |
| `bt_api_risk==0.1.0` | `2201316f5ea196d164b3045d02648fe857989b92` | `d279381a6e809482ae9f76faa290af8a0e19fedc4e041ef4e3e62f1684e354de` | 92588 |
| `bt_api_monitor==0.1.0` | `f3583e744922d556a6015576f386c2d26e3aae51` | `0277663855356b22a7946da07ed4c6d33cebac11d93cbdc152531c287040ae8e` | 47018 |

构建使用 Windows CPython 3.11.5 的独立 venv（无 system-site）：
pip 23.2.1、setuptools 84.0.0、wheel 0.48.0、packaging 26.3。
命令为 `python -m pip wheel --no-index --no-deps --no-build-isolation`。
源清单 hash 是 `core.autocrlf=true` 下实际 checkout 字节，并非 Git blob hash。
原始 wheel、构建目录与日志位于 `D:\temp\iteration41-capability-artifacts-20260926`。

## 严格 consumer 结果

新的 consumer venv 通过显式本地 wheel 路径安装三包及本地依赖闭包；
逐项验证 wheel payload、安装后的 RECORD、direct_url archive hash、模块来源，
`pip check` 为 `No broken requirements found.`。项目模块全部来自该 venv 的
site-packages；禁用 user-site、无 system-site、清除 `PYTHONPATH`。

实际由 `consumer-venv\Scripts\python.exe -I -m pytest` 执行复制的源测试，
没有手工插入 consumer site-packages 或修改 `sys.executable`。
QA-only conftest 在测试进程内断言解释器、prefix、环境和所有已加载项目模块来源；
复制的测试文件 hash 与 clean checkout 相符。

| 范围 | 结果 | 时间与诊断 |
| --- | --- | --- |
| risk 全包 | **206 passed** | 36.14 秒；包含 fresh isolated import 与真实 SQLite reserve；1 条未设置 asyncio fixture scope 的非失败警告 |
| monitor 全包 | **90 passed** | 4.65 秒；5 条 psutil Windows 弃用警告及 1 条 asyncio scope 非失败警告 |

测试工具为实际安装在 consumer 内的 pytest 8.2.2、pytest-asyncio 0.24.0。
仅测试工具从官方 PyPI 下载，固定 wheel hash 后离线安装；项目安装与测试没有
provider/native 访问。工具 wheel 与安装报告 hash 均保存在原始 JSON。

## 证据修正与边界

初次测试曾用全局解释器并手工加入 consumer site-packages、改写
`sys.executable`；该次 206/90 结果已明确降级为 **hybrid diagnostic**，
不能用作隔离安装验收。上述通过数来自随后真实 consumer 解释器的重新运行。

base 此精确源版本为 **0.15.4**，不同于历史 I4 pin 的 0.15.5。
risk 保留继承而来的版本不一致：distribution metadata 为 **0.1.0**，
模块 `__version__` 为 **1.0.0**；此次未规范化版本，也不宣称 release ready。
monitor 没有模块 `__version__`。

此证据不包含 parent、CTP 或 execution 最新候选的统一 wheel，不更新默认 SDK pin，
不证明依赖发布来源、OS 隔离、BM56–59 性能矩阵、真实账户、原生会话或写权限。
risk 的分析依赖 metadata 仍为必需项；lazy import 仅改变运行时加载边界。

## 原始清单

[完整 JSON 清单](capability-artifacts-strict-consumer-2026-09-26.json)
SHA-256：`b3ddfc47944b05671cbbd14b9a88a104ae66ea4843728ad06b8ac762d415b34b`。
根代理独立完成 JSON 解析、hash 核对，并审核严格 consumer 与被降级运行的区分。
完整清单包含每个实际源文件、wheel payload/RECORD、安装报告、测试环境和命令。
