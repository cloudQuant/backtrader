# CTP SDK 本机安装制品核验（2026-09-24）

## 结论

`NOT_PINNABLE / NO_RELEASE_ELIGIBLE_ARTIFACT`。本次核验没有找到可写入
`backtrader_runtime.ctp_artifact_provenance.CTP_SDK_ARTIFACT_PINS` 的 SDK 制品。
该映射继续为空，默认 SimNow 路由在本次核验时未登记。本记录不证明发布来源、代码审查、
生产部署资格或真实 SimNow 会话。

## 本机安装情况

检查使用 `C:\anaconda3\python.exe` 的 Python distribution metadata 和安装目录；
没有导入 CTP SDK 模块，没有读取账号配置或密钥，也没有访问网络或供应商。
检查同时核对了各安装分发包的 `RECORD` 中列出的文件大小和 SHA-256。

| Distribution | 安装版本 | 已检查 RECORD 文件 | RECORD 不匹配 | PEP 610 来源 | 结果 |
|---|---:|---:|---:|---|---|
| `bt_api_ctp` | `2.0.2` | 117 | 0 | 本机目录；无归档哈希 | 不能绑定不可变 wheel |
| `bt_api_base` | `0.15.4` | 8 | 0 | editable 本机目录；无归档哈希 | 不能绑定不可变 wheel，且 RECORD 不覆盖完整源码 |

安装 RECORD 文件本身的 SHA-256：

- `bt_api_ctp`: `dc1e744aa7b67a2801570143d708f54eae8eae32f8a3b538d58cb5631f9ad174`
- `bt_api_base`: `b64813445b80731231a0519a9eb35734f34ac4577f8323a3802332aeabcd17ac`

`bt_api_ctp` 已安装版本是 `2.0.2`。Iteration 41 的候选证据目标为 `2.0.3`，因此
即使本机目录安装文件与它自己的 `RECORD` 相符，也不能满足当前 SDK 能力版本要求。
`bt_api_base` 的安装 metadata 标为 editable，不能以该 RECORD 代表实际源码内容。

## wheel 与现有候选证据

在 `D:\bt_api_py` SDK checkout 的目录树和当前 pip wheel cache 中核查 CTP/base wheel：
SDK checkout 仅发现聚合包 `bt_api_py-0.15.4-py3-none-any.whl`，pip cache 仅发现
`bt_api_base-0.15.4-py3-none-any.whl`；没有发现当前安装版本对应的 CTP wheel 或可配对的
`bt_api_base`/`bt_api_ctp` wheel。

现存 [2026-09-23 候选审阅记录](ctp-artifact-review-2026-09-23.json)包含候选：

| Distribution | 候选版本 | wheel SHA-256 | wheel RECORD SHA-256 |
|---|---:|---|---|
| `bt_api_base` | `0.15.4` | `d9a3bcd8183cf532dcbb5d16573d3a0af479a88df1e37e267f738379285ce548` | `8fef3bd9627cfdfb725d4b522f1dceff8d1f9ee25ad03868989f3225c6cc6d8a` |
| `bt_api_ctp` | `2.0.3` | `3c80720e4bc092a6dadc7b096683c00511ab9549c31a097521f73f2e27e85f3e` | `68cb71f3f952f13cd4f823c5f261f76351a2354d782f21e1a2bb44dd6c028f65` |

这只是此前的本地构建审阅材料，不是本机当前安装证明或发布证明。该记录将
`pin_material_status` 标记为 `refused_dirty_source`：SDK checkout `D:\bt_api_py`
采集时处于 dirty 状态（HEAD `d3674e19a11b9f35f19ae756899bcf18854c8c46`），并且
`bt_api_ctp/ctp/client.py` 有一处源码与 wheel 内容不一致。故这些候选哈希不可升级为
代码 pin。

## 下一步

先将 CTP/base SDK 变更提交到明确审阅的干净源码版本，再从该提交构建配对 wheel。对
两个 wheel 重新生成审阅记录，确认源码快照、元数据、完整 wheel `RECORD`、依赖和
SimNow profile 均匹配；随后在新的隔离环境安装这对 wheel，再采集安装 RECORD 与
wheel 来源哈希。只有经过独立制品审阅后，才可考虑把确切 wheel/RECORD 双哈希写入
代码拥有的 pin。此步骤仍不登记 SimNow runtime、不读取凭据、不打开 provider 会话。

## 后续状态说明

上文记录的是当次安装与旧候选的核验时点。默认 inventory 此后已登记 CTP SimNow 私有只读 route（无 runner/写能力），但其私有配置不存在，代码拥有的 SDK pin catalog 仍为空；production 仍未登记。后续构建的本地成对候选、隔离安装及未完成的 CTP 全套测试见[SDK pin 就绪度审计](ctp-sdk-pin-readiness-audit-2026-09-24.md)。新候选尚无干净源码提交和独立发行审阅，不改变本页的 `NOT_PINNABLE` 结论，也不构成真实账号或 provider 连接证据。
