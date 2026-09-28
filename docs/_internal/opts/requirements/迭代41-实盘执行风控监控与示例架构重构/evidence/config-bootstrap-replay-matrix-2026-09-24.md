# 迭代 41 本地配置与回放矩阵（2026-09-24）

状态：`CONFIG_VALIDATE_DOCTOR_PASS / LOCAL_REPLAY_PASS / REAL_SIMNOW_NOT_RUN / LIVE_NO_GO`。本记录覆盖本机创建的 schema-v4 回放配置及离线执行结果。它不证明真实 SimNow 会话、生产账户、下单或实盘准入。

## 配置生成与覆盖范围

使用受信 runtime-set 运行 `bt-runtime bootstrap`：普通集 `iteration41-replay` 覆盖 11 个 nonmanaged source/example runtime，托管集 `iteration41-managed-replay-l2` 覆盖 2 个 fake-provider managed L2 runtime。13 个登记目录中的 `config.yaml` 均存在、均被 Git 忽略，mode/preset 均为 `simulation/replay`，未把账号或密钥写入文件。本轮 bootstrap 新建 12 个文件；`examples/012_1_midfreq_cross_exchange/runtime/config.yaml` 已存在且与模板匹配。

| Runtime | 本地配置路径 |
| --- | --- |
| 012_1 midfreq cross exchange | `examples/012_1_midfreq_cross_exchange/runtime/config.yaml` |
| 012_2 event driven cross exchange | `examples/012_2_event_driven_cross_exchange/runtime/config.yaml` |
| 013_1 midfreq cross arbitrage | `examples/013_1_midfreq_cross_arbitrage/runtime/config.yaml` |
| 013_2 highfreq calendar arbitrage | `examples/013_2_highfreq_calendar_arbitrage/runtime/config.yaml` |
| 013_3 SA midfreq SimNow replay | `examples/013_3_sa_midfreq_simnow/runtime/config.yaml` |
| 014_1 CTP options low frequency | `examples/014_1_ctp_options_lowfreq/runtime/config.yaml` |
| 014_2 CTP options mid frequency | `examples/014_2_ctp_options_midfreq/runtime/config.yaml` |
| 015 CTP options high frequency | `examples/015_ctp_options_highfreq/runtime/config.yaml` |
| sample migration profile | `examples/sample/runtime/config.yaml` |
| 007 CTP no-action profile | `examples/007_ctp/runtime/config.yaml` |
| 010 legacy no-action profile | `examples/010_live_examples/runtime/config.yaml` |
| 013_3 managed fake-provider L2 | `examples/013_3_sa_midfreq_simnow/runtime-managed-replay/config.yaml` |
| CTP options managed fake-provider L2 | `examples/ctp_options_simnow_managed_replay_runtime/config.yaml` |

## 离线检查和运行

对以上 13 个目录逐一执行 `bt-runtime validate` 和 `bt-runtime doctor`：全部 exit 0。`doctor` 报告 `offline=true`、`provider_preflight_started=false`、`allows_network=false`、`allows_external_writes=false`。这只是配置和环境诊断结果，不会连接账户。

| 当前源码运行结果 | Runtime |
| --- | --- |
| exit 0；本地回放完成 | `012_1_midfreq_cross_exchange`, `012_2_event_driven_cross_exchange`, `013_1_midfreq_cross_arbitrage`, `013_2_highfreq_calendar_arbitrage`, `013_3_sa_midfreq_simnow`, `014_1_ctp_options_lowfreq`, `014_2_ctp_options_midfreq`, `015_ctp_options_highfreq`, `sample`, `007_ctp`, `010_live_examples` |
| exit 0；`LOCAL_MANAGED_FAKE_PROVIDER_L2_PASS` / `LOCAL_CTP_MECHANICAL_MANAGED_FAKE_PROVIDER_L2_PASS`，需临时 `PYTHONPATH` 指向本机 SDK 源码包目录 | `013_3_sa_midfreq_simnow/runtime-managed-replay`, `ctp_options_simnow_managed_replay_runtime` |

更新 012_1/012_2 的目录内冻结 manifest 并通过 `scripts/refresh_cross_exchange_local_manifests.py --check` 后，两条 runner 均重新完成 validate、doctor 和 run；结果 `FORMULA_CHECK_PASS`，`network=0`、`order_write=0`。最终 11/11 ordinary replay 和 2/2 managed fake-provider replay 通过。managed L2 的 PASS 需要临时 `PYTHONPATH` 指向 `D:\bt_api_py\bt_api_py` 及 `D:\bt_api_py\bt_api\bt_api_base\src`、`bt_api_execution\src`、`bt_api_risk\src`、`bt_api_monitor\src`；没有全局安装或网络安装。默认 Anaconda 环境缺少这些 `bt_api_*` 包时以 `PRESET_POLICY_VIOLATION / capability_dependency_missing`、`field=runtime.capabilities.bt_api_execution` 在 provider 前 fail closed。该依赖条件只影响本机 L2 replay 运行方式，不改变真实 provider/SimNow/live 的未准入状态。

所有完成的离线和 fake-provider 回放均记录 `network=0`、`external writes=0`。这些计数不代表真实 provider 验收。

## SimNow 与实盘状态

本机 `examples/013_3_sa_midfreq_simnow/.env` 和 `examples/015_ctp_options_highfreq/.env` 的 SimNow 用户名/密码字段为空；`examples/014_1_ctp_options_lowfreq/.env` 的投资者身份/密码字段为空。另有一个候选 Wondertrader 配置仅做了字段/权限元数据核查：虽有交易前置与认证字段，但缺少独立行情前置、交易所、HedgeFlag 和当前合约。该文件已由另一仓库的 Git 跟踪且 ACL 范围过宽，不能视为安全的凭据来源；未从中复制、回显或记录凭据值。现有 `.env` 也不是 Iteration 41 `config.yaml` 的自动配置来源。

`examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` 和 `examples/007_ctp/runtime-production/config.yaml` 均不存在。当次核对时前者没有默认登记的 SimNow private-read binding，SDK artifact pin 目录也为空；后者只是未登记的 parser-only 生产配置位置，没有 production front pin 或 live runner。因而真实 SimNow preflight、真实行情/交易登录和生产 live 均未运行，也不能靠复制旧 `.env` 或填写 replay 配置使其获得准入。

后续运行 012_1/012_2 需先复核更新后的冻结 fixture；要进行真实 SimNow/production 验收，则还需完成对应受审 runtime 注册、制品与 endpoint pin、受保护的私有配置/凭据来源和所需外部验收门。当前结论保持 `REAL_SIMNOW_NOT_RUN / LIVE_NO_GO`。

## 同日后续状态（取代上文“SimNow private-read binding 未登记”）

默认 inventory 现已登记 `runtime-ctp-private` 的 `simulation/sandbox` 配置绑定私有只读 route，共 16 条注册；该 route 没有 runner、执行能力或外部写权限。目标 `config.yaml` 仍不存在，SDK artifact pin catalog 仍为空，默认 `doctor`/`preflight` 以 `CONFIG_REQUIRED/missing_config`（原生退出码 2）在 provider 前拒绝。production 目录仍未登记。配置来源缺口见[CTP 私有配置来源核对](ctp-private-config-source-audit-2026-09-24.md)；真实 SimNow/production 验收仍 `NOT_RUN / LIVE_NO_GO`。上文回放结果与当时配置核对保留为历史观察。

## Later shared CTP configuration direction

The earlier “production directory not registered” and missing-private-config statements above describe that matrix checkpoint and are historical, not a requirement to create `examples/007_ctp/runtime-production/config.yaml`. The current operator path is the single protected `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` with canonical `ctp:` fields; it is the SimNow file now and the future production file after a reviewed mode/account/front/contract edit. Production remains fail-closed until its runner, write admission, and independent artifact/account/session/risk acceptance pass. The current five-pair config and I2 TD/MD evidence are recorded in [the latest validation summary](validation-summary-2026-09-24.md); status remains `NO_WRITE / LIVE_NO_GO`.
