# Iteration 41 — 000 三场所穿透认证最终交付记录（2026-10-09）

**结论（用户已接受）**：三场所 99 例 = **98 PASS / 1 BLOCKED（带完整证据与零改动翻转路径）**；
可选组件 16 拓扑 = **16/16 真实通过**；本轮同时完成迭代41方案的三件套快速通道修订（v2）。
用户于 2026-10-09 明确接受 98/99 作为最终交付，EM01 的受限密钥路径保留为将来可选翻转。

## 1. 逐场所结果

| 场所 | PASS | BLOCKED | 说明 |
| --- | --- | --- | --- |
| SimNow（33） | 33 | 0 | 真实报撤单/成交/平仓；操作员授权场方登出（ReqUserLogout）；标准引擎真实资金不足拒绝（error 31） |
| OKX（33） | 33 | 0 | 含 51008 保证金拒绝、价格带拒绝（/public/price-limit）、凭证层鉴权丢失/恢复 |
| Binance（33） | 32 | 1 | 仅 EM01：Demo 密钥具备持仓模式权限 |
| Optional16 | 16/16 | — | binance C01+T03 × 16 组合真实运行 + 网关能力验收 |

## 2. 唯一 BLOCKED（EM01）的证据与翻转路径

- 证据：`r21-case-evidence/binance/EM01__*_BLOCKED.json` — 持仓模式切换探测成功、模式已恢复、
  `permission_restriction_not_producible_on_demo_key`。
- 翻转：把一枚受限权限 Demo 密钥的 `BINANCE_DEMO_RESTRICTED_API_KEY/SECRET` 加入 `.env`，
  EM01 自动改用受限密钥探测（代码路径 `b89539a5` 已就绪并干跑验证），无需其他改动。

## 3. 验收物（全部在 dev，均已提交）

| 交付物 | 位置 / 提交 |
| --- | --- |
| 方案修订 v2（行业实践对照 + 快速通道） | `000三场所-三件套快速通道-v2-2026-10-09.md`（`285aac68`，后多次回填） |
| r21 验收快照（99 份证据 SHA-256 + 归档） | `evidence/iteration41-three-venue-99-case-acceptance-tracking-r21-2026-10-09.{json,md}` + `evidence/r21-case-evidence/`（`1048cdd4`/`0b36063e`） |
| 三件套用例（99 个目录） | `binance/okx/simnow_penetration/cases/<ID>/{config.yaml,<ID>_strategy.py,run.py}`（`8f668fca`/`595daa04`/`8f721384`/`3bf6a37d`/`b8d492f5`） |
| certlib 最小公共层（每场所） | `*/certlib/`（同上提交链） |
| optional16（规格/网关/组件/矩阵） | `examples/000_live_certification/optional16/`（`fadcfb81`/`75993720`）；矩阵 `acceptance-matrix.json`（live，16/16）；能力 `gateway-capability.json`（PASS） |
| SDK 窄口径 SimNow 写入准入 | bt_api_ctp `a497bab`；SDK 父仓 gitlink `7312e718` |
| 证据化翻转轮 | EM03 场方登出 `9ce049ea`；E01 标准引擎 `1048cdd4`；EM01 就绪 `b89539a5` |

## 4. 运维与工程发现（供后续复用）

- SimNow 标准前置（3000x）仅在交易时段（如夜盘 21:00–23:00 北京）TCP 可达；7x24 前置常时可达。
- SimNow 7x24 引擎：持续撮合、不冻结挂单保证金、不校验资金；标准引擎：真实冻结与资金校验。
- 受理判定以场内侧订单查询为准（OnRspOrderInsert 回报可能缺失）；OrderRef 需时间戳唯一。
- OKX Demo：价格带实测约 ±0.5%（用 /public/price-limit 取带）；下单端点偶发 50013（同 clOrdId 幂等重试）。
- Binance Demo：本机时钟慢约 8.8s（服务器时偏补偿必需）；双向持仓模式。
- optional16 组件为 binance 参考接线；OKX/SimNow 组件挂载需"按场所订单参数翻译层"，明确不在本轮范围。

## 5. 快照完整性

r21 快照记录每例证据（现场文件 + 归档副本）的 SHA-256；独立抽样 13 例（含 E01/EM03）复算
**0 处不符**；矩阵与能力记录均为 live 模式、状态与提交内容一致。
