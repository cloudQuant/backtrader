# CTP 6.7.7 Windows MD/TD 原生生命周期：厂商确认草案

状态：`QUESTION_DRAFT / NOT_SENT / NO_VENDOR_CONTRACT / NO_WRITE`。本文供开发负责人向 SDK/柜台提供方核对精确二进制合同；不含账号、密码、前置地址或合约，不代表已取得答复，也未发送。

## 本机 Windows 6.7.7 文件指纹

以下 SHA-256 已从本机 Windows 6.7.7 source 与 frozen-source 对应文件重新计算，两个位置结果一致。这些值只标识待询问的本机文件，不代表厂商确认其生命周期语义。

| API | DLL | DLL SHA-256 | Header | Header SHA-256 |
|---|---|---|---|---|
| MD | `thostmduserapi_se.dll` | `72a833786836ce6e6026bc0c19a06bd3c1b0279cb1ea9df0297b1c2916cad98b` | `ThostFtdcMdApi.h` | `744b6890028b5265f2a91dd6b43821ec71fb0512770a6f5e8fb01056f6f2d4e8` |
| TD | `thosttraderapi_se.dll` | `d79cc036fc90733a30cee8e8e30bdea17b346333c69413f33d44ebc7a96b1fad` | `ThostFtdcTraderApi.h` | `e52c2cb7a8c17571d47848ea0a946679f9c2e12b5c9f4057188707a15d1546b0` |

## 现有观察与边界

I8 的受监督 MD-only receipt 是有损投影，只报告 `native_shutdown_uncertain`，没有可靠的 `close_state`；不能从中推断 `Join()` 正在等 `Release()`。更强的 pending-Join 观察分别来自 I2 的 TD/MD 诊断、I6 的 no-login MD 关闭观察和 I7 的 MD-only 诊断，见[I2 验证汇总](evidence/validation-summary-2026-09-24.md)、[I6 证据](evidence/ctp-i6-md-diagnostic-2026-09-25.md)和[I7 证据](evidence/ctp-i7-md-diagnostic-2026-09-25.md)。这些观察均不确定根因，不能证明 `Release()` 会或不会解除 `Join()`，也不证明特定关闭顺序安全。

当前代码在 `Join()` 仍活动时保留 API/SPI，只有确认 `Join()` 返回后才调用 `Release()`。外部进程退出或 Job containment 仅证明进程结束，不能证明 native worker/callback 已按 SDK 合同静止。不得为排查而抢先调用 `Release()`。

## 请厂商分别确认 MD 和 TD 合同

请逐项对应上表的 DLL 与 header 哈希回答 MD、TD 两套 API；若合同依赖操作系统、发行版或 ABI，请说明准确范围并提供版本化手册或官方示例。

1. `RegisterSpi(nullptr)` 是否是 callback-quiescence fence：返回时是否保证没有 callback 正在运行，且之后不会再开始或投递 callback？若不是，SDK 提供什么可等待的 callback drain/静止合同？这一保证在调用 `ReqUserLogout` 前后是否不同？
2. `ReqUserLogout` 与对应的 logout response 在 MD、TD 中分别承担什么生命周期作用？它只结束柜台会话，还是会停止 API 内部线程？是否要求先 logout、等待终态回调，再注销 SPI 或调用 `Join()`/`Release()`？若 logout 无响应，应如何有界关闭？
3. 在 `Init()` 后另一线程处于 pending `Join()` 时，是否允许同线程或另一线程调用 `Release()`？`Release()` 是否保证唤醒 `Join()`，并发调用是否受支持、线程安全且有界？请分别回答 `Join()` 尚未启动、正在等待、已返回三种情况。
4. 对 MD 和 TD 各自，厂商支持的有界停止流程是什么？请明确 `RegisterSpi(nullptr)`、logout、`Join()` 与 `Release()` 的顺序、每步的完成证明及超时后的安全处置。若 `Join()` 无界等待，是否有受支持的 bounded stop API 或可验证的有界终止方法？
5. `Release()` 返回后，是否有正式保证所有内部线程和 callback 均已停止，且不会再访问已注销或释放的 SPI/API 对象？该保证是否对 MD/TD、评测版/生产版或不同平台有所不同？
6. 对成功登录的 `OnRspUserLogin`，文档列出的 `BrokerID`、`UserID`、`TradingDay` 是否要求非空或必须回显请求身份？若非必需，MD 与 TD 客户端应以何种官方字段/证据验证会话身份？

## 官方公开材料核对：`NO_VENDOR_CONTRACT`

只读核对了[官方 CTP Mini API V1.7.0 手册](https://www.simnow.com.cn/DocumentDown/api_3/5_2_4/SFIT%2BCTP%2BMini%2BAPI-V1.7.0.pdf)和[官方 API 下载目录](https://www.simnow.com.cn/static/apiDownload.action)。公开手册说明 `Init()` 开始工作、`Join()` 等待 API 线程结束、`Release()` 删除 API 对象，并展示 Create、RegisterSpi、RegisterFront、Init、Join 的示例顺序；没有约定 `Release()` 是否唤醒 pending `Join()`、并发调用是否安全、`RegisterSpi(nullptr)` 是否排空 callback，或 logout 对线程退出的合同。登录响应字段虽有列出，也没有承诺身份字段必须非空或与请求相等。V1.7.0 文档未被精确映射到上表本机 6.7.7 文件，不能作为其完整 MD/TD 关闭合同。

本问题保持 `QUESTION_DRAFT / NOT_SENT / NO_VENDOR_CONTRACT`。在取得与上述文件身份匹配的厂商答复或版本化合同前，不进行 provider 关闭顺序实验，不尝试活跃 `Join()` 期间的 `Release()`，也不以进程退出、`client_stop_returned` 或 fake Join event 作为 native shutdown 证明。本文不授予订单写入权限；SimNow 与未来 production 均保持 `NO_WRITE / LIVE_NO_GO`。