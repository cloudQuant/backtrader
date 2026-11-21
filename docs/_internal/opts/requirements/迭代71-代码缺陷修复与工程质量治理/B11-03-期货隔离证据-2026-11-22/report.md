# 迭代 71：期货单元测试隔离核查

日期：2026-11-22。结论为限定源码测试证据，不构成 B11-03 完整验收。

## 固定输入

Backtrader 公开 Git 对象 f749673104e852784fb20e133933d0c3e20d9273；bt_api_py 对象 53d3ebe621ef048c7f4c47f9125740c7fa29b3ee；该 SDK 的 Base gitlink 和 Base checkout 均为 1bd1a13e36dbbf587acc63acdb5d8e0fdecaf6ca。现有工作树未作为源码输入。

三个公开 Git archive 的 SHA-256：

- bt.tar：9b9c841b13eed94304face009bd75d2c1153d4059998b128dcd365b31c1051d8
- sdk.tar：b0dff866ec630d116a733c7f54fe00f36e7304b3d4d7a96ac329f01e77901164
- base.tar：5d34178dc3bb360af7309b226072e91a83a0a12e2ddcc9b1ea479d33af4a271d

测试前后运行 verify_public.py，逐个核对 Git blob：Backtrader 704 文件，SDK 516 文件，Base 182 文件。Git archive 的 CRLF 文本分别有 702、509、182 个文件在将 CRLF 规范化为 LF 后匹配原 blob；其余原字节匹配。归档树 Git 条目无符号链接。verify_public.py SHA-256 为 6a32b5bc70c2bf567ef1d91b538ffdb51fb0a9aac4abcac3b2f8779042d582c5。

七个测试文件及其 Git archive 检出字节 SHA-256：

| 文件，均在 tests/unit/feeds/ 下 | SHA-256 |
| --- | --- |
| test_futures_sessions.py | 881d612290c9c3ea0f96d70f9f221ded3d881f0134096da852d89fb934239a47 |
| test_futures_selection_io.py | 318b74dd131d5933dda920944031d407c827c6f83daab432084d6ec0490a0f05 |
| test_futures_rollover_plan.py | c4169cf82f46e1d33b6bade7d04e0fa346b1875a92f63b139d7193053962e2dd |
| test_futures_main_contract.py | 623bb792fe6e61be0d28336c76fc3aec62bf26b30adc5de944e0032184c8fa72 |
| test_futures_expected_calendar.py | 9a5f4e6802552d5dd28478524b10903be1667e19b83c3cbfec9a42892d2ca2d5 |
| test_futures_calendar_evidence_roundtrip.py | 2d08b04c6fe956418de5c3b4dd40defbbb1a80041ebce8c684d49847e1df0073 |
| test_iter72_futures_type_and_export_fixes.py | 4d6b4f5373676c5dfa0db3048bbe0df6d5c00c31e125326c0606e85c6a9e7c73 |


## 执行与结果

Python 3.11.5，pytest 8.4.2，pluggy 1.5.0，iniconfig 1.1.1，packaging 26.3，requests 2.32.3，urllib3 1.26.20；第三方运行时来自本机安装，未进行 wheel 全量字节固定。测试解释器使用 -I -S -B。

guarded_run_r5.py SHA-256 0065ac7a04212e8985111f3923a75060ed2e95bd704c9056849e98680e323547。其直接运行结果由工具输出人工转录如下，并非原始 pytest stdout 文件：

- pytest 报告 36 passed、0 failed、0 skipped，1 个 warning，耗时 11.11 秒；warning 为测试文件中正则字符串的无效转义 DeprecationWarning。
- pytest 自身返回码为 0。运行器另记录到 1 次被捕获的 external_operation 拒绝，因此其最终逻辑设定进程退出码 2；PowerShell 工具报告的 shell 状态不能替代该 Python 退出码。
- 自检 6 项通过：受限路径读取、隔离目录外写入、socket 审计事件、子进程审计事件、native-load 审计事件和真实线程启动包装。网络与进程自检是人工发送审计事件；不能将其描述成真实联网或进程启动尝试。
- SDK 和 Base 的实际模块来源位于各自固定公开快照，七个 backtrader.futures 模块来源位于 Backtrader 快照。

同条件下的只收集诊断 R6/R7 均收集到 36 个节点，不运行测试。R7 记录拒绝事件 socket.__new__，调用栈为 urllib3.util.connection 导入期间的 _has_ipv6 本地能力探测；创建被守卫拒绝后被调用方捕获。guarded_collect_r7.py SHA-256 9794e75562784e9d21b902ce5975b1aee7cd4a75f7eb4a262638bb4f2f443ccd。R5 本身只记录了 external_operation 类别，未捕获事件名；R7 是独立复现，不能当作恢复了 R5 的同次调用栈。

早期 R1/R2 在 pytest 启动期被守卫拦截，未收集测试；R3/R4 各有 7 个收集错误、没有测试执行。R3 拒绝 SDK 导入时读取真实主机名；R4 拒绝 Backtrader 顶层导入 NumPy 时的 ctypes/kernel32 加载。这些是实际隔离运行障碍，未重写为通过。

## 环境边界与防护

运行器清空继承环境并设置限定值，将 gethostname 注入固定合成值；关闭 pytest 外部插件自动加载、cacheprovider 和 capture，日志写入隔离目录。它不加载仓库的 conftest：原本无操作的清理 fixture 被省略，proxy 环境在进程启动时清空；原根 conftest 的 Execution journal 端口安装与重置未执行。七个目标测试只声明 pytest 内置 fixture，但这种设置并不与原仓库 pytest 环境完全等价。

运行器通过指向固定公开 Backtrader 源码目录的合成父包壳加载真正的 backtrader.futures 模块；Backtrader 顶层 __init__.py 没有执行。故本轮不证明完整包默认导入、安装包行为或其余指标通过。SDK 和 Base 使用固定公开源码，实际主机标识、账户和服务均不作为测试输入。

审计守卫限制文件读取到隔离快照、解释器及系统库范围，限制写入到隔离目录，并拒绝 socket、子进程、native 动态加载和线程启动；实际对 urllib3 的 socket 构造尝试发生了拒绝。此为 Python 层防护和所观察事件的证据，不是对宿主全部本机或原生操作的操作系统级沙箱证明。未触碰现有 checkout、索引、真实服务、账户或保留 host。

原计划的 tests/unit/futures/ 目录不存在；七个目标实际位于 tests/unit/feeds/。本报告只覆盖这七个选定文件，不把目录替代、skip、源码存在或模拟输入当作完整迭代验收。
