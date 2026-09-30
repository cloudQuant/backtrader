# 000 三场所模拟穿透：2026-09-30 阶段证据

此记录仅覆盖只读账户预检、离线准入检查和源码测试。**真实穿透认证结果：Binance 0/33、OKX 0/33、SimNow 0/33；可选组件真实路线 0 项通过。** 不把 HTTP 200、测试通过或本地 fake 路线升级为案例 `PASS`。

## 源码与环境

- 工作区：`D:\source_code\backtrader`，分支 `dev`，基点 `7b333eabf9be2dde2176f42f0a184298356ee2c3`。运行时工作树有先前的 007 目录删除和未跟踪的 000 目录；本记录不把基点提交当成三个新脚本的身份。
- 三个预检源文件的 SHA-256：Binance `430291A762B11885BCAFDB13BB14EA95AF6383FE1FDBC209BA09C8A1EBBF0363`；OKX `52FE0946231E26175C224E8A58ED5F3399F963024A35127D8AE0CE6CB51EF0CD`；SimNow `201AD2E7893B2BF69CA6BECDDC8B0FCC140C73A8FDA60FE50FF1F84895D72FBB`。
- 凭据仅由本机 Git 忽略的 `.env` 读取；本记录不包含值、签名、账户号、余额、仓位或私有配置。源码测试使用假传输和显式 CPython 3.11。

## 实际运行

| 路线 | 结果 | 证据含义与限制 |
| --- | --- | --- |
| Binance USDⓈ-M direct，只读 | 2026-09-30 08:03:53 UTC，固定 `https://demo-fapi.binance.com` 上的签名 `GET /fapi/v3/account` 返回 HTTP 200，结构检查通过，`preflight=OBSERVED`；报单/撤单请求均为 0 | 只证明这把 Demo key 在当时可完成只读签名账户查询。响应未提供本认证合同所需的独立账号/会话来源；C01 仍 `NOT_RUN`，交易权限与完整快照未验证。 |
| OKX SWAP direct，只读 | `NOT_RUN` | API Key 所属区域尚未绑定；不得猜测 Global/US/EEA 域名。脚本就绪，尚未调用真实 OKX。 |
| SimNow 000，离线准入 | `BLOCKED`；零 native import、网络、登录、报单和撤单 | 七个所需 `.env` 变量存在；三个历史源码 profile 与当前 `.env` MD/TD 对均不匹配。000 套件未注册受管认证 runner，私有 `config.yaml` 未读取。当前 `C:\anaconda3\python.exe` 中 base 为 0.15.4（只读源 pin 0.15.5）、CTP 为 2.0.2（pin 2.0.3+iteration41.i2）；payload 未验证。`NO_WRITE / LIVE_NO_GO` 不变。另将 33 个 000 `run.py --live` 分别启动，全部 exit 2 / `BLOCKED` / `managed_ctp_certification_not_registered`。 |

Binance 预检是一次真实模拟环境只读请求；SimNow 是离线诊断。二者证据级别不同。SimNow 的 33 个入口只验证了关闭路径；没有运行任一场所的真实认证案例。

现行 Binance/OKX C01 合同强制 `source_session_id`、attestation session、认证 session 和登录 session 相等，还要求独立事件引用当次只读检查的 provider 请求/响应。Binance HMAC REST 200 不返回独立登录 session；OKX WS `connId` 只标识连接，不能由 REST 账户配置或 backend 自报补成两个登录事件。故现有预检不能计入 C01，且未尝试构造假的 session/账户证明。版本化的场所认证观察 profile、独立采集器和完整快照仍是 P2 开发项。

## 离线验证与可选组件

`C:\anaconda3\python.exe`，`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`：三个新预检、000 Binance/OKX 入口合同及新增显式 topology 关闭合同测试文件合计 **173 passed，1 个既有 pytest 配置 warning**；Ruff 对三个预检脚本及对应测试，以及 topology 新测试通过。入口测试验证 66 个固定案例入口、空凭据 C01 的无网络关闭、禁用 T01 的先授权和错配场所拒绝。topology 测试覆盖两场所、`direct`/`gateway_zmq` 与 execution/risk/monitor 的 16 种显式组合，均在凭据查询、backend 导入/创建、网络或证据目录建立前拒绝；没有显式 topology 的旧通用桥接入口在运行证据中固定标为 `legacy_generic_bridge`。这是防止错误路线声明的先行门，**所有显式路线仍不可用**，没有 provider 调用。禁用自动插件是因为当前全局 `pytest_asyncio` 与 pytest 收集不兼容；warning 为未知的 `asyncio_default_fixture_loop_scope` 配置项。

扩展到整个 `tests/unit/live_certification` 时，在收集阶段出现 4 个错误：旧测试仍导入已经从工作树删除的 `examples.007_ctp.live_certification`，其中一个还直接读取缺失的 `managed_case_entry.py`。该 007 删除和 000 简化套件在本轮开始前已经存在；新建的 000 测试不修复此迁移缺口。需先确定是否保留 007 原实现，或把对应实现和测试完整迁到 000，不能只替换测试路径。

可选组件采用显式 `BT_API_TEST_SOURCE_ROOTS` 的源码测试，非安装 wheel 验收：gateway 69、ZMQ 11（实际 TCP 1 项未跑）、execution 282、risk 140、monitor 92，合计 **594 passed**。Framework 五个 fake/offline 组合与投影文件中 **3 passed、4 failed**。清理旧 egg-info 的临时元数据遮蔽后仍是 4 失败：三个旧测试的无路由 `BtApiStore(provider="btapi", api=fake)` 被当前 Store 写门拒绝；另一个取消崩溃测试预期没有 freeze，但当前 risk admission 已持久创建 `dispatch-inflight` freeze。用非 CTP fake 路由诊断后，正常取消还暴露缺少经权威证明的 cancel-dispatch freeze 释放：risk SDK 有 `resolve_cancel_dispatch_freeze`，但当前组合没有提供它要求的 `VerifiedCancelDispatchResolution` 来源。不能通过绕过写门或直接清除 latch 让测试变绿。所有这些检查均未证明真实账号上的 gateway、ZMQ、execution、risk 或 monitor 路线可用。

另外从五个当前源码 HEAD 复制输入，在 `D:\temp\optional-component-wheels-20260930-ae3255ed` 完成离线 wheel 构建及全新隔离 Python 3.11.5 消费环境安装：五个 wheel 的 metadata、RECORD、与源码逐文件对照、安装 origin 和 `pip check` 均通过。execution wheel 为 0.2.0；其他四个为 0.1.0。依赖的 base 0.15.5 是复用的历史 wheel，未重新构建；该消费环境没有安装 parent SDK、Backtrader 或原生 CTP。这个结果关闭了五组件单独安装能力的疑问，**没有**关闭 parent/provider/可选路线验收。[制品安装报告及 JSON 旁证](optional-component-wheels-2026-09-30/README.md)已复制入本目录；原始命令输出与 wheel 文件仍保留在上述本地临时目录。

## 尚需取得的准入事实

1. OKX Demo key 的 API 区域及精确允许域名；三个场所各自的授权标的、单笔/累计预算和私有配置路径。
2. Binance/OKX 经审查的真实 schema-v2 venue adapter，以及 provider 身份、订单/成交/持仓/资金完整分页、独立事件来源、UNKNOWN 对账和限定清理。
3. M02/M03、EM01–EM03、L/M/TH/V 等案例的独立操作员、监控与本地未派发证据；B01 的真实部分成交及 E03 的真实市场状态条件不能由 API key 单独保证。盘点发现 SDK 有持久监控 outbox、控制账本和 HMAC ingress，Framework 有 Broker pause/resume/logout 钩子，但没有在三个套件中找到受信操作员身份解析、实际控制命令执行、账户级阈值流水或独立证据桥的接线。服务/进程名称检查未命中，不能据此断言远端服务不存在；部署状态仍待核实。
4. SimNow 000 受管注册、匹配前置/制品、G1–G6-S native/唯一写者准入，然后才可按 G7-S 做有限模拟报撤单；现有关闭状态不能用配置开关解除。
5. 五个可选组件的实际安装制品、组合路线和各路线账户级验收；源码测试与 fake 拓扑仅用于开发反馈。

对应开发计划：[000 三场所模拟穿透开发与验收](../000三场所模拟穿透开发与验收.md)。
