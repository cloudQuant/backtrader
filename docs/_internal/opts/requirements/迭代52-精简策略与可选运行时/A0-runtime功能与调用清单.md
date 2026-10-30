# I52-A0：旧 runtime 功能与调用清单（Backtrader runtime 子范围）

状态：A0 子范围调查草案；仅覆盖当前 Backtrader 仓库内 `backtrader_runtime/` 与 `backtrader/runtime/` 两个 tracked 路径，以及能从 tracked 源码直接确认的调用点。它不是 I52 全局 A0 清单，也不替代 `examples/live`、`examples/unified`、certlib、Optional16、bt_api_py/SDK、99 个正式 case 的逐项调查。

## 范围、方法与基线

只用当前 dev checkout 的 Git tracked 路径、tracked Python、setup.py、公开文档与公开测试做静态盘点。没有执行 CLI、pytest、账户/Provider 操作；没有读取真实 config.yaml、.env、凭据、私密捕获或任何未跟踪文件内容。运行配置的实际存在性、值、权限、消费状态和外部运行者均不在本清单的证据范围内。

观察基线：分支 dev，HEAD df3a61b9b49198e2ae80489e716d75d2ac1ddd42。调查开始时 tracked worktree diff 与 index 为空；已有大量未跟踪 .codex-tmp 内容，仅从 status 看过名称并原样保留。本文是唯一新建文件，未提交。可复核枚举为：

- git -c core.quotepath=false ls-files -- 'backtrader_runtime/**' 'backtrader/runtime/**'
- 结果 48 个 tracked 路径：44 个 Python 文件 + 3 个随包 YAML fixture + 1 个 CSV fixture。其中 backtrader/runtime 有 7 个兼容门面文件；backtrader_runtime 有 37 个 Python 文件和 4 个资源。
- 调用点用 git grep 对 tracked Python 路径检索 backtrader_runtime、backtrader.runtime、bt-runtime、具体模块 import；测试映射用 git ls-files，不因测试名推断实际账户验收。

标签：P/L候选＝有共享接口或当前 tracked 源调用，迁移前需保留并验证实际 paper/live 依赖；待核实＝调用的 mode、账户及当前活跃性未由此清单证明；延期＝只服务 replay/shadow/旧本地撮合或受保护 CTP read-only；测试/运维＝不是策略交易能力。标签描述归属决定的输入，不是 PASS。

## 模式与配置现况：旧合同不能直接当 I52 合同

证据：backtrader_runtime/policy.py:50-149、config.py:1437-1512、registry.py:1398-1545、runner.py:1153-1213。

| 旧 schema-v4 项 | 旧策略/路由含义 | 当前登记与 I52 处置 |
|---|---|---|
| mode=backtest / preset=local_backtest | local 环境，无 network、无外部写；独立回测用途 | 仅有一个随包本地 fixture registration；不是外部 paper。传统 Backtrader 回测不等于四种交易 mode。 |
| mode=simulation / preset=replay | offline，无 network、无外部写 | 默认 registry 登记 7 个旧示例回放入口；本轮 DEFERRED，不执行、不验收。 |
| mode=simulation / preset=shadow | public_read，可 network、read-only，无外部写、无 hypothetical fills | schema/policy 可识别，但默认 registry 没有 shadow runtime；本轮 DEFERRED。 |
| mode=simulation / preset=paper | public_read，可 network，order_route=local_simulation，account_access=public_read，无外部写，有 hypothetical fills | 这是旧本地撮合 preset，不是 I52 所指的 Provider 外部模拟账户。必须隔离并延期旧语义，不得把此项报作 paper 支持。 |
| mode=simulation / preset=sandbox | sandbox/private read，可 network，不允许外部写；可要求 private config | 007/013_3 CTP 私有只读配置与 preflight 边界；既非外部 paper，也非可下单 live。 |
| mode=live / preset=managed_live_direct | production/direct_provider；policy 描述允许 external/production writes，要求 execution+risk+monitor、approval、live confirmation | 当前默认 inventory 没有可执行 live registration；007/013_3 只把该 profile 显式登记为 unavailable。dispatcher 对 live 在导入注册绑定的应用 runner_module 前以 live_execution_admission_required 拒绝。 |
| mode=live / preset=managed_live_gateway | production/gateway；另要求 gateway 与 ZMQ capability | 只有 policy 定义，没有默认可运行 registration/runner；不可据 preset 名推导已交付。 |

旧 schema 的 mode 枚举是 backtest/simulation/live；replay、shadow、paper 是 simulation 下 preset，而非 mode。长期统一 mode 枚举为 replay/shadow/paper/live；I52 只实现、使用和验收 paper/live，replay/shadow 仅登记延期、不运行或验收。两者配置字段、序列化摘要、digest、参数与 secret-ref allow-list、来源 seal 均需明确迁移映射。

旧 run CLI 不接受 mode/preset/config 参数；选 mode 来自受登记配置的 runtime.mode/runtime.preset。BT_RUNTIME_MODE、BT_RUNTIME_PRESET、BACKTRADER_RUNTIME_MODE、BACKTRADER_RUNTIME_PRESET 等 override 会被拒绝。--confirm-live 只确认已审批配置，不能升权；runner 当前仍阻断 live。默认 registry 注释写“only reviewed offline replay runtimes”，但 inventory.py 同时把 local_backtest fixture 纳入默认 registry；需修正注释或确认登记归属，不能只靠注释分类。

## 公开安装、CLI、配置与注册入口

证据：setup.py:10-52,114-118；backtrader_runtime/cli.py:97-193,1379-1648；backtrader_runtime/config.py:36-38,1387-1512,1618-1759；inventory.py:49-340。

- 安装时 find_packages 收入 backtrader_runtime 与 backtrader.runtime；console_scripts 注册 bt-runtime=backtrader_runtime.cli:main。另有 python -m backtrader_runtime 及兼容入口 python -m backtrader.runtime。
- CLI 子命令：bootstrap、prepare-ctp-config、prepare-ctp-simnow-config（旧别名）、collect-evidence、validate、doctor、check-ctp-fronts、run、preflight。prepare/check/preflight 是 CTP 私有配置或只读检查；run 是受 inventory/registry 控制的 dispatcher。
- bootstrap 只对已登记目录或 code-owned runtime-set 工作；run/validate/doctor 不接受任意 config path、CWD 自动发现或 mode/preset 覆写。config loader 校验 schema v4、未知字段、mode/preset 对、注册、来源身份与脱敏摘要。
- setup.py 明确把 3 个 YAML 和 bars.csv 作为 backtrader_runtime 的 package_data 安装：local_backtest/config.yaml、managed_013_3/config.yaml、mechanical_p1b/config.yaml，以及 local fixture 的 data/bars.csv。它们属于随包测试/示例 fixture，不是 operator 的账户配置；本调查未读取任一 config.yaml 的内容。
- 当前 inventory：默认 registry 含 7 个 replay registrations（012_1、012_2、013_1、013_2、015、sample、007）、两个无 runner 的 CTP simulation/sandbox read-only registration，以及一个 package local_backtest fixture registration。两个 fake L2 managed replay registrations 位于单独的 iteration41_l2_fixture_registry()，不在默认 registry。不存在默认 paper、shadow 或可运行 live registration。具体身份见 inventory.py:105-340；测试对登记集合的断言见 tests/unit/runtime/test_runtime_config.py:201-335 与 test_runtime_runner.py:1728-1777。
- 旧 config.yaml 可在注册 runtime 目录内由 CLI bootstrap 首次创建；普通 runtime 配置内容、private config 的真实存在性与值均未读取。

## 48 个 tracked runtime 路径逐项分类

表中的“待核实”表示需由全量 I52 A0/调用方和实际合同确认；不表示功能不存在或已通过。路径集以 Git enumeration 为准。

### backtrader/runtime 兼容门面（7 个）

| 路径 | 职责、可见调用方/证据 | I52归属 |
|---|---|---|
| backtrader/runtime/__init__.py | star re-export backtrader_runtime；包级兼容 surface | 退役候选；tracked Python 未发现门面外的 backtrader.runtime import；需再查安装消费者/外仓。 |
| backtrader/runtime/__main__.py | 将 python -m backtrader.runtime 转给新 CLI | CLI 兼容入口；迁移后退役。 |
| backtrader/runtime/cli.py | backtrader_runtime.cli re-export | CLI 兼容模块；迁移后退役。 |
| backtrader/runtime/config.py | backtrader_runtime.config re-export | config API 兼容；字段与 seal 待映射。 |
| backtrader/runtime/errors.py | backtrader_runtime.errors re-export | 错误码兼容；保留映射到新错误合同。 |
| backtrader/runtime/policy.py | backtrader_runtime.policy re-export | 旧 preset 契约；paper 语义冲突必须显式迁移。 |
| backtrader/runtime/registry.py | backtrader_runtime.registry re-export | 注册/profile/digest API 兼容；来源和权限语义需保留。 |

### backtrader_runtime 公共、配置与分派模块（10 个）

| 路径 | 职责、可见调用方/证据 | I52归属 |
|---|---|---|
| backtrader_runtime/__init__.py | 导出 config/errors/policy/registry/managed-execution/CTP API；示例 run_runtime 调入包级符号 | 旧 public API；P/L替代面待逐符号核对。 |
| backtrader_runtime/__main__.py | python -m backtrader_runtime 入口，调用 cli.main | 公共 CLI；新入口完成切换前需保留。 |
| backtrader_runtime/cli.py | bt-runtime 命令 parser、bootstrap/validate/doctor/run/CTP 操作与错误投影 | P/L候选配置/操作入口；不是 live dispatcher 授权。 |
| backtrader_runtime/config.py | schema-v4 YAML 读取、严格校验、config seal、摘要、bootstrap 原子创建 | P/L配置字段迁移候选；I52 新 parser 所有者另定；不得复制/丢失 secret-ref/source seal。 |
| backtrader_runtime/errors.py | 稳定 RuntimeConfigError code/reason | 兼容/API 迁移；错误分类需列映射。 |
| backtrader_runtime/policy.py | 七个 preset 的环境、路由、网络/写权限、capability 与 approval 描述 | 旧 mode/preset 到 I52 mode/profile 的迁移源；旧 paper 必须标为 local-sim。 |
| backtrader_runtime/registry.py | directory/strategy/preset/profile allow-list、EffectiveConfig seal、resolve/bootstrap | P/L候选注册和权限来源；live 有明确 dispatcher gate。 |
| backtrader_runtime/inventory.py | 当前 code-owned runtime/profile/runtime-set 与 CTP 绑定 | 清理/迁移 blocker；保留当前示例 identity 和所有 unavailable 声明直至调用方切换。 |
| backtrader_runtime/runner.py | sealed effective config 到 code-owned runner 的唯一旧分派；source/capability import fences；live 拒绝 | current replay dispatcher 延期；source 身份与 live fail-closed 检查不可随删除丢失。 |
| backtrader_runtime/legacy.py | 阻止/诊断旧直接交易入口 | 被 007/012/013/014/015 tracked 示例引用；不是交易能力。须先迁移所有 import 或保留等价 fail-closed fence。 |

### 共享装配、安全与证据模块（11 个）

| 路径 | 职责、可见调用方/证据 | I52归属 |
|---|---|---|
| backtrader_runtime/capability_imports.py | 对 bt_api_* 来源根做受信 import fence；runner 与 028 protected_simnow 使用 | P/L装配边界候选；需迁移来源验证，不等于 wheel 签名。 |
| backtrader_runtime/credential_resolver.py | sealed CTP scope 的本地 credential resolve；不建 client、不连接、不授权写 | 028 protected_simnow 与 CTP read-only 链使用；CTP sandbox 私有功能，纸面外部账户适用性待核实。 |
| backtrader_runtime/managed_execution.py | managed SDK runtime 到 Backtrader Store/Broker 的投影桥与订单意图适配 | Backtrader stores/ctp_managed_projection_bridge.py 直接 import；当前共享调用必须保留/迁移；不证明 CTP managed write 已开通。 |
| backtrader_runtime/framework_projection.py | session-scoped framework 投影 receipt/去重机制 | 公开测试 test_framework_projection_source_events；与 Broker/Store 同名 projection seam 有关，是否有运行时调用需核实。 |
| backtrader_runtime/service_observation.py | 调用方持有 Gateway host，提供 SDK read-only observation/session | 012/013 run.py、014_1/015 service_live_backend、028 run.py 有 import；paper/live 行情组合候选，时钟/新鲜度与订单能力未由此模块证明。 |
| backtrader_runtime/cross_exchange_orderbook_observation.py | 两个 012 例子的双交易所 orderbook read-only observation | 仅见 012_1/012_2 run.py 调用；市场数据/交易时钟归属及本轮是否适用待核实。 |
| backtrader_runtime/provider_deployment.py | injected trust verifier 的离线部署 receipt 校验；默认 verifier fail closed | provider 部署准入候选；没有默认信任实现/实际 provider admission，状态待核实。 |
| backtrader_runtime/provider_preflight.py | sealed config 与 deployment receipt 的 offline preflight binding | future provider preflight 合同；不解析秘密、不建 session；是否迁移至新 runtime 待核实。 |
| backtrader_runtime/test_execution_profile.py | 短期、非权威的 sandbox test-execution profile/preflight observation | 测试/沙箱候选；不是外部 paper account 或 live permit。 |
| backtrader_runtime/review_evidence.py | 绑定已登记 config 与策略字节的离线 AI review evidence | 当前 CLI/审核辅助；只给 REVIEW_REQUIRED，不给 deployment/execution authority。 |
| backtrader_runtime/evidence_bundle.py | 收集代码指定的 Iteration 41 本地 JSON/JUnit 元数据，不读 config/凭据/网络 | 离线验收工具；迁移到 test/evidence 工具归属待定，不是 paper/live 交易运行时。 |




### CTP 专属/私有只读链（10 个）

| 路径 | 职责、可见调用方/证据 | I52归属 |
|---|---|---|
| backtrader_runtime/ctp_artifact_provenance.py | 对规定 CTP SDK 安装 wheel/RECORD 做 provenance 校验 | 028 protected_simnow 与 read-only composition 相关；若 CTP paper/live 重用须逐 wheel 重审，不把旧 pin 当新发布批准。 |
| backtrader_runtime/ctp_configured_front_check.py | CLI 配置 CTP front 的有限 TCP reachability 诊断 | CTP sandbox 运维诊断；不读账号、不登录、不授权；本轮延期。 |
| backtrader_runtime/ctp_front_pair_probe.py | 只在显式配置候选内选择可达 MD/TD pair | CTP 专属诊断；028 read-only 链调用；不是 live trading admission。 |
| backtrader_runtime/ctp_preflight.py | injected CTP read-only session 的有限摘要合同 | CTP 私有只读；与 test_execution_profile/provider_preflight 组合；不建立默认 SDK factory。 |
| backtrader_runtime/ctp_private_config_setup.py | 从显式 private source 构造受保护 CTP config；CLI command 调用 | 本地 operator/setup；私密读取发生在此处，A0 未读取输入；迁移前保护来源和权限合同。 |
| backtrader_runtime/ctp_sandbox_readonly_admission.py | 绑定 config、账户/品种范围和 CTP sandbox read-only admission | CTP sandbox；不含执行 authority；本轮非 paper/live 交易链。 |
| backtrader_runtime/ctp_sdk_market_readonly.py | 单一 admitted instrument 的 MD login/subscription/tick observation | CTP market read-only；不含 trader/execution client；本轮延期。 |
| backtrader_runtime/ctp_sdk_readonly.py | 用 SDK 做 CTP 账户只读查询 | CTP private read-only；credentials/native SDK/认证环境实际状态未在本调查核验。 |
| backtrader_runtime/ctp_simnow_operator.py | CLI 将 sealed 007/013_3 config 接到 CTP read-only preflight | 无 runner、无执行权；迁移前保留 operator read-only 入口记录。 |
| backtrader_runtime/ctp_simnow_readonly_runtime.py | 组合 config admission、credential/source checks、TD/MD read-only queries | 028 protected_simnow 等源链；不是 paper 外部模拟下单支持。 |

说明：此表列出的 10 个路径均为 CTP 专属；credential_resolver、capability_imports 和 provider contracts 在上表单独归类。

### Fixtures 与随包资源（10 个路径：6 Python + 4 资源）

| 路径 | 职责、调用方/证据 | I52归属 |
|---|---|---|
| backtrader_runtime/_iteration41_backtest_fixture/__init__.py | local backtest fixture package | 本地回测测试归属；非 paper/live runtime。 |
| backtrader_runtime/_iteration41_backtest_fixture/run.py | fixture runner，登记 local_backtest profile | DEFERRED/单独回测 fixture；integration 测试为 test_cfg05_v4_local_backtest_runtime.py。 |
| backtrader_runtime/_iteration41_backtest_fixture/data/bars.csv | 小型固定回测数据 | 仅 fixture 资源；随当前 wheel 发布但不是生产市场数据。 |
| backtrader_runtime/_iteration41_backtest_fixture/runtimes/local_backtest/config.yaml | 随包 local_backtest fixture 配置 | 已确认 tracked package fixture；内容未读取；应与生产配置完全分离。 |
| backtrader_runtime/_iteration41_l2_fixture/__init__.py | offline L2 fixture package | DEFERRED replay/local fake 测试。 |
| backtrader_runtime/_iteration41_l2_fixture/managed_013_3.py | 013_3 fake managed replay runner/provider | DEFERRED；仅由分开的 L2 fixture registry/测试绑定，不是 paper/live provider。 |
| backtrader_runtime/_iteration41_l2_fixture/mechanical_cycle.py | mechanical replay fixture 共享流程 | DEFERRED；只服务 L2 fake replay。 |
| backtrader_runtime/_iteration41_l2_fixture/mechanical_p1b.py | CTP mechanical fake managed replay | DEFERRED；不是真实 CTP trading route。 |
| backtrader_runtime/_iteration41_l2_fixture/runtimes/managed_013_3/config.yaml | 随包 L2 replay fixture config | 已确认 tracked package fixture；内容未读取。 |
| backtrader_runtime/_iteration41_l2_fixture/runtimes/mechanical_p1b/config.yaml | 随包 L2 replay fixture config | 已确认 tracked package fixture；内容未读取。 |



## 已观察到的 tracked import/callsite（非全仓生产验收）

- backtrader/stores/ctp_managed_projection_bridge.py:194,299 从 backtrader_runtime.managed_execution 导入；它是目前明确的 Backtrader core/store 依赖，删除旧 runtime 前必须有可核验替代。
- examples/unified/007_ctp 下的 backtest/live runners、ctp_example_support.py 和策略导入 backtrader_runtime.legacy；012_1/012_2/013_1/013_2/013_3/014_1/014_2/015 的历史入口也有 legacy fence。它保护旧 direct 路径，不等于当前入口已被实际使用。
- examples/unified/012_1、012_2 的 run.py 调用 cross_exchange_orderbook_observation 与 service_observation；013_1/013_2/013_3 run.py 调用 service_observation；014_1/015 service_live_backend 调用 service_observation；028 protected_simnow.py 使用 capability_imports、credential_resolver、CTP artifact/front/admission/readonly 模块。I52 总体必须逐例确认这些是否仍属活跃 paper/live 生产链，不能从路径名或 mode 文本猜测。
- `backtrader.runtime` 门面外未检出 tracked Python 对 backtrader.runtime 的 import；这个结果不覆盖未安装消费者、外仓、打包后反射导入或运行态/动态 import。
- 来源身份/组件边界的现存集中点：runner.py 的 code-owned runner/source binding；capability_imports.py 的 bt_api import origin fence；ctp_artifact_provenance.py 的 CTP wheel/RECORD pins；config.py 与 registry.py 的 loader/effective-config seals。迁移必须逐项对照新 owner，不得通过关闭验证、替换测试样例或改写冻结 source hash 来“解决”。

## 公开测试映射（仅指出验证入口，不称通过）

| 子合同 | tracked 测试证据 |
|---|---|
| config/policy/registry/bootstrap/operator CLI/runner/live拒绝 | tests/unit/runtime/test_runtime_config.py、test_runtime_runner.py、test_runtime_operator_flow.py、test_runtime_operator_guidance.py、test_runtime_batch_bootstrap.py、test_runtime_live_dispatch_guard.py、test_runtime_package_import_boundary.py、test_legacy_remote_config_migration.py |
| package runtime / local_backtest fixture | tests/integration/test_cfg05_v4_local_backtest_runtime.py；tests/unit/scripts/test_iteration50_installed_fixture.py（安装包与 bt-runtime launcher 校验） |
| SDK import/credentials/CTP private read-only | tests/unit/runtime/test_capability_imports.py、test_credential_resolver.py、test_ctp_*（tracked 的 CTP operator、admission、preflight、artifact、front probe、SDK read-only、config setup tests） |
| managed execution/Broker/Store projection | tests/unit/runtime/test_managed_execution_bridge.py、test_managed_allocation_reader.py、test_framework_projection_source_events.py、tests/unit/brokers/test_btapibroker_managed_execution_projection.py、tests/unit/stores/test_managed_execution_store_adapter.py、tests/integration/test_btapi_runtime.py |
| service/orderbook observation | tests/unit/test_service_observation_session.py、tests/unit/test_scn02_012_orderbook_observation.py、tests/integration/test_scn02_013_service_observation.py |

调查未运行上述测试。测试中的 fake/provider/本地 replay、来源固定检查或拒绝路径不能表述成外部 paper-account/live 通过。

## 共享依赖、迁移阻塞与未确认事项

1. 旧 runtime 目前仍包含于 Backtrader 安装包；I52 删除前需迁移 setup.py 包、console script、module entrypoints、公开符号、异常与序列化/schema 合同，完成已知 tracked source callers 切换，并在安装消费者/外仓层面另做检索。
2. managed_execution 是 Backtrader Store 当前 source import；service_observation 是多个示例调用的 read-only SDK bridge；legacy 是多个旧 direct 示例的 safety fence。三个类别可能对 paper/live 迁移有价值，但当前本身没有证明外部模拟账户写入、订单回报、live readiness 或实际账户状态。由 I52 A0 逐调用方定 owner/适配轮次。
3. CTP config、credential resolver、SDK probes、read-only admission/queries 属于 sandbox/read-only，不可当作 live trade adapter；若本轮选择 CTP paper/live，需新合同及独立验收，否则移入明确 non-runtime 保留位置。
4. replay/shadow/local simulation fixtures、注册、测试输入与证据须明确从未来可安装 paper/live runtime 分离的位置和稳定来源；本轮禁止执行/本地行为验收。setup.py 当前仍随包发布这些 fixtures，属于后续迁移事项。
5. 外仓调用方、wheel/install consumers、插件反射/entrypoint imports、现场活跃 process、实际配置文件、账号与凭据来源未确认；本次调查没有读取 private inputs，也没有进行实际账户或网络验证。
6. 此清单不重新 adjudicate 12 PASS / 3 BLOCKED / 84 NOT_RUN 或 Optional16 0/16；历史正式 tracker/case 不在本子范围，任何源码与 fake 测试计数不得转换为正式通过数。

## 可自动复核的只读检查建议

后续每轮可在同一 dev checkout 运行以下只读盘点，再由审核者按输出更新条目；不得把不受信/未跟踪文件读入：

- 路径闭包：git -c core.quotepath=false ls-files -- backtrader_runtime/ backtrader/runtime/；校验 48 项及 44 Python/4 资源，新增/删除必须在本清单显式出现。
- 直接引用：git grep -n -E 'backtrader_runtime|backtrader\.runtime|bt-runtime' -- '*.py' '*.toml'；对新增/删减 import 做逐项 caller diff。若需限制目录，应分别检查 backtrader、examples/live、examples/unified、scripts、tests。
- 模式登记：静态对照 policy.py 的 preset -> mode/environment/routes/write flags、config.py mode/schema validator、inventory.py registration/profile sets、registry.py allow-list/resolution、runner.py final live gate；不得用仅搜索 mode 字符串代替配置/登记/派发闭环。
- 包装闭包：静态检查 setup.py package list、package_data、console_scripts 与两个 __main__.py；按结果校验 CLI/资源是否仍进入 wheel。
- 证据闭包：git ls-files tests/unit/runtime tests/integration；只记存在和用途，不执行测试就不写通过；真实环境/账户证据按原授权和 formal entrypoint 独立管理。

验收建议：新增 A0 后，请主代理复核本清单数字、补齐其他仓库/样例全部生产调用方，并确认 I52 owners/迁移/延期保留目录。当前这份 runtime 子清单接受级别为 source inventory only。
