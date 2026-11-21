# StochasticHistogram 严格模式受限修复小轮

日期：2026-11-22。状态：**已提交，源码和公开隔离样本的限定复审通过**。本记录承接同目录已提交的有限 WIP 修复记录，但不改写旧记录，也不代表 B11-03 整项、全部指标场景或真实账户能力完成。

## 提交与范围

- Backtrader `dev` 提交 `4716bf95146bc8250a1b75a6d6f8e372f9e5de53`，实际父提交 `563e62c937b774a42735ed1c508a963e72597cbe`；父提交不是独立复审所用的公开快照 `c5fc2e7e954eae104d4acae5accdd9bf30e9c44d`。本提交包含指标源码和两份新增专项测试，共三个路径。
- 提交源码 `backtrader/indicators/contrib/stochastic_histogram_indicator.py` 的 blob 为 24,477 字节、SHA-256 `46781c9113cb5b7ab91ff915207f454087ca167a665c68411fbdf0fed5ea827c`；两份新增测试 blob SHA-256 分别为 `bb2134972c7f6034ac412d9cc0ae3d8742fc6e9acc31cf2f7de85406ec8caa4b` 和 `dcb4ee1180cc3d5f1f11ec596c5ce912b3208eff34c852293b06efadf8076681`。三份 blob 与冻结 V5 隔离候选原字节逐一相同。
- 公开临时补丁 `D:/temp/i71-stochhist-strict-v5/stochhist_strict_c5fc.patch` 的 SHA-256 为 `bc19dd8cd812b690eed0f8aaf3a969bac34eb341b9ef1f33f1357117d5b33256`。作者报告该补丁在新建的公开 `c5fc2e7e` archive 上通过 `git apply --whitespace=error`；临时补丁不属于本提交的永久归档。
- 活动 strict 作用域中，对符合限定条件的标准指标实例，batch 计算按逐根 legacy 路径执行，并在所测的极值、差值、乘法、除法及均线计算中检查中间无穷值。此举有意将该范围旧 once 数值改为所测 next 数值，不是保留旧 once 数值的优化。

## 独立复审

独立复审以固定公开 `c5fc2e7e` archive 和上述冻结源码，在 Python 3.11.5、pytest 8.4.2、`--noconftest`、禁用外部插件自动加载及 cacheprovider 的隔离环境运行新增两份测试：**29 passed，1 条既有 Quandl 弃用警告**。作者另报告其测试 29 passed、Ruff 通过；该作者结果与独立运行分别计数，不能相加成独立覆盖数。

真实 `FactorStrategy` 的公开合成有限行情中，`k_period=3`、`slowing=3`、`d_period=3`、EMA 的最小周期均为 11。旧公开快照首个有效 `main` 的 next/once 分别约为 80.9370360 / 72.3421646；候选在所测数据上两模式均约为 80.9370360。包含 high、low 和 close 不同位置 NaN 的样本，两模式的所测 NaN 位置及后续恢复一致。对有限输入 high=`1e308`、low=`-1e308`、close=`0`，中间运算溢出后两模式均抛 `FactorComputationError`，cause 为 `ArithmeticError`，不再在该样本静默输出 NaN。

普通参数的双 Feed 有限样本，指标仅消费自身 Feed，所测 next/once 首段一致。此前独立复审发现：标准指标子类覆写 `next`、或标准实例覆写 `next` 并读取第二 Feed 时，早期候选 once 会因第二 Feed 尚未定位而抛错，原快照 once 可完成；V5 对这两种覆写回退旧 batch，所测 once 恢复原快照行为。独立检查还覆盖普通非 strict 的 4 种均线、4 个 K 周期、3 组平滑参数与 `exactbars=0/1` 共 **96 组、0 组失败**；结果限于该有限样本。

独立隔离 runner 安装文件、网络和进程访问限制。私密路径读取自检按预期被拒；每个测试进程中有 3 次库的文件写探测被 guard 拒绝并由调用方捕获，不能称零拦截。pytest 采用 `-s`，不放宽文件 guard。保存的 JSON 回执记录退出码和拦截类别；测试项及样本结果来自执行输出，不能把回执本身当成对所有输入和结果的完整绑定证明。

## 适用条件与开放项

- 新 batch 路径限定为活动 strict scope、精确标准指标类、普通内建周期/均线/阈值参数和原有默认方法及参数 getter。子类、实例方法覆写、自定义参数或阈值，以及没有活动 scope 的附着 strict context，仍可能沿旧 batch 路径；不声称这些路径的 next/once parity 和 batch 中间溢出全部解决。
- 真实双 Feed 的自定义阈值回调读取另一 Feed 时，旧版和候选的 once 均可出现 `FactorComputationError`，cause 为 `IndexError`；这是保留的既有时钟缺口，不是本轮修复。不同步 Feed、复杂多 Feed 回调及 strict replay 未完成验收，不能根据普通双 Feed 样本外推。
- 该修复只针对所列源码和真实因子策略隔离样本。其他参数、异常恢复、所有非有限输入组合、性能、完整策略覆盖和交易账户行为仍须各自验证。
