# TODO / FIXME 跟踪清单

> 代码库中的待办项，供后续逐步清理或建立 GitHub Issue 跟踪。

## 数据来源

基于 2026-03 对 `backtrader/` 目录的扫描。

## 清单

| 文件 | 行号 | 类型 | 内容 |
|------|------|------|------|
| backtrader/analyzers/annualreturn.py | 79 | todo | This value is not used, commented out |
| backtrader/analyzers/annualreturn.py | 84 | todo | Directly setting in PyCharm will warn about setting attribute values outside __init__ |
| backtrader/analyzers/sharpe.py | 170 | TODO | change self.ratio to ratio |
| backtrader/analyzers/sharpe.py | 231 | TODO | self.ratio is not used here, just use ratio for assignment |
| backtrader/brokers/bbroker.py | 248 | TODO | Understand literally as transferring generated interest costs to pnl |
| backtrader/brokers/bbroker.py | 696 | TODO | This function is only declared here and not used anywhere else |
| backtrader/brokers/bbroker.py | 763 | TODO | Why is it necessary to reset pos_value_unlever every time |
| backtrader/brokers/bbroker.py | 770 | TODO | Commented out unused v |
| backtrader/brokers/bbroker.py | 954 | TODO | Commented out unused comminfo |
| backtrader/brokers/bbroker.py | 976 | TODO | Set additional pannotated attribute for order, purpose unknown |
| backtrader/brokers/bbroker.py | 1370 | TODO | Confirm required commission |
| backtrader/brokers/bbroker.py | 1426 | TODO | Commented out unused ago |
| backtrader/brokers/bbroker.py | 1505 | TODO | Commented out unused pmin |
| backtrader/cerebro.py | 1518 | TODO | Re-checking self._dopreload here seems unnecessary |
| backtrader/cerebro.py | 1937 | TODO | rs and rp are not used, commented out |
| backtrader/cerebro.py | 1954 | TODO | lastqcheck not used, commented out |
| backtrader/cerebro.py | 1960 | TODO | Modify while loop condition to avoid premature exit |
| backtrader/cerebro.py | 1973 | TODO | This check has no meaning |
| backtrader/cerebro.py | 1998 | TODO | Debug code, try printing |
| backtrader/cerebro.py | 2019 | TODO | dt0 < 1 is wrong, needs modification |
| backtrader/cerebro.py | 2053 | TODO | Code is redundant, rpi always returns False |
| backtrader/cerebro.py | 2056 | TODO | rpi is False here, consider removing |
| backtrader/cerebro.py | 2158 | TODO | Variable slen not used, commented out |
| backtrader/dataseries.py | 146 | TODO | Add public `name` (alias for _name) to avoid PyCharm warning |
| backtrader/dataseries.py | 325 | TODO | Uncommenting these lines causes an error; investigate |
| backtrader/feed.py | 308 | FIXME | These two are never used and could be removed |
| backtrader/feed.py | 1334 | FIXME | if removed from guest, remove here too |
| backtrader/feeds/rollover.py | 130 | todo | Using list again here seems not very useful |
| backtrader/feeds/vchartfile.py | 68 | FIXME | find reference to tick counter for format |
| backtrader/feeds/yahoo.py | 163 | todo | pay attention to logic |
| backtrader/feeds/yahoo.py | 205 | todo | Test this class when time permits |
| backtrader/functions.py | 224 | todo | A friend in the backtrader quantitative trading group pointed out this issue |
| backtrader/order.py | 631 | todo | need to understand better where dteos is used |
| backtrader/position.py | 126 | todo | Using 0 directly instead of self.size may improve efficiency |

## 说明

- **todo** / **TODO**：待办或可优化项
- **FIXME**：已知问题需修复
- 建议为高优先级项创建 GitHub Issue 跟踪
- 低优先级或文档类可保留注释供日后参考
