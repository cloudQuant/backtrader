# 默认借用补完

静态复核发现 FactorPanel 构造仍对已经规范化的 factors/grid/价格/universe 做全量复制，与 v0.6 §3.1 默认借用约定不一致。本轮修复后，float64、bool 和 UTC open_time 缓冲可复用；规范化只创建独立帧壳、索引/列对象及 attrs，必要类型转换保留。study_factors 直接返回已限定研究区间的 factors。调用者仍不得在评价/报告期间并发修改借用值。

主线程检查实现及测试 diff，并运行：

```text
/Users/yunjinqi/opt/anaconda3/bin/conda run --no-capture-output -n base python -m pytest tests/unit/test_factor_*.py tests/unit/test_alpha101_*.py tests/unit/test_alpha003_daily_runner.py tests/integration/test_alpha101_native_boundaries.py -q
```

574 passed / 59.72s。随后补充旧 pandas 缺少 Copy-on-Write 配置项的回退及显式嵌套 attrs 隔离，再独立运行 panel/CSV/sink/fincore adapter/report 五个文件：58 passed / 4.75s。最终日志见 panel-borrowing-focused-final.txt；广泛回归见 panel-borrowing-regression.txt。测试实证规范缓冲 shares_memory、metadata 不变、混合 dtype 必要转换、CSV 往返和消费不变性；使用 pandas 3.0.3，兼容分支模拟旧行为，不冒称已运行真实 pandas 1/2。

ResearchSpec 保持其公开防御性 grid 复制合同；Sink 仍是按点数值 tuple 缓冲，未保存每因子单元字典，close 释放缓冲。v0.6 §2.5 明确列式布局由新开销决定，这两项以阶段/RSS 诊断记录，不更改成未经验证的全局缓存或第二套推进器。

BT 045a739d 另修正算子/027 的过期 v1/PIT 文案；主线程 AST 对照证明除 docstring 和三条诊断字符串外行为相同。

最终 report-only 500 只第一轮在预热阶段主动停止（report-only-500-aborted.json），不纳入正式性能。后续端到端、采集与 RSS 均绑定本次借用修复后的干净提交重新执行。
