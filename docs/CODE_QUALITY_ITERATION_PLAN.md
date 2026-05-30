# 代码质量迭代计划 (Code Quality Iteration Plan)

> 修订版 v2 — 2026-05-30。所有指标已对照当前 `dev` 分支源码**重新核实**（旧版多处
> 数字已过时，见下方「核实与勘误」）。本计划面向 `dev` 分支，目标是在**零破坏性、
> 测试 100% 通过、CI 持续绿灯**的前提下，逐步提升可观测性、健壮性与可维护性。

## 核心原则 (Guiding Principles)

1. **CI 即真相** — 仓库已有 GitHub Actions（`.github/workflows/test.yml`）在
   6 个 Python 版本 × 3 个 OS 上跑 `pytest tests/ -n auto` + `ruff check` +
   `black --check --line-length 100`。**任何变更必须保持 CI 绿灯**，配置类改动要
   同步改 CI，否则等于没做。
2. **日志先行** — 先建立可观测性，再做重构（无日志的重构无法验证回归）。
3. **零破坏性变更** — 公共 API、导入路径、类继承、参数默认值、数值结果必须不变。
4. **测试是唯一验收标准** — 当前 **2,991** 个用例（`pytest tests -n 8`，1 个 skip）
   必须保持全绿；新增能力要补测试。
5. **渐进可回滚** — 每个 Sprint 独立成 PR、独立可验证、可回滚。
6. **先纠矛盾，再加功能** — 优先消除「文档/配置/CI/代码互相打架」这类低成本高收益项。

---

## 核实与勘误 (Verification & Corrections, 2026-05-30)

旧版计划基于一份较早的静态分析，以下指标已与现状不符，已在本版修正：

| 指标 | 旧版数值 | 实测 (2026-05-30) | 说明 |
| --- | --- | --- | --- |
| 测试用例数 | 2,869 | **2,991**（含 1 skip） | 回归测试 inline 后增加 |
| 源码文件 / 行数 | 228 / 79,000 | **228 / 79,116** | ✅ 一致 |
| 静默异常 `except…: pass` | 110 / 21 文件 | **~99 / 18 文件** | 已有若干轮清理，仍需收尾 |
| 非 `__init__` 的 star import | ~50（Sprint 7 重点） | **0** | ✅ 已完成，Sprint 7 降级/删除 |
| star import 总数 | 117 | 117（**全部在 `__init__.py`**） | 属正常导出，保留 |
| eval/exec | 10 | **1** | 旧版高估，几乎无需治理 |
| Ruff 告警 | 63 | **63**（E402:多数 / F811 / F401:8 等） | ✅ 一致，待清 |
| Mypy 错误 | 543 | **543（112 文件 / 228 源文件）** | ✅ 一致 |
| 高复杂度（radon F，CC>40） | — | **14 个**；E(31-40) 13；D(21-30) 55 | 见 Sprint 3 |
| 超大文件 >1000 / >1500 行 | 20 / 12 | **21 / 11** | ✅ 基本一致 |
| 使用 logging 的文件 | 46/228 | **45/228 (~20%)** | ✅ 一致 |

**新发现的关键矛盾（旧版未提及）**：

- **Python 版本三方打架** 🔴
  - `setup.py` classifiers 写 3.8–3.13，但**没有 `python_requires` 字段**；
  - `.kiro/steering/tech.md`、`README.md` 均声明 **3.9+**；
  - CI `test.yml` 矩阵**实际在跑 3.8**；
  - 而 `backtrader/brokers/hft/*.py` 等已使用 PEP 604 `X | Y`、小写泛型 `dict[...]`
    等 **3.9/3.10+ 运行期语法**，且全仓仅 7 个文件加了 `from __future__ import
    annotations`。
  - → 这意味着 **CI 的 3.8 任务很可能已经在某些路径上隐性失败或只是没触达那些
    模块**。必须先定一个版本基线（建议 **3.9+**，与文档一致、删除 3.8），否则后续
    所有「保持 3.8 兼容」的约束都是空中楼阁。
- **行宽配置不一致** 🟠：`black=100`（pyproject + Makefile + CI），但
  `ruff/isort=121`。旧版建议「统一到 121」会**直接打破 CI 的 `black --check
  --line-length 100`**。本版改为**统一到 100**（改动最小、与 CI 一致）。
- **CI 已存在但旧版完全没提** 🟠：旧版把「加 CI 门禁」放在 Sprint 9 (P3)，实际
  `test.yml` 已跑全量测试 + ruff + black。应当是**增强**它（加 mypy 非阻塞、加
  分层测试），而非新建。
- **CI 跑全量 ≈ 10 分钟**：配合已落地的 `make test-fast` 分级（见
  `docs/SLOW_TESTS_TODO.md`），CI 可拆「PR 快速门禁 + nightly 全量」。

---

## 重新排序后的路线图 (Re-prioritized Roadmap)

按「收益 ÷ 风险 ÷ 成本」重排。最高价值是**纠矛盾**与**可观测性**；
**大文件拆包（旧 Sprint 6）被降级**——它风险最高（破坏 pickle/导入/继承）、对用户
零收益，放到最后且设为可选。

| 顺序 | Sprint | 主题 | 优先级 | 工时 | 风险 |
| --- | --- | --- | --- | --- | --- |
| 1 | S1 | 配置/版本/CI 一致性（纠矛盾） | **P0** | 1–2d | 低 |
| 2 | S2 | 统一日志基础设施 + 消灭静默异常 | **P0** | 3–4d | 低 |
| 3 | S3 | 异常处理细化（泛化→具体 + 上下文） | P1 | 4–5d | 中 |
| 4 | S4 | 公共 API 类型注解 + mypy 收敛 | P1 | 5–7d | 中 |
| 5 | S5 | 高复杂度函数治理（Top 10） | P1 | 5–8d | 中高 |
| 6 | S6 | 测试质量 / 文档 / DX | P2 | 3–4d | 低 |
| 7 | S7 | 接口设计（长参数列表，19 处） | P3 | 2–3d | 中 |
| 8 | S8 | （可选）超大文件拆分 | P3 | 5–7d | **高** |

> Sprint 7（star import 清理）已无必要——非 `__init__` 中已为 0，故从路线图移除，
> 仅在 CI 中加一条 `ruff --select F403` 防回归即可（并入 S1）。

---

## Sprint 1：配置 / 版本 / CI 一致性 🔥 (P0, 1–2d)

**目标**：消除文档、配置、CI、代码之间的相互矛盾，建立一致的质量基线。这是后续所有
Sprint 的地基，且成本极低、风险极低。

### 1.1 敲定 Python 版本基线 = 3.9+

- [ ] `setup.py` 增加 `python_requires=">=3.9"`，classifiers 删除 3.8。
- [ ] CI `test.yml` 矩阵删除 `3.8` 行（3 个 OS 各一处）。
- [ ] `pyproject.toml`：`[tool.black] target-version` 去掉 `py38`；
  `[tool.ruff] target-version = "py39"`；`[tool.mypy] python_version = "3.9"`。
- [ ] `.pre-commit-config.yaml`：`pyupgrade --py311-plus` **改为 `--py39-plus`**
  （与基线一致，避免把代码升级到超过支持下限的语法）。
- [ ] 跑一次全量 `pyupgrade --py39-plus` + `make format`（独立 PR），消化已有的
  3.10+ 语法分歧（要么补 `from __future__ import annotations`，要么统一到 3.9 可
  运行形态）。
- [ ] 同步 `README.md` / `CLAUDE.md` / `tech.md` 文案到 3.9+（README/tech 已是
  3.9+，确认无 3.8 残留）。

> 决策依据：文档与代码事实都已是 3.9+，唯独 CI 还在跑 3.8 而代码未必兼容。删 3.8
> 是「让声明与现实一致」，不是抬高门槛。

### 1.2 统一行宽 = 100

- [ ] `pyproject.toml`：`[tool.ruff] line-length` 与 `[tool.isort] line_length`
  从 121 **改为 100**，与 black / Makefile / CI 对齐。
- [ ] 跑 `make format`（独立 PR，纯格式化，无逻辑变更）。
- [ ] 验证 CI 的 `black --check --line-length 100` 与本地一致。

> 选 100 而非 121：100 是 CI 与 black 的现行真相，改 121 反而要动 CI 且 diff 巨大。

### 1.3 清理 Ruff 现有 63 告警

- [ ] `ruff check backtrader --fix`（自动修 8×F401 + 1×F841）。
- [ ] 18×F811：人工审查（多为 `__init__.py` 故意 re-export 覆盖，确认后用
  `# noqa: F811` 显式标注意图）。
- [ ] 36×E402：核心是 `conftest.py` 之类「先改 `sys.path` 再 import」的合法场景，
  逐处加 `# noqa: E402` + 注释，或调整顺序；不可一刀切。
- [ ] 目标：`ruff check backtrader` 干净退出。

### 1.4 增强 CI（基于已有 test.yml，不新建）

- [ ] 拆分 job：**PR 门禁**用 `make test-fast`（~3.5 min，跑全部非策略 + 最快 35%
  策略，见 `docs/SLOW_TESTS_TODO.md`）；**nightly / push-to-dev** 跑
  `pytest tests -n auto`（全量）。
- [ ] 新增 `mypy backtrader`（**非阻塞**，仅输出报告，作为 S4 的趋势看板）。
- [ ] 新增 `ruff --select F403`（阻塞）防止 star import 回流到非 `__init__`。
- [ ] 修复或显式标注当前在 3.9 矩阵下可能失败的 hft 模块语法问题。

### S1 验收

- 所有工具/文档/CI 的 Python 版本与行宽一致；`ruff check backtrader` 零告警；
  CI 全绿；全量测试 100%。

---

## Sprint 2：统一日志基础设施 + 消灭静默异常 🔥 (P0, 3–4d)

**目标**：建立项目级统一日志入口，并把 ~99 处 `except…: pass` 变为可追溯。

### 2.1 日志架构

- [ ] 新建 `backtrader/utils/logging_config.py`：
  - `get_logger(name)` 工厂；`configure_logging(level, log_file=None, fmt=None)`
    配置入口；`set_level(name, level)` 运行时调级。
  - **默认 `NullHandler`**：用户不调用 `configure_logging()` 时行为与现状完全一致
    （零破坏）。
  - 在 `backtrader/__init__.py` re-export `get_logger` / `configure_logging`。
- [ ] 发布 `docs/LOGGING_GUIDELINES.md` 级别规范：
  - CRITICAL：引擎无法继续；ERROR：可恢复失败（订单拒绝、数据加载失败）；
    WARNING：降级/自动修正；INFO：里程碑（启动/结束/成交）；DEBUG：每 bar 诊断。

### 2.2 消灭静默异常（~99 处 / 18 文件）

- [ ] 统一改为带级别与 `exc_info` 的日志；真正无所谓的（析构/清理）降级为
  `logger.debug(...)` 并加注释说明原因。
- [ ] **热路径守护**：`next()` / `once()` / `_runonce` / `_runnext` 等热点里加的日志
  一律用 `if logger.isEnabledFor(logging.DEBUG):` 包裹，避免格式化开销。
- [ ] 按子目录分批 PR：核心 `*.py` → `brokers/` `feeds/` → `plot/` `bokeh/`
  `reports/`。

### 2.3 print → logging（当前 63 处 print / 306 logging）

- [ ] `reports/reporter.py`、散落诊断 print → `logger.info/debug`。
- [ ] `btrun/` 面向用户的 CLI 输出**保留 print/click.echo**（不破坏 CLI 体验）。
- [ ] `observers/trade_logger.py` 已有 `self.log()` 机制，内部走 logger，外部接口不变。

### 2.4 测试与文档

- [ ] `tests/unit/utils/test_logging_config.py`：验证 logger 命名、默认不输出
  （NullHandler）、`configure_logging` 不破坏已存在 logger、级别切换生效。
- [ ] README 增「日志使用」小节；`pytest tests -n 8` 全绿；benchmark 无显著回归。

### S2 验收

| 指标 | 当前 | 目标 |
| --- | --- | --- |
| `except…: pass` 静默异常 | ~99 | 0 |
| 使用 logging 的文件占比 | ~20% | >50% |
| 散落 `print()` | 63 | <10（仅 CLI 用户输出） |
| 统一日志入口 | 无 | `bt.get_logger` / `bt.configure_logging` |
| 测试通过率 | 100% | 100% |

---

## Sprint 3：异常处理细化 (P1, 4–5d)

**目标**：把泛化 `except` 比例从 ~40% 降到 <15%，与 S2 的日志联动。**前置依赖 S2**。

- [ ] 分类细化 272 处泛化捕获：数据解析→`(ValueError, TypeError, KeyError)`；
  网络→`(ConnectionError, TimeoutError, OSError)`；文件→`(OSError,
  PermissionError)`；第三方（ccxt 等）→查其异常基类；顶层事件循环保留
  `except Exception` + `logger.exception()`。
- [ ] 补全异常链：上层有 `except` 的 `raise X(...)` 改 `raise X(...) from e`。
- [ ] `backtrader/errors.py` 扩展业务异常层级（**只增父类、不删旧类**，保持
  isinstance 兼容）：`BacktraderError` → `DataError` / `BrokerError` /
  `OrderError` / `ConfigError`。
- [ ] eval/exec：当前仅 **1 处**，审查能否用 `ast.literal_eval`/`getattr` 替代；
  不能则加白名单校验 + `# nosec` + 注释。

**S3 验收**：泛化异常比例 <15%；eval/exec 经审查；测试 100%。

---

## Sprint 4：公共 API 类型注解 + mypy 收敛 (P1, 5–7d)

**目标**：类型注解覆盖率 9.2% → 40%+，mypy 543 → <150（务实目标，不强求归零）。

### 分层

- **第一层（必须）公共 API**：`cerebro.py`、`strategy.py`（buy/sell/close/
  order_target_*）、`order.py`、`feed.py`、`broker.py`。
- **第二层（推荐）核心内部**：`linebuffer.py`、`lineseries.py`、`lineiterator.py`、
  `parameters.py`。
- **第三层（渐进）子模块**：`indicators/`、`analyzers/`、`feeds/`。

### mypy 错误治理（543，按类型）

call-arg(78) / union-attr(62) / misc(54) / operator(42) / index(34) /
arg-type(34) / var-annotated(33) … 优先修公共 API 路径上的；动态属性密集处可用
`# type: ignore[code]` + 注释，避免为类型而扭曲运行时行为。

### 约束

- 全程 `from __future__ import annotations`，避免运行期求值与循环导入；
  循环导入用 `TYPE_CHECKING` 守护；**不引入运行时类型检查依赖**（保持零新增依赖）。

**S4 验收**：覆盖率 >40%；mypy <150（CI 非阻塞看板持续下降）；测试 100%。

---

## Sprint 5：高复杂度函数治理 (P1, 5–8d)

**目标**：把 Top 复杂度函数降到可维护区间。**纯内部重构，外部行为不变。**

### Top 10（radon 实测，2026-05-30）

| CC | 文件 | 函数 | 建议 |
| --- | --- | --- | --- |
| 161 | brokers/tickbroker.py | `process_orderbook` | 提取订单簿状态机 |
| 84 | strategy.py | `SignalStrategy._next_signal` | 拆信号处理子方法 |
| 70 | lineiterator.py | `LineIterator.__init__` | 分阶段初始化 |
| 63 | strategy.py | `_periodset` | **拆分**（注：含本次多数据时钟修复新增逻辑，见下注） |
| 59 | cerebro.py | `_runnext` | 提取数据推进/通知子方法 |
| 57 | cerebro.py | `runstrategies` | 提取准备/执行/清理阶段 |
| 55 | plot/plot.py | `Plot_OldSync.plotind` | 提取配置/渲染 |
| 49 | linebuffer.py | `LineActions._once` | 提取一次性计算分支 |
| 48 | lineiterator.py | `LineIteratorMixin.donew` | 拆参数提取/数据绑定 |
| 44 | lineseries.py | `_register_line_assignment_child` | 拆注册逻辑 |

> 注：`_periodset` 的复杂度部分来自近期「多数据时钟对齐」修复（见
> `docs/DEV_REGRESSION_FAILURES.md`）。重构时**务必先跑 `make test-strategies`**，
> 那批多时间框架用例正是此函数的回归网。

### 策略

- 每个函数单独 PR；重构前后跑相关测试 + 必要时 `make test-strategies`；
- 关键决策分支加 DEBUG 日志（复用 S2）；目标 CC>40 → <30，>30 → <20；
- 提取的辅助方法以 `_` 前缀标识为内部；签名/返回值不变；魔法方法只改内部。

---

## Sprint 6：测试质量 / 文档 / DX (P2, 3–4d)

- [ ] 给 17 个无专属测试的核心模块**至少补冒烟测试**（旧版把这条排除了，但这是真正
  的测试盲区，应纳入）。
- [ ] 扩大 fixture（当前少）与参数化（当前 62 处）使用；核心模块覆盖率 >80%。
- [ ] 文档：`CONTRIBUTING.md`（风格/PR 流程/测试分级/日志规范）、`ARCHITECTURE.md`
  （ADR）、补 12 个缺失的模块级 docstring。
- [ ] 把已落地的测试分级（`make test-fast/-slow/-strategies/-all`、
  `BT_SLOW_PERCENTILE`）写进 CONTRIBUTING。

---

## Sprint 7：接口设计 — 长参数列表 (P3, 2–3d)

- 当前 >7 参数的函数约 **19 处**（旧版写 61，偏高）。引入 `dataclass`/`TypedDict`
  参数对象（`OrderParams`、`PlotConfig` 等）作为**附加**接口；旧签名保留，必要时
  `DeprecationWarning` 引导，不强制迁移。

---

## Sprint 8：（可选/最后）超大文件拆分 (P3, 5–7d, 高风险)

> **默认不做，除非有明确维护痛点。** 把 `strategy.py`/`lineiterator.py` 等拆成子包
> 收益主要是「文件变短」，但风险极高：破坏 `pickle`（`__module__` 变化）、潜在循环
> 导入、用户 monkeypatch 失效。若执行，必须：包 `__init__.py` 完整 re-export 保持
> 导入路径；逐文件拆；保留 `__module__` 重定向；每步全量测试。

---

## 贯穿所有 Sprint 的硬约束 (Compatibility Constraints) ⚠️

1. 公共 API 不删除、不改签名（`bt.Cerebro/Strategy/Indicator` 等）。
2. 导入路径不变（`from backtrader[.x] import Y` 全部继续可用）。
3. 类继承关系不变（用户 `isinstance` 行为不变）。
4. 参数默认值不变；数值结果、订单逻辑、事件顺序可重现。
5. **每个 Sprint 必须**：`pytest tests -n 8` 全绿（2,991 用例）+ CI 全绿 +
   benchmark 无显著回归（>5% 视为回归）。
6. 破坏性变更需先讨论，走 `DeprecationWarning` 至少保留 2 个版本。

---

## 度量看板 (Metrics Dashboard)

| 指标 | 当前 (2026-05-30) | 目标 (对应 Sprint) |
| --- | --- | --- |
| Python 版本声明一致性 | ❌ 3 处矛盾 + 代码用 3.10+ 语法 | ✅ 统一 3.9+ (S1) |
| 行宽配置一致性 | ❌ black 100 / ruff,isort 121 | ✅ 统一 100 (S1) |
| Ruff 告警 | 63 | 0 (S1) |
| CI 覆盖 mypy | 否 | 是（非阻塞，S1） |
| `except…: pass` | ~99 | 0 (S2) |
| 使用 logging 文件占比 | ~20% | >50% (S2) → >80% (S3) |
| 散落 `print()` | 63 | <10 (S2) |
| 泛化异常比例 | ~40% | <15% (S3) |
| 类型注解覆盖率 | 9.2% | >40% (S4) |
| Mypy 错误 | 543 | <150 (S4) |
| 高复杂度 CC>40 / >30 | 14 / 27 | 0 / <10 (S5) |
| 无专属测试核心模块 | 17 | 0（冒烟，S6） |
| 长参数列表 (>7) | ~19 | 显著减少 (S7) |
| 非 `__init__` star import | **0（已达标）** | 0（CI 防回归，S1） |
| **测试通过率** | **100% (2,991)** | **100%（每个 Sprint）** |

---

## 附录：核实命令 (Verification Commands)

```bash
# 复杂度（D 级及以上 = CC>20）
pip install radon
radon cc backtrader -n D -s | grep -E " - [DEF] "

# 类型错误
mypy backtrader --config-file=pyproject.toml 2>/dev/null | tail -1

# Lint
ruff check backtrader --statistics

# 静默异常（next 行为 pass）
python3 - <<'PY'
import re,os
c=0
for r,_,fs in os.walk('backtrader'):
    if '__pycache__' in r: continue
    for f in fs:
        if not f.endswith('.py'): continue
        L=open(os.path.join(r,f)).read().splitlines()
        for i,l in enumerate(L):
            if re.match(r'\s*except\b.*:\s*$',l):
                j=i+1
                while j<len(L) and not L[j].strip(): j+=1
                if j<len(L) and L[j].strip()=='pass': c+=1
print('silent except->pass:',c)
PY

# 非 __init__ 的 star import（应为 0）
grep -rEn "^from .* import \*" backtrader --include="*.py" | grep -v "__init__.py" | wc -l

# 全量回归 / 快速回归
pytest tests -n 8 -q          # 全量 (~10 min)
make test-fast                # 快速门禁 (~3.5 min)
```
