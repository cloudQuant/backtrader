# G5 V22 隔离 wheel 与安装来源复核（2026-09-27）

裁决：`PROBE_WHEEL_IDENTITY_PASS / G5_BLOCKED / NO_WRITE`。独立 QA 以冻结 V22 manifest SHA-256 `8244038ab975f30de6c0ba56c140f033ddd5b5ce5fb3cabc9e60abb7bf24066d` 和 R3r3+V21 基线 SHA-256 `00577665667a33c9a7d62d331c0cad99b0b660790d0b475d0bd8c1b6caa6e2dd` 为输入，只在隔离 staging 将 `0.2.0` 元数据变成探针版 `0.2.2.dev0+v22.8244038ab975`。两次离线构建 wheel 字节一致，SHA-256 `bfa0583be8f97cc62f979b5848d7b798d440789617bf3dec813be53641d0702a`；18 个 RECORD 行中 17 个有哈希，自身 RECORD 行不哈希。

新建无 system-site 的 Python 3.11.5 消费环境核对了 11 个包的精确 wheel 来源、`direct_url`、安装文件及 RECORD，`pip check` 通过，`_ctp` 未加载。进程退出恢复焦点 `20 passed`。完整未过滤包测试为 `309 passed / 2 failed`：两项桥接测试要求真实 Trader 登录证据，在 native import guard 下无法成立；只精确排除这两项后为 `309 passed / 2 deselected`。原始失败与精确排除的日志、JUnit 均保留，不能称完整包无条件通过。

独立回执 SHA-256 `7d1f089d86344db0347b10b96c13a501c74ae80862b01b6d8667f2393dbbda24`。root 对回执声明的全部 29 个输入/日志/wheel 逐项核对大小及摘要，并将回执和制品封存到[原始归档](ctp-g5-v22-installed-wheel-independent-review-2026-09-27.raw.zip)：31 项，ZIP 完整性及内部摘要通过，SHA-256 `5cf3b310707a4d78ccb21ba945e5be425e4a55c0277f777c47f46d84b9fca1b3`。此 wheel 是已占用的临时探针身份，不是稳定 `0.2.2` 发布。

V22 只测试注入的假进程退出验证器。它没有绑定真实 G1 native-owner 进程/Job 的受信验证器、服务制品 pin、真实 provider 会话或默认写路由。旧无进程代次 CLAIMED 在迁移后 UNKNOWN 并永久冻结；真实进程崩溃前未取得原生请求回执的结果仍未知且不可重派。G5 继续阻断模拟盘和实盘写入。
