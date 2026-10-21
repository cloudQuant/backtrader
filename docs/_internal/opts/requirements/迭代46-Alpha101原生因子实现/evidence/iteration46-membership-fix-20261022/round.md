# L3 当前公式池资格修复

仓库/分支：D:/source_code/backtrader / dev；父提交 `0349d8f315f78ba4345310eff18803d78c2fa9ab`。

完整场景复核发现 Alpha003 在当前公式池退出格输出 NaN 却标记 DOMAIN_ERROR；纯时序根线则可能仍有限。修复仅在 FactorStrategy 的采集分类层检查当前 formula_universe，在缺当前bar及输入可用性判断之后、因子自报状态/H/数学域判断之前返回 FORMULA_INELIGIBLE，并屏蔽公开值。评价 universe 保持独立；不扫描历史成员H、不改核心调度。

新增 6资产×48格双模式真实 Cerebro 用例验证 Alpha001即时恢复、Alpha003窗口恢复、Alpha009原生线有限但被正确屏蔽、因子自报READY不得绕过排除、缺bar/迟到输入原因优先、评价池独立、原生生命周期及零broker调用。与既有1条成员变更用例合并，统一解释器 C:/anaconda3/python.exe 实际3 passed，10.643秒，两条既有pytest配置/Quandl警告。命令：`python -m pytest -p no:asyncio -o filterwarnings=default tests/unit/test_alpha101_formula_membership.py tests/unit/test_factor_research_pit_bindings.py::test_formula_membership_changes_current_static_group_result_without_rewriting_history -q --junitxml=.codex-tmp/iteration46-membership-fix-r1.xml`。

Root审查生产diff及测试，并完成 scoped mypy；Black/Ruff/diff检查通过。此提交只接受该共享修复，完整场景和安装验收随后进行；不重复已通过101基础/复合矩阵。原场景失败XML留存，不能当作PASS。保留其他工作区改动，无账户操作、无推送。
