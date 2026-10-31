# 迭代 52：SimNow registered-sim paper representative 往返（2026-10-31）

- 仓库/分支：Backtrader `dev`（本记录提交）；runtime/SDK 无本轮新改动
- 证据等级：SOURCE + FAKE（20 项 SimNow 适配测试）+ **真实 SimNow registered-sim paper**（preflight、1 手开/平仓、独立撤单处置）
- 不改变：生产账户写入未授权；99 案与 Optional16 历史状态不改写；旧 runtime 未退役
- 来源更正：Store `poll_execution_maintenance`/`_sdk_event_drain_lock` 的源码提交为 `c9dcb6742`（早先 `3dcfca0fe` 的提交信息提到该能力，但该文件未被暂存；已由该 follow-up 补齐）

## 1. 交付

新增/修改（052 leaf）：

| 文件 | 行数（非空） | 职责 |
| --- | --- | --- |
| `simnow_paper.py` | 798 | 复用 013_3 `simnow_direct` 的 Store/Wrapper（按路径加载），提供 runtime 所需 readiness/instrument/reconcile/arm/disarm 表面 |
| `simnow_runner.py` | 429 | 私有 `ctp:` 块读取、front 选择、凭据按名解析、SimNow 会话构建与证据 |
| `paper_common.py` | 83 | 凭据读取、grant、策略参数、证据写入、摘要 |
| `run.py` | 350 | Binance/OKX 原路径 + SIMNOW 分支惰性调用 |
| `config.simnow.yaml` | 69 | schema-v2 paper 模板（SA701/CZCE，1 手，GFD，marketable 50 bps 内） |
| `tests/unit/test_iteration52_simnow_paper.py` | 333 | 20 项 fake 合同测试（缺 front/SDK/登录/账户/arm、freeze/disarm、凭据脱敏） |

该适配通过 importlib 按路径加载 `examples/unified/013_3_.../simnow_direct.py`；它是 checkout-bound 示例，未复制 846 行模块，旧 013_3/014/028 未改动。后续应将 registered-sim 组件迁入明确组件 owner。

## 2. 真实 SimNow 结果

### 2.1 只读预检（PASS）

- 证据：`examples/unified/052_provider_demo_roundtrip/evidence/20261031T022927Z_052_simnow_demo_roundtrip_COMPLETED.json`
- front 选择：index 3，MD/TD 各 3/3，whitelisted；instrument `SA701`，exchange `CZCE`。
- 登录：trading_day `20261029`，read_only_ready/trading_ready 均为 true，connection_generation 1。
- arm 1 次；账户 1 行、合约 93 行、持仓 0、委托 0。
- 停止：`disarm / simnow_paper_clean_stop`，final 0 持仓/0 委托，unknown 0。

### 2.2 首次 GTC 挂/撤尝试（BLOCKED/UNKNOWN，已安全收尾）

- run `i52-simnow-paper-20261031T023411Z-a871a2b3`，证据 `…023539Z_…_UNKNOWN.json`。
- 订单：OrderRef `1`，OrderSysID `21766`，SA701 买 1 手；策略收到本地 Canceled，但 **交易所查询仍为 OrderStatus 3（NoTradeQueueing）**，0 成交、0 持仓。
- 适配器 stop 看到 1 条活动订单行，按设计 `freeze`，未伪报成功。
- 独立 000 SimNow certlib 只读查询确认 OrderStatus 3；随后 certlib `arm + cancel_order`（request_id 5，submit_code 0）将订单变为 **OrderStatus 5（Canceled）**，VolumeTraded 0，positions []。
- 根因：SDK `TraderClient.next_order_ref()` 为**会话内**递增（新会话从 1 开始），交易所保留跨会话订单历史；legacy Store cancel 仅按 OrderRef、不带 typed OrderSysID/Front/Session。typed cancel 路径要求 managed decision journal，当前 direct paper 会话未提供。适配器的 freeze 是正确行为。

### 2.2b 第二次 GTC 撤单尝试与唯一 OrderRef 试验（仍 BLOCKED）

- run `i52-simnow-paper-20261031T030449Z-676392da`，订单 OrderRef `1` / OrderSysID `24667` / OrderStatus 3；策略本地 Canceled，适配器 stop 再次 freeze。
- 尝试在适配器启动后把 wrapper client 的 `_max_order_ref` 播种为 12 位时间戳基数；但 broker `order.info` 仍报告 `ctp_order_ref: "1"` 且无 `external_order_id`，说明 registered-sim Broker 的 OrderRef 投影并未使用该 client 计数器；该未验证试验已回退，不提交。
- 独立 certlib 以 OrderSysID `24667` 撤单成功（OrderStatus 5）。最终账户查询：6 笔订单全部终态（`21766`/`24667` Canceled；`24596`/`24597`、`24215`/`24218` Filled），positions []，无活动委托。
- 结论：需修复 Broker/Store 的 registered-sim OrderRef/OrderSysID 投影或接入 typed cancel target/journal；仅修改 client 计数器不足。

### 2.3 最终接受运行（PASS：marketable 开仓 + reduce-only 平仓）

- **最终源码**（helper 拆分后）run `i52-simnow-paper-20261031T025819Z-cd4fd242`，证据
  `evidence/20261031T030042Z_052_simnow_demo_roundtrip_PASS.json`
  （SHA-256 `894f3b1db09f6cb1a736f8dbfdc44b898e8429c6ec0304bf005c11f837d4ab71`）。
- 配置：`offset_bps=-50`（可成交买价）、GFD、1 手、`notional_usdt=25000`（换算 1 手）。
- 开仓 Completed：+1 手，成交价 982.0；平仓 Completed：-1 手，成交价 975.0；手续费字段 0.0（CTP fee 未投影，见边界）。
- 拆分前同一行为运行 `i52-simnow-paper-20261031T024939Z-3d632dd5`（证据 `025143Z`，SHA-256 `133f7d08…`）亦 PASS；最终证据采用拆分后源码运行。
- 独立 000 certlib 只读复核：positions []；账户 flat。
- stop：`disarm / simnow_paper_clean_stop`，final 0 持仓/0 委托，unknown 0；store summary active 0/unknown []/evidence_complete true；shutdown PASS。
- 独立只读查询：positions []；order query 仅显示旧会话 OrderRef 1 的 Canceled 行（新会话订单行受跨会话 OrderRef/查询去重限制未显示），无活动持仓或活动委托证据。账户最终为 flat。
- 最终源码行数：run.py 350、paper_common 110、simnow_runner 429、simnow_paper 786、strategy 240；均 ≤800 非空行。

## 3. 测试

- `tests/unit/test_iteration52_simnow_paper.py`：**20 passed**
- `tests/unit/test_iteration52_provider_demo_strategy.py`：**3 passed**
- `python -m py_compile`：run.py / paper_common.py / simnow_runner.py / simnow_paper.py / 测试
- 行数：run.py 350、paper_common 83、simnow_runner 429、simnow_paper 798、strategy 240、config 69、entry_tier 98，均 ≤800 非空行。
- dry：Binance/OKX/SimNow 三配置 exit 0；`--live` 无写授权 exit 2；SimNow 私有配置缺失时 BLOCKED 且不读 `.env`。

## 4. 边界与下一步

- SimNow 真实结果只覆盖 **1 手 SA701 开/平仓**；撤单路径尚未在新 runtime 中验收（见 §2.2），不得把本次 PASS 写成 SimNow 撤单通过。
- 交易所费用未投影（commission 0.0）；F08 手续费证据仍待 CTP fee/成交回报补全。
- `simnow_direct` 按 checkout 路径加载；复制出去需显式提供 helper 或后续组件化。
- 下一步：修复 registered-sim cancel identity（唯一 OrderRef 或 typed target/Managed journal），补 SimNow 撤单与 fee 证据；随后 028 迁移、A0 收敛、R10。
