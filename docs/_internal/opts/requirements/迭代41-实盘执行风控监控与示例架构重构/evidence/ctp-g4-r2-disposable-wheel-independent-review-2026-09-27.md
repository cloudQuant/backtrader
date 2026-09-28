# G4 r2 disposable wheel 独立审查（2026-09-27）

## 裁决

**WHEEL_SOURCE_FAKE_INSTALLATION_PASS / G4_NATIVE_CLOSE_CLOSED / DEFAULT_PIN_CLOSED**。

仅接受本地 disposable wheel、冻结源码身份、隔离安装与 inert fake 消费测试。不是原生 CTP 生命周期关闭证据，不接受真实 Join/Release，不打开默认 CTP route，也不构成 SDK/default pin 或生产接受。

## 身份与构建

- 探针根：D:\temp\iteration41-g4-lifecycle-r2-repro-probe-20260927。冻结 receipt SHA-256 4b23afe25c80830b01409e7319f5b27a94ab29456ed2b775e304049b57023671；evidence manifest d579ef460d9fd1b9e03364f7e96f9c58cf1afc78b72eaa326bcb7225829c9dc7；README 96eeb81ebce64b5512a43572d9847b9f8f8572854f21c499add98a65fc0c18a7。38 个冻结 evidence 文件哈希均通过。
- 干净基线 D:\q\e 为 HEAD 29f8ff171f61a71038328a7067e0909bf44774b2，审查前后均 clean。r2 候选在同一基线上只有 src/bt_api_ctp/ctp/client.py 与 tests/test_ctp_native_lifecycle_receipt.py 两项；覆盖 manifest SHA-256 e55d077572ee7f071d3d0ad0fd74522618e1e338a6e38e9963ed6ef76d2f15ee，两个文件 hash 匹配。
- A/B 使用不同 source/output/scratch roots，均退出 0。wheel 版本 2.0.4+g4r2.probe.20260927，各 5,433,813 bytes，SHA-256 均为 00e0c0c56574f60013115ee6010e531f72a8c811780f27dfcba3249cdafb5384。每个 ZIP 90 个成员，成员集合/逐成员 hash 相同且 testzip clean。每个 RECORD 90 行，89 个 payload hash 校验通过。
- 最终 _ctp.pyd 和两个随包 DLL 在 A/B 一致，但中间 ctp_wrap.obj 不同：A 455693844163f197f4c4e5b688f09449c301bd72db8931faf8d01631f9fe2123，B c6a7ed3b51092314ea96ff2be62457a41ea425f5dd5e2b548c091dec2e84959f。因此只报告 wheel/最终 native output 可复现，不声称全部中间对象一致。
- 版本扫描计 28 项，包括此次 A/B 两 wheel；明确排除这两个 probe 自身后，先前 26 个本地 wheel 无版本碰撞。仅是本地库存范围，不涉及包索引/网络。

## 隔离安装与限制

- strict no-system consumer venv 从 wheel 离线安装，包来源与 direct-url hash 指向本 wheel。安装 RECORD 共 174 行，92 个有 hash 条目验证通过、82 个无 hash 条目；89 个 wheel payload 安装 bytes 均相同。pip check 退出 0，输出 No broken requirements found.
- wheel 内 _ctp.cp311-win_amd64.pyd 和两个 CTP DLL 的安装文件 bytes 匹配 wheel。但 meta-path guard 在导入扩展前阻断 _ctp，因此 DLL 未映射/加载；这不是 runtime mapped-DLL 测试。
- inert fake 消费 suite 为 66 passed、0 failures/errors/skips。日志含两类 warning：一个既有 pytest 配置 asyncio_default_fixture_loop_scope 未识别；另一个 RuntimeWarning 由有意 _ctp guard 触发（作者摘要只提了配置 warning）。guard 记录两次扩展加载拒绝，ctp_native_loaded=false。
- cl /Bv 探针因缺少源文件名报告 D8003，cl_bv_exit=2；VS 环境初始化、工具探测及两次构建均成功退出。保留这一诊断异常，不把它当作 build failure。
- 初次逐文件 raw SHA 比较曾误报 EOL 变化：该路径基线 raw SHA-256 2950f29a32b8fff49f293554fc3765d8c0a8e566eea0207a7444380fd9251bcd，source-a/source-b raw SHA-256 均为 08f37df3b48a378e4fcb3c4980dc2e3812ce4deb446b45a7fbd29d8a6a64e4e9；按 Git 路径清理后的 HEAD blob SHA-1 为 158514df5a02184af081a373092a59c7d856aea7，完全一致。QA 自身早期脚本假设修正记录见 initial-comparator-correction-note.md。

## 证据范围

配套 JSON 与 raw ZIP 保存冻结 receipt/manifest、构建和工具链日志、两只 wheel 与 RECORD、安装审计、fake 测试日志、源码/覆盖 manifest、独立审计脚本和更正说明；不含完整 source trees 或 venv。没有导入真实 CTP 扩展、连接 provider、读取账户/凭据或访问网络。不证明原生 Join/Release 命令截止、clean shutdown、默认 pin 或 G4 接受。
