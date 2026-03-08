---
title: 发布流程指南
description: Backtrader 版本管理和发布流程的完整指南

---
# 发布流程指南

本文档描述 Backtrader 项目的版本管理策略和发布流程。遵循这些准则可以确保发布的一致性、可追溯性和可靠性。

## 目录

- [版本管理策略](#版本管理策略)
- [发布分支策略](#发布分支策略)
- [发布前检查清单](#发布前检查清单)
- [发布流程](#发布流程)
- [发布后任务](#发布后任务)
- [紧急发布流程](#紧急发布流程)
- [回滚流程](#回滚流程)

---
## 版本管理策略

### 语义化版本

Backtrader 遵循 [语义化版本 2.0.0](<https://semver.org/lang/zh-CN/)> 规范：

```bash
MAJOR.MINOR.PATCH

```

| 位置 | 名称 | 说明 | 示例 |

|------|------|------|------|

| MAJOR | 主版本号 | 包含破坏性 API 变更时递增 | 1.0.0 → 2.0.0 |

| MINOR | 次版本号 | 向后兼容的新功能时递增 | 1.0.0 → 1.1.0 |

| PATCH | 补丁版本号 | 向后兼容的 Bug 修复时递增 | 1.0.0 → 1.0.1 |

### 版本号示例

| 版本 | 类型 | 说明 |

|------|------|------|

| `1.0.0` | 初始发布 | 第一个稳定版本 |

| `1.0.1` | 补丁 | Bug 修复 |

| `1.1.0` | 次版本 | 新增 CTP 期货支持 |

| `1.2.0` | 次版本 | 新增 WebSocket 订单推送 |

| `2.0.0` | 主版本 | 移除元类架构 |

### 预发布版本

对于不稳定的版本，可以使用预发布标识符：

| 标识符 | 说明 | 示例 |

|--------|------|------|

| `alpha` | 内部测试版本 | `1.2.0-alpha.1` |

| `beta` | 公开测试版本 | `1.2.0-beta.1` |

| `rc` | 候选发布版本 | `1.2.0-rc.1` |

### 开发版本

开发中的版本使用 `dev` 后缀：

```bash
1.3.0-dev

```

---
## 发布分支策略

### 分支模型

```bash
                    ┌─────────────────┐
                    │   master (稳定)  │
                    │  v1.0.0, v1.1.0 │
                    └────────▲────────┘
                             │ 合并
                             │
┌─────────────┐       ┌─────┴──────┐       ┌─────────────┐
│  feature/*  │──────▶│    dev     │───────▶│ release/*   │
│  功能分支    │       │  (主开发)   │       │  发布准备分支 │
└─────────────┘       └────────────┘       └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   ctp       │
                    │  CTP 期货开发 │
                    └─────────────┘

```

### 分支说明

| 分支 | 用途 | 合并目标 | 保护规则 |

|------|------|----------|----------|

| `master` | 稳定发布版本 | 仅来自 `release/*` | 必须通过 PR，需要审核 |

| `dev` | 主开发分支 | 接受 `feature/*` 合并 | 必须通过 PR，需要 CI 通过 |

| `release/x.y.z` | 发布准备分支 | 合并到 `master` 和 `dev` | 严格版本控制 |

| `feature/*` | 功能开发分支 | 合并到 `dev` | 常规开发 |

| `hotfix/*` | 紧急修复分支 | 合并到 `master` 和 `dev` | 快速通道 |

### 发布分支创建

```bash

# 从 dev 分支创建发布分支

git checkout dev
git pull origin dev
git checkout -b release/1.2.0

# 推送到远程

git push -u origin release/1.2.0

```

---
## 发布前检查清单

### 1. 代码质量检查

```bash

# 格式化检查

make format-check

# Linting

ruff check backtrader/

# 类型检查

make type-check

# 安全检查

make security

```

- *通过标准**:
- 无格式化错误
- 无 Linting 错误（或已批准的例外）
- 类型错误率 < 5%
- 无高危安全问题

### 2. 测试套件

```bash

# 运行完整测试套件

pytest tests/ -n 4 -v --tb=short

# 测试覆盖率

pytest tests/ --cov=backtrader --cov-report=term-missing

# 集成测试（需要凭证）

pytest tests/integration/ -m integration -v

```

- *通过标准**:
- 所有核心测试通过率 100%
- 代码覆盖率 >= 75%
- 无 P0、P1 级别的测试失败

### 3. 性能基准

```bash

# 运行性能基准测试

make benchmark

# 与上一版本对比

pytest tests/benchmarks/ --benchmark-compare

```

- *通过标准**:
- 性能回退 < 5%
- 无新的性能瓶颈

### 4. 文档更新

- [ ] CHANGELOG.md 已更新
- [ ] 版本号已更新
- [ ] API 文档已同步
- [ ] 迁移指南（如需要）
- [ ] 发布说明已起草

### 5. 兼容性验证

```bash

# 测试 Python 版本兼容性

pyenv local 3.8 3.9 3.10 3.11 3.12 3.13
for version in 3.8 3.9 3.10 3.11 3.12 3.13; do
    pyenv shell $version
    pytest tests/ -q
done

```

- *通过标准**:
- 在 Python 3.8-3.13 上均可运行
- 无弃用警告

### 6. 依赖检查

```bash

# 检查依赖安全性

safety check

# 检查过时的依赖

pip list --outdated

```

### 7. 发布前会议

在大版本发布前，召开发布前会议确认：

- 功能完整性
- 已知问题列表
- 回滚计划
- 发布时间窗口
- 负责人分配

---
## 发布流程

### 步骤 1: 更新版本号

- *文件**: `setup.py`

```python
setup(
    name="backtrader",
    version="1.2.0",  # 更新此行
    ...
)

```

- *文件**: `backtrader/__init__.py`（如果存在）

```python
__version__ = "1.2.0"

```

### 步骤 2: 更新 CHANGELOG

- *文件**: `CHANGELOG.md`

```markdown

## [1.2.0] - 2026-03-15

### Added

- 新增 CTP 期货交易支持 (P0)
- WebSocket 订单推送功能 (P1)
- 自适应速率限制器 (P2)

### Changed

- CCXT Broker 错误处理优化
- 提升回测性能 15%

### Fixed

- 修复数据长度不一致导致提前终止的问题
- 修复 CrossOver 指标依赖顺序问题

### Removed

- 移除过时的 `DataStream` 类（已废弃 3 个版本）

```

### 步骤 3: 创建发布分支

```bash

# 从 dev 创建发布分支

git checkout dev
git pull origin dev
git checkout -b release/1.2.0

# 推送到远程

git push -u origin release/1.2.0

```

### 步骤 4: 提交版本更新

```bash

# 添加变更文件

git add setup.py CHANGELOG.md backtrader/__init__.py

# 提交

git commit -m "release: v1.2.0 — 准备发布

- 更新版本号至 1.2.0
- 完成 CHANGELOG 更新
- 通过所有发布前检查"

```

### 步骤 5: 合并到 master

```bash

# 切换到 master

git checkout master
git pull origin master

# 合并发布分支

git merge release/1.2.0 -m "Merge release/1.2.0 into master"

# 推送到远程

git push origin master

```

### 步骤 6: 创建版本标签

```bash

# 创建带注释的标签

git tag -a v1.2.0 -m "v1.2.0: CTP 期货支持与 WebSocket 订单推送

新增功能:

- CTP 期货完整支持
- WebSocket 订单推送
- 自适应速率限制

改进:

- CCXT Broker 错误处理
- 15% 性能提升

修复:

- 数据长度问题
- CrossOver 依赖顺序"

# 推送标签到远程

git push origin v1.2.0

```

### 步骤 7: 合并回 dev

```bash

# 切换到 dev

git checkout dev
git pull origin dev

# 合并 master（确保 dev 包含发布变更）

git merge master -m "Merge master back to dev after v1.2.0 release"

# 推送

git push origin dev

```

### 步骤 8: 构建发布包

```bash

# 清理旧的构建

make clean

# 构建 sdist 和 wheel

python -m build

# 检查构建包

twine check dist/backtrader-1.2.0*

```

### 步骤 9: 上传到 PyPI

```bash

# 上传到测试 PyPI（先验证）

twine upload --repository testpypi dist/*

# 安装测试版本验证

pip install --index-url <https://test.pypi.org/simple/> backtrader

# 确认无误后上传到正式 PyPI

twine upload dist/backtrader-1.2.0*

```

### 步骤 10: 创建 GitHub Release

使用 gh CLI 或在 GitHub 网页上创建：

```bash

# 使用 gh CLI

gh release create v1.2.0 \

  - -title "v1.2.0: CTP 期货支持与 WebSocket 订单推送" \
  - -notes-file RELEASE_NOTES.md \
  - -draft

```

- *发布说明模板**:

```markdown

# Backtrader v1.2.0 发布说明

发布日期: 2026-03-15

## 新增功能

### CTP 期货交易支持

- 完整的 CTP API 集成
- 支持上期所、大商所、郑商所、能源中心
- 自动连接管理（SimNow 7x24/交易时段）
- 66 个单元测试覆盖

### WebSocket 订单推送

- 实时订单状态推送
- 自动 WebSocket 订阅管理
- 降低 API 调用延迟 50%

### 自适应速率限制

- 智能速率限制调整
- 防止交易所限流
- 自动重试机制

## 改进

- CCXT Broker 错误处理优化
- 回测性能提升 15%
- Cython 加速核心计算

## 修复

- 修复数据长度不一致导致提前终止的问题
- 修复 CrossOver 指标依赖顺序问题

## 升级指南

```
pip install --upgrade backtrader

```bash

### 迁移注意事项

如需从 CTP 旧版迁移：

1. 更新 `.env` 配置文件
2. 使用新的 `CTPStore` API
3. 参考 `docs/CCXT_LIVE_TRADING_GUIDE.md`

## 完整变更

详见 [CHANGELOG.md](<https://github.com/yunjinqi/backtrader/blob/master/CHANGELOG.md)>

```

---
## 发布后任务

### 1. 更新文档

```bash

# 生成文档

make docs

# 部署文档（根据项目配置）

make docs-deploy

```

### 2. 发布公告

- *渠道**:
- [ ] GitHub Discussions
- [ ] 项目官网
- [ ] 邮件列表（如有）
- [ ] 社交媒体（如有）

- *公告模板**:

```markdown

# Backtrader v1.2.0 现已发布

我们很高兴地宣布 Backtrader v1.2.0 正式发布！

## 亮点功能

- **CTP 期货交易支持**: 完整支持国内期货市场
- **WebSocket 订单推送**: 更快的订单响应
- **性能提升**: 15% 回测性能改进

## 安装

```
pip install --upgrade backtrader

```bash

## 文档

- 发布说明: [链接]
- 迁移指南: [链接]
- 完整文档: [链接]

## 感谢

感谢所有贡献者！

```

### 3. 监控反馈

发布后 48 小时内：

- 监控 GitHub Issues
- 检查 PyPI 下载统计
- 关注社区反馈
- 准备快速响应 Bug 修复

### 4. 创建下一版本

```bash

# 更新 dev 分支的 CHANGELOG

vim CHANGELOG.md

# 添加新的 Unreleased 部分

## [Unreleased] - dev branch

### Added

- (新功能占位)

```

### 5. 清理发布分支

```bash

# 删除本地发布分支

git branch -d release/1.2.0

# 删除远程发布分支（可选）

git push origin --delete release/1.2.0

```

---
## 紧急发布流程

### 触发条件

- 生产环境严重 Bug
- 安全漏洞
- 数据损坏风险

### 流程

```bash

# 1. 从 master 创建 hotfix 分支

git checkout master
git pull origin master
git checkout -b hotfix/1.2.1

# 2. 修复问题

# (进行必要的代码修改)

# 3. 测试验证

pytest tests/ -n 4 -v

# 4. 提交修复

git commit -am "hotfix: 修复严重数据损坏问题"

# 5. 合并到 master

git checkout master
git merge hotfix/1.2.1

# 6. 创建标签和发布

git tag -a v1.2.1 -m "v1.2.1: 紧急修复"
git push origin master v1.2.1

# 7. 合并回 dev

git checkout dev
git merge master
git push origin dev

# 8. PyPI 发布

python -m build
twine upload dist/backtrader-1.2.1*

```

---
## 回滚流程

### 何时回滚

- 发布后发现严重 Bug
- 安全问题
- 无法快速修复的问题

### 回滚步骤

```bash

# 1. 通知用户暂停升级

# 2. 从 PyPI 删除有问题的版本（仅限发布后 24 小时内）

# 使用 twine 或访问 PyPI 手动删除

twine delete --version 1.2.0 backtrader

# 3. 创建修复版本

# 通常是 1.2.1 (补丁版本)

# 4. 重新发布修复版本

# 按正常发布流程进行

```

### 回滚公告

```markdown

# 紧急通知: v1.2.0 回滚

由于发现严重问题，v1.2.0 已被撤回。请勿使用此版本。

受影响的用户应：

1. 降级到 v1.1.0
2. 等待 v1.2.1 修复版本

```
git clone <https://github.com/cloudQuant/backtrader.git>
cd backtrader && pip install -U .

```bash
我们将在 24 小时内发布修复版本。

```

---
## 快速参考

### 发布命令速查

```bash

# 完整发布流程

git checkout dev && git pull
git checkout -b release/1.2.0

# 编辑 setup.py, CHANGELOG.md

git add setup.py CHANGELOG.md
git commit -m "release: v1.2.0"
git checkout master && git merge release/1.2.0
git tag -a v1.2.0 -m "v1.2.0"
git push origin master v1.2.0
git checkout dev && git merge master
git push origin dev
make clean
python -m build
twine upload dist/*
gh release create v1.2.0 --notes "发布说明..."

```

### 检查清单速查

```markdown
发布前:

- [ ] 测试通过 (100% 核心测试)
- [ ] 代码覆盖率 >= 75%
- [ ] 格式化检查通过
- [ ] 类型检查通过
- [ ] 安全检查通过
- [ ] CHANGELOG 已更新
- [ ] 版本号已更新
- [ ] 文档已同步

发布中:

- [ ] 发布分支已创建
- [ ] 版本更新已提交
- [ ] 已合并到 master
- [ ] 标签已创建并推送
- [ ] 已合并回 dev
- [ ] 构建包已验证
- [ ] 已上传到 PyPI
- [ ] GitHub Release 已创建

发布后:

- [ ] 文档已部署
- [ ] 公告已发布
- [ ] 反馈监控已启动

```

---
## 另请参阅

- [开发环境设置](setup_zh.md)
- [代码风格指南](style_zh.md)
- [测试指南](testing_zh.md)
- [贡献指南](contributing_zh.md)
- [CHANGELOG.md](../../CHANGELOG.md)
