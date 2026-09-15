# Backtrader 1.4.0 历史 master 对照与 dev → development 提升审计

> **历史审计上下文。** 本文保留当时的差异、治理和候选观察；当前发布状态以[联合验收与发布记录](../../1.4.0联合验收与发布记录.md)和[修复后本地候选证据](post-fix-local-closeout.md)为准。主仓仍只允许 dev -> development，master 为 **NOT_TOUCHED**。

审计日期：2026-09-15。工作目录：`/Users/yunjinqi/Documents/new_projects/backtrader`。

## 结论与证据边界

分支边界已于 2026-09-15 更正：本次只允许 `dev` → `development`，不构成三分支政策的例外。`master` 是原始 Backtrader 的历史只读基线，必须 **NOT_TOUCHED**；不得向其合并、从其构造合并提交、推送、作为本次 CI/tag/Release 目标，或为本次工作创建回滚 tag。

不能把“全部采用 dev 树”直接称为无损合并。本次发现并补回 MACD.lines.me1/me2 和 PyFolio.get_format_results 及四个 helper，保留调用签名与主要返回结构，同时修复旧报表的实质错误。下面逐项审计只证明这些兼容处置适合保留在现代 dev 候选；仍须保留现代导出/观察器命名与历史布局差异的说明，并通过 `dev` → `development` 的最终门禁。

最近三个 broker/feed 正确性修复已有现代等价实现及专门回归。其余明确的库缺陷修复在现代结构中已保留或对应被移除的旧组件。旧测试、策略、工具和文档的大量变更保留在历史 master 基线中，按现代路径及现有验收合同运行，不应复活整个旧布局。

本审计既非最终 `development` 候选的全量测试结果，也非 PyPI 发布授权。本子任务实际运行 MACD/PyFolio 兼容与原有回归，联合17项通过；其他测试仅检查源代码与断言。父任务负责最终 `dev` → `development` 树、CI、完整验收和发布。

## 冻结 Git 对照范围与历史合并风险

| 项目 | 值 |
|---|---|
| 历史只读 master | `b418caf7364e1134983a4c4b394768686e1916aa` |
| 审计时已提交 dev | `404383b7e92690374f33563e90c70497c98860b9` |
| master 独有提交 | 62（其中 1 个双亲合并提交） |
| dev 独有提交 | 1083 |
| 历史 `git merge-tree --write-tree --name-only master dev` 对照 | exit 1；284 个冲突路径 |
| 历史预演 tree | `3c1dce65b1177d3d3fff550a6907f4a420a7c03c` |

284 个冲突路径：backtrader 172、tests 83、strategies 13、scripts 4、studies 3；其余为 `.github/workflows/docs.yml`、`.gitignore`、CLAUDE.md、README.en.md、README.md、docs 中一个文件、pyproject.toml、requirements.txt、setup.py，各 1 个。冲突诊断出现 content 163、add/add 12、modify/delete 98、rename/delete 14；诊断可重叠，不能把这些数字相加当路径总数。这是历史对照，当前不执行此合并。

只解决历史对照中的显式冲突仍不安全。该预演会自动合入 dev 已删除的旧文件：

- `.github/workflows/publish.yml`：`release.published` 会自动尝试发布生产 PyPI。当前用户仅授权 GitHub/Gitee 发布，必须保持删除。
- `.github/workflows/release.yml`：tag push 自动构建并创建 GitHub Release，无需 CI 完成，也无 tag/version 一致性校验；会与本次受控发布重复。必须保持删除。
- `.github/workflows/sync.yml`：包含 `--all --force`、`--tags --force`，与本次定点双远程发布冲突。必须保持删除。
- `.github/workflows/tests.yml`、`codeql.yml`、`pages-simple.yml`、`docs.yml.disabled`：旧流水线/旧配置自动回流。应维持现代 dev 的明确文件集合，任何恢复需独立说明用途。
- `backtrader/configs/account_config.yaml`：master 独有跟踪配置自动回流。只读取了路径与 Git 元数据，未读取或输出内容；必须维持 dev 删除状态。

不得以旧 master 和验收后的 dev 构造两个 parent 的合并提交。284 个冲突路径只说明不能机械混合两代元类/非元类架构；本次应保留下面的兼容处置表、解决剩余公开接口差异、验证获准 dev tree，并依 `dev` → `development` 的流程运行发布门禁。父任务管理正式 Git 操作；本子任务未 checkout、改 index、提交、fetch 或 push。

## 行为修复与等价证据

| master 提交 | 原行为 | 现代 dev 证据与处置 |
|---|---|---|
| b418caf7 | stacked bar 使用旧 tick 价格 | `backtrader/feed.py::_fromstack` 调用 `_tick_fill(force=True)`；`tests/unit/brokers/test_bbroker_edge_cases.py::test_market_order_uses_final_stacked_bar_open_not_stale_tick_open` 断言最终成交价 4。保留现代实现。 |
| 8a71452b | Submitted 订单不能取消 / OCO sibling 残留 | `BackBroker.cancel` 对 alive/status 检查并搜索 pending、submitted；`test_cancel_submitted_oco_member_cancels_submitted_sibling` 断言两腿 canceled 且 sibling 未 Accepted/Completed。保留现代实现。 |
| d35750e5 | margin 拒单污染后续订单 cash/position 试算 | `BackBroker.check_submitted` 用 trial_position.clone()/trial_cash，只在通过时提交试算；`test_margin_rejected_order_does_not_reserve_cash_for_next_submission` 验证超额单 Margin、随后可负担单 Completed。保留现代 dualside 扩展。 |
| 39cb9531 | TradeLogger 生命周期与事件转发 | 当前 `Strategy._notify_*_to_observers`、`_cerebro/notifications.py`、TradeLogger 的 stop/position/order/trade 路径已覆盖；`tests/integration/test_trade_logger_runtime.py` 包含 store/data、reject、batch cancel、reconnect、channel-mode 真运行测试。保留现代实现，勿复制旧元类代码。 |
| efab731a | empyrical 应延迟到扩展报表调用时导入 | 当前 PyFolio 模块无 empyrical 顶层导入，基础 `get_pf_items` 不依赖它，保留导入容错意图。但不能由此推断旧报表接口已保留，见 f222ee35。 |
| d6cfcd7c | 暴露 MACD.lines.me1/me2 | 确认现代 dev 缺失并已最小补回 `self.lines.me1 = self.me1` / me2；不增加输出 lines。新增 `tests/unit/indicators/test_macd_master_aliases.py`。详情见实际验证。 |
| 9fb8960b | 缺 statsmodels 导致 import backtrader 失败 | 当前 `backtrader/indicators/ols.py::_get_statsmodels` 惰性导入，顶层导入不会要求 statsmodels。已有 `tests/unit/indicators/test_ind_ols.py`；本子任务未实际运行可选依赖缺失环境。 |
| e8743889 | DataTrades 用非字符串 data._name 动态创建 lines 时出错 | 现代 `DataTrades` 固定 data0…data9 lines，`_setup_plotlines_simple` 使用固定 alias，旧 `_derive(lnames)` 崩溃入口不存在；`tests/unit/observers/test_observer_trades.py` 验证 plotlines dict 和按 data 分发。非字符串名字专门实际用例未在本子任务运行；超过十数据的固定容量是现代既有范围，不能冒称与旧动态命名完全同构。 |
| 0696eba6 | indicators 显式 __all__ 便于 IDE | 当前正常分支由子模块导出、LIGHT_IMPORT 分支显式导出；原提交的硬编码 118 项列表甚至未包含所有后来指标。不要恢复旧列表以免隐藏新增导出。属于静态 IDE 可见性变化，而非计算修复；没有证明完全相同的 `__all__` 反射契约。 |
| f222ee35 | 名为 format，实际包括 PyFolio 新报表功能 | AST 比较去掉独立字符串表达式后，169 个库 .py 可执行 AST 不变；2 个不同为 pyfolio.py（新增功能）和 btrun.py（帮助文本拼写）；另 3 个旧内嵌测试被删除。PyFolio 新增 `_get_order_type`、`_compute_profit_loss`、`_get_trade_info`、`_get_performance_indicators`、公开 `get_format_results`。现代 dev 无这五个入口，git log dev -S get_format_results 无迁入记录，当前 reports 无同名适配，旧 master git grep 也仅发现其定义。本次已补入五个入口、原 performance 字段和十九列交易表，见后文实际回归。不能将原提交称为纯格式。 |
| e19f5eb2 | Python 3.12 UTC 时间兼容、删除旧 native/策略布局、CI | `_cerebro/runnext.py` 的 qstart/qlapse 使用 datetime.now(UTC)，`resamplerfilter.DTFaker` 同样使用 UTC；ccxtfeed/ibdata/ibstore/oandastore 已由现代 dev 移除，勿为 timezone 变更复活旧组件。旧 cython/native 文件在现代构建中也无扩展入口。CI 部分保持现代规则，旧发布/同步 workflow 不恢复。 |
| 764c0714 | ComminfoFundingRate 资金费率支持 | 当前 `backtrader/comminfo.py::ComminfoFundingRate` 存在且有增强 fallback；`tests/unit/brokers/test_comminfo_fillers_edge_cases.py::TestComminfoFundingRateFallback` 与 `test_quality_improvements_v4.py::test_comminfo_funding_rate_none_margin_fallback` 有断言。保留现代实现。 |
| d4159c49 | Python 2 分支 iteritems 改 items | 只影响 `if PY2`；本项目支持 Python 3.8–3.13，现代 Python 3 分支不受影响。按已声明平台范围不需迁入 Python 2 变更。 |
| 69580a40（策略） | ExtendPandasFeed 在 set_index 后列错位 | 现代 `tests/functional/strategies/special/test_01_premium_rate_strategy.py` / `test_02_multi_extend_data.py` 已把 datetime=None、open=0、volume=4、openinterest=-1、自定义字段5…8；保留现代可执行回归，旧 strategies/0025 路径留在历史，不复活旧布局。 |
| 4694372b（工具） | 子进程日志截断 | `scripts/run_test_with_log.py:258` 使用 process.communicate() 收完整输出；保留 scripts 下现代工具，不恢复根目录副本。 |
| 937617da（构建） | Windows 安装脚本与 setup 作者名 | setup 的修改只将 author 改为 cloudQuant；现代 setup 当前 author=cloud；这项署名差异需父任务明确保留 cloudQuant 或说明处置，不影响运行逻辑，构建为纯 Python。Windows 安装旧脚本不能替代本次 Windows matrix。 |

### PyFolio 兼容补入与明确修复

五个方法签名、performance 字段和十九列交易表已补回。原基础四子分析器和回测热路径不增加报表计算，不新增 empyrical 依赖。

- 按各标的实际持仓转换确定开平仓，替代 pair_num=1 全标开仓；pair_num 参数继续兼容接受。
- 按有符号成交数量确定买卖，不再反转买入平空/卖出平多。
- 加权持仓成本处理部分平仓、加仓、反手；反手拆成开平两条记录，不跨标的配对。
- COMMISSION 保留字段，Transactions 未记录实际手续费时为 NaN；有 commission 输入时按拆分数量分摊。毛盈亏仅使用原始价格/数量，不推断输入缺少的期货合约乘数；净交易统计读取已有 TradeAnalyzer。
- TradeAnalyzer 任意名称均可读取；有交易但没有该分析器则胜负统计为 NaN，空交易则零计数，不虚构缺失证据。
- 现有 numpy/pandas 完成252交易日指标，去掉 stdout print，不再调用 empyrical 缺失的 API。未定义比率为 NaN；DATE_REGION 为峰值/谷值/恢复日期三元组，无回撤为 None，缺少端点为 None。

最终联合验证：17 passed in 5.66s。PyFolio 新八例加原三例；MACD 新四例加原二例。PyFolio 真实多空预期：long 2 @10→12 收益4，short 3 @14→10 收益12，long 2 @9→8 收益-2，最终资金1014、胜二负一；另验证多标的/部分平仓/反手、输入手续费分摊、未知手续费、无交易、无TradeAnalyzer、输入不变性及无stdout。独立四日收益序列验证 beta=2、alpha=0、Sharpe/Sortino/信息比率/波动率及最大回撤。

## MACD 实際验证

新增用例先于修复运行：4 failed，全部在 `self.macd.lines.me1` 抛 AttributeError；确认回归命中真实缺口。

最小修复后运行：

```text
/Users/yunjinqi/opt/anaconda3/bin/conda run -n base python -m pytest tests/unit/indicators/test_macd_master_aliases.py tests/unit/indicators/test_ind_macd.py tests/unit/indicators/test_ind_macdhisto.py -q --tb=short -n 0
6 passed in 2.46s
```

新增四例为 MACD/MACDHisto × runonce/runnext，使用真实 PandasData → Cerebro → Strategy → Indicator。断言别名对象身份、输出 line 名集合不变、六根有效 bar 的 fast EMA / slow EMA / MACD / signal 独立固定值、MACDHisto 值。新测试已用项目 Black 格式化。本结果与上述联合结果绑定本地四个兼容文件，不等于最终发布 tree 的完整验证。

## CI/release 工程审计摘要

- 审计时 GitHub master/dev 无 branch protection、rulesets 为 0、Actions variables 为 0，`GOVERNANCE_BLOCKING` 缺省 false。因此 PR Governance 当前为告警观察，不是强制授权系统。发布 PR 必须明确本次 `dev` → `development` 路线；不得伪装成 `hotfix/master-*`，也不得对 master 进行任何本次发布操作。
- 最近 dev Tests run `34907186010` 在 isort 对 `backtrader/cerebro.py`、`backtrader/plot/locator.py` 失败，矩阵随 needs lint 跳过；不是测试已全部通过。其余 Ruff/Black 当次通过。isort 未固定版本，runner 当次使用 9.0.1。
- 旧 CI 所有测试用 -n auto，会跳过性能标记。父任务已加入 serial lane 及 `make ... BT_CONDA_PYTHON=python`，修复 Ubuntu 调用本机 Anaconda 绝对路径的障碍。
- `.[dev]` 缺少 bt_api_py，但多处测试顶层导入 SDK，清洁 runner 收集会失败；父任务正在处理明确的兼容 SDK 安装来源和 Python 范围。不可用整体 skip 假造绿色。
- `tests/unit/test_ctp_options_midfreq_timing.py` 曾硬编码用户 Python 路径用于子进程，Linux/Windows 必失败；父任务负责改 sys.executable。
- coverage 安装 `.[dev]` 没有 pytest-cov，且步骤 continue-on-error=true；须明确安装插件并区分不可运行与低覆盖率。
- spdlog 可选不可用时测试 BACKENDS 列表直接不含 spdlog，因此普通绿色不能证明双后端；需独立可用后端证据和真实 spawn 子进程场景。macOS 验证不能冒称全部矩阵平台已验证。
- `scripts/release.sh` 测试旧路径 `backtrader/tests`、允许跳测/失败继续、裸 python/pip、提交时可能携带已有 staged 内容、在当前分支先 tag、`push --tags` 推全部 tag、另含交互 twine upload。不要用于本次受控发布。
- 当前 dev 没有自动 PyPI 发布流程。由于 master 必须 NOT_TOUCHED，历史 merge-tree 所显示的 master `publish.yml` 自动回流风险不进入本次流程；不得以它为由恢复旧发布工作流。

最低充分发布矩阵：保留项目声明的现有 3 OS × Python3.8–3.13 功能矩阵与稳定汇总检查；明确 Python/SDK 可运行组合，不把不可收集当成功；Ubuntu3.11 serial performance + 独立 RSS；支持平台的 stdlib/spdlog 与真实 spawn；精确 1.4.0 wheel 出仓安装、版本/源码哈希/模块来源检查并运行消费者。最终 full strategy 1271 项与全部功能套件由父任务执行；旧 Iter28/29 历史 PASS 不替代最终 commit 的门禁。

版本文件：`backtrader/version.py` 为单一版本源；`setup.py` 和 Sphinx conf 动态读取；README badge/示例、AGENTS 版本摘要、CHANGELOG 的 1.4.0 条目同步。不要全仓替换历史设计和测试证据中的 1.3.0。

发布顺序：补足验收/版本/CI → task-owned allowlist 提交到 dev → 两远程精确 ref 验证 → 受控 `dev` → `development` 提升候选 → 最终候选门禁 → development 落地并双远程验证 → 对实际接受的 development commit 打单一 1.4.0 annotated tag → 从该 tag 构建一次 wheel/sdist/sha256 → 双平台 tag object 与 peeled commit 校验 → GitHub/Gitee release 使用相同字节和明确边界的 notes → 独立读回 master 仍为 NOT_TOUCHED。只推指定 ref/tag；不调用 --all、--tags、force 或 twine。

## 全部 62 个 master 独有提交分类

下面由冻结的 SHA 范围生成，JSON sidecar 保留完整 SHA、parent、变更文件路径和处置。分类不把标题含 fix format 的提交自动当无行为变化。

<!-- GENERATED_COMMIT_TABLE -->
| SHA | 分类 | 提交标题 | 处置 |
|---|---|---|---|
| b418caf7 | 库行为修复 | Fix stale tick prices for stacked bars | stacked tick 已在 feed._fromstack(force=True) 和精确成交价回归保留。 |
| 8a71452b | 库行为修复 | Allow canceling submitted broker orders | Submitted/OCO 取消已在现代 BackBroker 和 sibling 回归保留；工具与策略测试保留现代路径。 |
| d35750e5 | 库行为修复 | Fix check_submitted margin rollback bug | margin 试算回滚已在现代 BackBroker 和超额单后可负担单回归保留。 |
| 39cb9531 | 库功能与工具 | Add TradeLogger observer port and branch compare script | TradeLogger 及 strategy/cerebro 转发已在现代版本增强；运行时事件测试存在。 |
| efab731a | 库修复与基线工具 | Fix strategy regression baselines and tooling | 基础 PyFolio 无 empyrical 顶层依赖；扩展报表本次补入。策略基线/工具使用现代 tests/functional、scripts 路径。 |
| c327dc46 | 测试数据 | add new data | 保留现代 tests/datas 中相应数据和回归；旧基线数据留历史可追溯。 |
| e05bbcff | 测试/回归演变 | fix tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| f121e176 | 分析工具 | 更新效率测试脚本 | 效率测量脚本/旧JSON：保留 scripts 下现代版本，历史结果不冒称当前性能证据。 |
| d6cfcd7c | 库兼容入口 | update macd | 本次补入 MACD.lines.me1/me2；4个新增真实运行模式用例及2个原指标用例通过。 |
| 21d06edf | 测试/回归演变 | test: add bar_num logging to MACD replay test | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 4694372b | 工具修复 | fix: use communicate() to capture all output | scripts/run_test_with_log.py 使用 Popen.communicate 完整收集输出；根目录旧副本不恢复。 |
| 6582fdc3 | 测试/回归演变 | update tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 39a5e90c | 测试/回归演变 | update tests/strategies/test_58_data_replay.py from origin | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 96d2a2f8 | 测试/回归演变 | update test from origin | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 2626b98f | 测试/回归演变 | update tests/strategies/test_58_data_replay.py from origin | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| c318bf4e | 测试/回归演变 | update tests/strategies/test_58_data_replay.py from master | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 9616bb48 | 测试/回归演变 | update tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 85bc1559 | 测试/回归演变 | update tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| a31f76db | 测试/回归演变 | update | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 2b69da08 | 测试/回归演变 | update | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 49bf2ca8 | 分析工具 | update profile_performance | 根目录 profile_performance 迭代由 scripts/profile_performance.py 的现代版本承接。 |
| 0466b704 | 测试/回归演变 | fix tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 5da3eb29 | 测试/回归演变 | update tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| ec3f9b3b | 测试/回归演变 | fix: restore test_02_multi_extend_data.py from performance-optimization branch | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 5399c89b | 测试/回归演变 | update tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| e44d5421 | 测试/回归演变 | update | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| c9ec1a74 | 测试/回归演变 | update | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| c6374c15 | 测试/回归演变 | update tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 6ec8abf5 | 测试/回归演变 | update test_multi_extend_data.py | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 5bee03b1 | 研究策略与数据 | update strategy for bonds | 旧可转债研究脚本/大CSV留历史；现代 special/misc 可转债回归路径保留，不恢复旧策略布局。 |
| e6130f05 | 研究策略与数据 | update strategy | 旧 strategies/0025 与 premium_rate 策略演变留历史；现代特殊策略回归及正确字段映射已保留。 |
| c520da60 | 分析工具 | update profile_performance | 根目录 profile_performance 演变保留历史，采用 scripts 中现代工具。 |
| a919abb4 | 分析工具 | update | 根目录 profile_performance 演变保留历史，采用 scripts 中现代工具。 |
| 4694a5fa | 分析工具 | update cal performance | 根目录 profile_performance 演变保留历史，采用 scripts 中现代工具。 |
| 29dcbbb0 | 测试/回归演变 | update | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 5ce743d7 | 测试工具与配置 | update test script | 旧 run_master_tests 与配置由 scripts 现代工具和现有 pytest/Makefile 接管，不恢复过期根路径。 |
| 12140fee | 文档整理 | delete some markdown files | 旧测试总结/说明删除，保留现代文档布局及历史记录。 |
| 13cbcf46 | 测试/回归演变 | update add_tests | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| 9fb8960b | 可选依赖修复 | fix: 修复statsmodels导入错误导致测试失败 | OLS 用 _get_statsmodels 惰性导入，保留无需可选包导入 backtrader 的意图。 |
| e8743889 | 观察器修复 | fix: 修复DataTrades observer数据源名称类型错误 | 现代固定 data0..data9 lines 不走旧动态 _derive(非字符串名称) 路径；保留现实现与观察器测试。 |
| d9e9c93c | 安装文档 | docs: 添加安装指南解决版本冲突问题 | 保留现代安装/版本说明，不恢复旧元类分支安装建议。 |
| 5d3b589f | 修复说明 | docs: 更新CHANGELOG记录ExtendPandasFeed修复 | ExtendPandasFeed 修复说明留历史；现代回归中 datetime=None 和字段0..8已保留。 |
| 69580a40 | 策略缺陷修复 | fix: 修复ExtendPandasFeed列索引错误导致stdstats报错的问题 | set_index 后字段映射修复已在 special/test_01_premium_rate_strategy.py 与 test_02_multi_extend_data.py 保留。 |
| 55400fff | 根目录整理 | chore: 清理项目根目录无用文件 | 清理旧安装/卸载脚本与页面：现代布局保持，不恢复旧文件。 |
| 4cf8c06b | 更新日志 | docs: 添加项目更新日志 | 历史变更记录由旧 master tag 保留；1.4.0 更新写当前 CHANGELOG。 |
| 0696eba6 | 导出与IDE提示 | fix: 为indicators模块添加显式__all__导出列表 | 不复制旧118项 __all__ 限制现代新增指标；保留当前常规/轻量导出策略，反射结构不宣称相同。 |
| 19f95edf | 项目文档 | docs: 优化CLAUDE.md和README.md文档内容 | 以当前 AGENTS/README 真实架构为准，旧说明留历史。 |
| f222ee35 | 格式混合真实功能 | fix format | AST审计169文件仅格式/文档、btrun帮助拼写；PyFolio五个报表入口确为新增且本次兼容补入。 |
| 68b8838a | 旧CI与页面 | update ci/cd 3 | 保持现代 workflows，旧 pages-simple/docs.disabled 不恢复。 |
| b8a4e208 | 旧CI与同步 | update ci/cd 2 | 旧 sync.yml 的 force/all/tags 发布不恢复；现代精确双远程流程代替。 |
| e19f5eb2 | UTC兼容和布局CI | update ci/cd | 现代 runnext/DTFaker UTC 已保留；删除旧 native/策略模块和危险发布工作流的状态保留。 |
| 040eae94 | README | update README.md. | 当前版本/安装/三分支说明为准，历史说明保留在rollback tag。 |
| e4625676 | 依赖配置 | update requirements.txt. | 采用现代 setup/requirements 的可验证兼容组合，不恢复历史整表。 |
| ed6eaeb2 | 历史合并 | Merge branch 'master' of https://gitee.com/yunjinqi/backtrader | 唯一双亲合并；remerge-diff 无额外冲突修复，父提交分别按表审计。 |
| cf934902 | 依赖配置 | update requirements.txt. | 采用现代 setup/requirements 的可验证兼容组合，不恢复历史整表。 |
| 1d847948 | 私有配置与旧测试产物 | fix | account_config.yaml 必须维持删除；未读取内容。旧crypto测试产物不纳入发布。 |
| 937617da | 安装工具与元数据 | add install_win.bat | 初审时发现 author=cloud；后续当前 setup.py 已保留 author=cloudQuant，此项已修正。旧 install_win.bat 不代替 Windows CI。 |
| a1922834 | 测试/回归演变 | fix test_ind_envelope | 采用现代迁移后的 tests/unit 或 tests/functional/strategies 同名用例与已更新基线；不复活旧导入/目录。此行不声明本轮运行通过。 |
| d6212ace | 文档与资金费率测试 | add new readme | 资金费率功能/回归保留现代路径，README以本次版本为准。 |
| d3a9e5a5 | README待办 | add todos | 历史计划留历史，当前AGENTS/README才定义真实能力。 |
| 764c0714 | 资金费率功能 | update crypto funding rate strategy | ComminfoFundingRate 已在现代版本保留及强化；fallback/数值回归存在。 |
| d4159c49 | Python2兼容及依赖 | update | 仅PY2分支items改动；当前支持3.8..3.13无需迁入旧分支，依赖用现代配置。 |

## CI 二次复核与 scanner 最终补强

二次复核时 requirements-ci-sdk.txt 固定四个公开源码 archive commit、bt_api_ctp==2.0.0 与 spdlog==2.0.6；专门 SDK job 先显式导入所有必需适配器和 spdlog，再跑完整非性能套件。核心3OS×3.8–3.13矩阵不安装可选SDK，optional_sdk helper只在 distribution 不存在时 skip，已安装但导入/接口/本地库损坏会失败。performance job 安装同一SDK清单并执行串行Makefile，Test Summary要求 test、sdk、performance、wheel-consumer 均 success；未发现新增确定的接线缺口。新增 pytest-cov/psutil/PyYAML 已在dev extras。

macOS支持经官方 actions/python-versions 版本清单复查：macos-latest 当前是macOS26 arm64；可用对应Python版本包括3.8.10、3.9.13、3.10.11、3.11.9、3.12.10和3.13.15。不能只检查每个minor最新patch而错误断言旧Python没有arm64版本；保留现有minor矩阵，最终支持证据仍以CI实际运行结果为准。SDK验收job当前只验证Ubuntu/Python3.11组合，不冒称SDK在全部核心矩阵平台通过。

父任务核验 Pages 环境只授权 development 分支，故将 docs 部署条件收窄到 development。主仓本次只提升 dev 到 development；master 保持 NOT_TOUCHED，不因 EN/ZH 构建、artifact、CI、tag 或 Release 产生变更。该处置不遗漏用户明确授权的 GitHub/Gitee Release 任务，也不需要扩大远程访问控制；Release notes 须明确 Pages 仍由 development 部署，不恢复旧 pages 旁路工作流。

scanner补强：scripts/scan_logging_baseline.py用统一logging_call_level识别logger已知级别、_safe_log首个literal级别、throttled_warning/error。当前源码不存在self._safe_log实现，故不把任意同名方法当作日志证据。目录名和文件名均排序，SyntaxError返回1，不发布部分catalog。新增tests/unit/scripts/test_scan_logging_baseline.py四例真实AST/CLI子进程验证：4 passed in 0.72s。未生成或覆盖任何历史M0 catalogs。

兼容联合17项测试之后，仅对两测试的同值dict comprehension作Ruff等价改写，库代码未再更改。scanner独立四例随后通过。最终发布全量结果由父任务绑定到正式commit。

## 归档后续处置说明

此归档副本修正 setup.py author 已保留 cloudQuant 的后续状态；原审计观察保留于 JSON 的 initial_disposition。源文件和修订副本 SHA-256 分别列于 artifact-manifest.json。不表示最终 wheel、`dev` → `development` 提升、远程发布或 `master` NOT_TOUCHED 读回已通过。
