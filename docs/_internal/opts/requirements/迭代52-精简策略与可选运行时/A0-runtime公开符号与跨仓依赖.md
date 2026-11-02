# I52-A0：runtime 公开符号与跨仓依赖清点

状态：A0 静态调查输入，未形成迁移批准。所有新 runtime/config API owner 均待 A1 统一合同确认。本文只记录当前 checkout 中可从 Git tracked source 证实的表面，不据此声称安装包、账户或运行消费者验收。

## 1. 基线、范围与方法

- Backtrader：`D:/source_code/backtrader`，分支 `dev`，HEAD `ed6b77d7ddf8630983c7d4555d4da92400b44ff3`。调查前 tracked worktree/index 无差异；大量已有 untracked `.codex-tmp` 内容未读取、未改动。本文件是本轮唯一新增文件，不提交。
- SDK consumer 历史全仓扫描快照：`D:/bt_api_py` 的原始扫描 HEAD 为 `a8ce5c9a4226748bbb377a5f4dd0b148aa454422`；当时根目录 903 个 tracked `.py` 与下表 21 个子仓的 SHA、数量、引用计数均只代表该快照。当前根仓 HEAD 已核对为 `805cd8de834c1a50d6665feb215c8a7ddd4b1a60`；从原 HEAD 到当前，`bt_api_py/_ctp_credential_binding.py` 与 `bt_api_py/bt_api.py` 两个被本页点名的父仓源码没有 HEAD diff，当前这两个路径也无工作区差异。本轮没有重做全仓/子仓扫描或刷新状态、数量、gitlink 与引用计数；下表及原 dirty 状态记载不得称为当前清点。
- Backtrader 目标范围含 48 个 tracked 路径：44 个 `.py`（`backtrader_runtime/` 37 个、`backtrader/runtime/` 7 个）及 4 个 package fixture 资源。资源只枚举路径，不读取任何 `config.yaml` 内容；未读取 `.env`、真实配置、secret、capture、evidence 或任何本轮以前的 untracked 文件内容。
- 以 `git ls-files` 建立路径集，用 Git `HEAD` blob 作静态 AST、`git grep HEAD` 作字面引用扫描；未执行项目、CLI、测试、SDK 或账户/provider 操作。反射、构造字符串、入口点之外的外部消费者，以及运行时是否实际导入/调用均未证实。

## 2. 覆盖统计与结论

| 范围 | 覆盖 | 结果 |
|---|---:|---|
| `backtrader_runtime/` + `backtrader/runtime/` | 48 tracked paths；44 tracked Python | 逐模块列于 §3；4 个非 Python 资源只列名：一个 `bars.csv`、三个 package fixture `config.yaml`，未读内容 |
| 字面 `__all__` | 20 个模块；240 个 export entries（含跨层重复） | package root 有 85 个显式导出名；19 个子模块显式列出导出名；其余模块无 literal `__all__`，不能据可访问属性视为稳定承诺 |
| SDK Python HEAD | 根 903 + 21 子仓 1,200 = **2,103** 个 tracked `.py` | 根仓及 `bt_api_ctp` 有 `backtrader_runtime` 字面命中；其余 20 子仓为 0 命中 |
| SDK runtime / CLI 直接依赖 | 2 个仓库有匹配 | `backtrader.runtime` 与 `bt-runtime` 在 SDK 集合中均无字面命中；BT API 根依赖包级动态导入和私有 adapter 名，CTP 仓命中为哈希字段/可选测试导入 |

四个只按路径盘点、未读取内容的资源：

- `backtrader_runtime/_iteration41_backtest_fixture/data/bars.csv`
- `backtrader_runtime/_iteration41_backtest_fixture/runtimes/local_backtest/config.yaml`
- `backtrader_runtime/_iteration41_l2_fixture/runtimes/managed_013_3/config.yaml`
- `backtrader_runtime/_iteration41_l2_fixture/runtimes/mechanical_p1b/config.yaml`

**A0 迁移影响：** `backtrader_runtime` 不是单纯可删的历史目录。Backtrader tracked source 仍由 CTP Store bridge、示例入口/旧 runner、service observation 和 028 protected CTP reader 引用；SDK 根仓还要求 source-bound credential adapter。旧 schema 的 `paper` 是 `simulation + local_simulation`，语义与 I52 外部 paper 账户不同。根据用户的迁移目标，I52 应先定唯一配置 owner、字段映射和 package/source identity 合同，将范围内功能及调用方切换到新归属后移除旧入口，最终不保留旧 API shim；延期功能按计划拆分留存。移除前仍须完成已知调用方迁移与外部消费者风险处理。

## 3. Backtrader runtime 模块与公开符号

以下名称来自 Git HEAD AST：显式列表标 `__all__`；无 `__all__` 的模块只登记顶层非下划线定义，属于“偶然可访问”，不应直接承诺为稳定 API。模块 owner 均暂记“旧 Backtrader runtime；I52 新合同 owner 待定”。每行的状态/兼容面/下一步单独列明。

### 3.1 `backtrader/runtime/` 兼容门面（7 个 tracked Python）

| 路径 | 公开/转发符号 | owner / 状态 | 兼容依赖与下一步 |
|---|---|---|---|
| `backtrader/runtime/__init__.py` | `from backtrader_runtime import *`；继承 root `__all__` | 旧 facade / 待核 | 该 star import 请求 root 的三个延迟 runner 名称，进而加载 runner 模块；外部依赖未知，迁移前静态扫描安装消费者，不能据本仓 grep 直接删 |
| `backtrader/runtime/__main__.py` | 转发 `backtrader_runtime.cli.main`，即 `python -m backtrader.runtime` | CLI alias / 迁移候选 | 与 `python -m backtrader_runtime`、console entry 共存；完成新入口与活跃调用方切换后移除旧入口 |
| `backtrader/runtime/cli.py` | `_implementation` 属性代理、动态 `__all__`/`__getattr__`/`__dir__` | CLI facade / 待核 | 运行时依赖 `backtrader_runtime.cli`；反射属性未穷举，先迁移活跃 CLI 消费者再移除门面 |
| `backtrader/runtime/config.py` | 动态代理 `backtrader_runtime.config` | config facade / 待核 | schema-v4、sealed config 与字段拒绝语义需先迁移；不得只换 import 路径 |
| `backtrader/runtime/errors.py` | 动态代理 `backtrader_runtime.errors` | error facade / 待核 | 稳定 error code 与 `as_dict()` 是 consumer 边界；需做新错误码映射 |
| `backtrader/runtime/policy.py` | 动态代理 `backtrader_runtime.policy` | policy facade / 待核 | preset 与 mode 的旧语义不可一对一映射 I52 mode；合同确定后迁移消费者并移除旧门面 |
| `backtrader/runtime/registry.py` | 动态代理 `backtrader_runtime.registry` | registry facade / 待核 | registration、seal、digest、bootstrap 共同构成兼容面；先迁移调用方再退役 |

### 3.2 `backtrader_runtime/` 模块 API（37 个 tracked Python）

#### package、CLI、配置、注册与通用桥接

| 路径 | 公开符号（AST） | 状态 / 兼容依赖 / 下一步 |
|---|---|---|
| `backtrader_runtime/__init__.py` | root `__all__` 共 85 项，完整清单见 §3.3；仅三个 runner 名称通过 `__getattr__` 延迟导入，其他名称由顶层导入绑定 | 主 public API / 待核；按 I52 新合同逐项确定功能归属并切换已确认的外部/SDK 调用方，最终不保留旧名 shim |
| `backtrader_runtime/__main__.py` | 模块入口，调用 `cli.main` | `python -m` 入口 / 迁移候选；与 console script 一起纳入 CLI 切换计划 |
| `backtrader_runtime/cli.py` | `build_parser`, `dispatch_registered_runtime`, `dispatch_registered_ctp_simnow_readonly_preflight`, `dispatch_registered_ctp_front_check`, `main` | operator CLI / 待核；保留拒绝未知输入与 live admission gate，逐命令决定迁移/退役 |
| `backtrader_runtime/config.py` | `CtpSimNowPrivateConfig`, `CtpProductionPrivateConfig`, `RuntimeConfig`, `require_loaded_runtime_config_seal`, `load_runtime_config`, `write_bootstrap_config`；常量 `CONFIG_FILENAME`, `CONFIG_SCHEMA_VERSION`, `MAX_CONFIG_BYTES`, `CTP_PRODUCTION_RUNTIME_DIR` | 唯一旧 schema/parser / 待核；I52 必须指定唯一新 parser owner 并建立显式版本迁移/拒绝表，禁止并存两套 YAML parser |
| `backtrader_runtime/errors.py` | `RuntimeConfigError`; `CONFIG_REQUIRED`, `CONFIG_SCHEMA_UNSUPPORTED`, `MODE_PRESET_MISMATCH`, `PRESET_POLICY_VIOLATION`, `ENVIRONMENT_MISMATCH`, `CONFIG_EXISTS`, `MIGRATION_REVIEW_REQUIRED`, `ERROR_CODES` | 稳定机器错误面 / 迁移输入；映射到新错误分类，保留安全脱敏与 `error_code/message/field_path/reason` 投影 |
| `backtrader_runtime/policy.py` | `CAPABILITY_EXECUTION`, `CAPABILITY_RISK`, `CAPABILITY_MONITOR`, `CAPABILITY_GATEWAY`, `CAPABILITY_TRANSPORT_ZMQ`, `MANAGED_WRITE_CAPABILITIES`, `PresetPolicy`, `PRESET_REGISTRY`, `get_preset_policy`, `preset_names` | 旧 mode/preset 权限模型 / 待核；不得将 `paper` preset 解释为外部模拟账户，按 A1 能力矩阵重定 owner |
| `backtrader_runtime/registry.py` | `RuntimeDirectoryIdentity`, `UnavailableModeProfile`, `RuntimeProfile`, `RegisteredRuntime`, `RuntimeSet`, `BootstrapRuntimeSetItem`, `BootstrapRuntimeSetResult`, `RuntimeRegistry`, `default_runtime_registry`, `EffectiveRuntimeConfig`, `require_effective_runtime_config_seal`, `resolve_runtime_config`, `validate_runtime_config`, `select_bootstrap_preset`, `bootstrap_runtime_set`, `bootstrap_runtime_config` | 运行登记/配置解析/来源 seal / 待核；迁移 registration、唯一 dispatch owner、digest 与拒绝边界；检查全部 live/paper 当前注册情况 |
| `backtrader_runtime/runner.py` | `dispatch_configured_runtime`, `dispatch_registered_runtime`, `resolve_runner_effective_config` | 唯一旧 dispatcher / 待核；A1 必须保持单一派发 owner、失败不回退，静态入口不证明当前注册能力可运行 |
| `backtrader_runtime/legacy.py` | `legacy_direct_execution_error`, `run_legacy_config_first_cli` | 旧 direct gate/示例迁移 shim / 迁移候选；枚举并切换实际调用方，保全必要拒绝语义后移除旧 shim |
| `backtrader_runtime/capability_imports.py` | `first_unavailable_trusted_capability_module`, `trusted_capability_import_context`, `trusted_installed_capability_import_context` | 可选能力导入审计 / 支持工具，是否进入可安装 runtime 待核；先确定 I52 dependency/origin policy |
| `backtrader_runtime/managed_execution.py` | `ManagedExecutionBindingError`, `CtpQueueReceiptState`, `CtpQueueReceiptClassification`, `classify_ctp_queue_receipt`, `CtpManagedExecutionAdapterPlaceholder`, `strict_limit_intent_from_order`, `observation_from_store_response`, `strict_cancel_intent_from_order`, `cancel_observation_from_store_response`, `project_record_to_store_response`, `project_cancel_record_to_store_response`, `ManagedExecutionBridge`, `bind_managed_execution` | Backtrader CTP Store 边界的 13 项模块符号候选 owner/处置见下方补充；不覆盖 85 项 root `__all__` 或全模块消费者 |
| `backtrader_runtime/cross_exchange_orderbook_observation.py` | `observe_cross_exchange_orderbooks` | read-only observation / 待核；依赖 `service_observation`，按 paper/live 是否需要决定保留或 DEFERRED |
| `backtrader_runtime/service_observation.py` | `ServiceObservationError`, `ServiceObservationInstrument`, `account_resource_key`, `market_subscription_key`, `load_service_observation_config`, `ServiceObservationSession`, `collect_service_observation`, `observe_service_contracts`, `open_service_read_session` | 只读 service facade / 迁移候选；核对 012/013/014/015 调用方、SDK version/source roots、资源所有权，再按 A1 生命周期合同定位 |
| `backtrader_runtime/framework_projection.py` | `FrameworkProjectionClaim`, `FrameworkProjectionJournal`, `FrameworkProjectionRecoveryError`, `canonical_framework_projection_fingerprint` | SQLite projection/journal surface / 待核；确认是否属于 Backtrader 的事实投影或旧支持证据，禁止变成第二个订单/账户事实权威 |

#### Credential、CTP 私有只读和 provenance surface

| 路径 | 公开符号（AST） | 状态 / 兼容依赖 / 下一步 |
|---|---|---|
| `backtrader_runtime/credential_resolver.py` | `CTP_AUTHENTICATION_CREDENTIAL_KEYS`, `CONFIG_YAML_REF`, `MAX_OS_SECRET_STORE_BLOB_BYTES`, `MAX_RUNTIME_SECRETS_BYTES`, `OS_SECRET_STORE_PREFIX`, `RUNTIME_SECRETS_FILENAME`, `RUNTIME_SECRETS_REF`, `CredentialResolutionError`, `ResolvedRuntimeCredentials`, `RuntimeCredentialScope`, `require_resolved_runtime_credentials_seal`, `resolve_runtime_credentials` | credential source adapter / 高影响待核；bt_api_py 要求的 source identity 见 §5，先统一 resolver/adapter owner、package digest 与缺失私有模块处理；本文未读取任何秘密值 |
| `backtrader_runtime/ctp_artifact_provenance.py` | `CTP_I3_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I4_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I5_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I6_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I7_ONESHOT_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I8_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I9_EMBEDDED_WHEEL_RECORD_SHA256`, `CTP_I9_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET`, `CTP_I9_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I9_REPRODUCED_WHEEL_SHA256`, `CTP_I10_EMBEDDED_WHEEL_RECORD_SHA256`, `CTP_I10_INSTALLED_RECORD_SHA256_BY_REPRO_TARGET`, `CTP_I10_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_I10_REPRODUCED_WHEEL_SHA256`, `CTP_I12_TD_ONLY_READONLY_ARTIFACT_PINS`, `CTP_I13_ONESHOT_MD_DIAGNOSTIC_ARTIFACT_PINS`, `CTP_SDK_ARTIFACT_PINS`, `CtpArtifactProvenanceError`, `CtpSdkArtifactPin`, `simnow_fronts_for_profile`, `simnow_profile_for_fronts`, `verify_ctp_simnow_managed_artifact_provenance_for_fronts`, `verify_ctp_sdk_artifact_provenance`, `verify_ctp_sdk_artifact_provenance_for_fronts`, `verify_ctp_i3_oneshot_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i4_oneshot_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i5_oneshot_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i6_oneshot_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i7_oneshot_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i8_oneshot_md_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i9_oneshot_md_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i10_oneshot_md_diagnostic_artifact_provenance_for_fronts`, `verify_ctp_i12_td_only_readonly_artifact_provenance_for_fronts`, `verify_ctp_i13_oneshot_md_diagnostic_artifact_provenance_for_fronts` | CTP source/artifact pins / migration input; preserve pin semantics only where a new owner and supported package contract are identified; historical proof IDs are not runtime capabilities |
| `backtrader_runtime/ctp_configured_front_check.py` | `CtpConfiguredFrontCheckResult`, `CtpConfiguredFrontPairCheck`, `check_configured_ctp_fronts` | CTP front probe result / ops candidate; classify as paper/live dependency or DEFERRED read-only tooling |
| `backtrader_runtime/ctp_front_pair_probe.py` | `MAX_PROBE_WORST_CASE_SECONDS`, `CtpConfiguredFrontPair`, `CtpFrontEndpointEvidence`, `CtpFrontPairEvidence`, `CtpFrontPairProbeError`, `CtpFrontPairSelection`, `CtpFrontProbeSample`, `select_ctp_front_pair` | CTP network/front selection / ops candidate; explicit capability and timeout contract needed before inclusion |
| `backtrader_runtime/ctp_preflight.py` | `CTP_PROVIDER`, `CTP_SIMNOW_ENVIRONMENT_PATTERN`, `REQUIRED_CTP_READ_ONLY_QUERIES`, `CtpReadOnlyPreflightError`, `CtpReadOnlyPreflightResult`, `CtpReadOnlyQuerySnapshot`, `CtpReadOnlySession`, `CtpReadOnlySessionFactory`, `CtpReadOnlySessionIdentity`, `CtpReadOnlySessionRequest`, `run_ctp_simnow_readonly_preflight` | private CTP read-only protocol /待核; separate read-only from execution write permissions and preserve failure-closed lifecycle |
| `backtrader_runtime/ctp_private_config_setup.py` | `PreparedCtpSimNowConfig`, `prepare_ctp_simnow_config_sources`, `prepare_ctp_simnow_config` | protected source/config creation tool / migration-critical ops surface; verify whether I52 keeps it outside ordinary runtime, preserve explicit source-path/security contract |
| `backtrader_runtime/ctp_sandbox_readonly_admission.py` | `CtpSandboxReadOnlyAdmissionError`, `CtpSandboxReadOnlyObservation`, `CtpSandboxReadOnlyRegistration`, `admit_ctp_simnow_sandbox_readonly`, `require_ctp_sandbox_readonly_runtime_contract` | bounded private read admission /待核; not paper write or live execution authority; retain only with explicit A1 owner |
| `backtrader_runtime/ctp_sdk_market_readonly.py` | `CtpSdkMarketReadOnlyError`, `CtpSdkMarketReadOnlyObservation`, `CtpSdkMarketTickBinding` | native market read-only adapter /待核; source/native lifecycle dependency should remain separate from credentials and orders |
| `backtrader_runtime/ctp_sdk_readonly.py` | `CtpCredentialSource`, `CtpSdkReadOnlyError`, `CtpSdkReadOnlyCloseEvidence`, `CtpSdkReadOnlyScope`, `CtpSdkReadOnlySessionFactory` | CTP SDK scope/read-only client /待核; compare against SDK's native/credential source identity contract before moving |
| `backtrader_runtime/ctp_simnow_operator.py` | `CtpSimNowConfigReadOnlyBinding`, `CtpSimNowReadOnlyBinding`, `dispatch_registered_ctp_simnow_readonly_preflight` | CLI-bound CTP ops routes /待核; operator config preparation is not trading authorization |
| `backtrader_runtime/ctp_simnow_readonly_runtime.py` | `CtpSimNowFrontSelectionAudit`, `CtpSimNowReadOnlyRuntimeError`, `CtpSimNowReadOnlyRuntimeObservation`, `open_ctp_simnow_readonly_runtime` | CTP read-only managed lifecycle /待核; requires separate actual-consumer proof and explicit I52 permission boundary |

#### Deployment/evidence/validation contracts

| 路径 | 公开符号（AST） | 状态 / 兼容依赖 / 下一步 |
|---|---|---|
| `backtrader_runtime/evidence_bundle.py` | `BASELINE_ID`, `DEFAULT_ARTIFACT_SPECS`, `EVIDENCE_BOUNDARY`, `EVIDENCE_KIND`, `EVIDENCE_SCHEMA_VERSION`, `EvidenceCollectionError`, `collect_iteration41_evidence` | Iteration41 evidence collector / historical ops API; locate any live callers, otherwise preserve outside installable runtime |
| `backtrader_runtime/provider_deployment.py` | `ACTIVE_RECEIPT_STATUS`, `MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULES`, `MAX_PROVIDER_DEPLOYMENT_CAPABILITY_MODULE_NAME_LENGTH`, `MAX_PROVIDER_DEPLOYMENT_RECEIPT_BYTES`, `PROVIDER_DEPLOYMENT_RECEIPT_SCHEMA_VERSION`, `RECEIPT_BINDING_VALIDATED`, `REVOKED_RECEIPT_STATUS`, `ProviderDeploymentReceipt`, `ProviderDeploymentReceiptError`, `ProviderDeploymentReceiptValidation`, `ProviderDeploymentReceiptVerifier`, `ProviderDeploymentRegistration`, `RejectingProviderDeploymentReceiptVerifier`, `canonical_provider_deployment_receipt`, `parse_provider_deployment_receipt`, `provider_deployment_receipt_sha256`, `validate_provider_deployment_receipt` | provider deployment receipt v2 /待核; receipt is one input, not authority; compare fields/digest/lifecycle to A1 plan and SDK owner |
| `backtrader_runtime/provider_preflight.py` | `ProviderSessionPreflightBinding`, `ProviderSessionPreflightRegistration`, `ProviderDeploymentReceiptError`, `validate_provider_session_preflight_binding` | provider preflight gate /待核; retain fail-closed admission chain only if a paper/live adapter uses it |
| `backtrader_runtime/test_execution_profile.py` | `MAX_TEST_EXECUTION_PROFILE_BYTES`, `MAX_TEST_EXECUTION_PROFILE_EXTERNAL_WRITES`, `MAX_TEST_EXECUTION_PROFILE_INSTRUMENT_LENGTH`, `MAX_TEST_EXECUTION_PROFILE_INSTRUMENTS`, `MAX_TEST_EXECUTION_PROFILE_LIFETIME_SECONDS`, `RejectingTestExecutionProfileVerifier`, `TEST_EXECUTION_PROFILE_PRECHECKED`, `TEST_EXECUTION_PROFILE_SCHEMA_VERSION`, `TestExecutionPreflightContext`, `TestExecutionProfile`, `TestExecutionProfileError`, `TestExecutionProfileObservation`, `TestExecutionProfileVerifier`, `canonical_test_execution_profile`, `parse_test_execution_profile`, `test_execution_profile_sha256`, `validate_test_execution_profile` | test/approval profile v2 /待核; distinguish test evidence from actual mode/permission; decide whether retained as internal contract or removed from installable runtime |
| `backtrader_runtime/review_evidence.py` | `ITERATION41_EVIDENCE_SCHEMA_VERSION`, `REVIEW_REQUIRED`, `Iteration41ReviewEvidenceBindings`, `Iteration41ReviewEvidenceError`, `Iteration41ReviewEvidenceObservation`, `canonical_json`, `evidence_sha256`, `resolve_iteration41_review_evidence_bindings`, `validate_iteration41_review_evidence`, `validate_registered_iteration41_review_evidence` | evidence schema v1 / historical certification support; preserve old evidence readers only in archival tooling if not used by paper/live |

#### Fixture and registry artifacts

| 路径 | 公开符号（AST） | 状态 / 兼容依赖 / 下一步 |
|---|---|---|
| `backtrader_runtime/_iteration41_backtest_fixture/__init__.py` | 无顶层公开定义 | fixture package / DEFERRED 候选；明确排除安装/runtime export 或指定保留位置 |
| `backtrader_runtime/_iteration41_backtest_fixture/run.py` | `runtime_registry`, `run_runtime`, `main` | 本地回测 fixture / DEFERRED；不要映射成 I52 `paper` |
| `backtrader_runtime/_iteration41_l2_fixture/__init__.py` | 无顶层公开定义 | fixture package / DEFERRED 候选；追踪任何测试依赖再决定保留位置 |
| `backtrader_runtime/_iteration41_l2_fixture/managed_013_3.py` | `runtime_registry`, `run_runtime`, `main` | fake managed L2 fixture / DEFERRED；不构成 provider runtime |
| `backtrader_runtime/_iteration41_l2_fixture/mechanical_cycle.py` | `MechanicalCycleBlocked`, `MechanicalLeg`, `MechanicalCycle` | fake/local mechanical cycle / DEFERRED；保留为研究/冻结材料，不进可安装 runtime |
| `backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py` | `runtime_registry`, `run_runtime`, `main` | fake managed/mechanical fixture / DEFERRED；非外部 paper/live proof |
| `backtrader_runtime/inventory.py` | `iteration41_runtime_registry`, `iteration41_l2_fixture_registry`, `iteration41_backtest_fixture_registry` | 默认/fixture registration owner / 待核；逐项登记 active consumer，拆分保留 profile 与正式运行能力 |

#### `managed_execution.py` 的 Store 边界：逐符号候选 owner 与决定（局部补充）

本表只处理上一行 13 项模块顶层符号，以及 `backtrader/stores/ctp_managed_projection_bridge.py` 实际导入的 private helper `_managed_runtime_order_id`，共 14 项；不是 85 个包级 `__all__` 的逐项结论，也不宣称完成整个模块、全仓 caller 或外部消费者调查。逐项源码交叉核对基于 Backtrader `dev` HEAD `7700f52dc502c199fe7efffc33033e87bfb2d0d1`；本页 §1 的 `ed6b77d7...` 是原调查基线，仍作历史记录，不由此补记改写。

| 符号 | 候选唯一 owner / 决定 | 已确认的 tracked 调用点 | 明确依赖与未决项 |
|---|---|---|---|
| `_managed_runtime_order_id`（private helper） | Backtrader Store adapter；**迁移**为框架侧稳定 identity helper。 | CTP bridge `_identity()` 调用，`ctp_managed_projection_bridge.py:202`；旧 canonical order validator 也调用，`managed_execution.py:708`。 | 保持 `backtrader.managed.runtime-order-id.v1` 域前缀、scope key 规范形状、intent id 校验及哈希输入逐字节兼容；I52 新 SDK 是否继续接受该 runtime-order-id 合同、scope key 版本 owner 尚未确认。 |
| `ManagedExecutionBindingError` | Backtrader Store adapter 错误合同；**先显式映射，再退役**旧异常类，不保留旧名 shim。 | 旧 strict helper 会抛出此类型；CTP bridge `submit_order()` 在 `_identity()` 失败后只设置 `managed_local_reject` 并 bare `raise` 原异常，见 `ctp_managed_projection_bridge.py:381-389`，因此类型可能透传给 Store caller。当前 bridge 自身导入 `ManagedExecutionAdapterError`（`ctp_managed_projection_bridge.py:25-33`）尚不表示已映射。 | 在 Store boundary 明确转译到 Backtrader adapter error contract，保留稳定且脱敏的错误分类并区分 local-reject 与 durable UNKNOWN；translating caller paths、外部对旧异常类型/字段的消费仍待全 A0 调查。 |
| `CtpQueueReceiptState` | Backtrader Store adapter；**退役**此旧 enum。 | 只由旧 classifier 构造 `UNKNOWN`/`REJECTED`；当前 CTP bridge 使用本地 `CtpManagedProjectionState`，不会读取旧 enum。 | 外部直接 import 未知。局部投影状态继续由 Backtrader Store adapter 的 typed projection 合同表达；队列收据不得被称为 provider ACK。 |
| `CtpQueueReceiptClassification` | Backtrader Store adapter；**退役**此旧结果 DTO。 | 旧 classifier 创建结果；当前 bridge 在 `ctp_managed_projection_bridge.py:352-357` 调用 classifier 但丢弃返回值，只依赖严格校验失败时拒绝进入回执持久化。 | 外部直接消费未知。迁移保留有调用者依据的 envelope 校验；不因当前 caller 未读取返回值而声称所有消费者已清点。 |
| `classify_ctp_queue_receipt` | Backtrader Store adapter；**迁移**为本地队列回执 validator，按需要不再返回旧 DTO。 | `_dispatch_or_replay()` 延迟导入于 `ctp_managed_projection_bridge.py:299`，校验于 `352-357`；成功后 `record_managed_queue_receipt`，失败后路径转 durable UNKNOWN，见 `358-379`。 | 保留 exact fields、typed `queued`、回执/订单身份、优先级、队列深度及 rejected error 的校验；队列 enqueue 证据仅为本地收据。SDK outbox 决定与持久化由 SDK owner负责。 |
| `CtpManagedExecutionAdapterPlaceholder` | Backtrader Store adapter 负责 fail-closed CTP Store 边界；旧 placeholder **退役**。 | 旧 `bind_managed_execution()` 为 CTP Store 构造它，`managed_execution.py:3284-3296`；其并不提供可写授权。 | 新 `CtpManagedExecutionProjectionAdapter` 仍需被 composition 显式注入一个符合 Store outbox port 的 authority；当前源码本身不证明该 SDK authority 或 CTP 写准入已完成。缺少时继续明确拒绝，不回退 direct/mock。 |
| `strict_limit_intent_from_order` | Backtrader Store adapter；**迁移**框架 Order 到 typed intent 的严格绑定/验证责任。 | CTP bridge `_identity()` 调用于 `ctp_managed_projection_bridge.py:194-216`；旧 aggregate bridge 默认绑定及调用位于 `managed_execution.py:1224,1319`。 | 保留明确 LIMIT、scope、instrument、side、quantity/price、position effect、reduce-only、intent/signal/metadata version、instrument metadata digest、quantity unit 与 typed SDK intent 的一致性。CTP bridge 当前丢弃该函数返回的 intent，只用它作校验；新的 SDK request 构造/消费点须由 runtime/SDK owner 明确，不能推定已传递该 intent。 |
| `observation_from_store_response` | Provider connector/adapter 是 raw venue response normalization 的候选 owner；本轮 **暂不迁移，I52 caller/具体 adapter owner 待 A1 与 provider 清点确认**。SDK execution 只拥有返回的 typed `ProviderObservation` DTO/state 合同。 | 旧 `ManagedExecutionBridge` 默认绑定 `managed_execution.py:1225`，接受响应后调用 `1354`；旧 helper 读取 status、provider order id、filled quantity、average price 与 fee；本轮所核 CTP outbox bridge 未调用它。 | `bt_api_execution/src/bt_api_execution/facade.py:54,135-147` 将 injected dispatch 类型定义为 `OrderIntent -> ProviderObservation`；facade 不导入交易所或做网络 I/O，调用方在 durable claim 后提供 normalized observation。I52 实际 venue adapter/caller 未核；不得把 raw payload 解析塞入 execution facade。 |
| `strict_cancel_intent_from_order` | Backtrader Store adapter；**迁移**框架取消请求到 typed cancel intent 的 identity/scope 校验。 | 旧 aggregate bridge 默认绑定 `managed_execution.py:1227`，取消路径调用 `2727`；当前 CTP bridge 自己构造 `CtpManagedCancelDispatch`，`ctp_managed_projection_bridge.py:206-212`，不调用此 helper。 | 保留取消 intent identity 与原 order scope 绑定；SDK 对 cancel command/receipt/UNKNOWN 的合同及本轮实际使用该 API 的 I52 caller 未证实。 |
| `cancel_observation_from_store_response` | Provider connector/adapter 是 raw venue cancel response normalization 的候选 owner；本轮 **暂不迁移，I52 caller/具体 adapter owner 待 A1 与 provider 清点确认**。SDK execution 只拥有 typed `CancelObservation` DTO/state 合同。 | 旧 `ManagedExecutionBridge` 默认绑定 `managed_execution.py:1228-1230`，响应处理调用 `2737`；旧 helper读取 provider-order identity 与 status；本轮 CTP outbox bridge 未调用它。 | `bt_api_execution/src/bt_api_execution/facade.py:54,135-147` 表明 execution facade 接收已 normalized observation，并把 dispatcher failure 归入 UNKNOWN。I52 实际 cancel venue adapter/caller 未核；撤单确认不得从本地队列回执推断。 |
| `project_record_to_store_response` | Backtrader Store adapter；**迁移**execution record 到 Backtrader Store response 的投影。 | 旧 aggregate bridge 默认绑定 `managed_execution.py:1226`，在 `1358` 调用；新 CTP bridge 的 port 文档指定由 typed projection DTO 生成 Store response，见 `ctp_managed_projection_bridge.py:91-97`。 | Store/Broker projection 只能投影被 SDK authority 证明的事实；保持 UNKNOWN/PENDING 不带 provider id/ACK/fill。新 SDK DTO 到现有 Store response 的字段映射待适配轮核对。 |
| `project_cancel_record_to_store_response` | Backtrader Store adapter；**迁移**cancel record 到 Backtrader Store response 的投影。 | 旧 aggregate bridge 默认绑定 `managed_execution.py:1231-1233`，在 `2743` 调用；所核新 CTP bridge 不调用该旧函数。 | 保持撤单事实来源于 SDK typed record；当前新 paper/live caller 和 DTO 形状未证实，不能因旧函数存在而声称支持撤单。 |
| `ManagedExecutionBridge` | **退役整个旧聚合类**；framework Order/Store 投影由 Backtrader adapter 承担，provider wire-to-observation normalization 由明确的 venue connector/adapter 承担，SDK execution 持有 observation DTO/state 与 durable authority，装配由 bt-api-runtime 承担；不把整类搬入任一 wheel。 | 旧 `bind_managed_execution()` 对非 CTP Store 构造它，`managed_execution.py:3296`；其 callback defaults 见 `1224-1233`，处理 submit/cancel 的调用见 `1319-1358,2727-2743`。 | 旧类耦合 framework order mapping、provider response normalization、SDK calls/observations、Store response 与 projection journal；各拆分 owner 的实际 I52 caller 尚未完整清点。不得用类级复制建立第二个订单/账户事实权威。 |
| `bind_managed_execution` | bt-api-runtime composition；**迁移**解析后 runtime-to-Store 的受控装配。 | 旧定义校验 `EffectiveRuntimeConfig` 与 runtime contract 后选择 bridge/placeholder，并调用 `store.attach_managed_execution_adapter`，见 `managed_execution.py:3200-3301`；已检查材料未证明其在旧模块之外的直接调用者。 | 新 composition 必须只注入已验证依赖并保留 Store startup 前显式 attach、profile/contract/scope/provider 匹配、无 fallback；A1 配置合同和 SDK runtime API 不在本补充中定义，旧调用者仍需全 A0 caller 调查。 |

上述决定是局部 source-owner 候选，不表示任何 helper 已迁移、authority 已存在、CTP/paper/live route 可用或旧产品可立即删除。对这 14 项以外的 root export、CLI、动态/反射导入、其它示例以及外部 wheel/plugin/operator consumers，仍按全局 A0 与 I52-D 继续逐项调查。

### 3.3 `backtrader_runtime` 包级 `__all__`（85 项）

下列 root names 全部来自当前 HEAD 的 literal `__all__`；只有 `dispatch_configured_runtime`、`dispatch_registered_runtime` 和 `resolve_runner_effective_config` 通过 `__getattr__` 延迟载入 runner，其他名称在包初始化时绑定。此列表不是 I52 的承诺，需按新合同筛选。

```text
CONFIG_EXISTS, CONFIG_FILENAME, CONFIG_REQUIRED, CONFIG_SCHEMA_UNSUPPORTED,
CONFIG_SCHEMA_VERSION, BootstrapRuntimeSetItem, BootstrapRuntimeSetResult,
ENVIRONMENT_MISMATCH, EffectiveRuntimeConfig,
ITERATION41_007_CTP_REGISTRATION, ITERATION41_007_CTP_RUNTIME_DIR,
ITERATION41_007_CTP_STRATEGY_ID, ITERATION41_012_1_REGISTRATION,
ITERATION41_012_1_RUNTIME_DIR, ITERATION41_012_1_STRATEGY_ID,
ITERATION41_012_2_REGISTRATION, ITERATION41_012_2_RUNTIME_DIR,
ITERATION41_012_2_STRATEGY_ID, ITERATION41_013_1_REGISTRATION,
ITERATION41_013_1_RUNTIME_DIR, ITERATION41_013_1_STRATEGY_ID,
ITERATION41_013_2_REGISTRATION, ITERATION41_013_2_RUNTIME_DIR,
ITERATION41_013_2_STRATEGY_ID, ITERATION41_013_3_MANAGED_REPLAY_RUNTIME_ID,
ITERATION41_013_3_STRATEGY_ID,
ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_RUNTIME_ID,
ITERATION41_CTP_MECHANICAL_MANAGED_REPLAY_STRATEGY_ID,
ITERATION41_015_REGISTRATION, ITERATION41_015_RUNTIME_DIR,
ITERATION41_015_STRATEGY_ID, ITERATION41_EVIDENCE_SCHEMA_VERSION,
ITERATION41_REPLAY_RUNTIME_SET, MIGRATION_REVIEW_REQUIRED,
ManagedExecutionBindingError, ManagedExecutionBridge, MODE_PRESET_MISMATCH,
PRESET_POLICY_VIOLATION, PRESET_REGISTRY, PresetPolicy,
ProviderSessionPreflightBinding, ProviderSessionPreflightRegistration,
RegisteredRuntime, RuntimeConfig, RuntimeConfigError, RuntimeProfile,
RuntimeRegistry, RuntimeSet, RejectingTestExecutionProfileVerifier,
REVIEW_REQUIRED, Iteration41ReviewEvidenceBindings,
Iteration41ReviewEvidenceError, Iteration41ReviewEvidenceObservation,
bootstrap_runtime_config, bootstrap_runtime_set, bind_managed_execution,
cancel_observation_from_store_response, default_runtime_registry,
dispatch_configured_runtime, dispatch_registered_runtime, load_runtime_config,
observation_from_store_response, project_cancel_record_to_store_response,
project_record_to_store_response, iteration41_runtime_registry, preset_names,
resolve_runtime_config, resolve_runner_effective_config,
resolve_iteration41_review_evidence_bindings, select_bootstrap_preset,
strict_limit_intent_from_order, strict_cancel_intent_from_order,
validate_runtime_config, TestExecutionPreflightContext, TestExecutionProfile,
TestExecutionProfileError, TestExecutionProfileObservation,
TestExecutionProfileVerifier, canonical_test_execution_profile,
parse_test_execution_profile, test_execution_profile_sha256,
validate_provider_session_preflight_binding, validate_test_execution_profile,
validate_iteration41_review_evidence,
validate_registered_iteration41_review_evidence
```

### 3.4 CLI、配置、异常和序列化迁移面

| Surface | 当前 tracked 事实 | owner / 状态 / 下一步 |
|---|---|---|
| 安装入口 | `setup.py` 的 `find_packages` 收入 `backtrader_runtime` 与 `backtrader.runtime`；console script 为 `bt-runtime=backtrader_runtime.cli:main`；两个 `__main__.py` 分别支持新/旧 `python -m` | Packaging owner 待定；检查目标发行包与安装消费者后再变更 package list/entrypoint |
| CLI 命令 | `bootstrap`; `prepare-ctp-config`（旧 alias `prepare-ctp-simnow-config`）；`collect-evidence`; `validate`; `doctor`; `check-ctp-fronts`; `run`; `preflight`。`run` 另有 `--confirm-live`、`--full-report`；另有 `--strategy-dir`、bootstrap `--runtime-set`/`--preset`、CTP `--source-env`/`--source-yaml`/`--source-collector-yaml`/`--runtime-id` | 老 CLI owner / 待核；确认各示例真实静态消费者、operator-only 子命令是否退出 runtime、不能把 `--confirm-live` 当权限升格 |
| Schema v4 | `config_schema_version`, `strategy`, `runtime`, `parameters`, `secrets_ref`, `ctp`, `ctp_simnow`, `ctp_production`；`strategy` 仅 `id`，`runtime` 仅 `mode`,`preset`。未知字段拒绝；旧 remote/gateway 字段命中 `MIGRATION_REVIEW_REQUIRED` 路径。真实配置值未读取 | 旧 parser owner；A1 定唯一新 schema owner，逐字段迁移或显式拒绝，不平移 `mode/preset` 字符串 |
| Preset | `local_backtest`; `replay`; `shadow`; `paper`; `sandbox`; `managed_live_direct`; `managed_live_gateway`。旧 `paper` 是 `simulation/public_read/local_simulation`，可有 hypothetical fills，不是外部模拟账户；`managed_live_*` policy 具外部写/审批字段，但默认可运行 registration 未由本扫描证明 | I52 新 mode 为 `replay/shadow/paper/live`，只实现/验收 paper/live；旧 `paper` 必须显式隔离，旧 live preset 名不授予能力 |
| RuntimeConfig projection | dataclass 字段：`strategy_dir`, `source_path`, `strategy_id`, `mode`, `preset`, `parameters`, `secrets_ref`, `config_digest`, 私有/隐藏 `ctp`, `ctp_simnow`, `ctp_production`, `_source_file_identity`；`as_public_dict()` 输出 strategy/runtime、`parameter_keys`、脱敏 `secrets_ref`、digest；`parameter_dict()` 返回 detached 参数 | 配置向后兼容 surface；注意 generic dataclass serialization 会暴露私有 CTP 子对象，迁移时保持脱敏/禁止泛化序列化 |
| Config seal / credential | config source identity/seal 绑定解析后的 config 与 registration；`ResolvedRuntimeCredentials` 只投影 runtime/provider/environment/mode/preset/account_access、credential name/count 与状态布尔，raw `_values` 不在 repr/投影；对象不能 truth-test，也不赋予 provider/preflight/execution/write authority | 需与 SDK `backtrader_runtime_sha256` 合同协调；禁止把 resolver result 当账户授权，明确 package source digest owner |
| Error wire | 七个 code：`CONFIG_REQUIRED`, `CONFIG_SCHEMA_UNSUPPORTED`, `MODE_PRESET_MISMATCH`, `PRESET_POLICY_VIOLATION`, `ENVIRONMENT_MISMATCH`, `CONFIG_EXISTS`, `MIGRATION_REVIEW_REQUIRED`。`RuntimeConfigError.as_dict()` 输出 `error_code`, `message`，可选 `field_path`,`reason`；CLI JSON 还固定排序/ASCII | error owner 待定；消费端兼容 code/reason 和字段路径，避免包含输入值/凭据 |
| 版本化 wire / journal | provider deployment receipt `bt-provider-deployment-receipt/v2`; test execution profile `bt-test-execution-profile/v2`; review evidence `bt-api-deployment-evidence/v1`; `FrameworkProjectionJournal` SQLite metadata schema `1`; config schema `4`；evidence bundle 独立 `EVIDENCE_SCHEMA_VERSION` | 迁移计划需分别列 schema version、canonical JSON、严格字段集、摘要和保留期；目前未发现 I52 版本转换器，保持待核 |
| 默认权限/dispatcher | 旧 CLI 将解析/校验/registry/runner 串接；`--confirm-live` 仅确认既有审批合约。旧 preset 注册不证明默认有 paper/shadow/live runtime；当前能否实际运行和外部消费都待核 | A1 重新列能力矩阵；任何未登记/未知路由必须 fail closed，无 direct/mock fallback |

## 4. Backtrader tracked 静态引用（抽样的高价值入口；非全量调用图）

只保留能说明迁移依赖的静态入口。已有 `A0-runtime功能与调用清单.md` 可作历史背景，但其基线为较早 HEAD；本节以本页 §1 当前 HEAD 为准。

| 调用点 | 确认内容 | owner / 状态 / 下一步 |
|---|---|---|
| `backtrader/stores/ctp_managed_projection_bridge.py:194-216,299,352-389` | `_identity()` 延迟导入旧 `_managed_runtime_order_id` 与 `strict_limit_intent_from_order`；`_dispatch_or_replay()` 校验回执后记录或转 durable UNKNOWN；`submit_order()` 对 identity 失败只加 local-reject 标记并 bare re-raise 原异常 | 这些 Store 调用点的候选 owner/处置见 §3.2 补充；`ManagedExecutionBindingError` 仍可能是 caller-visible compatibility surface，注入的 runtime/authority contract 与 CTP 授权状态仍待对应 owner 单独证明 |
| `examples/_support/sample.py:36` | 从包 root 导入 runtime API | tracked sample helper；依赖 root `__all__`，按重整后的 sample/setup API 决定保留 |
| `examples/_support/ctp_legacy_example_support.py:70,647,685,729,764,814,833,867` | 多处延迟调用 `legacy_direct_execution_error` | 示例 direct gate；逐例核查是否只拒绝旧入口，防止变成无意 live fallback |
| `examples/unified/007_ctp/**/run.py`, `007_ctp/run_runtime.py:26` | legacy helper 与 package-root runtime dispatcher 引用 | 007 旧入口/CTP 迁移输入；按每个 run variant 另核 Feed/Broker/Store 和写权限 |
| `examples/unified/012_1*/run.py`,`012_2*/run.py` 与 `run_runtime.py` | `service_observation`、cross-exchange observation、package-root runtime imports | observation/旧登记入口；区分 read-only 观察与交易 runner，不推断 active consumer |
| `examples/unified/013_1*/run.py`,`013_2*/run.py`,`013_3*/run.py`; `014_1*/service_live_backend.py`; `014_2*/legacy_runner.py`; `015*/service_live_backend.py`,`015*/run_runtime.py` | service observation、legacy wrapper 或 runtime root imports | 按 A0 总清单逐示例核对其 mode、provider 产品、Feed/Broker/Store 和读写能力；此表不替代逐目录审核 |
| `examples/unified/028_alpha003_simnow_minute/protected_simnow.py:14-38` | 直接引用 capability import guard、config、credential resolver、artifact provenance、front probe、sandbox admission、CTP readonly runtime、inventory 和 registry | paper/live 候选保护边界；须逐函数核对与同一 Strategy/Cerebro 适配关系，不能仅因有受保护路径而宣称已验收 |
| `backtrader_runtime` 包内部及 `tests/unit/runtime`, `tests/unit/stores` | CLI、config、credential、registry、runner、managed execution、provider/evidence schema 有广泛静态 imports | 测试仅证明源依赖/假路径；本轮未运行，不推导能力或 PASS |

**残余待办：** 完整逐 import/callsite ledger、反射/字符串导入、所有 examples/live/certlib/optional16/scripts/tools/docs/tests 的生产与测试分类，仍属于总计划 A0，不在本小轮覆盖；不得用本表冒充完整调用图。

## 5. `bt_api_py` 与 21 个 SDK 子仓依赖扫描（历史全仓扫描快照）

下表的 `py` 数量、SHA、字面命中行数及 `bt_api_gateway` dirty/status 说明是原根仓 HEAD `a8ce5c9a4226748bbb377a5f4dd0b148aa454422` 时的扫描快照，不是当前全量状态。当前根仓 HEAD `805cd8de834c1a50d6665feb215c8a7ddd4b1a60` 仅核对了上方明确列出的两个父仓源码路径没有 HEAD diff 与工作区差异；21 个子仓的当前 HEAD/status、根仓 `.py` 总数、命中计数均未刷新。

| repo | HEAD | tracked .py | `backtrader_runtime` 命中行数 | 说明 |
|---|---|---:|---:|---|
| `bt_api_py` | `a8ce5c9a4226` | 903 | 15 | 直接依赖见下方；无 `backtrader.runtime` 或 `bt-runtime` 字面命中 |
| `bt_api_base` | `afcaf29edda1` | 162 | 0 | 未发现目标字面依赖 |
| `bt_api_binance` | `81d664d0eac4` | 130 | 0 | 未发现目标字面依赖 |
| `bt_api_bitget` | `250299634684` | 34 | 0 | 未发现目标字面依赖 |
| `bt_api_bybit` | `bedf4fbf44d0` | 29 | 0 | 未发现目标字面依赖 |
| `bt_api_coinbase` | `890eb62a698b` | 32 | 0 | 未发现目标字面依赖 |
| `bt_api_ctp` | `2b17a09b1c1b` | 180 | 3 | 一个实现字段、两个测试命中；详见下方 |
| `bt_api_dydx` | `52234d92293f` | 25 | 0 | 未发现目标字面依赖 |
| `bt_api_gateio` | `b2715921cee7` | 32 | 0 | 未发现目标字面依赖 |
| `bt_api_htx` | `826aecb94d7f` | 47 | 0 | 未发现目标字面依赖 |
| `bt_api_hyperliquid` | `dcdc0e2e286b` | 34 | 0 | 未发现目标字面依赖 |
| `bt_api_ib_web` | `6fb47390080a` | 39 | 0 | 未发现目标字面依赖 |
| `bt_api_kraken` | `f71875eb9a47` | 28 | 0 | 未发现目标字面依赖 |
| `bt_api_mexc` | `898a81fb6099` | 30 | 0 | 未发现目标字面依赖 |
| `bt_api_mt5` | `f17403e7bd2c` | 5 | 0 | 未发现目标字面依赖 |
| `bt_api_okx` | `11dfe0a93135` | 132 | 0 | 未发现目标字面依赖 |
| `bt_api_execution` | `6d151aaf809f` | 93 | 0 | 有大量自有 journal/source digest 身份概念；无 Backtrader runtime import/string |
| `bt_api_risk` | `51e232f0b5c8` | 73 | 0 | 有自有 `source_sha256` 维度字段；无 Backtrader runtime import/string |
| `bt_api_monitor` | `93e23f89abfa` | 39 | 0 | 有少量通用 source hash 测试字段；无 Backtrader runtime import/string |
| `bt_api_gateway` | `69040a72ed25` | 42 | 0 | HEAD 有自有 source digest 使用；dirty checkout 内容未读取 |
| `bt_api_transport_zmq` | `6d0e2a345577` | 14 | 0 | 未发现目标字面依赖 |
| `bt_api_runtime` | `b76039691892` | 0 | 0 | 无 tracked Python |

### 5.1 已证实的 SDK 直接兼容依赖

1. `D:/bt_api_py/bt_api_py/_ctp_credential_binding.py`（HEAD）定义 `_ADAPTER_MODULE = "backtrader_runtime._ctp_credential_binding"`，在 `create_ctp_credential_binding_verifier` 路径用 `importlib.import_module()` 动态载入 `backtrader_runtime` 与该 adapter；其检查 package/module 文件与 `__spec__.origin`、adapter 类型/模块名、实现文件来源一致，并计算 package Python/native manifest SHA。scope/result 字段含 `backtrader_runtime_sha256`。这是明确的跨仓 source-origin 和 credential-binding identity 依赖，不是仅文档提及。
2. `D:/bt_api_py/bt_api_py/bt_api.py:4870` 把 verifier 的 `package_sha256` 写入绑定快照 `backtrader_runtime_sha256`；同根测试在 `tests/bt_api_contract/test_ctp_execution_approval.py` 构造该 adapter 与 source hash 预期。
3. 当前 Backtrader HEAD 的 44 个 runtime Python 列表中**没有** `backtrader_runtime/_ctp_credential_binding.py`；因此 SDK 所 pin 的模块在当前 tracked Backtrader source 中不存在。状态：跨仓接口待实现/待核 owner；下一步必须与 Backtrader 和 bt_api_py owners 协调明确 adapter 定义、安装位置、hash manifest 和降级拒绝行为。此项不授权读取真实 credential 或运行验证。
4. `bt_api_ctp/src/bt_api_ctp/ctp/client.py:7374` 有 `backtrader_runtime_sha256` 绑定字段；`bt_api_ctp/tests/test_ctp_shutdown.py:731` 的测试用 `importorskip("backtrader_runtime.ctp_native_shutdown")`；另一处测试提供假的 SHA 字段。这里体现 CTP SDK 对 Backtrader package/source binding 和可选 native shutdown helper 的集成假设，尚不能证明当前 runtime package 提供 `ctp_native_shutdown`（该模块也不在当前 44 个 Python 路径中）。下一步核对固定 SDK/test owner 与预期发布包，不把测试 import 当生产证明。
5. 其余 20 个子仓：对 `backtrader_runtime`, `backtrader.runtime`, `bt-runtime` 与指定 CTP runtime credential symbols 的 HEAD tracked Python 字面扫描均为零。execution/risk/gateway 等 repo 中的 `source_identity`, `source_hash`, `source_digest` 多为其自身 journal/receipt 字段；不能从相同术语推断为 Backtrader package dependency。
6. 本轮定向核对 `bt_api/bt_api_execution/src/bt_api_execution/facade.py`（该子仓 HEAD `6d151aaf809f3040bda420ce73c9a7abb7371f1f`）：第 54 行将 `DispatchCallable` 定义为 `OrderIntent -> ProviderObservation`；第 135-147 行说明 façade 不导入交易所或做网络 I/O，调用方在 durable intent/admission/dispatch claim 后注入 dispatcher，调用异常会变为 `UNKNOWN`。这支持“SDK execution 拥有 DTO/state 合同，provider adapter 负责 venue response normalization”的边界；不是 I52 venue caller 已确认，也不是当前 SDK 全仓扫描结果。

## 6. Owner、决定与未证明范围

| 条目 | owner（当前/目标） | 状态 | 兼容依赖 | 下一步 |
|---|---|---|---|---|
| 旧 package exports、`backtrader.runtime` facade、CLI | 当前旧 runtime 模块；新 runtime owner 待 A1 冻结 | `待核` | root `__all__`, dynamic facade, `bt-runtime`, module entrypoints, tests/examples imports | 建立旧功能到新归属及调用方切换清单；外部 consumer 和反射未证明，不保留旧 API shim |
| schema-v4 / policy / seals / error JSON | 当前 `config.py` / `policy.py` / `registry.py` / `errors.py`；唯一新 parser owner 待定 | `迁移输入` | schema 4 field allowlists、mode/preset、digest/seal、七错误码及 redacted projection | A1 冻结版本迁移、拒绝和诊断字段；不读取 operator config 补推 |
| managed CTP projection | Backtrader Store adapter 拥有框架订单校验、Store 回执边界和 Broker 投影；SDK execution 拥有 observation DTO/state 与 durable authority；provider connector/adapter 拥有 raw venue response normalization（具体 I52 owner 待核）；bt-api-runtime 拥有配置绑定/组合 | `局部候选映射已列；整体迁移待核` | §3.2 补充逐项列出 14 个 Store 边界符号（含 1 个 private helper）；新 typed execution/authority 版本、provider adapter、composition caller、外部包消费者仍未核 | 按符号分轮迁移；保留 fail-closed 与无 fallback；未完成 SDK contract/调用者调查前不删旧包 |
| CTP credential/native identity | bt_api_py `_ctp_credential_binding.py` / Backtrader adapter 尚缺 | `阻塞待核` | package root, adapter module origin, Python/native manifest SHA, CTP shutdown optional import | 新增前由两个 repo owner 明确 adapter & package contract；不以 source/fake 证据替代真实 acceptance |
| CTP read-only/preflight/provenance modules | 旧 CTP ops modules；目标 capability owner 待定 | `待核/延期候选` | bounded config source, SDK/native identity, read-only session/preflight/provenance | 与 paper/live 最小纵切逐项匹配；不需要者移出可安装 runtime，历史 evidence 保留 |
| `_iteration41_*_fixture`、evidence/test profile | Backtrader historical fixture/support | `DEFERRED 候选` | 测试和历史证据路径 | 确认测试保全位置与包排除检查；不宣称运行能力 |
| 静态调用方/外部消费者/反射 | 本仓调用方由各示例/Store owner 负责；外仓由各 SDK owner 负责 | `未完整证明` | AST imports 与 git grep 字面结果只覆盖可见 source | 总 A0 完成全 examples/live/certlib/optional16/tests/tools/docs callsite 与安全 tracker 对照；外部安装消费另列 |

## 7. 限制和复核说明

本页没有列出真实配置的值、存在性、账户、凭据、实际 provider 状态、真实调用状态或运行权限。四个 tracked runtime package fixture 资源仅按文件名登记。AST 看不到 `getattr`/字符串拼接/import hook/第三方 entry-point、部署安装差异或外部私有消费者；source hits 只证明 tracked HEAD 中存在静态文本。SDK 的 broad source-hash 命中不等同 Backtrader source identity dependency。若后续发现 tracked HEAD 变化或 dirty source 被纳入，应重做对应小节并分别标明 HEAD 与 checkout，不覆盖本次基线。
