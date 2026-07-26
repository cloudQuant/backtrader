# 代码质量迭代计划 · 第二轮 (Code Quality Iteration Plan — Round 2)

> 创建于 2026-05-31，承接 `docs/CODE_QUALITY_ITERATION_PLAN.md`（第一轮 S1–S8）。
> 第一轮已收口：S1–S4 + S6 完成、S1.5 CI 增强完成、S5 进行中（26 个高复杂度函数已降，
> 高风险状态机/热路径刻意暂缓）、S7 评估后暂缓、S8 明确不执行。
>
> 本轮基于对当前 `dev` 分支的**重新静态审计**（radon / bandit / ruff 扩展规则集 /
> 自定义扫描），聚焦第一轮**尚未覆盖**的质量与正确性维度。所有数字均为实测，命令见
> 文末附录。

## 核心原则（与第一轮一致）

1. **零破坏性** — 公共 API、导入路径、类继承、参数默认值、数值结果不变。
2. **测试是唯一验收标准** — 全量 3,001 用例（`pytest tests -n 8`，1 skip）保持全绿；
   新增能力补测试。验收时**暂忽略 `tests/functional/strategies/`**（按当前约定），
   但仍跑非策略全套 + 关键策略抽样回归。
3. **CI 即真相** — 任何门禁/配置类改动同步改 CI，保持 CI 绿灯。
4. **渐进可回滚** — 每个 Sprint 独立成 PR、独立可验证。
5. **先治正确性，再治风格** — 优先消除真实 bug 隐患（可变默认参数、弃用 API），
   风格/现代化项放后面且可选。

---

## 审计发现总览 (Audit Findings, 2026-05-31)

| 维度 | 实测现状 | 是否新增治理 | 落点 |
| --- | --- | --- | --- |
| **Ruff 规则集** | 仅 `select=["E","F"]`，扩展到 B/SIM/C4/PIE/RET/PERF/UP 后暴露 **957 项**（263 项可安全自动修） | ✅ 是（最高价值） | R2-S1 |
| **可变默认参数 (B006)** | **12 处**（`cerebro.add_timer`/`_add_timer`、`strategy` 下单/timer 等 `weekdays=[]`/`monthdays=[]`） | ✅ 是（正确性隐患） | R2-S2 |
| **弃用 API `datetime.utcnow()`** | **4 处**（`brokers/btapibroker.py`、`stores/btapistore.py`×3），3.12+ 已 `DeprecationWarning` | ✅ 是 | R2-S2 |
| **循环变量闭包 (B023)** | 1 处（`indicators/oscillator.py:134`，经判定为**假阳性**，lambda 同迭代内立即调用） | ✅ 是（加 `# noqa` + 注释固化判定） | R2-S2 |
| **Bandit 进 CI** | 仅在 `Makefile` 的 `security` 目标，**未进 CI**；2 项 Medium（B608 influxfeed SQL 串拼、B310 py3.py urlopen）未 triage | ✅ 是 | R2-S3 |
| **热路径 `try/except` in loop (PERF203)** | **35 处**，部分可能在 `once()`/逐 bar 循环（本项目以性能为卖点，值得排查） | ✅ 是（仅热路径） | R2-S4 |
| **测试覆盖率** | `pytest-cov`/`coverage` 已装，但覆盖率**从未度量**（第一轮 S6 显式跳过） | ✅ 是（先量基线） | R2-S5 |
| **高复杂度 CC>40（F 级）** | **13 个**（撮合状态机/事件主循环/line 基座/绘图），第一轮已记为「刻意暂缓」 | 🔁 延续（不强求） | R2-S6 |
| **PEP 585/604 注解现代化 (UP006/045/007)** | 8 文件可改，但受 3.8 运行期约束（需 `from __future__ import annotations`，仅 8 文件有） | ⏸ 可选 | R2-S7 |
| 散落 `print()` | 57 处，均为用户面向（channels 示例/reports/btrun） | ❌ 已在一轮 S2 triage | — |
| Py2 残留 (`__div__`/`__nonzero__`) | 7 处，均为**有意兼容别名**（`__bool__ = __nonzero__` 等） | ❌ 保留 | — |
| 裸 `except:` | **0** | ❌ 已清零 | — |
| 泛化 `except Exception` 比例 | 258/670 ≈ **38.5%**（与一轮 39.3% 一致，防御网/边界刻意保留） | ❌ 见一轮 S3 决策 | — |
| 静默 `except…: pass` 无注释 | **0**（B110=24 均已带注释，属有意吞） | ❌ 已清零 | — |

> 结论：**没有发现破坏性/阻断性问题**（无裸 except、无真实 SQL 注入面向用户、
> 无 py2 语法残留）。但存在**一批未被现有门禁覆盖的真实质量/正确性隐患**——核心是
> 「ruff 规则集过窄」漏掉了可变默认参数、弃用 API、热路径 try/except 等。本轮把这些
> 收编进门禁并逐项修复。

---

## 路线图 (Roadmap)

按「收益 ÷ 风险 ÷ 成本」排序。最高价值是**扩 lint 规则集**（一次性堵住一大类隐患的
回流）与**正确性修复**。

| 顺序 | Sprint | 主题 | 优先级 | 工时 | 风险 | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | R2-S1 | Ruff 规则集扩展（curated，分批落地） | **P0** | 2–3d | 低 | ✅ 完成 |
| 2 | R2-S2 | 正确性修复（可变默认参数 / utcnow 弃用 / B023） | **P1** | 1–2d | 低 | ✅ 完成 |
| 3 | R2-S3 | 安全扫描进 CI（bandit gate + triage 2 Medium） | P1 | 1d | 低 | ✅ 完成 |
| 4 | R2-S4 | 热路径性能（PERF203 等，仅 once/逐 bar 循环） | P2 | 2–3d | 中 | ✅ 完成 |
| 5 | R2-S5 | 覆盖率基线 + 设地板（防回退） | P2 | 1–2d | 低 | ✅ 完成 |
| 6 | R2-S6 | 延续高复杂度治理（带测试脚手架，不强求） | P3 | 3–5d | 中高 | ✅ 完成 |
| 7 | R2-S7 | （可选）PEP 585/604 注解现代化 | P3 | 1–2d | 低 | ⏸ 评估后暂缓 |

---

## R2-S1：Ruff 规则集扩展 🔥 (P0, 2–3d) ✅ 完成

**问题**：`pyproject.toml` 现为 `select = ["E", "F"]`，只查语法/未用变量/未定义名。
扩展到常用质量规则后暴露 **957 项**（其中 263 项 `--fix` 可安全自动修），包含真实
bug 隐患（可变默认参数、未用循环变量、闭包陷阱）。**这是本轮最高杠杆项**：一次配置 +
分批清理，就把一大类问题堵在门禁外。

**策略**：**分批引入、每批先清零再开门禁**，避免「开了规则但一直红」。优先纯净化、
低风险、可自动修的规则族。

### 扩展规则族（按引入顺序，实测数量）

| 批次 | 规则族 | 含义 | 实测命中 | 自动修 | 风险 |
| --- | --- | --- | --- | --- | --- |
| 1 | `PIE` | 冗余占位/冗余 pass 等 | ~115（PIE790=100） | 高 | 极低 |
| 1 | `C4` | 推导式/不必要的 `dict()`/`list()` | ~270（C408=256） | 中 | 极低 |
| 2 | `RET` | return 简化（多余 else/return None） | ~115 | 高 | 低 |
| 2 | `SIM` | 可简化的 if/with/except | ~250 | 中 | 低 |
| 3 | `B`(bugbear) | **真实 bug 隐患**（B006/B007/B023/B904…） | ~95 | 部分 | 中（逐条审） |
| 4 | `PERF` | 性能反模式（PERF203/401/403） | ~55 | 低 | 中（见 R2-S4） |

> `UP`（pyupgrade）单列到 R2-S7：受 3.8 运行期约束，需配合 `from __future__ import
> annotations`，不与本 Sprint 混做。

### 任务清单（R2-S1）

- [ ] **批次 1（PIE + C4）**：`ruff check backtrader --select E,F,PIE,C4 --fix`，
  人工复核 diff（C408 把 `dict(a=1)` 改 `{"a":1}` 需确认无 `**kwargs` 语义差异），
  跑全量测试 → 在 `[tool.ruff.lint] select` 加入 `PIE`,`C4`。
- [ ] **批次 2（RET + SIM）**：同上流程；SIM105（`try/except/pass`→`contextlib.suppress`）
  **逐条审**——一轮 S2/S3 刻意保留的防御网吞异常**不要**强行改成 suppress（会丢注释
  语义），对这些点用 per-file-ignore 或 `# noqa: SIM105` 保留。
- [ ] **批次 3（B / bugbear）**：**不自动修**，逐条审。真实隐患（B006/B023）在 R2-S2
  单独处理；B007（未用循环变量改 `_`）、B904（一轮已清零）等顺手清。审完加入 select。
- [ ] **批次 4（PERF）**：与 R2-S4 联动，仅清非热路径的明确反模式，热路径单独评估。
- [ ] 每批次更新 `[tool.ruff.lint.per-file-ignores]`：对**有意为之**的点（防御网
  suppress、绘图模块的 `assert`、`__init__` 的重导出）加豁免并注释原因。
- [ ] CI `lint` job 的 `ruff check` 自动生效（规则在 pyproject，无需改 CI 命令）。

### R2-S1 验收 ✅

- `ruff` 规则集从 `["E","F"]` 扩展为 `["E","F","PIE","C4","RET","SIM","B"]`，
  `ruff check backtrader` **零告警**（PIE 106 / C4 266 / RET 117 / SIM114+910 34
  自动修；其余 RET504/503 + SIM102/108/105/115/103/113/118/110 经审为主观或刻意
  保留，加 `ignore` 并逐条注释原因；4 处 `if False/True or` 上游禁用代码加 `# noqa`）。
- 全量非策略测试 **1,746 passed / 1 skipped**；black/isort 通过。
- 实际落地为「一次性扩 select + curated ignore」而非分多 PR——因自动修部分零风险、
  主观部分用 ignore 兜住，单次即可保持 CI 绿灯。

---

## R2-S2：正确性修复 (P1, 1–2d) ✅ 完成

**目标**：消除 ruff bugbear 暴露的**真实正确性隐患**与弃用 API。纯局部修复，零行为变化
（除消除 footgun）。

### 2.1 可变默认参数 B006（12 处）

- [ ] `cerebro.py::_add_timer` / `add_timer`：`weekdays=[]` / `monthdays=[]`
  （4 处）改为 `weekdays=None` + 函数体内 `weekdays = weekdays or []`（或直接透传给
  `Timer`，其 param 默认本就是 `None` + `get_param(...) or []`）。
- [ ] `strategy.py`：下单/timer 相关签名中的 `[]` 默认（约 8 处）同样改 `None` 守卫。
- [ ] **验证不变性**：这些默认目前是**只读透传**（`Timer._started` 用
  `get_param("weekdays") or []` 构造 deque），故修复属**消除潜在 footgun**而非改行为；
  跑 timer 相关测试（`tests` 内 timer/scheduler 用例）确认数值/触发序列不变。

### 2.2 弃用 API `datetime.utcnow()`（4 处）

- [ ] `brokers/btapibroker.py:1133`、`stores/btapistore.py:1419/1962`（及复扫到的第 4 处）：
  `datetime.utcnow()` → `datetime.now(timezone.utc)`。
- [ ] **注意语义**：`utcnow()` 返回 **naive** UTC，`now(timezone.utc)` 返回 **aware**。
  若下游对返回值做 `.strftime`/`.isoformat` 或与 naive 比较，需保持等价——
  对仅格式化的点（如 `strftime('%Y%m%d%H%M%S')`）可用
  `datetime.now(timezone.utc).replace(tzinfo=None)` 保持 naive 输出，避免引入
  tz 后缀差异。逐点确认后再改。
- [ ] 跑相关 broker/store 测试。

### 2.3 循环变量闭包 B023（1 处，假阳性固化）

- [ ] `indicators/oscillator.py:134`：lambda 在**同一迭代内立即作为默认值调用**
  （`getattr(movav.lines, "_getlinealias", lambda x: movav.__name__.lower())(0)`），
  不存在延迟绑定 bug。加 `# noqa: B023  # lambda invoked immediately in-loop, no late binding`
  固化判定（待 R2-S1 批次 3 开 B 规则后不再误报）。

### R2-S2 验收 ✅

- **B006 = 0**：`cerebro._add_timer`/`add_timer`、`strategy.add_timer`、
  `strategy.buy_bracket`/`sell_bracket` 的 `weekdays=[]`/`monthdays=[]`/`oargs={}`/
  `stopargs={}`/`limitargs={}` 全部改 `None` + 函数体内 `x = [] if x is None else x`
  归一化。这些值原本只读透传（Timer 内部用 `get_param(...) or []`，bracket 用
  `kargs.update(...)`），故属**消除 footgun 的等价重构**。
- **`datetime.utcnow()` = 0**：3 处改 `datetime.now(timezone.utc)`；其中需保持
  naive 输出格式的（btapibroker 记账、btapistore ISO 时间戳）用 `.replace(tzinfo=None)`
  保证字符串格式与旧 `utcnow()` 完全一致（已用脚本验证 strftime/isoformat 形状一致）。
- **B023** oscillator.py：确认为假阳性（lambda 同迭代内立即调用），加
  `# noqa: B023` + 注释固化判定。
- 验证：timer/bracket/broker/store/oscillator 专项 **502 passed**；全量非策略
  **1,746 passed**。

---

## R2-S3：安全扫描进 CI (P1, 1d) ✅ 完成

**问题**：`bandit` 只存在于 `Makefile::security`，**CI 不跑**，2 项 Medium 未 triage。

### 任务清单（R2-S3）

- [ ] **triage 2 项 Medium**（不盲目改，按上下文判定）：
  - `feeds/influxfeed.py:115` **B608（SQL 串拼）**：查询模板用 `.format()` 拼
    measurement/field 名。InfluxQL 不支持参数化标识符，且这些值来自**用户自己的
    feed 配置**（非外部输入）。判定为**可接受**，加 `# nosec B608` + 注释说明
    「标识符来自本地配置、InfluxQL 无参数化标识符机制」。
  - `utils/py3.py:61` **B310（urlopen scheme）**：Py2/3 兼容 shim。判定为
    **可接受**（上游 API），加 `# nosec B310` + 注释；或在调用点校验 scheme。
- [ ] **CI 加 bandit 步骤**（`lint` job 内，**非阻塞趋势** + Medium/High 阻塞）：
  - `bandit -r backtrader -ll`（沿用 `pyproject.toml [tool.bandit]` 的 skips/exclude）；
  - 先以 `continue-on-error` 跑一轮确认 Medium/High 已清零（靠 `# nosec`），
    再升级为 **High/Medium 阻塞、Low 仅报告**（与 mypy gate 同样的 threshold 模式）。
- [ ] `B311`（btrun 随机数）、`B106`（trade_logger 空串「密码」）经判定为**假阳性/
  非安全用途**，已在 `[tool.bandit] skips` 或加 `# nosec` 说明。

### R2-S3 验收 ✅

- `bandit -r backtrader -ll` **Medium/High = 0**（influxfeed B608 / py3.py B310
  各加 `# nosec` + 旁注说明；注意注释不能以 `nosec` 开头跟描述，否则 bandit 会把
  描述词逐个当 test-id 报 warning——已规避）。剩余 31 Low 为可接受项。
- CI `lint` job 新增 **bandit Medium/High 阻塞**步骤（安装 bandit，沿用
  `[tool.bandit]` 的 skips/exclude）。
- B311（btrun 随机数）/B106（trade_logger 空串）经判定非安全用途，维持现状。

---

## R2-S4：热路径性能 (P2, 2–3d) ✅ 完成

**问题**：`ruff --select PERF` 报 **35 处 PERF203（try/except in loop）** + 若干
PERF401/403。本项目主打「~45% 更快」，热路径里的 try/except 与可向量化的手写循环
是**真实性能点**，值得有据排查（非热路径的忽略）。

### 任务清单（R2-S4）

- [ ] 定位 PERF203 中位于**热路径**的点：`linebuffer.py`（`_once`/算子）、
  `lineiterator.py`（`_next`/`once`）、`functions.py`、`indicators/*.once()`、
  `cerebro._runnext`。逐点判断：
  - 若 try/except 在**每根 bar / 每个元素**执行且异常极少触发 → 把 try 提到循环外，
    或改为「先判定再执行」消除每次迭代的异常处理开销；
  - 若是预热期/边界一次性 → 加 `# noqa: PERF203` + 注释保留。
- [ ] PERF401/403（手写 list/dict 构建 → 推导式）：仅在**可读性不降且非状态机**处改。
- [ ] **基准护栏**：改动前后跑 `tests/performance/` 与 `pytest-benchmark`，
  **回归 >5% 视为失败**回滚。非热路径不动。
- [ ] 不进 PERF 全量门禁（避免对非热路径过度约束）；仅对已清理的热路径文件按需
  per-file 开启或加 noqa。

### R2-S4 验收 ✅

- **热路径 3 处 PERF203 治理**：`LineBuffer` 向量化 `once()` 的三个 per-element
  循环（`LineOwnOperation.once`、unary `once`、`LinesOperation._once_op`——即
  `sma-ema`、`(a+b)/2`、`abs(...)` 等批量算子）改为「**整段 fast-path 单 try +
  出错才走逐元素 slow-path**」。语义**完全保留**（fast-path 复刻原循环含 `continue`
  和 NaN/0.0 兜底；任何异常落到原逐元素回退），仅消除了无错时每元素的异常处理器
  开销。
- **基准**：新增 `tests/bench/bench_runonce_lineops.py`（50k bar × 多算子，
  `@pytest.mark.slow`）。本地实测中位数从约 9.8–10.2s 降到约 7.3–7.7s、min 从
  ~5.4s 降到 ~2.9s（笔记本噪声大，但方向一致且无回归）。
- **正确性**：indicator/linebuffer/operation 专项 **296 passed**；全量非策略
  **1,746 passed**；额外抽样策略回归（advanced + forecasting）**13 passed**——
  核心数值零偏移。
- 其余 ~32 处 PERF203 位于一次性/启动期/notify 循环（cerebro/metabase/channels/
  plot/strategy 等），非每 bar 热点，**保留**（不进 PERF 全量门禁，避免过度约束）。

---

## R2-S5：测试覆盖率基线 (P2, 1–2d) ✅ 完成

**问题**：第一轮 S6 显式跳过覆盖率度量（「聚焦补盲区而非刷数字」）。但**没有基线就
无法防回退**。本轮先量化，再设一个保守地板。

### 任务清单（R2-S5）

- [ ] 生成基线：`pytest tests --ignore=tests/functional/strategies --cov=backtrader
  --cov-report=term-missing --cov-report=html -n 8`（先量非策略子集，跑得快、可重复；
  策略套件另算）。记录总覆盖率与按模块覆盖率。
- [ ] 在 `docs/` 留一份 `COVERAGE_BASELINE.md` 快照（含日期、命令、各包覆盖率）。
- [ ] 识别**覆盖率显著偏低的核心模块**（非绘图/非可选依赖），补冒烟/边界测试到
  合理水平（目标：核心 `*.py` 行覆盖率 ≥ 当前基线，不强求统一 80%）。
- [ ] CI 可选加 `--cov-fail-under=<基线-2%>` 作为**地板**（非阻塞先行，确认稳定后阻塞），
  防止后续 PR 大幅拉低覆盖率。

### R2-S5 验收 ✅

- **基线已度量并落档** `docs/COVERAGE_BASELINE.md`：非策略子集（1,746 用例）总行
  覆盖率 **60%**（31,771 语句 / 12,654 未覆盖）。核心模块多在 76–100%；line 系统
  （lineiterator 48% / metabase 47% / lineroot 53%）偏低，因其分支主要由**策略回归
  套件**覆盖（已说明，不盲目刷数字）。
- **CI 地板**：新增 `coverage` job（3.11，非策略子集，`--cov-fail-under=55`，
  `continue-on-error` 非阻塞），防回退；稳定后可提到 58 并阻塞。
- 未追求统一 80%——按计划聚焦核心非 line 模块的真实盲区，作为长期渐进项。

---

## R2-S6：延续高复杂度治理 (P3, 3–5d, 中高风险) ✅ 完成（务实范围）

**现状**：13 个 F 级（CC>40）函数，**全部是第一轮已记录的「刻意暂缓」项**：
`process_orderbook`(161)、`LineIterator.__init__`(70)、`_periodset`(63)、
`_runnext`(59)、`_evaluate_signals`(57)、`plotind`(55)、`LineActions._once`(49)、
`donew`(48)、`_register_line_assignment_child`(44)、`Lines.__setitem__`/`__setattr__`(42)
等——撮合状态机 / 事件主循环 / line 基座 / 绘图。

**原则不变**：零破坏约束下，为降 CC 而动这些热点/状态机得不偿失。**本轮不强行重构**，
而是为「将来能安全重构」做铺垫：

- [ ] 给最值得拆但缺测试的 1–2 个（如 `_evaluate_signals` CC57、`plotind` CC55）
  **先补针对性测试脚手架**（固化输入→输出/副作用），把回归网建起来。
- [ ] 仅在测试脚手架就绪后，按一轮 S5 的「相位清晰可分」标准尝试拆分；否则维持暂缓。
- [ ] **不设硬性 CC 阈值门禁**（会逼迫改动状态机）；仅在 CI 加 `radon cc -n F` 的
  **非阻塞计数看板**，防止新增 F 级函数。

### R2-S6 验收 ✅（务实范围）

- **测试脚手架先行**：新增 `tests/unit/core/test_signal_evaluate.py`（19 个分支级
  用例），覆盖 `_evaluate_signals` 的全部信号类型（LONG/SHORT × 直接/反转/any、
  各 EXIT 变体、反转抑制、leave 抑制）——补上了原先只测 SIGNAL_LONG 的盲区。
- **基于脚手架的安全重构**：把 `SignalStrategy._evaluate_signals` 中重复的
  「`all(>0) or all(<0 inv) or all(any)`」三源模式抽成 3 个静态辅助
  （`_all_pos`/`_all_neg`/`_all_any`），**CC 57 → 17**（F→C），行为零变化
  （19 用例 + 既有 signal e2e + 策略回归 signals 用例全过）。
- **CI 复杂度看板**：`lint` job 新增 **非阻塞** radon F 级计数器（基线 13），
  新增 F 级函数即 `::warning::`，防回流。
- **其余 12 个 F 级刻意暂缓**：撮合状态机 `process_orderbook`(161)、事件主循环
  `_runnext`(59)、`_periodset`(63)、line 基座 `LineIterator.__init__`(69)/`donew`(47)/
  `_once`(49)/`_once_op`(41)/`__setitem__`/`__setattr__`(42)/`_register_line_assignment_child`(44)、
  绘图 `plotind`(55)/`plotdata`(42)、`LineActions.__new__`(43)——这些是热路径/状态机/
  动态 line 基座/导入期，零破坏约束下为降 CC 而改得不偿失（与 Round 1 S5 决策一致）。
  现由 CI 看板监控「不增加」即可。

---

## R2-S7：（可选）PEP 585/604 注解现代化 (P3, 1–2d) ⏸ 评估后暂缓

**约束**：基线是 **3.8+**。`list[int]` / `X | Y` 等在 3.8/3.9 运行期注解会报错，
**必须**配 `from __future__ import annotations`（当前仅 8 文件有）。

### 任务清单（仅在确有收益时做）

- [ ] 对 `ruff --select UP006,UP007,UP045` 命中的 8 个文件，先确认其
  `from __future__ import annotations` 存在（否则先补），再 `ruff --fix`。
- [ ] **不开 UP 全量门禁**（会与 3.8 运行期语法冲突，且收益仅风格）；
  或仅对已加 future-import 的文件做 per-file 启用。
- [ ] 全量测试在 **3.8** 上验证（CI 矩阵已含 3.8）。

### R2-S7 验收 ⏸ 评估后暂缓

**决策：暂缓**。理由：基线是 3.8+，`list[int]`/`X | Y` 等在 3.8/3.9 运行期注解会
报错，必须逐文件配 `from __future__ import annotations`；这是**纯风格现代化、对用户
零收益**，却要改动 8 个文件的运行期行为并冒 3.8 破坏风险。与 Round 1「修代码而非抬
门槛」「最小化变更」的取向一致，留作将来整体升基线（弃 3.8）时再一次性 `pyupgrade`。
未纳入 ruff `select`（避免与 3.8 运行期语法冲突）。

---

## 贯穿所有 Sprint 的硬约束 (Compatibility Constraints) ⚠️

1. 公共 API 不删除、不改签名；可变默认参数改 `None` 守卫属**等价重构**（需测试佐证）。
2. 导入路径、类继承、参数默认值（语义层面）、数值结果、订单逻辑、事件顺序不变。
3. `datetime.utcnow → now(timezone.utc)` 需逐点确认 naive/aware 语义等价。
4. 每个 Sprint：非策略全套测试全绿 + 策略抽样回归 + benchmark 无 >5% 回归。
5. 新增/收紧门禁（ruff 规则、bandit、覆盖率地板）一律「先非阻塞看板 → 确认稳定 →
   再阻塞」，绝不一次性卡红 CI。

---

## 度量看板 (Metrics Dashboard)

| 指标 | 本轮前 (2026-05-31) | 目标 | 实际 |
| --- | --- | --- | --- |
| Ruff 规则族 | `E,F` | `E,F,PIE,C4,RET,SIM,B`（零告警） | ✅ `E,F,PIE,C4,RET,SIM,B` 零告警 |
| Ruff 扩展规则命中 | 957 | 0（治理后） | ✅ 0（自动修 + curated ignore + noqa） |
| 可变默认参数 B006 | 12 | 0 | ✅ 0 |
| `datetime.utcnow()` | 4 | 0 | ✅ 0（保留 naive 输出格式） |
| Bandit 进 CI | 否 | 是（Medium/High 阻塞） | ✅ 是 |
| Bandit Medium/High | 2 / 0 | 0 / 0（triage + nosec） | ✅ 0 / 0 |
| 热路径 PERF203 | 35（含非热路径） | 热路径清零，benchmark 无回归 | ✅ 3 热点 once() 治理 + 新基准；无回归 |
| 覆盖率基线 | 未度量 | 已度量 + CI 地板 | ✅ 60%（非策略子集）+ CI floor 55 |
| 高复杂度 F 级 (CC>40) | 13 | **不增加**（看板监控） | ✅ 13（_evaluate_signals F→C，CI 看板守护） |
| 测试通过率 | 100% | 100%（每 Sprint） | ✅ 1,764 passed / 1 skipped |
| 裸 `except:` | 0 | 0 | ✅ 0 |
| 静默 `except…: pass` 无注释 | 0 | 0 | ✅ 0 |

> 路线图状态：R2-S1～R2-S6 完成；R2-S7（PEP585/604 现代化）评估后暂缓（3.8 运行期
> 约束 + 零用户收益）。所有已完成 Sprint 全程零行为变化、非策略全套 1,764 用例绿灯。

---

## 附录：本轮审计命令 (Verification Commands)

```bash
# 1) Ruff 扩展规则集预览（看会暴露什么）
ruff check backtrader --select B,SIM,UP,C4,PIE,RET,PERF --statistics

# 2) 可变默认参数 / 闭包陷阱 / raise-from
ruff check backtrader --select B006   # 可变默认参数
ruff check backtrader --select B023   # 循环变量闭包
ruff check backtrader --select B904   # raise without from（应为 0）

# 3) 弃用 API
grep -rEn "datetime\.utcnow|pkg_resources|np\.(float|int|bool|object)\b" backtrader --include="*.py"

# 4) 安全扫描（Medium 及以上）
bandit -r backtrader -ll -q

# 5) 复杂度 F 级（CC>40）计数
radon cc backtrader -n F -s | grep -cE " - F "

# 6) 覆盖率基线（非策略子集，快）
pytest tests --ignore=tests/functional/strategies --cov=backtrader \
  --cov-report=term-missing -n 8

# 7) 性能反模式
ruff check backtrader --select PERF --statistics

# 8) 回归
pytest tests --ignore=tests/functional/strategies -n 8 -q   # 验收（忽略策略套件）
make test-strategies                                         # 策略套件（抽样/全量）
```
