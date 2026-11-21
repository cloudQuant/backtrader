# R71-159 FindIndex R2 完整 Cerebro 基准证据

记录日期：2026-11-22。证据等级为本机真实 Cerebro 与公开合成数据；不代表账户、其他运行模式或全部负载的性能。

## 结论

**R2 保持 HOLD。** 根代理在最后 gate 测量前确定：30,000 根、四个指标，周期 128 和 512 的候选中位耗时相对基线均须至少改善 2%。比较的是候选耗时中位数 ÷ 基线耗时中位数，两者都应不大于 0.98。最终周期 128 的比值为 0.97248733；周期 512 为 **0.98495246**，仅改善约 **1.50%**，未达到预定门槛。不能声称普遍性能收益。

四份 JSON 中所有样本的合成输入、各指标完整输出数组和完整输出聚合哈希，基线与候选均一致；各结果内部采样前后快照 pin 一致。本次仅只读核对结果，未重跑基准。哈希一致仅证明所测数据及输出字节一致。

## 完整 Cerebro 采样

计时覆盖 `Cerebro.run()`，不包括构造合成 DataFrame 和引擎对象。样本按对交替基线和候选顺序。表中比值为**各组耗时中位数之比**，不是逐对比值的中位数。

| 结果 | 根数 | 指标数 | 周期 | 配对 | 基线中位秒 | 候选中位秒 | 候选/基线 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 3.11 初测 | 12000 | 2 | 128 | 3 | 0.30377520 | 0.30544860 | 1.00550868 |
| 3.11 初测 | 12000 | 4 | 128 | 3 | 0.36824190 | 0.35599470 | 0.96674143 |
| 3.11 初测 | 12000 | 2 | 512 | 3 | 0.30638750 | 0.30596470 | 0.99862005 |
| 3.11 初测 | 12000 | 4 | 512 | 3 | 0.38550090 | 0.35801530 | 0.92870159 |
| 3.11 扩展 | 30000 | 4 | 128 | 5 | 0.92681320 | 0.90093020 | 0.97207312 |
| 3.11 扩展 | 30000 | 4 | 512 | 5 | 0.92554370 | 0.88729720 | 0.95867672 |
| 3.14 扩展 | 30000 | 4 | 128 | 3 | 0.70652700 | 0.68175440 | 0.96493750 |
| 3.14 扩展 | 30000 | 4 | 512 | 3 | 0.70454620 | 0.68389580 | 0.97068979 |
| 3.11 最终 gate | 30000 | 4 | 128 | 4 | 0.91520730 | 0.89002750 | 0.97248733 |
| 3.11 最终 gate | 30000 | 4 | 512 | 4 | 0.88809205 | 0.87472845 | 0.98495246 |

12,000 根初测有候选更慢的配对：周期 512 的两指标一对比值 1.09318620、四指标一对比值 1.05725875；周期 128 的两指标中位数比也超过 1。3.14 每个场景仅三对。机器非独占，其他负载可能影响计时；不能将样本推广至所有数据、机器或模式。

## 版本与绑定

- 公开基线提交 `535eaa80e9aa5b4a8002855f4f3b61da8e585e28`；四指标依次为 FindFirstIndexHighest、FindFirstIndexLowest、FindLastIndexHighest、FindLastIndexLowest。
- 基线快照 `D:/temp/i71-index-baseline-535eaa80` 的 `backtrader/indicators/basicops.py` SHA-256：`cc06e9ddbc4d11fbac2dfd92e56ad22b702b9904d9d3028cbb9161e1fb3d568a`；R2 快照 `D:/temp/i71-index-inline-r2-535eaa80` 对应源码：`66e7f24598945a2e3cfeeec5362391143c3fcadaed4d0ac08d6c3469fb31ee7b`。
- 两快照除该源码外的 696 个包文件合并 SHA-256 均为 `e9cea07e7387150f6d71e0d2d689d8e8ffc8c247fe392f154fb5206ce71e1d5e`；原结果记录采样前后 pin。
- Python 3.11：3.11.5（Anaconda）、NumPy 1.26.4、pandas 2.2.3；Python 3.14：3.14.2、NumPy 2.4.1、pandas 2.3.3。Backtrader 均为 1.4.0。结果分别报告平台字符串 `Windows-10-10.0.26300-SP0` 与 `Windows-11-10.0.26300-SP0`，该字符串本身不能证明机器是否不同。
- 原 JSON 记录解释器及 NumPy/pandas 入口文件路径和哈希；入口文件哈希不等于整个解释器及依赖的完整字节 pin。

## 原字节文件

以下文件逐字节复制自 `D:/temp/i71-findindex-cerebro-bench-535eaa80/`，已核对复制前后哈希与内容；大小单位为字节。

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| [benchmark_findindex_cerebro.py](benchmark_findindex_cerebro.py) | 13145 | `c349be27e8fba5a3d3f57f9366015c51506b5e06e109edf8a741f4f444001560` |
| [result_311_root_20261122.json](result_311_root_20261122.json) | 60983 | `d1e9b062f244bd2f938069bd1f3a1f461ddb85533d10be555cee91186a0c6c98` |
| [result_311_root_30k_20261122.json](result_311_root_30k_20261122.json) | 53944 | `19da59879c2d4a3d1163ce9de2c77be083c1fb803a782af464c2a578a883232b` |
| [result_314_root_30k_20261122.json](result_314_root_30k_20261122.json) | 35044 | `abca8271c68af2321cf17c079ffd58e5325b12cee7150947f90ca4cca4a04ae9` |
| [result_311_gate_long_20261122.json](result_311_gate_long_20261122.json) | 44149 | `33f06ffb3ce71af353a2bbe4a9f36a456045bc88df6283d3f5decfe1a4f150fb` |

## 复现命令

命令将产生**新的**测量，不能重现历史耗时。脚本硬编码上述两个隔离快照及版本 pin；本目录不包含完整快照，快照被移动或修改、版本不符时脚本会拒绝运行。指定不存在的输出文件，脚本不会覆盖原始结果：

```powershell
$script = 'D:/source_code/backtrader/docs/_internal/opts/requirements/迭代71-代码缺陷修复与工程质量治理/R71-159-FindIndex-R2-Cerebro基准-2026-11-22/benchmark_findindex_cerebro.py'
C:/anaconda3/python.exe $script --output D:/temp/i71-findindex-cerebro-bench-535eaa80/repro_311_12k_new.json --bars 12000 --periods 128 512 --counts 2 4 --pairs 3 --seed 710159
C:/anaconda3/python.exe $script --output D:/temp/i71-findindex-cerebro-bench-535eaa80/repro_311_30k_new.json --bars 30000 --periods 128 512 --counts 4 --pairs 5 --seed 710159
C:/Python314/python.exe $script --output D:/temp/i71-findindex-cerebro-bench-535eaa80/repro_314_30k_new.json --bars 30000 --periods 128 512 --counts 4 --pairs 3 --seed 710159
C:/anaconda3/python.exe $script --output D:/temp/i71-findindex-cerebro-bench-535eaa80/repro_311_gate_new.json --bars 30000 --periods 128 512 --counts 4 --pairs 4 --seed 710159
```

再次执行需更换为新的结果路径。本次归档未修改 Git 索引。
