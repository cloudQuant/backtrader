# CTP SDK pin 就绪度审计（2026-09-24）

> **历史审计记录，结论已被后续 scoped review 更新：** 本文开头的 “NO_CURRENT_RELEASE_PAIR / pin catalog empty” 是该审计时点的结论。之后 F 的 `bt_api_base` 与 `bt_api_ctp` 制品经独立审阅并写入 code-owned pins，仅供 registered SimNow sandbox read-only preflight；managed 所需第三 `bt_api_py` parent pin 仍缺，managed 保持 `NO_PIN / NO_WRITE`。当前真实 TD 查询尝试失败的详情见[最新验证汇总](validation-summary-2026-09-24.md)。

## 结论

`NOT_PINNABLE / NO_CURRENT_RELEASE_PAIR`。当前没有可用于 Iteration 41 CTP SimNow 路由的 `bt_api_base` + `bt_api_ctp` 成对发行制品。代码拥有的 `CTP_SDK_ARTIFACT_PINS` 仍为空；本审计没有添加 pin、构建/发布制品、导入 SDK、读取配置或凭据，也没有访问 provider 网络。

## 采集到的身份与状态

采集范围为 `D:\bt_api_py` 的 Git/包元数据、`C:\anaconda3\python.exe` 的安装 distribution metadata、现有 Iteration 41 artifact review/install audit 文档。Python 只读 `importlib.metadata`、`RECORD` 与 `direct_url.json`；版本为 CPython 3.11.5。

| 项 | 当前观测 |
|---|---|
| SDK superproject | HEAD `d3674e19a11b9f35f19ae756899bcf18854c8c46`；工作树 dirty |
| `bt_api_base` source | HEAD `3de0fa4f6cfe8d1973e9f4b9b47b01254259524f`（`v0.15.4-3-g3de0fa4`）；工作树 dirty，含已修改 `src/bt_api_base/__init__.py` 和未跟踪 `deployment_evidence.py` |
| `bt_api_ctp` source | HEAD `ce1edd60785eb4c66fefa16a994a66946a1e068f`（`v2.0.2-14-gce1edd6`）；工作树 dirty，含已修改 `pyproject.toml`、`ctp/client.py`、`ctp_env_selector.py` 等文件 |
| 当前 CTP 源包元数据 | dirty 工作树 `pyproject.toml` 声明 `bt_api_ctp 2.0.3`，依赖 `bt_api_base>=0.15.4,<1.0`；该版本声明尚未对应到已审阅的干净提交 |
| SDK checkout / pip cache wheels | `D:\bt_api_py\dist` 仅有聚合包 `bt_api_py-0.15.4-py3-none-any.whl`；pip wheel cache 未发现 `bt_api_base` 或 `bt_api_ctp` wheel |
| 已安装 `bt_api_ctp` | `2.0.2`；118 个 distribution file entries；`RECORD` SHA-256 `7e6da57f2055a6d29863ce948e67be66783890226c44622c20c50a57ebdd7cbb`；PEP 610 指向本机目录，没有 wheel/archive 哈希 |
| 已安装 `bt_api_base` | `0.15.4`；9 个 distribution file entries；`RECORD` SHA-256 `291d5445d6a4dfb400c00ff2194d576afa917042d251333144e247cbd67b2646`；PEP 610 标为 editable 本机目录，没有 wheel/archive 哈希 |

本次读取的安装 metadata 与[2026-09-24 本机安装核验](ctp-artifact-install-audit-2026-09-24.md)中记录的 `RECORD` 哈希及文件数不同；以本次直接读取为当前观测。差异说明安装状态已变化，不能沿用旧 RECORD 指纹。

## 旧候选为什么不能升级为 pin

[2026-09-23 候选审阅](ctp-artifact-review-2026-09-23.md)记录的 wheel 身份为：

| Distribution | Version / wheel | wheel SHA-256 | RECORD SHA-256 |
|---|---|---|---|
| `bt_api_base` | `0.15.4` / `bt_api_base-0.15.4-py3-none-any.whl` | `d9a3bcd8183cf532dcbb5d16573d3a0af479a88df1e37e267f738379285ce548` | `8fef3bd9627cfdfb725d4b522f1dceff8d1f9ee25ad03868989f3225c6cc6d8a` |
| `bt_api_ctp` | `2.0.3` / `bt_api_ctp-2.0.3-cp311-cp311-win_amd64.whl` | `3c80720e4bc092a6dadc7b096683c00511ab9549c31a097521f73f2e27e85f3e` | `68cb71f3f952f13cd4f823c5f261f76351a2354d782f21e1a2bb44dd6c028f65` |

那次审阅明确给出 `refused_dirty_source`、`source_artifact_matches=false`、空 `candidate_pin_material` 和 `catalog_approval=none`。`bt_api_ctp` wheel 与当时源码虽有相同数量的 Python 文件，但 `ctp/client.py` 内容不一致。候选 wheel 当前也不在 checkout 的 `dist` 或 pip cache 中。旧哈希只标识此前的临时候选，不能绑定当前 dirty source、当前安装或一个已批准 release。

## pin 前必须通过的可复核门槛

1. **冻结源码身份。** 将两个包变更提交到明确审阅的干净提交；确认 superproject gitlinks 指向这两个确切提交，source version 与发布版本一致，相关 submodule 和父仓库无未提交/未跟踪变更。复核命令：

   ```powershell
   git -C D:\bt_api_py rev-parse HEAD
   git -C D:\bt_api_py status --short
   git -C D:\bt_api_py submodule status -- bt_api/bt_api_base bt_api/bt_api_ctp
   git -C D:\bt_api_py\bt_api\bt_api_base status --short
   git -C D:\bt_api_py\bt_api\bt_api_ctp status --short
   ```

2. **从冻结提交重建成对 wheel。** 保存目标 Python/平台/构建依赖身份；检查 wheel 文件名、distribution/version、依赖约束、CTP ABI/platform tag、包文件清单及 profile selector。源码与 wheel 的包快照必须相符，尤其重新比对 `bt_api_ctp/ctp/client.py`；不能有未解释的增删或差异。

3. **独立审阅不可变候选。** 对两只 wheel 分别记录 SHA-256 和完整 wheel `RECORD` SHA-256，审阅源码提交到 wheel 的对应关系、构建输出与发布审批。候选审阅必须得到可接受状态，不能是 `refused_dirty_source`，且 `source_artifact_matches=true`、`candidate_pin_material` 完整、批准状态明确。可沿用 `scripts/ctp_artifact_review_evidence.py` 和其测试 `tests/unit/runtime/test_ctp_artifact_review_evidence.py` 生成与验证该证据。

4. **新建隔离安装证明。** 在干净 venv 中仅从审阅过的本地 wheel 路径离线安装这对 wheel；安装完整的已批准依赖 wheelhouse，然后执行 `pip check`。为使安装来源可被代码门验证，两个 distribution 的 PEP 610 `direct_url.json` 都必须绑定精确 wheel 文件及 SHA-256，不能是 editable 或目录来源。

5. **复核安装内容。** 从该 venv metadata 读取版本、完整 `RECORD`、`direct_url.json`；逐项验证 RECORD 文件大小/SHA-256，要求 RECORD 清单与安装 distribution 清单相符，包目录无未记录文件，模块来源位于该 venv 的 site-packages。将两份新 RECORD 哈希、wheel 哈希与候选审阅记录逐一比对，并运行离线 artifact provenance/fail-closed 定向测试。

6. **最后才更新代码 pin。** 将两个精确版本、wheel 文件名、wheel SHA-256 和 RECORD SHA-256 一起写入代码拥有的不可变 catalog；运行相关 artifact provenance 与 Iteration 41 CTP fake/offline 回归。安装/制品门通过只允许把 runtime artifact 身份绑定到代码；本审计与这些离线检查均不构成真实 SimNow 会话或 provider 准入证据。

## 复现本次 metadata 读取

下列命令只输出 distribution 版本、RECORD 指纹、PEP 610 来源类型和本地 pip wheel cache 候选；不输出 source path：

```powershell
C:\anaconda3\python.exe -c "import hashlib,importlib.metadata as m,json; [(lambda d: print(d.metadata['Name'],d.version,len(tuple(d.files or ())),hashlib.sha256((d.read_text('RECORD') or '').encode()).hexdigest(),(json.loads(d.read_text('direct_url.json') or '{}').get('dir_info') or {}).get('editable'),(json.loads(d.read_text('direct_url.json') or '{}').get('archive_info') or {}).get('hash')))(m.distribution(n)) for n in ('bt_api_ctp','bt_api_base')]"
C:\anaconda3\python.exe -m pip cache list bt_api_
```

## 更新状态：本地候选成对构建（2026-09-24）

本节 supersede 上文“没有成对发行制品”及“候选 wheel 不在 checkout `dist` 或 pip cache”作为当前状态的描述；上文保留其采集时点的安装与候选观察。`release-candidate-iteration41-final` 现有 `bt_api_base` 与 `bt_api_ctp` 本地候选 wheel，SHA-256 分别为 `b12e1e84183cd17fb4ea8bb1b046518c7bf6e141ec49faea4cdaa20c9d1c3f9c` 与 `fe2b24e7930758b016bd66d2430086225742edfe0a0561e0ee3fd2fb75f6f0db`。已核对 wheel 中 Python 源码与对应 source Python 文件完全一致，wheel `RECORD` 校验通过；使用这对候选在干净 venv 安装并执行 `pip check` 通过。base suite 为 `676 passed, 8 skipped`。

这仅把状态推进到可验证的本地候选对：source checkout 仍 dirty，尚无独立 release approval 或代码拥有的 CTP pin。CTP 全套已收集 1,265 项，但完整运行被本机任务中断，不能宣称全套通过；已完成的 CTP 七文件焦点集为 `268 passed`，`tests/cleaner` 为 `195 passed`。清理测试的共享 fixture 原用 Windows 不合法的 `??odd-name.parquet`，现以同样无法分类但可创建的 `odd-name.parquet` 替换，仅更改测试，候选 wheel 未重建。上述本地构建、源码/RECORD 比对、隔离安装与局部测试都不构成独立发布批准、SimNow provider 会话或实盘准入证据；当前仍不能将候选写入默认 artifact pin catalog。

**后续复核更正（2026-09-24）：** 上段“候选 SDK `MdClient` 源码与 wheel 载荷逐字节一致”的结论已被当前 artifact-review 结果取代。`release-candidate-iteration41-final` 两只 wheel 的 metadata 与各自候选版本匹配，base 的 105 个 Python 文件与当前 source 一致；CTP 的 78 个 Python 文件中，只有 `bt_api_ctp/ctp/client.py` 与当前 dirty source 不一致。当前 review 返回 `status=refused_dirty_source`、`source_artifact_matches=false`、空 `candidate_pin_material`、`catalog_approval=none`。source manifest 声明 base `0.15.5` / CTP `2.0.3`，而当前已安装版本为 base `0.15.4` editable、CTP `2.0.2` file-source。旧候选源码对比与当时 `44 passed` fake-native 测试仅保留为其测试时点的合同证据，不能证明当前安装与 wheel 一致，也不能批准 pin。默认 pin catalog 仍空；当前 preflight 在 TCP transport 探测后因 base editable origin gate 拒绝，未读取 CTP 凭据、导入 CTP SDK 或登录账号。

**后续 source/wheel 状态补记（2026-09-24 10:15 UTC）：** 七项查询证书的窗口为 35 秒，仓位证据新鲜度限制为 5 秒，`finish()` 复核 expiry/session generation。证书与 position-evidence 两组测试在补齐 synthetic terminal callback 登录初始化后合跑 `93 passed`；该修复只调整测试 fixture，不改 runtime。此前 callback event-fence patch 曾有锁顺序/回调死锁风险，现已被新的本地设计替代：不在 public callback 周围持有 dispatch lock，由 `_query_state_lock` 串行化 origin 检查、队列准入与 callback capture；事件队列绑定 API/generation，waiter 丢弃旧代事件，startup abort 在 state lock 外执行。新增确定性 stale-buffered/abort/cross-thread 测试后，最新报告 `56 focused +17 shutdown` 通过、Ruff 通过；独立 source reviewer 的最终锁审仍待完成。此前 provisional patch 上的 `52+17` 数字不作为当前设计结论。上述仅是本地 source/test 证据，没有独立 pytest log artifact 或新 wheel/source comparison。此前 `frozen-live-compare-verified.json` 位于 `D:\bt_api_py\build\ctp-readonly-current-20260924-neutral-seam\build-logs\frozen-live-compare-verified.json`，早于当前 SDK 查询 TTL 与回调竞态修订，不能再当作当前 source comparison。早前独立 clean venv 中的 `66 passed` 只适用于当时的冻结 wheel snapshot 与测试输入；没有单独 pytest 日志。唯一被该次检查识别的 CPython 3.11 CTP wheel SHA-256 是 `8c211dbc6e2ff35f5445009e0a707eff0e9370344ccc661790692d7e3d7b841b`。其他同名或同为 `2.0.3` 的 wheel 未被该检查覆盖。该快照中通过的 artifact-integrity/ABI 子集不构成 release provenance、当前源码对照、发布批准或 code-owned pin；`catalog_approval` 仍为 `none`，默认 SDK pin catalog 仍为空。最终锁审通过后，仍须从冻结 source revision 重建 wheel，并用新 wheel 的精确 hash 重做 source/wheel 比对和隔离验收，再由独立审阅决定是否更新 pin。
