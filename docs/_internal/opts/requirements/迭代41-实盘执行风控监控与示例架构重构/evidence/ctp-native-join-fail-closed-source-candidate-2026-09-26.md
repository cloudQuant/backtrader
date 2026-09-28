# CTP Join/Release fail-closed 源码候选（2026-09-26）

隔离 worktree：`D:/bt_api_py/bt_api/bt_api_ctp-native-join-lifecycle-worktree`。
修改仅在 `src/bt_api_ctp/ctp/client.py` 和 `tests/test_ctp_shutdown.py`；
源码候选已本地提交为 `df565f6debef1fccd22fe378a2ccd774b4c61a67`，未 push、未构建成 wheel，也没有真实 provider 运行。提交仅包含这两个文件；隔离 worktree 仍有未纳入提交的历史 `native_join_candidate/` 目录。

源码审阅发现退休 API 的 `Release()` 异常原先会被吞掉：保留表先移除
API/SPI，随后客户端清除 pending Join 栅栏，允许在释放状态不明时重启。
候选改为只在 `Release()` 正常返回后移除保留项；异常后永久 poison 该
API ID，不重试 `Release()`，保留 API/SPI 和 pending 重启栅栏。另为同一 API
增加 Join claim，避免 MD/Trader 的两个并发 observer 各启动一次 `Join()`
并重置观察器状态。

两人分别从该 worktree 源码运行纯 fake `tests/test_ctp_shutdown.py`，
结果均为 **31 passed**（一条既有 pytest 配置警告及本机缺 `_ctp` 的预期警告）。
测试覆盖 Release 首次失败后再次调用 helper/stop 不重复释放、MD/Trader
重启继续拒绝，以及并发 observer 恰有一个成功且 Join 只调用一次。
Ruff、`py_compile`、`git diff --check` 通过。未调用 VSDevCmd、编译器、
wheel 构建或真实账号/前置。

后续另在隔离 CTP worktree 从 exact `ce1edd6` 合成当前 Feed Ref guard
`0609b05` 与 Join 候选的**完整五提交祖先链**（不能只取尾提交 `df565f6`）。
两组修改路径无交集，六个 cherry-pick 无冲突；合成 HEAD 为
`9976bcbbbe331ee77e2d90e05da08472259a625a`，worktree clean。
Feed、Iteration 22、shutdown 和 native callback 四个受影响 fake 文件
合跑 `255 passed`；八个修改 Python 文件 Ruff 通过。合成源码中 Feed
仍要求显式 12 位 ASCII 数字 Ref、原样透传；callback queue 的独占消费
lease 与 legacy wait 路径相互拒绝并发消费；同一 client 有 pending Join
时不能重启。父 SDK 的独立 Gitlink 候选 `7fe53a0` 仅指向 Feed commit
`0609b05`，**没有**指向此合成 HEAD；默认运行时和受信制品也未更新。

这仍不是 G4 的真实有序关闭证据。`_already_claimed=True` 是内部调用约定，
当前唯一 caller 先取得 claim，但缺少不可伪造的 claim 类型；Join 异常的
fake 测试目前仅覆盖 Trader，直接同步启动的 Release 异常也未包含在此候选。
供应商 `Join` 是否会在该会话条件下返回、`Release` 的真实效果、线程退出和
与精确 wheel/native 扩展的匹配仍为 `NOT_RUN`。Windows Job 清空只能证明
进程 containment，不计有序 native close。合成候选的 `wait_native_join`
最长 60 秒只限制等待者；超时后的后台同步 `api.Join()` 仍可能挂住。
`Join=returned` 不能代替 `Release=returned` 或无线程残留的完整关闭回执。
供应商精确 MD/TD、OS/ABI、6.7.7 二进制的生命周期合同与真实 native
观察仍须单独取得；不能因合成 fake 测试通过而解除 G4 或普通 preflight。
