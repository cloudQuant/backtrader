- --

title: 贡献指南
description: Backtrader 贡献指南

- --

# 贡献指南

感谢您对 Backtrader 的贡献兴趣！本文档提供了参与项目开发的指南和工作流程。

## 目录

- [快速开始](#快速开始)
- [Pull Request 流程](#pull-request-流程)
- [代码审查标准](#代码审查标准)
- [Issue 报告指南](#issue-报告指南)
- [社区准则](#社区准则)
- [许可证和贡献者协议](#许可证和贡献者协议)
- [开发者来源证书 (DCO)](#开发者来源证书-dco)

## 快速开始

### 前置要求

- Python 3.8 或更高版本
- Git
- Python 编程基础知识
- 了解量化交易概念（有帮助但非必需）

### 首次设置

```bash

# 1. 在 GitHub 上 Fork 仓库

# 访问 <https://github.com/cloudQuant/backtrader> 并点击 "Fork" 按钮

# 2. 克隆你的 Fork

git clone <https://github.com/你的用户名/backtrader.git>
cd backtrader

# 3. 添加上游远程仓库

git remote add upstream <https://github.com/cloudQuant/backtrader.git>

# 4. 安装依赖

pip install -r requirements.txt

# 5. 以开发模式安装

pip install -e .

# 6. 编译 Cython 扩展（推荐，以获得更好性能）

cd backtrader && python -W ignore compile_cython_numba_files.py && cd ..

```bash

### 分支命名约定

使用描述性的分支名来指示变更类型：

| 前缀 | 用途 | 示例 |

|------|------|------|

| `feat/` | 新功能 | `feat/websocket-reconnect` |

| `fix/` | Bug 修复 | `fix/indicator-calculation` |

| `refactor/` | 代码重构 | `refactor/broker-optimization` |

| `docs/` | 文档 | `docs/api-reference` |

| `test/` | 测试改进 | `test/coverage-increase` |

| `perf/` | 性能优化 | `perf/line-buffer-cache` |

## Pull Request 流程

### 步骤 1: 创建功能分支

```bash

# 与上游同步

git fetch upstream
git checkout dev
git merge upstream/dev

# 创建你的功能分支

git checkout -b feat/your-feature-name

```bash

### 步骤 2: 进行更改

- 编写清晰、可读的代码
- 遵循[代码风格](style_zh.md)指南
- 为新功能添加测试
- 更新相关文档

### 步骤 3: 提交更改

遵循 [Conventional Commits](<https://www.conventionalcommits.org/)> 格式：

```bash
<type>: <description>

[可选的正文]

```bash

- *有效类型：**
- `feat`: 新功能
- `fix`: Bug 修复
- `refactor`: 代码重构
- `docs`: 文档更改
- `test`: 测试添加或修改
- `chore`: 维护任务
- `perf`: 性能改进

- *示例：**

```bash
git commit -m "feat: 为 CCXTFeed 添加 WebSocket 健康检查"
git commit -m "fix: 处理 CCXTBroker.cancel() 中的 order-not-found"
git commit -m "perf: 在 total_value.next() 中缓存 broker 引用"
git commit -m "docs: 更新 CCXT 实盘交易指南"

```bash

### 步骤 4: 运行测试

```bash

# 运行预提交测试 (P0 + P1)

pytest tests/ -v -m "priority_p0 or priority_p1"

# 运行完整测试套件

pytest tests/ -v -n 4

# 检查代码格式

make format-check

# 运行代码检查

make lint

```bash

### 步骤 5: 推送并创建 Pull Request

```bash

# 推送到你的 Fork

git push origin feat/your-feature-name

# 在 GitHub 上创建 Pull Request

# 目标分支: dev

```bash

### Pull Request 描述模板

```markdown

## 概述

简要描述此 PR 的作用和原因。

## 变更内容

- 主要变更列表

## 变更类型

- [ ] Bug 修复
- [ ] 新功能
- [ ] 性能改进
- [ ] 文档更新
- [ ] 代码重构
- [ ] 破坏性变更

## 测试

- 描述测试方法
- 包含测试命令

```bash
pytest tests/path/to/test.py -v

```bash

## 检查清单

- [ ] 代码符合风格指南
- [ ] 本地测试通过
- [ ] 为新功能添加测试
- [ ] 更新文档
- [ ] 更新 CHANGELOG.md（面向用户的变更）
- [ ] 与目标分支无合并冲突

## 相关 Issues

Fixes #123
Related to #456

```bash

## 代码审查标准

### 审查流程

1. **自动检查**：所有 PR 必须通过 CI/CD 检查
2. **同行评审**：至少需要一位维护者批准
3. **测试覆盖**：新代码需要相应的测试
4. **文档更新**：API 变更需要更新文档

### 审查标准

维护者从以下方面审查 Pull Request：

| 方面 | 标准 |

|------|------|

| **功能正确性**| 按预期工作，无回归 |

|**代码质量**| 可读、可维护、符合约定 |

|**测试**| 覆盖充分，处理边界情况 |

|**文档**| 清晰的文档字符串，面向用户的变更已记录 |

|**性能**| 无显著退化，优化已记录 |

### 处理审查反馈

- 回应所有审查意见
- 进行请求的更改或提供理由
- 解决后标记对话为已解决
- 重大更改后请求重新审查

### 批准要求

- 小更改：一位维护者批准
- 中等更改：两位维护者批准
- 大型/复杂更改：核心团队共识

## Issue 报告指南

### Bug 报告

包含以下信息：

```markdown

## 环境

- Python 版本：3.11.0
- 操作系统：Ubuntu 22.04
- Backtrader 版本：1.0.0 (dev 分支)
- 安装方式：pip install -e .

## 问题描述

清晰描述 Bug。

## 复现步骤

1. 创建 Cerebro 实例
2. 添加数据源...
3. 运行策略
4. 观察错误

## 预期行为

应该发生什么。

## 实际行为

实际发生了什么（包含错误信息）。

## 代码示例

```python
import backtrader as bt

# 最小可复现代码

```bash

## 附加信息

日志、截图或其他相关信息。

```bash

### 功能请求

提供以下信息：

```markdown

## 问题陈述

这解决了什么问题？用例是什么？

## 建议的解决方案

所需功能的详细描述。

## 考虑的替代方案

您还考虑了哪些其他方法？

## 附加信息

示例、参考或实现想法。

```bash

## 社区准则

### 行为准则

- 尊重和包容
- 欢迎新手并帮助他们学习
- 专注于建设性反馈
- 假设良好意图

### 沟通渠道

- **Issues**：Bug 报告和功能请求
- **Discussions**：问题和想法
- **Pull Requests**：代码贡献

### 获取帮助

- 首先搜索现有的 issues 和 discussions
- 提供最小可复现示例
- 分享相关环境详情
- 对志愿者维护者保持耐心

## 许可证和贡献者协议

### 许可证

Backtrader 采用 GNU General Public License v3.0 (GPLv3) 许可。

通过向 Backtrader 贡献，您同意您的贡献将在 GPLv3 下许可。

### 版权

版权由原始贡献者保留。项目在以下位置包含致谢：

- LICENSE 文件
- CONTRIBUTORS 文件
- 发布说明

## 开发者来源证书 (DCO)

### 什么是 DCO？

DCO 是一个简单的声明，证明您有权提交您的贡献。

### DCO 签署

要认证您的贡献，请在提交消息中添加 `Signed-off-by` 行：

```bash
git commit -m "feat: 添加新指标

Signed-off-by: 你的名字 <your.email@example.com>"

```bash

### 自动签署

配置 Git 自动添加签署：

```bash
git config --global commit.signoff true

```bash
然后使用 `-s` 标志：

```bash
git commit -s -m "feat: 添加新指标"

```bash

### DCO 认证

通过签署，您证明：

> 开发者来源证书
> 版本 1.1
>
> 版权所有 (C) 2004, 2006 The Linux Foundation 及其贡献者。
> 1 Letterman Drive
> Suite D4700
> San Francisco, CA, 94129
>
> 任何人都可以复制和分发本许可文档的逐字副本，
> 但不允许更改。
>
>
> 开发者来源证书 1.1
>
> 通过向本项目做出贡献，我证明：
>
> (a) 该贡献全部或部分由我创建，我有权根据文件中
>     指明的开源许可证提交它；或
>
> (b) 该贡献基于以前的工作，据我所知，这些工作受
>     适当的开源许可证保护，我有权根据该许可证
>     提交修改后的作品（无论全部或部分由我创建），
>     使用相同的开源许可证（除非我被允许根据不同
>     许可证提交），如文件中所指明；或
>
> (c) 该贡献由认证了 (a)、(b) 或 (c) 的其他人直接
>     提供给我，且我未对其进行修改。
>
> (d) 我理解并同意该项目和贡献是公开的，贡献记录
>     （包括我提交的所有个人信息，包括我的签署）将
>     无限期保存，并可根据本项目或所涉及的开源许可
>     证重新分发。

## 认可

贡献者在以下位置获得认可：

- `CONTRIBUTORS` 文件
- 发布说明
- 项目文档（重大贡献）

感谢您为 Backtrader 做出贡献！

## 另请参阅

- [开发环境设置](setup_zh.md)
- [代码风格](style_zh.md)
- [测试指南](testing_zh.md)
- [项目上下文](../project-context.md)
