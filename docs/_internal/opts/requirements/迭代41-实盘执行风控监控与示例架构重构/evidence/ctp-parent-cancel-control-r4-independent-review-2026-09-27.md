# Parent 撤单释放控制端 r4 主桥接独立复核（2026-09-27）

状态：`OFFLINE_FAKE_FOCUS_PASS / RELEASE_NOT_ACCEPTED`。此复核只覆盖隔离源码 overlay 和 fake-provider 集成，不批准 CTP、G4/F14、真实撤单或生产释放。

## 冻结来源与测试

Parent r4 冻结快照为 `D:\temp\iteration41-cancel-control-r4-freeze-r1-20260927`，payload manifest SHA-256：`60B020202ED89169E24AFCA30B1B1B16680151A11C6F52C518D0F5BBFA7FAB0D`。独立复核逐项校验了 154 个 payload 条目，并在新 overlay 中再次核对 154/154 字节一致。冻结变更文件为 `cancellation_control.py` SHA-256 `8B7D2B02654D0B4A9FBEA63F4BC359A0135DF6410CF4034EA069A41E32B898CD` 与控制端测试 SHA-256 `0160907F5AE68EBA844BF39961B65EA09F038C3D0517A3FB0E432A142407C8D7`。

源组合是 source-only metadata shim、parent r4、本地 Backtrader overlay 和显式 base/Execution/risk/monitor/gateway 等源码根；不是已安装 wheel 组合。10 个受 guard 记录的进程有 1,158 条 source-import 记录，所有 observed imports 与期望根一致。CTP SDK 源码根只列入路径配置，fake 测试未导入 SDK；未读取私有配置、未启动 provider，也未发起 native 请求。源根与逐文件归档在机器回执和原始 ZIP 中。

原三个桥接节点在新 overlay 中 `3 passed`，一条现有 `backtrader.feeds.quandl` 弃用警告。五文件焦点 `73 passed`，同一条警告。三个节点包括离线 fake runner bootstrap、撤单 proof/release、以及 unknown takeover 后阻断重派。r3 对照记录保留了原先 `2 passed / 1 cleanup teardown failure` 与五文件 `70 passed / 3 failed`；r3 的 monitor SQLite 连接未显式关闭，造成 Windows 临时目录 `WinError 32`，随后 `WinError 267`。r4 的新复跑不再出现该清理失败。

## 尚未接受的边界

- r4 只覆盖协作式 SQLite 写者。已知同用户具备数据库 DDL 权限时可 `DROP TRIGGER` 后删除 monitor 事件，因此不提供抵御同用户恶意数据库写入的隔离。
- Risk 与 monitor 状态分属两个 SQLite 数据库；没有一般性的跨库原子事务保证。
- r4 作者报告改动文件有 23 项 Ruff 发现；本次独立桥接复核未重跑 Ruff。
- 以上结果是 source-only、fake-only 的局部复核，不构成发行制品、G4/F14、CTP 或生产取消释放验收。

原始证据包：[raw ZIP](ctp-parent-cancel-control-r4-independent-review-2026-09-27.raw.zip)，SHA-256 `c054ef744fc3f1386b9fe2cb30e8fb97a4263b70b8bb2a1cf8b2d752fe0c9766`。机器回执：[review-result.json](ctp-parent-cancel-control-r4-independent-review-2026-09-27.json)，SHA-256 `213878331ce1bdcd99fc4ca14d7951df3c3461d27fa5d784fd26af4d2f021c3e`。
