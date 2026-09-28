# CTP 同文件前置连通性复查（2026-09-25）

状态：`FRONT_CHECK_ONLY / I11_SEPARATE_ATTEMPT_INCOMPLETE / NO_WRITE / LIVE_NO_GO`。

**15:55 UTC 最新复查：** 前置选择由原来的两端各 3/3 全成功，改为两端各至少 2/3 成功才参与成功样本中位延迟排序；一端仅 1/3 时仍拒绝。诊断投影还会复核延迟分数与最快候选，拒绝不一致的选择回执。修改只影响无凭据 TCP 候选筛选，不绕过原生登录、身份、订阅、行情、交易准入，也不允许登录失败后改选另一组。定向 fake 回归 `47 passed, 1 existing warning`。对同一受保护配置重新执行 `check-ctp-fronts`，退出码 0，五组零基序号 0、1、2、4 的 MD/TD 均 0/3，序号 3 的 MD/TD 均 3/3，`status=selected`、`selected_config_index=3`。回执仍为 `tcp_probe_only=true`、`credential_resolver_invoked=false`、`sdk_imported=false`、`provider_login_started=false`、`authentication_attempted=false`、`order_submission_authorized=false`、`trading_writes=0`、`settlement_writes=0`。这是本次点时传输结果，不证明账号、原生会话或报撤单可用。

**15:40 UTC 历史复查：** 当时对同一受保护文件执行离线 `doctor` 成功（`simulation/sandbox`、无 runner/写权限）；随后按旧两端各 3/3 门槛执行无凭据 `check-ctp-fronts`，退出码 0，但结果为 `no_pair_reachable`、`selected_config_index=null`。五组零基序号 0、1、2、4 的 MD/TD 均为 0/3；序号 3 的 MD 为 2/3、TD 为 3/3，状态 `partial`。这份历史结果不按新规则倒改，也不能代替新一次登录或交易准入。

在约 08:00 UTC（中国时间 16:00）使用受保护的同一份 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml`，执行新增的 `bt-runtime check-ctp-fronts --strategy-dir <registered-runtime-dir>`。命令只从密封配置的五组成对候选发起有界、无凭据的 MD/TD TCP connect；输出没有前置地址、账号或认证值，也不按 set、时钟或日历选路。配置解析会读取文件中的认证字段字节，但该诊断不使用这些值，不调用凭据 resolver、CTP SDK、登录、订阅或交易 API，也不消耗原生一次性诊断标记。

| 零基序号 | MD 成功/采样 | TD 成功/采样 | 本次传输观察 |
| --- | ---: | ---: | --- |
| 0 | 0/3 | 0/3 | 不可达 |
| 1 | 0/3 | 0/3 | 不可达 |
| 2 | 0/3 | 0/3 | 不可达 |
| 3 | 3/3 | 3/3 | 可达，按配置候选内延迟规则选中 |
| 4 | 0/3 | 0/3 | 不可达 |

退出码为 0，公开结果为 `selected_configured_pair`、`selected_config_index=3`、`tcp_probe_only=true`、`provider_login_started=false`、`sdk_imported=false`、`trading_writes=0`、`settlement_writes=0`。本次观察只证明从该主机到第 4 组显式配置地址的 TCP 传输在该时点可用；不能证明 CTP 登录身份、行情订阅 ACK、tick、交易账户、结算或下单/撤单能力。其余组本次超时也不能推断地址永久失效。

约 08:25 UTC 再次执行相同无凭据命令，仍为五组候选中仅零基索引 3 的 MD 与 TD 各 3/3 连通，其他四组均为 0/3，退出码 0。该重复观察只更新当时的传输状态；没有启动 SDK、登录或交易。

约 10:16 UTC 第三次执行同一命令，退出码仍为 0；五组候选中仅零基索引 3 的 MD 与 TD 各 3/3 连通，其余四组均为 0/3。公开结果继续报告 `authentication_attempted=false`、`credential_resolver_invoked=false`、`sdk_imported=false`、`provider_login_started=false`、`order_submission_authorized=false`、`trading_writes=0` 和 `settlement_writes=0`。这仍只是一时点的 TCP 传输证据，不是账号或交易验收。

约 11:27 UTC 复查同一受保护文件，公开结果仍为 `status=selected`、`selected_config_index=3`、`configured_pair_count=5`、`tcp_probe_only=true`、`provider_login_started=false`、`trading_writes=0`，退出码 0。本次只投影了这些字段，未保留逐 pair 采样数；它不增加登录、行情或报撤单证据。

约 12:02 UTC 再次复查：同一五组显式候选中，零基索引 3 的 MD 与 TD 各 3/3 次 TCP 可达，其余四组均 0/3；选中索引仍为 3，退出码 0。公开回执明确 `authentication_attempted=false`、`credential_resolver_invoked=false`、`sdk_imported=false`、`provider_login_started=false`、`order_submission_authorized=false`、`trading_writes=0`、`settlement_writes=0`。这仍只是传输层时点观察。前置检查的离线定向测试现为 `12 passed`。

I10 的真实受监督尝试发生在较早时点，因五组 TCP 均超时而在凭据和 SDK 前拒绝；其专用标记已消耗，不会重置或重跑 I10。随后 I11 的前置要求已在一次独立受监督 MD-only 尝试中执行：marker 前完成固定制品 provenance Job 与同一密封配置的无凭据连通性检查，child 重新校验 digest/pair，并在 Windows Job 内运行；结果为 `incomplete / native_join_pending`，I11 marker 已消耗且不可重试。subscription ACK 已观察，但登录身份未验证，tick/交易日未正证，native close 未通过。详见[I11 脱敏证据](ctp-i11-md-diagnostic-2026-09-25.md)。这些传输观察不授权任何报单或撤单。

新 CLI 的 fake 定向测试在首次探测前为 `11 passed`，包括固定三次采样和错误证据拒绝；当时主仓 runtime `1501 passed, 25 skipped, 1 existing PytestConfigWarning` 是证据加固前历史 checkpoint。I11/latch/fresh-process/P2 更新后的 `1536 passed, 26 skipped, 1 existing PytestConfigWarning in 53.52s` 也是历史 checkpoint。可选前置探测截止时间更新后的当前主仓 runtime 全套为 `1561 passed, 26 skipped, 1 existing PytestConfigWarning in 69.12s`（exit 0）；这些测试没有真实 CTP 会话或写入。

[SimNow 官方产品页](https://www.simnow.com.cn/product.action)曾列出 7×24 环境的服务窗口，但该页面检索缓存较早；本次选择只以当前 sealed config 和实测延迟为准，没有根据该页面或时段切换候选。官方页也说明 7×24 环境不提供结算服务。
