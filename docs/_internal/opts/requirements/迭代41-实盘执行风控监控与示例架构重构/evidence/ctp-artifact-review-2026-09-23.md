# CTP SDK 候选 wheel 源码复核（2026-09-23）

使用 `scripts/ctp_artifact_review_evidence.py` 对当前 `D:\bt_api_py` 源码与临时
候选 wheel 做了只读比对。完整的结构化结果见
[ctp-artifact-review-2026-09-23.json](ctp-artifact-review-2026-09-23.json)，文件 SHA256 为
`8454fe58a44f6aa26c64beb84730a8a33105149e7c04afcad1911998dc4f4c82`。

## 结果

- `pin_material_status=refused_dirty_source`、`source_artifact_matches=false`、
  `candidate_pin_material={}`、`catalog_approval=none`；仍要求独立发布审阅。
- SDK 仓库 HEAD 为 `d3674e19a11b9f35f19ae756899bcf18854c8c46`，工作树有 57 项变化；
  `bt_api_base` 和 `bt_api_ctp` 子仓库也分别处于 dirty 状态（3 项与 15 项变化）。
- `bt_api_base 0.15.4` 的 wheel 与当前源码都含 105 个 Python 文件，快照相同：
  `d2b7189abe17364d738e33cd94b4692f22ddc357556c63dd6483b5f0bab03299`。
- `bt_api_ctp 2.0.3` 的 wheel 与当前源码都含 78 个 Python 文件，但
  `bt_api_ctp/ctp/client.py` 有一处差异；wheel 快照为
  `e800957ff6ca86b358648a5e69c753597bbbd092ea0a1afece8bd857417121b8`，当前源码快照为
  `5911a1dc9f892f40ad5e341207148abce6ce3ddec68ec2da1a4c24a0a045b07d`。没有新增或缺失的
  Python 文件。源码和 wheel 的项目元数据匹配，CTP selector 哈希也匹配。
- 候选身份：`bt_api_base-0.15.4-py3-none-any.whl` SHA256
  `d9a3bcd8183cf532dcbb5d16573d3a0af479a88df1e37e267f738379285ce548`；
  `bt_api_ctp-2.0.3-cp311-cp311-win_amd64.whl` SHA256
  `3c80720e4bc092a6dadc7b096683c00511ab9549c31a097521f73f2e27e85f3e`。
- 本次没有传入 isolated installed-site，因此 installed RECORD 哈希为空，结果只覆盖
  wheel 与源码快照核对；即便源码干净，也不足以生成可复制的安装 pin。

工具只扫描 wheel 归档与固定的源码元数据/`.py` 文件，结果不包含文件内容；没有读取本地
配置或凭据、导入 SDK、连接 provider，也没有修改 `CTP_SDK_ARTIFACT_PINS`。wheel 私有成员名
扫描计数为零。此记录不证明发布签名、来源可信度、真实账户会话或运行准入。

## 验证

`python -m pytest -n 0 -p no:asyncio tests/unit/runtime/test_ctp_artifact_review_evidence.py -q`
通过：18 passed。禁用 `pytest-asyncio` 是因为当前环境的插件在 pytest 8 收集阶段报
`Package` 缺少 `obj`；禁用后仅有仓库配置项 `asyncio_default_fixture_loop_scope` 未识别的提示。
目标脚本与测试文件的 `ruff check` 通过。
