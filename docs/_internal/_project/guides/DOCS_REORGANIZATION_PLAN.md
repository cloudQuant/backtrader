# Docs目录重组方案

## 当前问题分析

### 1. 目录混乱
- ❌ 根目录有30+个Markdown文件
- ❌ 同时存在`api_reference`和`api-reference`两个目录
- ❌ 同时存在`user_guide`和`source/user_guide`
- ❌ 大量项目管理文件混在文档中
- ❌ 临时文件和构建文件未隔离

### 2. 结构不清晰
- ❌ 没有明确的文档分类
- ❌ 新手难以找到入门文档
- ❌ 开发者文档和用户文档混在一起
- ❌ 中英文文档路径不统一

### 3. 重复内容
- ❌ 多个README和index文件
- ❌ 重复的API参考目录
- ❌ 重复的用户指南目录

## 新目录结构设计

```
docs/
├── README.md                          # 文档总入口
├── index.md                           # Sphinx主页
│
├── _project/                          # 项目管理文档（隔离）
│   ├── status/
│   │   ├── PROJECT_STATUS.md
│   │   ├── RELEASE.md
│   │   └── BRANCH_COMPARISON.md
│   ├── planning/
│   │   ├── DOCUMENTATION_TODO.md
│   │   ├── project-context.md
│   │   └── project-overview.md
│   ├── reports/
│   │   ├── DOC_COVERAGE_REPORT.md
│   │   ├── LINK_VALIDATION_REPORT.md
│   │   ├── DOCUMENTATION_UPDATE_REPORT.md
│   │   └── TASKS_1_2_4_5_COMPLETION.md
│   └── guides/
│       ├── DOCUMENTATION_ENHANCEMENT_SUMMARY.md
│       ├── API_AUTO_GENERATION_GUIDE.md
│       ├── SPHINX_CONVERSION_GUIDE.md
│       └── RTD_SETUP.md
│
├── getting-started/                   # 快速入门（英文）
│   ├── README.md
│   ├── installation.md
│   ├── quickstart.md
│   └── basic-concepts.md
│
├── getting-started-zh/                # 快速入门（中文）
│   ├── README.md
│   ├── installation.md
│   ├── quickstart.md
│   └── basic-concepts.md
│
├── tutorials/                         # 教程
│   ├── README.md
│   ├── notebooks/
│   │   ├── 01_quickstart.ipynb
│   │   ├── 02_indicators.ipynb
│   │   ├── 03_position_sizing.ipynb
│   │   ├── 04_optimization.ipynb
│   │   └── 05_live_trading.ipynb
│   └── examples/
│       └── strategies/
│
├── user-guide/                        # 用户指南（英文）
│   ├── README.md
│   ├── data-feeds.md
│   ├── strategies.md
│   ├── indicators.md
│   ├── analyzers.md
│   ├── observers.md
│   └── plotting.md
│
├── user-guide-zh/                     # 用户指南（中文）
│   ├── README.md
│   └── ...
│
├── api-reference/                     # API参考（统一）
│   ├── README.md
│   ├── cerebro.md
│   ├── strategy.md
│   ├── indicators.md
│   ├── feeds.md
│   ├── brokers.md
│   └── analyzers.md
│
├── advanced/                          # 高级主题
│   ├── README.md
│   ├── live-trading/
│   │   ├── ccxt-guide.md
│   │   ├── websocket.md
│   │   └── funding-rate.md
│   ├── architecture/
│   │   ├── overview.md
│   │   ├── line-system.md
│   │   └── multi-strategy.md
│   └── optimization/
│       └── parameter-optimization.md
│
├── developer-guide/                   # 开发者指南
│   ├── README.md
│   ├── setup.md
│   ├── testing.md
│   ├── contributing.md
│   └── architecture.md
│
├── migration/                         # 迁移指南
│   ├── README.md
│   └── from-original.md
│
├── reference/                         # 参考资料
│   ├── TERMINOLOGY_GLOSSARY.md
│   ├── QUICK_REFERENCE.md
│   ├── SEARCH_SETUP_GUIDE.md
│   └── optimization-docs/
│       └── INDEX.md
│
├── source/                            # Sphinx源文件
│   ├── conf.py
│   ├── index.rst
│   ├── _static/
│   ├── _templates/
│   └── locales/
│
├── _build/                            # 构建输出
├── _temp/                             # 临时文件
└── _archive/                          # 归档文件
```

## 重组步骤

### 第一阶段：创建新结构
1. 创建所有新目录
2. 创建各目录的README索引

### 第二阶段：移动文件
1. 项目管理文档 → `_project/`
2. 快速入门文档 → `getting-started/`
3. 用户指南 → `user-guide/`
4. API参考 → `api-reference/`（合并重复）
5. 高级主题 → `advanced/`
6. 开发者文档 → `developer-guide/`
7. 参考资料 → `reference/`

### 第三阶段：清理
1. 删除重复目录
2. 归档过时文件
3. 清理临时文件

### 第四阶段：更新索引
1. 更新主README.md
2. 创建各分类README
3. 更新Sphinx配置

## 文件映射表

### 项目管理文档 → _project/
- PROJECT_STATUS.md → _project/status/
- RELEASE.md → _project/status/
- BRANCH_COMPARISON.md → _project/status/
- DOCUMENTATION_TODO.md → _project/planning/
- DOC_COVERAGE_REPORT.md → _project/reports/
- LINK_VALIDATION_REPORT.md → _project/reports/
- DOCUMENTATION_ENHANCEMENT_SUMMARY.md → _project/guides/
- API_AUTO_GENERATION_GUIDE.md → _project/guides/
- SPHINX_CONVERSION_GUIDE.md → _project/guides/
- RTD_SETUP.md → _project/guides/

### 快速入门 → getting-started/
- opts/getting_started/* → getting-started/

### 用户指南 → user-guide/
- opts/user_guide/* → user-guide/
- source/user_guide/* → user-guide/（合并）

### API参考 → api-reference/
- api_reference/* → api-reference/
- api-reference/* → api-reference/（合并）
- source/api/* → api-reference/（合并）

### 高级主题 → advanced/
- advanced/* → advanced/
- CCXT_LIVE_TRADING_GUIDE.md → advanced/live-trading/
- FUNDING_RATE_GUIDE.md → advanced/live-trading/
- WEBSOCKET_GUIDE.md → advanced/live-trading/
- ARCHITECTURE.md → advanced/architecture/
- multi_strategy_architecture.md → advanced/architecture/

### 开发者指南 → developer-guide/
- developer_guide/* → developer-guide/
- development-guide.md → developer-guide/
- source/dev/* → developer-guide/

### 参考资料 → reference/
- TERMINOLOGY_GLOSSARY.md → reference/
- QUICK_REFERENCE.md → reference/
- SEARCH_SETUP_GUIDE.md → reference/
- opts/ → reference/optimization-docs/

### 归档 → _archive/
- project-scan-report.json
- source-tree-analysis.md
- existing-documentation-inventory.md
- project-structure.md

## 优势

### 1. 清晰的分类
- ✅ 用户文档和开发者文档分离
- ✅ 项目管理文档隔离
- ✅ 中英文文档路径统一

### 2. 易于导航
- ✅ 每个目录有README索引
- ✅ 逻辑清晰的层次结构
- ✅ 新手友好的入口

### 3. 易于维护
- ✅ 消除重复目录
- ✅ 临时文件隔离
- ✅ 归档机制

### 4. 符合标准
- ✅ 遵循文档最佳实践
- ✅ 与Sphinx结构兼容
- ✅ 支持国际化

## 实施计划

### 立即执行
1. 创建新目录结构
2. 移动关键文件
3. 更新主索引

### 后续优化
1. 合并重复内容
2. 补全缺失文档
3. 统一文档风格

## 注意事项

1. **保持向后兼容**：创建符号链接或重定向
2. **更新引用**：更新所有文档中的链接
3. **测试构建**：确保Sphinx能正常构建
4. **备份**：重组前备份当前结构
