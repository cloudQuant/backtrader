# Backtrader 项目文档索引

> 生成日期: 2026-02-22

## 文档导航

### 核心文档

| 文档 | 描述 | 读者 |
|------|------|------|
| [项目概览](project-overview.md) | 项目结构、核心模块、设计模式 | 开发者、用户 |
| [项目上下文](project-context.md) | LLM优化的架构规则和开发约定 | AI代理、开发者 |

### 文档目录

```
docs/
├── README.md                    # 文档系统说明
├── project-overview.md          # 项目概览（新增）
├── project-context.md           # 项目上下文（新增）
├── opts/                        # 优化报告
│   ├── OPTIMIZATION_REPORT.md   # 代码优化完整报告
│   └── project_status_summary.md # 项目状态总结
└── BRANCH_COMPARISON.md         # 分支对比分析
```

### 现有文档资源

- **CLAUDE.md** - 项目架构和开发指南
- **README.md** - 文档系统入口
- **opts/OPTIMIZATION_REPORT.md** - 代码优化完整报告
- **opts/project_status_summary.md** - 项目状态总结
- **BRANCH_COMPARISON.md** - 分支对比分析报告

## 快速开始

### 对于新开发者
1. 阅读 [项目概览](project-overview.md) 了解整体架构
2. 阅读 [项目上下文](project-context.md) 了解开发约定
3. 查看 CLAUDE.md 获取开发命令

### 对于AI代理
1. 读取 [project-context.md](project-context.md) 获取项目规则
2. 遵循架构模式和约定进行代码生成
3. 注意：不要引入新的元类，使用donew()模式

## 文档贡献

当修改代码时，请更新相应的文档：
- 新增模块：更新 project-overview.md
- 新增约定：更新 project-context.md
- 架构变更：更新相关文档

---

*此索引由BMAD项目文档化工作流生成*
