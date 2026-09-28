# G4 bt_api_py parent 制品阻塞独立核查

**裁决：`DISPOSABLE_PARENT_WHEEL_VERIFIED / THREE_PACKAGE_PIN_NOT_AVAILABLE / G4_CLOSED`。** 现存 parent wheel 可作为隔离 fake/offline 候选制品；主仓没有 `bt_api_py` 代码拥有 pin，也没有与当前 base/CTP pin 对齐的完整三包 wheel 安装证据。此核查不接受 G4 native start/Join/Release，不打开默认 CTP route。

## 核验范围

只读检查了两个 parent SDK checkout、coordinated parent/execution wheel 候选、settlement wheelhouse 的包身份、主仓 pin/RECORD 校验代码和已冻结的隔离 consumer 证据。没有读取私有账号或配置、导入 `bt_api_py`/`bt_api_ctp`/`_ctp`、加载 DLL、访问 provider/网络或改动主仓/SDK 源树。所有本次脚本、日志和回执位于 `D:\temp\iteration41-g4-parent-sdk-status-qa-20260927`。

## parent wheel 制品身份

候选 `bt_api_py-0.15.7.dev0+r4r3r3.67e54513-py3-none-any.whl` 为明确标记的 disposable dev wheel：

- 两个独立 build 输入根各有 156 个 parent 文件；本次对 `build-input-manifest-v4.json` 的逐文件检查，A 与 B 都是 156/156 字节和 SHA 匹配。
- Wheel A/B SHA-256 都为 `5e6e846d26b5038c0916fa15d3ce3f7a1c1334fd0aa160cd263d2d0397c07b0f`，大小 534,260 B。Wheel ZIP 有 144 个成员，内嵌 RECORD 有 144 行、143 个 payload 哈希均复核通过；内嵌 RECORD SHA-256 为 `5ae8306e16193a5bcd438104b62369bc57151b6f4f4fd7088499dd0b09b22728`。
- 父源码由基线 `76d5e0e60883263e0e79b67df321e7053ed46179` 与 R4 manifest `60b020202ed89169e24afca30b1b1b16680151a11c6f52c518d0f5bbfa7fab0d`、R3r3 manifest `50b0d8b99afdacdaf2055246010e5766bbe630bc66d71c2aeeaca117baf3ce7a` 组成；最终 source manifest 为 SHA-256 `01fa737d2a0f385dec8ce6187d95c4a104c13cce9dde6d693152df7dd94ef4b6`。这是可复现的 hash-bound 候选输入，不是批准的发布 tag。
- 另有历史 `bt_api_py 0.15.5` wheel：SHA-256 `25aadb8fafa5a354fa528ad0f933384124047642fe2744d6b4ba3a9d77ce552e`、embedded RECORD `b24ff7df451a7330bf02eab54ff376c1f382488f2cba187799d08d750bf08949`、ZIP 完整；邻接父仓 HEAD `62e683bc5ec9a04117e39f4a5dcbba1f6e3b16ec` clean，但所有 Git submodules 未初始化，本目录没有该 wheel 的双构建/installed RECORD/PEP 610 或精确源到轮子绑定证据。故只列为历史制品，不替代当前 R4/R3r3 disposable wheel。细节见 `historical-parent-wheel.txt`。`r
- 两个现存 SDK checkout 状态不干净：`D:\bt_api_py` HEAD `d3674e19a11b9f35f19ae756899bcf18854c8c46` 含多项主仓/submodule 修改和未跟踪文件；`D:\source_code\bt_api_py` HEAD `7a5335017bffff35d433bdb8d475a66e50aa50f6` 也有本地修改/未跟踪文件。逐项见 `source-tree-status.txt`。这些 dirty checkout 不应被当作当前 wheel 的直接、干净构建源；本次候选由前述冻结基线与 overlays 构建。

## wheel RECORD 与 installed RECORD 必须分开

当前主仓 `backtrader_runtime/ctp_artifact_provenance.py:621-665` 在 `:663-665` 对**安装后的 dist-info/RECORD 原始字节**取 SHA-256，并与 `CtpSdkArtifactPin.record_sha256` 比较。它不是比较 wheel ZIP 内的 RECORD。

本次读取既有 fresh consumer，并用相同 CPython 3.11.5 / pip 23.2.1 对相同 parent wheel 在两个全新 venv 中再次离线安装：

| 对象 | SHA-256 | 内容 |
|---|---|---|
| wheel 内嵌 RECORD | `5ae8306e16193a5bcd438104b62369bc57151b6f4f4fd7088499dd0b09b22728` | 144 行；143 payload 行 |
| fresh pip 安装后的 RECORD | `2157c78969a17576397cd05828264111f79e793e6bb653532effb13b41ddf036` | 286 行；146 条带哈希记录经逐项验证，140 条空 hash 行（139 个 `.pyc` 加 RECORD self 行） |

两个新 venv 的 installed RECORD SHA 完全相同；日志和解释器/pip 版本保存在 `record-install-a-*`、`record-install-b-*` 与 `two-venv-installed-record-reproduction.json`。这只验证同一 CPython/pip 安装档案的可重复性；没有跨 Python/pip 版本比较。候选 README 记录的 `5ae…` 是 wheel embedded RECORD digest；不能不加区分地写进当前代码校验器要求的 installed `record_sha256`。计划 pin 前应固定受支持的 Python/installer/profile，并用最终三包安装档案重算 installed RECORD。

## 隔离 consumer / fake 测试结果和范围

冻结的独立 consumer venv 使用 Python 3.11.5，无 system site packages。独立审查核对 parent wheel 的 143 个 payload 安装字节与 wheel 相同、PEP 610 direct URL SHA 等于 parent wheel SHA；安装 RECORD 行/文件检查全过。4 组 fake/offline suites 共 143 次执行、123 个 unique node IDs、0 failure / 0 error / 0 skip；所有 suite `native_modules_loaded=[]`。原始摘要、receipt、审查页与 raw archive 哈希见下文。

`pip check` 必须按实际 source-only 配置解读：

- 在卸载 `bt_api_base` wheel 后、未设置 source-only metadata 映射的本次对照命令 exit 1，精确输出：`bt-api-py 0.15.7.dev0+r4r3r3.67e54513 requires bt-api-base, which is not installed.` 日志为 `consumer-pip-check.log`。
- 显式设置候选 `source-only-metadata` 与 `source-adjuncts/base/src` 的 `PYTHONPATH` 后重跑，exit 0，输出 `No broken requirements found.` 日志为 `consumer-pip-check-source-metadata.log`。这与冻结 QA 描述一致：base 是 source-only metadata/source root，不是已安装 wheel；不能当作完整三发行包安装证明。完整两条命令、PYTHONPATH 和输出见 `pip-check-command-context.txt`。
- coordinated independent QA wheelhouse 没有安装 `bt_api_ctp` wheel；CTP 源 root 仅作为 guard/source adjunct 映射，suite 结束时 native imports 仍空。故该 143 项不是三 SDK 包 origin/RECORD/import 链验证。

另有一个 52-wheel settlement offline wheelhouse 干净安装与 `pip check` 证据，但其三包身份为 base `0.15.4` / CTP `2.0.4+g4r2.settlement.probe.20260927` / parent `0.15.7.dev0+r4r3r3.67e54513`。base wheel SHA `cfe3507e1324f675454c41c37cd09ff72c8947c5254e9496e97c373cb8f3b369`，CTP wheel SHA `857b06c914cfc4f58bc04a77f11b77ad5dc3c47dc2be4d9d18b8e2fc805b264d`。它是 `FAKE_ONLY / NO_RELEASE` probe，不匹配主仓已有码有 pin 的 base `0.15.5`、CTP `2.0.3+iteration41.i2` 组合，也没有导入其 CTP `.pyd`。

`wheel-candidate-inventory.txt` 的 `D:\temp` 精确文件名扫描对当前代码 pin 的 base/CTP wheel 返回 0 个 standalone 文件；有匹配的是 parent disposable `.15.7.dev0` 与历史 `.15.5` wheel。主仓 pin hash 和历史 archived evidence 可供定位/恢复输入，但本次没有将别的目录中的 wheel 包当作已验三包安装。

## 主仓三包 gate

主仓文件 hash 为 `78f7b385db4c33f522a645e160b23076d7b600cf539cf6a121897483c49b3c75`：

- `CTP_SDK_ARTIFACT_PINS` 在 `:115-134` 仅含 `bt_api_base` 与 `bt_api_ctp`；其当前身份分别为 base 0.15.5 / wheel SHA `1c1129444d8659f4dfe7b72f716872a63dddf13c1c935865e1d2568800d0d64d` / installed RECORD SHA `47994f991fee3266e62fb368fe167dc1f188eceecfddac6ccc06dad2604e9762`，以及 CTP 2.0.3+iteration41.i2 / wheel SHA `988c52a91a12d3256caadf27df2ae1f1eb45e54fc6c4f63b7abba0363f34c4ff` / installed RECORD SHA `4953ef5cb13468a300693fd3c37b7eb59c4afd0727e3d6dbcf8a15de5abebe08`。
- `_READONLY_CTP_MODULES` / `_MANAGED_SIMNOW_MODULES` 见 `:384-385`；managed verifier 在 `:1055-1068` 要求三模块，但仍传入只有两项的 `CTP_SDK_ARTIFACT_PINS`。`_verify_pinned_sdk_distributions()` 在 `:877-886` 发现缺少 `bt_api_py` pin 后以 `artifact_pin_unavailable` fail-closed，尚未校验/导入 parent。
- `tests/unit/runtime/test_ctp_artifact_provenance.py:573-585` 的专门合同断言正是拒绝缺 parent pin，并断言 `bt_api_py` 不进入 `sys.modules`。

因此当前状态不是“缺 parent wheel 文件”：缺的是**可接受的精确 parent 来源/授权身份、正确的 installed RECORD pin，以及与已 pin base/CTP 组合成套验证的安装记录**。现存 parent wheel 的双构建、包内 RECORD、consumer payload 来源和 fake tests 是有用本地证据，但不能替代这些 gate。

## 最小后续步骤

1. 选择并冻结唯一 parent source identity（当前 76d5 基线 + 两份已 hash 的 overlay，或另行形成已审阅的 immutable commit/tag）；记录源码、构建输入、wheel 全部 SHA，做独立 artifact review。
2. 以明确受支持的 CPython/pip profile，离线安装 exact parent wheel + code-owned base 0.15.5 wheel + code-owned CTP 2.0.3+iteration41.i2 wheel；不能以 source-only metadata 代替其中任一发行 wheel。逐项核对三个发行包版本、wheel/installed RECORD SHA、PEP 610 wheel 来源与 import roots；`pip check` 要在三个 distribution 都在场时通过。
3. 仅在 fresh fake/offline harness 中增加/复跑缺失 parent pin、记录篡改/文件差异、错误 origin、`bt_api_py` import/client 提前拒绝等合同；依旧阻止 `_ctp`/DLL/native 导入。
4. 在该 artifact gate 通过后仍需单独完成有界 Windows Job supervisor 与 native Start/Stop/Join/Release G4 审查。制品 pin 不能推出 native lifecycle 或 provider/账户验收。

## QA harness 诊断保留

本次早期两条自写断言曾失败，均是校验器假设不正确，已保留 raw traceback：wheel metadata 的实际名称是 `bt_api_py`（非 `bt_api-py`）；pip 安装后的 RECORD 是 286 行且只有 146 行携 SHA-256（不是预期的 285）。修正后逐文件/wheel/installed RECORD 校验通过。这些诊断不计作候选构建失败。

## 绑定来源与原始证据

- 作者 raw archive SHA-256 `9510abeffcf040bf4a7ea8b8e0524e93cfe1046a8b9498dbc7e26626adbb2c46`，Zip `testzip()` 成功；独立 raw QA archive SHA-256 `6f90ed890e0eb638f3e4b141fa0433c1cce854cc25661bf07fcccfbfb2ac9ddd`。
- 上游独立输入审计 `7cf5b4c84c36f753d0ae010d86dd901d5280d528c703230f32f9164906b441a4`；安装审计 `a17267072d895568ac3f91820379441380fe5f232b840d418b1d6b1944c1633e`；测试摘要 `a1feb0d15d6e7e1ac4f021687981c900b2802f5e506556c767bcd44659452beb`。本目录保存其副本及本次交叉校验脚本/日志。
- 机器回执：`status-audit.json`；安装摘要复现：`two-venv-installed-record-reproduction.json`；脚本：`audit_parent_artifacts.py`、`reproduce_installed_record.py`。




