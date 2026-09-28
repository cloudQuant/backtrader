# CTP 私有配置来源核对（2026-09-24）

本次记录只列字段是否存在、来源处理、配置摘要及离线准入结果，不记录任何凭据值或前置地址值。没有读取输出或复述密钥、账号口令、认证码、AppID 或 front 内容。

初次来源核对时已将仓库根目录 `.env` 规范化为 UTF-8 并设置为 owner-only ACL；该时点删除了一条重复赋值并补入明确的非凭据 `CTP_HEDGE_FLAG=1`。后续配置更新的当前状态见文末追加复核。变更前的原始文件备份保存在被忽略且受保护的 SimNow `runtime-ctp-private/state/` 目录中。

`prepare-ctp-simnow-config` 原已支持 `CTP_HEDGE_FLAG`。本轮补上根 `.env` 使用的 `CTP_INSTRUMENT`、`CTP_EXCHANGE` 别名，并允许多个别名在解引号后的值完全相同时映射到同一字段；值冲突仍拒绝。准备器写出的 `strategy.id` 也已改为与默认注册表中的 Iteration 22 SA strategy ID 完全一致，避免生成后被 registry seal 校验拒绝；对应的本地测试对该身份作精确相等断言。

初次私有 schema-v4 `config.yaml` 从明确指定的根 `.env` 生成至 `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/`。当时输入的十个 CTP 字段与生成配置逐项匹配，mode/preset 为 `simulation/sandbox`，文件被目录 `.gitignore` 忽略且具有 owner-only ACL；当时配置摘要为 `c819e949755a317891d383851a73cd5fb62fbc494d75a879d4d2e78042bafe45`。该摘要及后续单 pair 观测是历史配置时点，不代表当前文件。

初次核对时离线 `doctor` 已识别配置并以 exit 0 通过；当时配置是单 pair。后来的一次单 pair 三样本探测得到 `selected_index=0`、`reachable_pairs=1`、`score_ms=391.38`，仅为那一配置时点的运输层观察，不是当前配置状态或 CTP 账号验收。

初次 `bt-runtime preflight` 在当时单 pair 前置探测后以 exit 2、`ctp_simnow_preflight_capability_origin_rejected` 拒绝：基础 SDK 为 editable/source 安装，受审 SDK artifact pin 目录为空。该命令未读取凭据、未进行 CTP 登录、查询、订阅、下单或撤单；没有产生 provider 会话、外部写入或 live 执行。`examples/007_ctp/runtime-production/config.yaml` 仍不存在。这只说明当时未登记 production runner；当前目标操作约定是 SimNow 与 future production 共用 013_3 下同一个 protected runtime config 和 canonical `ctp:` 字段，production runner/admission 仍另需实现与验收。后续状态见下方追加复核与[最新验证汇总](validation-summary-2026-09-24.md)。

## 后续配置复核（2026-09-24）

该来源审计采集时，仓库根 `.env` 有 50 个唯一键；显式执行 `prepare-ctp-simnow-config` 时，准备器可读取 current、完整 SET1 numbered、成对 SET2 的 MD/TD 输入，按输入次序写成不带 set 标签的 `front_pairs` 并对精确重复 pair 去重；半组、冲突和超过 8 组会拒绝。运行时仍只读取密封配置，不按 set 或时间选择，也不访问 `.env`。当时私有 `config.yaml` 有四组成对、无标签且去重的候选；之后已扩为五对。该历史证据不公开地址或账号值。

以上一版 `ctp_simnow:` config snapshot 为基准时，离线 `doctor` digest 为 `bfdbe9e31770420097b3829972da9032d0e1a8de456765410992fbf65cee7654`。此前一次三样本四候选 selector（每端点连接上限 3 秒）exit 0，`reachable_pairs=1`、`selected_index=3`、`score_ms=386.299`；该结果现为历史时点。接着的单样本 probe 对四组候选报告 `selected_config_index=3`、`selected_latency_ms=411.9175`、`reachable_config_indices=[3]`。旧 block 下的 `preflight` 使用三样本 selector，在候选探测后以 exit 2、`ctp_simnow_preflight_capability_origin_rejected` 拒绝；SDK wheel pin catalog 为空且未受审，没有 CTP SDK 登录。该 preflight 的选中索引和分数未留存，不能用 standalone one-sample 分数代替。更早的单地址 timeout 与单 pair `selected_index=0` / `391.38 ms` 也只是各自时点的 transport 观察。以上不替代真实账号验收；没有真实登录、查询、行情回调、下单或撤单证据。

## Same-path schema update (2026-09-24; supersedes prior `ctp_simnow:` digest)

The protected file at `examples/013_3_sa_midfreq_simnow/runtime-ctp-private/config.yaml` was migrated in place to the canonical top-level `ctp:` block. Owner-only ACL and Git-ignore status were preserved; mode remains `simulation/sandbox` and the same four ordered pairs and other values remain. Offline `doctor` returned exit 0 with digest `23ffc90a6c481e462f2627a01586e2e90689b916b4acb294503f5c952ec30ea5`. The prior digest `bfdbe9e31770420097b3829972da9032d0e1a8de456765410992fbf65cee7654` is historical.

After migration, CLI `preflight` still exited 2 with `ctp_simnow_preflight_capability_origin_rejected` after configured-front TCP probes because the installed base SDK is editable/source. It did not perform SDK account login/read or real writes. A later standalone probe (one sample per endpoint, 2-second timeout) returned `no_configured_front_pair_reachable` and selected no pair; an earlier one-sample probe saw index 3 / 411.9175 ms. These are separate, unlogged transport timepoints; the preflight selection index/score remains unrecorded. The previous independent production config/path described above is legacy/deferred evidence, not the operator contract. Future production CTP must reuse this same physical registered `config.yaml` and shared `ctp:` field shape after user initiation; its runner/admission remains unimplemented and production account/front values are not prefilled.
