#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Deep reorganization of docs directory.

This script performs comprehensive cleanup:
1. Merges duplicate directories (api_reference, user_guide, developer_guide)
2. Reorganizes opts/ directory (202 files)
3. Cleans up source/ directory
4. Handles legacy directories
"""

import os
import shutil
from pathlib import Path
import re


class DeepDocsReorganizer:
    """Deep reorganization of docs directory."""
    
    def __init__(self, docs_root='docs'):
        self.docs_root = Path(docs_root)
        self.moves = []
        self.merges = []
        self.deletes = []
    
    def merge_directory(self, src, dest, description=""):
        """Merge source directory into destination."""
        src_path = self.docs_root / src
        dest_path = self.docs_root / dest
        
        if not src_path.exists():
            print(f"✗ Source not found: {src}")
            return False
        
        # Create destination if needed
        dest_path.mkdir(parents=True, exist_ok=True)
        
        # Move all files
        moved_count = 0
        for item in src_path.rglob('*'):
            if item.is_file():
                rel_path = item.relative_to(src_path)
                dest_file = dest_path / rel_path
                
                # Skip if already exists
                if dest_file.exists():
                    print(f"  ⊙ Skip (exists): {rel_path}")
                    continue
                
                # Create parent directory
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                
                # Move file
                shutil.move(str(item), str(dest_file))
                moved_count += 1
        
        self.merges.append((src, dest, moved_count))
        print(f"✓ Merged: {src} → {dest} ({moved_count} files)")
        if description:
            print(f"  ({description})")
        
        return True
    
    def move_file(self, src, dest, description=""):
        """Move a single file."""
        src_path = self.docs_root / src
        dest_path = self.docs_root / dest
        
        if not src_path.exists():
            return False
        
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dest_path))
        self.moves.append((src, dest))
        print(f"✓ Moved: {src} → {dest}")
        return True
    
    def remove_empty_dir(self, path):
        """Remove directory if empty."""
        dir_path = self.docs_root / path
        if dir_path.exists() and dir_path.is_dir():
            try:
                # Remove if empty or only contains .DS_Store
                items = list(dir_path.iterdir())
                if not items or (len(items) == 1 and items[0].name == '.DS_Store'):
                    shutil.rmtree(str(dir_path))
                    self.deletes.append(path)
                    print(f"✓ Removed empty: {path}")
                    return True
            except Exception as e:
                print(f"✗ Error removing {path}: {e}")
        return False
    
    def phase1_merge_api_reference(self):
        """Merge all API reference directories."""
        print("\n" + "="*60)
        print("PHASE 1: Merging API Reference Directories")
        print("="*60)
        
        # Merge api_reference → api-reference
        self.merge_directory('api_reference', 'api-reference', 
                           'Merging old api_reference')
        
        # Merge source/api → api-reference (if exists)
        self.merge_directory('source/api', 'api-reference',
                           'Merging Sphinx API docs')
        
        # Remove old directories
        self.remove_empty_dir('api_reference')
        self.remove_empty_dir('source/api')
    
    def phase2_merge_user_guide(self):
        """Merge all user guide directories."""
        print("\n" + "="*60)
        print("PHASE 2: Merging User Guide Directories")
        print("="*60)
        
        # Merge user_guide → user-guide
        self.merge_directory('user_guide', 'user-guide',
                           'Merging old user_guide')
        
        # Merge source/user_guide → user-guide
        self.merge_directory('source/user_guide', 'user-guide',
                           'Merging Sphinx user guide')
        
        # Merge opts/user_guide → user-guide (carefully)
        self.merge_directory('opts/user_guide', 'user-guide',
                           'Merging opts user guide')
        
        # Chinese user guide
        self.merge_directory('source/user_guide_zh', 'user-guide-zh',
                           'Merging Chinese user guide')
        
        # Remove old directories
        self.remove_empty_dir('user_guide')
        self.remove_empty_dir('source/user_guide')
        self.remove_empty_dir('source/user_guide_zh')
        self.remove_empty_dir('opts/user_guide')
    
    def phase3_merge_developer_guide(self):
        """Merge all developer guide directories."""
        print("\n" + "="*60)
        print("PHASE 3: Merging Developer Guide Directories")
        print("="*60)
        
        # Merge developer_guide → developer-guide
        self.merge_directory('developer_guide', 'developer-guide',
                           'Merging old developer_guide')
        
        # Merge source/dev → developer-guide
        self.merge_directory('source/dev', 'developer-guide',
                           'Merging Sphinx dev docs')
        
        # Chinese developer guide
        self.merge_directory('source/dev_zh', 'developer-guide-zh',
                           'Merging Chinese dev guide')
        
        # Remove old directories
        self.remove_empty_dir('developer_guide')
        self.remove_empty_dir('source/dev')
        self.remove_empty_dir('source/dev_zh')
    
    def phase4_reorganize_opts(self):
        """Reorganize the massive opts directory."""
        print("\n" + "="*60)
        print("PHASE 4: Reorganizing opts/ Directory (202 files)")
        print("="*60)
        
        opts_path = self.docs_root / 'opts'
        if not opts_path.exists():
            print("✗ opts directory not found")
            return
        
        # Move optimization requirements
        if (opts_path / '优化需求').exists():
            # Rename Chinese directory
            old_name = opts_path / '优化需求'
            new_name = opts_path / 'requirements'
            if old_name.exists():
                shutil.move(str(old_name), str(new_name))
                print(f"✓ Renamed: 优化需求 → requirements")
            
            # Move to reference
            self.merge_directory('opts/requirements', 
                               'reference/optimization-docs/requirements',
                               'Moving optimization requirements')
        
        # Move analysis reports to _project/reports
        report_patterns = [
            '*分析*.md', '*analysis*.md', '*report*.md', 
            '*总结*.md', '*summary*.md'
        ]
        
        for pattern in report_patterns:
            for file in opts_path.glob(pattern):
                if file.is_file():
                    dest = f'_project/reports/opts-{file.name}'
                    self.move_file(f'opts/{file.name}', dest)
        
        # Move CODE_QUALITY_GUIDE to developer-guide
        self.move_file('opts/CODE_QUALITY_GUIDE.md', 
                      'developer-guide/code-quality-guide.md')
        
        # Move LIVE_TRADING_OPTIMIZATION to advanced
        self.move_file('opts/LIVE_TRADING_OPTIMIZATION.md',
                      'advanced/optimization/live-trading.md')
        
        # Move todos to _project/planning
        if (opts_path / 'todos').exists():
            self.merge_directory('opts/todos', '_project/planning/todos',
                               'Moving todos')
        
        # Remove already moved getting_started
        self.remove_empty_dir('opts/getting_started')
    
    def phase5_merge_legacy_dirs(self):
        """Merge legacy directories."""
        print("\n" + "="*60)
        print("PHASE 5: Merging Legacy Directories")
        print("="*60)
        
        # Merge architecture
        self.merge_directory('architecture', 'advanced/architecture',
                           'Merging architecture docs')
        
        # Merge examples
        self.merge_directory('examples', 'tutorials/examples',
                           'Merging examples')
        
        # Merge strategies
        self.merge_directory('strategies', 'tutorials/examples/strategies',
                           'Merging strategies')
        
        # Handle support directory
        support_path = self.docs_root / 'support'
        if support_path.exists():
            # Check if it has content
            files = list(support_path.glob('*.md'))
            if files:
                self.merge_directory('support', 'reference/support',
                                   'Moving support docs')
            else:
                self.remove_empty_dir('support')
        
        # Remove old directories
        self.remove_empty_dir('architecture')
        self.remove_empty_dir('examples')
        self.remove_empty_dir('strategies')
    
    def phase6_cleanup_source(self):
        """Clean up source directory."""
        print("\n" + "="*60)
        print("PHASE 6: Cleaning up source/ Directory")
        print("="*60)
        
        # Merge locales/zh into locales/zh_CN
        zh_path = self.docs_root / 'source/locales/zh'
        zh_cn_path = self.docs_root / 'source/locales/zh_CN'
        
        if zh_path.exists() and zh_cn_path.exists():
            # Merge zh → zh_CN
            for item in zh_path.rglob('*'):
                if item.is_file():
                    rel_path = item.relative_to(zh_path)
                    dest_file = zh_cn_path / rel_path
                    if not dest_file.exists():
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(item), str(dest_file))
            
            # Remove zh
            shutil.rmtree(str(zh_path))
            print(f"✓ Merged: source/locales/zh → source/locales/zh_CN")
    
    def phase7_final_cleanup(self):
        """Final cleanup of empty directories."""
        print("\n" + "="*60)
        print("PHASE 7: Final Cleanup")
        print("="*60)
        
        # List of directories to check and remove if empty
        check_dirs = [
            'opts',
            'migration',
        ]
        
        for dir_name in check_dirs:
            self.remove_empty_dir(dir_name)
        
        # Remove .DS_Store files
        for ds_store in self.docs_root.rglob('.DS_Store'):
            try:
                ds_store.unlink()
                print(f"✓ Removed: {ds_store.relative_to(self.docs_root)}")
            except:
                pass
    
    def create_final_readmes(self):
        """Create/update README files."""
        print("\n" + "="*60)
        print("Creating/Updating README Files")
        print("="*60)
        
        readmes = {
            'api-reference/README.md': """# API Reference

Complete API documentation for Backtrader.

## Core Components

- **Cerebro** - Main engine
- **Strategy** - Strategy base class
- **Indicators** - Technical indicators
- **Feeds** - Data feeds
- **Brokers** - Broker interfaces
- **Analyzers** - Performance analyzers

## Usage

See individual module documentation for detailed API reference.
""",
            'user-guide/README.md': """# User Guide

Comprehensive guides for using Backtrader.

## Contents

- Data Feeds - Loading and managing data
- Strategies - Creating trading strategies
- Indicators - Using technical indicators
- Analyzers - Analyzing performance
- Observers - Monitoring execution
- Plotting - Visualizing results

## Getting Started

New to Backtrader? Start with [Getting Started](../getting-started/).
""",
            'developer-guide/README.md': """# Developer Guide

Documentation for Backtrader contributors and developers.

## Contents

- Development Setup
- Testing Guide
- Contributing Guidelines
- Code Quality Guide
- Architecture Overview

## Contributing

See [Contributing Guidelines](contributing.md) for how to contribute.
""",
        }
        
        for path, content in readmes.items():
            readme_path = self.docs_root / path
            if not readme_path.exists():
                readme_path.parent.mkdir(parents=True, exist_ok=True)
                readme_path.write_text(content, encoding='utf-8')
                print(f"✓ Created: {path}")
    
    def generate_report(self):
        """Generate final report."""
        print("\n" + "="*60)
        print("DEEP REORGANIZATION SUMMARY")
        print("="*60)
        
        print(f"\n📊 Statistics:")
        print(f"  ✓ Merged: {len(self.merges)} directory groups")
        for src, dest, count in self.merges:
            print(f"    - {src} → {dest} ({count} files)")
        
        print(f"\n  ✓ Moved: {len(self.moves)} individual files")
        
        print(f"\n  ✓ Removed: {len(self.deletes)} empty directories")
        for deleted in self.deletes:
            print(f"    - {deleted}")
        
        print("\n✨ Reorganization complete!")
        print("\nNext steps:")
        print("1. Review merged directories")
        print("2. Test Sphinx build: cd docs && make html")
        print("3. Update conf.py if needed")
        print("4. Run link validator")
        print("5. Commit changes")
    
    def run(self):
        """Run deep reorganization."""
        print("="*60)
        print("DEEP DOCS REORGANIZATION")
        print("="*60)
        print("\nThis will:")
        print("- Merge 7 groups of duplicate directories")
        print("- Reorganize 202 files in opts/")
        print("- Clean up source/ directory")
        print("- Remove empty directories")
        print("\nStarting in 3 seconds...")
        
        import time
        time.sleep(3)
        
        try:
            self.phase1_merge_api_reference()
            self.phase2_merge_user_guide()
            self.phase3_merge_developer_guide()
            self.phase4_reorganize_opts()
            self.phase5_merge_legacy_dirs()
            self.phase6_cleanup_source()
            self.phase7_final_cleanup()
            self.create_final_readmes()
            self.generate_report()
        except Exception as e:
            print(f"\n❌ Error during reorganization: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        return True


if __name__ == '__main__':
    reorganizer = DeepDocsReorganizer()
    success = reorganizer.run()
    exit(0 if success else 1)
