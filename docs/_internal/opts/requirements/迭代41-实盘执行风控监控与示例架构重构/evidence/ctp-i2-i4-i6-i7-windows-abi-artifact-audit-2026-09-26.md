# I2/I4/I6/I7 Windows MD API ABI/制品归属离线核对（2026-09-26）

## 结论范围

对 I2、I4、I6、I7 精确源码提交及可取得的 Windows wheel payload 做了只读比对。审计到的组合均声明并携带 full CTP API v6.7.7：MD DLL、`ThostFtdcMdApi.h`、`ThostFtdcUserApiStruct.h`、`ThostFtdcUserApiDataType.h` 和 Python/SWIG 源码落在 `api/6.7.7/windows`。四个提交与对应 wheel 中没有 Mini 1.7.0 文件，也没有发现已审计制品内把 Mini DLL/header 与 full v6.7.7 混装的证据。

这个结论只针对下列可审计源码和 wheel 的字节。它**不能证明**诊断 child 实际映射了 wheel 中同哈希的 DLL；I2/I4/I6/I7 的 `thostmduserapi_se.dll` OS mapped-module 路径/文件身份回执均未找到。也没有本地官方 full/Mini 原始归档或官方 SHA-256，可把这些本地字节与 SimNow 发布字节逐字节比对。因而不能据此解释 `OnRspUserLogin` 的 broker/user 空值、I2 request-ID mismatch、I6 `broker_id_mismatch` 或 native `Join` pending，也不能推断账号错误。

## 精确提交与 SHA-256 摘要

| 候选 | `bt_api_ctp` 源码 commit |
|---|---|
| I2 | `28157ce33009f932fbf8b3a78f7e77cb42c9cc4b` |
| I4 | `809239fdc0b7982d3512f4289e3e8dbcbd43a523` |
| I6 | `d85cd1571000c63d38bb9417a4942ec2692c5ad6` |
| I7 | `55a90a4fd841a996f2f5350593e09af2bf48e4a0` |

四个源码提交中的下列路径逐字节相同：

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `api/6.7.7/windows/thostmduserapi_se.dll` | 3,044,352 | `72a833786836ce6e6026bc0c19a06bd3c1b0279cb1ea9df0297b1c2916cad98b` |
| `api/6.7.7/windows/ThostFtdcMdApi.h` | 6,558 | `744b6890028b5265f2a91dd6b43821ec71fb0512770a6f5e8fb01056f6f2d4e8` |
| `api/6.7.7/windows/ThostFtdcUserApiStruct.h` | 348,447 | `13458040d1a7840e0e9b7ea77acc9251088e591a4e7e8be86fc6c44340d789b5` |
| `api/6.7.7/windows/ThostFtdcUserApiDataType.h` | 288,713 | `8de1bf4c06abd87b21ad0f7ee239286fde0c28c1562e81f85e5fc770a8c8830c` |
| `ctp_md_api.py` | 5,895 | `ccddb61719b32fdbada17b6994173aa54f15d687472eda933a02559459d6febe` |
| `setup.py` | 8,737 | `db501fb25690d23ebabbdd82b44c768d7215a3667ca903836e6de5625d7a0d7f` |

`setup.py` 的 `API_VERSION` 为 `6.7.7`，include 路径指向 `api/6.7.7/windows`。I2/I4/I6 的 `ctp.i` 与生成 wrapper SHA-256 分别为 `02d4e0a64142397dc06ee9440c8d5af36fac3ea5710fc794c17e9a544858ca31`、`0db9998aada2331b30f5bebb19ed456272f678a7f00a6507f3607d975fc8d259`。I7 的对应哈希为 `6bd3cf8bd0f6dffd89db507939d0c0905015542c0329e33b6e8738a3c6183dd0`、`9134f7fcecd0741a254a2857c6d9725547eff89a2dc37540d4ec8c0aff584adf`；差异是额外的诊断字段形状 helper，不是 CTP 结构定义变更。四个 wrapper 中 `OnRspUserLogin` 的 request ID 参数都是 C++ `int`，经 `SWIG_From_int` 转为 Python int；响应结构是 borrowed pointer。该静态转换路径没有提供 native callback 为何送出特定 request ID 的证据。
本地 DLL 的 Windows FileVersion 与 ProductVersion 资源为空；此处的 v6.7.7 来自仓库 API_VERSION 和 include 路径，不是 PE 版本资源。

## Wheel payload 交叉核对

| 候选 | Windows wheel SHA-256 | wheel 内 `_ctp.cp311-win_amd64.pyd` SHA-256 |
|---|---|---|
| I2 | `988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff` | `468eaf9b623f684959922e3d1a2970f7f5ea71c73b7495cd533732f39672ef47` |
| I4 | `96f8c874871b6f571e3abb14bf25b32a4ccb133ca09e51767584e5c03682283e` | `dd0572c4cce960f04793d02c55e8be3ec260e0f3c70c0b150f7d1bb35666146a` |
| I6 | `3788bf75019eb8fa685b828be9dae66b2f17d41422e770441870a105e02c1ded` | `5a5759f57e45b0cf80478a7d64ab425ab7f084c2bfde916643b47d6a0b0fe8a7` |
| I7 | `22bc34140233785abcad61e7c3bc4dbb85c9d97b171692d5e6b44cf89eda94b4` | `148739cdecb070f11f310c19bdf44ab7b2d803a5b3c54249571d3f16b5a0d6bb` |

四个 wheel 内 MD DLL 哈希均为上述 `72a833…cad98b`；Trader DLL 哈希均为 `d79cc036fc90733a30cee8e8e30bdea17b346333c69413f33d44ebc7a96b1fad`。扩展模块因候选代码变化而有不同哈希。Wheel verifier/manifest 可将各本地 wheel 与相应安装扩展关联；这仍不是运行中的 Windows module map 证据。

## 官方资料引用与缺口

- SimNow API 下载索引：[https://www.simnow.com.cn/static/apiDownload.action](https://www.simnow.com.cn/static/apiDownload.action)
- SimNow CTP Mini API V1.7.0 手册：[https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf)

本轮没有访问或下载这两个页面/文件；父任务提供的页面观察称下载索引把 full v6.7.7 与 Mini 1.7.0 列为不同项目，并指出 Mini 手册提及 `RspUserLoginField` 版本变化。由于手册 PDF、官方归档、发布校验值均不在本地，本核对没有独立确认该变更的字段布局，也没有可比对的官方归档 hash。不同下载项目是版本/产品系列提示，不是本机加载来源证明。

## 不启动 native 的下一步验收设计

1. 在不导入 SDK、不加载 DLL 的离线环境中，留存官方 full v6.7.7 与 Mini 1.7.0 归档及发布页/发布校验值的来源快照；分别计算归档与解包文件 SHA-256，禁止交叉覆盖目录。
2. 只做静态比较：PE machine/import/export 信息，DLL 与头文件归档一致性，`RspUserLoginField` 声明/字段顺序/packing/尺寸，以及 SWIG `.i`、生成 wrapper 与头文件的版本绑定；输出一份哈希清单。若无官方归档或可靠发布校验值，标记“官方字节归属未证实”，不得把本地文件名当证明。
3. 对 I2/I4/I6/I7 的保留 wheel 做静态内容和安装来源核验，并检查安装树中的同名 DLL、加载目录设置与潜在同名副本；测试过程不得 `import _ctp`、构造 API 或启动 child/native。该步骤只能验证候选部署布局，不产出实际 mapped-module receipt。
4. 将“实际映射文件路径/文件身份/hash”列为任何未来独立受监督诊断的前置观测字段；若它必须由运行中进程取得，应另行批准并按既有硬期限 supervisor 门槛执行。本次不启动 native，也不因缺 receipt 重试任何已消耗诊断。

以上都是静态制品归属/兼容性检查设计，不是登录、账号、vendor callback 行为或生命周期验收；`NO_WRITE / LIVE_NO_GO` 与 G1–G4 状态不变。