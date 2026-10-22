# 迭代42 验收报告 2026年10月12日

**验收结论：部分完成，整体验收未通过，当前不能标记为已完成。**

八个示例的标准四件套和目录内直接脚本离线入口已具备，本次 dry 8/8、replay 8/8 均退出 0。公开记录支持四个示例的历史真实模拟盘成交往返，以及 015 的 tick 到达观察通过；013_3、014_1、014_2 尚缺各自目标层级的通过证据。迭代43重组后还存在两个加密示例的根级清单路径失效、README模块命令失效、迭代42 tracker 未迁移，以及回归测试未同步的问题。

本报告确认已经完成的交付，并列出剩余验收条件；不以离线测试替代账户验收，也不否定已有的历史成功运行。

## 验收范围与基线

| 项目 | 本次口径 |
| --- | --- |
| 验收日期 | 2026年10月12日，北京时间 |
| 仓库与分支 | `D:/source_code/backtrader`，`dev` |
| 被验收提交 | `9ef0e00aa38da900ca8835d93b81f2c16cf782d9` |
| 解释器 | `C:/anaconda3/python.exe`，CPython 3.11.5；pytest 8.0.0 |
| 实现范围 | 012_1、012_2、013_1、013_2、013_3、014_1、014_2、015；不扩展到016/017或迭代41认证矩阵 |
| 实际操作 | 公共需求、源码、历史脱敏记录审查；现有离线/假场所测试；dry/replay；只读清单校验 |
| 账户证据边界 | 未重新连接场所、登录、报撤单；未读取 `.env`、ignored 私有配置或现场 private captures；历史 live 结论来自已跟踪的公开摘要，未重新核验 ignored 原始 live JSON |
| 文件保护 | 验收执行前后，219个选定公共文件的 SHA-256、HEAD、原始 index、tracked diff 和完整 Git 状态全部一致；本轮仅新增本报告和相邻 JSON 结果文件 |

SDK环境另行记录于[结构化验收结果](acceptance-audit-2026-10-12.json)：父仓库为 `cfe6543e7bc9aaa3622624f1b490b4d5f99f3766`，risk/execution/monitor 均使用各自现有 `dev`。这些源树测试不构成安装包、发布或部署验收。

## 重组后的路径与验收标准

八个示例目前统一位于 `examples/unified/<原目录名>/`，目录名保留。认证套件改到 `examples/live/000_live_certification/`，仓库支持文件改到 `examples/_support/`。历史记录中的旧路径按这一映射理解，历史材料不因搬迁而重写。

验收采用[迭代42计划](../迭代计划.md)及其后续明确修订，而非机械要求八例都成交：

- 012_1/012_2：接受已记录的有界机械 Demo 技术往返例外，保留研究拒绝与 HFT 未准入状态。机械信号不证明原研究信号有效。
- 013_1/013_2/013_3/014_1：需要对应全部交易腿真实开平、订单终态与最终持仓/活动单对账。源码完成或纯拒单不能替代。
- 014_2/015：计划§6已改为零写观察层，不能再把未实现的写路径作为本轮必交项。015的实际通过层级是 tick 到达及真实拒绝事实，不包括有效 cohort 决策。
- [迭代43计划](../../迭代43-examples目录三类重构与config选层/迭代计划.md)§1记录用户于2026-10-11取消周一六步时段排期约束。因此本次不将“未在周一指定时间重跑”列为未完成原因；013_1/013_2已有7×24往返应保留其真实技术证据，标准前置未单独验证则注明覆盖范围。
- R10/R10b/R11/R12退役的是旧登记路由、启动器或独立旧示例，八例当前直接 `run.py` 入口仍存在。退役不等于直接 live 目标验收通过。

迭代43新增 `config.entry.tier` 选层和无写观察通道；`entry_tier` 表示通道选择，原 `tier` 表示结果层级，两者应分别判读。无参数不再无条件等于 dry：未声明时默认 dry，显式声明 live 时按新合同进入 live 通道。

## 逐示例结论

以下目录均以 `examples/unified/` 为前缀。本次八例 dry/replay 全部通过；表中的 live 为历史公开证据层级，不代表当前HEAD重新实跑。

| 示例目录 | 公开记录可支持的历史结果 | 当前验收结论与缺口 |
| --- | --- | --- |
| `012_1_midfreq_cross_exchange` | `447e9a10`：机械Demo往返，4笔成交，`FLAT_RECONCILED`、远端flat、活动/未知订单为0；后续 `82a55b70`再次成功 | 历史机械技术通过。当前根级canonical manifest仍指向旧目录，当前Demo路径在源绑定检查被阻断；不能据旧成功宣称当前live可用 |
| `012_2_event_driven_cross_exchange` | `f28557f7`：双所4单4成交，平仓与远端flat确认；机械分支明确绕过研究模型门 | 历史机械技术通过，非原策略研究或HFT准入通过。存在同一canonical manifest路径阻断 |
| `013_1_midfreq_cross_arbitrage` | `7e938fc7`：7×24，m2612/RM701两腿各开平1手，4个订单引用、8条交易行，持仓/活动单为0，`run_error=null` | 接受为历史7×24全腿往返证据；标准前置覆盖未单独证明，不要求为本报告重复已成功运行 |
| `013_2_highfreq_calendar_arbitrage` | `3583ad31`：7×24，rb2701/rb2705双腿完整往返、最终归零 | 接受为历史7×24全腿往返证据，保留HFT未准入边界；早先失败后的人工清理不算自动成功，采用后续成功记录 |
| `013_3_sa_midfreq_simnow` | 已有登录/行情/门控与修复记录；公开记录仍为缺限价、无成交或drain待验证 | **未完成成交层验收**。需真实成交往返、会话归属明确的逐腿成交核算，以及自动平仓/对账终态 |
| `014_1_ctp_options_lowfreq` | 严格live adapter已实现；`5a848a7f`在7×24限价资料闸门前BLOCKED、未进入三腿武装 | **未完成三腿成交验收**。需要可用C/P/F行情和限价信息下的三腿开平、预算、对账及资源退出证据 |
| `014_2_ctp_options_midfreq` | 实收三腿行情，但 `live_event_clock_outside_run_mapping`，事件钟陈旧约47.9小时 | **未完成观察层验收**。需要真实有效分钟特征窗、密封证据与运行时钟一致，`feed_evidence_fault=null`、零写 |
| `015_ctp_options_highfreq` | `39d69fb7`：240.3秒、FG/C/P各收到151/13/1个tick，`order_write=0`、`OBSERVATION_PASS` | 仅接受tick到达观察层。165次 `TRUSTED_NOW_INVALID`，`cohort_decisions=0`；不能标为有效策略决策、成交或HFT通过 |

对应历史依据：[R2加密中频记录](r2-acceptance-record-2026-10-10.md)、[R3加密事件记录](r3-acceptance-record-2026-10-10.md)、[R4跨品种记录](r4-implementation-and-smoke-record-2026-10-10.md)、[R5跨期记录](r5-implementation-record-2026-10-10.md)、[R1运行进展](r1-live-run-progress-2026-10-10.md)、[R6期权低频记录](r6-0141-strict-live-adapter-2026-10-10.md)、[R7期权中频记录](r7-0142-observation-tier-2026-10-10.md)、[R8 tick观察记录](r8-015-observation-tier-2026-10-10.md)。

因此应分别报告“4例历史成交往返”“1例tick观察通过”“3例目标层级尚未通过”，不合并成无条件的5/8完整PASS。

## 本次实际验证结果

| 检查 | 实际结果 | 可支持的结论 |
| --- | --- | --- |
| 八例 `run.py --dry` | 8/8，退出0 | 当前公开配置与离线入口可用 |
| 八例 `run.py --replay` | 8/8，退出0；012_x为`FORMULA_CHECK_PASS`，其余为`LOCAL_REPLAY_PASS` | 当前公式/fixture回放可用，非完整历史回测或账户验收 |
| 迭代42聚焦，5个文件 | **57 passed / 8 failed**，65项，退出1 | 原有回归网尚未适配全部新入口行为 |
| 迭代43选层、布局、假场所无写观察，6个文件 | **132 passed / 4 skipped**，退出0 | 当前选层和观察边界的离线行为通过 |
| optional16假场所挂载 | **5 passed**，退出0 | 真SDK组件与假场所的局部交互通过，不是迭代42八例的真实组件矩阵 |
| 自包含守卫 | **42 passed / 3 failed**，退出1 | 仍有已登记的3项基线失败，其中2项关联013_1/013_2 |
| 复制到仓库外的unified文件过滤契约 | **8 passed / 34 deselected**，退出0 | 八个复制集合未携带ignored文件；此组节点未执行复制后的入口 |
| 复制后八例dry启动合同 | **8 passed / 34 deselected**，退出0 | 七例直接运行退出0；012_1按既有测试合同明确拒绝缺少checkout。通过的是“运行或准确拒绝”的合同，未证明八例全部便携，也未覆盖全部目录外replay |
| README中的两条012_x模块启动命令 | 两例均退出1，`ModuleNotFoundError: entry_tier` | 从仓库根按文档使用 `python -m ...run --replay` 确实不可用；区别于已通过的目录内直接脚本命令 |
| `refresh_cross_exchange_local_manifests.py --check` | 两例均`up to date`，退出0 | 目录内清单自洽，不证明根级canonical清单或live准入可用 |
| 登记离线冒烟 | **8 passed / 0 failed / 2 skipped**，退出0 | 当前登记replay可用；两个私有只读路由在读取配置前跳过 |

测试命令使用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH=D:/source_code/backtrader`、`--noconftest`，cache/basetemp/evidence均指定到本轮仓库外临时目录。禁用conftest避免根conftest执行既有临时目录清理；本次为所列现有测试的隔离验收，不是全量CI结果。每个pytest进程均记录1条 `asyncio_default_fixture_loop_scope` 未识别配置警告，不声称零警告。

4个skip分别为配置选层replay抽样合同中的013_2、013_3、014_2，以及无标准入口的007_ctp。另行逐例执行的8条replay已覆盖前三例的命令行回放，不把skip计为通过。

精确命令、测试节点、失败分类、日志哈希、逐例退出码和219个输入pin见[结构化验收结果](acceptance-audit-2026-10-12.json)。临时原始输出位于 `D:/temp/iteration42_acceptance_20261012_9cb01d2e/`；机器迁移后可依据相邻JSON中的有限结果和命令复验。

## 未通过项与影响

### 当前加密Demo入口被旧根清单阻断

`examples/strategy-candidate-manifest.json`中012_x的 `resolved_example_path`仍是 `012_...`，实际应定位到 `unified/012_...`；旧目录已不存在。两例 `run_live`仍向内部引擎传入 `REPO_CANONICAL_MANIFEST`，而 `legacy_runner.load_candidate()`要求解析目录等于当前 `HERE`，否则抛出 `manifest resolves to a different example`。机械演练例外不绕过这一先行来源检查。

这是一项可由公共源码与路径确定的重组后可用性缺口，不能归因于交易所。依据：012_1 `run.py:290`、`legacy_runner.py:351–358`，012_2 `run.py:296`、`legacy_runner.py:274–281`，以及[迭代43 R2清单处置](../../迭代43-examples目录三类重构与config选层/evidence/r2-unified-relocation-2026-10-11.md)。本次未发起live验证。修复时须受控重绑候选指纹与相关receipt，保留研究拒绝和签名边界，不能只替换字符串使审批失真。

### 三例目标层级仍未闭环

013_3、014_1缺完整成交/清理通过记录，014_2缺有效观察窗通过记录。014_2/015写路径已明确不在当前范围，不应为凑八例成交擅自新增；015的tick观察也不能替代014_2的分钟窗口验收。若存在本报告未审查的后续现场结果，应先通过保护流程形成可核查的公共脱敏摘要，再更新结论，避免重复已消费的运行。

### 迭代42 tracker和计划摘要陈旧

`scripts/generate_iteration42_tracker.py:26`仍以 `REPO / "examples"`为根，`:144`按 `EXAMPLES / name`拼路径，重组后找不到八例真实目录。现有[tracker](iteration42-example-tracker.md)生成于2026-10-09，仍将012_x写为BLOCKED、013_1/013_2写为PENDING；[R9清单](r9-acceptance-audit-checklist-2026-10-10.md)也保留后来已取消的周一排期描述。

生成器还依赖硬编码dry/replay状态，按文件mtime选择最新现场run，且只用PASS/FAIL/UNKNOWN覆盖默认状态，BLOCKED不覆盖；不能将“最新尝试”“历史最好结果”“当前版本能力”可靠分开。本次未运行生成器，也未覆盖旧tracker。最终交付仍需按计划§7.1补齐每例来源提交、环境、逐腿成交、清理、证据引用及哈希。

### 测试没有完全跟随新入口语义

本次11个失败节点分为三类，不混称交易功能失败：

1. **4个动态装载兼容失败**：`test_iteration42_component_boundaries.py:48–59`用 `spec_from_file_location`装载012_1/012_2/013_1/013_2，但未建立例子目录的本地import路径；新顶层 `import entry_tier`报 `ModuleNotFoundError`。直接CLI dry/replay已通过，故不能据此断言直接脚本CLI失效。另行复验012_1/012_2 README第22行的 `python -m examples.unified.<目录>.run --replay`，两例也均在 `run.py:92/93`同因退出1，属于真实的文档启动合同缺陷，不能全部归为测试装载问题。
2. **4个陈旧的文本断言**：`test_iteration42_live_front_failure_evidence.py:137`要求整个文件的专用handler只出现1次。013_1/013_2/013_3/014_1现有observe逐pair、observe外层、write外层三个不同try范围，实际为3。应按函数/失败路径验证持久化语义，不能删正确handler迁就字符串数量。
3. **3个既有基线失败**：自包含测试中的000认证组件导入、013_1/013_2 `ctp_example_support.py`副本漂移，已登记于[迭代43 R0基线](../../迭代43-examples目录三类重构与config选层/evidence/r0-baseline-freeze-2026-10-11.md)。000属于范围外债务；两个CTP副本相关失败须在迭代42收尾中明确处置。实际差异包含 `BtApiStore`导入、fail-closed函数和 `iter_simnow_env_candidates()`行为，**并非纯换行差异**。尚未证明这些差异破坏当前标准dry/replay，但已违反声明的同源副本契约。不能删断言、转skip或以EOL解释全部差异。

### 无写观察的证据降级尚不明确

013_1/013_2/013_3/014_1的 `run_live_observe`在 `registered_sim_write_health()`异常时仅写入 `write_health_error`，随后仍输出 `LIVE_OBSERVE_PASS`并退出0；也未在这段成功条件中要求健康计数全为0。源码位置分别为 `run.py:704–707`、`:705–708`、`:672–675`、`:815–818`。

这是静态可见的证据完整性缺口，不是本次观察到真实写入。假场所正常路径通过不足以接受健康读取失败的分支。后续应补错误/非零计数的负例，明确在缺少健康证明时返回BLOCKED、部分观察结果，或以独立可靠的只读约束证明其零写边界；不能把无健康证据的PASS解读成零写计数已确认。

### 活跃README仍混有旧操作面

015 README第49行称日常入口为 `run_runtime.py`，第150–166行及第208行仍给出 `legacy_runner.py`/`simnow_launcher.py`的直接操作命令，与开头“run.py唯一入口”和退役启动器说明不一致。012_x的模块命令缺陷见上文。应清楚区分历史说明、包内API和当前可执行命令，保留必要内部模块不等于保留多套对外入口。

## 后续改进顺序与通过条件

| 优先级 | 后续工作 | 完成判据 |
| --- | --- | --- |
| P1 | 受控修复012_x根canonical manifest与重组后的绑定链 | 路径、候选指纹、配置/入口hash、receipt关系一致；先做无凭据来源检查及失败边界回归，再按实际受影响范围验收Demo；不提升研究/HFT准入 |
| P1 | 补齐013_3、014_1、014_2目标层级 | 013_3真实开平并自动flat；014_1 C/P/F全部开平成交及对账；014_2有效分钟特征窗/密封证据/真实时钟、零写。每项保留失败记录与明确的外部阻塞事实 |
| P2 | 修复文档模块启动、测试装载和handler回归合同，处理支持副本登记 | 文档命令及新入口的离线测试通过；支持模块按实际职责统一或独立登记来源，漂移守卫真实有效；000范围外失败单列，不掩盖 |
| P2 | 明确无写观察的异常证据语义 | 健康查询失败/非零计数负例通过，PASS只覆盖有足够事实支持的观察范围；不以正常路径假测试代替异常分支验证 |
| P2 | 迁移tracker并形成最终公共状态矩阵 | 从已审阅的脱敏摘要生成；分列历史成功、最新尝试、当前能力、结果层级、环境、清理、证据hash及代码版本；旧历史不覆盖，BLOCKED如实保留 |
| P2 | 同步活跃说明和便携边界 | 计划/README/tracker相互一致；旧Monday文档标明排期已撤销；明确012_1 checkout依赖，补所需目录外replay检查；无写观察不冒充策略成交 |
| P3 | 后续独立能力增强 | 015如需有效cohort决策，另做真实quote证明及决策时钟适配；盈利、生产准入、HFT延迟矩阵继续独立，不列作本轮已完成 |

后续应继续采用“明确一轮范围 → 完成该轮验收 → scoped dev提交”的现有流程；已经通过且来源未受影响的真实运行无需为文档汇总重复执行。本轮遵守只验收要求，未实施上述修复。

## 交付判定

可接受本次已证的四件套结构、目录内直接脚本的离线可运行性、部分历史真实模拟盘往返及015有限观察结果。**在当前加密Demo路径恢复、三例剩余验收证据闭环、相关回归与最终状态矩阵收尾之前，迭代42整体维持未完成。**

本报告和相邻JSON作为本次只读验收轮的新增交付；旧计划、tracker、历史证据和所有实现代码保持原样。
