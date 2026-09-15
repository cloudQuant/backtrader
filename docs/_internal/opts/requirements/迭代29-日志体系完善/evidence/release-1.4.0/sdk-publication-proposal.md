# Backtrader 1.4.0 CI 的外部 SDK 发布候选

> **历史发布前提案，已被后续执行取代。** 本文保留当时的候选范围、权限和阻塞事实；它不再描述当前状态。当前记录见[联合验收与发布记录](../../1.4.0联合验收与发布记录.md)和[修复后本地候选证据](post-fix-local-closeout.md)：bt_api_base 0.15.4、bt_api_ctp 2.0.2、bt_api_py 0.15.3 已发布。

> **主仓分支边界更正：** 本提案中的 `dev/master` 仅指各独立 SDK 仓库。Backtrader 主仓本次只允许 `dev` → `development`；`master` 是历史只读基线，必须 **NOT_TOUCHED**。本提案不授权、也不暗示任何 Backtrader master 合并、CI、tag 或 Release 操作。

## 需要解决的问题

当前 CI 固定的 `bt_api_py` 提交 `40deb51b8855cdd2e0120067a1c988ab3a9068e2` 不导出 `CtpExecutionApprovalCapability`，导致已有审批能力契约测试在收集阶段报错。该类型首次在 `ee3a8bc1385fcb5a06196638566560a696f7c304` 出现；候选的 `bt_api_py/__init__.py:104-114` 明确导入它，`__all__` 同时导出它，类型定义位于 `_ctp_execution_authorization.py:1171`。不应修改测试来跳过已安装但 API 不完整的 SDK。

## 建议授权的三个远端引用

三个仓库均只新增同名分支：`refs/heads/codex/backtrader-v1.4.0-ci-sdk`。

| GitHub 仓库 | 新分支指向的完整 SHA | 当前公开基准及相对提交数 | 差异规模 |
|---|---|---|---|
| cloudQuant/bt_api_py | `ee3a8bc1385fcb5a06196638566560a696f7c304` | `dev` = `40deb51b8855cdd2e0120067a1c988ab3a9068e2`；ahead 4 / behind 0 | 21 文件，+20,530 / -1,442 行 |
| cloudQuant/bt_api_base | `74be52d8432c348c93304e9f3b5774bb4dbc766c` | `codex/iter21-cross-venue-arbitrage` = `89dc18ee64aa068fa6271c2796fe27d4c81bdab6`；ahead 1 / behind 0 | 2 文件，+102 / -2 行 |
| cloudQuant/bt_api_ctp | `b371098d5f7f91c8843da1ff6ded6da568ac8f4e` | `codex/iter21-cross-venue-arbitrage` = `22cd9267973eae1687063a1cd9e4e05207bafa5f`；ahead 4 / behind 0 | 41 文件，+17,972 / -1,222 行，另包含一个已跟踪 macOS native 二进制变化 |

合计：公开 9 个既有增量提交；三个 diff 合计 64 个文件、+38,604 / -2,666 行。SDK 两个 gitlink 行计入 SDK 文件数；这不是仅增加一个类型的微小补丁。

本地只读核实：

- SDK 当前 HEAD 为 `b22a678521278de23cf6a86fe8dd755e7052fa74`，相对公开 `dev` 有 13 个提交；本提案停在最早提供缺失能力的第 4 个提交，不公开其后的 9 个提交。
- base 当前 HEAD 正是 `74be52d8432c348c93304e9f3b5774bb4dbc766c`；CTP 当前 HEAD 正是 `b371098d5f7f91c8843da1ff6ded6da568ac8f4e`。
- 三个仓库 `git status --porcelain=v1` 均为空。未读取 `.env` 或凭据文件，未改动任何外部仓库。
- SDK 后续 9 个提交包含其他测试、OKX margin mode、bounded reconciliation 和 Binance 更新；本次不把它们一并发布。这不代表这些变更对所有运行场景都无关，仅限定本次最早候选的范围。

## SDK 的最小既有提交链

四个提交是单一线性祖先链，依次为：

1. `715486eb9de5ec5f982366ff0e3769940c8df11e` — expose iteration 22 execution contracts；5 文件，+513 / -6。
2. `23562d16ab94993e11c39ded02874b7dc685ffee` — harden managed execution contracts；11 文件，+8,564 / -1,033。
3. `721ef3bbb70d271af83c4fcab76469c52e2fd5cc` — add managed SimNow contracts；6 文件，+214 / -11。
4. `ee3a8bc1385fcb5a06196638566560a696f7c304` — add CTP path budget, entry approval and close plan owners；9 文件，+11,245 / -398。

单次提交统计相加不等于首尾 diff，因为同一文件在链内被多次修改。建议直接公开现有 tip，不 cherry-pick 或改写这条依赖链。

该 SDK tip 的两个改变过的 gitlink 是：

- `bt_api/bt_api_base`：`89dc18ee64aa068fa6271c2796fe27d4c81bdab6` → `74be52d8432c348c93304e9f3b5774bb4dbc766c`。增量为 GatewayTick 的 Quote V2 字段及协议序列化测试。
- `bt_api/bt_api_ctp`：`22cd9267973eae1687063a1cd9e4e05207bafa5f` → `b371098d5f7f91c8843da1ff6ded6da568ac8f4e`。CTP 子链为 `bc3e0728e7c2e6d80f7166a3516755eaa363302e` → `ea6dbf81f8183fdca60c560bb2efd1afae61ad6b` → `9bfc7d459c2a7e72a75007406b3294e8d49f307b` → `b371098d5f7f91c8843da1ff6ded6da568ac8f4e`。

## 公开可达性核实

2026-09-15 实际只读查询结果：

- `git ls-remote` 确认上述公开基准存在，三个拟新增分支均不存在。
- GitHub commits API 对三个候选 SHA 均返回 HTTP 422。
- GitHub codeload 的候选 tar.gz HEAD 请求均返回 HTTP 404。因此目前 CI 不能直接下载这些精确候选。
- 不需要发布新的 OKX/Binance ref：SDK 候选仍引用已公开的 OKX `d407ba69f40f775f4d6aa4d07c9a96f94ddb5263`、Binance `9985d13d32ce4080d8d1c2da36f404800f9a6675`；两者当前都可从各自 `codex/iter21-cross-venue-arbitrage` 分支取得。

## 只公开 SDK 一个 ref 是否足够

**只能解决候选 SDK 本身的可下载性，不能证明完整依赖组合成立。** SDK 的 `setup.py` 只打包 `bt_api_py`，GitHub archive 与 pip 不会自动安装 gitlink 指向的子模块；元数据仅要求 `bt_api_base>=0.15.2`，也不会强制选到这里的新 base 提交。保留当前旧 base/CTP pin 将得到另一套混合依赖，不能当作此 SDK gitlink 组合的验收。

仅就缺失类型的静态导入而言，该类型定义使用 SDK 自身与标准库，不要求在导入瞬间加载新的 CTP native 模块。但这不等于 managed CTP 运行能力可与旧插件互换。建议三个仓库一起公开上述最早候选闭包，CI 显式 pin 三个 archive；公开 ref 本身无需版本升级或变更主分支。

授权后，Backtrader CI 依赖文件的对应候选值为：

```text
bt_api_py @ https://github.com/cloudQuant/bt_api_py/archive/ee3a8bc1385fcb5a06196638566560a696f7c304.tar.gz
bt_api_base @ https://github.com/cloudQuant/bt_api_base/archive/74be52d8432c348c93304e9f3b5774bb4dbc766c.tar.gz
bt_api_ctp @ https://github.com/cloudQuant/bt_api_ctp/archive/b371098d5f7f91c8843da1ff6ded6da568ac8f4e.tar.gz
```

OKX、Binance、spdlog 的既有 pin 保持原值。SDK 候选要求 Python >=3.11，适用于独立 SDK lane。CTP 是 native 包：候选 setup.py 会编译已跟踪的 `ctp_wrap.cpp`，Linux 链接所需头文件和两个 `libthost*_se.so` 已在该提交中；不把 macOS `.so` 当作 Linux wheel。实际 Ubuntu 编译与加载仍需验证。

## 授权后执行与验收边界

授权范围仅为：向三个 GitHub 仓库各推送一个上述既有 SHA 到同名独立 CI 分支，再将本仓库 CI pin 更新为这些 SHA 并运行验收。不 force push，不改变远端 dev/master/tag，不创建新的 SDK 内容提交，不推送本地 SDK HEAD，也不修改 Gitee。

执行前重新核对工作树及三个目标 ref；若目标已存在且指向不同 SHA，应停止而非覆盖。先发布 base/CTP，再发布 SDK，随后用 `git ls-remote` 与 archive 下载验证精确 SHA。

**NOT_RUN：** 本次没有构建/安装候选，没有运行候选 SDK 测试、CTP native 测试或 Backtrader 全量测试，没有做登录、下单或实时交易验收。此前本机已安装 SDK HEAD 的通过结果不能代替此最早候选组合。发布分支只是让精确输入可供 CI 下载，CI 安装、缺失类型预检、功能与性能检查全部通过后才能解除本次发布依赖阻断。
