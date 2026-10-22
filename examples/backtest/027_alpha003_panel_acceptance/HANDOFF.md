> 历史记录：本文写于迭代46（2026-10-22 之前）。迭代45-46优化（v0.6）已删除
> `ResearchDataset`、`inputs.py`、`dataset.py`、`storage.py`、`field_validation.py`
> 及 PIT/classification/`table:` 绑定。文中引用的 `ResearchDataset._validate_named_tables`
> 等路径只用于追溯旧实现，不再是当前 API。当前入口见 `README.md` 与
> `docs/source/developer-guide/factor-research.md`。

# Alpha003 全市场日线运行交接

更新：2026-10-22；仓库 `cloudQuant/backtrader`，分支 `dev`。

这是按用户要求保存的可继续开发检查点。日线数据已验收；核心策略回归已通过；
真实全市场 Alpha003 只完成 **1/13 个日期分段**，全年验收尚未完成。

## 已保存的代码、数据与结果

| 项目 | 当前状态 |
| --- | --- |
| 逐股日线 | `tests/datas/a_stocks/`，5,471 个股票 CSV，1,309,654 行，243 个观测日期 |
| 日期范围 | 2025-01-02 至 2025-12-31，股票 CSV 总计 192,406,724 字节 |
| 数据验收 | 全部文件哈希、行数、顺序、日期及总量核对通过；9 组原始分钟独立抽查通过 |
| 日线数据提交 | `e2d4218893505de7ac1b451cc566c32c73a4377d` |
| 因子 feed 身份绑定修复 | `57980f5c538fb7eb99ad7ed1bb506e1eb763e4b5` |
| 本次代码 | `run.py`（真实数据快速入口，默认均匀抽样500只）、`run_daily.py`（全市场分块/续跑）、其测试、核心 Indicator 身份注册修复及回归测试 |
| 完整策略回归 | 1,286 passed，23 warnings，约 406 秒，无失败或跳过 |
| 定向检查 | 身份绑定/注册及研究契约等 12 passed；生产 Alpha003 runonce/runnext 参考核对 2 passed；日线入口 2 passed |
| 真实 Alpha003 | 第 0 段通过，第 1 段主动停止，第 2–12 段未运行；全年剩余 12 段未验收 |

本次提交的完整哈希可用 `git log -1 --format=%H -- examples/backtest/027_alpha003_panel_acceptance/HANDOFF.md` 查询。
验收摘要和原始运行状态副本保存在
[本轮证据目录](../../../docs/_internal/opts/requirements/迭代46-Alpha101原生因子实现/evidence/iteration46-real-daily-alpha003-20261022/)。
其中 `handoff-status.json` 记录检查点状态、源文件哈希与证据文件哈希；
`strategy-regression.xml` 保存完整策略回归的 JUnit 结果。
历史迭代46的合成/原生测试通过不表示 101 个因子都已通过本份真实数据验收。

原始分钟文件为 `ChinaStock1MinTradeInfo.1min.20250101_20260101.par`，
含 315,626,614 行，SHA-256 为
`a9df0336c2da13b395aeb7167f662a795b6df9b10127bec09ec96bf7f069d50c`。
该约 5.64 GB 原始文件未加入 Git；在新电脑运行已生成的日线不需要它。
数据验收详情见 `tests/datas/a_stocks/_metadata/aggregation_validation.json`。

## 新电脑运行

在仓库根目录使用 Python 3.11 环境。当前实际计算环境为 Python 3.11.5、
NumPy 1.26.4、Pandas 2.2.3；更换版本后需要重新建立运行结果。

```powershell
git checkout dev
git pull --ff-only origin dev
# 仓库其他历史归档使用 Git LFS，新克隆时也应安装并启用 Git LFS。
git lfs install
python -m pip install -e .
python -m pip install "numpy==1.26.4" "pandas==2.2.3" pyarrow
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
python examples/backtest/027_alpha003_panel_acceptance/run_daily.py --data-dir tests/datas/a_stocks --output-dir examples/backtest/027_alpha003_panel_acceptance/output/daily_a_stocks_2025_new_machine --chunk-days 20
```

日线已经在 Git 中，直接使用即可，不需要再次运行分钟聚合脚本。
`pyarrow` 同时用于日线入口的 Parquet 中间文件和结果导出。
入口使用生产库 `get_alpha(3)` 返回的 `Alpha003Native`，经 `FactorStrategy`、Cerebro 运行；
所有 5,471 只股票始终在同一个截面，只按日期分段，每段带入前 9 个观测日期预热。
不要分股票执行后再拼接，否则截面排名和因子值会改变。

完整运行将导出 `factor_values.csv`、`factor_values.parquet`、
`availability_reasons.csv`、`run_state.json` 和 `run_summary.json`。
输入校验、独立参考及分段校验都由入口执行。

输出目录被 Git 忽略，旧电脑的缓存和完整分段输出没有随本次提交迁移。
**新电脑使用全新的输出目录从第 0 段重新计算**；仓库中的证据副本不能代替可恢复的结果缓存。
入口复用结果时检查输入、代码、参数、运行版本和输出哈希，worker 配置还包含解析后的绝对路径。
修改代码、环境或目录后，不要手工修改旧状态或哈希以强行复用缓存。

## 真实运行进度与停止原因

本轮运行 ID：`01b6c36d682dbafb8ffc2a18efcdfbb7d8f433f12afb13a18f7b768531790b62`。
第 0 段覆盖 2025-01-02 至 2025-02-06，共 20 个日期、109,420 个日期/股票单元：

- 有限结果 58,552 个，有限值/NaN 掩码与独立参考一致。
- 最大绝对误差 `4.440892098500626e-16`，低于入口阈值 `5e-12`。
- 原因分布：READY 58,552；INCOMPLETE_WINDOW 47,927；NO_CURRENT_BAR 2,929；DOMAIN_ERROR 12。
- Broker submit/cancel 调用均为 0。

第 1 段已启动，但在用户要求提交并换电脑时主动停止未完成的 worker。
原始 `run_state.json` 和 `run_summary.json` 保持 `FAILED`，错误为
`chunk 0001 worker exited 4294967295`。这是本次主动停止产生的运行状态，
不是已观测到的数值核对失败，也不能改写为全年成功。
证据目录保留该状态和第 0 段 worker 的成功结果，`handoff-status.json` 另行解释停止原因。
没有生成或验收全年最终合并结果。

## 已修复问题与待优化项

两次早期全市场尝试分别在 feed 成员检查和 Indicator 注册阶段触发了重载 `__eq__`，
大量构造无用 `LinesOperation`。修复分别使用 feed 身份集合/索引、对象身份比较，
覆盖 `factor_indicator.py` 及核心 `indicator.py`、`lineiterator.py`、`lineseries.py`、`strategy.py`。
前两次失败记录仍保存在旧电脑被忽略的输出目录，未作为成功验收。

后续按以下顺序继续，不需要为本次提交重复已通过的测试：

1. 记录大股票池的分阶段耗时和峰值内存。一次实际采样位于
   `ResearchDataset._validate_named_tables` 的 `DataFrame.iterrows` 路径，
   这是待量化的性能候选，单次采样不能证明其耗时占比。
2. 检查注册列表的反复身份扫描。当前修复消除了重载相等运算的副作用，
   但逐个注册时仍可能是 O(N²) 扫描，不能声称全流程已线性化。
3. 评估数据集逐行校验/复制，以及每段重新建立 5,471 个 feed 的成本。
   比较更长日期分段的耗时和内存，必须保持整个股票截面与 9 日预热。
4. 多研究组的 `_FactorGroupInstances._merge_nodes` 仍有 `self.datas.index(data)`，
   当前单一全股票组不走该分支；后续单独修复并增加多组验收。
5. 优化后完成相应回归，再跑完全部 13 段、核验跨段边界并导出全年结果。

另有兼容性待办：`run_daily.py` 的路径包含检查使用 `Path.is_relative_to`，
Python 3.8 不支持此方法。本检查点仅按上述 Python 3.11 环境交接，
未声明该示例在 Python 3.8 可用；如需兼容，另做替换与测试。

全年验收要求：243 × 5,471 = **1,329,453** 个网格单元，无重复/漏格；
全部分段的有限值/NaN 掩码与独立参考一致，有限值误差不超过 `5e-12`；
分段预热不产生边界偏差；下单和撤单计数为 0；最终状态为 `COMPLETED`。
其他 100 个因子的真实数据运行、IC/组合绩效和交易回测仍属于后续工作。

若改动核心注册、时钟或最小周期路径，使用项目开发依赖并重新运行相应回归。
本次完整策略回归使用的命令为：

```powershell
python -m pytest tests/functional/strategies -n 8 -q -p no:asyncio -o filterwarnings=default --tb=short
```

`-p no:asyncio` 是本机已安装插件兼容性处理；23 条警告包括已有配置项、
Pandas FutureWarning 和资源/系统探测警告，没有用忽略失败的方式取得通过结果。

## 数据解释边界

价格按来源原样使用，本次聚合和计算未应用复权；不推断原来源的复权口径。
成交量单位保持 `SOURCE_NATIVE`，未验证股/手换算。
日期来自源文件观测，股票池是文件内所有股票，没有独立验证交易所日历或点时可交易股票池。
缺失股票日和不可计算窗口保留缺失值，不前填、不压缩 10 格相关窗口。
