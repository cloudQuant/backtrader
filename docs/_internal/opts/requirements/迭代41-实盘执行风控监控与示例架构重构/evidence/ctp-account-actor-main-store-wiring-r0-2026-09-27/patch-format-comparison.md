# r0 patch hash差异与同基线应用结果

本说明补充修正先前给出的 `D:\temp\...r0-apply.patch`（SHA `4b208cc745f8d3fb153cb5dff65c92008d928bc38c06ae12acc559659a6258cb`）与本目录归档 `candidate-r0.patch`（SHA `c1bab0ae9d94c7d428ffa436934c9cee91f51e94c8461e23d20f5a56269004f9`）为何不同，以及相同基线上的逐文件结果。没有修改主仓生产文件。

## 差异原因

- 两个 patch 都由同一 r0 输入源码生成。Store 基线原始 SHA 为 `dba2989252db76fe010fbee7caacdcdba34a9b951e3702724156482b67fae826`。
- `4b208c…` 是以文本模式 `Path.read_text()` 读取源码后生成的 diff；Python 将 CRLF/LF 统一为 LF，因此 patch 只表达文本行差异，不表达原始换行形式。该 patch 63,362 bytes。
- `c1bab0…` 是从原始 bytes 解码后保留每行 EOL 生成的 diff；patch 明确包含 Store 整体换行变化。它是 219,334 bytes。基线 Store 含 15,583 个 CRLF 和 1,462 个 lone LF；候选 Store 为 17,402 个 CRLF、无 lone LF。候选 Store 文本是在候选构造时整文件归一成 CRLF，因此保留 EOL 的 patch 大得多。
- 两者在把应用结果的 CRLF/LF 统一为 LF 后，三文件逐字节归一化内容相同；其差异来自 EOL，不是逻辑源码差异。

## 同一基线逐 patch 重放

每个重放都在独立新目录复制同一个冻结 base Store 文件，核对 base SHA，再 `git init`。完整命令和每个目标文件 hash 在 `patch-format-replay.output.txt` 中；该 log SHA-256 为 `a07706d8eef2779458b2a0c8f9e25283c9f5aa0ee0a6b10308e7459c1dcda916`。

- `4b208c…` + `git -c core.autocrlf=true apply --whitespace=nowarn --check/apply`：检查/应用均 exit 0。Store 和测试文件与候选 SHA 完全一致；新增 actor module 被工作树转换成 CRLF，结果 SHA `c80b1e934dc097ebfce2ca83a1bc1dc78eb2d76b3c6b3fed7c18ab5ebeb4299a`，候选 LF 文件 SHA 为 `e0d3147ec7ce867ec96f29e5dc3e8c4a9343b6ef2845b03e712a7676c9c55a48`。三者换行归一后相同，但 actor module **原始字节不相同**。
- `4b208c…` + `core.autocrlf=false`：`git apply --check` exit 1，报 `backtrader/stores/btapistore.py:36` patch does not apply。
- `c1bab0…` + `core.autocrlf=true`：检查/应用均 exit 0，三个输出文件 SHA 均与候选完全一致。
- `c1bab0…` + `core.autocrlf=false`：检查/应用均 exit 0，三个输出文件 SHA 也均与候选完全一致。

结论：两个 patch 的规范化文本改动相同，但它们不能不加条件地称为字节级等价。`4b208c…` 在 autocrlf=false 下不能应用；autocrlf=true 时 actor module 的换行被转换、文件 SHA 不同。目录内 `candidate-r0.patch`（`c1bab0…`）是可复现冻结文件字节的版本，以上两种 autocrlf 设置都已验证三文件 exact hash。
