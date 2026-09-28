# CTP I5 一枪式 MD 只读候选：离线与真实诊断证据（2026-09-25）

结论：`INCOMPLETE / NO_WRITE / LIVE_NO_GO`。I5 离线制品核验及本地测试通过；一次受 Windows Job Object 监督的真实 SimNow MD-only 诊断未取得可接受登录、订阅 ACK、匹配 tick 或完整 native 关闭。它没有触发交易或结算写入，也未改变默认注册的只读边界。该证据不证明配置账号错误，也不构成 provider、账户、生产或 live 验收。

## 离线制品与测试

| 项目 | 已核验结果 |
| --- | --- |
| 隔离 SDK 源码 | clean commit `a101590f5f29070439c13b6062b3487abee936cc` |
| CTP wheel | SHA-256 `552dc8711523aef930864b7441a2a93ed2f4cb9541acc15435ac8fe9a3ca98dc` |
| CTP 安装 RECORD | SHA-256 `3320042e1b0d4706cda2c9272806c91aa5ef7efe329f85178db45f3ed2b36026` |
| base wheel | SHA-256 `1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d` |
| base 安装 RECORD | SHA-256 `aa91bfa982d473eb2b8ce59192196f87a84e7c9c19aafd8e961c73e5ea87ce90` |
| 安装来源核验 | 隔离安装 verifier 通过 |
| SDK 离线测试 | 安装后焦点集 `100 passed`；源码焦点集 `83 passed`；扩展离线 CTP 集 `892 passed, 1 network test deselected`。其中两个依赖未固定 parent SDK 的写入测试文件未运行，不属于只读候选的通过范围。 |
| 主仓离线测试 | I5 代码尚未 pin 时 `tests/unit/runtime` 为 `1223 passed, 24 skipped, 1 warning`；完成 I5 pin 与 verifier 后完整 runtime 为 `1225 passed, 24 skipped, 1 warning in 56.72s`（exit 0）。I4/I5 pin 后焦点集 `62 passed`，Ruff 通过。 |

以上测试均为本机离线或假客户端范围，没有 provider I/O。I5 使用独立候选制品核验；它不更改 I2 注册预检 pin，也不表示 I5 诊断已注册为默认 route。I2 与 I4 的独立历史证据仍分别见原有记录，不由此结果覆盖。

## 一次真实 MD-only 诊断

Windows Job supervisor 的脱敏审计记录位于本机受限目录 `D:\c41sdki5_audit\audit\i5-md-diagnostic.jsonl`，不纳入仓库。审计用时 `15,141 ms`，未超时，子进程退出码为 3。诊断只从同一个 Git-ignored 受保护 `runtime-ctp-private/config.yaml` 的五组成对候选中选择；本次 `selected_config_index=3`（从 0 开始）。不记录候选地址、账户值、配置摘要或凭据。

结果为 `incomplete / market_client_stop_failed`，阶段为 `market_data`。只观察到一次登录回调，`identity_rejected`，固定失败类别为 `broker_id_mismatch`；I5 请求 ID 有意设为 0，回调 request-ID 关系为 `zero`，与该请求匹配；响应错误状态也为 `zero`。脱敏诊断还记录登录回调的 BrokerID getter 结果形状为 empty：SDK getter 返回空字符串或空字节串，未保存原值。该观察只证明 getter 返回了空值，不能说明 native 字段为何为空，也不能据此认定账号或配置错误。

行情登录未就绪；没有订阅 ACK 或匹配 tick。`client_stop_returned=true`，但 native Join 仍 pending/uncertain，完整关闭未获确认。交易和结算写入计数均为零。登录失败且关闭未确认后没有尝试其他候选。

本机审计器对这条 JSON 记录执行的脱敏扫描未发现任何配置账号、凭据、合约或前置原值。离线合成 native SWIG 响应结构的 BrokerID ASCII round-trip 测试通过；未填充结构的 getter 默认返回空。CTP headers/API 手册列出响应中的 BrokerID 字段，但没有保证在响应错误状态为零时该字段一定非空，也没有定义安全的并发 `Release`/`Join` 次序。以上源码/合成对象观察均不能解释本次真实 native 字段为空的原因；Join/Release 安全合同仍未确立。

## 边界与后续

这是一项未注册的一次性只读诊断，没有 Trader、报单、撤单或结算写入能力。SimNow 目前仍只使用该受保护配置中的 `simulation/sandbox` 私有只读注册；未来 production 目标复用同一物理 `config.yaml`，但当前没有 production runner、默认 live route 或 live 写入准入。后续须分别解决 SDK/native 登录身份字段来源和安全关闭问题，并取得被接受的真实登录、精确订阅 ACK、匹配 tick、完整 Join/Release 关闭观察；该证据不授权自动换候选重放账号。精确 Windows 6.7.7 identity 与 shutdown 合同问题保持未发送，见[厂商确认问题草稿](../CTP原生关闭厂商确认问题.md)。
