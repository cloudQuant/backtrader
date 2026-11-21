# R71-159 FindIndex：当前队列与原逐窗方法对照

记录日期：2026-11-22。证据为公开合成行情、本机真实 Cerebro `runonce` 的限定样本；本次归档只核对并复制原记录，没有重跑。

## 结论

当前已提交的 FindIndex 队列路径在所测有限数据上快于优化前的原逐窗方法，完整指标输出数组哈希一致。30,000 根每个场景只有三对，100 万根只有一对；机器非独占，不能据此声称稳定收益或所有负载达标。**R71-159 全项未验收**：本结果只覆盖四个 FindIndex 指标，其他算子、下游场景、非有限数据和动态回调的全部合同不由这些样本证明。

## 对照方法

两边使用同一个当前公开源码快照 `c5fc2e7e954eae104d4acae5accdd9bf30e9c44d`、同一解释器及确定性合成 OHLC。基线子进程从优化前提交 `2bebe4e47900a4c5cd09bf74b08a4167c7950f04` 的公开源码中提取并编译原 `OperationN.once`，将其绑定到当前快照的 `OperationN`；该方法的全局变量仍解析到当前模块。当前子进程保留已提交的方法。除一次方法替换外，其余框架源码相同；这不是两套完整历史 checkout 的比较。

脚本在两边使用同一个队列调用计数包装，记录快路是否被调用。每个场景的旧方法调用计数为 0，当前方法为 8；每对样本的输入、四条完整输出数组和汇总输出字节 SHA-256 一致。计时范围为 `Cerebro.run()`，包括预加载和计算，不包括合成 DataFrame 及引擎构造。计数包装属于两边共同基准环境。

每个场景有四个指标：FindFirstIndexHighest、FindFirstIndexLowest、FindLastIndexHighest、FindLastIndexLowest。30,000 根样本每周期三对并交替顺序；100 万根只有一对。

| 根数 | 周期 | 配对数 | 原逐窗中位秒 | 当前队列中位秒 | 当前 / 原 |
|---:|---:|---:|---:|---:|---:|
| 30,000 | 50 | 3 | 1.32419480 | 1.04165940 | 0.78663607 |
| 30,000 | 128 | 3 | 1.58477480 | 0.99177910 | 0.62581706 |
| 30,000 | 512 | 3 | 3.15736210 | 1.08016400 | 0.34210964 |
| 1,000,000 | 50 | 1 | 48.81360030 | 36.46680390 | 0.74706237 |

表中比值是两组耗时中位数之比；单对的两组中位数即各自那次耗时。百万根合成输入 SHA-256 为 `1baa6de729f3253c4a2277e3558aeb0331b104700413b5e1e60aff71e919ae55`，四条完整输出聚合 SHA-256 为 `f964fc13f8fd5305096e81b78db46a81913c10230445b079761306d185e3e09e`；各条数组的独立哈希保存在原始 JSON。

当前 FindIndex 队列快路有适用条件：仅限所认定的四种内置指标、足够长的精确整数周期、标准独立双精度数组及动态绑定检查通过的情形；短周期、动态函数或参数等不符合条件时走原通用路径。若有效窗口左端出现 NaN，该批范围会保留通用路径与原回退行为。本次基准使用有限合成数据，不能证明缺失值、无穷、异常、并发修改或非标准存储上的完整等价性与性能。

## 版本和源码绑定

- 解释器 Python 3.11.5（Anaconda，64 位），NumPy 1.26.4，pandas 2.2.3；结果中的平台字符串为 `Windows-10-10.0.26300-SP0`。
- 当前公开源码隔离快照：`D:/temp/i71-index-original-window-c5fc2e7e`。其 697 个包文件的合并 SHA-256 为 `a727877846205c6b850ae812dbf7ecdfd4dcda3c7698992c3fc0079ecce9a7c2`；当前 `basicops.py` SHA-256 为 `c39958aef1b8d6e761ba1605e083d1acc51266ab5347e8b1b2a8a2f3261da058`。
- 从旧提交导出的 `basicops_original_2bebe4e47.py` SHA-256 为 `9382da9640e4229d8786afa9a522a8090a774eeab40424d1e25ce122c227fc32`。基准对比前后都核验快照和旧源码 pin。
- JSON 中保存完整样本、输入和输出哈希、计数、解释器路径及解释器文件哈希；版本和解释器文件哈希不等于所有依赖文件的完整绑定。

## 原字节归档

以下三个文件直接复制自 `D:/temp/i71-index-original-window-c5fc2e7e/`，复制前后已逐字节比较；大小单位为字节。

| 文件 | 大小 | SHA-256 |
|---|---:|---|
| [benchmark_original_vs_current.py](benchmark_original_vs_current.py) | 11866 | `066434be41cb9dfb8e10d0534a4f0218daea1bf72ef0cfaaaa1d9a6892fa1c9b` |
| [original_vs_current_30k_311.json](original_vs_current_30k_311.json) | 38875 | `18ca185dc22aeb231b116f4b8b43f7690351397563a988b445055648df831fd3` |
| [original_vs_current_1m_311.json](original_vs_current_1m_311.json) | 5998 | `dd8717faf3df91063bbf520c53beb4be628c5512aa1b7cdd1c28b034233ce391` |

## 同参数复现

本目录不包含完整当前隔离快照或旧源码文件。脚本硬编码原快照路径及哈希，原路径缺失或修改将拒绝运行；新测量的耗时也不能重建历史耗时。请使用不存在的新结果路径，脚本拒绝覆盖已有文件：

```powershell
$script = 'D:/source_code/backtrader/docs/_internal/opts/requirements/迭代71-代码缺陷修复与工程质量治理/R71-159-FindIndex-原逐窗对照-2026-11-22/benchmark_original_vs_current.py'
C:/anaconda3/python.exe $script --output D:/temp/i71-index-original-window-c5fc2e7e/repro_30k_new.json --bars 30000 --periods 50 128 512 --counts 4 --pairs 3 --seed 710159
C:/anaconda3/python.exe $script --output D:/temp/i71-index-original-window-c5fc2e7e/repro_1m_new.json --bars 1000000 --periods 50 --counts 4 --pairs 1 --seed 710159
```

再次执行需改用新的输出文件名；不应覆盖三份原始归档或源结果。本次归档未修改 Git 索引。
