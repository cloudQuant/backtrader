# 全市场 Alpha003：原生 feed 身份绑定修复

日期：2026-10-22。仓库：`D:/source_code/backtrader`，分支：`dev`。
本轮起点：`e2d4218893505de7ac1b451cc566c32c73a4377d`，即已验收的全量日线数据提交。

## 实际发现

用户要求使用 5,471 只股票的 2025 全年日线运行生产版 Alpha003。
第一次实际运行在首个20日分段进入 Cerebro 后持续使用单核 CPU，但尚未完成因子构造。
Root 用独立安装在临时目录的 py-spy 对自己启动的 worker 只读采样，观察到调用栈：

```text
FactorStrategy.__init__
FactorIndicator._bind_for_research (原第230行)
  any(data not in datas for data in targets)
LineRoot.__eq__ -> _operation_stage1 -> _makeoperation
LinesOperation.__init__ -> LineActions.__init__
```

该检查应判断输入对象身份。序列成员检查却调用了 Backtrader 重载的 `__eq__`，
为大量资产配对创建了无用运算，最坏复杂度为 O(N²)。这不是行情或公式问题。

Root 确认 worker PID 12692 属于本轮父进程 42736 后停止它；父进程以失败退出。
没有任何分段结果通过验收。原输入缓存、状态和失败摘要保留在忽略目录
`examples/backtest/027_alpha003_panel_acceptance/output/daily_a_stocks_2025_membership_failure/`。
原始分钟文件、已提交的逐股日线以及其他进程未修改。

## 修复范围与验收

- `FactorIndicator._bind_for_research` 使用输入 feed 的 `id` 集合进行身份检查，整体 O(N)。
- 同一公开类的 `field(alias, data)` 改为初始化一次的身份索引，避免调用重载相等运算。
- 公式、数值算法、时间网格和 Indicator 生命周期不变。
- 新增真实 PandasData 子类的相等运算陷阱测试：正常绑定不调用 `__eq__`；
  即使外部 feed 的相等运算返回 True，也必须拒绝其作为目标或字段访问对象。

定向测试：新测试与既有 `test_factor_research_contracts.py` 共 **4 passed**。
使用 `-p no:asyncio -o filterwarnings=default`，存在一条已有 pytest 配置警告。
Black（py311）、Ruff、diff 空白检查通过。

本提交只接受该绑定修复及定向本地测试。全年真实数据结果由后续实际运行另行验收，
不能用这4项测试代替全年运行成功。已提交日线的全部文件校验及9组独立分钟样本核对不重复执行。

另一个相似的 `.index(data)` 位于多研究组适配器 `_FactorGroupInstances._merge_nodes`；
当前单一全股票组不使用它，本轮未修改，保留为后续多组性能检查项。
