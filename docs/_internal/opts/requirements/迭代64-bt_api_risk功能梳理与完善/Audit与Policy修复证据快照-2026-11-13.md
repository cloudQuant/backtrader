# 迭代 64：Audit 与 Policy 修复证据快照

日期：2026-11-13（本机时间）  
状态：**局部源码/模拟测试 PASS；整期 IN_PROGRESS / NO-GO**。

本文记录本轮提供的运行快照和本次只读核对，不是完整验收结论。Risk 为业务政策、账本和受信规则解析的 owner；SDK 负责服务组件与 Registry 装配，Web 只做有界响应检查。来源、账户权限或生产能力不能由本记录中的政策解析和模拟结果推导。测试运行后工作树仍可能变化，以下日志结果只对应各自运行时快照；日志本身没有完整命令行、逐文件版本和所有输入清单，不能仅凭本文独立重建全套运行环境。

## 本地提交与工作树

- Risk 本地 `dev` HEAD `6dd43a7a6909ad4b0de69c82587e54109a177b47`，提交 `fix(risk): validate policy reads with bounded identifiers`，只提交 `src/bt_api_risk/web/app.py` 和 `tests/test_risk_web_api.py` 两个文件。
- SDK 本地 HEAD `f7dfcb6323b2c694ea6947c1df71805dece09837`，提交 `build: update risk policy web validation`，将 Risk gitlink 更新到上述提交。这些是本地提交；未以此声称推送、发布或安装包验收。
- 核对时 Risk 的 `pretrade/policy.py`、`engine.py`、`ledger.py` 等及其相关测试仍是未提交 WIP；SDK `risk_service_component.py` 和 audit 合同测试也未提交。相关工作树还包含其他改动，不应把当前整个工作树视作上述两个提交的内容。
- Web 的独立 clean archive 测试在 Risk HEAD 的两文件覆盖范围得到 **187 passed**；这是隔离源码测试，不覆盖其他 WIP。

## Policy 与 Web 读取

已提交的 Web policy read 修复按明确的 policy-v1 策略和品种映射位置识别动态 identifier，避免对其一般性子串规则产生不必要拒绝；递归扫描仍作用于子项，精确敏感键仍拒绝，整个响应还要检查合同形状。它依赖可信服务提供已授权、已校验的 policy，文档衍生的规则 allowlist 只用于形状校验，不授权规则或证明规则文件。伪装成动态 ID 的内容并未因这项检查获得来源可信度；合法 ID 若恰好命中精确敏感键仍可能误拒，不能承诺任意合法名称都能读回。

`policy_id` 读取要求非空、首尾无空白、可打印且最多 256 字符，允许满足合同的 Unicode；数值字段在规范化前按识别出的路径执行有界展开预算，避免小输入在固定小数展开时消耗无界资源。该预算是保守限制，服务此前接受的某些政策仍可能在 Web 读取时遭拒；标识符和自定义规则参数不作为数值统一展开。Web 请求体与 Risk 解析器的预算各有边界，不能把它们等同为通用权限或来源校验。

Risk 的 WIP 为 policy/exchange rules 的数值规范化设置各自 **1 MiB** 展开预算，约束 YAML merge 扩张，并在发布前生成有界快照，修复校验、摘要与发布使用不一致输入的问题。对应快照检查 **255 passed、7 deselected**。外部 `Mapping` 的读取不是原子快照，其方法可执行调用方代码，边界检查不是沙箱；并发修改和恶意或阻塞的实现仍需由调用方信任与隔离。超过新预算的历史政策可能无法重新解析或发布，应单独评估兼容和迁移，不能假定旧数据全部可用。

## Audit 读取合同与限制

WIP 将 audit 查询限制为 `after` 有效游标及 `limit` 1–1000，成功返回所请求的完整页面；页无法装入时拒绝并保留游标，而不是成功返回短页让旧客户端误认为 EOF。调用方需自行用较小 limit 重试；系统没有自动降页。单行不可表示或超限时不能靠缩页跨越；其他账户持续产生较长记录、消耗候选扫描预算也可能让目标账户长期无法前进。

响应错误包含 `risk_audit_record_too_large`、`risk_audit_page_too_large`、`risk_audit_corrupt`、`risk_audit_unavailable`、`risk_audit_number_unrepresentable`、`risk_audit_size_unavailable`；请求无效和未授权另用对应拒绝。Risk 侧读取/页面预算为 **768 KiB、100,000 节点、详情深度 14 层、100,000 候选行**，组件另有自己的响应节点预算。历史数据中的负零整数 token `-0`、NaN、无穷大或无法无损表达的数字等（浮点 `-0.0` 有时可以保留），不能静默转换为看似正确的结果；不兼容历史行可能阻塞读取，须保留拒绝并处理历史兼容。

标准 Registry 提供结果大小检查，配置的 ServiceHost frame checker 还可检查封装帧；裸 Registry 中单独提供的 checker 不证明实际传输帧受限。缺少可用检查或有界 reader 时返回拒绝，不回退到无界旧读取。已知 GAP：非规范 TEXT scope 的异常可能漏检；SQL 层内部的内存和执行时间上界未由这些应用层预算证明。上限不会证明所有 SQLite 实现、数据分布或持续写入负载下的可用性。

## 验证记录与 SHA-256

| 证据 | 结果与范围 | 完整日志 SHA-256 |
|---|---|---|
| `/tmp/iter64-web-clean-archive.log` | Risk HEAD clean archive，Web 两文件限定切片：187 passed | `73b59dd0deffb85b1387f0bdb6ff91adadb431919599f4f6ec31fe3417e4058f` |
| `/tmp/iter64-policy-audit-snapshot-final2.log` | policy、audit 与 snapshot 局部 WIP 快照：255 passed，7 deselected | `2ad25f80af6f77c927ab94bff8b5593fd2c2c577b48689d3928866aa31a2ddac` |
| `/tmp/iter64-audit-last.log` | Web → Registry → 真实 Risk 服务组件 → 临时 SQLite 的本地联合切片：287 passed | `214e4758f164b92805b6bf954a4e74e679ecb7eeb5dcf4ceb7cc9cbd8f5ac7b3` |
| `/tmp/iter64-risk-full-after-policy-audit.log` | Risk 全套快照：1594 passed、578 failed、82 errors，命令失败 | `ac0e088cc7ee493afd467da180635ff56ee586fb4080b87e13e4d10794ba0890` |

联合切片使用本地模拟上下文和临时 SQLite，真实组件不等于真实 socket、真实账户或生产端到端。运行方报告该联合切片涉及的 15 个文件在运行前后 hash 一致；上述日志本身不包含这组逐文件 hash，本次未独立重建该快照。主会话报告全套与旧日志比较后，660 个 FAILED/ERROR 测试 ID 相同；本次仅核对新日志的数量和哈希，未独立复核旧日志或各失败根因。测试还报告 pytest 配置项 `asyncio_default_fixture_loop_scope` 未识别的警告。旧失败 ID 相同不能证明本轮没有行为回归，也不能把全套标为通过。

## 未完成验收

- **GAP**：活动订单共同来源切点、账户及日内事实、母子单授权和跨代未发送证明等仍缺失；默认自成交检查涉及的 Risk OPEN/CLOSE 路径继续失败关闭。
- **NOT_RUN**：本记录未运行真实 socket、真实账户或生产验收；未重跑上述测试，也未读取真实凭据、私有配置或操作现有 host。
- **NOT_RUN**：本机未发现 Windows PowerShell 5.1，无法在其默认读取方式下检查中文；本机 BOM、严格 UTF-8 解码及无替换符检查已完成并通过；该本地检查不能替代 Windows 读取验证。
- 后续应固定待验收源码与测试清单、保留完整命令和环境、定位全套失败并复测；分别补齐授权来源、历史数据兼容、真实传输和账户证据后再讨论相应验收。整期仍为 **NO-GO**。

## 2026-11-13 后续提交与 scope 扫描快照

Risk `7c88116` / SDK `23f60dcb` 的政策解析预算与 snapshot helper，及 Risk `718a79b` / SDK `e9584a98` 的政策发布快照均已本地提交；干净 archive 的限定测试分别为 **81 passed / 1 warning** 和 **105 passed / 1 warning**。上述较早记录中的 WIP 描述按当时快照理解；audit reader 与 SDK 接线仍是未提交 WIP。

最新范围键规范扫描消除当前窗口已测试的空白或键序导致的伪 EOF；合成测试中的合法极端 `U+FFFD` 字符及异常子类会返回 unavailable，游标已越过的历史行不能由此补回。100,000 行 / 16 MiB 工作预算下可能无法继续推进；SQLite 内部内存上界未证明，写锁约 0.9 秒仅为小样本观察，均为 **GAP**，不证明完整来源。联合本地测试 `/tmp/iter64-audit-final-pinned.log` 为 **313 passed / 1 warning**，SHA-256 `0bf34325cf735c69da26a0d40bacb11af69659f1cc49bfa45d4fd8fb2ca08c10`；主会话报告涉及的 15 个文件运行前后哈希一致，本日志不含逐文件哈希，本次未独立复核。该结果无真实账户或网络证据。并发修改中的 `/tmp/iter64-risk-full-after-scope-guard.log` 不作为固定快照；Risk 最终全套正在执行，结果待更新。临时日志可能被清理，整期保持 **NO-GO**。

## 2026-11-13 固定源码全套结果

Risk 最终固定源码全套 `/tmp/iter64-risk-stable-full.log`：**1620 passed、578 failed、82 errors，exit 1**；完整日志 SHA-256 `d44b5ae0ef3110765b15dedf31945dad67b3080c8cbd8bcbf63d756119fbd460`。选定 6 个源码/测试文件的运行前后 SHA 列表 `/tmp/iter64-risk-stable-before.sha` 与 `/tmp/iter64-risk-stable-after.sha` 经 `cmp` 一致；这不证明其他文件未改变。与此前 1594 passed 的完整历史快照比较，660 个 FAILED/ERROR 测试 ID 完全相同；ID 相同不能证明无行为回归。此前“全套正在执行”按记录时点理解。最新一致 audit 联合快照为上述 **313 passed / 1 warning**，是本地 fake 和临时 SQLite 证据，没有真实账户或网络验证。真实来源、CI 与发行仍为 **GAP / NO-GO**；临时日志可能被清理。

## 2026-11-13 已提交 audit 读取的后续快照

Risk `6efeb25` 的有界及规范 scope 审计读取、`0a1a47a` / `16cfd2f` 的说明，以及 SDK `b711f222` 的审计接线和 Risk gitlink 已本地提交；Risk 其他 WIP 保留。Risk 基线 archive 四文件 **362 passed**；SDK + Risk clean archives 四文件 **152 passed / 1 warning**，主会话日志 `/tmp/iter64-audit-committed-cross-check.log` SHA-256 `733bf0933e9661a3b440fea44942a57aece18c6f48ace9516c08e7026e0c5e2e`。这是 fake 身份、临时 SQLite 与 Registry 的本地切片，无真实 socket 或账户；临时日志可能清理。先前 audit WIP、非规范 scope 漏检和 313 passed 均按历史快照理解；当前扫描窗口检查 canonical scope 并拒绝异常，不能恢复游标已越过的历史行。100,000 行 / 16 MiB 预算、其他账户长间隙导致不能前进、极端合法 scope unavailable、SQLite 内部内存及持锁性能、旧客户端自动降页、超小帧、CI 和真实来源仍是 **GAP**。Risk 全套 **1620 passed / 578 failed / 82 errors** 是 WIP 固定运行，局部提交不改变失败或整期 **NO-GO**。

## 2026-11-13 UNKNOWN 与 facts cache 快照

Risk `646003b` / SDK gitlink `85c588a4` 已本地提交 Web UNKNOWN 回复去重、字段及固定点检查；主会话报告 Web **248 passed**、独立审查相关 **87 passed**，均为本地 fake。Risk/SDK UNKNOWN 有界读取仍为未提交 WIP：完整返回或有限拒绝，旧 opaque payload 返回 unavailable。原固定版本联合 **378 passed / 1 warning**（`/tmp/iter64-unknown-pinned.waq0jR/pytest.log`）为修订前快照，后续独立修订 **65 passed**；修订后当时的固定跨组件快照 **385 passed / 1 warning**（`/tmp/iter64-unknown-pinned.I0YDuY/pytest.log`，SHA-256 `a0a77607722941b2364cda106ca5590c173259c5cc7863b40d28b2f4954ba8be`），主会话报告 14 文件运行前后 SHA 一致。读取上限 10,000 项 / 768 KiB、全表 scope 扫描 100,000 行 / 16 MiB 及解析预算会影响历史兼容；无分页，SQLite native 内存和持锁、Python 3.9 未验证，结果不证明来源。SDK facts cache 已独立提交 `003ce35d`，主会话报告专项 **81 passed**、独立复核 **40 passed**，均为 fake；完整键核对仅是本地一致性，依赖 owner 线程约定，不能证明同一事件或来源。Risk `1776a0f` / SDK gitlink `32943baf` 已本地提交 `_gather` 三类完整 key 关联；主会话报告 Risk HEAD archive 新测试 **28 passed**、邻近规则 **19 passed / 4 deselected**，使用本机干净 Base，均为 fake。独立 WIP 当时固定快照另有 **162 passed**；后续 Risk `2e26324` / SDK gitlink `e1820025` 已本地提交 R02 bps 与 R08 off 的本地 fake 测试，主会话报告当前 Risk HEAD archive 的该测试文件 **36 passed**。source gate WIP 的两项另测未随此前 `_gather` 提交。全套历史固定运行仍为 **1620 passed / 578 failed / 82 errors**，13 项未验收，整期 **NO-GO**；临时日志可能被清理。Windows PowerShell 5.1 默认读取验证 **NOT_RUN**。

## 2026-11-13 Occupancy 算术隔离评估

临时 archive 的 occupancy 算术隔离专项 **50 passed / 1 warning**（UNIT/FAKE；`/tmp/iter64-occupancy-isolate.a1BqLX/target.log`，SHA-256 `ab54d8a92ff386884586f036b38912db0e69a5142a2829f5727cf655fc8da3cc`）。隔离补丁为 `/tmp/iter64-occupancy-isolate.a1BqLX/risk-occupancy-isolated.patch`，SHA-256 `d35353e83fc1e6db8b69505e329a985ceeef388a4cdea3228e29705aa84fa51e`；这些临时文件可能清理。在保留的隔离树中，重跑专项可从该目录用 `PYTHONPATH=src /Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest -q tests/test_pretrade_occupancy_decimal_isolated.py`；原运行命令与完整环境未随日志保存，重跑结果需单独记录。该补丁可能将部分低精度静默舍入变为异常；Registry 捕获异常不等于健康持久降级，既有 reservation 不能据此推断 NOT_SENT。HEAD 缺少 WIP 来源隔离，持久健康闭锁与重启恢复未证明，暂不建议独立交付，补丁保留 WIP。历史库、Python 3.9 与真实 host 均未验。另一次邻近回归被中断，不能计为通过；审查进程工具报告 KeyboardInterrupt，未留 OS PID 或明确退出码，之后进程表未见包含该临时目录或该组文件名的命令，仍不能证明全部子进程已清理，状态 **cleanup_unknown**。整期仍为 **NO-GO**。

## 2026-11-13 撤单状态新鲜度局部快照

SDK `013ad628` 已本地提交撤单状态新鲜度局部修复：查询失败、超时、拒绝、operation_id 不匹配、回复无效或状态矛盾时，当前查询返回 `None`，不回退旧缓存，也不触发撤单或重试。`OBSERVED` 仅含 Gateway 前 256 条和全部 counts，状态按 producer 合同校验；`NOT_FOUND` 仅原样传递可信有限回复。当时快照 **137 passed / 1 warning**，日志 `/var/folders/7d/hnmknylj1w91h3cvq6mh3thm0000gn/T/iter64-cancel-status-final4.bFWKiE/pytest.log`，SHA-256 `e52dea1e0adbc61951d2b3cd989ba774706aae437b5b0f578e424cb920324e11`；主会话报告独立复审 **131 passed**。均为 fake、临时 SQLite 和本地 owner / 合成 provider；超过 256 条仅 fake 覆盖，`last_cancel_status` 外部并发时序、实际多页、真实账户与来源及撤成均未证明。临时日志可能清理，整期仍为 **NO-GO**。

## 2026-11-13 规则插件异常处理局部快照

Risk `fa2243a` / SDK gitlink `b5feed39` 已本地提交规则插件异常处理：规则版本读取与比较、`evaluate` 和结果校验的普通异常固定返回 `DENY risk_rule_failed`，不吞掉 `KeyboardInterrupt` 或 `SystemExit`。干净归档专项 **16 passed / 1 warning**，日志 `/tmp/iter64-rule-failure.obEjgq9w/final2.log` SHA-256 `9388eb0d2d46e6ca164061e3933e84b23104a7018d2983995cdccb44d69fd661`；主会话报告独立复核 **14 passed**。两者均是纯 fake 插件，不证明 engine 审计、真实账户或整期通过；临时日志可能清理，整期仍为 **NO-GO**。

## 2026-11-13 64.07 / 64.08 受限 PACKAGE 快照

64.07 / 64.08 的受限 PACKAGE 快照：`/tmp/iter64-package-isolation.Z9FFTI` 使用 SDK `b5feed39`、Risk `fa2243a`、Base `b70e920`、Gateway `4688fda`、Execution `10685c`、Transport `47f3d26` 和 BT `47c649b` 构建 7 个 wheel；该目录保存 `wheel-sha256.txt` 与 `wheel-build.log`，不含当前 WIP。验证借用 Conda base 第三方依赖视图、`--no-deps`，以 `python -S` 排除全局 editable；这是受限 fake 证据。缺 Risk wheel 时 3 场景远端不可用拒绝且不回退 Gateway；假配置下缺包 host 启动在建立账本或 host 前 `ModuleNotFoundError`，非 CLI 验证。安装 Risk 后 direct fake 生命周期未观察到 Risk 导入或网络连接；屏蔽 numpy 仅验证 `pretrade` / `order_admission` 导入，未测准入或配置。Base/SDK 常规声明 numpy/pandas；离线普通依赖安装缺 numpy wheel 为 **BLOCKED**，不是干净环境通过。主会话报告独立只读审计已对筛选的 Python/pyproject 做 hash 与 Git blob 核对并以 `python -S` 重跑，不证明完整归档或可重复构建；普通解释器受全局 editable 污染，不能复现缺包。真实账户及生产 **NOT_RUN**，不能据此整体验收 64.07 / 64.08；整期 **NO-GO**。临时目录可能清理。

## 2026-11-13 运营组件联调快照

当前 WIP 测试 `tests/integration/test_iter64_web_real_host_integration.py` 使用真实 HTTP、CURVE、Registry 及独立 Risk/Gateway fake 进程，强制 `self_trade=true`，观察 `available=false`；实际低层独立 principal 请求得到服务端 `SCOPE_DENIED` 且策略版本不变，并验证 Web CSRF、成功 publish 审计和关闭重启隔离。结果 **1 passed / 3 warnings**，日志 `/tmp/iter64-web-real.nrL3D4/final.log` SHA-256 `24e6d74eecc3e547e27e62534282eef607b155efa2081cdd5a9c7ff30b8dd7a1`；同目录 before/after SHA 清单一致。主会话报告该测试自建 Risk 86282 / Gateway 86281 正常退出码 0，进程表无匹配，host/runtime 清理检查通过。Clean SDK `b5feed39` / Risk `fa2243a` 加精确依赖 archive 运行同测试 **FAIL**：`status.available` 实际为 true 而期望 false，后续 HTTP/ACL 步骤未执行；日志 `/tmp/iter64-web-clean-head.q6deej/test.log` SHA-256 `77536475d7277c3789f55c47e23fd318d2feb81b93787415ec477cbbf04c52fb`。主会话报告该测试自建 Risk 87256 / Gateway 87255 退出码 0 且进程表无匹配。`available` 仅表示注册健康，不是来源证明；测试仍 WIP，未下单且未断言拒绝审计。真实浏览器、账户和 provider **NOT_RUN**，不据此宣称 64.13 或整期完成，仍为 **NO-GO**；临时证据可能清理。

## 2026-11-13 正式 PyPI 普通依赖安装快照

正式 PyPI 普通依赖安装的新快照：固定的 7 个 wheel 及依赖进入 `/tmp/iter64-package-isolation.Z9FFTI/full-normal`，安装退出 0；Anaconda base Python 以 `-I -S` 仅加载 target。主会话报告目标 metadata 按默认 marker 检查 60 distributions / 108 active requirements，无缺失或版本不符，未请求项目 extras；NumPy 1.26.4、pandas 3.0.6、PyArrow 25.0.1，且明确安装了 numpy。fake direct 已运行，但仅观察到 Risk import / socket 事件为空；Risk/SDK 模块有限 import 通过。记录位于同目录 `install-full-pypi.log`、`full-normal-smoke-retry.log`、`full-risk-smoke.log`；首次 smoke 因 `/tmp` 与 `/private/tmp` 路径比较失败，修正后重跑。pip 与 base 关联的 73 行 incompatible 等警告未解决，不能等同全环境 `pip check`；`actual-command-provenance.txt` 是事后按调用记录转录的实际命令与 index，并非由日志自身证实。此前离线普通依赖安装 **BLOCKED** 保留为历史快照；新快照未覆盖 WIP、浏览器、真实账户或全部功能，64.07 无 numpy 行为未通过，整期 **NO-GO**。BT 旧 `risk.available` 表示 local route / transport，不能证明交易准入；WIP 当前 status false 与 local route true 可同时存在，不能据此推断实际放行。临时证据可能清理。

## 2026-11-13 64.13 运营测试拆分快照

64.13 运营测试拆分：SDK `a3032c35` 仅本地提交共用 helper 与通用 real-local HTTP/CURVE/Registry/Risk + fake Gateway 测试。提交前 clean SDK `adef9b4a` / Risk `fa2243a` archive 和 WIP 各 **1 passed / 3 warnings**；测试强制 `self_trade=true`，服务器返回 `SCOPE_DENIED` 且策略版本不变，覆盖 Web CSRF、成功发布审计、Web 重启和独立 admin/Risk 保活。`available` 仅校验 bool 一致性，不授予交易授权。独立且未提交的严格来源测试要求三次 `available=false`：clean archive 实际为 true，**1 failed / 1 warning**；WIP **1 passed / 3 warnings**，无 skip/xfail。四组日志及清单位于 `/tmp/iter64-web-split.Vt6fcD`，clean 和 WIP 各 11 个文件的前后 SHA 清单分别一致；主会话报告四组各自新建的 fake Gateway/Risk 均自行退出码 0、进程表无匹配。非真实账户、provider 或浏览器测试，未断言拒绝审计；临时证据可能清理。此前测试和提交均为历史快照，不据此宣称 64.13 或整期完成，仍为 **NO-GO**。

## 2026-11-13 只读混装风险与建议验证

只读混装风险，建议验证 **NOT_RUN**：BT `live` / `execution` extra 允许 `bt-api-py>=0.15.5`，旧 SDK `0fa07542` 的 `reserve_order` 不接受当前 BT WIP 的 `first_send_ticket`。源码显示 WIP 搭配旧 SDK 时 `NOT_SENT` → `REQUEST_DENIED` 可能将本次未送达误认为历史已决，不能据此认定旧键安全。版本号 `0.16.0.dev64` 可能对应不同源码与合同，需固定 commit / wheel，再以新旧 SDK ↔ Risk、BT ↔ SDK 双向混装及旧键、取消、来源门进行隔离 fake 验证；现有 WIP 测试不是混装证据。Risk 测试源码记载的负例显示旧 binary 持有连接时，测试性版本变更后仍可写；本轮未重跑，不能推断真实旧进程已排空。跨代来源与在途证明 **NOT_RUN**，整期仍为 **NO-GO**。

## 2026-11-13 旧 SDK 签名 fake 实测

BT WIP 新增未提交 `tests/unit/brokers/test_iter64_old_sdk_ticket_compat.py`，以旧 SDK commit `0fa07542` 的真实 `reserve_order` 参数 AST 核对替身。定向 **1 passed / 1 warning**，主会话报告独立复核 **1 passed**；在该 fake 中当前 BT WIP 持久化 Submitted intent 后传入 `first_send_ticket`，`TypeError` 向调用者传播，binding 为 `SUBMIT_UNKNOWN`，同订单/同 Feed 被阻断，两次假恢复仅读，未观察到 Risk/Gateway 写或 direct 回退。日志与清单位于 `/tmp/iter64-bt-old-signature-verified.RjE1EB`，`pytest.log` SHA-256 `35af42e3c87ca2bc32423158aa5db898061127c8a0dba28808053bd74fc408cf`，7 文件前后 SHA 清单一致；首次 AST 比较因遗漏类型注解失败，更正后重验。这是当前 SDK 对象加旧签名 fake，不是真正旧 SDK 完整模块或 wheel 混装，也不证明真实跨代结果；`TypeError` 兼容风险未修复，整期仍为 **NO-GO**。临时证据可能清理。

## 2026-11-13 Risk 来源隔离临时闭包实验

Risk `fa2243a` archive 的 v3-only、bounded UNKNOWN 与 L4 最小依赖临时闭包，在同一固定快照得到 **95 passed / 8 deselected / 1 warning**，另 L4 **5 passed / 1 warning**；选定 7 文件前后 SHA 清单一致。仅为临时 fake，未跑全量；8 项未选包括 3 个旧 writer / binary 子进程测试（含 kill 清理，未运行）和 5 个关闭隔离的 synthetic 分支。说明及实验材料位于 `/tmp/iter64-source-isolation.wovc8M/EXPERIMENT-README.txt` 与同目录 `EXPERIMENT-NOT-FOR-APPLY.patch`，后者 SHA-256 `20017d2c934d700a09a9b35ab25e946aca2404ce75ea89f38a183b5b326d2d54`；这是不可应用的实验材料，不得应用或提交。风险包括仅测试调用的无界 `all_permits`、Decimal 异常语义、缺 SDK 初始化不确定 fence / BT 恢复、L4 持久健康、旧 writer / 跨 host 和真实来源未证明；不证明准入或整期完成，保持 **NO-GO**。临时材料可能清理。

## 2026-11-13 首发票据兼容 WIP 固定快照

首发票据兼容最终固定快照仍为 WIP：SDK `gateway_api` 的 `risk_first_send_reserve_contract`，以及 BT 下单前对公开 `risk_selected` / config、同 facade 版本合同和绑定 `MethodType` 的严格检查均未提交。旧 SDK 缺合同或 Gateway facade 无明确 bool 时失败关闭，避免分配 seq、创建 intent、更改订单或发送；调用开始后异常保留 `SUBMIT_UNKNOWN`，不推断 NOT_SENT、不重试、不回退。预检之前已有 `binding.next_idle_read` 本地调度及 scope / 连接检查，不是完全无副作用；无 `risk_selected` 的旧 Gateway facade 兼容性受影响。SDK 同步重入修复防止 Risk 被清空后转 direct，保留 host 已有副作用。主会话报告 SDK 最终 **43 passed / 1 warning**、独立 **101 passed**，BT 最终 **245 passed / 1 warning**、独立 **245 passed**，另 SDK 专项 **20 passed**。BT 固定快照日志 `/tmp/iter64-bt-ticket-strict.Ub8JlE/pytest.log` SHA-256 `93df2a10b0f120ece94dd1c8ba2b0d8fe3b5b754d62a93f821e20d368b204e7c`，9 个选定文件前后 SHA 清单一致。较早跨仓 pytest 发生 `tests.conftest` ImportPathMismatch，0 项、rc 4；分别以各仓为 cwd 后通过，不能把早期运行计为通过。BT 四个相关文件的 Ruff 中 lifecycle 既有第 225 / 235 行 B017 仍存在；产品、新测试与投影测试 Ruff 通过，未改既有断言。真实旧 wheel、真实账户、线程并发及跨代来源 **NOT_RUN**，整期 **NO-GO**。临时日志可能清理。

## 2026-11-13 SDK + BT + host 票据合同 WIP 快照

SDK + BT + host 票据合同仍为未提交 WIP：host 公开本地无 I/O 声明绑定同一 host 的 save / create / consume，SDK capability 绑定同一份 host 合同，BT 使用其 `bound_save`。旧 host 缺声明时 SDK Risk reserve 返回 UNKNOWN、不回退；非 Risk 保留原路径。调用前后方法或 host 改变时有限拒绝或保留异常。保存后的真实 Broker + 临时 host 故障测试为 `RESTART_REQUIRED`，保留 intent、快照及 pending 通知；同进程 fake 重绑恢复 Submitted 并重放通知。8 个 Gateway / Risk / delegated fake 写端口 spy 已单独验证，在该故障测试中调用 0 次；不能外推任意写端口或真实重启。BT 当时固定快照 **280 passed / 1 warning**，`/tmp/iter64-bt-postsave-writes.LA7Mrv/pytest.log` SHA-256 `350230a4f8313a55f641c8140b1da76e01c1ce6b8d1ebb07ba65f759a84a5b48`，36 个选定文件前后 SHA 清单一致。主会话报告 SDK **211 passed**、独立 SDK **139 passed** / BT **84 passed** 及最终 spy 两项 **2 passed**，均按当时快照理解；首次 BT **277 passed / 1 failed** 因替换方法 spy 被新合同拒绝，改为可还原 profile 观察真实 consume 后通过。此前 245 结果保留为历史快照。真实旧 wheel、跨代、线程并发及账户来源 **NOT_RUN**，整期 **NO-GO**；临时证据可能清理。

## 2026-11-13 旧 SDK 混装受限证据

旧 SDK 受限混装 fake 实验 `/tmp/iter64-old-sdk-mix.Z8seAQ` 使用 SDK 旧 commit `0fa07542` 构建 wheel，Base `417a575` / Gateway `4688fda` / Execution `10685c`，BT 为 HEAD `2066e3050` 加 8 个 WIP 文件的临时源码副本，非 wheel；以 `-I -S` 显式借 Conda 依赖视图。执行方报告 `--no-deps`，但 pip 日志未保留完整命令，不能单凭日志确认。`final3.log` **2 passed / 1 warning**，SHA-256 `dd6b4ca108a174d00da997830df35ed1a925764cbc04d3ff01018f8b816aacb1`；10 文件前后 hash 清单一致并记录 4 个 wheel SHA，仅固定部分依赖。首次 `mix.log` 因 fake store 漏字段失败，修正后重验。真实旧 facade 缺票据合同，当前 BT 在新 intent / seq 前拒绝，8 个 fake 写 spy 未调用，旧 intent / record 保留；仅有一次自己的 fake cancel 和同进程 host 重开，不证明 delegated cancel、真实重启或账户行为。旧 wheel 单测 `_risk_not_sent(ROUTE_UNAVAILABLE)` → `REQUEST_DENIED/RISK_UNAVAILABLE`，不能证明历史键未发送；主会话报告独立 reviewer 只读核对路径及部分文件与 Git 一致。另 `/tmp/iter64-old-sdk-risk.xMh6aHBU/probe-pinned.log` **1 passed / 1 warning**，SHA-256 `dd917a8745ca159258a09adcbdb3ed98671021e611b1a763dfe9028e8988b741`：旧 SDK `0fa07542` 源码、Base `417a575` 与当前 Risk WIP / 临时 SQLite 中已存同键 RESERVED 时，fake STALE_EPOCH 使旧 SDK 确定拒绝而许可仍保留，Risk 直接与进程内 fake 路由为 UNKNOWN。主会话报告独立复核 **1 passed**，12 文件前后 SHA 清单一致；不是实际 Registry / socket 或旧 wheel 跨进程验证。真实混装与来源未验，整期 **NO-GO**；临时材料可能清理。

## 2026-11-13 旧 Registry epoch 进程内反例

进程内真实旧 Registry 的 epoch 反例：旧 SDK `0fa07542` / 旧 Base `417a575`，两个真实内存 Registry 独立注册合成 principal；将 Registry1 的注册 / epoch 投到 Registry2，实际返回 `STALE_EPOCH`，fake bridge 映射 `service_reply_code` 后旧 facade 为 `REQUEST_DENIED/RISK_UNAVAILABLE`。临时 Risk WIP SQLite 中同键许可拒绝前后完整相等且仍为 RESERVED；一次独立合成重试投 Registry1 的真实 handler 得到 UNKNOWN，fake Gateway / Risk 写为空。`/tmp/iter64-old-sdk-risk.xMh6aHBU/registry-pinned.log` **1 passed / 1 warning**，SHA-256 `a293683de99ecb6ae9276e1daf8257ec36f378bac6bca6c06035f3e606691a1e`，16 文件前后 SHA 清单一致；主会话报告独立复核复跑 **1 passed**，旧 `service_registry` 与注册 fixture 的 Git 对照一致。principal 由测试注入，bridge 非真实 `_rpc` 回复校验或 socket / CURVE，Registry 非独立进程或重启，旧 SDK 为源码而非 wheel；未证明真实账户或实际跨代发送，不能由该拒绝认定旧键未发送。此前 fake 异常记录保留为历史，整期 **NO-GO**；临时材料可能清理。

## 2026-11-13 旧 BT / 新 SDK 反向混装 fake 探针

反向混装固定 fake 探针 `/tmp/iter64-oldbt-newsdk.S6gthQjo` 使用已提交 BT `a37049a1` archive 与当前 BT WIP（覆盖 3 个产品和 2 个 fixture 文件）的两个隔离副本，搭配同一 SDK `a3032c35` archive + `gateway_api` WIP，使用实际 Broker、`GatewayBtApi` 和临时 host。fake reserve 的 UNKNOWN 构造历史 Submitted 后，注入 fake Risk status DENIED 与 Gateway unavailable；`broker.next` 中旧 BT 转为 Rejected 并持久化拒绝通知，WIP 保持 Submitted / RISK_RECOVERY_PENDING；UNKNOWN 对照保持 Submitted。另旧 host 缺合同经新 SDK reserve 保持 Submitted / SUBMIT_UNKNOWN，fake venue 无调用。`old-pinned.log` **3 passed / 1 warning**，SHA-256 `c658f30ece33e16e35ce23d7475cc31a5dbe33120a1f1db5e141dff55d3da874`；`wip-pinned.log` **1 passed / 1 warning**，SHA-256 `4bc1da3a10466c679f317a2884c991c6a829d769c9f94c9347483e4c27d23e44`；32 个指定文件前后 SHA 清单一致，只固定清单所列范围。主会话报告独立只读复核已检查真实导入路径及断言。Risk DENIED、行情和 Gateway 都是 fake，不能证明默认 Risk 会产生 DENIED、旧代确实在途、真实发送或跨进程重启；不是实际 wheel / socket / 账户全链验证，整期 **NO-GO**。临时材料可能清理。 上述 pinned 日志为较早快照；最终加强版 `final-old.log` **3 passed / 1 warning**，SHA-256 `60e78a36c39f2e403e90c6fca8f2722bd0ab2d4bb44a390355cd5c2238c3dadf`，`final-wip.log` **1 passed / 1 warning**，SHA-256 `2e5e582dc7463c228a9a12a6bfe0b1853c1060370198f37ee53fba7921c620de`，`final-before.sha256` / `final-after.sha256` 的 32 项一致；旧 host 对照的 8 个指定 fake 写端口均装 spy 且 0 次，不能外推其他端口。

## 2026-11-13 64.07 无 numpy 受限运行时快照

64.07 无 numpy 受限运行时快照：固定 wheel 的 `--no-deps` target 加 Conda 只读第三方依赖视图，Anaconda Python 3.11 以 `-I -S` 在产品导入前阻断 numpy；启动时无已载 numpy，工作流未请求或缓存 numpy，主动 import 负对照被拦截。实际执行合成 YAML / JSON policy、digest 与非法拒绝、fake R04 WARN / DENY / 版本错误、临时生成 CURVE keys 的合成 Risk config 加载，以及 wheel SDK `read_policy_files`；115 个已加载 SDK / Base / Risk 模块路径核验来自 wheel。最终脚本 `/tmp/iter64-package-isolation.Z9FFTI/policy_no_numpy_probe.py` SHA-256 `a8b3374a585ad9b22001fbb228e373f162aed84fba692d6d9a7004a8e60277be`，日志同目录 `policy-no-numpy-host-file.log` SHA-256 `f3d297f6e0ed3b5736e0ab61f4f12087c61a6724d8a999d7eec6f871400599b6`，rc 0。主会话报告独立复制临时环境复跑一致，阻断 socket connect / sendto 且未输出密钥。早期同名脚本已经更新，旧日志不能用当前 SHA 解释。该切片不是完整真实 PretradeEngine、服务或账户验证；Base / SDK 普通 metadata 要求 numpy，不是干净无 numpy 安装。此前无 numpy 仅导入和未整体验收的记录按历史范围理解；整期 **NO-GO**，临时证据可能清理。

## 2026-11-13 无 numpy fake PretradeEngine 快照

固定 Risk `fa2243a` wheel 的无 numpy fake PretradeEngine 实测：`/tmp/iter64-package-isolation.Z9FFTI/engine_no_numpy_probe.py` SHA-256 `869426a1cc3ef4606ca33f5533823837767e62a3f2ab9e4976497f6d923ba0f3`，最终 `engine-no-numpy-final3.log` SHA-256 `e3083222a562fba1b7cf55e94b9a4f3bc170ec2c40689cfa027a20432a87984c`。11 个关键文件运行前后 SHA 清单一致；主会话报告独立复制安全复跑 rc 0。运行前阻断 numpy / 网络并验证负对照，128 个 SDK / Base / Risk 模块来自 wheel，其余依赖借 Conda 视图。真实 wheel engine + 临时 SQLite / fake Gateway：默认政策源码 `self_trade=true`，合成覆盖缺失时 `DENIED/risk_self_trade_unverifiable` 且 Gateway 0 次；另一个全新账本显式 `self_trade=false` 时，数量 10 fake 预约 RESERVED，数量 11 超上限 DENIED，账本两行、fake reserve 恰 1 次。旧 Risk wheel 不含 WIP source gate，正向场景关闭 R05，不证明真实来源、账户授权或实盘能力；Base / SDK 普通安装仍声明 numpy。早期两次脚本误用仅 WIP API 导致 AttributeError，修正测试后通过；保留早期日志，不称产品失败。仅固定所列 11 文件与本地 fake，整期 **NO-GO**；临时材料可能清理。

## 2026-11-13 SDK WIP 固定回归快照

固定 SDK WIP 的 10 文件回归 **277 passed / 11 failed / 2 deselected / 1 warning，rc 1**；日志 `/tmp/iter64-sdk-regression.BqPcnAWD/pytest.log` SHA-256 `a617302546fb13328e4f06fc7dddefba5fb2f6bd71696836ee6f8c7f15e235f7`，同目录 `run.zsh` 保存命令；33 个指定文件前后 SHA 清单一致，主会话报告已独立复核。11 项均在 `test_iter64_risk_service_component`：5 项首先期待 v1 RESERVED，3 项 fake payload 期待 DENIED，1 项数量规则 code 被 SDK 已认证 v1 写 guard 的 UNKNOWN 覆盖；另 parent 预约被 Risk quarantine 返回 UNKNOWN，及 available 旧期望 true、实际 false。这些仅解释首个失败，不证明其后策略隔离、母子单、字段或计数等逻辑通过。另两个 dispatch / release 的 `ThreadPoolExecutor` 参数项因死锁时退出无界而未运行，**NOT_RUN**，不是 xfail。这是本地 fake / 临时 SQLite 的限定回归，不是全套、发行或账户验收；整期 **NO-GO**。临时证据可能清理。

## 2026-11-13 SDK 并发节点独立补跑

SDK 原回归仍为 **277 passed / 11 failed / 2 deselected，rc 1**；其中原 deselected 的 dispatch / release 两个参数项在新建专用 fake 进程补跑，各 passed，合计 **2 passed / 1 warning**，pytest 与 wrapper rc 0。日志 `/tmp/iter64-concurrency-bounded.sjamW829/pytest.log` SHA-256 `90a693b703a74bcbc3e7ee78f6f197a2d250db245ba69542c090fe847501487c`；watchdog 未触发、未发信号，记录父子标识，原进程组检查为空且 ps 无匹配，36 文件前后 SHA 清单一致。原 `proof.json` 因 `.NODE_RESULT` 同行解析遗漏，保守标为 INCOMPLETE，保留不覆盖；事后 `verify.py` 生成的 `verified-proof.json` 正确匹配两节点，主会话报告独立复核通过。runner 只检查原 PGID，未覆盖同一 SID 下所有进程组，proof 中 session 清理字段名过宽，不能据此声称整个会话为空。Python 审计 hook 不是 OS 沙箱，范围限已列事件，且仅被阻断事件列表为空；Barrier 只同步开始，不证明全部锁交错、真实账户或跨代来源。整期 **NO-GO**；临时证据可能清理。

## 2026-11-13 SDK 原锁竞争确定性观察 WIP

未提交 WIP `test_iter64_risk_lock_contention.py` 以 fake 确定性观察原 SDK 锁竞争：A 在产品原 `_risk_reserve` 持原 `threading.Lock` 且发出意图前暂停；B 在实际更早的 `_check` 同一原锁语句处非阻塞探测为 False 后释放 A。不替换原锁或 host 方法；线程局部 trace / profile 检查同对象 ticket create / consume 各 1 次、两结果 UNKNOWN、fake wire / direct 0 次，后续 dispatch / release 为 UNKNOWN。本机最终 **2 passed / 1 warning**，日志 `/tmp/iter64-lock-portable.FqnVhZyO/pytest.log` SHA-256 `ce7bc142657487aea005dd1caacf133fe74051283452cc7bc54212b1a091a505`，37 个选定文件前后 SHA 清单一致；主会话报告独立只读复审。首轮两个失败来自错误假设 B 先到 `_risk_reserve`，后改为实际 `_check`，旧日志保留。动态 Conda base / `ps` 不可用、非 POSIX 等条件显式 skip，属 **NOT_RUN**；本机独立 fake 子组正常退出、未发信号，检查仅限原 PGID 及记录 PID。超时条件下信号仅针对本测试可识别组，但仍有 TOCTOU / `cleanup_unknown`；hook 非 OS 沙箱，异常路径和其他平台未验。该观察不证明 B 已进入 blocking acquire、所有调度或真实账户来源；依赖 SDK 其他 WIP，不可单独交付，整期 **NO-GO**。临时证据可能清理。

## 2026-11-14 独立真实 Risk 服务合成联调 WIP

独立真实 Risk 服务合成联调仍为 WIP：未提交测试 `tests/integration/test_iter64_real_risk_source_quarantine.py` 最终文件 SHA-256 `fc4379fe864e1cb43d68883999f954bb711e67ceb0aec83125c0e4e093a103c5`；`/tmp/iter64-real-risk-final4.7g4CAMXD/pytest.log` **1 passed / 1 warning**，SHA-256 `9e9c68222924ffc2f2d7751bbc3a9e97987c47834920340a087291b3d5ba1cff`，16 文件前后 SHA 清单一致，主会话报告独立只读审核。测试只创建自己的 Risk PID 43326 / Gateway PID 43323，主会话报告退出码 0、ps 无匹配。测试以 writer fence 事务 seed 临时 v3 SQLite，关闭后重取 fence；真实 `RiskOrderService.build_view` 对同一 canonical request 校验完整视图、digest、quantity 与本地 permit 一致，`R05=true` / `available=false`。独立授权 strategy 经真实 CURVE 到 Risk：旧键同 payload / 异 payload 及新键 reserve 均为 UNKNOWN，旧 / 新 dispatch / release 均 UNKNOWN；旧 status UNKNOWN，新 status NOT_FOUND 仅表明本账本未记录，不是 NOT_SENT。旧 permit 整行前后相等，Gateway command / release 两表行数未增，不证明 0 RPC 或旧行未更改；非 BT 完整链。先前 fixture 的 quantity 单位、TIF、trading_day 不一致已按实际 `build_view` 修正，先前日志为旧快照。无真实账户、provider、来源、跨代或 BT 联动证据，整期 **NO-GO**；临时材料可能清理。

## 2026-11-14 BT → 合成 Gateway 失败与清理记录

以下仅依据主会话提供的脱敏事实，BT → 真实合成 Gateway 联调仍为 WIP：`tests/integration/test_iter64_bt_gateway_quarantine.py` 与 `tests/integration/iter64_bt_quarantine_gateway_support.py` 未提交，修复诊断与清理前不宜复用。前三轮 rc 1：前两轮为测试 fixture 参数 / alias 错误，各自 test-owned Gateway / Risk 均 exit 0 且 ps 无匹配。第三轮创建 Risk PID 43516 / Gateway PID 43513，到达假服务 / 策略会话准备，但在 Broker 绑定前异常，pytest rc 1；finally 的清理封装以 `SyntheticCleanupUncertain` 掩盖原因，测试按保护路径保留 host，未向其发送停止或 kill。主会话只读 ps 未见两个 PID / 直接子进程，lsof 未见测试目录打开文件，但缺退出码与注销证据，仍为 **cleanup_unknown**；`/tmp/iter64-bt-real-gateway.ojNoKRr6` 及关联身份必须保留，不得操作、释放或重试。OPEN pending 仍为 schema v5，intent 和订单快照为 0，尚未到 submit；CLOSE 未执行。监听窗口未见指定写操作不能证明订单路径，因为根本未提交。原失败回溯含本测试生成的合成 CURVE key repr，不得复制或公开原日志及密钥，不涉及真实凭据。真实来源、账户及 BT 链仍未验，整期 **NO-GO**。

## 2026-11-14 合成 Gateway 清理证据勘误

对此前合成 Gateway 清理证据的后续勘误：只读源码显示 SDK `tests/integration/test_iter64_risk_service_process.py::_gateway` 的 `finally` 仅在 `host.state == "started"` 时尝试 `host.close()`；对 `owner.close(5)` 未检查返回值，随后发送 `("closed", pid)`，上层 helper 使用该 marker。因此先前 64.13 WIP / clean 运营联调及独立真实 Risk 服务测试中 Gateway 子进程 exit 0、ps 无 PID 是已观察事实，但 `closed` marker 不证明 `owner.close` 成功、严格注销或全部资源清理，此前完整清理表述受本条限定。Risk / client 自身另有检查，不一概否定。必须区分 `state=closed/failed` 与真实注销证据；`GatewayStrategyClientSession` 默认 `require_unregister_ack=False`，不能由普通 closed 声称严格 ACK。BT 第三轮 retained PID 43513 / 43516 仍为 **cleanup_unknown**，未进行信号或释放，当前 ps 未见不等于出口确认；详见前文保留要求。本条仅为源码审查，未重跑，不证明真实账户通过；整期 **NO-GO**。

## 2026-11-14 清理测试夹具修复 WIP

清理测试夹具修复均为未提交 WIP，仅有纯 fake 证据，所有测试未启动 host。SDK 共享 `tests/integration/test_iter64_risk_service_process.py` 的 Gateway helper 不再无条件发 closed：验证 ServiceHost 本地 closed / `cleanup_failures`，`owner.close` 精确为 True 后最多等待 0.25 秒自然线程退出并检查队列与 failure，运行失败或未确认为固定 uncertain；原父测试要求唯一同 PID closed 且无额外事件。secret 文件以 `O_EXCL`、0600 或更严格方式创建，处理短写和已存在；相关写入错误仅对 `Exception` 固定码，不声称处理全部 `BaseException`。fake **58 passed / 1 warning**，`/tmp/iter64-fixture-cleanup-final5.ywORQ3eR/pytest.log` SHA-256 `d96dfbecad380a5c2b869b004a0331324a128328768818e19b6d1e29ceb61c90`；主会话报告独立 **58 passed**，不证明严格 ACK。BT 两文件 WIP 的 reporter 仅真实同 PID closed 且无错误时确认；异步 uncertain / 错误、preclose 检查及分步构造失败 / 已知 uncertain 保留已返回引用与异常，但不保证底层未返回资源保活。fake **53 passed / 1 warning**，日志 `/var/folders/7d/hnmknylj1w91h3cvq6mh3thm0000gn/T/iter64-bt-start-audit.BYsWFmISyD/pytest.log` SHA-256 `8febb37076a29506f04d7394252e8de3d6e3cdd2b3349d7594b656725442e4d4`；主会话报告独立 **53 passed**。Web helper WIP 的 reporter 识别 uncertain / closed / PID，使用随机 challenge、独立 0700 身份目录 / 0600 配置和各步 precheck；fake **33 passed / 1 warning**，`/tmp/iter64-web-reporter-final.38dlww/pytest.log` SHA-256 `c3418eacfcba693d4f615d4675afbed02bc5d8287da452e9a0a91e48d9c7438e`；主会话报告独立 **33 passed**。事件检查到动作仍有 TOCTOU，无严格远端 ACK，内存对象不跨进程退出，其他平台与真实进程未证明；旧 retained PID 43513 / 43516 与 `/tmp/iter64-bt-real-gateway.ojNoKRr6` 仍为 **cleanup_unknown**，未操作且禁止复用 / 释放，此前 ps 无匹配不等于注销确认。不能声称真实 host 已修复或整期通过，仍 **NO-GO**。

## 2026-11-14 独立 Risk 来源测试清理安全修订 WIP

独立 Risk 来源集成测试的清理安全修订仍为未提交 WIP：`tests/integration/test_iter64_real_risk_source_quarantine.py` SHA-256 `1f8ada0c2bb18759e0f3444ecf6126eb9212e6209a58a094b33e89edbf3cf195`，新 fake 测试 `tests/unit/test_iter64_real_risk_quarantine_cleanup.py` SHA-256 `16c3df8b86c8bb25133a8443072b9050ad5a6ca7df1b15670c17fbe28d38de85`。复用独立持久 0700 身份根 / 0600 原子 key 和 Gateway reporter 逐步检查；已有不确定时禁止进一步 close / stop。策略客户端关闭仅接受精确 `RuntimeSnapshot`、`thread_alive is False`、`strict_unregister_ack is True` 和 4 个精确 int 零计数；该标志不是远端权威。身份文件写失败仅输出本测试有效 PID 与私有目录，标明 PID 可复用且不授权停止；seed `ExitStack` 关闭异常记录 `cleanup_unknown`，不声称 fence 仍持有、不重试。主会话报告纯内存 fake **66 passed / 1 warning**、独立复核 **66 passed**，未启动服务；未读取旧含合成 key 日志 / 密钥，未碰 retained。此前 Risk 真实进程 **1 passed** 属旧版 SHA，新安全版真实进程 **NOT_RUN**。TOCTOU、远端注销、OS 退出后的内存保留、跨平台及真实来源 / 账户仍为 GAP；旧 PID 43513 / 43516 及此前目录仍为 **cleanup_unknown**，整期 **NO-GO**。

## 2026-11-14 清理护栏联合修订 WIP

清理护栏联合修订均为未提交 WIP：独立审查发现先前 Web helper 在已知 direct unregister uncertain 时仍 close，且可能先 close Web；此前 91 项 fake 因旧错误预期仍全绿，前版 33 / 66 均保留为历史快照。现 Web helper SHA-256 `cfb91e6d15f22265caec4a6989ff7ff6fb575d10a68f5c47d17fe2068c40fe27`，Web fake 测试 SHA-256 `130451fb4f3489d184ed59f07e1cfecdf8a95393d9d29c3adb400dd0a55be418`：任何动作前精确检查所有现存 Web / direct 状态和计数，Gateway 退出码须为精确 int 且 0，`pre_close` 与额外 `pre_action` 仅接受精确 True，空对象、未知或异常不继续。主会话报告 fake **77 passed**、独立 **77 passed**。Risk 集成测试 SHA-256 `30f1046b378585e9c06c05b56dc9ef072a136e2f7a1ec4154aa3942b869f966a`，fake 测试 SHA-256 `25f35cb66031784ddb3a616d9efa99edbe828bb7159296083e2d45d060de18f3`：`client_uncertain` 仅接受精确 False，在策略与 admin 每次 close 及后续 stop 前复核；主会话报告联合 fake **104 passed**，独立 Risk + Web **181 passed**。均未启动服务，未读旧 BT 含 key 日志 / 密钥或碰 retained。此前真实进程 **1 passed** 属旧 SHA，新版真实集成 **NOT_RUN**；检查与动作之间 TOCTOU、严格远端 ACK、跨平台和进程退出后的内存保留未证明，旧 PID 43513 / 43516 仍为 **cleanup_unknown**，整期 **NO-GO**。

## 2026-11-14 Sticky cleanup 合成测试行为记录

以下仅据主会话提供的事实：SDK Risk host sticky cleanup 执行方先运行两轮自行新建的 fake / 临时 SQLite 单元，各 **54 passed / rc 0**。第一轮的 7 个本次测试创建 host 随 pytest 进程自然退出释放，并产生解释器 generator 提示；不能据此声称 fence 仍持有。第二轮测试曾新增 teardown，在断言后对同轮 7 个临时 host 直接 `_stack.close()`，并从该 pytest 进程的 `_RETAINED_HOSTS` discard，随后 rc 0；该 teardown 在主会话指示后已撤销。后续仅使用 fake stack / 局部 mock retained set，不再自行释放任何 retained。两次执行器仅有 session ID `70439` / `62941`，未保存 OS PID 或 tmp 绝对路径，无法独立验证更强身份；测试源码表明均由本轮 `tmp_path` 创建，执行方报告未触及既有 / 用户 retained host。新版无真实 fence 的 fake 结果 **31 passed** 仅为 WIP；observer / delegate 自动 cleanup 重试仍有 GAP，不能说全局关闭安全。原 PID 43513 / 43516 保持 **cleanup_unknown**，整期 **NO-GO**。

## 2026-11-14 Risk Web 请求体上限局部提交

以下为主会话提供的局部证据：Risk Web 请求体上限改为逐块读取，超限后不调用 admin 且不继续读取；Risk `b3bc6f54f4bac88806ecbcc36e5c1bda1506747c`、SDK gitlink `bd01f05e` 已本地提交。纯 ASGI fake / 单元独立验证 **260 passed / 1 deselected**，未选中的子进程测试 **NOT_RUN**；覆盖认证 / CSRF、三个端点恰好限制、流超限和断流。Ruff check 通过；两个文件的 format check 在 HEAD 同样不通过。上游单个 chunk 的分配、真实网络及生产账户未证明；host / delegate sticky WIP 仍未闭合，不能声称完成。整期 **NO-GO**。

## 2026-11-14 Risk journal / SDK sticky 保留 WIP

以下为主会话提供的当前 WIP 快照：Risk journal SHA-256 `c8a1ca5891e4691352d2e5a6dc4eb3d02992081e585dc17f2e959324a1c5dfa4`、storage SHA-256 `74d1884267163fc603e0e33b13e72c084900aa9d9c3b6cb77d8b9fa322c12c11`、fake 测试 SHA-256 `8116a54bd8dd1b9bac485e767a71dc3dbacc2947af65390634457d8b9d5c1f9a`；纯 fake **45 passed**，含真实 Python 线程但无真实 SQLite / fence。SDK 上一快照 `28762036…` 与 Risk 联合 **196 passed**、stderr 0；SDK host 随后仍在更改，该测试不是最终结果。WIP 引入 Risk entry 不明 scope 粘滞保留、受信 manager 与异常单次证明 / 弱引用，以及 SDK host / port 和探测失败关闭；但并发最后检查与动作间仍有 TOCTOU，已在途 SQLite / token 不可撤销，旧 Risk 无合同及 SQLite BUSY 均为 UNKNOWN。旧 `sqlite3.OperationalError` 与解锁重试合同不兼容，不能通过重写测试掩盖。SQLite 实际路径仍有隐式 cursor、可变 adapter、rollback / close 覆盖异常，清理证明及真实资源尚未验收；不证明原 fence 仍持有、token 未变或账户可用。此前 7 个本轮临时 synthetic host 的清理事件保留原记录；旧 retained 仍为 **cleanup_unknown**，不得触碰。整期 **NO-GO**。

## 2026-11-14 误跑测试透明记录

以下为执行方报告的误跑记录：本轮明确仅允许内存 fake、禁止真实 SQLite / host，runtime worker 误执行 `/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest -q tests/unit/test_iter64_strict_unregister_cleanup.py`，结果 **10 passed / 3 failed / rc 1**。测试源码使用 pytest `tmp_path` 创建进程内 synthetic ServiceRegistry / SQLite、LocalTransport 与 Python daemon owner 线程，在测试和 finally 中显式 close 测试 runtime、transport、registry、虚构候选及数据库；未构造 RiskServiceHost 实例。执行方报告未直接操作既有 retained、未访问真实账户。执行的 conda / python pytest 子进程已 exit code 1，但当时未保存 OS PID 或临时目录，不能独立证明每次 close、锁或临时目录最终状态，不能称清理已证明；不对目录或对象采取后续动作。三个失败为 `[STALE_EPOCH]` / `[NOT_REGISTERED]` / `[WRONG_ID]` 的 fake `SimpleNamespace` 缺 `_check_owner`，不算业务通过；该组已停止，未改测试文件。此前 7 个本轮临时 host 事件记录不变，原 retained 保持 **cleanup_unknown**，整期 **NO-GO**。

## 2026-11-14 清理合同 438 项旧固定快照

以下仅据主会话提供的上一固定快照：7 个明确 fake 文件联合 **438 passed**、无 deselect，执行方报告 stderr 0、16 文件前后 hash 一致；主会话独立复跑 **438 passed**。host `02ad5acb…`、market `12469034…`、thread `c69d3f6a…`、raw `de64241d…` 均为该快照 SHA 前缀。命令：`/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest -q tests/unit/test_iter64_risk_sticky_cleanup.py tests/unit/test_iter64_delegate_sticky_cleanup.py tests/unit/test_iter64_raw_runtime_sticky.py tests/unit/test_iter64_runtime_sticky_cleanup.py tests/unit/test_iter64_market_owner_sticky.py tests/unit/test_iter64_account_owner_cleanup.py bt_api/bt_api_risk/tests/test_iter64_fence_entry_cleanup_contract.py`。执行后只读审查发现 market 构造 / 关闭状态读取和 thread snapshot 回调后检查缺口，market / thread 仍在修；438 仅为旧快照，不证明全链路。单个 `ServiceMarketClient` 内部、SQLite BUSY、全局跨线程 TOCTOU 和真实资源仍为 GAP；进程级保守熔断还涉及跨账户可用性代价。此前合成 SQLite 误跑及 retained 事件记录保留，整期 **NO-GO**。

## 2026-11-14 SDK 秒数转换局部提交

据主会话提供的局部证据，SDK commit `09942183` 在秒数转为 float 后拒绝下溢为 0、无穷及转换错误，覆盖 10 个实际字段。独立指定纯内存 fake **14 passed / 1 pytest 配置警告**，审核 **13 passed / 同警告**；未执行 host / SQLite / fence。极小正浮点可能不足以使 `monotonic + interval` 前进，调度粒度仍为 GAP；该提交不证明服务、账户或验收。此前误跑 SQLite 等证据保持原样，整期 **NO-GO**。

## 2026-11-14 SDK freshness 纳秒精度局部提交

据主会话提供的局部证据，SDK 本地 commit `f321d13f` 对 account / strategy 两个 `max_age` 字段按 host 相同的 `int(float秒 * 1e9)` 验证至少 1 ns，并通过与原始 Decimal 精确比较拒绝会扩大 freshness 上限的输入。pure fake 覆盖正常 / 可选字段、1 ns、1.5 ns 向下、接近 2 ns 向上舍入及低精度 / 陷阱；主会话以 Conda base 指定节点独立 **17 passed / 1 warning**（禁用 pytest 插件导致未知配置项），独立审核先前 **16 passed**。未运行真实 host / SQLite / fence，不可推断来源、账户或发行；poll / TTL / 其他 timeout 未由此修复。此前误跑记录保持原样，整期 **NO-GO**。

## 2026-11-14 SDK host 轮询 deadline WIP

据主会话提供的 WIP 快照，SDK host SHA-256 `7780c021b95777971586e4acf93f766e8c241619ecb2a8cc7fbb91242e78deee`，fake 测试 SHA-256 `45ee8820f67b7d80d6cb904d2d963e48473da44f26c304c7cfdecb495b525360`，均未提交。启动时最终时钟非有限则拒绝；`run_once` 检查启用项已有 deadline 及所有到期项新 deadline 有限且大于实际 now，再执行 poll / maintain，非法时不改 `_next`。主会话独立 pure fake **83 passed / 230 deselected**，独立静态复核通过。初始 `pump.poll` 与 `run_once` 的 `serve_once` 分别在相应 clock 检查前，不能声称验证前无动作。此 WIP 与 global cleanup 改动同文件未提交，不代表实际资源、账户或整体验收；旧 SQLite 误跑等记录不变，GAP 与 **NO-GO** 保持。

## 2026-11-14 SDK TTL 纳秒精度局部提交

据主会话提供的局部证据，SDK commit `3f36c3a1` 对 `reservation_ttl_seconds` 与 `dispatch_recheck_seconds` 按 Risk 实际 `int(float * 1e9)` 验证至少 1 ns 且不扩大原始 Decimal，复用现有两个 `max_age` helper，保持各字段上限及其他秒数字段。主会话独立 Conda base pure fake **18 passed / 32 deselected**，独立复核 **18 passed**；禁用插件时有 1 个警告。未运行真实 host / SQLite / fence / account，Gateway `now + ttl` 与 V2 整毫秒 / 传输仍未证明，此提交不等于远端或整期 PASS。旧 SQLite 误跑与所有 WIP 记录保持原样，整期 **NO-GO**。

## 2026-11-14 Gateway TTL 局部提交

据主会话提供的局部证据，Gateway 子仓 `9e2cc56b9382948b8bd7bca8087642b320b90036` / SDK gitlink `0b1832b7` 对新 key reserve 在采集 now 后、UUID / INSERT 前计算不超过传入二进制 float TTL 的正 deadline；若向上舍入则使用相邻浮点向下，不可表示时返回 `INVALID_TTL`。旧 key 仍按原路径返回、不续期，明确拒绝白名单未变。主会话及独立复核 pure math / 内存 fake **23 passed**，未执行真实 SQLite / host / socket / fence / account。此时事务、fence 和权限路径此前已进入，不能声称无副作用、回滚或未发送；非 owner 映射 `HANDLER_FAILED`，再由标准 `GatewayDirectClient` 映射 UNKNOWN 仅为源码静态分析，未经端到端验证。既有 `_reserve` 输入校验可能调用数值子类覆写、超大 int 可能触发 `OverflowError`，本次未改变；现有记录不追溯，剩余 TTL 减法、V2 毫秒 / 原十进制、持久化及实际账户仍为 GAP。旧误跑记录保留，整期 **NO-GO**。

## 2026-11-14 Gateway 剩余 TTL 局部提交

据主会话提供的局部证据，Gateway `099f00f` / SDK gitlink `9c790f8f` 已本地提交剩余 TTL 修复：合法非负 SQLite int / 有限 float 的 `expires - now` 按精确二进制值差向下量化，供 observe / first receipt 使用；旧代 RESERVED 为 0、非 RESERVED 为 None。历史 `int(2**53+1) - float(2**53)` 从误算 0 修为 1。postcommit 剩余计算的 `Exception` 纳入 `FIRST_RESERVATION_UNCERTAIN`，`BaseException` 保持原传播。主会话与独立复核在 Conda base 使用 pure Fraction 和内存 fake 的两个测试文件各 **34 passed**，未运行真实 SQLite / host / socket / fence。该值是远端观察，不是本地授权、freshness 或未发送证明；提交 / 回滚、V2 少于 1 ms 的 UNKNOWN 接线、跨进程时钟及账户仍未验，整期 **NO-GO**；原 SQLite 误跑记录保留。

## 2026-11-14 清理合同 601 项 fake 固定快照

据主会话提供的固定 WIP 快照：host SHA-256 `7780c021b95777971586e4acf93f766e8c241619ecb2a8cc7fbb91242e78deee` / fake `45ee8820f67b7d80d6cb904d2d963e48473da44f26c304c7cfdecb495b525360`；thread wrapper `dbebd8d13f498823c71ba14bf80d2908427550fcc77bbb3f41dced5d855013bd` / fake `3a588454e90fd6095dd14b7672a2d887101c271ec52c5458a9335dac0b6f7daa`；market owner `b8ef44f71692a51ad1607eedd402356400f57e230656ed59ee9bb0ec91b826b7` / fake `d98e170308aa438dc874ff6ec02f5e7b67d2f48681343755bbeea8f89d0547bc`。执行方 Conda base 七文件 **601 passed / 0 skipped / 0 deselected**、stderr 0，16 文件前后 hash 一致；主会话独立同七文件 **601 passed**。仅有会话输出，无单独落盘日志。七文件为 `tests/unit/test_iter64_risk_sticky_cleanup.py`、`tests/unit/test_iter64_delegate_sticky_cleanup.py`、`tests/unit/test_iter64_raw_runtime_sticky.py`、`tests/unit/test_iter64_runtime_sticky_cleanup.py`、`tests/unit/test_iter64_market_owner_sticky.py`、`tests/unit/test_iter64_account_owner_cleanup.py`、`bt_api/bt_api_risk/tests/test_iter64_fence_entry_cleanup_contract.py`。未运行此前误跑的 `strict_unregister_cleanup`，未运行真实 host / SQLite / fence / socket，所有产品修改仍未提交 WIP。单 client async / batch 未接 token / custody、SQLite BUSY 兼容、TOCTOU、进程全账户熔断的可用性及真实账户 / 来源仍为 GAP；原合成 SQLite 误跑及 7 个临时 host 记录保留，整期 **NO-GO**。

## 2026-11-14 SDK Risk 配置 YAML 预算局部提交

据主会话提供的局部证据，SDK commit `c696e5fb` 对 Risk 服务配置 YAML 的 compose / alias graph / flatten 先预算再展开，深度上限 64、累计预算 100,000，保留空 merge / 正常合并与重复键拒绝；默认 traceback 隐藏底层 YAML 异常显示，但 `__context__` 仍可反射。主会话和独立复核的 Conda base 纯内存测试均为 **33 passed / 31 deselected**；禁用插件导致 1 个 pytest 配置警告。预算不覆盖词法扫描 / 标量全部成本，不等于绝对 CPU 时间上限。未运行真实 host / SQLite / fence / account，不证明来源或整体验收；此前误跑和所有 WIP 记录保留，整期 **NO-GO**。

## 2026-11-14 R01 纯规则测试局部提交

据主会话提供的局部证据，Risk 子仓 commit `9136817` / SDK gitlink `6313f23f` 新增独立 `test_iter64_r01_pure_rules.py`：真实 controls 函数使用合成事实验证开平数量 / 名义边界、缺配置、缺乘数 / 市价；未改默认来源门或原测试。主会话与独立审核各 **30 passed / 1 warning**，警告为禁插件后的 pytest 配置警告。审核者将 HEAD controls 内存加载、其他模块仍用当前环境时另有 **30 passed**；该混合对照不是干净 checkout。未运行 host / SQLite / fence / 网络；原 660 个失败 / 错误快照不变，原 reserve / Gateway、账户、来源与 schema 迁移仍未验，整期 **NO-GO**。

## 2026-11-14 R02 纯规则测试局部提交

据主会话提供的局部证据，Risk 子仓 `a8b7a3b` / SDK gitlink `6b88333e` 新增 R02 纯规则测试：source / received 双时钟各 1000 ms 及超出 1 ns、quality / 字段缺失、market / close 开关、5 tick 双向边界和 tick 0.2 的非 1 示例；合成价格不证明市场网格。主会话独立 **40 passed**，禁插件产生 1 个 pytest 配置警告；独立审核在 HEAD controls 内存加载、其他模块使用当前环境的混合对照中 **40 passed**，不是完整干净 checkout。未改默认 source gate，未运行真实 host / SQLite / fence / account；reserve → dispatch 复查、Gateway 不发送、bps 与真实来源未证明，660 失败 / 错误历史快照不能改计数；误跑记录与整期 **NO-GO** 保持。

## 2026-11-14 R08 warn 保证金纯规则测试局部提交

据主会话提供的局部证据，Risk 子仓 `338bada` / SDK gitlink `a6128070` 新增 R08 warn 保证金纯规则测试：覆盖 long / short 费率、可用资金等额 / 不足、已有占用、`envelope_credit`、缺费率 / 账户 / 可用额、off / CLOSE 与 deny OPEN 失败关闭。主会话独立 **20 passed**，禁插件产生 1 个 pytest 配置警告；审核者 HEAD controls 内存加载、其他模块使用当前环境的混合对照 **20 passed**，不是干净 checkout。仅证明合成输入返回码，不证明实际告警、账户费率 / 来源、并发额度或完整准入；未运行 SQLite / host / fence / network。历史 660 失败 / 错误快照不改计数，误跑记录及整期 **NO-GO** 保持。

## 2026-11-14 R03b 纯规则测试局部提交

据主会话提供的局部证据，Risk 子仓 `52fa4ee` / SDK gitlink `c9a74af2` 新增 R03b 纯规则合成测试 31 项：覆盖 SHFE / INE 与 DCE、平今 / 普通平 / 显式平昨、BUY / SELL、今昨桶、两个占用扣减、零可平及 coverage / continuity 未证拒绝。主会话独立 **31 passed**，禁插件产生 1 个 pytest 配置警告；审核者 HEAD controls 内存加载的混合环境 **31 passed**，不是完整干净 checkout。纯函数 offset 映射不证明 Q39 跨日原目标 / 受信日切映射、真实账户共同切点或并发 / dispatch；未运行 SQLite / host / fence / network。历史 660 失败 / 错误快照不改计数，误跑记录及整期 **NO-GO** 保持。

## 2026-11-14 R07 损失阈值纯分类测试局部提交

据主会话提供的局部证据，Risk 子仓 `a0c6e8f` / SDK gitlink `5eb376da` 新增 R07 损失阈值纯分类测试 20 项，覆盖 warn / block 边界与相等优先、账户 / 策略 breach scope / latch 字段。主会话独立 **20 passed**，禁插件产生 1 个 pytest 配置警告；审核者以内存加载 HEAD engine 的混合环境 **20 passed**，不是干净 checkout。仅为内存规则返回，不证明真实损益、跨日资金基线、UNKNOWN、持久锁存、告警或派发；未运行 SQLite / host / fence / network。历史 660 失败 / 错误快照不改计数，误跑记录及整期 **NO-GO** 保持。

## 2026-11-14 损坏许可内存 fake 局部验证

据主会话提供的局部证据，Risk 子仓 `1e9b7b5` / SDK gitlink `d9895183` 新增损坏许可内存 fake 验证。在 `object.__new__` 绕过真实 engine 构造器并注入严格内存 fake 的前提下，使用真实 Permit / RiskOrderView / canonical digest 先确认合成 holding 记录一致；按复合身份替换恰 1 个内存对象后，真实 `apply_observations` 在读取 cursor / 事件前抛出 `risk_permit_mismatch`。空批次未损坏对照到达 fake cursor，fake 覆盖 9 种状态分类。主会话 Conda base **13 passed / 1 warning**（禁插件配置警告）；独立审核以内存加载 HEAD engine + ledger、其他依赖使用当前 WIP 的混合环境 **13 passed**，不是干净 checkout。无真实 SQLite / host / fence / network；内存匹配数不证明 SQL rowcount、事务回滚 / 持久、事件推进、来源或账户。历史 660 失败 / 错误快照不改计数，误跑记录及整期 **NO-GO** 保持。

## 2026-11-14 Risk 六组纯内存组合回归

据主会话提供的局部证据，Conda base 对 R01、R02、R03b、R07 threshold、R08 五个纯规则测试文件及 `tests/test_iter64_corrupt_permit_guard_fake.py` 的纯内存组合回归为 **154 passed / 1 warning**，警告为禁用 pytest 插件导致的配置警告；该结果运行当前 Risk controls / engine WIP。此前 HEAD 控制单文件仅为内存混合对照，非完整干净 checkout。未执行 SQLite / host / fence / socket / network，真实数据库、账户来源与派发仍为 GAP；历史 660 失败 / 错误快照不改计数，误跑事件及整期 **NO-GO** 保持。

## 2026-11-14 行情 strict 失败关闭 WIP

据主会话提供的未提交行情 strict WIP 快照，`service_market.py` SHA-256 `11c32789b083fe58eddde1127cb487b8d21b395d950dad974da7e7e09a15c1c3`、`GatewayMarketOwner` SHA-256 `165fa74f0dccc9703e0917f0ea196cfc1dd73d6de2bb7079a2d86b3a99670fe4`。strict 将 start / recover / accept_resync / resync_after_regrant 及对应 begin / batch / bootstrap 在 binding / factory / RPC 前明确拒绝 `STRICT_MARKET_FACTORY_UNAVAILABLE`，owner 透传 client guard；strict 空 new close 不读 binding，污染或非空状态 close 拒绝并保留，legacy 默认不变。poll / clock / history 未显式禁用，可能执行 maintenance / RPC / revoke，不能证明安全。主会话及独立复核的两个纯内存 fake 测试文件各 **76 passed / 1 warning**，警告为禁插件后的 pytest 配置警告；未运行真实 host / SQLite / socket / fence / account。strict 行情当前不可获取；真实工厂 quiescence / partial / 内部 socket lease、动态 token / custody 未接线、跨线程 TOCTOU / 旧 SQLite BUSY 与账户来源仍为 GAP，不能声称交付或验收。此前误跑及 660 失败 / 错误快照保留，整期 **NO-GO**。

## 2026-11-14 Risk ledger 无界测试辅助方法 WIP 缩减

据主会话提供的未提交 WIP 事实，Risk ledger SHA-256 从 `0de94c536f724561731ace60f1271410c54f5585e088533eae5d7f2b0423ac78` 变为 `0785db06c940f678b0790e2858e608e60e8fe7c4d0718b8f1149e3f435e2eda3`，删除 WIP 内仅测试使用的无界 `LedgerTxn.all_permits`。未跟踪 golden 测试改为按 9 个固定 ID 读取 scoped `txn.permit`，保留 9 条、顺序、字段及其他 scope 排除断言。执行方报告 AST / 内存 fake 通过；独立只读检索 SDK / BT Python 无引用，不排除外部或动态调用。完整 golden 因需要 SQLite / fence 未运行，不证明 SQL / 事务。该方法也不在 HEAD，变更前旧 WIP 无法从 Git 独立恢复；执行方报告前后 SHA 与反向逐字节对照。本步骤未提交，不闭合 v1 / v3 / SDK / BT 来源隔离或总验收；保留 660 失败 / 错误历史、SQLite 误跑及整期 **NO-GO**。

## 2026-11-14 bounded UNKNOWN 元数据 WIP

据主会话提供的 bounded UNKNOWN 元数据未提交 WIP 快照，Risk ledger SHA-256 `285986d25b4601b0560536762bcc459037d11ec34863e5ea11edf130949b226c`，新 pure fake 测试 SHA-256 `a4d27acd8f8678a27d8de1876604e062cc8510d2e85ce340c45bb0b919b9485c`。直接调用真实 `LedgerTxn` / engine 的内存 fake 验证：负 created / updated 与非空但不符合既有 8 字符 `isdigit` 交易日的元数据固定为 corrupt，整批拒绝。历史拒单可能存空交易日；空日返回 unavailable 而非 corrupt，属于读取兼容变化。主会话及独立审核各 **14 passed / 1 warning**，警告为禁插件后的 pytest 配置警告。未验证日历真实性、日期与 view 一致性或 updated 顺序，未运行真实 SQLite / host / fence / network。SDK UNKNOWN 投影不转发交易日 / updated，不能声称 Web 泄露；其他 WIP、660 失败 / 错误历史、误跑记录及整期 **NO-GO** 保持。

## 2026-11-14 Risk 七文件纯 fake 组合回归

据主会话提供的局部证据，Conda base 在 Risk 工作树对 R01 / R02 / R03b / R07 / R08、`corrupt_permit_guard_fake` 与 `unknown_metadata_fake` 七文件的纯 fake 组合为 **168 passed / 1 warning**，警告为禁用 pytest 插件引发的配置警告。当前 ledger / engine 为 WIP，metadata 项未提交；此前 154 为六文件旧快照。未运行真实 SQLite / host / fence / socket / network，不能证明账户、事务或整体验收；历史 660 失败 / 错误统计不变。主会话源码核对显示 `list_unknown_bounded` 文档仅保证有限拒绝，既有 WIP 测试要求 `PRETRADE_V2_COMMIT_UNCERTAIN` 原始 `RiskOrderJournalError` 传播，SDK 外层映射 unavailable；不能仅以类型不同断言为 bug，本次未改该异常边界。误跑事件与整期 **NO-GO** 保持。

## 2026-11-14 Base 合同差异与参考价时间 GAP

据主会话提供的本轮证据，Base 历史 `417a575^` 与 HEAD `b70e920` 均声明版本 `0.16.0.dev64`，但前者缺少 `gateway_risk_first_reserve_v2`，Risk 未提交 ledger 的顶层导入可能导致 pretrade 导入失败；该历史版本未证明已发布或安装。Risk ledger 已局部惰性导入，在缺失且通过既有来源 / schema 门时固定返回 `PRETRADE_V4_REQUEST_CONTRACT_UNAVAILABLE`。纯内存首次 **3 passed**，此前 v4 + metadata 组合 **17 passed / 1 warning** 为类型反射修订前快照，警告为禁插件配置警告。后续类型注解改为 `object`，运行时严格类型校验保留；合同存在 / 缺失时均覆盖 `get_type_hints`，主会话独立 **3 passed / 1 warning**，两文件 Ruff F821 通过。最终 ledger SHA-256 `e478b41930d50e46d6a823eb34e00173a4715d2f242ab5f8258ff8170181aaf8`、测试 SHA-256 `dfea1c75a654828d635e16f28251254c507acc328686189d71fc3c5885197e31`；该测试临时改进程全局 import hook / sys.modules，仅限单线程独立执行。现有未提交状态和其他 WIP 保留，不证明旧 wheel、真实账本或发行兼容。参考价未来时间目前只有纯函数复现：source / received 晚于 now 仍可能被接受。engine 先采 now 再取行情，本机 received、远端 provider source、不同时钟域、校时和最大允许偏差均未证明；直接修改可能误拒并改变其他事实与 TTL 边界，因此未修改，记为 GAP，不声称实盘绕过或来源已证。原 660 失败 / 错误快照、误跑及整期 **NO-GO** 保留。

## 2026-11-14 reference-age 未提交 WIP 快照

以下为主会话提供的未提交 reference-age WIP 快照：Risk `policy.py` 新增可选的 `per_order.max_reference_age_ms` 与 `margin_precheck.max_reference_age_ms`，均无数值默认，旧输入的固定 canonical / digest 测试不变；但旧 `max_notional` 的市价 OPEN 缺年龄现在拒绝，摘要相同不代表跨版本语义相同。保证金 warn 仅告警、deny 仍恒拒、off 不启用检查；热发布从缺失变为存在按放宽处理。warn 对新市价估值在过期或缺年龄时写 None；已有有剩余市价 permit / 未分配 parent 的估值没有时间来源，非 off 时为 UNKNOWN。同一政策版本的 market OPEN claim 重验名义额，warn 重验告警，但真正事务、释放和 Gateway 未验证。四文件纯 fake 主会话独立 **104 passed / 1 warning**（禁插件配置警告）；此前 **28 passed / 2 failed** 的旧 R01 断言在明确配置后保留原断言，Web 新测首次 **2 failed** 因测试误判异常类型后修正，历史失败不掩盖。FastAPI 在相关单测中为单项可选跳过，本机 0 skip。review 发现旧未跟踪 `test_pretrade_engine_decimal_arithmetic` fake 缺 `limit_price`，已补字段并新增纯 fake 精确算术覆盖；涉及 SQLite / fence 的原测试 **NOT_RUN**。该工作树未提交，不表示 source / time / 实际账户 / 占用或验收已通过。**严重 GAP**：终态但有待补成交的 permit 按当前合同仅用于持仓，未覆盖账户级保证金汇总；账户余额和成交共同切点未证，warn 仍可能低估或错误提示，deny 当前恒拒，不宣称实盘放行。future timestamp 可能被误接受，gather 后事务锁等待未计入年龄，Gateway 发送时有效性未证明；新 age 数值沿既有 `_count` 大边界，业务上限未冻结；旧 binary 不能解析新字段，升级 / 回滚需审计。快照 SHA-256：engine `073062d20b8f17404ca1b3576cbb07a61c8efccdfd02cd570746fa53c5a6920a`；policy `0ffd0bc9ad027e0520beeec6dee1e3d4cf8bd0f1044c1e5c40b128ee6b801f3a`；controls `ef4d30e87057bf9ec50eca0605becb606f1a70e880e4e3d30150a88495d4a946`；new tests pure `57301ac4e6c12f1256d8c57cc13329a7e1c2277a3aebdb04b011e64afad1132c`；claim `855af5248d66f742429b6802f5f9e23c8157ba61edde95393e235ca3ff1220d5`。历史 660 失败 / 错误、真实 SQLite 误跑记录与整期 **NO-GO** 保留。

### 后续保证金不确定快照

据主会话提供的后续未提交快照，Risk engine SHA-256 `1804eb70eb9438bff0dbad43a7ff186599cc4618b2bfd4191c866a12e944a4d8`：真实 `_exposure` 对 active 且 `margin_mode != off` 的 OPEN 强制 `uncovered_margin=None`，因为资金、成交与费用无可证明共同覆盖；这只避免有限结果冒充已证，不实现全账户终态查询或真实切点。warn 始终产生 `risk_margin_facts_unavailable` 而不拒绝，不能给出真实资金不足的数值告警；deny 仍拒，off / CLOSE 和其他字段保持原样。源码将 warnings 写入审计 detail，未在同步结果中输出；未证明运营可见或真实 audit / SQL 持久化。四个纯内存文件主会话独立 **108 passed / 1 warning**（禁插件配置警告）；新 claim fake SHA-256 `5aa046b48b4c021035eac2fe1f42fba599fe68265ef2fc3f6e671d7184d5d128`。旧未跟踪算术 Harness 测试改为预期 None 并保留其他断言（含原 1.24 数量断言），原 1.5252 运算由纯 fake 直接调用真实 `_add` / `_multiply`、精度 2 证明；由于覆盖门抹去最终值，不能称真实 `_exposure` 的 margin 聚合链已完成验证。原测试因需要 SQLite / fence **NOT_RUN**。此前 104 与有限占用语义均属旧快照，不代表当前完整行为。future timestamp、采样后锁等待、语义版本 / 旧 binary / 显式年龄上限、真实事务来源 / Gateway 仍为 GAP；660 失败 / 错误历史、误跑记录与整期 **NO-GO** 保持。

## 2026-11-14 R08 审计投影 fake 限定证据

据主会话提供的限定证据，SDK 新增未提交 `tests/unit/test_iter64_r08_audit_fake.py`，SHA-256 `b358894b7ab7268ab0e965fbda15b8a41eeedcc602035cfc479c1f7dd5830fb6`。Risk 真实 `_evaluate` / `_evaluate_claim` 在 fake context 与真实 `_exposure` 下返回内部 warning `risk_margin_facts_unavailable`；测试手工将结果复制进内存审计替身，再由实际 SDK `RiskOrderService.handle` 与 Web `/audit` handler 验证同账户分页读取、无 grant / 跨账户拒绝和超预算拒绝后原游标仍可读。主会话独立 Conda `--noconftest` **3 passed / 1 warning**，警告为禁插件配置警告；FastAPI / httpx 仅影响 Web 单项的可选跳过，本机 0 skip。合成已知 occupancy 的 standalone `check_margin` 可产生 `risk_margin_insufficient`，但真实 engine 因账户覆盖门返回未知，不能据此宣称真实资金足额 / 不足能力。全部使用 fake principal / port / ASGI，未验证真实审计写入、权限、账户、主动告警或同步响应；计划 WARN 仍须主动告警或冻结的交付合同。源码静态上 `audit.read` 限 operator / grant / account / domain，不得向策略或跨账户开放。原 660 失败 / 错误、source / time、真实 SQLite 误跑与整期 **NO-GO** 保持。

## 2026-11-14 R03 纯计算与 UNKNOWN 内存 SQLite 限定证据

据主会话提供的本轮证据，Risk 子仓 `cd005d2` / SDK gitlink `ba86c1ad` 已本地提交逐合约 R03 纯计算测试，主会话与独立审核复跑各 **29 passed / 1 warning**，警告为禁插件配置警告；审核以内存替换 HEAD controls + policy、其他模块使用当前环境得到 29 passed，并非 clean 安装。此切片仅证明 synthetic 策略 / 账户多空、在途、阈值及缺事实拒绝，不证明来源、完整 UNKNOWN、母单授权或计划中的账户合计 / 净敞口；账户合计 / 净敞口在计划与冻结稿中不一致，已向用户询问。另新增未提交 `test_iter64_unknown_sqlite_memory.py`，SHA-256 `5da95477f06bf83944b2865186a6b5205d4909ffaa43112fc56bd317904f48f9`：使用 `:memory:` SQLite，断言 `temp_store` 与 `journal_mode` 为 MEMORY，使用真实 ledger `_SCHEMA` / 直接 `LedgerTxn`、synthetic AccountScope / fake fence 和手工合成行。主会话独立 **22 passed / 1 warning**，警告为禁插件配置警告；首次开发测试的 2 个参数错误修复后通过。覆盖 UNKNOWN 状态、跨 scope、排序、坏元数据整批拒绝及资源预算；非真实 host / fence / 磁盘库 / 账户，不证明生产事务并发、持久恢复、engine 摘要校验或授权。历史 660 失败 / 错误、真实 SQLite 误跑及整期 **NO-GO** 保留。

### 内存 SQLite 后续 WIP 快照

据主会话提供的后续未提交 WIP 快照，UNKNOWN 内存测试现 SHA-256 `52d15e42efb3b882eb0c356b7f530462ac0c180d97429ea84dcd92d4a56d2328`：显式断言 9 种固定状态 / 排序，不用被测常量生成预期；独立覆盖双行 UTF-8 字节预算恰好 / 少 1 边界与两项 quarantine，主会话 **23 passed / 1 warning**（禁插件配置警告）。此前 22 passed 为旧快照。另新增未提交 `test_iter64_r03_exposure_sqlite_memory.py`，SHA-256 `b17f8f1458b6cc87b2e21eb9433f94fa729a9c82fafd862e87168a11f7c0f9e3`，使用真实 Risk schema / `LedgerTxn` / `_exposure`、synthetic scope / fake fence 与纯内存 SQLite；主会话 **7 passed / 1 warning**（禁插件配置警告）。开发中补游标合成测试曾 **1 failed**，原因为 fake fence 缺审计字段，修正后通过。测试覆盖 UNKNOWN 子单、父未分配、其他策略 / 账户 / 品种隔离、排除重评、终态待补，以及真实覆盖门不因 VERIFIED cursor 放开。这是合成 SQL 数据，不证明真实母子授权、成交 / 来源、生产事务 / fence、持久 / 并发或账户，不作为 R03 全功能验收。初始 `:memory:` 断言 `temp_store` / `journal_mode=MEMORY` 和主库路径为空，不声称 Python 进程全局无文件 I/O。两个测试均未提交且依赖 WIP；原 660 失败 / 错误、误跑、time / source 和整期 **NO-GO** 保持。

## 2026-11-14 ObservationPump event-day / ACK 局部修复

据主会话提供的本轮证据，SDK dev `c7c0eb42` 本地提交 ObservationPump event-day 两处 hunk 与新 pure fake 测试，未携带 SDK 其他 dirty；Risk gitlink 前序为 `ba86c1ad` / `cd005d2`。原 bug 在 blocked / partial 或 cursor unproven 前先调用 `facts.note_event_day`：合成真实 Risk 内存账本经济冲突下 blocked 且 last / applied / covered 已前进，可能污染缓存但 pump 不 ACK。修复先检查 blocked / partial / cursor 与本地绑定；默认 `RiskFactsCache` 同一 covered page 取最大有效日期、仅一次 callback，再在 ACK 前检查 observer / generation / epoch / reentry 和 cursor revision，已知本地失效先短路。健康每页固定 3 次 cursor 检查，首次 reset 另一次；纯 fake 256 计数不是生产吞吐。真实 cache callback 从逐条变每页一次，对自定义 facts 有兼容变化。callback 自身可能部分写入且不回滚，最终校验与 ACK 不跨线程 / 实例原子；合法 prefix 后遇坏映射仍 ACK prefix 后 gap。真实 Gateway、来源 / 账户 / 事务 / fence、持久重启、真实 ACK 和吞吐未验证。新增已提交 `test_iter64_observation_event_day_fake.py` SHA-256 `b240e529bc80e00e70b1651f946c0d2f4c1e8e6ee529b19b3f5f75862868db15`；SDK HEAD + 仅替换 ObservationPump 类的混合环境主会话 **8 passed / 1 warning**，原 HEAD 执行方负对照 **6 failed / 2 passed**；其余 Risk / SDK 来自环境，非 clean 包。另未提交真实 Risk 内存 SQLite + fake observer 测试 `test_iter64_trade_conflict_ack_memory.py` SHA-256 `13df7a930e0e6bb569f3df763fd90a539efdf74ca15610eedd32c7523f6af3e6`，主会话与既有部分 pure fake 定向组合 **25 passed / 1 warning**（禁插件配置警告）；同进程新 pump 不等于跨进程重启，fake ACK 非真实 Gateway。开发中初始两失败证实污染、双栅栏初版三失败证实重入 ACK、逐条版五失败证实回调 / 性能预算，修复后通过，以上均非全量。UNKNOWN 与 R03 内存测试最新分别 **23** 和 **10 passed**；R03 test SHA-256 `4054bce47221116297255c014817dea5bbec545a8f9d6708a2b8a4a6fe7010fa`，economic conflict 时明确 `last=3 applied=1 covered=1 blocked`，重放仍阻断；该计数不是 ACK。历史 660 失败 / 错误与误跑记录保留，R03 聚合业务问题仍待用户回答，整期 **NO-GO**。 主会话另使用 SDK `c7c0eb42097ce8df23bc3c4ac0cd65f162b3b17d`、Risk `cd005d2525ea59f04e3b5a8aa5d5d9e86651dc8a`、Base `b70e920ca86f687b40d59ed88d533f837f6da7ef` 的 git archive 构造独立临时源码树，禁用 pytest 插件 / cache 与 bytecode，核验 3 个关键模块 `__file__` 均位于归档后，纯 fake 新测试 **8 passed**；临时树已自动清理，未运行 host / fence / socket / SQLite。第三方依赖仍借 Conda base，是源码归档验证，不是干净 wheel 或生产验证。

### SDK event-day gap 局部修复

据主会话提供的本轮证据，SDK dev `fdc830f1a2ef7e27124516f33f1a831c0fbf0844` 已本地提交，仅暂存 `RiskFactsCache` / `ObservationPump` 九处审查过的 hunk 和两份 pure fake 测试，保留其他 dirty。known gap、首轮 poll / 重连及 ACK 失败等撤销观察事件日、保留 market 日；先失效后 mark，callback 后再次失效。连续相同恢复读失败不重复写 gap；mark 异常、清理重入或代际变化保持待重标，清理普通失败仅重试清理。`verified_epoch` 捕获 engine / observer / generation / epoch / after / target / revision 并在 callback 后复核，递归及 poll 同步重入失败关闭。SDK mapper 对缺失 / 非法日保守停止坏回报及后缀，不越界 ACK，合法 prefix 可 ACK；broken 已发现时 apply 前 / 后清 event 日且不投影 prefix 日。匹配 `GatewayExecutionObservation` 1–3 经 `GatewayReturnFact` 1 / 4 要求 ASCII 有效日期；`DirectExecutionEvent` / 直接 Risk 路径允许 None，本次不覆盖直接路径。旧或自定义 observer 缺日可能永久反复阻断不可变历史，需恢复合同；custom facts 必须有幂等 `forget_event_day`，若虚报成功不可证明清理，首 poll 前直接读取预置 facts 仍可能看到旧日。独立 review fake 指出受信 engine cursor callback 可在 broken 清理后重写 event 日，ACK callback 可短暂读到；但 `verified_epoch=None`、ACK 仅覆盖合法 prefix，最终 gap 清理；无已证生产事故。market_day 来源 / 时效、poll 中未完成 replay 可见、外部游标、非事务 cache 与跨线程 / 跨实例 ACK 仍为 GAP。两文件纯 fake 源码归档（SDK `fdc830f1` / Risk `cd005d2` / Base `b70e920`）核实 3 个关键 `__file__` 位于归档，借 Conda base 依赖得 **58 passed**；当前工作树 3 文件加 6 条旧回归，主会话 **75 passed / 1 warning**（禁插件配置警告），包含内存 SQLite / fake transport，不是真实 Gateway / 账户 / ledger 事务。旧行为导致 **27 passed / 10 failed** 后按合同更新断言；开发中收集失败、**41 passed / 1 failed**、**57 passed / 1 failed** 分别修正，仅说明测试迭代，不抹去历史 660 失败 / 错误或旧误跑。新未跟踪 `trade_conflict_ack_memory` 与 Risk 其他 WIP 未提交；R03 账户合计 / 净额问题仍待用户回答，整期 **NO-GO**。
