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
