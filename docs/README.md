# Backtrader Documentation

Welcome to the Backtrader documentation!

## 📚 Documentation Structure

The documentation follows Sphinx best practices with a `source/` directory containing all content.

### For Users

- **[Getting Started](source/getting-started/)** - Installation and quickstart
- **[Tutorials](source/tutorials/)** - Interactive Jupyter notebooks and examples
- **[User Guide](source/user-guide/)** - Comprehensive usage guides
  - [Concepts](source/user-guide/concepts/) - Basic concepts and terminology
  - [Data Feeds](source/user-guide/data-feeds/) - Data sources and live trading
  - [Indicators](source/user-guide/indicators/) - Technical indicators
  - [Strategies](source/user-guide/strategies/) - Trading strategies
  - [Analyzers](source/user-guide/analyzers/) - Performance analysis
  - [Visualization](source/user-guide/visualization/) - Plotting and charts
- **[API Reference](source/api/)** - Detailed API documentation
- **[Advanced Topics](source/advanced/)** - Live trading, architecture, optimization

### For Developers

- **[Developer Guide](source/developer-guide/)** - Contributing and development
- **[Migration Guide](source/migration/)** - Migrating from original Backtrader

### Reference

- **[Quick Reference](source/reference/)** - Command cheat sheet
- **[Terminology Glossary](source/reference/)** - 中英文术语对照

## 🚀 Quick Links

- [Installation Guide](source/getting-started/installation.md)
- [Quickstart Tutorial](source/getting-started/quickstart.md)
- [Complete Strategy Example](source/tutorials/complete-strategy.md)
- [CCXT Live Trading](source/user-guide/data-feeds/live/ccxt-live-trading.md)
- [CTP Live Trading](source/user-guide/data-feeds/live/ctp-live-trading.md)

## 🌍 Languages

- **English** - Main documentation
- **中文** - Chinese documentation (使用 Sphinx i18n)

## 📖 Building Documentation

```bash
# Build English HTML documentation
cd docs
make html

# Build Chinese HTML documentation
make html-zh

# Build both languages
make html-all

# Live preview (English only)
make livehtml

# Clean build directory
make clean
```

The built documentation will be in `_build/html/en/` (English) and `_build/html/zh/` (Chinese).

## 🔧 Documentation Tools

Located in `../tools/`:
- `doc_coverage_scanner.py` - Check docstring coverage
- `doc_link_validator.py` - Validate documentation links
- `doc_consistency_checker.py` - Check consistency
- `docstring_enhancer.py` - Enhance docstrings

## 📂 Directory Layout

```
docs/
├── source/              # Documentation source files (Sphinx)
│   ├── getting-started/  # Quick start guides
│   ├── user-guide/       # User documentation
│   ├── api/              # API reference
│   ├── advanced/         # Advanced topics
│   ├── developer-guide/  # Developer documentation
│   ├── tutorials/        # Tutorial examples
│   ├── migration/        # Migration guides
│   ├── reference/        # Reference materials
│   ├── locales/          # i18n translation files (.po)
│   └── conf.py           # Sphinx configuration
│
├── _internal/           # Internal documentation (not published)
│   ├── opts/            # Internal optimization notes
│   └── _project/        # Project planning documents
│
├── _archive/            # Archived old documentation
├── _build/              # Build output (gitignored)
├── Makefile             # Build automation
└── README.md            # This file
```

---

**Last Updated**: 2026-03-01
**Documentation Version**: 3.0 (Reorganized)
