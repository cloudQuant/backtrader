#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reorganize docs directory structure.

This script reorganizes the messy docs directory into a clean, logical structure.
"""

import os
import shutil
from pathlib import Path


class DocsReorganizer:
    """Reorganize docs directory."""
    
    def __init__(self, docs_root='docs'):
        self.docs_root = Path(docs_root)
        self.moves = []
        self.created_dirs = []
    
    def create_new_structure(self):
        """Create new directory structure."""
        new_dirs = [
            '_project/status',
            '_project/planning',
            '_project/reports',
            '_project/guides',
            'getting-started',
            'getting-started-zh',
            'user-guide',
            'user-guide-zh',
            'api-reference',
            'advanced/live-trading',
            'advanced/architecture',
            'advanced/optimization',
            'developer-guide',
            'migration',
            'reference/optimization-docs',
            '_temp',
            '_archive',
        ]
        
        for dir_path in new_dirs:
            full_path = self.docs_root / dir_path
            if not full_path.exists():
                full_path.mkdir(parents=True, exist_ok=True)
                self.created_dirs.append(str(full_path))
                print(f"✓ Created: {dir_path}")
    
    def move_file(self, src, dest, description=""):
        """Move a file with logging."""
        src_path = self.docs_root / src
        dest_path = self.docs_root / dest
        
        if src_path.exists():
            # Create destination directory if needed
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Move file
            shutil.move(str(src_path), str(dest_path))
            self.moves.append((src, dest))
            print(f"✓ Moved: {src} → {dest}")
            if description:
                print(f"  ({description})")
            return True
        else:
            print(f"✗ Not found: {src}")
            return False
    
    def reorganize_project_docs(self):
        """Move project management documents."""
        print("\n=== Moving Project Management Docs ===")
        
        # Status
        self.move_file('PROJECT_STATUS.md', '_project/status/PROJECT_STATUS.md')
        self.move_file('RELEASE.md', '_project/status/RELEASE.md')
        self.move_file('BRANCH_COMPARISON.md', '_project/status/BRANCH_COMPARISON.md')
        
        # Planning
        self.move_file('DOCUMENTATION_TODO.md', '_project/planning/DOCUMENTATION_TODO.md')
        self.move_file('project-context.md', '_project/planning/project-context.md')
        self.move_file('project-overview.md', '_project/planning/project-overview.md')
        
        # Reports
        self.move_file('DOC_COVERAGE_REPORT.md', '_project/reports/DOC_COVERAGE_REPORT.md')
        self.move_file('LINK_VALIDATION_REPORT.md', '_project/reports/LINK_VALIDATION_REPORT.md')
        self.move_file('DOCUMENTATION_UPDATE_REPORT.md', '_project/reports/DOCUMENTATION_UPDATE_REPORT.md')
        self.move_file('TASKS_1_2_4_5_COMPLETION.md', '_project/reports/TASKS_1_2_4_5_COMPLETION.md')
        
        # Guides
        self.move_file('DOCUMENTATION_ENHANCEMENT_SUMMARY.md', '_project/guides/DOCUMENTATION_ENHANCEMENT_SUMMARY.md')
        self.move_file('API_AUTO_GENERATION_GUIDE.md', '_project/guides/API_AUTO_GENERATION_GUIDE.md')
        self.move_file('SPHINX_CONVERSION_GUIDE.md', '_project/guides/SPHINX_CONVERSION_GUIDE.md')
        self.move_file('RTD_SETUP.md', '_project/guides/RTD_SETUP.md')
        self.move_file('DOCS_REORGANIZATION_PLAN.md', '_project/guides/DOCS_REORGANIZATION_PLAN.md')
    
    def reorganize_getting_started(self):
        """Move getting started docs."""
        print("\n=== Moving Getting Started Docs ===")
        
        # From opts/getting_started
        if (self.docs_root / 'opts/getting_started').exists():
            for file in (self.docs_root / 'opts/getting_started').glob('*.md'):
                dest = f'getting-started/{file.name}'
                self.move_file(f'opts/getting_started/{file.name}', dest)
    
    def reorganize_advanced(self):
        """Move advanced topics."""
        print("\n=== Moving Advanced Topics ===")
        
        # Live trading
        self.move_file('CCXT_LIVE_TRADING_GUIDE.md', 'advanced/live-trading/ccxt-guide.md')
        self.move_file('FUNDING_RATE_GUIDE.md', 'advanced/live-trading/funding-rate.md')
        self.move_file('WEBSOCKET_GUIDE.md', 'advanced/live-trading/websocket.md')
        self.move_file('CCXT_ENV_CONFIG.md', 'advanced/live-trading/ccxt-env-config.md')
        
        # Architecture
        self.move_file('ARCHITECTURE.md', 'advanced/architecture/overview.md')
        self.move_file('multi_strategy_architecture.md', 'advanced/architecture/multi-strategy.md')
    
    def reorganize_reference(self):
        """Move reference materials."""
        print("\n=== Moving Reference Materials ===")
        
        self.move_file('TERMINOLOGY_GLOSSARY.md', 'reference/TERMINOLOGY_GLOSSARY.md')
        self.move_file('QUICK_REFERENCE.md', 'reference/QUICK_REFERENCE.md')
        self.move_file('SEARCH_SETUP_GUIDE.md', 'reference/SEARCH_SETUP_GUIDE.md')
        
        # Move opts to reference
        if (self.docs_root / 'opts/INDEX.md').exists():
            self.move_file('opts/INDEX.md', 'reference/optimization-docs/INDEX.md')
    
    def archive_old_files(self):
        """Archive old project files."""
        print("\n=== Archiving Old Files ===")
        
        archive_files = [
            'project-scan-report.json',
            'source-tree-analysis.md',
            'existing-documentation-inventory.md',
            'project-structure.md',
            'development-guide.md',
            'home.md',
            'SITE_INDEX.md',
        ]
        
        for file in archive_files:
            self.move_file(file, f'_archive/{file}')
    
    def create_readme_files(self):
        """Create README files for new directories."""
        print("\n=== Creating README Files ===")
        
        readmes = {
            '_project/README.md': """# Project Management Documentation

This directory contains project management and meta-documentation.

## Directories

- **status/** - Project status, releases, comparisons
- **planning/** - Planning documents and TODOs
- **reports/** - Generated reports (coverage, validation, etc.)
- **guides/** - Documentation guides and enhancement summaries
""",
            'getting-started/README.md': """# Getting Started

Quick start guides for new users.

## Contents

- Installation guide
- Quickstart tutorial
- Basic concepts

See also: [Tutorials](../tutorials/) for interactive Jupyter notebooks.
""",
            'user-guide/README.md': """# User Guide

Comprehensive guides for using Backtrader.

## Topics

- Data Feeds
- Strategies
- Indicators
- Analyzers
- Observers
- Plotting

See also: [API Reference](../api-reference/) for detailed API documentation.
""",
            'advanced/README.md': """# Advanced Topics

Advanced features and architecture documentation.

## Sections

- **live-trading/** - Live trading with CCXT, WebSocket, funding rates
- **architecture/** - System architecture and design
- **optimization/** - Performance optimization techniques
""",
            'developer-guide/README.md': """# Developer Guide

Documentation for contributors and developers.

## Contents

- Development setup
- Testing guide
- Contributing guidelines
- Architecture overview

See also: [Project Documentation](../_project/) for project management docs.
""",
            'reference/README.md': """# Reference Materials

Quick references and glossaries.

## Contents

- Terminology Glossary (中英文术语对照)
- Quick Reference Guide
- Search Setup Guide
- Optimization Documentation Index
""",
        }
        
        for path, content in readmes.items():
            readme_path = self.docs_root / path
            if not readme_path.exists():
                readme_path.write_text(content, encoding='utf-8')
                print(f"✓ Created: {path}")
    
    def update_main_readme(self):
        """Update main docs README."""
        print("\n=== Updating Main README ===")
        
        readme_content = """# Backtrader Documentation

Welcome to the Backtrader documentation!

## 📚 Documentation Structure

### For Users

- **[Getting Started](getting-started/)** - Installation and quickstart
- **[Tutorials](tutorials/)** - Interactive Jupyter notebooks
- **[User Guide](user-guide/)** - Comprehensive usage guides
- **[API Reference](api-reference/)** - Detailed API documentation
- **[Advanced Topics](advanced/)** - Live trading, architecture, optimization

### For Developers

- **[Developer Guide](developer-guide/)** - Contributing and development
- **[Migration Guide](migration/)** - Migrating from original Backtrader

### Reference

- **[Quick Reference](reference/QUICK_REFERENCE.md)** - Command cheat sheet
- **[Terminology Glossary](reference/TERMINOLOGY_GLOSSARY.md)** - 中英文术语对照
- **[Optimization Docs](reference/optimization-docs/)** - 204份优化文档索引

## 🚀 Quick Links

- [Installation Guide](getting-started/installation.md)
- [Quickstart Tutorial](tutorials/notebooks/01_quickstart.ipynb)
- [CCXT Live Trading](advanced/live-trading/ccxt-guide.md)
- [API Auto-Generation](_project/guides/API_AUTO_GENERATION_GUIDE.md)

## 🌍 Languages

- **English** - Main documentation
- **中文** - Chinese documentation in `*-zh/` directories

## 📖 Building Documentation

```bash
# Build HTML documentation
cd docs
make html

# Build Chinese documentation
make html SPHINXOPTS="-D language=zh_CN"

# Live preview
sphinx-autobuild source build/html
```

## 🔧 Documentation Tools

Located in `../tools/`:
- `doc_coverage_scanner.py` - Check docstring coverage
- `doc_link_validator.py` - Validate documentation links
- `doc_consistency_checker.py` - Check consistency
- `docstring_enhancer.py` - Enhance docstrings

## 📊 Project Documentation

Project management and meta-documentation is in [`_project/`](_project/).

---

**Last Updated**: 2026-03-01  
**Documentation Version**: 2.0
"""
        
        readme_path = self.docs_root / 'README.md'
        readme_path.write_text(readme_content, encoding='utf-8')
        print(f"✓ Updated: README.md")
    
    def generate_report(self):
        """Generate reorganization report."""
        print("\n" + "="*60)
        print("REORGANIZATION SUMMARY")
        print("="*60)
        print(f"\n✓ Created {len(self.created_dirs)} new directories")
        print(f"✓ Moved {len(self.moves)} files")
        print("\nNew structure created successfully!")
        print("\nNext steps:")
        print("1. Review the new structure")
        print("2. Update Sphinx conf.py if needed")
        print("3. Test documentation build")
        print("4. Update any remaining file references")
    
    def run(self):
        """Run the reorganization."""
        print("Starting docs reorganization...")
        print("="*60)
        
        self.create_new_structure()
        self.reorganize_project_docs()
        self.reorganize_getting_started()
        self.reorganize_advanced()
        self.reorganize_reference()
        self.archive_old_files()
        self.create_readme_files()
        self.update_main_readme()
        self.generate_report()


if __name__ == '__main__':
    reorganizer = DocsReorganizer()
    reorganizer.run()
