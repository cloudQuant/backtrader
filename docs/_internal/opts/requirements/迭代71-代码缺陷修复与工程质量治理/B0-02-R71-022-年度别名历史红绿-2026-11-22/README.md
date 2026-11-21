# B0-02：R71-022 年度重采样历史红绿

日期：2026-11-22。结论为 **限定样本的目标行为红绿**：公开历史源码在真实 pandas 2.0.3 下，年度收益图由修前返回空图变为修后正常生成。本证据不完成 B0-02 全项，不证明所有 pandas 版本、完整报告、交易策略或账户行为。

## 目标与固定版本

原始 R71-022 P1 指向 pandas 2.2 前 `YE` 年末频率别名不可用、年度收益图被静默省略。既有历史表把非日频硬编码 252 的 22 项红绿列在该编号下，与本目标不同；本记录单独补证年度别名，不改写原表。

Backtrader 修前 Git 提交 `15e1cc5167cf6b94e87b04d755f3d21b5cfc5df3`，修后 `d94016dbffa1da1d8c5179b464d7f7010b91b88f`，前者是后者的实际父提交。两版分别用 `git -c core.autocrlf=false archive <commit> backtrader` 导出到无 `.git` 的普通临时目录。独立只读复核反馈：该时点两份导出的 `backtrader/` 各 694 文件，分别与固定 Git tree blob 原字节一致；本目录仅归档目标源码，不包含完整源码树。目标源码在试验前后 SHA-256 不变。

| 归档原字节 | SHA-256 | 作用 |
|---|---|---|
| [charts_old.py.txt](charts_old.py.txt) | `11cb897d5ff899be10e033df108444920a0fe8fbf2403f5b41f7bb84e1acec72` | 修前 `backtrader/reports/charts.py`，Git blob `9039ead6d9748fd7b4bdc623953023355e42a3ba` |
| [charts_fixed.py.txt](charts_fixed.py.txt) | `4c77b2250920691975fe967ad38065e2cc28601bacbcd21997a9c56abe2c3816` | 修后同路径，Git blob `c90f114251ace8b010c168146f3436ab85548dee` |
| [test_yearly_target_v2.py](test_yearly_target_v2.py) | `1133518dd04a6bd26913b89fa6a2f6671eccd80b06fd2bc490234f0bb47659ba` | 本轮新写、两版共用的 1,075 字节最小测试，并非历史提交测试 blob |
| [run_yearly_target_v3.py](run_yearly_target_v3.py) | `dc4217dd4ec072ab6152f1f04f6f51ea545954001e777229329508f435cd859a` | 3,595 字节执行与 guard 运行器，按自身目录寻找 `old/`、`fixed/` 和测试文件 |

测试提供 2018–2025 年末的 Python datetime 列表和每年增长 10% 的合成权益，分别调用显式 `yearly` 和跨越 5 年的 `auto`。它只将 `charts.logger.warning` 换为内存收集器以保留实际警告文本，**没有替换 pandas、重采样、图形或目标代码**。修后断言图非空、标题为 Yearly Returns、7 根柱各约 10%。

## 原始执行结果

执行时使用 `C:/anaconda3/envs/btcpp-py38/python.exe -I -S -B` 分别调用运行器并传入 `old` 和 `fixed`。实际版本为 CPython **3.8.20**、pandas **2.0.3**、matplotlib **3.7.5**、pytest **8.3.5**。修复提交的公开 `setup.py` 声明 Python >=3.8、pandas >=1.3.0 和 matplotlib >=3.3.0；本机依赖版本已观察，但第三方依赖文件**未逐字节固定**。

- 修前 Python 退出 1，**2 failed**；两种入口均返回 `None`，测试记录同次实际警告 `Failed to resample returns with period YE: Invalid frequency: YE`。
- 修后 Python 退出 0，**2 passed**；目标图标题、柱数和值断言通过。
- stdout 是运行时外层重定向得到的原始文件；两份 stderr 均为空。回执记录 pytest 退出码、实际模块路径和有限 guard 拦截，不能单独证明完整依赖或所有测试输出。

| 原始结果文件 | 字节 | SHA-256 |
|---|---:|---|
| [old_target_v3.stdout](old_target_v3.stdout) | 1306 | `69528ed24dfbbc948c23dadb57dfa6fed9307294ca54538b1f2e33ed276c7ef9` |
| [fixed_target_v3.stdout](fixed_target_v3.stdout) | 170 | `664480aa9c9e2731fb6fe18ddd9a971cc21fd076814202b41af3d3b6228e6d5d` |
| [old_target_v3.stderr](old_target_v3.stderr) | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| [fixed_target_v3.stderr](fixed_target_v3.stderr) | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| [receipt_target_v3_old.json](receipt_target_v3_old.json) | — | `22286931a4db31f346ca2d3b194e3e617aee91d513a96235eb35232bc34e5e2f` |
| [receipt_target_v3_fixed.json](receipt_target_v3_fixed.json) | — | `e401e16a933b41eaa2edd851365c8c2014ab9bda792eea38a48d0083d17776f9` |

## 首次观察、环境和边界

作者最初用修复提交自带的 yearly 参数测试作配对；当时观察为旧版先因 `DatetimeIndex` 真值歧义失败、新版通过。该轮没有留存可独立恢复该失败原因的 stdout；旧回执只记录状态及 guard 类别，因此**这段仅是作者当时观察，不计入本次目标红测**。为进入目标重采样路径，后续两版共用上面的 Python 日期列表测试；留存结果为之后使用相同测试、记录 stdout/stderr 的 V3 运行。

runner 禁用外部 pytest 插件、conftest 和 cacheprovider，Matplotlib 使用 Agg 与临时根内分版本缓存；清理环境后显式加入目标快照和所选解释器的 site-packages。runner 将 `socket.gethostname` 替换为固定合成主机名；此替换属于运行器，测试本身只替换 warning 收集器。私密路径读取自检被拒后清除自检计数；每个目标进程另有 **1 次目录枚举被 guard 拒绝并由调用方捕获**，有限栈指向 importlib 查找，未记录目标路径，不推断其内容。不能称零拦截。外层启动 Python 是测试执行动作；Python 审计 guard 限制网络、进程和文件访问，但不是覆盖全操作系统或全主机活动的沙箱。

只对真实 pandas 2.0.3 的这两个合成输入获得红绿；未验证 pandas 1.3–1.5、2.1、3.x、混合时区或完整报告。要重新执行，应在**新的独立临时根**按上述 Git 对象重建 `old/backtrader` 和 `fixed/backtrader`，复制归档测试与运行器并绑定相同版本的依赖后再运行；直接在本冻结目录运行会缺少完整源码且可能覆盖证据。归档时没有重跑测试，没有修改既有文件、产品源码或 Git 索引。
