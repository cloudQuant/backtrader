# Risk 包版本一致性与严格安装环境复验

日期：2026-09-26。范围：离线候选制品，未更新默认 pin 或发布/交易权限。

原 risk `2201316f` 的 `__version__=1.0.0` 与 package metadata `0.1.0` 不一致。
根代理只修改公开模块版本，保持 pyproject 的权威版本，并本地提交为干净候选
**`d4bc03047ebfc2b416259aba313fafca7a0dffcc`**，未 push。

独立子代理从两个 detached clean clone 构建，固定 `core.autocrlf=true`、
`SOURCE_DATE_EPOCH=1790000000`、Python 3.11.5 及原构建环境。两份完整 wheel
字节一致：

```text
bt_api_risk-0.1.0-py3-none-any.whl
SHA-256 d7e7bb28cfd049be3aa0b50f1e9deb7a83e97f24da3bc9bce51dc6f599a5202f
size    92587 bytes
```

全新无 system-site 的 consumer venv 使用真实 `python.exe -I -m pytest`，7 个
复制测试文件均与 clean source hash 一致，结果 **206 passed**。模块与 metadata
同时报告 `0.1.0`；installed RECORD/payload、origin、direct_url wheel hash 和
`pip check` 均通过。根代理另用该真实 venv 的 `python -I` 独立复核版本、解释器、
模块位置和隔离配置，并复核回执、wheel 副本及旧 manifest 的 SHA-256。

base `3de0fa4`/0.15.4 与 monitor `f3583e7`/0.1.0 复用此前已验 wheel，没有重建或
重测它们的功能套件。旧三包 manifest 保持原始字节，SHA-256 为
`b3ddfc47944b05671cbbd14b9a88a104ae66ea4843728ad06b8ac762d415b34b`。

[新回执 JSON](risk-version-consumer-2026-09-26.json) SHA-256：
`e09f9371d6b928ca4a5b8518d44d83a46bea31346798ae18c3f8314f7761590f`。
完整临时材料位于 `D:\temp\iteration41-capability-risk-version-fix-20260926`。
该结果不包含最新 parent/CTP/execution 的统一制品或真实账户验收。
