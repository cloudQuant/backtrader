# 2026-09-16 本地原始证据销毁记录

> 状态：`LOCAL_RAW_EVIDENCE_DESTROYED`
> 范围：`.git/iter21-evidence/`（整目录）
> 结论影响：无。既有结论不变，制品认定依据改为已入库的 SHA-256 摘要

## 1. 处置决定与理由

`.git/iter21-evidence/` 曾作为本迭代的本地原始证据目录。该位置不合适：

1. `.git/` 不是证据仓库。位于 `.git/` 内部的文件既不属于 tracked 也不属于 ignored，
   `git status` 不会提示其存在或变化，版本控制无法保护、审计或迁移它们；常规清理
   （如 `make clean`）也只会清掉里面的 `__pycache__`，主体长期滞留。
2. 该目录含明文凭据与私钥（见第 4 节），不应驻留在任何会被整体打包、复制或备份的位置。
3. 目录主体是从已记录构建输入派生的安装副本与二进制（`wheels/`、`isolated-site*/`、
   `installed*/`、`*.pkl`、`*.jsonl`），占体积绝大部分，可由已固化的 hash 与构建命令重新确认。

处置方式：**整目录销毁，不做迁移**。认定依据回归为已入库文档中固化的 SHA-256 摘要。

## 2. 销毁清单（2026-09-16 记录）

合计 372.9 MiB / 12,419 个文件。

| 顶层条目 | 大小 | 文件数 | 性质 |
|---|---|---|---|
| `2026-09-08-final/` | 178M | 6,610 | 收尾轮轮子、隔离安装副本与 replay 收据 |
| `2026-09-08-cross-venue-layer-v7/` | 53M | 1,916 | 当前 G3 收据对应 epoch |
| `2026-09-08-cross-venue-layer-v6/` | 53M | 1,908 | v6 epoch |
| `2026-09-08-cross-venue-layer-v5/` | 52M | 1,900 | 已拒绝 epoch |
| `public-l2-capture.jsonl` / `-first.jsonl` | 15M / 14M | 2 | 公开 L2 采集原始数据 |
| `public-l2-v2-holdout.aborted-before-freeze.jsonl` | 5.2M | 1 | 冻结前中止的 holdout 采集 |
| `assets/` | 724K | 41 | 用户资产副本（含 `.env`） |
| 其余根级脚本、JSON 收据与 data-card | 约 1.3M | 约 50 | 采集/校准/经济屏脚本与结构化结果 |

## 3. 认定依据

销毁前已交叉核对：磁盘上 v6、v7 的 `backtrader-1.3.0-py3-none-any.whl` 实际 SHA-256 与
对应 receipt 记录逐字节一致，说明已入库摘要忠实反映被销毁制品。

**仍可验证（不依赖本地原始目录）**

- v6 五 wheel SHA-256：见 `evidence/2026-09-08-v6-build-install-receipt.md` 第 2 节。
- v7 五 wheel SHA-256：见 `evidence/2026-09-08-v7-build-install-receipt.md` 第 2 节。
- candidate manifest SHA-256 `ace39424097ad7667034b0cac7feaeeebc7dbe25ba1b37ec3c30be6ccaf96f94`：
  见 `evidence/2026-09-08-v7-build-install-receipt.md` 第 1 节。
- 基线冻结的 branch/HEAD 文字记录：见 `evidence/G0-document-gate.md`。

**不再可验证**

- 无法再对 wheel 重新计算 SHA-256，也无法重跑 `unzip -l` 内容断言。制品认定自此为
  **hash 冻结**，而非可复算。若后续需要可复算的制品证据，应在受版本控制的位置重新
  构建并重新固化摘要，不再使用 `.git/`。
- `baseline-manifest.json`（销毁时点 SHA-256
  `1bbe3299984b7620eaf3f79b24f25d29ea4ac32f8c775754de8ca03e99ed8986`）中的
  status / diff / name-status / stat 明细已不可查，仅保留上述存在性摘要。

## 4. 已销毁的凭据与私钥 — 需轮换

以下文件随目录一并销毁。销毁本身不构成凭据失效，**仍需在相关平台侧轮换或重新签发**：

| 文件 | 销毁时点 SHA-256 | 后续动作 |
|---|---|---|
| `assets/.env`（`OKX_DEMO_API_KEY/SECRET/PASSPHRASE`、`BINANCE_DEMO_API_KEY/SECRET`） | `32ecf713a070ed99c13bbc6d4abe6c681592fe879af6f2c2c7cd1780554ede53` | 5 项 demo 凭据应在对应平台轮换 |
| `iter21-demo-approval-private.pem`（Ed25519） | `9ea99f57e0dbb783d6c6de1417e07804dacc0e71e11dd371cb18541941d66e7a` | demo 审批签名私钥应重新签发；旧密钥作废 |
| `credential-migration.json` | `72627efe824624b9d1ee3c7ad87f75d7d6908f24f9c4c28b74b8b7a5ac0af140` | 迁移记录，无独立动作 |

在凭据完成轮换前，不得依据本迭代结论启用任何 demo 写入路径。两候选的
`RESEARCH_REJECTED_DEMO_PROHIBITED` 状态本就禁止 demo 下单，本记录不放宽该限制。

## 5. 对既有结论的影响

- `G0 PASS`、`G3_ARTIFACT_CONSUMER_PASS`、candidate
  `RESEARCH_REJECTED_DEMO_PROHIBITED`、生产阻断状态均**不因本次销毁而改变**。
- 销毁的是本地原始副本，不是收据本身；收据与摘要仍受版本控制。
- 后续迭代不应再将证据写入 `.git/`。可入库证据放 `evidence/`；体积大且需保留的
  原始数据应放在仓库外的受控位置，并在收据中记录路径、hash 与保留期限。
