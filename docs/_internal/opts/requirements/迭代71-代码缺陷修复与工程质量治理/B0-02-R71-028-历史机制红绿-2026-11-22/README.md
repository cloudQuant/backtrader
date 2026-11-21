# B0-02：R71-028 历史目标机制红绿

记录日期：2026-11-22。证据等级为公开历史源码、合成 DataFrame 与内存事件替身；不涉及 Bokeh 服务、网络、账户或生产环境。本次归档只复制和核对已有材料，没有重跑测试。

## 目标与实际结果

R71-028 的目标之一是避免 `LiveDataHandler._process` 在每条已有索引 UPDATE 时，以 `datastore["index"] == idx` 再逐行比较整列。既存批次 C 的性能计时是另一项证据；其历史测试中两项因旧版缺少新增辅助方法而失败，不能单独作为此目标机制的红测。

本次新测试使用两版共有的真实 `LiveDataHandler._process`，构造 96 行已有整数索引数据，分别处理 3、7、11 条已有索引更新。测试包裹 pandas `Series.__eq__`，记录名称为 `index`、与整数 bar id 比较的整列相等操作；推送方法使用内存替身记录事件，不启动或连接 Bokeh。目标断言之前先检查完整最终 DataFrame、事件顺序和 patch 数量。

| 历史版本 | 3 条更新 | 7 条更新 | 11 条更新 | pytest |
|---|---:|---:|---:|---|
| 修复前 | 3 次整列相等比较 | 7 次 | 11 次 | 3 failed，退出 1 |
| 修复后 | 0 次 | 0 次 | 0 次 | 3 passed，退出 0 |

两次各有一条既有 Quandl 弃用警告。该对照证明所测 UPDATE 路径不再发生**这类**逐行整列相等比较；不证明其他索引访问或扫描消失，不证明所有输入的复杂度、性能收益、并发安全或完整 Bokeh 服务能力。测试替换了 pandas 比较方法进行计数，覆盖限于该受控合成输入。

## 固定源码与环境

- 修复提交：`6e0cba79190290f3708d0db01865b811a7c1c0e8`；精确父提交：`276776852a09f639db49f489c1345590ac085c14`。两版分别从对应公开提交的 `backtrader/` 使用 `git archive` 导出至无 `.git` 的独立临时目录。
- 修前 `backtrader/bokeh/live/datahandler.py`：Git blob `5f8c7222d641a1695f0f855d9b9478ee9fd80ef5`；文件 SHA-256 `bf819b5ec2d28c740c0173a87f8840a515b6c37c8fecf0bad4697472bf329358`。
- 修后同文件：Git blob `1f3cbc3f2f442faa6ecea81e477e767cbf7591ea`；文件 SHA-256 `373e42fb68c752b3ca911809a025b6f2c09cdb625c8cb7962994eae691dbf5ae`。
- 新合成测试文件 SHA-256 `c7e599ed37206122439e8eb757858f539c752dd31d711274bb5dac53b67172ec`；测试实际断言导入的产品模块来自各自导出根。测试哈希在后续结果记录生成时核对，不声称首次旧版执行前另有独立测试哈希冻结。
- 环境：Windows、`C:/anaconda3/python.exe`、Python 3.11.5、pytest 8.4.2、pandas 2.2.3、NumPy 1.26.4；禁用 pytest 插件自动加载、conftest 与 cacheprovider，关闭字节码写入，`PYTHONPATH` 指向对应导出根。第三方依赖版本记录不等于其全部文件已按字节固定。

## 运行过程和限制

第一次 [run_r71_028_pair.py](run_r71_028_pair.py) 成功执行旧版测试并写出 [old.log](old.log)，控制台报告旧版退出码 1；随后在启动修复版测试之前，因运行器中修复版源码 SHA-256 转录少了一个字符而触发断言并中止。它没有生成原计划的 `result.json`。旧日志中的失败均发生在整列比较计数断言，非收集失败；先前的 DataFrame、事件和 patch 断言已经通过。

随后 [run_fixed_r2.py](run_fixed_r2.py) 使用正确的修复版源码哈希，只执行修复版测试，产生 [fixed.log](fixed.log) 和 [result_r2.json](result_r2.json)。该结果文件的 `old_exit_from_prior_console` 是引用前一运行的控制台结果，不是第二次执行旧版。原始运行器、日志、结果和测试均按原字节保留；没有重跑旧版或既有 QA。

## 归档文件

以下公开文件直接复制自 `D:/temp/i71-r71-028-redgreen-6e0cba79/`，已核对复制前后逐字节相同；大小为字节。隔离源码树和无关缓存未复制。

| 文件 | 大小（字节） | SHA-256 |
|---|---:|---|
| [test_r71_028_common_entry.py](test_r71_028_common_entry.py) | 2208 | `c7e599ed37206122439e8eb757858f539c752dd31d711274bb5dac53b67172ec` |
| [old.log](old.log) | 3380 | `a423e19fbbaab7a14d19bc0b416ede8981875038e7567fd7449845cabf3fcad7` |
| [fixed.log](fixed.log) | 1052 | `d368fd39cb777227f3956ea053bd427a55ac76ef3e8dce46c22d078c1088ec64` |
| [result_r2.json](result_r2.json) | 750 | `072346726e0e54dd60f69260f110c79dd4929e9c04b547aa21ca27fc32b70496` |
| [run_r71_028_pair.py](run_r71_028_pair.py) | 1851 | `d10d1fad68d0134ece1051807ca8c76f4c48eafa36e516425a72e929572ca947` |
| [run_fixed_r2.py](run_fixed_r2.py) | 1699 | `fbf303ac6ded718d0235190957b0e35012781ede759c0560f8306856e5c541cf` |
| [empty.ini](empty.ini) | 10 | `578fc1cd12d8d642df8eff41d71d5119626e9f88f21fafadba6b1092ac840a93` |

## 同测试复现

以下是重新测试的命令，不会重建已归档的原始日志。先选择不存在的临时根目录，并在 Backtrader 仓库目录执行；需本机已有上述 Git 对象、解释器与依赖版本。指定路径应改成新的隔离目录，不能覆盖源日志或本归档。

```powershell
$root = 'D:/temp/i71-r71-028-repro-new'
New-Item -ItemType Directory -Path $root -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path "$root/old","$root/fixed" -ErrorAction Stop | Out-Null
git archive --format=tar --output="$root/old.tar" 276776852a09f639db49f489c1345590ac085c14 backtrader
git archive --format=tar --output="$root/fixed.tar" 6e0cba79190290f3708d0db01865b811a7c1c0e8 backtrader
tar -xf "$root/old.tar" -C "$root/old"
tar -xf "$root/fixed.tar" -C "$root/fixed"
$evidence = 'D:/source_code/backtrader/docs/_internal/opts/requirements/迭代71-代码缺陷修复与工程质量治理/B0-02-R71-028-历史机制红绿-2026-11-22'
Copy-Item -LiteralPath "$evidence/test_r71_028_common_entry.py","$evidence/empty.ini" -Destination $root
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$env:PYTHONPATH = "$root/old"
Push-Location "$root/old"
C:/anaconda3/python.exe -B -m pytest -c "$root/empty.ini" --noconftest -p no:cacheprovider --rootdir "$root/old" -v --tb=short "$root/test_r71_028_common_entry.py"
Pop-Location
$env:PYTHONPATH = "$root/fixed"
Push-Location "$root/fixed"
C:/anaconda3/python.exe -B -m pytest -c "$root/empty.ini" --noconftest -p no:cacheprovider --rootdir "$root/fixed" -v --tb=short "$root/test_r71_028_common_entry.py"
Pop-Location
```

上述历史运行器的硬编码路径及独占创建日志行为均保留为来源记录，不应直接重用；复测前应确认目录全新并核验源码和测试哈希。本次归档未暂存或提交。
