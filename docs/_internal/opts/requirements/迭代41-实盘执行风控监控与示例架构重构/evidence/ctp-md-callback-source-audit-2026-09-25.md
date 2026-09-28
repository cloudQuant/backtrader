# CTP MD 登录回调身份源码复核（2026-09-25）

状态：`SOURCE_HYPOTHESES_ONLY / REAL_MD_NOT_ACCEPTED / NO_WRITE`。本次仅审查本地 CTP SDK 源码与已脱敏的 I2/I4/I6/I7/I10/I13 记录，没有重新使用一次性 marker、私有配置、账号或 provider。

I2 的 `request_id_mismatch` 与后续 `broker_id_mismatch` 是不同失败。I2 固定 SDK `28157ce3` 使用连接代次作为登录请求 ID，并在身份字段读取前要求回调 ID 精确相等；当时回调 ID 0，因此被拒。SWIG director 将 C++ `int` 原样转为 Python 整数，现有记录不能解释 native 为什么返回 0。I6 one-shot 则主动使用请求 ID 0，回调 ID 0 正常；其拒绝点是身份未验证，不能再把“零 ID”写成同一根因。

I4 只记录 SDK 的 BrokerID 比较不匹配，缺少原生字段形状，不能由此判定账号错误或字段一定为空。I7/I10 的历史原生形状观察显示 BrokerID/UserID 字段首字节为空，TradingDay 字段有形状；I6 合成 SWIG 对象的字段往返正常。组合起来只能把疑点收窄到真实 vendor callback 的数据、结构布局或借用指针生命周期，不能推断认证失败。I13 SDK `c68bebe` 增加了在 callback 内同步读取原生定长数组形状与 getter、并在已验证身份的延迟通知前复制整份响应；它尚无受监督的真实 provider 观察。

源码边界：Windows CTP 6.7.7 头文件将 BrokerID/UserID 定义为 `char[11]` / `char[16]`。`ctp.i` 的原生形状 helper 区分首字节 NUL、正常终止与未终止数组；生成 getter 使用数组读取及转换。`SwigDirector_CThostFtdcMdSpi::OnRspUserLogin` 传给 Python 的响应是 borrowed pointer。当前 one-shot 代码在 callback 内先读取字段；已验证的延迟结果使用 owned copy，未验证身份的延迟事件没有保存该指针。源码审查没有找到一个可直接定论的“排队后读取悬空登录指针”路径，也不能证明 vendor 回调结构布局正确。

测试专用 native shim 已在独立、未冻结的 I13 源码 worktree `D:\temp\c41sdki13-native-boundary-fake` 中完成，须以 `BT_API_CTP_TEST_NATIVE_CALLBACK=1` 显式编译。它在 C++ 栈上构造登录响应，通过 `CThostFtdcMdSpi::OnRspUserLogin` 虚函数进入 SWIG director，返回后覆写原结构。新增三项测试通过，完整 MD one-shot 文件 `107 passed`，Ruff 通过；独立 reviewer 复跑三项并确认该路径确实经过 C++ virtual→SWIG director→Python，没有发现 P1/P2。空 BrokerID/UserID 在 callback 内呈 EMPTY 并保持 `identity_unverified`；有效 ASCII 可精确匹配，延迟事件持有 `thisown=True` 的完整 owned copy；未终止数组呈 UNTERMINATED/UNREADABLE 并拒绝 getter。这证明当前头文件、测试构建 wrapper、Python callback 在合成 native director 调用中的读取与生命周期合同，没有证明真实 vendor 回调为何为空，也没有证明实盘 DLL 的结构布局或真实登录成功。该 worktree 的测试改动尚未提交、未进入默认 SDK pin。

另从冻结 I13 commit `c68bebe8631419801e7a24e13b98c42867df0beb` 建立独立默认构建 worktree，拷入相同 shim 源码改动，并在构建进程中明确清除/断言 `BT_API_CTP_TEST_NATIVE_CALLBACK` 未设置。普通 wheel SHA-256 为 `0b92d6f84693fe6a0fb1c3307ff3e6e69b470668fe50a921db0180f03ccf8394`；隔离安装后 Python shim export 不存在，native payload 内 helper/method 字符串及 MSVC object 符号均不存在。普通 wheel 下 MD one-shot 文件 `104 passed, 3 deselected`（三项 shim 专用测试）。这证明本次普通构建未携带测试入口；该独立构建仍非受审 production pin，也未接 provider。

下一步仍需隔离验证 I2 精确提交/回调 ID 的 0、匹配与旧代次拒绝顺序，解决父进程信任根、原生 Join 关闭，并受监督观察真实 MD login→订阅 ACK→matching tick。当前不产生新的真实诊断许可，更不开放报撤单。
