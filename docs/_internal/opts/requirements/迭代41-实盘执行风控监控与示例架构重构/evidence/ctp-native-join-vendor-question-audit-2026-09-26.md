# CTP 原生关闭厂商问题草案：只读证据审计（2026-09-26）

状态：`READ_ONLY_AUDIT / QUESTION_DRAFT / NOT_SENT / NO_VENDOR_CONTRACT / NO_WRITE`。只审阅仓库内既有脱敏文档；没有运行 SDK、导入扩展、读取私有配置或 marker、访问账户/网络，或重试 I2/I11/I12。

## 草案评估

`CTP原生关闭厂商确认问题.md` 对 MD 和 TD 都提出了 callback quiescence、logout、Join/Release 互操作、有界停止顺序、Release 后置条件和登录身份字段问题。就解除当前生命周期与身份语义缺口而言，覆盖完整；以问题清单而言略有重复：第 2、3、4、5 题都涉及停止流程或其后置条件。给厂商的精简版可合并为三组：

1. `RegisterSpi(nullptr)` 是否排空正在执行及后续 callback；若否，正式的 callback-drain 证明是什么？
2. MD、TD 各自受支持的停止顺序、logout 回调、Join 与 Release 状态约束是什么？Release 能否唤醒 pending Join，是否有界且线程安全，返回后如何证明所有线程/callback 已停止？
3. 对成功的 MD、TD `OnRspUserLogin`，哪些身份字段必须非空、必须回显请求，或应以什么官方字段验证身份？

每组仍要求按精确产品、Windows/ABI、DLL/header 身份分别回答；不能以 Mini 文档替代 full v6.7.7 合同。若保留原六题也足够清晰，且便于逐项作答。

## 本地证据核对

- `ctp-native-join-source-review-2026-09-25.md` 记录冻结 SDK wrapper 的源码顺序：`Init()` 后在后台线程调用 `Join()`；活动 Join 时 `stop()` 尝试 `RegisterSpi(None)`、保留 API/SPI 并返回；Join 返回后才 `Release()`。这是 wrapper 源码事实，不是 DLL 的关闭合同。
- 同一复核记录所审的头文件只说明 `Join()` 等待 API 线程结束、`Release()` 删除 API 对象。未发现 callback 排空、pending Join 唤醒、并发 Release 安全/有界、logout 使线程退出或安全关闭顺序的承诺。
- 本地官方材料没有填补缺口。仓库记录引用了不同 Mini 文档（V1.7.0 与 Ver.1.2）；两者都未被映射到本机 full v6.7.7 二进制。下载目录与示例调用顺序不是生命周期保证。登录字段名称/释义也不构成字段必须非空或必须回显请求身份的合同。
- `ctp-i2-i4-i6-i7-windows-abi-artifact-audit-2026-09-26.md` 独立记录了 MD DLL/header 哈希，以及 I2/I4/I6/I7 wheel 中的 MD、TD DLL 哈希；记录明确指出没有诊断进程的 OS mapped-module 文件身份回执，也没有官方发布归档/校验值。该审计本身没有列 TD header 哈希。2026-09-26 后续只读补核验找到与 native Join 源码复核所用 I10 commit `a6253a58b1ebca11f58c8836fbed757d0daf7582` 对应的两个 clean clones：

  | 绝对路径 | 大小 | SHA-256 |
  |---|---:|---|
  | `D:\temp\i10-final-wheel-repro-20260925\clone-a\src\bt_api_ctp\ctp\api\6.7.7\windows\ThostFtdcTraderApi.h` | 51,263 bytes | `e52c2cb7a8c17571d47848ea0a946679f9c2e12b5c9f4057188707a15d1546b0` |
  | `D:\temp\i10-final-wheel-repro-20260925\clone-b\src\bt_api_ctp\ctp\api\6.7.7\windows\ThostFtdcTraderApi.h` | 51,263 bytes | `e52c2cb7a8c17571d47848ea0a946679f9c2e12b5c9f4057188707a15d1546b0` |

  两个 clone 的 Git HEAD 均为上述 I10 commit。各自同目录 `thosttraderapi_se.dll` 大小均为 3,428,864 bytes、SHA-256 均为 `d79cc036fc90733a30cee8e8e30bdea17b346333c69413f33d44ebc7a96b1fad`，与既有 artifact audit 记录的 TD DLL hash 一致。因此草案 TD header hash 已与精确审阅源码及同树 TD DLL 对应；这仍不证明 I2/I11/I12 进程实际映射了该 DLL，也不证明本地文件等于官方发布字节。
- 公开本地材料只支持如下字段事实：6.7.7 头文件声明 `BrokerID`/`UserID` 的定长数组；Mini 手册列出登录响应字段。`ctp-md-callback-source-audit-2026-09-25.md` 与 I6/I7 记录报告了历史 callback 字段形状，但不能推出 vendor 的必填/回显规则。

## 官方发布材料核对（2026-09-26）

本节只采用 SimNow / 上海期货信息技术有限公司发布材料；搜索官方页面及其正式手册，没有找到能补足下列未定义语义的厂商 FAQ。API 下载索引对版本归属有帮助，但不是本机文件的发布身份收据：

- [SimNow API 下载目录](https://www.simnow.com.cn/static/apiDownload.action)分别列出其看穿式监管目录下的 v6.7.7 生产版本（`v6.7.7_20240607`，页面 MD5 `cb50cad8696bf00b64741641d9224ebc`）和评测版本（`v6.7.7_P3_SMCP_20240613`，页面 MD5 `14e92c110ca6d90e2e235cf86081f607`），同时另列 CTP Mini API V1.7.0（页面标注含 MD、TD API，归档 MD5 `87046333389971a2969a4a5a137c3a3d`）。对上述两个 v6.7.7 release，目录说明明确标注“仅 traderapi / 本次更新不涉及行情 API”。所以它们只能作为交易 API 更新的官方发布线索，不能证明本地 `thostmduserapi_se.dll` 的来源，也不能把同目录 MD DLL 归属给这两个 release。页面列出的 MD5 是归档校验值，不是单个 DLL/header 的 hash。仓库 `api/6.7.7/windows` 路径和 `API_VERSION=6.7.7` 不能单独辨别这些发布包变体，也没有把本地 SHA-256 对应到页面的某个官方归档。因此本地 I10 源码/hash 对应关系已核实，官方发布包逐字节归属仍为 `UNVERIFIED`。
- [SFIT CTP Mini API V1.7.0 应用开发参考手册](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf)不是仓库本机 full API v6.7.7 的版本证明。其第 162–164 页（4.1.1、4.1.3–4.1.5、4.1.8）说明 Release 用于删除 API 对象，Init 后接口开始工作，Join 等待接口线程退出并返回线程退出码，RegisterSpi 用于注册 callback；示例按 Create/RegisterSpi/RegisterFront/Init/Join 展示调用。以上材料没有规定 `RegisterSpi(nullptr)` 会排空 callback、Release 能唤醒活动 Join、二者并发安全/有界，或 Release 返回可证明线程与 callback 静止；示例顺序也没有给出可支持的停止流程。第 64 页（3.1.14）把 ReqUserLogout 定义为登出请求，没有描述 native API worker 的退出或 Join/Release 行为。
- 同一 V1.7.0 手册第 109 页（TD SPI 3.2.3）及第 169 页（MD SPI 4.2.3）描述 OnRspUserLogin 回调；其字段表列出 BrokerID、UserID、TradingDay 的名称/含义，回调的 `nRequestID` 被描述为终端原始请求编号。这支持请求编号用于关联的预期语义；手册没有说明零值无效，也没有规定这三个身份/交易日字段必须非空或 BrokerID/UserID 必须回显请求值。第 63 页（3.1.12 ReqUserLogin）的 request 结构把 BrokerID、UserID 列为必填，但这是**请求侧**约束，不是对成功登录响应内容的必填/回显承诺。以上都属于 Mini V1.7.0，不可外推为本机 full v6.7.7 的精确 vendor 合同。
- [CTPIIMini API V1.2 手册](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/CTPIIMini_API_Ver1.2.pdf)也列出登录响应字段并描述原始请求编号；它是更早且不同版本的 Mini 资料，同样不能证明 full v6.7.7 行为。官方目录中的 full v6.7.7 与 CTP Mini V1.7.0 是分列的产品/发布项目，不应混作同一版本线。

据此，官方可查资料只确认 API 的基本生命周期接口描述和 Mini 手册中的登录回调字段/请求编号描述。callback 排空、Join 唤醒、Release 与 Join 的合法并发/关闭顺序、有界停止及 Release 后置条件仍为 `UNKNOWN`；full v6.7.7 的 `OnRspUserLogin` 身份字段必填/回显规则也仍为 `UNKNOWN`。不以 Mini 示例顺序、字段表或请求编号描述补出这些保证。

## 官方 6.7.x MD 来源归属尝试（2026-09-26）

目标是把本机 I10 的 Windows `api/6.7.7` MD DLL/header 对应到上期技术的正式 MD 发布包，而不是只用同目录 Trader DLL 版本推断。只读检索 [官方 API 下载目录](https://www.simnow.com.cn/static/apiDownload.action) 后，搜索索引返回的精确 `v6.7.7_20240607` 和 `v6.7.7_P3_SMCP_20240613` 项均标明仅 traderapi、更新不涉及行情 API；其归档 MD5 分别为 `cb50cad8696bf00b64741641d9224ebc` 与 `14e92c110ca6d90e2e235cf86081f607`。因此这两个正式发布项不能证明本机 `thostmduserapi_se.dll` 或 `ThostFtdcMdApi.h` 来自其归档。目录中另有明确标示同时含 MDAPI/TraderAPI 的 CTP Mini V1.7.0，但它是独立 Mini 产品线，不是 full 6.7.7 MD 来源。此次官方索引检索未找到可对应本机 Windows full 6.7.7 MD 文件的基线发布说明/归档链接。

按官方索引 URL 直接读取页面以取得其 API 下载锚点时，`Invoke-WebRequest https://www.simnow.com.cn/static/apiDownload.action` 返回 **HTTP 403**、`Content-Type: text/html`，响应为腾讯云 WAF 拦截页。网页搜索缓存只提供 catalog 文本和归档 MD5，没有暴露对应 API ZIP 的直接下载 URL；`web.open` 对同一官方页亦超时。因此本次未取得或下载归档，也没有解压、覆盖或生成新的本地 DLL/header。当前手头的本机 I10 clean clone 仍只证明两个 source copies 与同目录 TD DLL 的本地哈希对应，不建立 MD 文件与官方发行包的关系。

**结论：**本机 full 6.7.7 MD DLL/header 的官方发布来源仍为 `UNVERIFIED`；不将 Trader-only release 的归档 MD5 当作 MD 来源证据。推进此项需要从可访问的官方入口取得明确包含行情 API 的 Windows full CTP 6.7.x 基线归档及其正式版本/校验值，或取得一份官方发布说明把 MD DLL/header 映射到具体归档。HTTP 403 下不尝试绕过 WAF，也不以第三方镜像、第三方文章或本机源码路径补足该映射。

## I2/I11/I12 历史回执边界

- **I2：**历史汇总记录 TD 七类查询收到终包，但 native Join 未完成，完整只读预检因此拒绝。单独 MD 尝试未接受登录；回执记录 request-ID mismatch 与 native Join pending。它们是失败观察，不证明 Join 的根因、Release 效果或账号错误。
- **I11：**MD 回执为 `identity_unverified`、订阅 ACK 已观察、tick/交易日无正面观察、`client_stop_returned=true` 且 `native_join_pending=true`。Windows Job empty 只证明进程树收拢。专用 marker 已消耗，不重试。
- **I12：**TD-only 尝试在 `sdk_artifact` 阶段被拒绝，发生在凭据解析和登录前；无 TD session、query 或 close 观察。I12 marker 已消耗，不重试。它不能用作 TD native 生命周期证据。

## 后续只读 conformance 计划

1. **静态身份核验：**分别取得厂商发布的 full 6.7.7 Windows x64 MD/TD 归档、版本说明和可信发布校验值；保留来源与日期，计算归档、DLL、头文件的 SHA-256。将结果逐项对照草案哈希及 frozen wheel 内容。检查 PE machine、header/API 版本路径、函数声明、登录响应字段顺序/packing/尺寸，以及 SWIG interface/wrapper 的对应关系。不得 import SDK、加载 DLL、构造 API 或启动 child。缺官方字节或校验值时标为 `vendor_binary_identity_unverified`。
2. **合同矩阵：**以厂商针对这些精确文件身份的书面答复或版本化手册逐项填表，MD、TD 分开记录：SPI detach 的 drain 保证；logout 请求/终态 callback；Join 可返回条件；Join 未启动/活动/已返回时 Release 是否允许、是否唤醒及其界限；Release 返回后的 callback/thread/API 生命周期；登录身份字段规则。每一格附原文位置和适用版本；无明文保证即记 `unverified`，不得由 sample 顺序或 fake 推断。
3. **离线 wrapper conformance：**只有合同矩阵完整后，给 wrapper 加纯 fake 的有序事件断言，覆盖合同指定的正常 callback/stop 顺序及 logout 拒绝、缺失终态 callback、timeout、pending Join、Release 失败。断言所有未知/超时情形均保留 API/SPI 并投影为 incomplete/unknown。Fake 结果只证明 wrapper 符合书面顺序，不证明 DLL 行为。
4. **未来动态确认门：**若合同仍需运行验证，另行进行新的、独立受监督、明确批准的只读 one-shot；不得重用 I2/I11/I12 marker。先验证 child 实际映射的 DLL 路径与哈希和合同完全一致，再分别做 MD 只读登录及固定单品种订阅、TD 只读登录及无写入查询；按厂商规定顺序关闭。仅在 callback-drain 证据、终态 callback（如合同要求）、Join returned、Release returned、无 native thread/SPI/API 残留和完整 receipt 全部成立时记为 orderly close。外层 Job empty 不替代任何 native 条件；超时或语义不明即停止并记 incomplete/unknown，不切换前置、不自动重试、不开放普通 preflight 或写路由。

本计划未执行。当前仍为 `NO_VENDOR_CONTRACT / NO_WRITE / LIVE_NO_GO`。
