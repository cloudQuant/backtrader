# Contributing to Backtrader

感谢你对 Backtrader 的贡献兴趣！本文档说明如何参与项目开发。

分支角色、PR 目标分支选择、风险分级与 promotion/hotfix 协议的**权威来源**见
[Branch Governance](docs/source/developer-guide/branch-governance.md)。本文档与
其冲突时，以分支治理文档为准。

## 快速开始

### 环境搭建

```bash
# 1. Fork 并克隆仓库
git clone https://github.com/cloudQuant/backtrader.git
cd backtrader

# 2. 切到目标分支（见下方「分支策略」选择正确的目标分支）
git checkout dev

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装开发模式（纯 Python，无独立 Cython 编译步骤）
pip install -e .

# 5. 验证安装
python -c "import backtrader as bt; print(bt.__version__)"
make test-fast        # 快速回归（约 3.5 分钟）
```

### 开发命令速查

```bash
make test-fast         # 快速开发回路（~3.5min）：全部非策略测试 + 最快 ~35% 策略测试
make test-strategies   # 仅重型策略回归套件（~9min，多时间框架时钟回归网）
make test-slow         # 仅 test-fast 跳过的最慢 ~65% 策略测试
make test-all          # 全量并行（~10min）
make test-coverage     # 测试 + 覆盖率
make format            # 代码格式化 (Black, line-length 100)
make format-check      # 仅检查格式
make lint              # ruff / pylint 检查
make type-check        # mypy 类型检查（非阻塞）
make quality-check     # 全部质量检查
make docs              # 生成文档（en + zh）
```

---

## 分支策略

本仓库使用**三分支模型**（不同于常见 GitFlow）。完整定义与决策表见
[Branch Governance](docs/source/developer-guide/branch-governance.md)。

| 分支 | 定位 | 允许进入的变更 |
|------|------|----------------|
| `dev` | **日常开发入口** | 常规功能、普通 Bug 修复、文档、测试、重构、社区贡献 |
| `development` | **改进与优化版本** | 优化版能力、架构优化、仅在优化版存在的回归修复 |
| `master` | **原始 Backtrader 基线** | 已在原始版复现的 Bug、兼容性或安全修复（仅 `hotfix/master-*`） |

**选择目标分支：**

1. 文档、测试、常规功能、普通 Bug 修复 → **`dev`**
2. 仅在优化架构中出现的问题或优化版功能 → **`development`**
3. 原始 Backtrader 的真实 Bug / 安全问题 → **`master`**（`hotfix/master-*` 分支）

**工作流程（以 `dev` 为例）：**

```bash
git checkout -b feature/your-feature dev   # 从目标分支创建功能分支
# 开发、测试、提交
# 向 dev 提交 Pull Request
```

> 不要把 `development` 当作 `master` 的上游，也不要把优化版代码批量回灌到 `master`。

---

## 代码规范

### 风格要求

- **格式化**: Black (line-length=100)
- **Lint**: Pylint + Ruff
- **类型检查**: MyPy (可选)
- **import 排序**: isort (profile=black)

### 架构规则

1. **禁止新增元类** — 使用 `donew()` + `BaseMixin` 模式
2. **保持 API 兼容** — 现有用户代码必须无修改可运行
3. **初始化顺序** — 先调用 `super().__init__()` 再访问 `self.p`

```python
# ✅ 正确
class MyIndicator(bt.Indicator):
    params = (('period', 20),)

    def __init__(self):
        super().__init__()
        self.sma = bt.indicators.SMA(self.data, period=self.p.period)

# ❌ 错误 — self.p 在 super().__init__() 之前不可用
class BadIndicator(bt.Indicator):
    def __init__(self):
        print(self.p.period)  # 会失败!
        super().__init__()
```

### 提交信息规范

使用 [Conventional Commits](https://www.conventionalcommits.org/)：

```bash
feat: add live tick aggregation to BtApiFeed
fix: keep BtApiBroker alive before first live bar
perf: cache broker reference in total_value.next()
docs: update CTP live trading guide
test: add regression coverage for live broker startup
refactor: extract retry logic to _retry_api_call()
```

---

## 测试要求

### 必须

- 新功能必须有对应测试
- 修复 bug 必须有回归测试
- 不得删除或弱化现有测试

### 测试分级（重要）

策略回归套件很大，按耗时分级运行（详见 `Makefile` 与 `README`）：

| 命令 | 范围 | 大致耗时 | 用途 |
| --- | --- | --- | --- |
| `make test-fast` | 全部非策略测试 + 最快 ~35% 策略测试 | ~3.5min | 日常开发反馈 |
| `make test-strategies` | 全部策略回归（多时间框架时钟回归网） | ~9min | 改动 `cerebro`/`strategy`/line 系统后必跑 |
| `make test-slow` | test-fast 跳过的最慢 ~65% 策略 | — | 补充验证 |
| `make test-all` | 全量并行 | ~10min | 提交/发版前 |

慢/快分级由 `tests/functional/strategies/.test_durations.json` 的时长百分位决定，
阈值百分位用环境变量 `BT_SLOW_PERCENTILE`（默认 35）调整；新增策略默认归入快速档。

```bash
# 直接用 pytest 时
pytest tests -n 8 -q                 # 全量并行
pytest tests -n 8 -m "not slow"      # 跳过慢速策略
pytest tests/unit/brokers/test_btapibroker.py -v   # 单文件

# 切换到 pip 安装的 backtrader 而非工作区源码
BACKTRADER_USE_INSTALLED=1 pytest tests -q
# 或：pytest --use-installed-backtrader tests -q
```

### 日志规范

框架代码**不要直接 `import logging`**，统一走 `backtrader.utils.log_message`：

```python
from backtrader.utils.log_message import get_logger
logger = get_logger(__name__)   # -> "backtrader.<module>"
```

完整规范见 `docs/LOGGING_GUIDELINES.md`。

---

## Pull Request 流程

### 1. 创建 PR 前

- [ ] 代码通过 `make format-check`
- [ ] 代码通过 `make lint` (无新增 warning)
- [ ] 相关测试通过（改动核心路径时跑 `make test-strategies`）
- [ ] 新功能有测试覆盖
- [ ] 确定唯一目标分支（见上方「分支策略」）
- [ ] 确定风险级别 R0–R3（见分支治理文档）

### 2. PR 描述

使用仓库内的 [PR 模板](.github/pull_request_template.md)：必填字段仅包括问题与动机、
目标分支与原因、风险级别、兼容性影响、执行过的命令/结果、关联 issue。

### 3. 审查标准

- 代码清晰可读
- 无硬编码值
- 错误处理完善
- 性能不退化
- API 向后兼容

---

## 报告问题

使用 [Issue Forms](.github/ISSUE_TEMPLATE/) 提交。

### Bug 报告

请包含：环境（Python 版本、操作系统、backtrader 版本、目标分支）、最小复现、
预期行为 vs 实际行为、错误日志（完整 traceback）。

### 功能请求

请说明：使用场景、期望行为、目标分支影响、替代方案。

安全问题请走 `SECURITY.md` 定义的私密报告路径，**不要**在公开 issue 中提交。

---

## 项目结构导航

| 目录 | 说明 | 开发频率 |
|------|------|----------|
| `backtrader/brokers/` | Broker 实现 | 高 |
| `backtrader/feeds/` | 数据源 | 中 |
| `backtrader/indicators/` | 技术指标 | 中 |
| `backtrader/analyzers/` | 分析器 | 低 |
| `tests/functional/strategies/` | 策略回归套件（最大、分级） | 高 |
| `docs/` | 文档 | 中 |

详细架构参见 `docs/ARCHITECTURE.md`。
