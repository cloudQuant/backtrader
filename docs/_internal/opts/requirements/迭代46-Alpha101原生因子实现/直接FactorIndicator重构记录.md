# Alpha101 直接继承 FactorIndicator 的结构重构

日期：2026-10-22。仓库：Backtrader；分支：`dev`。原始 HEAD：`b353bb27`。
本轮按用户要求重构生产实现，不增加公式语言或独立计算引擎。

## 结构

- `backtrader/research/alpha101/alpha001.py` 至 `alpha101.py` 各自定义一个具体公式类，全部直接继承 `FactorIndicator`。
- 各类在普通 `__init__` 中调用 `super().__init__()`、创建原生子指标并设置预热，在自己的 `next` 中写入输出线；子指标始终由 Cerebro 推进。
- `_helpers.py` 只复用逐资产/截面子指标的创建和中间节点引用。节点引用用于独立中间值、PIT 时钟和缺失原因探针。
- `_metadata.py` 检查每个公式的 ID、原式、字段、窗口和 profile，并保留原有不可变公式/实现身份；它不执行公式。
- `get_alpha()`、`list_alphas()`、根包的 101 个类导出及只读注册表继续使用。

删除 `NativeAlphaBase`、`_make_formula` 虚方法，以及旧 `_base.py`、`batch_a.py` 至 `batch_e.py`、`promoted.py` 模块。生产代码不再从诊断实现继承公式。

20 个历史诊断类移至 `tests/test_utils/alpha101_diagnostic_factors.py`，只调整其导入路径。论文目录逐字节移至 `tests/fixtures/research/alpha101_dependencies.json`。两项均退出安装包，独立参考和中间值回归继续使用它们。

`factor_indicator.py`、`factor_strategy.py` 和数值算子的实现本轮没有改动。保留的配置、输入对齐、严格计算检查、数据集、保存和 fincore 适配模块具有实际调用者；具体职责见[原生因子指南](../../../../source/developer-guide/alpha101-native.md#实现结构与模块职责)。

## 验收证据

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 全 101 类直接继承、各自 `__init__`/`next`、迁移前后计算语句及身份元数据 | PASS，101/101 | [逐式比对](evidence/iteration46-direct-factor-refactor-20261022/formula-preservation.json) |
| 原生数值、双运行模式、窗口、缺失/PIT、推进次数与边界回归 | PASS，298 个唯一测试 ID | [覆盖核对](evidence/iteration46-direct-factor-refactor-20261022/source-coverage.json)、[首批原始记录](evidence/iteration46-direct-factor-refactor-20261022/source-native-initial.xml)及[余项原始记录](evidence/iteration46-direct-factor-refactor-20261022/source-native-remainder.xml) |
| 目录路径与等价分支调整后复核 | PASS，3 tests | [目录回归](evidence/iteration46-direct-factor-refactor-20261022/catalog-followup.xml) |
| 隔离 wheel 的全部 101 类导入来源、研究源码 payload、旧模块退出安装包 | PASS | [wheel 记录](evidence/iteration46-direct-factor-refactor-20261022/wheel-smoke.json) |
| 隔离安装的 Alpha003/Alpha009 原生数值与生命周期 | PASS，3 tests | [安装回归](evidence/iteration46-direct-factor-refactor-20261022/installed-l0.xml) |
| 原生包 Black、改动源码/测试 Ruff、暂存差异空白检查 | PASS | [静态检查](evidence/iteration46-direct-factor-refactor-20261022/static-checks.json) |

解释器为用户 Anaconda base 的 Python 3.11.8。源码回归命令：

```bash
env -u BT_ALPHA101_NATIVE_BATCHES -u BT_ALPHA101_NATIVE_IDS -u BACKTRADER_USE_INSTALLED \
  /Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest -n 4 \
  tests/unit/test_alpha101*.py tests/unit/test_factor_research_representatives.py \
  tests/integration/test_alpha101_native_matrix.py \
  tests/integration/test_alpha101_native_boundaries.py \
  tests/integration/test_alpha101_native_data_contracts.py -q --tb=short \
  --junitxml=docs/_internal/opts/requirements/迭代46-Alpha101原生因子实现/evidence/iteration46-direct-factor-refactor-20261022/source-native.xml
```

首次执行已通过 292 项后，为重新分配集中在单 worker 的长耗时用例主动中断，退出码为 2；该执行保留为 `source-native-initial.xml`，不作为单次全量 PASS。重新收集得到的 298 个测试 ID 固定在 `source-coverage-plan.json`，仅余下 6 个边界用例使用 `-n 6 --dist=worksteal` 运行，6 passed、退出码 0、554.52 秒。[覆盖核对脚本](evidence/iteration46-direct-factor-refactor-20261022/check_coverage.py)已核对原始收集输出、两份 JUnit 和余项实际进程退出记录：298 个唯一 ID 全部通过，0 failure/error/skip，没有漏项或重复计数；首次中断产生的一个匿名空记录明确排除。

安装检查从只暂存本轮改动的 Git tree `bc17aad0f9d9828485021ea9c292a5f3b16aa20d` 导出干净源码，未把工作区其他改动混入 wheel。可使用[检查脚本](evidence/iteration46-direct-factor-refactor-20261022/wheel_smoke.py)重新导出、构建、安装并验证；构建和安装均不解析网络依赖，隔离消费者使用由 Anaconda Python 创建的 venv。

以上为源码合成输入/独立参考回归和安装包检查。全量 installed fincore 评价矩阵及 A 股全市场重跑均为 `NOT_RUN`；历史迭代46安装验收仍对应原记录中的源码提交，不自动转作本轮证据。
