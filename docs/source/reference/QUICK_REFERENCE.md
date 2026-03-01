# 文档工具快速参考指南

## 🛠️ 可用工具

### 1. 文档覆盖率扫描
```bash
# 扫描整个项目
python tools/doc_coverage_scanner.py --output docs/DOC_COVERAGE_REPORT.md

# 扫描特定模块
python tools/doc_coverage_scanner.py --root backtrader/cerebro.py
```

### 2. 链接验证
```bash
# 验证内部链接
python tools/doc_link_validator.py --output docs/LINK_VALIDATION_REPORT.md

# 验证包括外部链接（需要requests库）
python tools/doc_link_validator.py --check-external --output docs/LINK_VALIDATION_REPORT.md
```

### 3. Docstring增强
```bash
# 扫描需要增强的函数
python tools/docstring_enhancer.py --scan backtrader/ --output docs/DOCSTRING_REPORT.md
```

### 4. 一致性检查
```bash
# 检查文档一致性
python tools/doc_consistency_checker.py --output docs/CONSISTENCY_REPORT.md
```

## 📖 文档构建

### 本地构建
```bash
cd docs

# 构建英文文档
make html

# 构建中文文档
make html SPHINXOPTS="-D language=zh_CN"

# 使用国际化工具
make -f Makefile.i18n build-zh
```

### 实时预览
```bash
cd docs
sphinx-autobuild source build/html
```

## 🔄 国际化工作流

### 提取翻译字符串
```bash
cd docs
make -f Makefile.i18n gettext
```

### 更新翻译目录
```bash
make -f Makefile.i18n update-po
```

### 构建多语言文档
```bash
make -f Makefile.i18n build-lang
```

## 📊 报告位置

所有生成的报告保存在：
- `docs/DOC_COVERAGE_REPORT.md` - 文档覆盖率
- `docs/LINK_VALIDATION_REPORT.md` - 链接验证
- `docs/CONSISTENCY_REPORT.md` - 一致性检查

## 🎯 推荐工作流

### 每周维护
```bash
# 1. 检查文档覆盖率
python tools/doc_coverage_scanner.py --output docs/reports/coverage_$(date +%Y%m%d).md

# 2. 验证链接
python tools/doc_link_validator.py --output docs/reports/links_$(date +%Y%m%d).md

# 3. 检查一致性
python tools/doc_consistency_checker.py --output docs/reports/consistency_$(date +%Y%m%d).md
```

### 发布前检查
```bash
# 运行所有检查
./scripts/check_docs.sh  # 需要创建此脚本
```

## 📚 重要文档

- [完整总结](DOCUMENTATION_ENHANCEMENT_SUMMARY.md)
- [术语对照表](TERMINOLOGY_GLOSSARY.md)
- [搜索设置指南](SEARCH_SETUP_GUIDE.md)
- [优化文档索引](opts/INDEX.md)

## 🔗 相关资源

- GitHub Actions: `.github/workflows/docs-auto-build.yml`
- Algolia配置: `.algolia-config.json`
- Sphinx配置: `source/conf.py`
- 国际化Makefile: `Makefile.i18n`
