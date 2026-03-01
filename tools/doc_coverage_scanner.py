#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Documentation Coverage Scanner for Backtrader.

This tool scans Python modules to analyze docstring coverage and generate
reports on missing or incomplete documentation.

Usage:
    python tools/doc_coverage_scanner.py
    python tools/doc_coverage_scanner.py --module backtrader.cerebro
    python tools/doc_coverage_scanner.py --output docs/coverage_report.md
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class DocCoverageStats:
    """Statistics for documentation coverage."""
    total_modules: int = 0
    documented_modules: int = 0
    total_classes: int = 0
    documented_classes: int = 0
    total_functions: int = 0
    documented_functions: int = 0
    total_methods: int = 0
    documented_methods: int = 0
    
    @property
    def module_coverage(self) -> float:
        return (self.documented_modules / self.total_modules * 100) if self.total_modules > 0 else 0.0
    
    @property
    def class_coverage(self) -> float:
        return (self.documented_classes / self.total_classes * 100) if self.total_classes > 0 else 0.0
    
    @property
    def function_coverage(self) -> float:
        return (self.documented_functions / self.total_functions * 100) if self.total_functions > 0 else 0.0
    
    @property
    def method_coverage(self) -> float:
        return (self.documented_methods / self.total_methods * 100) if self.total_methods > 0 else 0.0
    
    @property
    def overall_coverage(self) -> float:
        total = self.total_classes + self.total_functions + self.total_methods
        documented = self.documented_classes + self.documented_functions + self.documented_methods
        return (documented / total * 100) if total > 0 else 0.0


@dataclass
class MissingDocItem:
    """Represents an item missing documentation."""
    file_path: str
    line_number: int
    item_type: str  # 'module', 'class', 'function', 'method'
    item_name: str
    parent_class: Optional[str] = None


class DocCoverageScanner:
    """Scanner for analyzing documentation coverage in Python code."""
    
    def __init__(self, root_path: str = "backtrader"):
        self.root_path = Path(root_path)
        self.stats = DocCoverageStats()
        self.missing_docs: List[MissingDocItem] = []
        self.file_stats: Dict[str, DocCoverageStats] = {}
        
        # Patterns to skip
        self.skip_patterns = [
            '__pycache__',
            '.git',
            'tests',
            'examples',
            'docs',
            'build',
            'dist',
            '*.pyc',
            '__init__.py',  # Often minimal
        ]
        
        # Private items to skip (starting with _)
        self.skip_private = True
    
    def should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        file_str = str(file_path)
        for pattern in self.skip_patterns:
            if pattern in file_str:
                return True
        return False
    
    def has_docstring(self, node: ast.AST) -> bool:
        """Check if AST node has a docstring."""
        return (
            ast.get_docstring(node) is not None and
            len(ast.get_docstring(node).strip()) > 0
        )
    
    def is_private(self, name: str) -> bool:
        """Check if name is private (starts with _)."""
        return name.startswith('_') and not name.startswith('__')
    
    def scan_file(self, file_path: Path) -> DocCoverageStats:
        """Scan a single Python file for documentation coverage."""
        file_stats = DocCoverageStats()
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content, filename=str(file_path))
            
            # Check module docstring
            file_stats.total_modules = 1
            if self.has_docstring(tree):
                file_stats.documented_modules = 1
            else:
                self.missing_docs.append(MissingDocItem(
                    file_path=str(file_path.relative_to(self.root_path.parent)),
                    line_number=1,
                    item_type='module',
                    item_name=file_path.stem
                ))
            
            # Scan classes and functions
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    if self.skip_private and self.is_private(node.name):
                        continue
                    
                    file_stats.total_classes += 1
                    if self.has_docstring(node):
                        file_stats.documented_classes += 1
                    else:
                        self.missing_docs.append(MissingDocItem(
                            file_path=str(file_path.relative_to(self.root_path.parent)),
                            line_number=node.lineno,
                            item_type='class',
                            item_name=node.name
                        ))
                    
                    # Scan methods
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            if self.skip_private and self.is_private(item.name):
                                continue
                            
                            file_stats.total_methods += 1
                            if self.has_docstring(item):
                                file_stats.documented_methods += 1
                            else:
                                self.missing_docs.append(MissingDocItem(
                                    file_path=str(file_path.relative_to(self.root_path.parent)),
                                    line_number=item.lineno,
                                    item_type='method',
                                    item_name=item.name,
                                    parent_class=node.name
                                ))
                
                elif isinstance(node, ast.FunctionDef):
                    # Only top-level functions (not methods)
                    if not any(isinstance(parent, ast.ClassDef) for parent in ast.walk(tree)):
                        if self.skip_private and self.is_private(node.name):
                            continue
                        
                        file_stats.total_functions += 1
                        if self.has_docstring(node):
                            file_stats.documented_functions += 1
                        else:
                            self.missing_docs.append(MissingDocItem(
                                file_path=str(file_path.relative_to(self.root_path.parent)),
                                line_number=node.lineno,
                                item_type='function',
                                item_name=node.name
                            ))
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}", file=sys.stderr)
        
        return file_stats
    
    def scan_directory(self) -> None:
        """Scan all Python files in the directory."""
        python_files = list(self.root_path.rglob('*.py'))
        
        for file_path in python_files:
            if self.should_skip_file(file_path):
                continue
            
            file_stats = self.scan_file(file_path)
            
            # Update global stats
            self.stats.total_modules += file_stats.total_modules
            self.stats.documented_modules += file_stats.documented_modules
            self.stats.total_classes += file_stats.total_classes
            self.stats.documented_classes += file_stats.documented_classes
            self.stats.total_functions += file_stats.total_functions
            self.stats.documented_functions += file_stats.documented_functions
            self.stats.total_methods += file_stats.total_methods
            self.stats.documented_methods += file_stats.documented_methods
            
            # Store per-file stats
            rel_path = str(file_path.relative_to(self.root_path.parent))
            self.file_stats[rel_path] = file_stats
    
    def generate_report(self, output_file: Optional[str] = None) -> str:
        """Generate coverage report in Markdown format."""
        report_lines = [
            "# Documentation Coverage Report",
            "",
            f"**Generated**: {self._get_timestamp()}",
            f"**Root Path**: `{self.root_path}`",
            "",
            "## Overall Statistics",
            "",
            "| Category | Total | Documented | Coverage |",
            "|----------|-------|------------|----------|",
            f"| Modules | {self.stats.total_modules} | {self.stats.documented_modules} | {self.stats.module_coverage:.1f}% |",
            f"| Classes | {self.stats.total_classes} | {self.stats.documented_classes} | {self.stats.class_coverage:.1f}% |",
            f"| Functions | {self.stats.total_functions} | {self.stats.documented_functions} | {self.stats.function_coverage:.1f}% |",
            f"| Methods | {self.stats.total_methods} | {self.stats.documented_methods} | {self.stats.method_coverage:.1f}% |",
            f"| **Overall** | **{self.stats.total_classes + self.stats.total_functions + self.stats.total_methods}** | **{self.stats.documented_classes + self.stats.documented_functions + self.stats.documented_methods}** | **{self.stats.overall_coverage:.1f}%** |",
            "",
        ]
        
        # Coverage visualization
        report_lines.extend([
            "## Coverage Visualization",
            "",
            self._generate_progress_bar("Modules", self.stats.module_coverage),
            self._generate_progress_bar("Classes", self.stats.class_coverage),
            self._generate_progress_bar("Functions", self.stats.function_coverage),
            self._generate_progress_bar("Methods", self.stats.method_coverage),
            self._generate_progress_bar("Overall", self.stats.overall_coverage),
            "",
        ])
        
        # Missing documentation by type
        missing_by_type = defaultdict(list)
        for item in self.missing_docs:
            missing_by_type[item.item_type].append(item)
        
        report_lines.extend([
            "## Missing Documentation",
            "",
            f"**Total Missing**: {len(self.missing_docs)} items",
            "",
        ])
        
        for item_type in ['module', 'class', 'function', 'method']:
            if item_type in missing_by_type:
                items = missing_by_type[item_type]
                report_lines.extend([
                    f"### Missing {item_type.title()} Docstrings ({len(items)})",
                    "",
                    "| File | Line | Name | Parent Class |",
                    "|------|------|------|--------------|",
                ])
                
                for item in sorted(items, key=lambda x: (x.file_path, x.line_number)):
                    parent = item.parent_class or "-"
                    report_lines.append(
                        f"| `{item.file_path}` | {item.line_number} | `{item.item_name}` | {parent} |"
                    )
                
                report_lines.append("")
        
        # Top files needing documentation
        report_lines.extend([
            "## Files Needing Most Documentation",
            "",
            "| File | Classes Missing | Methods Missing | Functions Missing | Total Missing |",
            "|------|-----------------|-----------------|-------------------|---------------|",
        ])
        
        file_missing_counts = defaultdict(lambda: {'class': 0, 'method': 0, 'function': 0})
        for item in self.missing_docs:
            file_missing_counts[item.file_path][item.item_type] += 1
        
        sorted_files = sorted(
            file_missing_counts.items(),
            key=lambda x: sum(x[1].values()),
            reverse=True
        )[:20]  # Top 20 files
        
        for file_path, counts in sorted_files:
            total = sum(counts.values())
            report_lines.append(
                f"| `{file_path}` | {counts['class']} | {counts['method']} | {counts['function']} | **{total}** |"
            )
        
        report_lines.extend([
            "",
            "## Recommendations",
            "",
            "1. **Priority 1**: Add module docstrings to all files",
            "2. **Priority 2**: Document all public classes",
            "3. **Priority 3**: Document public methods and functions",
            "4. **Priority 4**: Add type hints to improve IDE support",
            "",
            "## Next Steps",
            "",
            "- Run `python tools/doc_coverage_scanner.py --fix` to generate docstring templates",
            "- Use Google-style docstrings for consistency",
            "- Include examples in docstrings where appropriate",
            "- Add type hints alongside docstrings",
            "",
        ])
        
        report = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"Report saved to: {output_file}")
        
        return report
    
    def _generate_progress_bar(self, label: str, percentage: float, width: int = 30) -> str:
        """Generate a text-based progress bar."""
        filled = int(width * percentage / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f"**{label}**: {bar} {percentage:.1f}%"
    
    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Scan documentation coverage in Backtrader")
    parser.add_argument(
        '--root',
        default='backtrader',
        help='Root directory to scan (default: backtrader)'
    )
    parser.add_argument(
        '--output',
        '-o',
        help='Output file for report (default: print to stdout)'
    )
    parser.add_argument(
        '--include-private',
        action='store_true',
        help='Include private members (starting with _)'
    )
    
    args = parser.parse_args()
    
    scanner = DocCoverageScanner(root_path=args.root)
    scanner.skip_private = not args.include_private
    
    print(f"Scanning {args.root}...")
    scanner.scan_directory()
    
    print(f"\nFound {len(scanner.missing_docs)} items missing documentation")
    print(f"Overall coverage: {scanner.stats.overall_coverage:.1f}%\n")
    
    report = scanner.generate_report(output_file=args.output)
    
    if not args.output:
        print(report)


if __name__ == '__main__':
    main()
