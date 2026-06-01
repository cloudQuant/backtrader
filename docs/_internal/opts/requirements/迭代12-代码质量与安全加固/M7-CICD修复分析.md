# 迭代12 · M7 CI/CD 失败修复分析与现状

> 创建：2026-06-01
> 适用分支：`dev`
> 触发：用户报告 CI 红灯，要求从历史失败信息中诊断并修复
> 诊断方式：`gh run view` 拉取失败日志 + 本地多 Python 版本（3.11/3.12/3.13）×
> numpy(1.x/2.x) 隔离 venv 复现

---

## 1. 失败分类（基于 run 26727816157 原始失败 + 26732118071/26734770684 复现）

| 类别 | 表现 | 根因 | 状态 |
|------|------|------|------|
| A. 可选依赖缺失 | 8 个 collection ERROR + 1 个 FAILED | sklearn/hmmlearn/bt_api_py 未装却在模块顶层硬导入 | ✅ 已修（importorskip 守卫，缺失即 skip） |
| B. SVD 符号不确定性 | `test_0061` buy 209↔210 跨 py 版本漂移 | `np.linalg.svd` 奇异向量符号随平台/BLAS 翻转 | ✅ 已修（确定性符号约定，py3.11/3.12/3.13×numpy1/2 一致，重标定断言） |
| C. py3.13 无 numpy 1.x wheel | win/py3.13 `import backtrader` 段错误(exit 139) | numpy<2 在 3.13 源码构建崩溃 | ✅ 已修（条件 pin：<3.13 用 numpy<2，>=3.13 用 numpy>=2.1） |
| D. exact-count 回归基线仅适配 Python 3.11 | 大量策略测试在 3.8/3.9/3.10/3.12/3.13 与 macos/windows 上计数漂移（±1 到 614vs217） | pandas 2.x/3.x 布尔 downcast、前导 None 比较、Series 共享底层数据、排序 tie-break 等行为差异 | ✅ 已修复代表漂移；CI 全矩阵保持 blocking |

---

## 2. 本迭代实际成效（对比原始失败 run 26727816157）

| 作业 | 原始失败 | 修复后（run 26734770684） |
|------|----------|---------------------------|
| ubuntu 3.11 | 失败 | ✅ **3035 passed, 0 failed** |
| ubuntu 3.12 | 多失败+8 error | 2 failed（D 类）, 0 error |
| ubuntu 3.13 | 多失败+8 error | 2 failed（D 类）, 0 error |
| ubuntu 3.10 | 多失败 | 4 failed（D 类） |
| ubuntu 3.9 | 6 failed+14 error | 5 failed+8 error（error 为 venv 缺 yaml，CI 装 .[dev] 不受影响） |
| ubuntu 3.8 | 更多 | 26 failed（D 类，跨多策略族） |
| macos 3.11 | 失败 | ✅ passed |
| macos 3.12 | 失败 | ✅ passed |

> A/B/C 类已根治：collection error 清零、test_0061 与 test_btapistore 通过、
> 段错误消除。ubuntu/macos 的 Python 3.11/3.12 已转绿。

---

## 3. D 类（exact-count 跨平台漂移）——保持全矩阵 blocking 的修复策略

### 3.1 本质

策略回归测试（`tests/functional/strategies/**`）大量使用形如
`assert strat.buy_count == 440` 的**精确计数断言**，这些黄金值是在
**Python 3.11 + numpy 1.x**（开发者本地环境）下标定的。CI 矩阵覆盖
5 个 Python 版本 × 3 个 OS = 15 个组合，而黄金值仅在 3.11 组合成立。

漂移来源（非单一）：
- 浮点归约/排序在不同 Python/BLAS 下的边界差异（±1~±2，如 442vs440、124vs123）；
- macos 上更大幅度差异（614vs217、23vs0），疑似数据加载/日期解析的平台差异；
- 受影响测试横跨 momentum / asset_allocation / calendar_effects /
  commodity_currency / rotation / trend_following 等多个策略族。

### 3.2 为何本迭代不逐个"修"

1. **无法每平台一套黄金值**：精确断言不能同时等于 440 和 442。
2. **逐个确定性化成本极高且高风险**：SVD（B 类）只是其中一例；要让每个策略的
   计数在所有平台 bit 级一致，需排查排序 tie-break、归约顺序、日期解析等，
   工作量是多个迭代级别，且要改动策略/数据处理逻辑，风险大。
3. **不允许弱化断言**：把精确计数改成区间属于"为通过而放宽"，违反迭代硬约束。
4. **该矩阵长期红灯**：`test.yml` 历史上每次运行都失败，D 类是长期既有状态，
   非本次引入。

### 3.3 已落地的 CI 门禁策略

用户进一步明确要求"不删减检查"并确保 CI/CD 通过，因此撤回"信息矩阵"方案，保持
所有 Python/OS 组合为 blocking：

- **阻塞门禁**：`.github/workflows/test.yml` 的完整 Python/OS matrix 均保持 blocking。
- **不采用**：不使用 `continue-on-error` 把失败矩阵降为信息性看板。
- **不采用**：不跳过失败测试、不删除检查、不把 exact-count 断言改为宽区间。
- **采用**：针对 pandas/Python/OS 造成的确定性差异做显式语义修复。

本次修复后，历史失败代表子集已在 pandas 2.3、pandas 3.0、Python 3.13/numpy 2.x
组合下通过；最终仍以 GitHub Actions 全矩阵为准。

### 3.4 受 D 类影响的已知测试（非穷尽）

`test_0048_long_short_equity`、`test_0002_safe_haven_rotation`、
`test_0020_0407_turn_of_month`、`test_0018_zweig_breadth_thrust`、
`test_0266_1080_bnb`，以及 3.8 上额外的 momentum/asset_allocation/
calendar_effects/commodity_currency 多个测试与 `test_bokeh_module`。

---

## 4. 结论

- A/B/C 类已修复并通过验证；CI 在**已验证环境（Ubuntu/Python 3.11）已全绿**。
- D 类不再通过降级门禁处理；本次保持全矩阵 blocking，并对代表性 pandas/Python
  确定性差异做显式修复。
- 后续若 GitHub Actions 全矩阵仍暴露新的 exact-count 漂移，应继续按"定位语义差异
  并修复确定性"处理，而不是跳过测试或弱化断言。

## 5. 补充修复（Codex，2026-06-01）

用户要求继续查看并尝试修复其它 Python/OS 矩阵失败后，复查 run `26734770684`
失败日志，新增以下处置：

| 类别 | 失败表现 | 处置 |
|------|----------|------|
| pandas 旧版本频率别名 | Python 3.8 矩阵大量 `ValueError: Invalid frequency: ME` | 将测试和 `reports/charts.py` 中月末频率从字符串别名改为跨 pandas 2.x/3.x 均可用的 `pd.offsets.MonthEnd()` |
| Python 3.8/3.9 注解运行时求值 | HFT 测试 collection error：`list[...]` / `type | None` 在旧解释器报错 | `tests/test_utils/hft_scenarios.py` 增加 `from __future__ import annotations` |
| bokeh 包层级误判 | Python 3.8 bokeh 集成测试报 `attempted relative import beyond top-level package` | bokeh 子包中跨到 `backtrader.utils` 的导入改为绝对导入 |
| 排序 tie-break 不稳定 | `test_0048_long_short_equity_strategy` 与 `test_0002_safe_haven_rotation` 在部分 Python 版本出现 ±1/±2 exact-count 漂移 | 对分数排序增加显式资产顺序和 `mergesort` 稳定排序 |
| pandas 2.x 布尔 downcast | `0020` 出现 `614→217`，`0018` 出现 `89→87` | 显式保留 pandas 3.x object-boolean 语义，避免 pandas 2.x `fillna(False)` 自动 downcast |
| pandas 2.x 前导 None 比较 | `rotation 0002` 出现 `123→110` | 显式保留前导无资产选择日的 rebalance 事件，匹配迁移 golden |
| pandas 2.x Series 共享底层数据 | `0266 BnB` 出现 `23→0`，上下缓冲线完全相同 | `bulls`/`bears` 显式 `.copy()`，避免互相覆盖导致信号消失 |

未按平台改写 golden values，也未把断言放宽为区间。若 GitHub Actions 仍出现新的
exact-count 漂移，应继续优先排查 pandas 2.x/3.x 布尔/重采样/rolling 语义差异，
而不是为每个平台维护一套期望值。
