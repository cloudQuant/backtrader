# R7c：恢复普通输入边界测试（2026-10-22）

接手时 formula_membership、guide_examples 测试文件没有可收集的 test 入口，composite boundary 仅剩缺字段检查；因此撤回先前“边界矩阵均已通过”的笼统表述。

本轮以普通 feed 重新覆盖 Alpha009 正负/常量分支和真实缺 bar、Alpha029 手算截面秩、研究 universe 与公式计算隔离、Alpha100 行业缺码/中性化/scale、代表公式资产重排和未来尾段扰动、公开 API vwap/subindustry 输入。保留全101缺字段拒绝合同。清理两个未被调用且指向已删除 formula_universe API 的类属性。

主线程审查并独立执行三份测试：**108 passed in 3.75s**，见 boundary-regression.txt。该切片不替代全101长历史及全101重排/未来反事实；后续另记。
